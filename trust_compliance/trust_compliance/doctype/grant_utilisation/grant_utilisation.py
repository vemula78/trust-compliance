"""Recognise a restricted grant's liability as income, as it is spent.

The counterpart to `Trust Donation.is_grant`: that document defers a grant into
the grant liability account instead of income; this document later moves
exactly the amount utilised from that liability into donation income, so the
year's income reflects what was actually spent, not what was merely received
with a condition attached.

Posts one balanced Journal Entry - debit the grant liability account, credit
donation income, both legs tagged to the fund - so the trial balance moves but
net assets of the fund do not: recognising income out of a liability the fund
already holds is not a fresh inflow to the fund.

All arithmetic is `core.grant`, unit-tested outside a bench.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from trust_compliance.core.grant import round_money, validate_grant_utilisation
from trust_compliance.trust_compliance.doctype.trust_compliance_settings.trust_compliance_settings import (
    get_company_accounts,
)


class GrantUtilisation(Document):
    # -- lifecycle ------------------------------------------------------------

    def validate(self):
        self._validate_fund()
        self.outstanding_balance = self._outstanding_balance()
        errors = validate_grant_utilisation(flt(self.amount), self.outstanding_balance)
        if errors:
            frappe.throw("<br>".join(_(error) for error in errors))

    def on_submit(self):
        self.journal_entry = self._post_journal_entry()
        self.db_set("journal_entry", self.journal_entry, update_modified=False)

    def on_cancel(self):
        self.flags.ignore_links = True
        if self.journal_entry:
            entry = frappe.get_doc("Journal Entry", self.journal_entry)
            if entry.docstatus == 1:
                entry.flags.ignore_permissions = True
                entry.cancel()

    # -- validation -----------------------------------------------------------

    def _validate_fund(self):
        fund = self._fund()
        if fund.company != self.company:
            frappe.throw(
                _("Fund {0} belongs to company {1}, not {2}.").format(
                    self.fund, fund.company, self.company
                )
            )
        if fund.disabled:
            frappe.throw(_("Fund {0} is disabled.").format(self.fund))
        if fund.fund_class != "Restricted":
            frappe.throw(
                _(
                    "Fund {0} is {1} class. A grant can only be recognised on a "
                    "Restricted fund - only a Restricted fund receives a grant "
                    "donation in the first place."
                ).format(self.fund, _(fund.fund_class))
            )

    def _outstanding_balance(self) -> float:
        """The fund's grant liability balance right now, row-locked.

        `SELECT ... FOR UPDATE` over the matching GL Entry rows serialises two
        clerks recognising against the same fund at the same moment, the same
        protection `Investment Transaction` takes over an instrument's book
        value - without it, both would validate against the same opening
        balance and the second submit would recognise more income than the fund
        had actually received.
        """
        account = get_company_accounts(self.company).get("grant_liability_account")
        if not account:
            frappe.throw(
                _(
                    "No grant liability account is configured for {0}. Add it to "
                    "Trust Compliance Settings before recognising a grant."
                ).format(self.company),
                title=_("Setup Incomplete"),
            )
        row = frappe.db.sql(
            """
            SELECT SUM(credit) - SUM(debit) AS balance
            FROM `tabGL Entry`
            WHERE account = %s AND fund = %s AND company = %s AND is_cancelled = 0
            FOR UPDATE
            """,
            (account, self.fund, self.company),
            as_dict=True,
        )
        return round_money(flt(row[0].balance if row else 0))

    # -- GL posting -------------------------------------------------------------

    def _post_journal_entry(self) -> str:
        accounts = get_company_accounts(self.company)
        liability_account = accounts.get("grant_liability_account")
        income_account = accounts.get("donation_income_account")

        entry = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Journal Entry",
                "company": self.company,
                "posting_date": self.utilisation_date,
                "user_remark": _("Grant utilisation {0} on fund {1}{2}").format(
                    self.name,
                    self.fund,
                    f" - {self.purpose}" if self.purpose else "",
                ),
                "accounts": [
                    {
                        "account": liability_account,
                        "debit_in_account_currency": flt(self.amount),
                        "fund": self.fund,
                    },
                    {
                        "account": income_account,
                        "credit_in_account_currency": flt(self.amount),
                        "fund": self.fund,
                    },
                ],
            }
        )
        entry.flags.ignore_permissions = True
        entry.insert()
        entry.submit()
        return entry.name

    # -- helpers ----------------------------------------------------------------

    def _fund(self) -> dict:
        if not hasattr(self, "_fund_cache"):
            self._fund_cache = frappe.db.get_value(
                "Fund",
                self.fund,
                ["name", "fund_class", "is_fcra", "is_default", "company", "disabled"],
                as_dict=True,
            )
            if not self._fund_cache:
                frappe.throw(_("Fund {0} does not exist.").format(self.fund))
        return self._fund_cache

"""Inter-fund transfer.

Posts one balanced Journal Entry with **both legs on the same equity clearing
account** - debit tagged to the source fund, credit to the destination. The
account therefore always nets to zero, so the trial balance and the balance sheet
are untouched and the entire movement is carried by the fund dimension. That is
what makes a fund transfer a reallocation of net assets rather than income in one
fund and expenditure in another.

The source leg being an equity *debit* is why `build_fund_balances` classifies by
the direction of net movement rather than by account type: it is what makes the
source fund actually decrease.

Approval: `Accounts User` may create and edit a draft but cannot submit;
`Accounts Manager` submits. A transfer therefore always passes through a second
pair of hands. For a multi-step approval, install the optional Workflow with
`trust_compliance.setup.workflow.create_fund_transfer_workflow()`.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from trust_compliance.core.segregation import validate_corpus_outflow, validate_fund_segregation
from trust_compliance.trust_compliance.doctype.trust_compliance_settings.trust_compliance_settings import (
    get_company_accounts,
)
from trust_compliance.trust_compliance.doctype.trust_donation.trust_donation import (
    amount_in_words,
)


class FundTransfer(Document):
    def validate(self):
        self._validate_amount()
        self._validate_funds_differ()
        self._validate_funds_belong_to_company()
        self._validate_corpus_is_one_way()
        self._validate_segregation()
        self.amount_in_words = amount_in_words(self.amount, self._currency())

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

    # -- validation ---------------------------------------------------------

    def _validate_amount(self):
        if flt(self.amount) <= 0:
            frappe.throw(_("Transfer amount must be greater than zero."))

    def _validate_funds_differ(self):
        if self.from_fund == self.to_fund:
            frappe.throw(_("A fund cannot be transferred to itself."))

    def _validate_funds_belong_to_company(self):
        for fieldname in ("from_fund", "to_fund"):
            fund = self._fund(fieldname)
            if fund.company != self.company:
                frappe.throw(
                    _("Fund {0} belongs to company {1}, not {2}.").format(
                        fund.name, fund.company, self.company
                    )
                )
            if fund.disabled:
                frappe.throw(_("Fund {0} is disabled.").format(fund.name))

    def _validate_corpus_is_one_way(self):
        """Corpus may receive a transfer but never make one.

        Section 11(1)(d) corpus is capital held on the donor's direction. Moving
        it into a spendable fund would convert capital into income of the year and
        defeat the direction, so it is refused outright rather than warned about.
        """
        errors = validate_corpus_outflow(
            self._fund("from_fund"), self._fund("to_fund")
        )
        if errors:
            frappe.throw("<br>".join(_(error) for error in errors), title=_("Corpus"))

    def _validate_segregation(self):
        """FCRA and domestic funds cannot be mixed, in either direction.

        A transfer is the one operation that would otherwise launder foreign
        contribution into domestic money - or the reverse - without any account
        changing, because both legs sit on the same clearing account. The generic
        segregation rule is applied to the two legs as they will be posted, so the
        transfer is refused with the same message a manual journal would give.
        """
        lines = [{"fund": self.from_fund}, {"fund": self.to_fund}]
        funds = frappe.get_all(
            "Fund",
            filters={"company": self.company},
            fields=["name", "fund_name", "fund_class", "is_default", "is_fcra"],
        )
        errors = validate_fund_segregation(lines, funds)
        if errors:
            frappe.throw(
                "<br>".join(_(error) for error in errors), title=_("FCRA Segregation")
            )

    # -- GL posting ---------------------------------------------------------

    def _post_journal_entry(self) -> str:
        accounts = get_company_accounts(self.company)
        clearing = accounts.get("inter_fund_transfer_account")
        if not clearing:
            frappe.throw(
                _(
                    "No inter-fund transfer account is configured for {0}. Set an "
                    "Equity clearing account in Trust Compliance Settings - both legs "
                    "of a transfer post to it, so the trial balance stays untouched."
                ).format(self.company),
                title=_("Setup Incomplete"),
            )

        entry = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Journal Entry",
                "company": self.company,
                "posting_date": self.transfer_date,
                "user_remark": _("Fund transfer {0}: {1} to {2} - {3}").format(
                    self.name, self.from_fund, self.to_fund, self.reason
                ),
                "accounts": [
                    {
                        "account": clearing,
                        "debit_in_account_currency": flt(self.amount),
                        "fund": self.from_fund,
                    },
                    {
                        "account": clearing,
                        "credit_in_account_currency": flt(self.amount),
                        "fund": self.to_fund,
                    },
                ],
            }
        )
        entry.flags.ignore_permissions = True
        entry.insert()
        entry.submit()
        return entry.name

    # -- helpers ------------------------------------------------------------

    def _fund(self, fieldname: str) -> dict:
        cache = self.__dict__.setdefault("_fund_cache", {})
        fund_name = self.get(fieldname)
        if fund_name not in cache:
            fund = frappe.db.get_value(
                "Fund",
                fund_name,
                ["name", "fund_class", "is_fcra", "is_default", "company", "disabled"],
                as_dict=True,
            )
            if not fund:
                frappe.throw(_("Fund {0} does not exist.").format(fund_name))
            cache[fund_name] = fund
        return cache[fund_name]

    def _currency(self) -> str:
        return frappe.get_cached_value("Company", self.company, "default_currency")

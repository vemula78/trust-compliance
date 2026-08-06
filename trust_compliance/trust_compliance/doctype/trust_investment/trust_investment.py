"""An instrument the Trust holds, and the section 11(5) clause that permits it.

Every rule lives in `trust_compliance.core.investment`; this controller reads
records, hands plain mappings to the core, and turns the returned strings into
`frappe.throw`. Nothing statutory is re-implemented here.

Three things make this record more than a fixed-asset row:

- **The permitted mode is a field, not a note.** A 12A/12AB trust may invest only
  in the modes listed in section 11(5) and extended by Rule 17C. Investment
  outside them makes that income taxable at 30% under section 115BBI, so the
  clause is validated at the point the instrument is bought.
- **One fund per instrument.** The fund is single-valued on purpose. A fixed
  deposit bought out of a bank balance that holds mixed FCRA and domestic money,
  or mixed corpus and unrestricted money, cannot be reported in FC-4 and cannot be
  shown at audit as separately identifiable corpus. Co-funding is therefore made
  impossible rather than merely discouraged, and a trust that wants two funds in
  one bank product buys two instruments.
- **Corpus identification.** Since the Finance Act 2021 corpus retains its
  section 11(1)(d) exemption only if it is held in an 11(5) mode *and* remains
  separately identifiable. The fund dimension on both legs of the purchase entry
  is what makes it identifiable in the ledger.

On submit one balanced Journal Entry debits the investment account and credits the
funding bank - the FCRA-designated account when the fund is an FCRA fund, because
foreign contribution may only move through that account.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from trust_compliance.core.investment import validate_investment_mode
from trust_compliance.trust_compliance.doctype.trust_compliance_settings.trust_compliance_settings import (
    get_company_accounts,
)

#: The one instrument type that is an equity holding. Most 11(5) clauses are
#: deposit or debt modes and do not admit equity at all, so the core rule needs to
#: know whether this instrument is equity; it is derived from the type rather than
#: asked for twice, so the two can never disagree.
EQUITY_INSTRUMENT_TYPES = frozenset({"Equity Shares"})


class TrustInvestment(Document):
    # -- lifecycle ----------------------------------------------------------

    def validate(self):
        self._validate_cost()
        self._validate_fund_belongs_to_company()
        self._derive_is_corpus()
        self._validate_dates()
        self._validate_investment_account()
        self._validate_permitted_mode()

    def on_submit(self):
        self.db_set("book_value", flt(self.cost), update_modified=False)
        self.db_set("status", "Active", update_modified=False)
        journal_entry = self._post_journal_entry()
        self.db_set("journal_entry", journal_entry, update_modified=False)

    def on_cancel(self):
        self.flags.ignore_links = True
        if self.journal_entry:
            entry = frappe.get_doc("Journal Entry", self.journal_entry)
            if entry.docstatus == 1:
                entry.flags.ignore_permissions = True
                entry.cancel()
        self.db_set("book_value", 0, update_modified=False)

    # -- validation ---------------------------------------------------------

    def _validate_cost(self):
        if flt(self.cost) <= 0:
            frappe.throw(_("Cost of the investment must be greater than zero."))

    def _validate_fund_belongs_to_company(self):
        fund = self._fund()
        if fund.company != self.company:
            frappe.throw(
                _("Fund {0} belongs to company {1}, not {2}.").format(
                    fund.name, fund.company, self.company
                )
            )
        if fund.disabled:
            frappe.throw(_("Fund {0} is disabled.").format(fund.name))

        # Mirrored onto the record so reports and the FC-4 investment schedule do
        # not have to join back to Fund for the two flags they filter on.
        self.fund_class = fund.fund_class
        self.is_fcra = 1 if fund.is_fcra else 0

    def _derive_is_corpus(self):
        """Corpus-ness is derived from the funding fund, never entered.

        An instrument bought with corpus money is a corpus holding and one bought
        with spendable money is not - there is no third case and no case where the
        two disagree. So this is computed rather than validated: an earlier version
        auto-filled the flag and then refused a mismatch, which made the refusal
        unreachable, because the auto-fill had already corrected the value the check
        was looking for. Deriving removes the state and the dead branch together.

        It matters because corpus keeps its section 11(1)(d) exemption only while it
        stays separately identifiable, so the corpus schedule must neither omit a
        holding nor claim one the Trust does not have.
        """
        self.is_corpus = 1 if self._fund().fund_class == "Corpus" else 0

    def _validate_dates(self):
        if self.maturity_date and self.purchase_date:
            if getdate(self.maturity_date) < getdate(self.purchase_date):
                frappe.throw(_("Maturity Date cannot be before Purchase Date."))

    def _validate_investment_account(self):
        """The holding must sit in a real Asset account of this company.

        A group account cannot be posted to, and an investment carried anywhere
        other than under Assets would leave the balance sheet showing the Trust's
        11(5) holdings as something else - which is exactly the schedule an
        assessing officer reads.
        """
        details = frappe.db.get_value(
            "Account",
            self.investment_account,
            ["name", "company", "root_type", "is_group", "is_fcra"],
            as_dict=True,
        )
        if not details:
            frappe.throw(
                _("Account {0} does not exist.").format(self.investment_account)
            )
        if details.company != self.company:
            frappe.throw(
                _("Account {0} belongs to {1}, not to {2}.").format(
                    details.name, details.company, self.company
                )
            )
        if details.is_group:
            frappe.throw(
                _("Account {0} is a group account and cannot be posted to.").format(
                    details.name
                )
            )
        if details.root_type != "Asset":
            frappe.throw(
                _(
                    "Account {0} is a {1} account. An investment is an asset of the "
                    "Trust and must be carried in an Asset account."
                ).format(details.name, _(details.root_type))
            )

    def _validate_permitted_mode(self):
        """Section 11(5) / Rule 17C, plus the section 13(3) prohibited-party check."""
        mode = frappe.db.get_value(
            "Investment Mode", self.mode, ["name", "clause", "disabled"], as_dict=True
        )
        if not mode:
            frappe.throw(_("Investment Mode {0} does not exist.").format(self.mode))
        if mode.disabled:
            frappe.throw(
                _(
                    "Investment Mode {0} is disabled - the clause has been withdrawn, so "
                    "a new investment cannot be made under it."
                ).format(mode.name),
                title=_("Section 11(5)"),
            )

        fund = self._fund()
        investment = {
            "instrument_type": self.instrument_type,
            "mode_clause": mode.clause,
            "is_equity": self.instrument_type in EQUITY_INSTRUMENT_TYPES,
            "issuer": self.issuer,
            "issuer_is_psu": bool(self.issuer_is_psu),
            "counterparty": self.counterparty,
            "amount": flt(self.cost),
        }
        errors = validate_investment_mode(
            investment,
            {
                "name": fund.name,
                "fund_class": fund.fund_class,
                "is_fcra": bool(fund.is_fcra),
            },
            get_prohibited_parties(self.company),
        )
        if errors:
            frappe.throw(
                "<br>".join(_(error) for error in errors), title=_("Section 11(5)")
            )

    # -- GL posting ---------------------------------------------------------

    def _post_journal_entry(self) -> str:
        """Debit the investment account, credit the bank the money left.

        Both legs carry the fund, and the fund is set at parent level as well. The
        parent value is what ERPNext falls back to for any leg that is not written
        from an item row, and the dimension is mandatory for balance-sheet
        accounts - both legs here are balance-sheet accounts, so neither can be
        left untagged.

        The bank is the FCRA-designated account when the fund is an FCRA fund.
        Foreign contribution may only move through that account, so an FCRA
        investment cannot be bought out of the domestic bank even by mistake.
        """
        accounts = get_company_accounts(self.company)
        bank_key = "fcra_bank_account" if self.is_fcra else "bank_account"
        bank_account = accounts.get(bank_key)
        if not bank_account:
            frappe.throw(
                _(
                    "No {0} is configured for {1}. Set it in Trust Compliance Settings; "
                    "the account the money left cannot be guessed."
                ).format(_(bank_key.replace("_", " ").title()), self.company),
                title=_("Setup Incomplete"),
            )

        entry = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Journal Entry",
                "company": self.company,
                "posting_date": self.purchase_date,
                "user_remark": _("Investment {0}: {1} under {2}, funded by {3}").format(
                    self.name, self.investment_name, self.mode, self.fund
                ),
                # See the docstring: the parent fund carries the dimension for any
                # leg not written from an item row.
                "fund": self.fund,
                "accounts": [
                    {
                        "account": self.investment_account,
                        "debit_in_account_currency": flt(self.cost),
                        "fund": self.fund,
                    },
                    {
                        "account": bank_account,
                        "credit_in_account_currency": flt(self.cost),
                        "fund": self.fund,
                    },
                ],
            }
        )
        entry.flags.ignore_permissions = True
        entry.insert()
        entry.submit()
        return entry.name

    # -- helpers ------------------------------------------------------------

    def _fund(self):
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


def get_prohibited_parties(company: str) -> list[str]:
    """Persons the Trust may not invest with under sections 13(2)(h) and 13(3).

    **This check is currently inert and returns an empty list.** It is wired
    through to `validate_investment_mode` so the rule is exercised end to end, but
    it can never fire, because Trust Donor has no field that marks a donor as an
    interested person under section 13(3).

    TODO: add an `is_prohibited_person` check field to Trust Donor - author,
    trustee, manager, substantial contributor, their relatives, and any concern in
    which they have a substantial interest - and return those donor names here.
    Trust Donor is outside this change's scope, so the field is not being added
    now; until it exists, investing in a prohibited concern will pass validation
    silently and must be caught by the trustees, not by this app. Do not read this
    function's presence as evidence that the 13(3) check is live.
    """
    return []

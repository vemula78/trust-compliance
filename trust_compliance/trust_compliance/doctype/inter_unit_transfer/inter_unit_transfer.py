"""A grant of money from one unit of the Trust to another.

The Trust funds hospitals and schools that keep their own books and file their own
returns, so one transfer is two accounting facts, not one:

    Paying unit:    Debit  Transfers to Institutions   Credit  Bank
    Receiving unit: Debit  Bank                        Credit  Grants Received

Both entries are posted here, in one request, so the two can never exist
separately - Frappe rolls the whole request back if the second leg fails, and the
second leg is posted before the first is committed. A transfer existing in one
unit's books only would misstate both units and could not be found again.

Both legs are flagged `is_inter_unit` and name the other unit in
`counterparty_company`. That flag is what the Inter-Unit Eliminations report
reads: at group level the expense and the grant income are the same money seen
twice. The flag lives on the Journal Entry, not only here, because a consolidation
reads the ledger.

Three refusals, all in `core.inter_unit`: corpus cannot be paid out, foreign
contribution cannot be transferred to another person at all (FCRA section 7 as
amended in 2020), and a grant cannot be received into a Corpus fund because
corpus arises only from a donation given with that direction.

Approval mirrors Fund Transfer: `Accounts User` drafts, `Accounts Manager`
submits. In addition the submitter must be permitted on *both* companies - the
transfer writes to the receiving unit's ledger, and authority over one unit is not
authority over another.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from trust_compliance.core.inter_unit import validate_inter_unit_transfer
from trust_compliance.trust_compliance.doctype.trust_compliance_settings.trust_compliance_settings import (
    get_company_accounts,
)
from trust_compliance.trust_compliance.doctype.trust_donation.trust_donation import (
    amount_in_words,
)


class InterUnitTransfer(Document):
    # -- lifecycle ----------------------------------------------------------

    def validate(self):
        self._validate_funds_belong_to_their_units()
        self._validate_rules()
        self._validate_program()
        self.amount_in_words = amount_in_words(self.amount, self._currency())

    def before_submit(self):
        self._require_permission_on_both_units()

    def on_submit(self):
        from_entry = self._post_paying_leg()
        to_entry = self._post_receiving_leg()
        self.db_set("from_journal_entry", from_entry, update_modified=False)
        self.db_set("to_journal_entry", to_entry, update_modified=False)

    def on_cancel(self):
        """Cancel both legs, or neither.

        Cancelling one leg alone would leave the group's expense and grant income
        unequal, which is the one state the elimination cannot be applied to - the
        report reconciles the two sides and would report the difference as
        unbalanced. Both are cancelled in this one request, so a failure on the
        second rolls the first back.
        """
        self.flags.ignore_links = True
        for fieldname in ("from_journal_entry", "to_journal_entry"):
            name = self.get(fieldname)
            if not name:
                continue
            entry = frappe.get_doc("Journal Entry", name)
            if entry.docstatus == 1:
                entry.flags.ignore_permissions = True
                entry.cancel()

    # -- validation ---------------------------------------------------------

    def _validate_funds_belong_to_their_units(self):
        for fund_field, company_field in (
            ("from_fund", "from_company"),
            ("to_fund", "to_company"),
        ):
            fund = self._fund(fund_field)
            company = self.get(company_field)
            if fund.company != company:
                frappe.throw(
                    _(
                        "Fund {0} belongs to {1}, not to {2}. Each unit keeps its own "
                        "fund master, and a transfer moves money between two of them."
                    ).format(fund.name, fund.company, company)
                )
            if fund.disabled:
                frappe.throw(_("Fund {0} is disabled.").format(fund.name))

    def _validate_rules(self):
        errors = validate_inter_unit_transfer(
            {
                "from_company": self.from_company,
                "to_company": self.to_company,
                "amount": flt(self.amount),
            },
            self._fund("from_fund"),
            self._fund("to_fund"),
        )
        if errors:
            frappe.throw(
                "<br>".join(_(error) for error in errors),
                title=_("Inter-Unit Transfer"),
            )

    def _validate_program(self):
        """The program must belong to the receiving unit.

        Utilisation is measured where the money is spent, and that is the receiving
        unit - so the program dimension goes on the receiving leg, tagging the grant
        income to the program its Program Utilisation report measures against.

        It is deliberately *not* put on the paying leg. An ERPNext Project belongs
        to one company; the receiving unit's project id on the Trust's own GL rows
        would appear on the Trust's schedule as a program the Trust does not have,
        which is precisely the case `build_program_utilisation` treats as untagged.
        The Trust's side of the transfer is a transfer to an institution, not
        program expenditure of the Trust.
        """
        if not self.program:
            return
        company = frappe.db.get_value("Project", self.program, "company")
        if company and company != self.to_company:
            frappe.throw(
                _(
                    "Program {0} belongs to {1}, not to the receiving unit {2}. "
                    "Utilisation is measured in the unit that spends the money."
                ).format(self.program, company, self.to_company)
            )

    def _require_permission_on_both_units(self):
        """Authority over the paying unit is not authority over the receiving one.

        This writes a posted entry into the receiving unit's ledger, so the
        submitter has to be permitted there too. Checked against Company, because
        that is what a User Permission restricts a user to.
        """
        for company in (self.from_company, self.to_company):
            if not frappe.has_permission(
                "Company", ptype="read", doc=company, throw=False
            ):
                frappe.throw(
                    _(
                        "You are not permitted on {0}. An inter-unit transfer posts "
                        "to both units' ledgers, so it needs permission on both."
                    ).format(company),
                    frappe.PermissionError,
                )

    # -- GL posting ---------------------------------------------------------

    def _post_paying_leg(self) -> str:
        accounts = self._accounts(self.from_company)
        expense = self._require(
            accounts, "institution_transfer_account", self.from_company, "Expense"
        )
        bank = self._require(accounts, "bank_account", self.from_company)
        return self._post(
            company=self.from_company,
            counterparty=self.to_company,
            fund=self.from_fund,
            remark=_("Inter-unit transfer {0} to {1} - {2}").format(
                self.name, self.to_company, self.purpose
            ),
            debit_account=expense,
            credit_account=bank,
            program=None,
        )

    def _post_receiving_leg(self) -> str:
        accounts = self._accounts(self.to_company)
        income = self._require(
            accounts, "grant_income_account", self.to_company, "Income"
        )
        bank = self._require(accounts, "bank_account", self.to_company)
        return self._post(
            company=self.to_company,
            counterparty=self.from_company,
            fund=self.to_fund,
            remark=_("Inter-unit grant {0} from {1} - {2}").format(
                self.name, self.from_company, self.purpose
            ),
            debit_account=bank,
            credit_account=income,
            program=self.program,
        )

    def _post(self, company, counterparty, fund, remark, debit_account,
              credit_account, program) -> str:
        """One unit's leg. The fund is set on the parent as well as both lines.

        ERPNext takes a leg's accounting dimension from the parent whenever the
        leg is not written from an item row, and the fund dimension is mandatory
        for balance-sheet accounts - the bank leg is one - so the parent value
        cannot be left off.
        """
        entry = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Journal Entry",
                "company": company,
                "posting_date": self.transfer_date,
                "user_remark": remark,
                "is_inter_unit": 1,
                "counterparty_company": counterparty,
                "fund": fund,
                "project": program,
                "accounts": [
                    {
                        "account": debit_account,
                        "debit_in_account_currency": flt(self.amount),
                        "fund": fund,
                        "project": program,
                    },
                    {
                        "account": credit_account,
                        "credit_in_account_currency": flt(self.amount),
                        "fund": fund,
                        "project": program,
                    },
                ],
            }
        )
        entry.flags.ignore_permissions = True
        entry.insert()
        entry.submit()
        return entry.name

    # -- helpers ------------------------------------------------------------

    def _accounts(self, company: str) -> dict:
        cache = self.__dict__.setdefault("_accounts_cache", {})
        if company not in cache:
            cache[company] = get_company_accounts(company)
        return cache[company]

    def _require(self, accounts: dict, key: str, company: str,
                 root_type: str | None = None) -> str:
        account = accounts.get(key)
        if not account:
            frappe.throw(
                _(
                    "No {0} is configured for {1}. Set it in Trust Compliance "
                    "Settings; the account cannot be guessed from a chart the Trust "
                    "owns."
                ).format(_(key.replace("_", " ").title()), company),
                title=_("Setup Incomplete"),
            )
        if root_type:
            actual = frappe.db.get_value("Account", account, "root_type")
            if actual != root_type:
                frappe.throw(
                    _(
                        "Account {0} configured as {1} for {2} is a {3} account, not "
                        "{4}. The two legs of a transfer are eliminated against each "
                        "other on consolidation, which only works if one is expense "
                        "and the other income."
                    ).format(account, _(key.replace("_", " ").title()), company,
                             _(actual), _(root_type)),
                    title=_("Setup Incomplete"),
                )
        return account

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
        return frappe.get_cached_value("Company", self.from_company, "default_currency")

"""Donation receipting with 80G numbering and automatic GL posting.

On submit a donation allocates its receipt number and posts one balanced Journal
Entry, fund-tagged on both legs. On cancel the Journal Entry is cancelled with
it; the receipt number is *not* released, because a number that has been printed
and handed to a donor may never be re-issued to somebody else.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, fmt_money

from trust_compliance.core.financial_year import financial_year_of, next_receipt_no
from trust_compliance.trust_compliance.doctype.trust_compliance_settings.trust_compliance_settings import (
    get_company_accounts,
)

#: Modes that settle into a bank-type account rather than cash.
BANK_MODES = frozenset({"Bank", "UPI", "Cheque"})


class TrustDonation(Document):
    # -- lifecycle ----------------------------------------------------------

    def validate(self):
        self._validate_amount()
        self._sync_donor_fields()
        self._validate_fund()
        self._validate_foreign_contribution()
        self._validate_corpus()
        self._validate_cash_limits()
        self._validate_pan_requirement()
        self.financial_year = financial_year_of(self.donation_date)

    def before_submit(self):
        self.receipt_no = self._allocate_receipt_no()

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
            frappe.throw(_("Donation amount must be greater than zero."))

    def _sync_donor_fields(self):
        donor = frappe.db.get_value(
            "Trust Donor",
            self.donor,
            ["donor_name", "donor_type", "is_anonymous", "pan", "company", "disabled"],
            as_dict=True,
        )
        if donor.disabled:
            frappe.throw(_("Donor {0} is disabled.").format(self.donor_name or self.donor))
        if donor.company != self.company:
            frappe.throw(
                _("Donor {0} belongs to company {1}, not {2}.").format(
                    self.donor, donor.company, self.company
                )
            )
        self.donor_name = donor.donor_name
        self.donor_type = donor.donor_type
        self.is_anonymous = donor.is_anonymous

    def _validate_fund(self):
        fund = self._fund()
        if fund.disabled:
            frappe.throw(_("Fund {0} is disabled.").format(self.fund))
        if fund.company != self.company:
            frappe.throw(
                _("Fund {0} belongs to company {1}, not {2}.").format(
                    self.fund, fund.company, self.company
                )
            )

    def _validate_foreign_contribution(self):
        """FCRA rules for a foreign donor.

        A foreign contribution may only be credited to an FCRA fund, may only be
        banked into the designated FCRA account, and may never be received in
        cash - FCRA requires it to arrive through the designated bank account.
        In-kind foreign contribution is permitted (donated equipment), which is
        why the cash rule is written against the mode and not against "not bank".
        """
        fund = self._fund()

        if self.donor_type == "Foreign":
            if not fund.is_fcra:
                frappe.throw(
                    _(
                        "Donor {0} is a foreign donor, so the donation must go to an "
                        "FCRA fund. {1} is a domestic fund."
                    ).format(self.donor_name, self.fund),
                    title=_("FCRA Segregation"),
                )
            if self.mode == "Cash":
                frappe.throw(
                    _(
                        "Foreign contribution cannot be received in cash; it must "
                        "arrive in the FCRA-designated bank account."
                    ),
                    title=_("FCRA"),
                )
        elif fund.is_fcra:
            frappe.throw(
                _(
                    "Fund {0} holds foreign contribution only, but donor {1} is "
                    "{2}. Domestic money cannot enter an FCRA fund."
                ).format(self.fund, self.donor_name, _(self.donor_type or "domestic")),
                title=_("FCRA Segregation"),
            )

    def _validate_corpus(self):
        """A Corpus-class fund may only receive corpus donations, and vice versa.

        Section 11(1)(d) corpus is capital: crediting income into a corpus fund,
        or capital into a spendable fund, would misstate both the 85% application
        test and the fund's spendable balance.
        """
        fund = self._fund()
        if fund.fund_class == "Corpus" and not self.is_corpus:
            frappe.throw(
                _(
                    "Fund {0} is Corpus class, so a donation into it must be marked "
                    "as a corpus donation."
                ).format(self.fund)
            )
        if self.is_corpus and fund.fund_class != "Corpus":
            frappe.throw(
                _(
                    "A corpus donation must go to a Corpus-class fund; {0} is {1}. "
                    "Corpus is capital and is not spendable."
                ).format(self.fund, _(fund.fund_class))
            )

    def _validate_cash_limits(self):
        """Section 269ST: a single cash receipt above the limit is not permitted."""
        if self.mode != "Cash":
            return
        limit = flt(
            frappe.db.get_single_value(
                "Trust Compliance Settings", "block_cash_donation_above"
            )
        )
        if limit and flt(self.amount) > limit:
            frappe.throw(
                _(
                    "A single cash donation of {0} exceeds the {1} limit under "
                    "Section 269ST. Receive it through the bank instead."
                ).format(
                    fmt_money(self.amount, currency=self._currency()),
                    fmt_money(limit, currency=self._currency()),
                ),
                title=_("Section 269ST"),
            )

    def _validate_pan_requirement(self):
        """Form 10BD needs an identification number for every reported donor."""
        if self.is_anonymous:
            return
        threshold = flt(
            frappe.db.get_single_value("Trust Compliance Settings", "require_pan_above")
        )
        if not threshold or flt(self.amount) < threshold:
            return
        if not frappe.db.get_value("Trust Donor", self.donor, "pan"):
            frappe.throw(
                _(
                    "Donor {0} has no PAN. A donation of {1} must be reported in "
                    "Form 10BD, which cannot be filed without the donor's PAN."
                ).format(
                    self.donor_name, fmt_money(self.amount, currency=self._currency())
                ),
                title=_("PAN Required"),
            )

    # -- receipt numbering --------------------------------------------------

    def _allocate_receipt_no(self) -> str:
        """Allocate the next gap-free receipt number for the financial year.

        Concurrency: the `SELECT ... FOR UPDATE` takes InnoDB gap locks over the
        (company, financial_year) index range, so two clerks submitting at the
        same moment serialise here rather than both computing the same number.
        The `unique` index on `receipt_no` is the final arbiter if they somehow
        do not - the second submit fails rather than duplicating a receipt.

        A number is never released on cancellation. A receipt already printed and
        handed to a donor cannot be re-issued to somebody else, so a cancelled
        donation leaves a hole in the series and the register shows it as
        cancelled. That is the audit-safe behaviour, not a defect.
        """
        financial_year = financial_year_of(self.donation_date)
        prefix = get_company_accounts(self.company).get("receipt_prefix") or "80G"

        existing = [
            row[0]
            for row in frappe.db.sql(
                """
                SELECT receipt_no
                FROM `tabTrust Donation`
                WHERE company = %s AND financial_year = %s AND receipt_no IS NOT NULL
                FOR UPDATE
                """,
                (self.company, financial_year),
            )
        ]

        return next_receipt_no(existing, financial_year, prefix=prefix)

    # -- GL posting ---------------------------------------------------------

    def _post_journal_entry(self) -> str:
        """One balanced Journal Entry, fund-tagged on both legs.

        Debit is where the money (or the asset) landed; credit is donation income,
        or the corpus equity account for a corpus donation - corpus is capital of
        the Trust and does not pass through income of the year.
        """
        accounts = get_company_accounts(self.company)
        debit_account = self._resolve_debit_account(accounts)
        credit_account = (
            accounts["corpus_fund_account"]
            if self.is_corpus
            else accounts["donation_income_account"]
        )

        remark = _("Donation {0} from {1}").format(self.receipt_no, self.donor_name)
        if self.purpose:
            remark = f"{remark} - {self.purpose}"

        entry = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Journal Entry",
                "company": self.company,
                "posting_date": self.donation_date,
                "user_remark": remark,
                "accounts": [
                    {
                        "account": debit_account,
                        "debit_in_account_currency": flt(self.amount),
                        "fund": self.fund,
                    },
                    {
                        "account": credit_account,
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

    def _resolve_debit_account(self, accounts: dict) -> str:
        """Where the donation landed.

        A foreign contribution is forced to the FCRA-designated account whatever
        the user chose, which is the account-level half of segregation. Everything
        else honours an explicit `deposit_account` and otherwise falls back to the
        account configured for the mode.
        """
        if self.donor_type == "Foreign":
            account = accounts.get("fcra_bank_account")
            if not account:
                frappe.throw(
                    _(
                        "No FCRA-designated bank account is configured for {0}. "
                        "Foreign contribution cannot be received until it is."
                    ).format(self.company),
                    title=_("Setup Incomplete"),
                )
            if self.deposit_account and self.deposit_account != account:
                frappe.msgprint(
                    _(
                        "Foreign contribution must be banked into the FCRA-designated "
                        "account {0}; the selected account was overridden."
                    ).format(account),
                    indicator="orange",
                )
            return account

        if self.mode == "In Kind":
            return self._in_kind_asset_account()

        if self.deposit_account:
            return self.deposit_account

        account = (
            accounts.get("bank_account")
            if self.mode in BANK_MODES
            else accounts.get("cash_account")
        )
        if not account:
            frappe.throw(
                _(
                    "No account is configured for mode {0} in company {1}. Set it in "
                    "Trust Compliance Settings or choose a Deposited Into account."
                ).format(_(self.mode), self.company),
                title=_("Setup Incomplete"),
            )
        return account

    def _in_kind_asset_account(self) -> str:
        """Fixed-asset account for an in-kind donation, from the Asset Category.

        Known gap, tracked deliberately: this posts the GL effect correctly but
        does not yet create the ERPNext Asset register record, because that needs
        a fixed-asset Item. Donated *property* - the dominant in-kind case for
        this Trust - is handled by the Property register, which creates the asset
        alongside the Property. Until that lands, an in-kind donation of
        equipment needs its Asset record created manually.
        """
        if not self.in_kind_asset_category:
            frappe.throw(
                _("An in-kind donation needs an Asset Category to capitalise into.")
            )
        account = frappe.db.get_value(
            "Asset Category Account",
            {"parent": self.in_kind_asset_category, "company_name": self.company},
            "fixed_asset_account",
        )
        if not account:
            frappe.throw(
                _(
                    "Asset Category {0} has no fixed-asset account configured for {1}."
                ).format(self.in_kind_asset_category, self.company)
            )
        return account

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

    def _currency(self) -> str:
        return frappe.get_cached_value("Company", self.company, "default_currency")

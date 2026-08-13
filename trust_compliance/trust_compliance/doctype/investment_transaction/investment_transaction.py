"""A receipt on an investment: interest, dividend, redemption or maturity.

The whole point of this record is that it separates *income* from *return of
capital*, because the two behave completely differently under section 11:

- Interest and dividend are **income of the year**. They are credited to an
  investment income account and therefore enter the 85% application test. They
  must **never** be credited to the corpus equity account, however the underlying
  instrument was funded - a corpus fixed deposit earns income for the Trust; it
  does not grow the corpus. Crediting it to corpus would understate the year's
  income and silently shrink the amount the Trust is required to apply.
- Redemption and maturity are **return of capital**. They credit the investment
  account and reduce the holding's book value. No income arises.

Two further rules are enforced in the posting:

- **TDS is a recoverable asset, not application of income.** The gross is the
  income; the tax deducted is debited to a receivable, because a trust with 12AB
  registration recovers it on filing. Netting it against income - or treating it
  as expenditure - would misstate both the income and the 85% test.
- **Income derived from foreign contribution is itself foreign contribution.**
  Interest on an FCRA-funded deposit therefore comes back into the
  FCRA-designated bank account and stays on the FCRA fund. Banking it domestically
  would be a fresh FCRA breach on money that was received lawfully.

Every rule about amounts and classification lives in
`trust_compliance.core.investment`; this controller only adapts it to Frappe.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, fmt_money

from trust_compliance.core.investment import (
    classify_investment_income,
    split_interest_receipt,
)
from trust_compliance.trust_compliance.doctype.trust_compliance_settings.trust_compliance_settings import (
    get_company_accounts,
)


class InvestmentTransaction(Document):
    # -- lifecycle ----------------------------------------------------------

    def validate(self):
        self._sync_investment_fields()
        self._validate_investment_is_submitted()
        self._validate_amounts()
        self._validate_transaction_date()
        self._validate_redemption_within_book_value()

    def on_submit(self):
        journal_entry = self._post_journal_entry()
        self.db_set("journal_entry", journal_entry, update_modified=False)
        if self._classification() == "asset":
            self._recompute_book_value_and_status()

    def on_cancel(self):
        self.flags.ignore_links = True
        if self.journal_entry:
            entry = frappe.get_doc("Journal Entry", self.journal_entry)
            if entry.docstatus == 1:
                entry.flags.ignore_permissions = True
                entry.cancel()
        if self._classification() == "asset":
            self._recompute_book_value_and_status()

    # -- validation ---------------------------------------------------------

    def _sync_investment_fields(self):
        """Copy company, fund and the FCRA flag down from the instrument.

        Read from the parent rather than trusted from the form: the fetched values
        are read-only in the UI but a request to the API can carry anything, and
        these three decide which bank account the money moves through.
        """
        investment = self._investment()
        self.company = investment.company
        self.fund = investment.fund
        self.is_fcra = 1 if investment.is_fcra else 0

    def _validate_investment_is_submitted(self):
        """No receipt can exist on an instrument the Trust has not booked.

        A draft investment has posted no purchase entry, so its investment account
        holds nothing; crediting a redemption against it would put the asset
        account into a negative balance out of nowhere.
        """
        investment = self._investment()
        if investment.docstatus != 1:
            frappe.throw(
                _(
                    "Investment {0} is not submitted. Submit the investment first - "
                    "until it is, no purchase entry exists for this receipt to relate "
                    "to."
                ).format(investment.name)
            )

    def _validate_amounts(self):
        """Split the receipt into net and TDS, using the core rule.

        The core raises on a TDS greater than the gross; that is turned into a
        document error rather than a traceback, because it is a data-entry mistake
        on a TDS certificate, not a bug.
        """
        if flt(self.gross_amount) <= 0:
            frappe.throw(_("Gross amount must be greater than zero."))

        try:
            split = split_interest_receipt(flt(self.gross_amount), flt(self.tds))
        except (ValueError, AssertionError) as exc:
            frappe.throw(
                _("TDS cannot exceed the gross amount of the receipt. ({0})").format(exc)
            )

        if flt(split["net"]) < 0:
            frappe.throw(
                _(
                    "TDS of {0} exceeds the gross receipt of {1}. Check the TDS "
                    "certificate."
                ).format(
                    fmt_money(self.tds, currency=self._currency()),
                    fmt_money(self.gross_amount, currency=self._currency()),
                )
            )

        self.tds = flt(split["tds"])
        self.net_amount = flt(split["net"])

    def _validate_transaction_date(self):
        """A transaction cannot predate the instrument it belongs to.

        Interest credited before the deposit was made, or a maturity dated before
        purchase, both corrupt an as-on register: the reconstruction as at any date
        between the two shows income or a redemption against a holding that did not
        yet exist.
        """
        purchase_date = frappe.db.get_value(
            "Trust Investment", self.investment, "purchase_date"
        )
        if purchase_date and getdate(self.transaction_date) < getdate(purchase_date):
            frappe.throw(
                _(
                    "Transaction date {0} is before the investment was purchased on {1}."
                ).format(
                    frappe.format_value(self.transaction_date, {"fieldtype": "Date"}),
                    frappe.format_value(purchase_date, {"fieldtype": "Date"}),
                )
            )

    def _validate_redemption_within_book_value(self):
        """A redemption cannot return more capital than the instrument carries.

        Guarded on the gross, because that is the capital coming back. Interest and
        dividend are income and do not touch capital, so they are not checked here.

        The parent row is locked for the remainder of the transaction. Without the
        lock two clerks redeeming at the same moment both validated against the
        same opening book value, both posted, and the second decrement overwrote
        the first - the instrument then showed one redemption's worth of capital
        still on hand while the bank had received two.

        No tolerance is allowed on the excess. An earlier version permitted
        `remaining + 0.01`, which let a redemption of 100.01 through against a
        remaining 100.00 and clamped the negative residual to zero, quietly losing
        a paisa of capital.
        """
        if self._classification() != "asset":
            return

        remaining = flt(
            frappe.db.get_value(
                "Trust Investment", self.investment, "book_value", for_update=True
            )
        )
        if flt(self.gross_amount) > remaining:
            frappe.throw(
                _(
                    "Investment {0} carries a book value of {1}; a {2} of {3} would "
                    "return more capital than the instrument holds."
                ).format(
                    self.investment,
                    frappe.format_value(remaining, {"fieldtype": "Currency"}),
                    _(self.kind),
                    frappe.format_value(flt(self.gross_amount), {"fieldtype": "Currency"}),
                ),
                title=_("Redemption Exceeds Book Value"),
            )


    def _post_journal_entry(self) -> str:
        classification = self._classification()
        if classification == "income":
            return self._post_income_entry()
        if classification == "asset":
            return self._post_capital_entry()

        # Unreachable with the current core, which returns only "income" or
        # "asset". Left as a refusal rather than a fallback: if a third bucket is
        # ever added, this document must be taught how to post it deliberately,
        # not default to one of the two existing treatments - and in particular
        # never to a corpus credit, which would drop the amount out of the 85%
        # application test without anyone noticing.
        frappe.throw(
            _(
                "Receipt kind {0} classifies as {1}, which this document does not know "
                "how to post. Interest and dividend are income of the year and must "
                "not be credited to corpus."
            ).format(_(self.kind), classification),
            title=_("Classification"),
        )

    def _post_income_entry(self) -> str:
        """Interest / dividend: net to bank, TDS to receivable, gross to income.

        The credit is the *gross*, not the net: the tax deducted is still the
        Trust's income, and it is recoverable, so it is debited to an asset. The
        bank leg is the FCRA-designated account when the instrument was funded by
        an FCRA fund, because income derived from foreign contribution is itself
        foreign contribution.
        """
        accounts = get_company_accounts(self.company)
        bank_account = self._bank_account(accounts)
        income_account = self._required_account(accounts, "investment_income_account")

        legs = [
            {
                "account": bank_account,
                "debit_in_account_currency": flt(self.net_amount),
                "fund": self.fund,
            },
            {
                "account": income_account,
                "credit_in_account_currency": flt(self.gross_amount),
                "fund": self.fund,
            },
        ]

        if flt(self.tds) > 0:
            legs.insert(
                1,
                {
                    "account": self._required_account(
                        accounts, "tds_receivable_account"
                    ),
                    "debit_in_account_currency": flt(self.tds),
                    "fund": self.fund,
                },
            )

        return self._insert_journal_entry(
            legs,
            _("{0} on investment {1} ({2}), gross {3}").format(
                _(self.kind),
                self.investment,
                self.fund,
                fmt_money(self.gross_amount, currency=self._currency()),
            ),
        )

    def _post_capital_entry(self) -> str:
        """Redemption / maturity: bank up, investment account down.

        No income leg. Any TDS on a redemption is still recoverable and is debited
        to the same receivable, so the bank leg takes the net.
        """
        accounts = get_company_accounts(self.company)
        bank_account = self._bank_account(accounts)
        investment_account = self._investment().investment_account

        legs = [
            {
                "account": bank_account,
                "debit_in_account_currency": flt(self.net_amount),
                "fund": self.fund,
            },
            {
                "account": investment_account,
                "credit_in_account_currency": flt(self.gross_amount),
                "fund": self.fund,
            },
        ]

        if flt(self.tds) > 0:
            legs.insert(
                1,
                {
                    "account": self._required_account(
                        accounts, "tds_receivable_account"
                    ),
                    "debit_in_account_currency": flt(self.tds),
                    "fund": self.fund,
                },
            )

        return self._insert_journal_entry(
            legs,
            _("{0} of investment {1} ({2}), {3}").format(
                _(self.kind),
                self.investment,
                self.fund,
                fmt_money(self.gross_amount, currency=self._currency()),
            ),
        )

    def _insert_journal_entry(self, legs: list[dict], remark: str) -> str:
        """One balanced entry, fund-tagged on every leg and at parent level.

        The parent fund is not redundant: it is what ERPNext falls back to for a
        leg it did not build from an item row, and the fund dimension is mandatory
        for balance-sheet accounts - the bank, the receivable and the investment
        account are all balance-sheet accounts.
        """
        entry = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Journal Entry",
                "company": self.company,
                "posting_date": self.transaction_date,
                "user_remark": f"{remark} - {self.remarks}" if self.remarks else remark,
                "fund": self.fund,
                "accounts": legs,
            }
        )
        entry.flags.ignore_permissions = True
        entry.insert()
        entry.submit()
        return entry.name

    def _bank_account(self, accounts: dict) -> str:
        key = "fcra_bank_account" if self.is_fcra else "bank_account"
        return self._required_account(accounts, key)

    def _required_account(self, accounts: dict, fieldname: str) -> str:
        """A configured account, or a setup error naming the one that is missing.

        Never derived from an account code or a name pattern: on ERPNext the chart
        is the Trust's own and account names are company-suffixed, so guessing
        would post real money to the wrong account.
        """
        account = accounts.get(fieldname)
        if account:
            return account

        frappe.throw(
            _(
                "No {0} is configured for {1}. Add it to the company's row in Trust "
                "Compliance Settings - this posting cannot proceed without it, and the "
                "account is not guessed from the chart."
            ).format(_(fieldname.replace("_", " ").title()), self.company),
            title=_("Setup Incomplete"),
        )

    # -- book value ---------------------------------------------------------

    def _recompute_book_value_and_status(self):
        """Derive book value and status from every submitted Redemption/Maturity.

        Not an increment/decrement on this transaction alone: that went wrong the
        moment transactions were cancelled out of order. Two partial Redemptions
        followed by a Maturity, then cancelling the *first* Redemption, must not
        reopen the instrument to Active while the Maturity is still submitted and
        closes it. Recomputing from the full submitted set after every submit and
        cancel is safe regardless of which one is touched or in what order.

        This document is excluded from the query by name rather than relied on to
        be at a particular docstatus: on submit it is already live and belongs in
        the set on its own account; on cancel it must not count itself.
        """
        investment = self._investment()
        rows = frappe.get_all(
            "Investment Transaction",
            filters={
                "investment": investment.name,
                "docstatus": 1,
                "kind": ["in", ("Redemption", "Maturity")],
                "name": ["!=", self.name],
            },
            fields=["kind", "gross_amount"],
        )
        if self.docstatus == 1:
            rows = [*rows, frappe._dict(kind=self.kind, gross_amount=self.gross_amount)]

        redeemed = sum(flt(row.gross_amount) for row in rows)
        remaining = flt(investment.cost) - redeemed
        if remaining < 0.01:
            remaining = 0

        # A Maturity always leaves the instrument Matured even if a residual
        # value remains - the instrument has run its term, which is a different
        # fact from having been cashed out - and that holds regardless of order,
        # so any submitted Maturity in the set is terminal.
        if any(row.kind == "Maturity" for row in rows):
            status = "Matured"
        elif remaining <= 0:
            status = "Redeemed"
        else:
            status = "Active"

        frappe.db.set_value(
            "Trust Investment",
            investment.name,
            {"book_value": remaining, "status": status},
            update_modified=False,
        )
        self._clear_investment_cache()

    # -- helpers ------------------------------------------------------------

    def _classification(self) -> str:
        """"income", "corpus" or "asset", decided by the core rule, not by a list.

        Kept out of this module deliberately: whether a dividend is income of the
        year is a statutory question, and it is answered in one place. The core
        raises on a kind it does not know; that becomes a document error, because
        it means this doctype's Kind options and the core's kind table have drifted
        apart - a deployment fault the accountant should see stated plainly.
        """
        try:
            return classify_investment_income(self.kind)
        except ValueError:
            frappe.throw(
                _(
                    "Receipt kind {0} is not one the section 11 rules recognise. The "
                    "Kind options on this doctype and "
                    "<code>trust_compliance.core.investment</code> have drifted apart."
                ).format(self.kind),
                title=_("Classification"),
            )

    def _investment(self):
        if not hasattr(self, "_investment_cache"):
            self._investment_cache = frappe.db.get_value(
                "Trust Investment",
                self.investment,
                [
                    "name",
                    "company",
                    "fund",
                    "is_fcra",
                    "is_corpus",
                    "investment_account",
                    "cost",
                    "book_value",
                    "status",
                    "docstatus",
                ],
                as_dict=True,
            )
            if not self._investment_cache:
                frappe.throw(
                    _("Investment {0} does not exist.").format(self.investment)
                )
        return self._investment_cache

    def _clear_investment_cache(self):
        if hasattr(self, "_investment_cache"):
            del self._investment_cache

    def _currency(self) -> str:
        return frappe.get_cached_value("Company", self.company, "default_currency")

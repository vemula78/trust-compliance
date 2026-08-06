"""Shared reads that drive every report in this app.

There is deliberately one GL query. Each report is a pure function in
`trust_compliance.core` fed from `gl_rows()`, so no two reports can disagree
about the ledger - a discrepancy between the fund balance report and FC-4 would
otherwise be invisible until an auditor found it.
"""

from __future__ import annotations

import frappe

from trust_compliance.core.financial_year import financial_year_window


def gl_rows(company: str, upto: object = None) -> list[dict]:
    """Posted GL entries joined to their account's classification.

    Not clipped to the report window: `build_fund_balances` and
    `build_fcra_register` need the earlier rows to form an opening balance, and
    they apply the window themselves. `upto` only trims what can never be needed.
    """
    conditions = ["gle.company = %(company)s", "gle.is_cancelled = 0"]
    params: dict = {"company": company}
    if upto:
        conditions.append("gle.posting_date <= %(upto)s")
        params["upto"] = upto

    return frappe.db.sql(
        f"""
        SELECT gle.account, gle.debit, gle.credit, gle.fund, gle.posting_date,
               gle.voucher_type, gle.voucher_no, gle.remarks, gle.party,
               acc.root_type, acc.account_type, acc.is_administrative
        FROM `tabGL Entry` gle
        JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE {" AND ".join(conditions)}
        ORDER BY gle.posting_date, gle.voucher_no
        """,
        params,
        as_dict=True,
    )


def funds(company: str) -> list[dict]:
    """Fund master including disabled funds.

    Disabled funds are included on purpose: a fund closed part-way through a year
    still holds that year's activity, and omitting it would silently reattribute
    its money to the default fund in every report.
    """
    return frappe.get_all(
        "Fund",
        filters={"company": company},
        fields=["name", "fund_name", "fund_class", "is_default", "is_fcra", "disabled"],
        order_by="name",
    )


def donations(company: str, from_date=None, to_date=None) -> list[dict]:
    """Submitted donations with the donor fields the statutory reports need."""
    filters: dict = {"company": company, "docstatus": 1}
    if from_date and to_date:
        filters["donation_date"] = ("between", [from_date, to_date])

    rows = frappe.get_all(
        "Trust Donation",
        filters=filters,
        fields=[
            "name", "receipt_no", "donation_date", "donor", "donor_name", "donor_type",
            "amount", "mode", "fund", "is_corpus", "is_anonymous", "purpose",
            "journal_entry",
        ],
        order_by="donation_date, receipt_no",
    )
    if not rows:
        return rows

    donor_meta = {
        donor.name: donor
        for donor in frappe.get_all(
            "Trust Donor",
            filters={"name": ("in", list({row.donor for row in rows}))},
            fields=["name", "pan", "address", "country"],
        )
    }
    for row in rows:
        meta = donor_meta.get(row.donor)
        row.donor_pan = meta.pan if meta else None
        row.donor_address = meta.address if meta else None
        row.donor_country = meta.country if meta else None

    return rows


def capital_additions(company: str) -> list[dict]:
    """Capital expenditure, read as debits to Fixed Asset accounts.

    Section 11 treats capital expenditure as application of income. Reading it
    from the ledger rather than from the Asset register is deliberate: it catches
    an in-kind donation that capitalises straight into a fixed-asset account as
    well as an ERPNext Asset purchase, and it cannot disagree with the GL the rest
    of the report is built from.
    """
    return [
        {"date": row["posting_date"], "amount": row["debit"] - row["credit"],
         "account": row["account"], "voucher_no": row["voucher_no"]}
        for row in gl_rows(company)
        if row["account_type"] == "Fixed Asset" and (row["debit"] - row["credit"]) > 0
    ]


def form_10_accumulations(company: str, financial_year: str | None = None) -> list[dict]:
    filters: dict = {"company": company, "docstatus": 1}
    if financial_year:
        filters["financial_year"] = financial_year
    return frappe.get_all(
        "Form 10 Accumulation",
        filters=filters,
        fields=["name", "financial_year", "amount", "purpose", "period_years"],
        order_by="financial_year",
    )


def investments(company: str) -> list[dict]:
    """Submitted investments with the fund attributes the 11(5) check needs."""
    rows = frappe.get_all(
        "Trust Investment",
        filters={"company": company, "docstatus": 1},
        fields=[
            "name", "investment_name", "fund", "mode", "instrument_type", "issuer",
            "issuer_is_psu", "counterparty", "folio_no", "cost", "book_value",
            "interest_rate", "payout_type", "purchase_date", "maturity_date",
            "is_corpus", "status",
        ],
        order_by="purchase_date, name",
    )
    if not rows:
        return rows

    modes = {
        mode.name: mode
        for mode in frappe.get_all(
            "Investment Mode",
            fields=["name", "clause", "label", "is_speculative", "allows_equity",
                    "citation_verified"],
        )
    }
    for row in rows:
        mode = modes.get(row.mode)
        # `mode_clause` is what the pure rules key on; the label is for display.
        row.mode_clause = mode.clause if mode else None
        row.mode_label = mode.label if mode else None
        row.is_speculative = mode.is_speculative if mode else 0
        row.allows_equity = mode.allows_equity if mode else 0
        row.citation_verified = mode.citation_verified if mode else 0
        row.is_equity = row.instrument_type == "Equity Shares"
        # The pure register keys rows on `investment`; `amount` is what the
        # 11(5) validator reads as the sum at stake.
        row.investment = row.name
        row.amount = row.cost

    return rows


def investment_transactions(company: str) -> list[dict]:
    """Submitted investment transactions, unclipped.

    Not windowed here: `build_investment_register` applies `as_on` itself, and it
    needs the earlier rows to arrive at a book value.
    """
    return frappe.get_all(
        "Investment Transaction",
        filters={"company": company, "docstatus": 1},
        fields=["name", "investment", "kind", "transaction_date as date",
                "gross_amount as amount", "tds", "fund"],
        order_by="transaction_date, name",
    )


def window_for(filters: dict) -> tuple:
    """Report window from a `financial_year` filter, or (None, None) for all time."""
    financial_year = (filters or {}).get("financial_year")
    if not financial_year:
        return None, None
    return financial_year_window(financial_year)


def default_financial_year() -> str:
    """Financial year of today, for pre-filling report filters."""
    from trust_compliance.core.financial_year import financial_year_of

    return financial_year_of(frappe.utils.nowdate())

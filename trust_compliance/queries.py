"""Shared reads that drive every report in this app.

There is deliberately one GL query. Each report is a pure function in
`trust_compliance.core` fed from `gl_rows()`, so no two reports can disagree
about the ledger - a discrepancy between the fund balance report and FC-4 would
otherwise be invisible until an auditor found it.
"""

from __future__ import annotations

import frappe

from trust_compliance.core.financial_year import financial_year_window


def require_company_read_permission(company: str) -> None:
    """Refuse a report before it reads anything, for a company the user cannot read.

    Every query in this module goes through `frappe.get_all` or raw SQL, neither
    of which applies document-level User Permissions. Without this check, a user
    restricted to one Company could type another Company into a report filter and
    read its donations, ledger, grants, TDS, and property data.
    """
    frappe.get_doc("Company", company).check_permission("read")


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
               gle.project,
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


def investment_modes() -> dict[str, dict]:
    """The live permitted-mode master, keyed by clause.

    This is the authority for what section 11(5) permits, not the seed table in
    `core/investment.py`. Reading it here is what lets the Trust's auditor add a
    Rule 17C clause against the notified text, or withdraw one, without an app
    release - and what makes a mode disabled after purchase stop reporting as
    permitted on the register.
    """
    return {
        mode.clause: {
            "clause": mode.clause,
            "label": mode.label,
            "is_speculative": bool(mode.is_speculative),
            "allows_equity": bool(mode.allows_equity),
            "disabled": bool(mode.disabled),
            "citation_verified": bool(mode.citation_verified),
        }
        for mode in frappe.get_all(
            "Investment Mode",
            fields=["clause", "label", "is_speculative", "allows_equity", "disabled",
                    "citation_verified"],
        )
    }


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


def programs(company: str) -> list[dict]:
    """Programs, which are ERPNext Projects.

    Cancelled projects are included: a programme closed part-way through a year
    still holds that year's expenditure, and dropping it would move that spending
    into the untagged total instead of onto the schedule.
    """
    return frappe.get_all(
        "Project",
        filters={"company": company},
        fields=["name", "project_name", "status", "company"],
        order_by="project_name",
    )


def project_budgets(company: str, from_date=None, to_date=None) -> list[dict]:
    """Budget amounts per program, from ERPNext's own Budget against a Project.

    This is what the source ERP could not do: its budget line was keyed on
    (cost centre, account, period) with no project on it, so program budgets had
    to be left out of the utilisation report. ERPNext's Budget can be set against
    a Project, so the budget column here comes from the same master the rest of
    ERPNext's budget controls read - not a second one that could drift from it.

    In ERPNext 16 a Budget is one account with one amount over a period, not a
    parent with an account table, so several Budget records make up one program's
    budget and the caller sums them.

    Only submitted budgets count; a draft budget has not been approved by anyone.

    Budgets are matched to the report window by *overlap*, not containment: a
    budget period need not line up with the window being reported, and a budget
    that covers part of the window is still the authority for that part. A window
    spanning two budget years therefore sums both, which is what "budget for this
    period" means.
    """
    filters: dict = {"company": company, "budget_against": "Project", "docstatus": 1}
    if from_date:
        filters["budget_end_date"] = (">=", from_date)
    if to_date:
        filters["budget_start_date"] = ("<=", to_date)

    return frappe.get_all(
        "Budget",
        filters=filters,
        fields=["name", "project", "account", "budget_amount",
                "budget_start_date", "budget_end_date"],
    )


def grant_liability_rows(company: str, upto: object = None) -> list[dict]:
    """GL rows against the configured grant liability account.

    Filtered out of the same `gl_rows()` read rather than a second query, for the
    reason stated at the top of this module: two reads of the ledger could
    disagree with each other, one could not. Returns nothing, rather than
    throwing, when no grant liability account is configured - a company with no
    grants has nothing to show on the register, which is a fact, not an error.
    """
    from trust_compliance.trust_compliance.doctype.trust_compliance_settings.trust_compliance_settings import (
        get_company_accounts,
    )

    account = get_company_accounts(company).get("grant_liability_account")
    if not account:
        return []
    return [row for row in gl_rows(company, upto=upto) if row["account"] == account]


def tds_payable_rows(company: str, upto: object = None) -> list[dict]:
    """GL rows against the configured TDS payable account.

    Same reasoning as `grant_liability_rows()`: filtered out of the one GL read
    rather than a second query, and returns nothing rather than throwing when no
    TDS payable account is configured.
    """
    from trust_compliance.trust_compliance.doctype.trust_compliance_settings.trust_compliance_settings import (
        get_company_accounts,
    )

    account = get_company_accounts(company).get("tds_payable_account")
    if not account:
        return []
    return [row for row in gl_rows(company, upto=upto) if row["account"] == account]


def grant_liability_account(company: str) -> str | None:
    """Configured grant liability account for a company, or None.

    Unlike `get_company_accounts()`, this does not throw when the company has no
    Trust Compliance Settings row at all - callers here are read-only reports
    tagging GL rows for classification, not the donation posting path that
    requires the account to exist.
    """
    from trust_compliance.trust_compliance.doctype.trust_compliance_settings.trust_compliance_settings import (
        get_company_accounts,
    )

    try:
        return get_company_accounts(company).get("grant_liability_account")
    except frappe.ValidationError:
        return None


def inter_unit_gl_rows(companies: list[str], from_date=None, to_date=None) -> list[dict]:
    """GL rows of the vouchers flagged as inter-unit transfers.

    Joined through Journal Entry because the flag lives there: a consolidation
    reads the ledger, and the ledger is where the fact that these two entries are
    one transfer has to be recorded. Both units' rows are read in one query so the
    two sides can be reconciled against each other - the elimination is only
    applicable if they are equal.
    """
    if not companies:
        return []

    conditions = [
        "gle.is_cancelled = 0",
        "gle.voucher_type = 'Journal Entry'",
        "je.is_inter_unit = 1",
        "gle.company IN %(companies)s",
    ]
    params: dict = {"companies": tuple(companies)}
    if from_date:
        conditions.append("gle.posting_date >= %(from_date)s")
        params["from_date"] = from_date
    if to_date:
        conditions.append("gle.posting_date <= %(to_date)s")
        params["to_date"] = to_date

    return frappe.db.sql(
        f"""
        SELECT gle.company, gle.account, gle.debit, gle.credit, gle.fund,
               gle.posting_date, gle.voucher_no, gle.project,
               je.counterparty_company, je.user_remark,
               acc.root_type
        FROM `tabGL Entry` gle
        JOIN `tabJournal Entry` je ON je.name = gle.voucher_no
        JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE {" AND ".join(conditions)}
        ORDER BY gle.posting_date, gle.voucher_no
        """,
        params,
        as_dict=True,
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

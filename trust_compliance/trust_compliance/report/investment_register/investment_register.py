"""Investment Register with a live section 11(5) compliance check.

The register is the schedule an auditor asks for: what the Trust holds, under
which permitted mode, funded from which fund, at what book value, and what income
it produced. Compliance is re-evaluated here rather than trusted from the purchase
- an auto-rollover, a change in Rule 17C, or a mode later disabled can all make an
instrument that was compliant when bought non-compliant today, and section
115BBI taxes the income of a non-compliant investment at 30%. A register that
only showed the status recorded at purchase would hide exactly that.

Book value is cost less redemptions. Trusts carry investments at cost, not fair
value, so no revaluation is applied.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from trust_compliance import queries
from trust_compliance.core.investment import build_investment_register


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    as_on = filters.get("as_on")

    report = build_investment_register(
        queries.investments(company),
        queries.investment_transactions(company),
        queries.funds(company),
        as_on=as_on,
    )

    rows = report["rows"]
    if filters.get("fund"):
        rows = [row for row in rows if row["fund"] == filters["fund"]]
    if filters.get("only_non_compliant"):
        rows = [row for row in rows if not row["is_compliant"]]

    data = [
        {
            "investment": row["investment"],
            "fund": row["fund"],
            "source": _("FCRA") if row["is_fcra"] else _("Domestic"),
            "mode_clause": row["mode_clause"],
            "mode_label": row["mode_label"],
            "instrument_type": row["instrument_type"],
            "issuer": row["issuer"],
            "cost": row["cost"],
            "redeemed": row["redeemed"],
            "book_value": row["book_value"],
            "income_earned": row["income_earned"],
            "tds": row["tds"],
            "compliance": _("Permitted") if row["is_compliant"] else _("Outside 11(5)"),
            "violations": "; ".join(row["violations"]) or None,
        }
        for row in rows
    ]

    if data:
        data.append({})
        data.append(
            {
                "mode_label": _("Total"),
                "cost": sum(flt(row["cost"]) for row in rows),
                "redeemed": sum(flt(row["redeemed"]) for row in rows),
                "book_value": sum(flt(row["book_value"]) for row in rows),
                "income_earned": sum(flt(row["income_earned"]) for row in rows),
                "tds": sum(flt(row["tds"]) for row in rows),
                "bold": 1,
            }
        )

    # (columns, data, message, chart) - the chart must not land in the
    # report_summary slot, which the desk iterates as a list.
    return _columns(), data, _message(report, rows, company), _chart(report)


def _message(report: dict, rows: list[dict], company: str) -> str:
    if not rows:
        return _("No submitted investments for this company yet.")

    currency = frappe.get_cached_value("Company", company, "default_currency")

    def money(value):
        return fmt_money(value, currency=currency)

    totals = report["totals"]
    lines = [
        _("{0} instruments, book value {1}, income {2} (TDS {3}).").format(
            len(rows), money(totals["book_value"]), money(totals["income_earned"]),
            money(totals["tds"]),
        )
    ]

    non_compliant = flt(totals["non_compliant_book_value"])
    if non_compliant:
        lines.append(
            "<b style='color:var(--red-600)'>"
            + _(
                "{0} is held outside the forms and modes permitted by section 11(5). "
                "Income from it is specified income taxable at 30% under section "
                "115BBI, and repeated breach puts the 12AB registration at risk."
            ).format(money(non_compliant))
            + "</b>"
        )
    else:
        lines.append(_("Every instrument is within a permitted section 11(5) mode."))

    corpus_value = sum(
        flt(row["book_value"]) for row in rows if row["fund_class"] == "Corpus"
    )
    if corpus_value:
        lines.append(
            _(
                "Corpus held in investments: {0}. Since Finance Act 2021 a corpus "
                "donation keeps its section 11(1)(d) exemption only while it stays in "
                "an 11(5) mode and separately identifiable."
            ).format(money(corpus_value))
        )

    unverified = sum(
        flt(row["book_value"]) for row in rows if not row.get("citation_verified")
    )
    if unverified:
        lines.append(
            _(
                "{0} sits under a clause whose citation has not been verified against "
                "the currently notified text of Rule 17C. The investment is treated as "
                "permitted, but confirm the clause number before quoting it on an audit "
                "schedule or a Form 10B annexure, then tick Citation Verified on the "
                "Investment Mode."
            ).format(money(unverified))
        )

    lines.append(
        "<i>"
        + _(
            "Interest and dividend shown here is income of the year, not corpus, and "
            "is included in the 85% application test. TDS is a recoverable asset and "
            "is not application of income."
        )
        + "</i>"
    )

    return "<br>".join(lines)


def _chart(report: dict) -> dict:
    by_mode = report["by_mode"]
    labels = [by_mode[clause]["mode_label"] or clause for clause in sorted(by_mode)]
    values = [by_mode[clause]["book_value"] for clause in sorted(by_mode)]
    return {
        "data": {"labels": labels,
                 "datasets": [{"name": _("Book Value"), "values": values}]},
        "type": "bar",
    }


def _columns() -> list[dict]:
    currency_options = "Company:company:default_currency"
    return [
        {"fieldname": "investment", "label": _("Investment"), "fieldtype": "Link",
         "options": "Trust Investment", "width": 130},
        {"fieldname": "mode_label", "label": _("Permitted Mode"), "fieldtype": "Data",
         "width": 200},
        {"fieldname": "mode_clause", "label": _("Clause"), "fieldtype": "Data",
         "width": 100},
        {"fieldname": "book_value", "label": _("Book Value"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "income_earned", "label": _("Income"), "fieldtype": "Currency",
         "options": currency_options, "width": 120},
        {"fieldname": "tds", "label": _("TDS"), "fieldtype": "Currency",
         "options": currency_options, "width": 100},
        {"fieldname": "compliance", "label": _("11(5)"), "fieldtype": "Data",
         "width": 110},
        {"fieldname": "fund", "label": _("Fund"), "fieldtype": "Link", "options": "Fund",
         "width": 100},
        {"fieldname": "source", "label": _("Source"), "fieldtype": "Data", "width": 90},
        {"fieldname": "instrument_type", "label": _("Instrument"), "fieldtype": "Data",
         "width": 150},
        {"fieldname": "issuer", "label": _("Issuer"), "fieldtype": "Data", "width": 170},
        {"fieldname": "cost", "label": _("Cost"), "fieldtype": "Currency",
         "options": currency_options, "width": 120},
        {"fieldname": "redeemed", "label": _("Redeemed"), "fieldtype": "Currency",
         "options": currency_options, "width": 120},
        {"fieldname": "violations", "label": _("Violation"), "fieldtype": "Data",
         "width": 300},
    ]

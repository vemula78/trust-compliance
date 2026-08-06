"""Program Utilisation: what each program was given, spent, and budgeted.

Thin adapter. The arithmetic is `core.program.build_program_utilisation`, which is
unit-tested outside a bench.

The question this answers is the one the Trust has to answer to its donors and to
the assessing officer: what did each program cost, and was it what the trustees
approved. Expenditure on a program is application of income to the objects of the
Trust, so these figures belong to the same 85% test the Income Application report
measures - and they are read off the ledger, not from a separate program record,
so the two cannot disagree.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from trust_compliance import queries
from trust_compliance.core.program import build_program_utilisation


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    from_date, to_date = queries.window_for(filters)

    report = build_program_utilisation(
        queries.gl_rows(company, upto=to_date),
        queries.programs(company),
        queries.project_budgets(company, from_date=from_date, to_date=to_date),
        from_date=from_date,
        to_date=to_date,
    )

    rows = report["rows"]
    if filters.get("only_over_budget"):
        rows = [row for row in rows if row["over_budget"]]

    data = [
        {
            "program": row["program"],
            "program_name": row["program_name"],
            "status": row["status"],
            "funds": ", ".join(fund["fund"] for fund in row["by_fund"] if fund["fund"])
            or None,
            "income": row["income"],
            "expense": row["expense"],
            "net": row["net"],
            "budget": row["budget"] or None,
            "utilised_pct": row["utilised_pct"],
            "remaining": row["remaining"] if row["budget"] else None,
        }
        for row in rows
    ]

    if data:
        data.append({})
        data.append(
            {
                "program_name": _("Total"),
                "income": sum(flt(row["income"]) for row in rows),
                "expense": sum(flt(row["expense"]) for row in rows),
                "net": sum(flt(row["net"]) for row in rows),
                "budget": sum(flt(row["budget"]) for row in rows) or None,
                "bold": 1,
            }
        )

    # (columns, data, message, chart) - the chart must not land in the
    # report_summary slot, which the desk iterates as a list.
    return _columns(company), data, _message(report, rows, company), _chart(rows)


def _message(report: dict, rows: list[dict], company: str) -> str:
    if not report["rows"]:
        return _(
            "No programs are defined for this company. A program is an ERPNext "
            "Project; create one per activity the Trust funds, and set a Budget "
            "against it to get the budget columns."
        )

    currency = frappe.get_cached_value("Company", company, "default_currency")

    def money(value):
        return fmt_money(value, currency=currency)

    lines = [
        _("{0} programs, income {1}, expenditure {2}.").format(
            len(rows),
            money(sum(flt(row["income"]) for row in rows)),
            money(sum(flt(row["expense"]) for row in rows)),
        )
    ]

    over = [row for row in rows if row["over_budget"]]
    if over:
        lines.append(
            "<b style='color:var(--red-600)'>"
            + _("{0} over the approved budget: {1}.").format(
                len(over), ", ".join(row["program_name"] for row in over)
            )
            + "</b>"
        )

    unbudgeted = [row for row in rows if not row["budget"] and row["expense"]]
    if unbudgeted:
        lines.append(
            _(
                "{0} spent without a budget against the program: {1}. Utilisation "
                "cannot be measured for these."
            ).format(len(unbudgeted), ", ".join(row["program_name"] for row in unbudgeted))
        )

    # Reported rather than pooled into an "unassigned" row. An untagged line is not
    # part of any program, and showing it as one would overstate what the programs
    # delivered - but its size is exactly what an auditor asks about, because the
    # difference between this and the Income & Expenditure statement is the part of
    # the year's spending nobody attributed.
    untagged = report["untagged"]
    if untagged["expense"] or untagged["income"]:
        lines.append(
            _(
                "Not attributed to any program: expenditure {0}, income {1}. These "
                "are excluded from the rows above, so this report and the Income and "
                "Expenditure statement differ by exactly this much."
            ).format(money(untagged["expense"]), money(untagged["income"]))
        )

    return "<br>".join(lines)


def _chart(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    labels = [row["program_name"] for row in rows]
    return {
        "data": {
            "labels": labels,
            "datasets": [
                {"name": _("Budget"), "values": [flt(row["budget"]) for row in rows]},
                {"name": _("Spent"), "values": [flt(row["expense"]) for row in rows]},
            ],
        },
        "type": "bar",
    }


def _columns(company: str) -> list[dict]:
    currency_options = "Company:company:default_currency"
    return [
        {"fieldname": "program", "label": _("Program"), "fieldtype": "Link",
         "options": "Project", "width": 140},
        {"fieldname": "program_name", "label": _("Name"), "fieldtype": "Data",
         "width": 220},
        {"fieldname": "budget", "label": _("Budget"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "expense", "label": _("Spent"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "utilised_pct", "label": _("Utilised %"), "fieldtype": "Percent",
         "width": 100},
        {"fieldname": "remaining", "label": _("Remaining"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "income", "label": _("Income / Grants"), "fieldtype": "Currency",
         "options": currency_options, "width": 140},
        {"fieldname": "net", "label": _("Net"), "fieldtype": "Currency",
         "options": currency_options, "width": 120},
        {"fieldname": "funds", "label": _("Funds"), "fieldtype": "Data", "width": 150},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
    ]

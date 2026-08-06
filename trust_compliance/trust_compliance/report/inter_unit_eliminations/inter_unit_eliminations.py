"""Inter-Unit Eliminations: what a consolidated statement must leave out.

Each unit of the Trust keeps its own books, so a grant from the Trust to one of
its hospitals is real expenditure in one set and real income in the other, and
both entries must stand in the unit accounts. At *group* level they are the same
money seen twice: adding them unchanged would inflate group income and group
expenditure by the amount transferred, and would show the group as having applied
income it had only moved between its own units.

ERPNext's own Consolidated Financial Statement does not eliminate these, so this
report is the disclosure that goes with it: the amount to remove from each side,
per pair of units, with the two sides reconciled against each other. If they
disagree, one leg was cancelled or edited alone and the consolidation is wrong by
the difference however the elimination is applied - which is why that check is
stated on the report rather than assumed.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from trust_compliance import queries
from trust_compliance.core.inter_unit import build_elimination_summary


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    from_date, to_date = queries.window_for(filters)

    companies = _group_companies(company)
    rows = queries.inter_unit_gl_rows(companies, from_date=from_date, to_date=to_date)
    report = build_elimination_summary(rows)

    data = [
        {
            "from_company": row["from_company"],
            "to_company": row["to_company"],
            "amount": row["amount"],
        }
        for row in report["rows"]
    ]

    if data:
        data.append({})
        data.append(
            {
                "from_company": _("Total to eliminate"),
                "amount": report["net_transferred"],
                "bold": 1,
            }
        )

    # (columns, data, message, chart) - the chart must not land in the
    # report_summary slot, which the desk iterates as a list.
    return _columns(company), data, _message(report, company), None


def _group_companies(company: str) -> list[str]:
    """The unit asked for, plus every unit it has transferred to or from.

    Derived from the transfers themselves rather than from ERPNext's company tree:
    the Trust's units are separate legal persons and need not be arranged as a
    parent and its children, and an elimination set defined by the transfers cannot
    omit a counterparty that a tree happened not to include.

    Permission is checked on every unit that goes into the figures. A unit the user
    cannot read is refused rather than dropped: a group total silently missing one
    side of a transfer would be worse than no total at all.
    """
    frappe.get_doc("Company", company).check_permission("read")

    counterparties = frappe.get_all(
        "Inter Unit Transfer",
        filters={"docstatus": 1},
        or_filters={"from_company": company, "to_company": company},
        fields=["from_company", "to_company"],
    )
    companies = {company}
    for row in counterparties:
        companies.add(row.from_company)
        companies.add(row.to_company)

    for other in sorted(companies - {company}):
        if not frappe.has_permission("Company", ptype="read", doc=other, throw=False):
            frappe.throw(
                _(
                    "This unit has transferred to or from {0}, which you are not "
                    "permitted to read. The elimination cannot be shown without both "
                    "sides."
                ).format(other),
                frappe.PermissionError,
            )

    return sorted(companies)


def _message(report: dict, company: str) -> str:
    if not report["rows"]:
        return _(
            "No inter-unit transfers in this window. Nothing needs to be eliminated "
            "from a consolidated statement."
        )

    currency = frappe.get_cached_value("Company", company, "default_currency")

    def money(value):
        return fmt_money(value, currency=currency)

    lines = [
        _(
            "{0} transfers on {1} journal entries. Remove {2} from group expenditure "
            "and {3} from group income - {4} in total from the group's figures."
        ).format(
            len(report["rows"]),
            report["voucher_count"],
            money(report["eliminated_expense"]),
            money(report["eliminated_income"]),
            money(report["total_removed"]),
        )
    ]

    if report["is_balanced"]:
        lines.append(
            _(
                "The two sides agree, so the elimination is complete: every paying "
                "unit's expense has its matching grant income in the receiving unit."
            )
        )
    else:
        difference = flt(report["eliminated_expense"]) - flt(report["eliminated_income"])
        lines.append(
            "<b style='color:var(--red-600)'>"
            + _(
                "The two sides differ by {0}. One leg of a transfer has been "
                "cancelled or edited without the other, so a consolidated statement "
                "is wrong by this amount whichever way the elimination is applied. "
                "Find the transfer with only one live journal entry and cancel or "
                "repost both."
            ).format(money(abs(difference)))
            + "</b>"
        )

    return "<br>".join(lines)


def _columns(company: str) -> list[dict]:
    return [
        {"fieldname": "from_company", "label": _("Paying Unit"), "fieldtype": "Data",
         "width": 260},
        {"fieldname": "to_company", "label": _("Receiving Unit"), "fieldtype": "Link",
         "options": "Company", "width": 260},
        {"fieldname": "amount", "label": _("Amount to Eliminate"),
         "fieldtype": "Currency", "options": "Company:company:default_currency",
         "width": 180},
    ]

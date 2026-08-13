"""85% application-of-income tracking for a 12A/12AB registered trust.

This is a working paper for the auditor, not the filed return. The message under
the report states every simplification, so nobody mistakes it for the Form 10B
computation.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import fmt_money

from trust_compliance import queries
from trust_compliance.core.compliance import (
    REQUIRED_APPLICATION_RATIO,
    build_income_application,
)


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    queries.require_company_read_permission(company)
    financial_year = filters.get("financial_year")
    from_date, to_date = queries.window_for(filters)

    report = build_income_application(
        queries.gl_rows(company, upto=to_date),
        capital_additions=queries.capital_additions(company),
        accumulations=queries.form_10_accumulations(company, financial_year),
        from_date=from_date,
        to_date=to_date,
    )

    required_percent = int(REQUIRED_APPLICATION_RATIO * 100)
    data = [
        {"particulars": _("Total income of the year"), "amount": report["total_income"],
         "bold": 1},
        {"particulars": _("Required application ({0}% of income)").format(required_percent),
         "amount": report["required_application"], "bold": 1},
        {},
        {"particulars": _("Applied - revenue expenditure"),
         "amount": report["applied_revenue"], "indent": 1},
        {"particulars": _("Applied - capital expenditure"),
         "amount": report["applied_capital"], "indent": 1},
        {"particulars": _("Total applied"), "amount": report["applied"], "bold": 1},
        {"particulars": _("Accumulated under Section 11(2) / Form 10"),
         "amount": report["accumulated"], "indent": 1},
        {"particulars": _("Applied plus accumulated"),
         "amount": report["applied"] + report["accumulated"], "bold": 1},
        {},
        {"particulars": _("Application achieved"), "percent": report["application_percent"],
         "bold": 1},
        {
            "particulars": _("Shortfall") if report["shortfall"] else _("No shortfall"),
            "amount": report["shortfall"],
            "bold": 1,
        },
    ]

    return _columns(), data, _message(report, company)


def _message(report: dict, company: str) -> str:
    currency = frappe.get_cached_value("Company", company, "default_currency")
    required_percent = int(REQUIRED_APPLICATION_RATIO * 100)

    if report["compliant"]:
        headline = (
            "<b style='color:var(--green-600)'>"
            + _("The {0}% application requirement is met ({1}% achieved).").format(
                required_percent, report["application_percent"]
            )
            + "</b>"
        )
    else:
        headline = (
            "<b style='color:var(--red-600)'>"
            + _(
                "Shortfall of {0}. Either apply the balance before the year end or file "
                "Form 10 to accumulate it for a stated purpose."
            ).format(fmt_money(report["shortfall"], currency=currency))
            + "</b>"
        )

    caveat = _(
        "Working paper, not the filed return. The Form 10B computation carries further "
        "adjustments this does not model: corpus donations excluded from income, the "
        "15% permitted accumulation carried forward, application measured on a payment "
        "basis, depreciation disallowed on assets already claimed as application, and "
        "inter-charity donations. Capital expenditure is read as debits to Fixed Asset "
        "accounts, so an in-kind donation appears in both income and capital application."
    )

    return f"{headline}<br><br><i>{caveat}</i>"


def _columns() -> list[dict]:
    return [
        {"fieldname": "particulars", "label": _("Particulars"), "fieldtype": "Data",
         "width": 420},
        {"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency",
         "options": "Company:company:default_currency", "width": 170},
        {"fieldname": "percent", "label": _("%"), "fieldtype": "Percent", "width": 100},
    ]

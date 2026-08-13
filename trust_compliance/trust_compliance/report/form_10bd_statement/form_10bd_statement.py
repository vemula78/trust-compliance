"""Form 10BD donor statement.

One row per donor per donation type per receipt mode, which is how the filing
utility expects a donor who gave both in cash and otherwise to be reported.
Export this to CSV and it maps onto the utility's columns directly.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import fmt_money

from trust_compliance import queries
from trust_compliance.core.compliance import build_form_10bd

#: Form 10BD identification types. PAN is the only one this app captures; the
#: others exist in the utility for donors who have no PAN (passport, Aadhaar,
#: taxpayer identification number of the foreign country).
ID_TYPE_PAN = "Permanent Account Number"


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    queries.require_company_read_permission(company)
    from_date, to_date = queries.window_for(filters)

    report = build_form_10bd(
        queries.donations(company, from_date, to_date),
        from_date=from_date,
        to_date=to_date,
    )

    data = [
        {
            "donor": row["donor"],
            "donor_name": row["donor_name"],
            "id_type": ID_TYPE_PAN if row["pan"] else "",
            "pan": row["pan"],
            "donor_type": row["donor_type"],
            "address": row["address"],
            "donation_type": row["donation_type"],
            "mode": row["mode"],
            "receipt_count": row["receipt_count"],
            "amount": row["amount"],
            "pan_missing": row["pan_missing"],
        }
        for row in report["rows"]
    ]

    data.append({})
    data.append(
        {
            "donor_name": _("Total reported"),
            "amount": report["summary"]["reported_total"],
            "bold": 1,
        }
    )

    return _columns(), data, _message(report["summary"], company)


def _message(summary: dict, company: str) -> str:
    currency = frappe.get_cached_value("Company", company, "default_currency")
    lines = [
        _("{0} donor rows reporting {1}.").format(
            summary["donor_rows"], fmt_money(summary["reported_total"], currency=currency)
        ),
        _(
            "Anonymous donations of {0} are excluded - there is no donor to report - "
            "but are disclosed here so this statement reconciles to the Donation "
            "Register."
        ).format(fmt_money(summary["anonymous_total"], currency=currency)),
    ]

    if summary["rows_missing_pan"]:
        lines.append(
            "<b style='color:var(--red-600)'>"
            + _(
                "{0} row(s) have no PAN. Form 10BD cannot be filed without an "
                "identification number for each donor - fill these in before filing, "
                "or the return will be rejected."
            ).format(summary["rows_missing_pan"])
            + "</b>"
        )

    return "<br>".join(lines)


def _columns() -> list[dict]:
    return [
        {"fieldname": "donor", "label": _("Donor"), "fieldtype": "Link",
         "options": "Trust Donor", "width": 130},
        {"fieldname": "donor_name", "label": _("Name of Donor"), "fieldtype": "Data",
         "width": 200},
        {"fieldname": "id_type", "label": _("ID Type"), "fieldtype": "Data", "width": 190},
        {"fieldname": "pan", "label": _("Unique Identification Number"),
         "fieldtype": "Data", "width": 190},
        {"fieldname": "donor_type", "label": _("Donor Type"), "fieldtype": "Data",
         "width": 110},
        {"fieldname": "address", "label": _("Address"), "fieldtype": "Data", "width": 240},
        {"fieldname": "donation_type", "label": _("Type of Donation"), "fieldtype": "Data",
         "width": 130},
        {"fieldname": "mode", "label": _("Mode of Receipt"), "fieldtype": "Data",
         "width": 130},
        {"fieldname": "receipt_count", "label": _("Receipts"), "fieldtype": "Int",
         "width": 90},
        {"fieldname": "amount", "label": _("Amount of Donation"), "fieldtype": "Currency",
         "options": "Company:company:default_currency", "width": 160},
    ]

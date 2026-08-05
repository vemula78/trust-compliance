"""FCRA Register / FC-4 data pack.

Two sections in one report, because that is how FC-4 is filed and how the
administrative cap is defended: the contributor-wise receipts, then the
utilisation with each line's administrative classification, then the summary that
measures the 20% cap against contribution *received* in the year.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import fmt_money

from trust_compliance import queries
from trust_compliance.core.compliance import FCRA_ADMIN_CAP_PERCENT, build_fcra_register


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    from_date, to_date = queries.window_for(filters)

    report = build_fcra_register(
        queries.gl_rows(company, upto=to_date),
        queries.donations(company),
        queries.funds(company),
        from_date=from_date,
        to_date=to_date,
    )

    data: list[dict] = []

    data.append({"particulars": _("Foreign Contribution Received (contributor-wise)"),
                 "indent": 0, "bold": 1})
    for row in report["receipts"]:
        data.append(
            {
                "particulars": row["donor_name"],
                "reference": row["receipt_no"],
                "posting_date": row["donation_date"],
                "country": row["donor_country"],
                "purpose": row["purpose"],
                "fund": row["fund"],
                "received": row["amount"],
                "indent": 1,
            }
        )
    data.append({"particulars": _("Total receipted foreign contribution"),
                 "received": report["summary"]["donation_receipts"],
                 "indent": 1, "bold": 1})
    data.append({})

    data.append({"particulars": _("Utilisation"), "indent": 0, "bold": 1})
    for row in report["utilizations"]:
        data.append(
            {
                "particulars": row["account"],
                "reference": row["voucher_no"],
                "posting_date": row["posting_date"],
                "purpose": row["remarks"],
                "fund": row["fund"],
                "utilised": row["amount"],
                "administrative": _("Yes") if row["is_administrative"] else "",
                "indent": 1,
            }
        )
    data.append({"particulars": _("Total utilised"), "utilised": report["summary"]["utilized"],
                 "indent": 1, "bold": 1})
    data.append({"particulars": _("of which administrative"),
                 "utilised": report["summary"]["admin_utilized"],
                 "administrative": _("Yes"), "indent": 1, "bold": 1})
    data.append({})

    summary = report["summary"]
    data.append({"particulars": _("Summary"), "indent": 0, "bold": 1})
    for label, value in [
        (_("Opening balance of foreign contribution"), summary["opening_balance"]),
        (_("Received during the year (from the ledger)"), summary["receipts"]),
        (_("Utilised during the year"), -summary["utilized"]),
        (_("Closing balance"), summary["closing_balance"]),
    ]:
        data.append({"particulars": label, "received": value, "indent": 1,
                     "bold": 1 if label == _("Closing balance") else 0})

    return _columns(), data, _message(summary, company)


def _message(summary: dict, company: str) -> str:
    currency = frappe.get_cached_value("Company", company, "default_currency")
    lines = [
        _(
            "Administrative expenditure {0} is {1}% of foreign contribution received "
            "({2}). The FCRA cap is {3}%, measured against contribution received in "
            "the year and not against what was utilised out of it."
        ).format(
            fmt_money(summary["admin_utilized"], currency=currency),
            summary["admin_percent"],
            fmt_money(summary["receipts"], currency=currency),
            FCRA_ADMIN_CAP_PERCENT,
        )
    ]

    if summary["admin_cap_exceeded"]:
        lines.append(
            "<b style='color:var(--red-600)'>"
            + _("The {0}% administrative cap is exceeded.").format(FCRA_ADMIN_CAP_PERCENT)
            + "</b>"
        )

    if summary["donation_receipts"] != summary["journal_receipts"]:
        lines.append(
            _(
                "Receipted donations total {0} but the ledger shows {1} of foreign "
                "contribution received. The difference is foreign contribution posted "
                "by journal entry rather than through the donation register - it counts "
                "for FC-4 but has no contributor row above, so identify it before filing."
            ).format(
                fmt_money(summary["donation_receipts"], currency=currency),
                fmt_money(summary["journal_receipts"], currency=currency),
            )
        )

    return "<br>".join(lines)


def _columns() -> list[dict]:
    """Amounts before free text.

    This report has nine columns and its purpose is the money. With the
    descriptive columns first, Received and Utilised fall off the right edge of a
    1280px screen and the reader has to scroll horizontally to see any figure -
    so the amounts sit immediately after the identifying columns, and Country and
    Purpose (long, and only populated on some rows) go last.
    """
    currency_options = "Company:company:default_currency"
    return [
        {"fieldname": "particulars", "label": _("Particulars"), "fieldtype": "Data",
         "width": 230},
        {"fieldname": "reference", "label": _("Reference"), "fieldtype": "Data",
         "width": 135},
        {"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 90},
        {"fieldname": "fund", "label": _("Fund"), "fieldtype": "Link", "options": "Fund",
         "width": 100},
        {"fieldname": "received", "label": _("Received"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "utilised", "label": _("Utilised"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "administrative", "label": _("Admin"), "fieldtype": "Data",
         "width": 70},
        {"fieldname": "country", "label": _("Country"), "fieldtype": "Data", "width": 110},
        {"fieldname": "purpose", "label": _("Purpose / Remarks"), "fieldtype": "Data",
         "width": 200},
    ]

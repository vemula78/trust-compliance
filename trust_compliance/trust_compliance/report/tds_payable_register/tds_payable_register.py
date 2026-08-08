"""TDS Payable Register: deducted, remitted and outstanding TDS payable.

The payable-side counterpart of the Investment Register's TDS column. Deduction
itself is posted by ERPNext's own Tax Withholding Category on a Purchase
Invoice or Payment Entry - see `core.tds` for why this app does not duplicate
that. This report only reads what has landed in the configured TDS payable
account. All arithmetic is `core.tds.build_tds_payable_register`, unit-tested
outside a bench.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from trust_compliance import queries
from trust_compliance.core.tds import build_tds_payable_register


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    as_on = filters.get("as_on")

    report = build_tds_payable_register(
        queries.tds_payable_rows(company, upto=as_on),
        queries.funds(company),
        as_on=as_on,
    )

    data = list(report["rows"])
    if data:
        data.append({})
        data.append(
            {
                "fund_name": _("Total"),
                "deducted": report["total_deducted"],
                "remitted": report["total_remitted"],
                "balance": report["total_balance"],
                "bold": 1,
            }
        )

    return _columns(company), data, _message(report, company)


def _message(report: dict, company: str) -> str:
    if not report["rows"]:
        return _(
            "No TDS payable posted for this company. Either the Trust has deducted "
            "no TDS on a payment, or no TDS Payable Account is configured in Trust "
            "Compliance Settings."
        )
    currency = frappe.get_cached_value("Company", company, "default_currency")
    unfunded = sum(1 for row in report["rows"] if row["fund"] is None)
    message = _(
        "{0} deducted, {1} remitted to the government, {2} still payable."
    ).format(
        fmt_money(flt(report["total_deducted"]), currency=currency),
        fmt_money(flt(report["total_remitted"]), currency=currency),
        fmt_money(flt(report["total_balance"]), currency=currency),
    )
    if unfunded:
        message += "<br>" + _(
            "One row has no fund - the deducting Payment Entry or Purchase "
            "Invoice did not carry the fund dimension. Tag it so the schedule "
            "attributes the liability correctly."
        )
    return message


def _columns(company: str) -> list[dict]:
    currency_options = "Company:company:default_currency"
    return [
        {"fieldname": "fund", "label": _("Fund"), "fieldtype": "Link",
         "options": "Fund", "width": 110},
        {"fieldname": "fund_name", "label": _("Fund Name"), "fieldtype": "Data",
         "width": 200},
        {"fieldname": "deducted", "label": _("Deducted"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "remitted", "label": _("Remitted"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "balance", "label": _("Outstanding Payable"),
         "fieldtype": "Currency", "options": currency_options, "width": 160},
    ]

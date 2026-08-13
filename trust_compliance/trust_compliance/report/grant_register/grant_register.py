"""Grant Register: received, recognised and outstanding grant liability per fund.

The schedule for a "Grant Received in Advance" note - the real audited accounts'
own name for this liability. All arithmetic is `core.grant.build_grant_register`,
unit-tested outside a bench; this module only reads the ledger and formats it.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from trust_compliance import queries
from trust_compliance.core.grant import build_grant_register


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    queries.require_company_read_permission(company)
    as_on = filters.get("as_on")

    report = build_grant_register(
        queries.grant_liability_rows(company, upto=as_on),
        queries.funds(company),
        as_on=as_on,
    )

    data = list(report["rows"])
    if data:
        data.append({})
        data.append(
            {
                "fund_name": _("Total"),
                "received": report["total_received"],
                "recognised": report["total_recognised"],
                "balance": report["total_balance"],
                "bold": 1,
            }
        )

    return _columns(company), data, _message(report, company)


def _message(report: dict, company: str) -> str:
    if not report["rows"]:
        return _(
            "No grant liability posted for this company. Either no grant has been "
            "received, or no Grant Liability Account is configured in Trust "
            "Compliance Settings."
        )
    currency = frappe.get_cached_value("Company", company, "default_currency")
    return _(
        "{0} received as grants, {1} recognised as income so far, {2} still "
        "outstanding as \"Grant Received in Advance\"."
    ).format(
        fmt_money(flt(report["total_received"]), currency=currency),
        fmt_money(flt(report["total_recognised"]), currency=currency),
        fmt_money(flt(report["total_balance"]), currency=currency),
    )


def _columns(company: str) -> list[dict]:
    currency_options = "Company:company:default_currency"
    return [
        {"fieldname": "fund", "label": _("Fund"), "fieldtype": "Link",
         "options": "Fund", "width": 110},
        {"fieldname": "fund_name", "label": _("Fund Name"), "fieldtype": "Data",
         "width": 200},
        {"fieldname": "received", "label": _("Received"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "recognised", "label": _("Recognised as Income"),
         "fieldtype": "Currency", "options": currency_options, "width": 160},
        {"fieldname": "balance", "label": _("Outstanding Balance"),
         "fieldtype": "Currency", "options": currency_options, "width": 150},
    ]

"""Fund Balances: opening, inflow, outflow and closing net assets per fund.

Thin adapter. All arithmetic is `core.fund_balance.build_fund_balances`, which is
unit-tested outside a bench.
"""

from __future__ import annotations

from frappe import _

from trust_compliance import queries
from trust_compliance.core.fund_balance import build_fund_balances


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    queries.require_company_read_permission(company)
    from_date, to_date = queries.window_for(filters)

    report = build_fund_balances(
        queries.gl_rows(company, upto=to_date),
        queries.funds(company),
        from_date=from_date,
        to_date=to_date,
    )

    data = []
    for row in report["rows"]:
        data.append(
            {
                "fund": row["fund"],
                "fund_name": row["fund_name"],
                "fund_class": row["fund_class"],
                "designation": _("FCRA") if row["is_fcra"] else _("Domestic"),
                "opening": row["opening"],
                "inflow": row["inflow"],
                "outflow": row["outflow"],
                "balance": row["balance"],
            }
        )

    data.append({})
    data.append(
        {
            "fund_name": _("Total"),
            "opening": report["total_opening"],
            "inflow": report["total_inflow"],
            "outflow": report["total_outflow"],
            "balance": report["total_balance"],
            "bold": 1,
        }
    )

    return _columns(company), data, _message(report)


def _message(report: dict) -> str:
    return _(
        "Net assets by fund. Only income, expense and equity movements count - asset "
        "and liability lines are the contra side of those and would double-count. "
        "Untagged lines are attributed to the default fund, so no money is missing "
        "from this report. Inter-fund transfers net to zero across all funds."
    )


def _columns(company: str) -> list[dict]:
    currency_options = "Company:company:default_currency"
    return [
        {"fieldname": "fund", "label": _("Fund"), "fieldtype": "Link",
         "options": "Fund", "width": 110},
        {"fieldname": "fund_name", "label": _("Fund Name"), "fieldtype": "Data",
         "width": 200},
        {"fieldname": "fund_class", "label": _("Class"), "fieldtype": "Data",
         "width": 110},
        {"fieldname": "designation", "label": _("Source"), "fieldtype": "Data",
         "width": 90},
        {"fieldname": "opening", "label": _("Opening"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "inflow", "label": _("Inflow"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "outflow", "label": _("Outflow"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "balance", "label": _("Closing Balance"), "fieldtype": "Currency",
         "options": currency_options, "width": 140},
    ]

"""Fund-wise Income & Expenditure: the statement a Trust's accounts must show per fund.

Rendered as an indented tree - fund, then its income accounts, then its expense
accounts, then surplus or deficit - because that is how the statement is read and
signed off, not as a flat table.
"""

from __future__ import annotations

from frappe import _

from trust_compliance import queries
from trust_compliance.core.fund_balance import build_fund_income_expenditure


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    from_date, to_date = queries.window_for(filters)

    report = build_fund_income_expenditure(
        queries.gl_rows(company, upto=to_date),
        queries.funds(company),
        from_date=from_date,
        to_date=to_date,
    )

    wanted_fund = filters.get("fund")
    statements = [
        statement
        for statement in report["funds"]
        if not wanted_fund or statement["fund"] == wanted_fund
    ]

    data: list[dict] = []
    for statement in statements:
        data.append(
            {
                "particulars": f"{statement['fund']} - {statement['fund_name']}",
                "fund_class": statement["fund_class"],
                "designation": _("FCRA") if statement["is_fcra"] else _("Domestic"),
                "indent": 0,
                "bold": 1,
            }
        )

        data.append({"particulars": _("Income"), "indent": 1, "bold": 1})
        for row in statement["income"]:
            data.append({"particulars": row["account"], "income": row["amount"],
                         "indent": 2})
        data.append({"particulars": _("Total Income"), "income": statement["total_income"],
                     "indent": 1, "bold": 1})

        data.append({"particulars": _("Expenditure"), "indent": 1, "bold": 1})
        for row in statement["expense"]:
            data.append({"particulars": row["account"], "expense": row["amount"],
                         "indent": 2})
        data.append({"particulars": _("Total Expenditure"),
                     "expense": statement["total_expense"], "indent": 1, "bold": 1})

        surplus = statement["surplus"]
        data.append(
            {
                "particulars": _("Surplus") if surplus >= 0 else _("Deficit"),
                "surplus": surplus,
                "indent": 1,
                "bold": 1,
            }
        )
        data.append({})

    if not wanted_fund:
        data.append(
            {
                "particulars": _("All Funds"),
                "income": report["total_income"],
                "expense": report["total_expense"],
                "surplus": report["total_surplus"],
                "indent": 0,
                "bold": 1,
            }
        )

    message = _(
        "Income and expenditure of the year, per fund. Equity movements - corpus "
        "contributions and inter-fund transfers - are excluded by construction: "
        "neither is income or expenditure of the year. A refund reduces the line it "
        "belongs to rather than appearing as the opposite kind of activity."
    )
    return _columns(), data, message


def _columns() -> list[dict]:
    currency_options = "Company:company:default_currency"
    return [
        {"fieldname": "particulars", "label": _("Particulars"), "fieldtype": "Data",
         "width": 340},
        {"fieldname": "fund_class", "label": _("Class"), "fieldtype": "Data", "width": 110},
        {"fieldname": "designation", "label": _("Source"), "fieldtype": "Data", "width": 90},
        {"fieldname": "income", "label": _("Income"), "fieldtype": "Currency",
         "options": currency_options, "width": 140},
        {"fieldname": "expense", "label": _("Expenditure"), "fieldtype": "Currency",
         "options": currency_options, "width": 140},
        {"fieldname": "surplus", "label": _("Surplus / (Deficit)"), "fieldtype": "Currency",
         "options": currency_options, "width": 160},
    ]

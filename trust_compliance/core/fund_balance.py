"""Fund-wise net-asset movement and fund-wise Income & Expenditure.

Pure module: no frappe import. Ported from `buildFundBalances` and
`buildFundIncomeExpenditure` in `src/lib/accounting.ts`.

Input is a flat sequence of GL rows so the caller can feed it either ERPNext
`GL Entry` records or fixtures:

    {"account": str, "root_type": str, "debit": float, "credit": float,
     "fund": str | None, "posting_date": date}
"""

from __future__ import annotations

import datetime
from typing import Iterable, Mapping, Sequence

GLRow = Mapping[str, object]
FundRow = Mapping[str, object]

#: Account root types that carry net assets. Asset and liability rows are the
#: contra side of these and would double-count every movement.
NET_ASSET_ROOT_TYPES = frozenset({"Income", "Expense", "Equity"})


def round_money(value: float) -> float:
    """Two-decimal rounding, matching the ERP's `roundMoney` and Decimal(18, 2)."""
    return round(value + 0.0, 2)


def _as_date(value: object) -> datetime.date | None:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return datetime.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def build_fund_balances(
    gl_rows: Iterable[GLRow],
    funds: Sequence[FundRow],
    from_date: object = None,
    to_date: object = None,
) -> dict:
    """Opening / inflow / outflow / closing per fund, on a net-asset basis.

    A fund is a net-asset bucket, so a row is classified by the *direction* of
    its net movement rather than by account type alone. Credit is the net-asset
    direction for everything that reaches here: an income or equity credit adds
    to the fund, an expense debit takes from it. Classifying by direction (rather
    than by "income means inflow") is what makes the source leg of an inter-fund
    transfer visible - that leg is a debit on the Inter-fund Transfers equity
    clearing account, tagged to the fund the money leaves, and it correctly
    *reduces* that fund. Symmetrically an expense credit - a refund or a
    reversal - is an inflow.

    Untagged rows, and rows naming a fund that has left the master, attribute to
    the default fund, so money never disappears from the report even though the
    dimension is nullable in the database.
    """
    window_from = _as_date(from_date)
    window_to = _as_date(to_date)

    default_fund = next(
        (fund for fund in funds if fund.get("is_default")), funds[0] if funds else None
    )

    rows: dict[str, dict] = {
        str(fund["name"]): {
            "fund": str(fund["name"]),
            "fund_name": fund.get("fund_name") or fund["name"],
            "fund_class": fund.get("fund_class"),
            "is_fcra": bool(fund.get("is_fcra")),
            "is_default": bool(fund.get("is_default")),
            "opening": 0.0,
            "inflow": 0.0,
            "outflow": 0.0,
            "balance": 0.0,
        }
        for fund in funds
    }

    for gl in gl_rows:
        if str(gl.get("root_type")) not in NET_ASSET_ROOT_TYPES:
            continue

        posting_date = _as_date(gl.get("posting_date"))
        if window_to and posting_date and posting_date > window_to:
            continue

        fund_name = gl.get("fund")
        row = rows.get(fund_name) if isinstance(fund_name, str) else None
        if row is None and default_fund is not None:
            row = rows.get(str(default_fund["name"]))
        if row is None:
            continue

        net = round_money(float(gl.get("credit") or 0) - float(gl.get("debit") or 0))
        inflow = net if net > 0 else 0.0
        outflow = round_money(-net) if net < 0 else 0.0

        if window_from and posting_date and posting_date < window_from:
            row["opening"] = round_money(row["opening"] + inflow - outflow)
            continue

        row["inflow"] = round_money(row["inflow"] + inflow)
        row["outflow"] = round_money(row["outflow"] + outflow)

    ordered = sorted(rows.values(), key=lambda row: row["fund"])
    for row in ordered:
        row["balance"] = round_money(row["opening"] + row["inflow"] - row["outflow"])

    return {
        "rows": ordered,
        "total_opening": round_money(sum(row["opening"] for row in ordered)),
        "total_inflow": round_money(sum(row["inflow"] for row in ordered)),
        "total_outflow": round_money(sum(row["outflow"] for row in ordered)),
        "total_balance": round_money(sum(row["balance"] for row in ordered)),
    }


def build_fund_income_expenditure(
    gl_rows: Iterable[GLRow],
    funds: Sequence[FundRow],
    from_date: object = None,
    to_date: object = None,
) -> dict:
    """Fund-wise Income & Expenditure: account-level income and expense per fund.

    Only income and expense accounts appear - equity (corpus contributions and
    inter-fund transfers) is excluded by construction, because neither is income
    or expenditure of the year. Income rows are credits net of debits and expense
    rows are debits net of credits, so a refund reduces the line it belongs to
    instead of appearing as the opposite kind of activity.
    """
    window_from = _as_date(from_date)
    window_to = _as_date(to_date)

    default_fund = next(
        (fund for fund in funds if fund.get("is_default")), funds[0] if funds else None
    )
    fund_names = {str(fund["name"]) for fund in funds}

    per_fund: dict[str, dict] = {}

    for gl in gl_rows:
        root_type = str(gl.get("root_type"))
        if root_type not in {"Income", "Expense"}:
            continue

        posting_date = _as_date(gl.get("posting_date"))
        if window_to and posting_date and posting_date > window_to:
            continue
        if window_from and posting_date and posting_date < window_from:
            continue

        fund_name = gl.get("fund")
        if not isinstance(fund_name, str) or fund_name not in fund_names:
            fund_name = str(default_fund["name"]) if default_fund else None
        if fund_name is None:
            continue

        bucket = per_fund.setdefault(
            fund_name, {"fund": fund_name, "income": {}, "expense": {}}
        )
        account = str(gl.get("account"))
        debit = float(gl.get("debit") or 0)
        credit = float(gl.get("credit") or 0)

        if root_type == "Income":
            bucket["income"][account] = round_money(
                bucket["income"].get(account, 0.0) + credit - debit
            )
        else:
            bucket["expense"][account] = round_money(
                bucket["expense"].get(account, 0.0) + debit - credit
            )

    fund_meta = {str(fund["name"]): fund for fund in funds}
    statements = []
    for fund_name in sorted(per_fund):
        bucket = per_fund[fund_name]
        income_rows = [
            {"account": account, "amount": amount}
            for account, amount in sorted(bucket["income"].items())
        ]
        expense_rows = [
            {"account": account, "amount": amount}
            for account, amount in sorted(bucket["expense"].items())
        ]
        total_income = round_money(sum(row["amount"] for row in income_rows))
        total_expense = round_money(sum(row["amount"] for row in expense_rows))
        meta = fund_meta.get(fund_name, {})
        statements.append(
            {
                "fund": fund_name,
                "fund_name": meta.get("fund_name") or fund_name,
                "fund_class": meta.get("fund_class"),
                "is_fcra": bool(meta.get("is_fcra")),
                "income": income_rows,
                "expense": expense_rows,
                "total_income": total_income,
                "total_expense": total_expense,
                "surplus": round_money(total_income - total_expense),
            }
        )

    return {
        "funds": statements,
        "total_income": round_money(
            sum(statement["total_income"] for statement in statements)
        ),
        "total_expense": round_money(
            sum(statement["total_expense"] for statement in statements)
        ),
        "total_surplus": round_money(sum(statement["surplus"] for statement in statements)),
    }

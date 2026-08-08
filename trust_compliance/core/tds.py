"""TDS Payable: tax the Trust itself deducts, and has not yet remitted.

Pure module, added following the 08-Aug review of SSSCT's real audited
accounts: TDS Payable exists there as a real liability alongside TDS
Receivable, but the app only modelled the receivable side (tax a bank deducts
on the Trust's own investment income - see `core/investment.py`).

Deliberately does not reinvent deduction. ERPNext's own Tax Withholding
Category, applied on a Purchase Invoice or Payment Entry, already deducts TDS
on a payment to a contractor, professional or employee and posts it to
whichever liability account that category names - that mechanism is not
duplicated here. What was missing was visibility: a fund-tagged schedule of
what has been deducted and what remains to be remitted to the government,
mirroring the Investment Register's TDS column on the receivable side. This
module is the arithmetic for that schedule; `queries.py` and the TDS Payable
Register report supply the ledger and the account.

Structurally identical to `core.grant.build_grant_register` - a credit is the
liability increasing (deducted, not yet remitted), a debit is the liability
decreasing (remitted). Kept as a separate, duplicated function rather than a
shared one: this is the second such register, not the third, and a TDS
schedule is likely to grow its own columns (challan number, section, TAN) that
a grant schedule never will.
"""

from __future__ import annotations

import datetime
from typing import Iterable, Mapping, Sequence

GLRow = Mapping[str, object]
FundRow = Mapping[str, object]


def round_money(value: float) -> float:
    """Two-decimal rounding, matching `fund_balance.round_money` / Decimal(18, 2)."""
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


def build_tds_payable_register(
    gl_rows: Iterable[GLRow],
    funds: Sequence[FundRow],
    as_on: object = None,
) -> dict:
    """Per-fund TDS payable: deducted, remitted, outstanding balance.

    `gl_rows` must already be filtered to the TDS payable account - this module
    does not know which account that is. Rows naming no fund are still totalled
    under an empty key rather than dropped, because most TDS deduction on a
    vendor payment will not carry the fund dimension until the paying document
    is tagged, and a schedule that silently dropped them would understate the
    liability rather than surface the gap.
    """
    window_to = _as_date(as_on)
    fund_meta = {str(fund["name"]): fund for fund in funds}

    rows: dict[object, dict] = {}
    for gl in gl_rows:
        posting_date = _as_date(gl.get("posting_date"))
        if window_to and posting_date and posting_date > window_to:
            continue

        fund_name = gl.get("fund")
        key = fund_name if isinstance(fund_name, str) and fund_name else None
        row = rows.setdefault(
            key,
            {
                "fund": key,
                "fund_name": fund_meta.get(key, {}).get("fund_name") or key,
                "deducted": 0.0,
                "remitted": 0.0,
                "balance": 0.0,
            },
        )
        row["deducted"] = round_money(row["deducted"] + float(gl.get("credit") or 0))
        row["remitted"] = round_money(row["remitted"] + float(gl.get("debit") or 0))

    ordered = sorted(rows.values(), key=lambda row: (row["fund"] is None, str(row["fund"])))
    for row in ordered:
        row["balance"] = round_money(row["deducted"] - row["remitted"])

    return {
        "rows": ordered,
        "total_deducted": round_money(sum(row["deducted"] for row in ordered)),
        "total_remitted": round_money(sum(row["remitted"] for row in ordered)),
        "total_balance": round_money(sum(row["balance"] for row in ordered)),
    }

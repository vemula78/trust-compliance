"""Deferred income for a restricted grant: received-but-not-yet-utilised.

Pure module: no frappe import, same convention as `fund_balance.py` and
`investment.py`. Added following the 08-Aug review of SSSCT's real audited
accounts, which showed restricted grant money carried as a liability ("Grant
Received in Advance") and recognised as income only as it is spent - not, as
the app previously modelled every restricted donation, as income of the year
it was received.

The mechanism is two documents, not one:
- `Trust Donation` with `is_grant` set credits the grant liability account
  instead of income (see `trust_donation.py`).
- `Grant Utilisation` later debits that liability and credits donation income,
  recognising exactly the amount utilised (see `grant_utilisation.py`).

This module has no opinion on which account is the grant liability account -
that is `queries.grant_liability_rows()`'s job, mirroring how `fund_balance.py`
takes `gl_rows` pre-filtered by the caller. It knows only what a credit and a
debit on that account mean: a credit is a grant received and not yet
recognised; a debit is income recognised, whether by a Grant Utilisation or by
the reversal of a cancelled donation.
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


def build_grant_register(
    gl_rows: Iterable[GLRow],
    funds: Sequence[FundRow],
    as_on: object = None,
) -> dict:
    """Per-fund grant liability: received, recognised, outstanding balance.

    `gl_rows` must already be filtered to the grant liability account - this
    module does not know which account that is. Only Restricted-class funds are
    expected to appear (`_validate_grant` refuses any other class), but a row
    naming a fund of another class is still totalled rather than dropped, so a
    stale or misconfigured entry is visible on the register instead of silently
    missing from it.
    """
    window_to = _as_date(as_on)
    fund_meta = {str(fund["name"]): fund for fund in funds}

    rows: dict[str, dict] = {}
    for gl in gl_rows:
        posting_date = _as_date(gl.get("posting_date"))
        if window_to and posting_date and posting_date > window_to:
            continue

        fund_name = gl.get("fund")
        if not isinstance(fund_name, str):
            continue
        row = rows.setdefault(
            fund_name,
            {
                "fund": fund_name,
                "fund_name": fund_meta.get(fund_name, {}).get("fund_name") or fund_name,
                "received": 0.0,
                "recognised": 0.0,
                "balance": 0.0,
            },
        )
        row["received"] = round_money(row["received"] + float(gl.get("credit") or 0))
        row["recognised"] = round_money(row["recognised"] + float(gl.get("debit") or 0))

    ordered = sorted(rows.values(), key=lambda row: row["fund"])
    for row in ordered:
        row["balance"] = round_money(row["received"] - row["recognised"])

    return {
        "rows": ordered,
        "total_received": round_money(sum(row["received"] for row in ordered)),
        "total_recognised": round_money(sum(row["recognised"] for row in ordered)),
        "total_balance": round_money(sum(row["balance"] for row in ordered)),
    }


def validate_grant_utilisation(amount: float, outstanding_balance: float) -> list[str]:
    """Refusal reasons for a proposed Grant Utilisation.

    Kept separate from the balance query itself (which needs the ORM) so the
    arithmetic rule - a utilisation cannot recognise more than the fund's
    outstanding grant liability - is tested without one.
    """
    errors: list[str] = []
    if float(amount) <= 0:
        errors.append("Utilisation amount must be greater than zero.")
    if float(amount) > round_money(float(outstanding_balance)):
        errors.append(
            f"Only {round_money(outstanding_balance):.2f} of grant liability is "
            f"outstanding on this fund; a utilisation of {round_money(amount):.2f} "
            "would recognise more income than the fund has received as grants."
        )
    return errors

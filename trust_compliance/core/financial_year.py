"""Indian financial year and gap-free receipt numbering.

Pure module: no frappe import, so it is unit-testable outside a bench.
Ported from `src/lib/accounting.ts` (`financialYearOf`, `nextDonationReceiptNo`)
in the Next.js Trust ERP, deliberately preserving the same edge-case behaviour.
"""

from __future__ import annotations

import datetime
import re

FY_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")
_DATE_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _as_date(value: object) -> datetime.date:
    """Coerce a date-like to `datetime.date`, rejecting anything that is not a real day.

    Frappe hands dates over as `datetime.date`, `datetime.datetime` or an ISO
    string depending on where they came from, so all three are accepted. A
    non-date is rejected rather than normalised: a receipt numbered against a
    financial year derived from "2026-02-30" is not recoverable once issued.
    """
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        match = _DATE_PATTERN.match(value.strip()[:10])
        if not match:
            raise ValueError(f'Cannot derive a financial year from "{value}".')
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime.date(year, month, day)
        except ValueError as exc:  # 2026-02-30 and friends
            raise ValueError(f'Cannot derive a financial year from "{value}".') from exc
    raise ValueError(f'Cannot derive a financial year from "{value!r}".')


def financial_year_of(value: object) -> str:
    """Financial-year label (April-March) for a date.

    15-Mar-2027 falls in "2026-27"; 01-Apr-2027 starts "2027-28".
    """
    date = _as_date(value)
    start_year = date.year if date.month >= 4 else date.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def is_financial_year(value: object) -> bool:
    """True for a well-formed, self-consistent FY label such as "2026-27"."""
    if not isinstance(value, str):
        return False
    match = FY_PATTERN.match(value.strip())
    if not match:
        return False
    start_year, end_short = int(match.group(1)), int(match.group(2))
    return (start_year + 1) % 100 == end_short


def financial_year_window(financial_year: str) -> tuple[datetime.date, datetime.date]:
    """Inclusive (from, to) dates of a financial year label."""
    if not is_financial_year(financial_year):
        raise ValueError(
            f'"{financial_year}" is not an Indian financial year such as "2026-27".'
        )
    start_year = int(FY_PATTERN.match(financial_year.strip()).group(1))
    return datetime.date(start_year, 4, 1), datetime.date(start_year + 1, 3, 31)


def next_receipt_no(
    existing: list[str], financial_year: str, prefix: str = "80G", width: int = 4
) -> str:
    """Next gap-free receipt number for a financial year: `<prefix>/<FY>/<seq>`.

    The sequence is `max(count_of_receipts_in_year, highest_sequence_issued) + 1`,
    so a hole in the series (a cancelled receipt) can never re-issue a number that
    was already used. Callers must allocate this under a row lock and rely on a
    unique constraint on the receipt number as the final arbiter.
    """
    if not is_financial_year(financial_year):
        raise ValueError(
            f'"{financial_year}" is not an Indian financial year such as "2026-27".'
        )

    series = f"{prefix}/{financial_year}/"
    in_year = [no for no in existing if isinstance(no, str) and no.startswith(series)]

    highest = 0
    for receipt_no in in_year:
        tail = receipt_no[len(series) :]
        if tail.isdigit():
            highest = max(highest, int(tail))

    return f"{series}{max(len(in_year), highest) + 1:0{width}d}"

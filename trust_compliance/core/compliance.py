"""Trust statutory compliance computations.

Pure module: no frappe import. Ported from `buildFCRARegister`,
`buildIncomeApplication`, `buildForm10BD` and `buildDonationRegister` in
`src/lib/accounting.ts`, preserving their bases of measurement.

All four take flat sequences of mappings so they can be driven from ERPNext
records or from fixtures:

    gl_rows      {"account", "root_type", "is_administrative", "debit",
                  "credit", "fund", "posting_date", "voucher_no", "remarks"}
    donations    {"name", "receipt_no", "donation_date", "donor", "donor_name",
                  "donor_type", "donor_pan", "donor_address", "donor_country",
                  "amount", "mode", "fund", "is_corpus", "is_anonymous",
                  "purpose"}
"""

from __future__ import annotations

import datetime
from typing import Iterable, Mapping, Sequence

from .fund_balance import _as_date, round_money

GLRow = Mapping[str, object]
DonationRow = Mapping[str, object]
FundRow = Mapping[str, object]

#: FCRA section 8(1)(b) cap on administrative expenditure, as a percentage of
#: foreign contribution received in the financial year.
FCRA_ADMIN_CAP_PERCENT = 20.0

#: Section 11(1)(a) application-of-income requirement for a 12A/12AB trust.
REQUIRED_APPLICATION_RATIO = 0.85

#: Section 115BBC: anonymous donations above this are taxed at the maximum
#: marginal rate, subject to the 5%-of-total-donations alternative.
ANONYMOUS_DONATION_THRESHOLD = 100_000.0
ANONYMOUS_DONATION_ALTERNATIVE_RATIO = 0.05


def _in_window(
    value: object, from_date: datetime.date | None, to_date: datetime.date | None
) -> bool:
    date = _as_date(value)
    if date is None:
        return True
    if from_date and date < from_date:
        return False
    return not (to_date and date > to_date)


def build_fcra_register(
    gl_rows: Iterable[GLRow],
    donations: Iterable[DonationRow],
    funds: Sequence[FundRow],
    from_date: object = None,
    to_date: object = None,
) -> dict:
    """Foreign contribution register and FC-4 data pack.

    `receipts` is the register's contributor-wise detail table: one row per
    receipted donation into an FCRA fund, which is what FC-4 lists.
    `utilizations` is every expense row tagged to an FCRA fund, carrying the
    account's administrative classification so the cap can be measured.

    The summary is built entirely from GL rows on the same net-asset basis as
    `build_fund_balances`, so opening, receipts and closing read one source and
    agree by construction. Foreign contribution posted by journal entry rather
    than through the donation register therefore still counts in the year it
    arrives, even though it has no row in the detail table; `donation_receipts`
    carries the detail table's total so the two can be compared.
    """
    window_from = _as_date(from_date)
    window_to = _as_date(to_date)

    fcra_fund_names = {
        str(fund["name"]) for fund in funds if fund.get("is_fcra")
    }
    fund_meta = {str(fund["name"]): fund for fund in funds}
    default_fund = next(
        (fund for fund in funds if fund.get("is_default")), funds[0] if funds else None
    )

    receipts = [
        {
            "donation": donation.get("name"),
            "receipt_no": donation.get("receipt_no"),
            "donation_date": donation.get("donation_date"),
            "donor": donation.get("donor"),
            "donor_name": donation.get("donor_name") or "Unknown donor",
            "donor_type": donation.get("donor_type") or "Foreign",
            "donor_address": donation.get("donor_address"),
            "donor_country": donation.get("donor_country"),
            "purpose": donation.get("purpose"),
            "amount": round_money(float(donation.get("amount") or 0)),
            "mode": donation.get("mode"),
            "fund": donation.get("fund"),
            "is_corpus": bool(donation.get("is_corpus")),
        }
        for donation in donations
        if str(donation.get("fund")) in fcra_fund_names
        and _in_window(donation.get("donation_date"), window_from, window_to)
    ]
    receipts.sort(key=lambda row: (str(row["donation_date"]), str(row["receipt_no"])))

    utilizations: list[dict] = []
    opening_balance = 0.0
    journal_receipts = 0.0

    for gl in gl_rows:
        root_type = str(gl.get("root_type"))
        if root_type in {"Asset", "Liability"}:
            # Contra side of the movements below; counting them would double-count.
            continue

        fund_name = gl.get("fund")
        if not isinstance(fund_name, str) or fund_name not in fund_meta:
            fund_name = str(default_fund["name"]) if default_fund else None
        if fund_name not in fcra_fund_names:
            continue

        posting_date = _as_date(gl.get("posting_date"))
        if window_to and posting_date and posting_date > window_to:
            continue
        is_opening = bool(window_from and posting_date and posting_date < window_from)

        debit = float(gl.get("debit") or 0)
        credit = float(gl.get("credit") or 0)

        if root_type != "Expense":
            # Income and equity credits are the inflows: before the window they
            # form the opening balance, inside it they are the year's receipts.
            inflow = round_money(credit - debit)
            if is_opening:
                opening_balance = round_money(opening_balance + inflow)
            else:
                journal_receipts = round_money(journal_receipts + inflow)
            continue

        amount = round_money(debit - credit)
        if amount == 0:
            continue

        if is_opening:
            opening_balance = round_money(opening_balance - amount)
            continue

        utilizations.append(
            {
                "voucher_no": gl.get("voucher_no"),
                "posting_date": gl.get("posting_date"),
                "account": gl.get("account"),
                "fund": fund_name,
                "remarks": gl.get("remarks"),
                "amount": amount,
                "is_administrative": bool(gl.get("is_administrative")),
            }
        )

    utilizations.sort(
        key=lambda row: (str(row["posting_date"]), str(row["voucher_no"] or ""))
    )

    donation_receipts = round_money(sum(row["amount"] for row in receipts))
    utilized = round_money(sum(row["amount"] for row in utilizations))
    admin_utilized = round_money(
        sum(row["amount"] for row in utilizations if row["is_administrative"])
    )
    # The cap is measured against foreign contribution *received* in the year,
    # not against what was utilised out of it.
    admin_percent = (
        round_money(admin_utilized / journal_receipts * 100)
        if journal_receipts > 0
        else 0.0
    )

    return {
        "from_date": window_from,
        "to_date": window_to,
        "receipts": receipts,
        "utilizations": utilizations,
        "summary": {
            "opening_balance": opening_balance,
            "receipts": journal_receipts,
            "journal_receipts": journal_receipts,
            "donation_receipts": donation_receipts,
            "utilized": utilized,
            "admin_utilized": admin_utilized,
            "admin_percent": admin_percent,
            "admin_cap_exceeded": admin_percent > FCRA_ADMIN_CAP_PERCENT,
            "closing_balance": round_money(
                opening_balance + journal_receipts - utilized
            ),
        },
    }


def build_income_application(
    gl_rows: Iterable[GLRow],
    capital_additions: Iterable[Mapping[str, object]] = (),
    accumulations: Iterable[Mapping[str, object]] = (),
    from_date: object = None,
    to_date: object = None,
) -> dict:
    """85% application-of-income tracking for a 12A/12AB registered trust.

    Income is income-account credits for the year, application is expense-account
    debits plus assets acquired in the year (capital expenditure counts as
    application), and accumulation is the Form 10 amounts set apart for that
    year. The trust is compliant when application plus accumulation reaches 85%
    of income.

    Deliberate simplification, unchanged from the Next.js implementation: the
    filed Form 10B computation carries further adjustments this does not model -
    corpus donations excluded from income, the 15% permitted accumulation carried
    forward, application on a payment basis, depreciation disallowed on assets
    already claimed as application, and inter-charity donations. An in-kind
    donation also lands in both income and capital application here, since it
    credits donation income and capitalises an asset in one voucher. This is a
    working paper for the auditor, not the return.
    """
    window_from = _as_date(from_date)
    window_to = _as_date(to_date)

    total_income = 0.0
    applied_revenue = 0.0

    for gl in gl_rows:
        if not _in_window(gl.get("posting_date"), window_from, window_to):
            continue

        root_type = str(gl.get("root_type"))
        debit = float(gl.get("debit") or 0)
        credit = float(gl.get("credit") or 0)

        if root_type == "Income":
            total_income = round_money(total_income + round_money(credit - debit))
        elif root_type == "Expense":
            applied_revenue = round_money(applied_revenue + round_money(debit - credit))

    applied_capital = round_money(
        sum(
            float(addition.get("amount") or 0)
            for addition in capital_additions
            if _in_window(addition.get("date"), window_from, window_to)
        )
    )
    accumulated = round_money(
        sum(float(record.get("amount") or 0) for record in accumulations)
    )

    applied = round_money(applied_revenue + applied_capital)
    required = round_money(total_income * REQUIRED_APPLICATION_RATIO)
    shortfall = round_money(max(0.0, required - applied - accumulated))

    return {
        "from_date": window_from,
        "to_date": window_to,
        "total_income": total_income,
        "applied": applied,
        "applied_revenue": applied_revenue,
        "applied_capital": applied_capital,
        "accumulated": accumulated,
        "required_application": required,
        "application_percent": (
            0.0
            if total_income == 0
            else round_money((applied + accumulated) / total_income * 100)
        ),
        "shortfall": shortfall,
        "compliant": shortfall == 0,
    }


def build_donation_register(
    donations: Iterable[DonationRow],
    from_date: object = None,
    to_date: object = None,
) -> dict:
    """Donation register with Section 115BBC anonymous-donation monitoring.

    The 115BBC exposure is the excess of anonymous donations over the higher of
    ANONYMOUS_DONATION_THRESHOLD and 5% of total donations, which is the
    statutory alternative. Reporting both the threshold and the ratio makes the
    binding limb of the test visible instead of asserting one.
    """
    window_from = _as_date(from_date)
    window_to = _as_date(to_date)

    rows = [
        dict(donation)
        for donation in donations
        if _in_window(donation.get("donation_date"), window_from, window_to)
    ]
    rows.sort(key=lambda row: (str(row.get("donation_date")), str(row.get("receipt_no"))))

    total = round_money(sum(float(row.get("amount") or 0) for row in rows))
    anonymous = round_money(
        sum(float(row.get("amount") or 0) for row in rows if row.get("is_anonymous"))
    )
    corpus = round_money(
        sum(float(row.get("amount") or 0) for row in rows if row.get("is_corpus"))
    )
    exempt_limit = max(
        ANONYMOUS_DONATION_THRESHOLD, round_money(total * ANONYMOUS_DONATION_ALTERNATIVE_RATIO)
    )

    return {
        "from_date": window_from,
        "to_date": window_to,
        "rows": rows,
        "summary": {
            "count": len(rows),
            "total": total,
            "corpus": corpus,
            "income": round_money(total - corpus),
            "anonymous": anonymous,
            "anonymous_exempt_limit": round_money(exempt_limit),
            "anonymous_taxable": round_money(max(0.0, anonymous - exempt_limit)),
            "anonymous_threshold_breached": anonymous > exempt_limit,
        },
    }


def build_form_10bd(
    donations: Iterable[DonationRow],
    from_date: object = None,
    to_date: object = None,
) -> dict:
    """Form 10BD donor statement: one row per donor per donation-type per mode.

    Anonymous donations carry no donor to report, so they are excluded from the
    rows but disclosed as a total, which is what lets the statement reconcile to
    the donation register. A donor with no PAN is flagged rather than dropped:
    Form 10BD cannot be filed without an identification number, so the gap has
    to be visible to whoever files.

    `donation_type` is "Corpus" when the donation is a corpus contribution,
    otherwise "Others". "Specific grant" is never derived automatically.
    """
    window_from = _as_date(from_date)
    window_to = _as_date(to_date)

    groups: dict[tuple, dict] = {}
    anonymous_total = 0.0

    for donation in donations:
        if not _in_window(donation.get("donation_date"), window_from, window_to):
            continue

        amount = round_money(float(donation.get("amount") or 0))

        if donation.get("is_anonymous"):
            anonymous_total = round_money(anonymous_total + amount)
            continue

        donation_type = "Corpus" if donation.get("is_corpus") else "Others"
        mode = "Cash" if str(donation.get("mode")) == "Cash" else "Others"
        key = (str(donation.get("donor")), donation_type, mode)

        group = groups.setdefault(
            key,
            {
                "donor": donation.get("donor"),
                "donor_name": donation.get("donor_name"),
                "donor_type": donation.get("donor_type"),
                "pan": (donation.get("donor_pan") or "") or None,
                "address": donation.get("donor_address"),
                "donation_type": donation_type,
                "mode": mode,
                "amount": 0.0,
                "receipt_count": 0,
            },
        )
        group["amount"] = round_money(group["amount"] + amount)
        group["receipt_count"] += 1

    rows = sorted(
        groups.values(),
        key=lambda row: (str(row["donor_name"] or ""), row["donation_type"], row["mode"]),
    )
    for row in rows:
        row["pan_missing"] = not row["pan"]

    return {
        "from_date": window_from,
        "to_date": window_to,
        "rows": rows,
        "summary": {
            "donor_rows": len(rows),
            "reported_total": round_money(sum(row["amount"] for row in rows)),
            "anonymous_total": anonymous_total,
            "rows_missing_pan": sum(1 for row in rows if row["pan_missing"]),
        },
    }

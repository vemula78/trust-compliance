"""Section 11(5) / Rule 17C investment-of-corpus compliance.

Pure module: no frappe import. A 12A/12AB trust may invest its corpus and
accumulated income only in the forms and modes listed in section 11(5) of the
Income-tax Act 1961, as extended by Rule 17C of the Income-tax Rules 1962.
Investing outside them turns that income into "specified income" taxed at the
maximum marginal rate under section 115BBI (and risks 12AB(4) cancellation on
repeat or wilful breach), so this module refuses a non-permitted mode rather
than merely flagging it.

Callers pass plain mappings for investments, funds and transactions - the same
convention as `segregation.py` and `compliance.py` - so this stays testable
without an ORM and can be driven from ERPNext records or from fixtures.
"""

from __future__ import annotations

import datetime
from typing import Iterable, Mapping, Sequence

from .financial_year import financial_year_of, financial_year_window

Investment = Mapping[str, object]
FundRow = Mapping[str, object]
Transaction = Mapping[str, object]

#: Modes of investment/deposit listed directly in section 11(5). Sub-clause
#: numbering follows the Act, which has been stable, so these carry
#: `verified: True` - the clause number may be cited on a schedule.
#:
#: (vii) is the only clause admitting equity, and only equity of a public sector
#: company, which is why it alone carries `allows_equity: True`. It is NOT marked
#: speculative: the clause covers deposits and bonds of a public sector company
#: as well as its shares, and a PSU deposit is not speculative. Speculation is
#: judged on the instrument (`is_equity`), not on the clause - see
#: `validate_investment_mode`.
SECTION_11_5_MODES: dict[str, dict] = {
    "11(5)(i)": {
        "clause": "11(5)(i)",
        "verified": True,
        "label": "Government savings certificates and other Central Government securities",
        "is_speculative": False,
        "allows_equity": False,
    },
    "11(5)(ii)": {
        "clause": "11(5)(ii)",
        "verified": True,
        "label": "Post Office Savings Bank deposit",
        "is_speculative": False,
        "allows_equity": False,
    },
    "11(5)(iii)": {
        "clause": "11(5)(iii)",
        "verified": True,
        "label": "Deposit with a scheduled bank or a co-operative society carrying on banking business",
        "is_speculative": False,
        "allows_equity": False,
    },
    "11(5)(iv)": {
        "clause": "11(5)(iv)",
        "verified": True,
        "label": "Units of the Unit Trust of India",
        "is_speculative": False,
        "allows_equity": False,
    },
    "11(5)(v)": {
        "clause": "11(5)(v)",
        "verified": True,
        "label": "State Government or Central Government security",
        "is_speculative": False,
        "allows_equity": False,
    },
    "11(5)(vi)": {
        "clause": "11(5)(vi)",
        "verified": True,
        "label": "Debentures with principal and interest guaranteed by Central or State Government",
        "is_speculative": False,
        "allows_equity": False,
    },
    "11(5)(vii)": {
        "clause": "11(5)(vii)",
        "verified": True,
        "label": "Deposit or investment, including equity shares, in a public sector company",
        "is_speculative": False,
        "allows_equity": True,
    },
    "11(5)(viii)": {
        "clause": "11(5)(viii)",
        "verified": True,
        "label": "Bonds of an approved financial corporation providing long-term industrial finance",
        "is_speculative": False,
        "allows_equity": False,
    },
    "11(5)(ix)": {
        "clause": "11(5)(ix)",
        "verified": True,
        "label": "Bonds of an approved public company providing long-term housing or urban infrastructure finance",
        "is_speculative": False,
        "allows_equity": False,
    },
    "11(5)(x)": {
        "clause": "11(5)(x)",
        "verified": True,
        "label": "Immovable property",
        "is_speculative": False,
        "allows_equity": False,
    },
    "11(5)(xi)": {
        "clause": "11(5)(xi)",
        "verified": True,
        "label": "Deposit with the Industrial Development Bank of India",
        "is_speculative": False,
        "allows_equity": False,
    },
}

#: Additional modes prescribed under section 11(5)(xii) by Rule 17C.
#:
#: **These sub-clause numbers are NOT verified against the current notified text
#: of Rule 17C**, which has been amended repeatedly since 1973. They therefore
#: carry `verified: False`, and the Investment Register warns when book value
#: sits under an unverified clause. That matters: a wrong statutory citation on
#: an audit schedule or a Form 10B annexure is worse than no citation, because a
#: reader takes it at face value. The Trust's auditor should confirm each clause
#: against the notified rule and correct the Investment Mode master, which exists
#: to be edited for exactly this reason.
RULE_17C_MODES: dict[str, dict] = {
    "17C(i)": {
        "clause": "17C(i)",
        "verified": False,
        "label": "Units of a mutual fund scheme referred to in section 10(23D)",
        "is_speculative": True,
        "allows_equity": False,
    },
    "17C(ii)": {
        "clause": "17C(ii)",
        "verified": False,
        "label": "Deposit with an authority constituted for housing accommodation, or for planning, development or improvement of cities, towns or villages",
        "is_speculative": False,
        "allows_equity": False,
    },
    "17C(iii)": {
        "clause": "17C(iii)",
        "verified": False,
        "label": "Deposit with, or investment in bonds of, a public financial institution",
        "is_speculative": False,
        "allows_equity": False,
    },
    "17C(iv)": {
        "clause": "17C(iv)",
        "verified": False,
        "label": "Investment in immovable property held wholly for charitable purposes, including a religious purpose",
        "is_speculative": False,
        "allows_equity": False,
    },
    "17C(v)": {
        "clause": "17C(v)",
        "verified": False,
        "label": "Deposit made by an employer-trust with LIC under an approved gratuity or superannuation fund",
        "is_speculative": False,
        "allows_equity": False,
    },
}

#: Merged view of every permitted mode, keyed by clause. This is what
#: `is_permitted_mode` and `validate_investment_mode` test against.
PERMITTED_MODES: dict[str, dict] = {**SECTION_11_5_MODES, **RULE_17C_MODES}

#: Transaction kinds and the register bucket they classify into. Interest and
#: dividend are always income of the year - see `classify_investment_income`.
_INCOME_KINDS = frozenset({"Interest", "Dividend"})
_ASSET_KINDS = frozenset({"Purchase", "Redemption", "Maturity"})


def round_money(value: float) -> float:
    """Two-decimal rounding, matching `fund_balance.round_money` / Decimal(18, 2)."""
    return round(value + 0.0, 2)


def _as_date(value: object) -> datetime.date | None:
    """Coerce a date-like to `datetime.date`, or `None` if it cannot be read.

    Unlike `financial_year._as_date` this never raises: `as_on` and transaction
    dates are window bounds, not statutory facts, so a missing or malformed one
    is treated as "no bound" / "unfiled" rather than aborting the register.
    """
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


def is_permitted_mode(clause: str) -> bool:
    """True if `clause` is a section 11(5) or Rule 17C mode of investment."""
    return clause in PERMITTED_MODES


def validate_investment_mode(
    investment: Mapping, fund: Mapping, prohibited_parties: Iterable[str] = ()
) -> list[str]:
    """Return human-readable refusal reasons for a proposed or existing investment.

    Every rule is evaluated independently and all failing reasons are returned,
    because a single instrument can breach more than one rule at once (e.g. a
    non-PSU equity investment bought from a trustee's own company) and the
    person fixing it needs the whole list, not the first hit.

    investment: {"instrument_type", "mode_clause", "is_equity", "issuer",
                 "issuer_is_psu", "counterparty", "amount"}
    fund: {"name", "fund_class", "is_fcra"}
    """
    errors: list[str] = []

    clause = investment.get("mode_clause")
    mode = PERMITTED_MODES.get(str(clause))
    if mode is None:
        errors.append(
            f'"{clause}" is not a mode permitted under section 11(5) or Rule 17C; '
            "income from it is specified income taxed at the maximum marginal "
            "rate under section 115BBI."
        )

    # Speculation is a property of the instrument as much as of the mode: a
    # public sector company deposit under 11(5)(vii) is not speculative, its
    # equity shares are. Testing both is what stops an over-broad refusal of
    # FCRA money into a PSU bond while still refusing FCRA money into equity.
    speculative = bool(investment.get("is_equity")) or (
        mode is not None and bool(mode.get("is_speculative"))
    )
    if bool(fund.get("is_fcra")) and speculative:
        reason = (
            "the instrument is equity"
            if bool(investment.get("is_equity"))
            else f"mode {clause} ({mode.get('label') if mode else ''}) is speculative"
        )
        errors.append(
            f"Fund {fund.get('name')} holds foreign contribution; FCRA section "
            "8(1) and FCRR rule 4 forbid using foreign contribution for "
            f"speculative activity, and {reason}."
        )

    if bool(investment.get("is_equity")) and not bool(investment.get("issuer_is_psu")):
        errors.append(
            "Equity shares are a permitted investment only in a public sector "
            f"company under section 11(5)(vii); issuer {investment.get('issuer')} "
            "is not a public sector company."
        )

    counterparty = investment.get("counterparty")
    if counterparty is not None and counterparty in prohibited_parties:
        errors.append(
            f"Counterparty {counterparty} is a person of substantial interest "
            "under section 13(2)(h)/13(3) (a founder, trustee, substantial "
            "contributor, their relative, or a concern they control); the "
            "investment is refused."
        )

    if float(investment.get("amount") or 0) <= 0:
        errors.append("Investment amount must be greater than zero.")

    return errors


def classify_investment_income(kind: str) -> str:
    """Classify an investment transaction kind as "income" or "asset".

    Interest and dividend are income of the year, full stop - never corpus.
    Crediting corpus-FD interest back to the corpus fund would silently remove
    that amount from the section 11(1)(a) 85%-application test, which measures
    against income, so this classification is the one thing in the module that
    cannot be got wrong. Purchase, Redemption and Maturity move principal, not
    income, so they classify as "asset".

    There is deliberately no "corpus" outcome. No transaction on an investment
    creates corpus: corpus arises only from a donation given with that direction,
    and the absence of the branch is what makes "interest can never be corpus"
    structural rather than a rule someone could later relax.
    """
    if kind in _INCOME_KINDS:
        return "income"
    if kind in _ASSET_KINDS:
        return "asset"
    raise ValueError(f'Unknown investment transaction kind "{kind}".')


def split_interest_receipt(gross: float, tds: float) -> dict:
    """Split a gross interest receipt into gross, TDS and net.

    TDS deducted at source is a recoverable asset (credited against the
    trust's own tax liability or refunded) - not application of income - so it
    must never be netted off before the 85%-application test runs on gross
    income.
    """
    gross_amount = float(gross)
    tds_amount = float(tds)
    if gross_amount < 0 or tds_amount < 0:
        raise ValueError("Gross interest and TDS cannot be negative.")
    if tds_amount > gross_amount:
        raise ValueError("TDS cannot exceed the gross interest it was deducted from.")
    return {
        "gross": round_money(gross_amount),
        "tds": round_money(tds_amount),
        "net": round_money(gross_amount - tds_amount),
    }


def donated_share_disposal_deadline(received_on: object) -> datetime.date:
    """Deadline to dispose of shares received as a donation.

    Shares are not themselves a permitted mode of investment under section
    11(5)/Rule 17C (equity is permitted only as a fresh investment in a public
    sector company under (vii)), so shares arriving as an in-kind donation must
    be converted into a permitted form within one year from the *end* of the
    financial year in which they were received. Reusing `financial_year_of` /
    `financial_year_window` keeps this on the same April-March calendar as
    every other statutory deadline in the app, instead of a second FY
    implementation drifting out of step.
    """
    fy = financial_year_of(received_on)
    _, fy_end = financial_year_window(fy)
    return fy_end.replace(year=fy_end.year + 1)


def build_investment_register(
    investments: Iterable[Investment],
    transactions: Iterable[Transaction],
    funds: Sequence[FundRow],
    as_on: object = None,
    prohibited_parties: Iterable[str] = (),
) -> dict:
    """Investment register carried at cost, with compliance re-checked per row.

    Trusts carry investments at cost, not fair value, so `book_value` is cost
    less redemptions - no mark-to-market. `as_on` clips transactions to
    on-or-before that date, so the register can be reconstructed as of any past
    date rather than only as of today.

    Compliance is re-evaluated here, not only at the time of purchase: an
    auto-rollover of a fixed deposit or a Rule 17C amendment can turn a once-
    valid instrument non-compliant without any new transaction being posted, so
    a register that only remembered the purchase-time verdict would miss it.
    The re-check includes the section 13(2)(h)/13(3) prohibited-counterparty rule
    when `prohibited_parties` is supplied. It has to be re-run rather than trusted
    from purchase time, because a person can *become* a prohibited person after
    the investment was made - a donor crossing the substantial-contribution
    threshold, or a new trustee - which retrospectively taints income from an
    instrument that was clean when bought.

    transactions: {"investment", "kind", "date", "amount", "tds", "fund"}
    """
    window_to = _as_date(as_on)
    fund_meta = {str(fund["name"]): fund for fund in funds}

    transactions_by_investment: dict[object, list[Transaction]] = {}
    for transaction in transactions:
        transaction_date = _as_date(transaction.get("date"))
        if window_to and transaction_date and transaction_date > window_to:
            continue
        transactions_by_investment.setdefault(transaction.get("investment"), []).append(
            transaction
        )

    rows: list[dict] = []
    by_mode: dict[str, dict] = {}
    totals = {
        "cost": 0.0,
        "redeemed": 0.0,
        "book_value": 0.0,
        "income_earned": 0.0,
        "tds": 0.0,
        "non_compliant_book_value": 0.0,
    }

    for investment in investments:
        investment_id = investment.get("investment") or investment.get("name")
        # The investment record carries its own cost - a Trust Investment is
        # submitted with the amount it was bought for and posts its own funding
        # entry, so there is no separate "Purchase" transaction in the normal
        # flow. Any Purchase rows that do exist are additional tranches and add
        # on top, which is why this starts from the record rather than zero.
        cost = round_money(float(investment.get("cost") or 0))
        redeemed = 0.0
        income_earned = 0.0
        tds_total = 0.0

        for transaction in transactions_by_investment.get(investment_id, []):
            amount = round_money(float(transaction.get("amount") or 0))
            classification = classify_investment_income(transaction.get("kind"))
            if classification == "income":
                income_earned = round_money(income_earned + amount)
                tds_total = round_money(tds_total + float(transaction.get("tds") or 0))
            elif classification == "asset":
                if transaction.get("kind") == "Purchase":
                    cost = round_money(cost + amount)
                else:  # Redemption or Maturity return principal
                    redeemed = round_money(redeemed + amount)

        book_value = round_money(cost - redeemed)

        fund_name = investment.get("fund")
        fund = fund_meta.get(fund_name, {})
        violations = validate_investment_mode(investment, fund, prohibited_parties)
        is_compliant = not violations

        clause = investment.get("mode_clause")
        mode_label = PERMITTED_MODES.get(str(clause), {}).get("label")

        rows.append(
            {
                "investment": investment_id,
                "fund": fund_name,
                "fund_class": fund.get("fund_class"),
                "is_fcra": bool(fund.get("is_fcra")),
                "mode_clause": clause,
                "mode_label": mode_label,
                # Carried through so the register can warn about a clause whose
                # citation has not been checked against the notified rule text.
                "citation_verified": bool(investment.get("citation_verified")),
                "instrument_type": investment.get("instrument_type"),
                "issuer": investment.get("issuer"),
                "cost": cost,
                "redeemed": redeemed,
                "book_value": book_value,
                "income_earned": income_earned,
                "tds": tds_total,
                "is_compliant": is_compliant,
                "violations": violations,
            }
        )

        mode_bucket = by_mode.setdefault(
            str(clause), {"mode_label": mode_label, "book_value": 0.0, "count": 0}
        )
        mode_bucket["book_value"] = round_money(mode_bucket["book_value"] + book_value)
        mode_bucket["count"] += 1

        totals["cost"] = round_money(totals["cost"] + cost)
        totals["redeemed"] = round_money(totals["redeemed"] + redeemed)
        totals["book_value"] = round_money(totals["book_value"] + book_value)
        totals["income_earned"] = round_money(totals["income_earned"] + income_earned)
        totals["tds"] = round_money(totals["tds"] + tds_total)
        if not is_compliant:
            totals["non_compliant_book_value"] = round_money(
                totals["non_compliant_book_value"] + book_value
            )

    rows.sort(key=lambda row: (str(row["fund"]), str(row["investment"])))

    return {"rows": rows, "by_mode": by_mode, "totals": totals}

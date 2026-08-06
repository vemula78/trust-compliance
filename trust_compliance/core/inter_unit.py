"""Inter-unit transfers between the Trust's units, and their elimination.

Pure module: no frappe import. Ported from `recordInterUnitTransfer` and the
elimination half of `buildConsolidatedFinancials` in the source ERP
(`src/lib/server/property-repository.ts`, `src/lib/accounting.ts`).

A transfer from the Trust to one of its hospitals or schools is real expenditure
in the paying unit and real income in the receiving one - each unit keeps its own
books and files its own return, so both entries must stand. At *group* level they
are the same money seen twice: consolidating them unchanged would inflate both
total income and total expenditure by the amount transferred, and would make the
group look as though it had applied income it had merely moved. So the two legs
are excluded from a consolidated statement and disclosed as an elimination.

The source ERP's elimination reported one figure, the total debit value removed,
which for a single transfer of X reads 2X - the payer's expense and the
receiver's income. That was documented but easy to misread as the cash moved.
Here the two sides are reported separately and reconciled against each other,
because a mismatch between them is a real defect (a leg cancelled on its own)
that a single total would hide.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from trust_compliance.core.segregation import validate_corpus_outflow

TransferRow = Mapping[str, object]
GLRow = Mapping[str, object]


def round_money(value: float) -> float:
    return round(value + 0.0, 2)


def validate_inter_unit_transfer(
    transfer: TransferRow,
    from_fund: Mapping | None = None,
    to_fund: Mapping | None = None,
) -> list[str]:
    """Return refusal reasons for a proposed transfer between two units.

    Every reason is collected rather than the first one thrown, so a transfer
    that is wrong in two ways is corrected once.

    transfer: {"from_company", "to_company", "amount"}
    """
    errors: list[str] = []

    amount = float(transfer.get("amount") or 0)
    if amount <= 0:
        errors.append("Transfer amount must be greater than zero.")

    from_company = transfer.get("from_company")
    to_company = transfer.get("to_company")
    if from_company and to_company and from_company == to_company:
        errors.append(
            f"{from_company} cannot transfer to itself. Moving money between funds "
            "inside one unit is a Fund Transfer, not an inter-unit transfer."
        )

    # Corpus is capital held on the donor's direction. Paying it to another unit
    # spends it, whatever the receiving unit does with it.
    errors.extend(validate_corpus_outflow(from_fund, None))

    if to_fund is not None and str(to_fund.get("fund_class")) == "Corpus":
        errors.append(
            f"Fund {to_fund['name']} is Corpus class. A grant from another unit is "
            "income of the receiving unit, not corpus - corpus arises only from a "
            "donation given with that direction, or from a section 11(2) "
            "accumulation."
        )

    # FCRA section 7, as amended by the FCRA (Amendment) Act 2020, prohibits
    # transferring foreign contribution to *any* other person, whether or not that
    # person is itself registered. It is refused in both directions: paying it out
    # is the prohibited transfer, and receiving domestic money into an FCRA fund
    # would report money as foreign contribution in FC-4 that never was.
    if from_fund is not None and bool(from_fund.get("is_fcra")):
        errors.append(
            f"Fund {from_fund['name']} holds foreign contribution. FCRA section 7 "
            "prohibits transferring foreign contribution to any other person, "
            "registered or not, so it cannot be granted to another unit. If the "
            "receiving unit is not a separate legal person, the money has not left "
            "the recipient and this is an internal allocation, not a transfer."
        )
    if to_fund is not None and bool(to_fund.get("is_fcra")):
        errors.append(
            f"Fund {to_fund['name']} holds foreign contribution. A grant from "
            "another unit is not foreign contribution, and receiving it here would "
            "report it as such in FC-4."
        )

    return errors


def build_elimination_summary(gl_rows: Iterable[GLRow]) -> dict:
    """What a consolidated statement must eliminate, from the inter-unit GL rows.

    Feed it the GL rows of vouchers flagged inter-unit. Expense debits are the
    paying units' side and income credits the receiving units' side; the bank legs
    are ignored, because cash really did move between the units and nothing about
    it is double-counted at group level.

    `eliminated_expense` and `eliminated_income` must be equal - they are the two
    faces of the same transfers. `is_balanced` says whether they are, and it is
    the check worth watching: an unbalanced summary means one leg was cancelled or
    edited on its own, which would leave a consolidated statement wrong by the
    difference no matter how the elimination is applied.

    `net_transferred` is the money that actually moved, equal to either side.
    `total_removed` is the sum of both, i.e. twice the transfers, which is what
    drops out of the group's totals.
    """
    eliminated_expense = 0.0
    eliminated_income = 0.0
    vouchers: set[object] = set()
    pairs: dict[tuple[str, str], float] = {}

    for row in gl_rows:
        root_type = str(row.get("root_type") or "")
        debit = float(row.get("debit") or 0)
        credit = float(row.get("credit") or 0)
        vouchers.add(row.get("voucher_no"))

        if root_type == "Expense":
            amount = round_money(debit - credit)
            eliminated_expense = round_money(eliminated_expense + amount)
            key = (str(row.get("company")), str(row.get("counterparty_company")))
            pairs[key] = round_money(pairs.get(key, 0.0) + amount)
        elif root_type == "Income":
            eliminated_income = round_money(eliminated_income + credit - debit)

    rows = [
        {"from_company": payer, "to_company": receiver, "amount": amount}
        for (payer, receiver), amount in sorted(pairs.items())
    ]

    return {
        "rows": rows,
        "eliminated_expense": eliminated_expense,
        "eliminated_income": eliminated_income,
        "is_balanced": abs(eliminated_expense - eliminated_income) <= 0.01,
        "net_transferred": eliminated_expense,
        "total_removed": round_money(eliminated_expense + eliminated_income),
        "voucher_count": len([voucher for voucher in vouchers if voucher]),
    }

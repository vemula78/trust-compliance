"""Program (grant) accounting: what each program took in, spent, and was budgeted.

Pure module: no frappe import. Ported from `buildProgramUtilization` in
`src/lib/accounting.ts`, and extended with the budget column that report could
not have - the source ERP's budget line was keyed on (cost centre, account,
period) and carried no project, so program budgets could not be derived from it.
ERPNext's own Budget can be set *against a Project*, which is what makes
budget-versus-utilisation possible here.

A program is a Project. ERPNext already carries `project` on every GL Entry, so
programs need no new dimension - one less thing to keep in step with the ledger.

Input shapes:

    gl_rows:  {"account", "root_type", "debit", "credit", "project", "fund",
               "posting_date"}
    programs: {"name", "project_name", "status", "company"}
    budgets:  {"project", "account", "budget_amount"}
"""

from __future__ import annotations

import datetime
from typing import Iterable, Mapping, Sequence

GLRow = Mapping[str, object]
ProgramRow = Mapping[str, object]
BudgetRow = Mapping[str, object]


def round_money(value: float) -> float:
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


def build_program_utilisation(
    gl_rows: Iterable[GLRow],
    programs: Sequence[ProgramRow],
    budgets: Iterable[BudgetRow] = (),
    from_date: object = None,
    to_date: object = None,
) -> dict:
    """Income, expenditure and budget per program, with a fund breakdown.

    Expenditure on a program is application of the Trust's income to its objects,
    which is what the 85% test under section 11(1)(a) measures - so these figures
    have to agree with the ledger, and they are read straight off it rather than
    from any separate program record.

    Lines carrying no project are **excluded**, not pooled into an "unassigned"
    row: an untagged line is not part of any program, and showing it as one would
    overstate what the programs delivered. The excluded total is returned as
    `untagged` instead, because the honest question an auditor asks is how much of
    the year's spending was *not* attributed to a program.

    Every program in the master gets a row, including one with no activity, so a
    program that received nothing is visible rather than missing.

    Income is credit less debit on Income accounts and expenditure is debit less
    credit on Expense accounts - both net of reversals, so a cancelled voucher
    does not inflate either. Asset and liability lines are ignored: buying an
    asset for a program is not expenditure of the year.

    `utilised_pct` is expenditure over budget. It is None, not zero, where there
    is no budget - a program with no budget is unbudgeted, not fully unspent, and
    a zero would read as the opposite of what it means.
    """
    window_from = _as_date(from_date)
    window_to = _as_date(to_date)

    budget_by_program: dict[str, float] = {}
    for budget in budgets:
        project = budget.get("project")
        if not project:
            continue
        key = str(project)
        budget_by_program[key] = round_money(
            budget_by_program.get(key, 0.0) + float(budget.get("budget_amount") or 0)
        )

    rows: dict[str, dict] = {}
    for program in programs:
        key = str(program.get("name"))
        rows[key] = {
            "program": key,
            "program_name": program.get("project_name") or key,
            "status": program.get("status"),
            "income": 0.0,
            "expense": 0.0,
            "net": 0.0,
            "budget": budget_by_program.get(key, 0.0),
            "by_fund": {},
        }

    untagged_expense = 0.0
    untagged_income = 0.0

    for row in gl_rows:
        posting_date = _as_date(row.get("posting_date"))
        if window_from and posting_date and posting_date < window_from:
            continue
        if window_to and posting_date and posting_date > window_to:
            continue

        root_type = str(row.get("root_type") or "")
        if root_type not in ("Income", "Expense"):
            continue

        debit = float(row.get("debit") or 0)
        credit = float(row.get("credit") or 0)
        project = row.get("project")

        if not project:
            if root_type == "Income":
                untagged_income = round_money(untagged_income + credit - debit)
            else:
                untagged_expense = round_money(untagged_expense + debit - credit)
            continue

        program = rows.get(str(project))
        if program is None:
            # A project that exists in the ledger but not in the master this
            # report was given - a disabled or another company's project. Counting
            # it against a program that is not on the schedule would make the rows
            # and the total disagree, so it is treated as untagged and reported.
            if root_type == "Income":
                untagged_income = round_money(untagged_income + credit - debit)
            else:
                untagged_expense = round_money(untagged_expense + debit - credit)
            continue

        fund = str(row.get("fund") or "")
        by_fund = program["by_fund"].setdefault(
            fund, {"fund": fund, "income": 0.0, "expense": 0.0}
        )
        if root_type == "Income":
            program["income"] = round_money(program["income"] + credit - debit)
            by_fund["income"] = round_money(by_fund["income"] + credit - debit)
        else:
            program["expense"] = round_money(program["expense"] + debit - credit)
            by_fund["expense"] = round_money(by_fund["expense"] + debit - credit)

    ordered = sorted(rows.values(), key=lambda row: str(row["program_name"]).lower())
    for row in ordered:
        row["net"] = round_money(row["income"] - row["expense"])
        budget = row["budget"]
        row["utilised_pct"] = (
            round(row["expense"] / budget * 100, 1) if budget else None
        )
        row["remaining"] = round_money(budget - row["expense"]) if budget else 0.0
        row["over_budget"] = bool(budget) and row["expense"] > budget
        row["by_fund"] = sorted(row["by_fund"].values(), key=lambda f: f["fund"])

    totals = {
        "income": round_money(sum(row["income"] for row in ordered)),
        "expense": round_money(sum(row["expense"] for row in ordered)),
        "budget": round_money(sum(row["budget"] for row in ordered)),
    }
    totals["net"] = round_money(totals["income"] - totals["expense"])
    totals["remaining"] = round_money(totals["budget"] - totals["expense"])

    return {
        "rows": ordered,
        "totals": totals,
        "program_count": len(ordered),
        "untagged": {"income": untagged_income, "expense": untagged_expense},
        "over_budget": [row["program"] for row in ordered if row["over_budget"]],
    }

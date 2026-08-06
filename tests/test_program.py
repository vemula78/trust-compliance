"""Tests for the frappe-free program-accounting and inter-unit core.

Runnable without a bench: `python3 -m pytest tests/ -q` from the app root.
Each assertion's comment names the reason it exists.
"""

from __future__ import annotations

import datetime

from trust_compliance.core.inter_unit import (
    build_elimination_summary,
    validate_inter_unit_transfer,
)
from trust_compliance.core.program import build_program_utilisation

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

HOSPITAL = {"name": "PROG-HOSP", "project_name": "Free Cardiac Surgery", "status": "Open"}
SCHOOL = {"name": "PROG-EDU", "project_name": "Free Education KG to PG", "status": "Open"}
PROGRAMS = [HOSPITAL, SCHOOL]

CORPUS_FUND = {"name": "CORPUS", "fund_class": "Corpus", "is_fcra": 0}
GEN_FUND = {"name": "GEN", "fund_class": "Unrestricted", "is_fcra": 0}
HOSP_FUND = {"name": "HOSP", "fund_class": "Restricted", "is_fcra": 0}
FCRA_FUND = {"name": "FCRA-GEN", "fund_class": "Unrestricted", "is_fcra": 1}


def gl(root_type, debit=0.0, credit=0.0, project=None, fund="GEN",
       posting_date="2026-06-01", account="Account"):
    return {
        "account": account,
        "root_type": root_type,
        "debit": debit,
        "credit": credit,
        "project": project,
        "fund": fund,
        "posting_date": posting_date,
    }


class TestProgramUtilisation:
    def test_every_program_gets_a_row_even_with_no_activity(self):
        # A program that received nothing must be visible, not missing: "no row"
        # reads as "no such program" to whoever is checking the schedule.
        report = build_program_utilisation([], PROGRAMS)
        assert [row["program"] for row in report["rows"]] == ["PROG-HOSP", "PROG-EDU"]
        assert report["program_count"] == 2

    def test_income_and_expenditure_are_read_off_the_project_dimension(self):
        rows = [
            gl("Income", credit=500_000, project="PROG-HOSP"),
            gl("Expense", debit=300_000, project="PROG-HOSP"),
            gl("Expense", debit=100_000, project="PROG-EDU"),
        ]
        report = build_program_utilisation(rows, PROGRAMS)
        by_id = {row["program"]: row for row in report["rows"]}
        assert by_id["PROG-HOSP"]["income"] == 500_000
        assert by_id["PROG-HOSP"]["expense"] == 300_000
        assert by_id["PROG-HOSP"]["net"] == 200_000
        assert by_id["PROG-EDU"]["expense"] == 100_000

    def test_reversals_net_off(self):
        # A cancelled voucher posts the opposite entry; counting only debits would
        # leave the programme permanently overstated.
        rows = [
            gl("Expense", debit=100_000, project="PROG-EDU"),
            gl("Expense", credit=100_000, project="PROG-EDU"),
        ]
        report = build_program_utilisation(rows, PROGRAMS)
        by_id = {row["program"]: row for row in report["rows"]}
        assert by_id["PROG-EDU"]["expense"] == 0

    def test_asset_and_liability_lines_are_ignored(self):
        # Buying an asset for a program is not expenditure of the year, and the
        # bank leg of every payment would otherwise be counted twice.
        rows = [
            gl("Asset", debit=250_000, project="PROG-HOSP"),
            gl("Liability", credit=250_000, project="PROG-HOSP"),
        ]
        report = build_program_utilisation(rows, PROGRAMS)
        assert report["totals"]["expense"] == 0
        assert report["totals"]["income"] == 0

    def test_untagged_lines_are_reported_not_pooled(self):
        # An untagged line is not part of any program. Pooling it into an
        # "unassigned" row would overstate what the programs delivered, but its
        # size is exactly the difference between this report and the I&E statement.
        rows = [
            gl("Expense", debit=80_000, project="PROG-EDU"),
            gl("Expense", debit=20_000, project=None),
            gl("Income", credit=5_000, project=None),
        ]
        report = build_program_utilisation(rows, PROGRAMS)
        assert report["totals"]["expense"] == 80_000
        assert report["untagged"] == {"expense": 20_000, "income": 5_000}

    def test_a_project_outside_the_master_counts_as_untagged(self):
        # A disabled or another company's project in the ledger must not be
        # counted against a program on this schedule, or the rows and the total
        # would disagree.
        rows = [gl("Expense", debit=9_000, project="PROG-SOMEWHERE-ELSE")]
        report = build_program_utilisation(rows, PROGRAMS)
        assert report["totals"]["expense"] == 0
        assert report["untagged"]["expense"] == 9_000

    def test_window_clips_by_posting_date(self):
        rows = [
            gl("Expense", debit=1_000, project="PROG-EDU", posting_date="2026-03-31"),
            gl("Expense", debit=2_000, project="PROG-EDU", posting_date="2026-04-01"),
            gl("Expense", debit=4_000, project="PROG-EDU", posting_date="2027-04-01"),
        ]
        report = build_program_utilisation(
            rows, PROGRAMS, from_date="2026-04-01", to_date="2027-03-31"
        )
        by_id = {row["program"]: row for row in report["rows"]}
        assert by_id["PROG-EDU"]["expense"] == 2_000

    def test_window_accepts_date_objects_as_well_as_strings(self):
        rows = [gl("Expense", debit=3_000, project="PROG-EDU",
                   posting_date=datetime.date(2026, 6, 1))]
        report = build_program_utilisation(
            rows, PROGRAMS,
            from_date=datetime.date(2026, 4, 1), to_date=datetime.date(2027, 3, 31),
        )
        assert report["totals"]["expense"] == 3_000

    def test_fund_breakdown_per_program(self):
        # Which fund paid for a program is the restricted-fund question: money
        # given for the hospital cannot be spent on the school.
        rows = [
            gl("Expense", debit=60_000, project="PROG-HOSP", fund="HOSP"),
            gl("Expense", debit=40_000, project="PROG-HOSP", fund="GEN"),
        ]
        report = build_program_utilisation(rows, PROGRAMS)
        by_id = {row["program"]: row for row in report["rows"]}
        assert by_id["PROG-HOSP"]["by_fund"] == [
            {"fund": "GEN", "income": 0.0, "expense": 40_000},
            {"fund": "HOSP", "income": 0.0, "expense": 60_000},
        ]

    def test_budget_comes_from_the_budget_master_and_is_summed_per_program(self):
        budgets = [
            {"project": "PROG-HOSP", "account": "Medical Consumables", "budget_amount": 700_000},
            {"project": "PROG-HOSP", "account": "Salaries", "budget_amount": 300_000},
        ]
        rows = [gl("Expense", debit=500_000, project="PROG-HOSP")]
        report = build_program_utilisation(rows, PROGRAMS, budgets)
        by_id = {row["program"]: row for row in report["rows"]}
        assert by_id["PROG-HOSP"]["budget"] == 1_000_000
        assert by_id["PROG-HOSP"]["utilised_pct"] == 50.0
        assert by_id["PROG-HOSP"]["remaining"] == 500_000
        assert by_id["PROG-HOSP"]["over_budget"] is False

    def test_over_budget_is_flagged(self):
        budgets = [{"project": "PROG-EDU", "budget_amount": 100_000}]
        rows = [gl("Expense", debit=120_000, project="PROG-EDU")]
        report = build_program_utilisation(rows, PROGRAMS, budgets)
        by_id = {row["program"]: row for row in report["rows"]}
        assert by_id["PROG-EDU"]["over_budget"] is True
        assert by_id["PROG-EDU"]["utilised_pct"] == 120.0
        assert report["over_budget"] == ["PROG-EDU"]

    def test_unbudgeted_program_reports_no_utilisation_rather_than_zero(self):
        # Zero would read as "nothing spent of the budget", which is the opposite
        # of "there is no budget to measure against".
        rows = [gl("Expense", debit=50_000, project="PROG-EDU")]
        report = build_program_utilisation(rows, PROGRAMS)
        by_id = {row["program"]: row for row in report["rows"]}
        assert by_id["PROG-EDU"]["utilised_pct"] is None
        assert by_id["PROG-EDU"]["budget"] == 0.0

    def test_a_budget_for_no_project_is_ignored(self):
        report = build_program_utilisation([], PROGRAMS, [{"budget_amount": 5_000}])
        assert report["totals"]["budget"] == 0

    def test_totals_reconcile_with_the_rows(self):
        rows = [
            gl("Income", credit=200_000, project="PROG-HOSP"),
            gl("Expense", debit=150_000, project="PROG-HOSP"),
            gl("Expense", debit=50_000, project="PROG-EDU"),
        ]
        report = build_program_utilisation(rows, PROGRAMS)
        assert report["totals"]["income"] == sum(r["income"] for r in report["rows"])
        assert report["totals"]["expense"] == sum(r["expense"] for r in report["rows"])
        assert report["totals"]["net"] == 0


class TestInterUnitValidation:
    def transfer(self, **overrides):
        base = {
            "from_company": "Sai Trust",
            "to_company": "Sai Hospital",
            "amount": 1_000_000,
        }
        base.update(overrides)
        return base

    def test_a_plain_transfer_between_two_units_is_allowed(self):
        assert validate_inter_unit_transfer(self.transfer(), GEN_FUND, HOSP_FUND) == []

    def test_a_unit_cannot_transfer_to_itself(self):
        errors = validate_inter_unit_transfer(
            self.transfer(to_company="Sai Trust"), GEN_FUND, HOSP_FUND
        )
        assert any("cannot transfer to itself" in error for error in errors)

    def test_zero_and_negative_amounts_are_refused(self):
        for amount in (0, -1):
            errors = validate_inter_unit_transfer(
                self.transfer(amount=amount), GEN_FUND, HOSP_FUND
            )
            assert any("greater than zero" in error for error in errors)

    def test_corpus_cannot_be_paid_to_another_unit(self):
        # Section 11(1)(d) corpus is capital held on the donor's direction; paying
        # it out spends it, whatever the receiving unit does with it.
        errors = validate_inter_unit_transfer(self.transfer(), CORPUS_FUND, HOSP_FUND)
        assert any("corpus cannot be transferred out" in error for error in errors)

    def test_a_grant_cannot_be_received_as_corpus(self):
        # Corpus arises only from a donation given with that direction, or from a
        # section 11(2) accumulation - never from another unit's grant.
        errors = validate_inter_unit_transfer(
            self.transfer(), GEN_FUND, {"name": "H-CORPUS", "fund_class": "Corpus",
                                        "is_fcra": 0}
        )
        assert any("income of the receiving unit" in error for error in errors)

    def test_foreign_contribution_cannot_be_transferred_out(self):
        # FCRA section 7 as amended in 2020 prohibits transferring foreign
        # contribution to any other person, registered or not.
        errors = validate_inter_unit_transfer(self.transfer(), FCRA_FUND, HOSP_FUND)
        assert any("FCRA section 7" in error for error in errors)

    def test_a_grant_cannot_be_received_into_an_fcra_fund(self):
        # It would be reported as foreign contribution in FC-4 when it never was.
        errors = validate_inter_unit_transfer(self.transfer(), GEN_FUND, FCRA_FUND)
        assert any("not foreign contribution" in error for error in errors)

    def test_every_breach_is_reported_together(self):
        errors = validate_inter_unit_transfer(
            self.transfer(to_company="Sai Trust", amount=0), FCRA_FUND, FCRA_FUND
        )
        assert len(errors) == 4


class TestElimination:
    def entry(self, company, counterparty, root_type, debit=0.0, credit=0.0,
              voucher_no="JE-0001"):
        return {
            "company": company,
            "counterparty_company": counterparty,
            "root_type": root_type,
            "debit": debit,
            "credit": credit,
            "voucher_no": voucher_no,
        }

    def both_legs_of(self, amount, payer="Sai Trust", receiver="Sai Hospital",
                     suffix="1"):
        return [
            self.entry(payer, receiver, "Expense", debit=amount,
                       voucher_no=f"JE-{suffix}A"),
            self.entry(payer, receiver, "Asset", credit=amount,
                       voucher_no=f"JE-{suffix}A"),
            self.entry(receiver, payer, "Asset", debit=amount,
                       voucher_no=f"JE-{suffix}B"),
            self.entry(receiver, payer, "Income", credit=amount,
                       voucher_no=f"JE-{suffix}B"),
        ]

    def test_nothing_to_eliminate(self):
        summary = build_elimination_summary([])
        assert summary["rows"] == []
        assert summary["net_transferred"] == 0
        assert summary["is_balanced"] is True

    def test_one_transfer_eliminates_once_from_each_side(self):
        summary = build_elimination_summary(self.both_legs_of(1_000_000))
        assert summary["eliminated_expense"] == 1_000_000
        assert summary["eliminated_income"] == 1_000_000
        # The money that moved is X; what leaves the group's totals is 2X, because
        # it is removed from income and from expenditure alike.
        assert summary["net_transferred"] == 1_000_000
        assert summary["total_removed"] == 2_000_000
        assert summary["is_balanced"] is True
        assert summary["voucher_count"] == 2

    def test_bank_legs_are_not_eliminated(self):
        # The cash really did move between the units; nothing about it is
        # double-counted at group level.
        summary = build_elimination_summary(self.both_legs_of(500_000))
        assert summary["total_removed"] == 1_000_000

    def test_transfers_are_grouped_by_pair_of_units(self):
        rows = (
            self.both_legs_of(100_000, suffix="1")
            + self.both_legs_of(50_000, suffix="2")
            + self.both_legs_of(70_000, receiver="Sai School", suffix="3")
        )
        summary = build_elimination_summary(rows)
        assert summary["rows"] == [
            {"from_company": "Sai Trust", "to_company": "Sai Hospital",
             "amount": 150_000},
            {"from_company": "Sai Trust", "to_company": "Sai School",
             "amount": 70_000},
        ]
        assert summary["net_transferred"] == 220_000

    def test_one_leg_cancelled_alone_is_reported_as_unbalanced(self):
        # This is the state the elimination cannot be applied to: whichever side is
        # removed, the consolidated statement is wrong by the difference. A single
        # total would hide it.
        rows = [
            row for row in self.both_legs_of(200_000)
            if row["root_type"] != "Income"
        ]
        summary = build_elimination_summary(rows)
        assert summary["is_balanced"] is False
        assert summary["eliminated_expense"] == 200_000
        assert summary["eliminated_income"] == 0

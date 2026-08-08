"""Tests for the frappe-free grant deferred-income and TDS payable cores.

Runnable without a bench: `python3 -m pytest tests/ -q` from the app root.
Each assertion's comment names the reason it exists.
"""

from __future__ import annotations

from trust_compliance.core.grant import build_grant_register, validate_grant_utilisation
from trust_compliance.core.tds import build_tds_payable_register

HOSP_FUND = {"name": "HOSP", "fund_name": "Hospital Fund", "fund_class": "Restricted"}
EDU_FUND = {"name": "EDU", "fund_name": "Education Fund", "fund_class": "Restricted"}
FUNDS = [HOSP_FUND, EDU_FUND]


def gl(debit=0.0, credit=0.0, fund="HOSP", posting_date="2026-06-01"):
    return {"debit": debit, "credit": credit, "fund": fund, "posting_date": posting_date}


class TestGrantRegister:
    def test_a_credit_is_received_and_a_debit_is_recognised(self):
        rows = [gl(credit=500_000), gl(debit=200_000)]
        report = build_grant_register(rows, FUNDS)
        by_fund = {row["fund"]: row for row in report["rows"]}
        assert by_fund["HOSP"]["received"] == 500_000
        assert by_fund["HOSP"]["recognised"] == 200_000
        assert by_fund["HOSP"]["balance"] == 300_000

    def test_a_fund_with_no_grant_activity_is_absent_not_zeroed(self):
        # Unlike build_fund_balances this register is not seeded from the fund
        # master: a fund with no grant liability activity has nothing to show,
        # and a zero row would read as "this fund had a grant, fully spent."
        report = build_grant_register([gl(credit=100_000, fund="HOSP")], FUNDS)
        assert [row["fund"] for row in report["rows"]] == ["HOSP"]

    def test_totals_reconcile_with_the_rows(self):
        rows = [
            gl(credit=500_000, fund="HOSP"),
            gl(debit=200_000, fund="HOSP"),
            gl(credit=100_000, fund="EDU"),
        ]
        report = build_grant_register(rows, FUNDS)
        assert report["total_received"] == sum(r["received"] for r in report["rows"])
        assert report["total_recognised"] == sum(r["recognised"] for r in report["rows"])
        assert report["total_balance"] == sum(r["balance"] for r in report["rows"])
        assert report["total_balance"] == 400_000

    def test_window_clips_by_posting_date(self):
        rows = [
            gl(credit=100_000, posting_date="2026-03-31"),
            gl(credit=200_000, posting_date="2026-04-01"),
            gl(credit=400_000, posting_date="2027-04-01"),
        ]
        report = build_grant_register(rows, FUNDS, as_on="2026-04-01")
        assert report["total_received"] == 300_000


class TestGrantUtilisationValidation:
    def test_a_utilisation_within_balance_is_allowed(self):
        assert validate_grant_utilisation(100_000, outstanding_balance=300_000) == []

    def test_a_utilisation_exceeding_balance_is_refused(self):
        errors = validate_grant_utilisation(400_000, outstanding_balance=300_000)
        assert any("more income than the fund has received" in error for error in errors)

    def test_a_utilisation_of_exactly_the_balance_is_allowed(self):
        # The boundary itself must not be refused - a grant fully spent is the
        # expected end state, not an edge case to reject.
        assert validate_grant_utilisation(300_000, outstanding_balance=300_000) == []

    def test_zero_and_negative_amounts_are_refused(self):
        for amount in (0, -1):
            errors = validate_grant_utilisation(amount, outstanding_balance=300_000)
            assert any("greater than zero" in error for error in errors)

    def test_floating_point_residue_does_not_false_positive_at_the_boundary(self):
        # Summing 0.10 three times drifts a fraction of a paisa above 0.30 in
        # float arithmetic; rounding both sides to money before comparing is what
        # keeps a fully-utilised grant from being refused by that artefact.
        drifted_balance = 0.10 + 0.10 + 0.10
        assert drifted_balance != 0.30  # the float drift this test guards against
        errors = validate_grant_utilisation(0.30, outstanding_balance=drifted_balance)
        assert errors == []


class TestTdsPayableRegister:
    def test_a_credit_is_deducted_and_a_debit_is_remitted(self):
        rows = [gl(credit=10_000, fund="HOSP"), gl(debit=4_000, fund="HOSP")]
        report = build_tds_payable_register(rows, FUNDS)
        by_fund = {row["fund"]: row for row in report["rows"]}
        assert by_fund["HOSP"]["deducted"] == 10_000
        assert by_fund["HOSP"]["remitted"] == 4_000
        assert by_fund["HOSP"]["balance"] == 6_000

    def test_an_untagged_row_is_grouped_under_no_fund_not_dropped(self):
        # Most TDS deduction on a vendor payment will not carry the fund
        # dimension until the paying document is tagged; dropping it would
        # understate the payable rather than surface the gap.
        rows = [gl(credit=5_000, fund=None)]
        report = build_tds_payable_register(rows, FUNDS)
        assert report["total_deducted"] == 5_000
        assert report["rows"][-1]["fund"] is None

    def test_totals_reconcile_with_the_rows(self):
        rows = [
            gl(credit=10_000, fund="HOSP"),
            gl(debit=4_000, fund="HOSP"),
            gl(credit=2_000, fund="EDU"),
        ]
        report = build_tds_payable_register(rows, FUNDS)
        assert report["total_deducted"] == sum(r["deducted"] for r in report["rows"])
        assert report["total_remitted"] == sum(r["remitted"] for r in report["rows"])
        assert report["total_balance"] == 8_000

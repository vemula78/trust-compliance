"""Tests for the frappe-free Trust compliance core.

Runnable without a bench: `python3 -m pytest tests/ -q` from the app root.
These mirror the assertions in the Next.js ERP's funds.test.ts / compliance.test.ts
so a divergence between the two implementations shows up as a failure here.
"""

from __future__ import annotations

import datetime

import pytest

from trust_compliance.core.compliance import (
    build_donation_register,
    build_fcra_register,
    build_form_10bd,
    build_income_application,
)
from trust_compliance.core.financial_year import (
    financial_year_of,
    financial_year_window,
    is_financial_year,
    next_receipt_no,
)
from trust_compliance.core.fund_balance import (
    build_fund_balances,
    build_fund_income_expenditure,
)
from trust_compliance.core.segregation import (
    validate_corpus_outflow,
    validate_fund_segregation,
)

# --------------------------------------------------------------------------
# Fixtures: a fund master with one domestic default, one FCRA fund, one corpus
# --------------------------------------------------------------------------

FUNDS = [
    {"name": "GEN", "fund_name": "General Fund", "fund_class": "Unrestricted",
     "is_default": 1, "is_fcra": 0},
    {"name": "HOSP", "fund_name": "Hospital Fund", "fund_class": "Restricted",
     "is_default": 0, "is_fcra": 0},
    {"name": "CORPUS", "fund_name": "Corpus Fund", "fund_class": "Corpus",
     "is_default": 0, "is_fcra": 0},
    {"name": "FCRA-GEN", "fund_name": "FCRA General Fund", "fund_class": "Unrestricted",
     "is_default": 0, "is_fcra": 1},
]

ACCOUNTS = [
    {"name": "1000 Bank", "is_fcra": 0, "account_type": "Bank"},
    {"name": "1001 FCRA Bank", "is_fcra": 1, "account_type": "Bank"},
    {"name": "4400 Donation Income", "is_fcra": 0, "account_type": "Income Account"},
    {"name": "6300 Office Rent", "is_fcra": 0, "account_type": "Expense Account"},
]


def gl(account, root_type, debit=0.0, credit=0.0, fund=None,
       posting_date="2026-06-15", is_administrative=0, voucher_no="JV-0001",
       is_grant_liability=False):
    return {
        "account": account, "root_type": root_type, "debit": debit, "credit": credit,
        "fund": fund, "posting_date": posting_date,
        "is_administrative": is_administrative, "voucher_no": voucher_no,
        "is_grant_liability": is_grant_liability,
    }


# --------------------------------------------------------------------------
# Financial year
# --------------------------------------------------------------------------

class TestFinancialYear:
    @pytest.mark.parametrize(
        "date,expected",
        [
            ("2026-04-01", "2026-27"),
            ("2027-03-31", "2026-27"),
            ("2027-04-01", "2027-28"),
            ("2026-01-15", "2025-26"),
            ("2099-12-31", "2099-00"),  # century rollover keeps the 2-digit form
        ],
    )
    def test_boundaries(self, date, expected):
        assert financial_year_of(date) == expected

    def test_accepts_date_and_datetime(self):
        assert financial_year_of(datetime.date(2026, 4, 1)) == "2026-27"
        assert financial_year_of(datetime.datetime(2027, 3, 31, 23, 59)) == "2026-27"

    def test_rejects_non_dates(self):
        for bad in ["2026-02-30", "not-a-date", "2026-13-01", ""]:
            with pytest.raises(ValueError):
                financial_year_of(bad)

    def test_label_validation(self):
        assert is_financial_year("2026-27")
        assert not is_financial_year("2026-28")  # not self-consistent
        assert not is_financial_year("2026")
        assert not is_financial_year(None)

    def test_window(self):
        assert financial_year_window("2026-27") == (
            datetime.date(2026, 4, 1),
            datetime.date(2027, 3, 31),
        )


class TestReceiptNumbering:
    def test_first_receipt_of_year(self):
        assert next_receipt_no([], "2026-27") == "80G/2026-27/0001"

    def test_continues_the_series(self):
        existing = ["80G/2026-27/0001", "80G/2026-27/0002"]
        assert next_receipt_no(existing, "2026-27") == "80G/2026-27/0003"

    def test_a_hole_never_reissues_a_used_number(self):
        # 0002 cancelled: count is 2 but the highest issued is 3, so the next is 4.
        existing = ["80G/2026-27/0001", "80G/2026-27/0003"]
        assert next_receipt_no(existing, "2026-27") == "80G/2026-27/0004"

    def test_series_is_per_financial_year(self):
        existing = ["80G/2025-26/0001", "80G/2025-26/0002"]
        assert next_receipt_no(existing, "2026-27") == "80G/2026-27/0001"

    def test_a_foreign_series_does_not_affect_this_one(self):
        existing = ["FC/2026-27/0009", "80G/2026-27/0001"]
        assert next_receipt_no(existing, "2026-27") == "80G/2026-27/0002"

    def test_a_malformed_number_in_the_series_skips_rather_than_reuses(self):
        # "abc" has no sequence to read, but it *is* in this year's series, so it
        # counts toward the tally and the next number is 0003. Safety over
        # contiguity: the rule may never hand back a number already issued.
        # This matches nextDonationReceiptNo in the Next.js ERP exactly.
        existing = ["80G/2026-27/abc", "80G/2026-27/0001"]
        issued = next_receipt_no(existing, "2026-27")
        assert issued == "80G/2026-27/0003"
        assert issued not in existing

    def test_rejects_bad_financial_year(self):
        with pytest.raises(ValueError):
            next_receipt_no([], "2026")


# --------------------------------------------------------------------------
# FCRA segregation — the rule that must be impossible to bypass
# --------------------------------------------------------------------------

class TestSegregation:
    def test_wholly_domestic_entry_passes(self):
        lines = [
            {"fund": "GEN", "account": "1000 Bank"},
            {"fund": "GEN", "account": "4400 Donation Income"},
        ]
        assert validate_fund_segregation(lines, FUNDS, ACCOUNTS) == []

    def test_wholly_fcra_entry_passes(self):
        lines = [
            {"fund": "FCRA-GEN", "account": "1001 FCRA Bank"},
            {"fund": "FCRA-GEN", "account": "4400 Donation Income"},
        ]
        assert validate_fund_segregation(lines, FUNDS, ACCOUNTS) == []

    def test_mixed_entry_is_refused(self):
        lines = [
            {"fund": "FCRA-GEN", "account": "1001 FCRA Bank"},
            {"fund": "GEN", "account": "4400 Donation Income"},
        ]
        errors = validate_fund_segregation(lines, FUNDS, ACCOUNTS)
        assert any("cannot mix" in error for error in errors)

    def test_half_tagged_entry_reads_as_mixed_not_as_fcra(self):
        # The untagged line follows the domestic default fund, so this is mixed.
        lines = [
            {"fund": "FCRA-GEN", "account": "1001 FCRA Bank"},
            {"fund": None, "account": "4400 Donation Income"},
        ]
        errors = validate_fund_segregation(lines, FUNDS, ACCOUNTS)
        assert any("cannot mix" in error for error in errors)

    def test_untagged_entry_on_fcra_account_is_refused(self):
        # This is the case a plain journal entry would otherwise slip through:
        # no fund tagged anywhere, so rule 1 sees a wholly domestic voucher.
        lines = [
            {"fund": None, "account": "1001 FCRA Bank"},
            {"fund": None, "account": "4400 Donation Income"},
        ]
        errors = validate_fund_segregation(lines, FUNDS, ACCOUNTS)
        assert any("FCRA-designated" in error for error in errors)

    def test_fcra_fund_through_domestic_bank_is_refused(self):
        # The reverse of the FCRA-bank/domestic-fund rule: an FCRA fund must not
        # bank through a domestic Bank/Cash account either, or foreign
        # contribution commingles with the domestic bank balance.
        lines = [
            {"fund": "FCRA-GEN", "account": "6300 Office Rent"},
            {"fund": "FCRA-GEN", "account": "1000 Bank"},
        ]
        errors = validate_fund_segregation(lines, FUNDS, ACCOUNTS)
        assert any("not FCRA-designated" in error for error in errors)

    def test_fcra_fund_through_ordinary_expense_account_is_accepted(self):
        # The reverse rule is limited to monetary (Bank/Cash) accounts; an FCRA
        # fund legitimately spends through an ordinary expense account paired
        # with the FCRA bank account.
        lines = [
            {"fund": "FCRA-GEN", "account": "6300 Office Rent"},
            {"fund": "FCRA-GEN", "account": "1001 FCRA Bank"},
        ]
        assert validate_fund_segregation(lines, FUNDS, ACCOUNTS) == []

    def test_account_rule_is_skipped_when_accounts_not_supplied(self):
        lines = [
            {"fund": None, "account": "1001 FCRA Bank"},
            {"fund": None, "account": "4400 Donation Income"},
        ]
        assert validate_fund_segregation(lines, FUNDS) == []

    def test_unknown_fund_is_reported(self):
        lines = [{"fund": "GHOST", "account": "1000 Bank"}]
        errors = validate_fund_segregation(lines, FUNDS, ACCOUNTS)
        assert any("not in the fund master" in error for error in errors)

    def test_check_fields_arriving_as_ints_are_honoured(self):
        # Frappe Check fields are 0/1, never bools.
        funds = [
            {"name": "D", "is_default": 1, "is_fcra": 0},
            {"name": "F", "is_default": 0, "is_fcra": 1},
        ]
        errors = validate_fund_segregation(
            [{"fund": "D", "account": None}, {"fund": "F", "account": None}], funds
        )
        assert any("cannot mix" in error for error in errors)

    def test_corpus_cannot_be_transferred_out(self):
        corpus = next(fund for fund in FUNDS if fund["name"] == "CORPUS")
        general = next(fund for fund in FUNDS if fund["name"] == "GEN")
        assert validate_corpus_outflow(corpus, general) != []
        assert validate_corpus_outflow(general, corpus) == []


# --------------------------------------------------------------------------
# Fund balances
# --------------------------------------------------------------------------

class TestFundBalances:
    def test_donation_increases_the_fund_and_asset_legs_are_ignored(self):
        rows = [
            gl("1000 Bank", "Asset", debit=50_000, fund="HOSP"),
            gl("4400 Donation Income", "Income", credit=50_000, fund="HOSP"),
        ]
        report = build_fund_balances(rows, FUNDS)
        hosp = next(row for row in report["rows"] if row["fund"] == "HOSP")
        assert hosp["inflow"] == 50_000
        assert hosp["outflow"] == 0
        assert hosp["balance"] == 50_000
        # Asset leg ignored, so the total is the donation once, not twice.
        assert report["total_inflow"] == 50_000

    def test_expense_reduces_the_fund(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=50_000, fund="HOSP"),
            gl("6100 Medical Supplies", "Expense", debit=20_000, fund="HOSP"),
        ]
        hosp = next(
            row for row in build_fund_balances(rows, FUNDS)["rows"] if row["fund"] == "HOSP"
        )
        assert (hosp["inflow"], hosp["outflow"], hosp["balance"]) == (50_000, 20_000, 30_000)

    def test_inter_fund_transfer_moves_money_and_nets_to_zero(self):
        # Both legs on the equity clearing account; the equity DEBIT must read as
        # an outflow from the source fund, which is the whole point of classifying
        # by direction rather than by account type.
        rows = [
            gl("3900 Inter-fund Transfers", "Equity", debit=10_000, fund="GEN"),
            gl("3900 Inter-fund Transfers", "Equity", credit=10_000, fund="HOSP"),
        ]
        report = build_fund_balances(rows, FUNDS)
        gen = next(row for row in report["rows"] if row["fund"] == "GEN")
        hosp = next(row for row in report["rows"] if row["fund"] == "HOSP")
        assert gen["balance"] == -10_000
        assert hosp["balance"] == 10_000
        assert report["total_balance"] == 0  # the ledger is untouched overall

    def test_untagged_rows_attribute_to_the_default_fund(self):
        rows = [gl("4400 Donation Income", "Income", credit=1_000, fund=None)]
        report = build_fund_balances(rows, FUNDS)
        gen = next(row for row in report["rows"] if row["fund"] == "GEN")
        assert gen["inflow"] == 1_000
        assert report["total_inflow"] == 1_000  # money never disappears

    def test_rows_naming_a_departed_fund_also_fall_to_default(self):
        rows = [gl("4400 Donation Income", "Income", credit=700, fund="GHOST")]
        report = build_fund_balances(rows, FUNDS)
        gen = next(row for row in report["rows"] if row["fund"] == "GEN")
        assert gen["inflow"] == 700

    def test_from_date_moves_prior_activity_into_opening(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=5_000, fund="HOSP",
               posting_date="2026-03-31"),
            gl("4400 Donation Income", "Income", credit=3_000, fund="HOSP",
               posting_date="2026-06-15"),
        ]
        report = build_fund_balances(rows, FUNDS, from_date="2026-04-01", to_date="2027-03-31")
        hosp = next(row for row in report["rows"] if row["fund"] == "HOSP")
        assert (hosp["opening"], hosp["inflow"], hosp["balance"]) == (5_000, 3_000, 8_000)

    def test_to_date_clips_the_window(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=3_000, fund="HOSP",
               posting_date="2027-04-02"),
        ]
        report = build_fund_balances(rows, FUNDS, from_date="2026-04-01", to_date="2027-03-31")
        assert report["total_inflow"] == 0

    def test_every_fund_appears_even_with_no_activity(self):
        report = build_fund_balances([], FUNDS)
        assert {row["fund"] for row in report["rows"]} == {
            "GEN", "HOSP", "CORPUS", "FCRA-GEN"
        }


class TestFundIncomeExpenditure:
    def test_surplus_per_fund_excludes_equity(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=100_000, fund="HOSP"),
            gl("6100 Medical Supplies", "Expense", debit=40_000, fund="HOSP"),
            gl("3200 Corpus Fund", "Equity", credit=500_000, fund="CORPUS"),
        ]
        report = build_fund_income_expenditure(rows, FUNDS)
        hosp = next(row for row in report["funds"] if row["fund"] == "HOSP")
        assert (hosp["total_income"], hosp["total_expense"], hosp["surplus"]) == (
            100_000, 40_000, 60_000,
        )
        # Corpus contributed no income or expense, so it has no statement at all.
        assert all(row["fund"] != "CORPUS" for row in report["funds"])

    def test_refund_reduces_the_income_line_it_belongs_to(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=10_000, fund="GEN"),
            gl("4400 Donation Income", "Income", debit=2_500, fund="GEN"),
        ]
        report = build_fund_income_expenditure(rows, FUNDS)
        gen = next(row for row in report["funds"] if row["fund"] == "GEN")
        assert gen["total_income"] == 7_500
        assert len(gen["income"]) == 1  # one net line, not an income and a contra


# --------------------------------------------------------------------------
# Statutory compliance
# --------------------------------------------------------------------------

class TestFCRARegister:
    def test_admin_cap_is_measured_against_contribution_received(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=100_000, fund="FCRA-GEN"),
            gl("6300 Office Rent", "Expense", debit=25_000, fund="FCRA-GEN",
               is_administrative=1),
            gl("6100 Medical Supplies", "Expense", debit=30_000, fund="FCRA-GEN"),
        ]
        report = build_fcra_register(rows, [], FUNDS,
                                     from_date="2026-04-01", to_date="2027-03-31")
        summary = report["summary"]
        assert summary["receipts"] == 100_000
        assert summary["utilized"] == 55_000
        assert summary["admin_utilized"] == 25_000
        # 25% of receipts, not 45% of utilisation.
        assert summary["admin_percent"] == 25.0
        assert summary["admin_cap_exceeded"] is True

    def test_within_cap_is_not_flagged(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=100_000, fund="FCRA-GEN"),
            gl("6300 Office Rent", "Expense", debit=15_000, fund="FCRA-GEN",
               is_administrative=1),
        ]
        summary = build_fcra_register(rows, [], FUNDS)["summary"]
        assert summary["admin_percent"] == 15.0
        assert summary["admin_cap_exceeded"] is False

    def test_domestic_activity_is_excluded_entirely(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=999_999, fund="GEN"),
            gl("4400 Donation Income", "Income", credit=100_000, fund="FCRA-GEN"),
        ]
        assert build_fcra_register(rows, [], FUNDS)["summary"]["receipts"] == 100_000

    def test_opening_balance_carries_prior_year_activity(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=80_000, fund="FCRA-GEN",
               posting_date="2025-06-01"),
            gl("6100 Medical Supplies", "Expense", debit=30_000, fund="FCRA-GEN",
               posting_date="2025-09-01"),
            gl("4400 Donation Income", "Income", credit=40_000, fund="FCRA-GEN",
               posting_date="2026-06-01"),
        ]
        summary = build_fcra_register(rows, [], FUNDS,
                                     from_date="2026-04-01", to_date="2027-03-31")["summary"]
        assert summary["opening_balance"] == 50_000
        assert summary["receipts"] == 40_000
        assert summary["closing_balance"] == 90_000

    def test_grant_liability_receipt_counts_as_ledger_receipts(self):
        # A grant is credited to the grant liability account, not to income, so
        # it must be tagged is_grant_liability or the receipt vanishes from the
        # ledger summary entirely (finding: contributor detail 100 vs ledger 0).
        rows = [
            gl("2400 Grant Liability", "Liability", credit=100_000, fund="FCRA-GEN",
               is_grant_liability=True),
        ]
        summary = build_fcra_register(rows, [], FUNDS,
                                     from_date="2026-04-01", to_date="2027-03-31")["summary"]
        assert summary["receipts"] == 100_000
        assert summary["closing_balance"] == 100_000

    def test_grant_recognition_alone_creates_no_second_receipt(self):
        # Grant Utilisation debits the liability and credits income for the same
        # amount, in one voucher. The two legs must net to zero, not double the
        # receipt.
        rows = [
            gl("2400 Grant Liability", "Liability", credit=100_000, fund="FCRA-GEN",
               is_grant_liability=True, voucher_no="JV-0001"),
            gl("2400 Grant Liability", "Liability", debit=40_000, fund="FCRA-GEN",
               is_grant_liability=True, voucher_no="JV-0002"),
            gl("4400 Donation Income", "Income", credit=40_000, fund="FCRA-GEN",
               voucher_no="JV-0002"),
        ]
        summary = build_fcra_register(rows, [], FUNDS,
                                     from_date="2026-04-01", to_date="2027-03-31")["summary"]
        assert summary["receipts"] == 100_000
        assert summary["closing_balance"] == 100_000

    def test_recognition_plus_expense_reduces_closing_balance_by_the_expense_only(self):
        rows = [
            gl("2400 Grant Liability", "Liability", credit=100_000, fund="FCRA-GEN",
               is_grant_liability=True, voucher_no="JV-0001"),
            gl("2400 Grant Liability", "Liability", debit=40_000, fund="FCRA-GEN",
               is_grant_liability=True, voucher_no="JV-0002"),
            gl("4400 Donation Income", "Income", credit=40_000, fund="FCRA-GEN",
               voucher_no="JV-0002"),
            gl("6100 Medical Supplies", "Expense", debit=40_000, fund="FCRA-GEN",
               voucher_no="JV-0003"),
        ]
        summary = build_fcra_register(rows, [], FUNDS,
                                     from_date="2026-04-01", to_date="2027-03-31")["summary"]
        assert summary["utilized"] == 40_000
        assert summary["closing_balance"] == 60_000

    def test_domestic_grant_liability_activity_is_still_excluded(self):
        rows = [
            gl("2400 Grant Liability", "Liability", credit=100_000, fund="GEN",
               is_grant_liability=True),
        ]
        summary = build_fcra_register(rows, [], FUNDS,
                                     from_date="2026-04-01", to_date="2027-03-31")["summary"]
        assert summary["receipts"] == 0

    def test_receipts_detail_lists_only_fcra_donations(self):
        donations = [
            {"name": "D1", "receipt_no": "80G/2026-27/0001", "donation_date": "2026-06-01",
             "donor": "DN1", "donor_name": "Overseas Devotee", "donor_type": "Foreign",
             "amount": 40_000, "mode": "Bank", "fund": "FCRA-GEN", "is_corpus": 0,
             "is_anonymous": 0},
            {"name": "D2", "receipt_no": "80G/2026-27/0002", "donation_date": "2026-06-02",
             "donor": "DN2", "donor_name": "Local Devotee", "donor_type": "Individual",
             "amount": 10_000, "mode": "UPI", "fund": "GEN", "is_corpus": 0,
             "is_anonymous": 0},
        ]
        report = build_fcra_register([], donations, FUNDS)
        assert [row["donation"] for row in report["receipts"]] == ["D1"]
        assert report["summary"]["donation_receipts"] == 40_000


class TestIncomeApplication:
    def test_eighty_five_percent_met_by_revenue_and_capital(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=1_000_000, fund="GEN"),
            gl("6100 Medical Supplies", "Expense", debit=700_000, fund="GEN"),
        ]
        report = build_income_application(
            rows,
            capital_additions=[{"date": "2026-08-01", "amount": 200_000}],
            from_date="2026-04-01",
            to_date="2027-03-31",
        )
        assert report["total_income"] == 1_000_000
        assert report["applied_revenue"] == 700_000
        assert report["applied_capital"] == 200_000
        assert report["required_application"] == 850_000
        assert report["shortfall"] == 0
        assert report["compliant"] is True

    def test_shortfall_is_reported(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=1_000_000, fund="GEN"),
            gl("6100 Medical Supplies", "Expense", debit=500_000, fund="GEN"),
        ]
        report = build_income_application(rows, from_date="2026-04-01", to_date="2027-03-31")
        assert report["shortfall"] == 350_000
        assert report["compliant"] is False
        assert report["application_percent"] == 50.0

    def test_form_10_accumulation_closes_the_gap(self):
        rows = [
            gl("4400 Donation Income", "Income", credit=1_000_000, fund="GEN"),
            gl("6100 Medical Supplies", "Expense", debit=500_000, fund="GEN"),
        ]
        report = build_income_application(
            rows,
            accumulations=[{"amount": 350_000}],
            from_date="2026-04-01",
            to_date="2027-03-31",
        )
        assert report["accumulated"] == 350_000
        assert report["shortfall"] == 0
        assert report["compliant"] is True

    def test_zero_income_does_not_divide_by_zero(self):
        report = build_income_application([])
        assert report["application_percent"] == 0.0
        assert report["compliant"] is True


class TestDonationRegisterAnd10BD:
    DONATIONS = [
        {"name": "D1", "receipt_no": "80G/2026-27/0001", "donation_date": "2026-05-01",
         "donor": "DN1", "donor_name": "A Devotee", "donor_type": "Individual",
         "donor_pan": "ABCDE1234F", "donor_address": "Bangalore",
         "amount": 500_000, "mode": "Bank", "fund": "GEN", "is_corpus": 0,
         "is_anonymous": 0},
        {"name": "D2", "receipt_no": "80G/2026-27/0002", "donation_date": "2026-05-02",
         "donor": "DN1", "donor_name": "A Devotee", "donor_type": "Individual",
         "donor_pan": "ABCDE1234F", "donor_address": "Bangalore",
         "amount": 20_000, "mode": "Cash", "fund": "GEN", "is_corpus": 0,
         "is_anonymous": 0},
        {"name": "D3", "receipt_no": "80G/2026-27/0003", "donation_date": "2026-05-03",
         "donor": "DN2", "donor_name": "Hundi", "donor_type": "Individual",
         "donor_pan": None, "amount": 60_000, "mode": "Cash", "fund": "GEN",
         "is_corpus": 0, "is_anonymous": 1},
        {"name": "D4", "receipt_no": "80G/2026-27/0004", "donation_date": "2026-05-04",
         "donor": "DN3", "donor_name": "Corpus Giver", "donor_type": "Company",
         "donor_pan": None, "amount": 1_000_000, "mode": "Bank", "fund": "CORPUS",
         "is_corpus": 1, "is_anonymous": 0},
    ]

    def test_register_totals_and_corpus_split(self):
        summary = build_donation_register(self.DONATIONS)["summary"]
        assert summary["count"] == 4
        assert summary["total"] == 1_580_000
        assert summary["corpus"] == 1_000_000
        assert summary["income"] == 580_000

    def test_115bbc_uses_the_higher_of_one_lakh_and_five_percent(self):
        summary = build_donation_register(self.DONATIONS)["summary"]
        # 5% of 15,80,000 = 79,000, which beats the ₹1,00,000 floor... it does not,
        # so the floor binds and anonymous 60,000 is fully exempt.
        assert summary["anonymous"] == 60_000
        assert summary["anonymous_exempt_limit"] == 100_000
        assert summary["anonymous_taxable"] == 0
        assert summary["anonymous_threshold_breached"] is False

    def test_115bbc_taxable_excess_when_anonymous_is_large(self):
        donations = [
            {"name": "D1", "donation_date": "2026-05-01", "amount": 500_000,
             "mode": "Cash", "is_anonymous": 1, "is_corpus": 0, "receipt_no": "R1"},
        ]
        summary = build_donation_register(donations)["summary"]
        # 5% of 5,00,000 = 25,000 < ₹1,00,000 floor, so the floor is the limit.
        assert summary["anonymous_exempt_limit"] == 100_000
        assert summary["anonymous_taxable"] == 400_000
        assert summary["anonymous_threshold_breached"] is True

    def test_configured_anonymous_threshold_changes_the_exempt_limit(self):
        # Trust Compliance Settings.anonymous_donation_threshold must actually be
        # honoured when the statutory floor is the binding limb, not silently
        # ignored in favour of the hardcoded default.
        summary = build_donation_register(self.DONATIONS, anonymous_threshold=50_000)["summary"]
        assert summary["anonymous_exempt_limit"] == 79_000  # 5% of 15,80,000 now wins
        assert summary["anonymous_taxable"] == 0

    def test_default_anonymous_threshold_unchanged(self):
        summary = build_donation_register(self.DONATIONS)["summary"]
        assert summary["anonymous_exempt_limit"] == 100_000

    def test_10bd_groups_by_donor_and_splits_cash_from_others(self):
        report = build_form_10bd(self.DONATIONS)
        keys = {(row["donor"], row["donation_type"], row["mode"]) for row in report["rows"]}
        assert ("DN1", "Others", "Others") in keys
        assert ("DN1", "Others", "Cash") in keys
        assert ("DN3", "Corpus", "Others") in keys

    def test_10bd_excludes_anonymous_but_discloses_the_total(self):
        report = build_form_10bd(self.DONATIONS)
        assert all(row["donor"] != "DN2" for row in report["rows"])
        assert report["summary"]["anonymous_total"] == 60_000
        # Reported + anonymous reconciles to the register total.
        assert report["summary"]["reported_total"] + 60_000 == 1_580_000

    def test_10bd_flags_missing_pan_rather_than_dropping_the_donor(self):
        report = build_form_10bd(self.DONATIONS)
        corpus_row = next(row for row in report["rows"] if row["donor"] == "DN3")
        assert corpus_row["pan_missing"] is True
        assert report["summary"]["rows_missing_pan"] == 1

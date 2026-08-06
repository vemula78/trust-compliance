"""Tests for the frappe-free section 11(5)/Rule 17C investment core.

Runnable without a bench: `python3 -m pytest tests/ -q` from the app root.
Mirrors the class-based style of test_core.py, with each assertion's comment
naming the statutory reason it exists.
"""

from __future__ import annotations

import datetime

import pytest

from trust_compliance.core.investment import (
    PERMITTED_MODES,
    RULE_17C_MODES,
    SECTION_11_5_MODES,
    build_investment_register,
    classify_investment_income,
    donated_share_disposal_deadline,
    is_permitted_mode,
    split_interest_receipt,
    validate_investment_mode,
)

# --------------------------------------------------------------------------
# Fixtures: a fund master with one domestic corpus fund and one FCRA fund
# --------------------------------------------------------------------------

CORPUS_FUND = {"name": "CORPUS", "fund_class": "Corpus", "is_fcra": 0}
GEN_FUND = {"name": "GEN", "fund_class": "Unrestricted", "is_fcra": 0}
FCRA_FUND = {"name": "FCRA-GEN", "fund_class": "Unrestricted", "is_fcra": 1}
FUNDS = [CORPUS_FUND, GEN_FUND, FCRA_FUND]


def investment(**overrides):
    base = {
        "investment": "INV-0001",
        "fund": "CORPUS",
        "instrument_type": "Fixed Deposit",
        "mode_clause": "11(5)(iii)",
        "is_equity": 0,
        "issuer": "State Bank of India",
        "issuer_is_psu": 0,
        "counterparty": None,
        "amount": 500_000,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# Masters
# --------------------------------------------------------------------------

class TestMasters:
    def test_permitted_modes_is_the_union_of_both_masters(self):
        assert PERMITTED_MODES == {**SECTION_11_5_MODES, **RULE_17C_MODES}

    def test_is_permitted_mode(self):
        assert is_permitted_mode("11(5)(iii)")
        # Not in the master, e.g. an off-market unlisted debenture.
        assert not is_permitted_mode("private placement debenture")

    def test_rule_17c_ships_empty_on_purpose(self):
        # An earlier version shipped a plausible but materially wrong 17C table.
        # Shipping nothing is the correct behaviour: the Trust's auditor adds the
        # notified clauses to the Investment Mode master. If someone re-populates
        # this table from memory, this test fails and asks them to prove it.
        assert RULE_17C_MODES == {}

    def test_the_live_master_authorises_a_clause_the_seed_table_lacks(self):
        # This is the whole point of the master being editable: a clause the
        # auditor adds must take effect without an app release.
        master = {
            **PERMITTED_MODES,
            "17C(ii)": {"clause": "17C(ii)", "label": "Public Account of India",
                        "is_speculative": False, "allows_equity": False},
        }
        assert not is_permitted_mode("17C(ii)")
        assert is_permitted_mode("17C(ii)", master)
        assert validate_investment_mode(
            investment(mode_clause="17C(ii)"), CORPUS_FUND, modes=master
        ) == []

    def test_a_withdrawn_mode_is_refused_even_though_it_exists(self):
        master = {**PERMITTED_MODES}
        master["11(5)(iv)"] = {**master["11(5)(iv)"], "disabled": True}
        errors = validate_investment_mode(
            investment(mode_clause="11(5)(iv)"), CORPUS_FUND, modes=master
        )
        assert any("withdrawn" in error for error in errors)

    def test_every_mode_carries_the_required_shape(self):
        for clause, mode in PERMITTED_MODES.items():
            assert mode["clause"] == clause
            assert isinstance(mode["label"], str) and mode["label"]
            assert isinstance(mode["is_speculative"], bool)
            assert isinstance(mode["allows_equity"], bool)

    def test_only_11_5_vii_allows_equity(self):
        # Section 11(5) permits equity only in a public sector company.
        equity_clauses = {c for c, m in PERMITTED_MODES.items() if m["allows_equity"]}
        assert equity_clauses == {"11(5)(vii)"}

    def test_equity_under_a_clause_that_does_not_permit_it_is_refused(self):
        # Inspecting the metadata is not enough: the validator must act on it.
        # Labelling PSU equity as a bank deposit must not slip through.
        errors = validate_investment_mode(
            investment(mode_clause="11(5)(iii)", is_equity=1, issuer_is_psu=1),
            CORPUS_FUND,
        )
        assert any("does not permit equity" in error for error in errors)


# --------------------------------------------------------------------------
# validate_investment_mode — the refusal rules
# --------------------------------------------------------------------------

class TestValidateInvestmentMode:
    def test_compliant_bank_fd_from_a_corpus_fund_passes(self):
        # A scheduled-bank FD under 11(5)(iii), bought out of corpus, is squarely
        # permitted; corpus can be invested, it just cannot be transferred out.
        assert validate_investment_mode(investment(), CORPUS_FUND) == []

    def test_mode_outside_section_11_5_and_rule_17c_is_refused(self):
        errors = validate_investment_mode(
            investment(mode_clause="unlisted private equity"), CORPUS_FUND
        )
        assert any("115BBI" in error for error in errors)

    def test_fcra_fund_plus_equity_is_refused(self):
        # 11(5)(vii) is speculative (equity/market-linked); FCRA 2010 s.8(1) and
        # FCRR rule 4 forbid speculative use of foreign contribution outright.
        errors = validate_investment_mode(
            investment(
                mode_clause="11(5)(vii)", is_equity=1, issuer_is_psu=1, fund="FCRA-GEN"
            ),
            FCRA_FUND,
        )
        assert any("speculative" in error for error in errors)

    def test_fcra_fund_plus_bank_fd_is_allowed(self):
        # A plain bank deposit is not speculative, so foreign contribution may
        # fund it; only the speculative modes are barred to an FCRA fund.
        errors = validate_investment_mode(
            investment(mode_clause="11(5)(iii)", fund="FCRA-GEN"), FCRA_FUND
        )
        assert errors == []

    def test_psu_equity_is_allowed(self):
        # Equity shares in a public sector company are the one equity carve-out
        # in section 11(5)(vii).
        errors = validate_investment_mode(
            investment(mode_clause="11(5)(vii)", is_equity=1, issuer_is_psu=1),
            CORPUS_FUND,
        )
        assert errors == []

    def test_non_psu_equity_is_refused(self):
        errors = validate_investment_mode(
            investment(
                mode_clause="11(5)(vii)",
                is_equity=1,
                issuer_is_psu=0,
                issuer="Acme Private Ltd",
            ),
            CORPUS_FUND,
        )
        assert any("public sector company" in error for error in errors)

    def test_prohibited_counterparty_is_refused(self):
        # Section 13(2)(h)/13(3): a trustee's own concern is a person of
        # substantial interest; funds cannot be invested with them.
        errors = validate_investment_mode(
            investment(counterparty="Trustee Holdings Pvt Ltd"),
            CORPUS_FUND,
            prohibited_parties=["Trustee Holdings Pvt Ltd"],
        )
        assert any("13(2)(h)" in error for error in errors)

    def test_counterparty_not_on_the_list_is_not_refused_on_that_ground(self):
        errors = validate_investment_mode(
            investment(counterparty="Unrelated Bank"),
            CORPUS_FUND,
            prohibited_parties=["Trustee Holdings Pvt Ltd"],
        )
        assert errors == []

    def test_zero_amount_is_refused(self):
        errors = validate_investment_mode(investment(amount=0), CORPUS_FUND)
        assert any("greater than zero" in error for error in errors)

    def test_negative_amount_is_refused(self):
        errors = validate_investment_mode(investment(amount=-100), CORPUS_FUND)
        assert any("greater than zero" in error for error in errors)

    def test_multiple_breaches_are_all_reported_together(self):
        # Non-PSU equity, funded by foreign contribution, at a zero amount:
        # three independent breaches, none of which should hide the others.
        errors = validate_investment_mode(
            investment(
                mode_clause="11(5)(vii)",
                is_equity=1,
                issuer_is_psu=0,
                amount=0,
                fund="FCRA-GEN",
            ),
            FCRA_FUND,
        )
        # Assert each breach by name. `len(errors) >= 2` would still pass with
        # any one of the three rules deleted, which is exactly the regression
        # this test exists to catch.
        assert any("public sector" in error for error in errors)
        assert any("foreign contribution" in error for error in errors)
        assert any("greater than zero" in error for error in errors)


# --------------------------------------------------------------------------
# Income classification
# --------------------------------------------------------------------------

class TestClassifyInvestmentIncome:
    def test_interest_is_income_never_corpus(self):
        # The single most consequential rule: corpus-FD interest must reach the
        # 85%-application test as income, not be credited back to corpus.
        assert classify_investment_income("Interest") == "income"

    def test_dividend_is_income(self):
        assert classify_investment_income("Dividend") == "income"

    def test_purchase_redemption_maturity_are_asset_movements(self):
        assert classify_investment_income("Purchase") == "asset"
        assert classify_investment_income("Redemption") == "asset"
        assert classify_investment_income("Maturity") == "asset"

    def test_no_transaction_kind_can_produce_corpus(self):
        # There is deliberately no "corpus" outcome. Corpus arises only from a
        # donation given with that direction, never from anything an investment
        # does - so "Corpus" is not a transaction kind at all. Asserting the
        # refusal is what keeps "interest can never be corpus" structural: if
        # somebody later adds a branch returning "corpus", this test fails.
        with pytest.raises(ValueError):
            classify_investment_income("Corpus")

        for kind in ("Interest", "Dividend", "Purchase", "Redemption", "Maturity"):
            assert classify_investment_income(kind) in {"income", "asset"}

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            classify_investment_income("Bonus Issue")


# --------------------------------------------------------------------------
# TDS split
# --------------------------------------------------------------------------

class TestSplitInterestReceipt:
    def test_splits_gross_into_tds_and_net(self):
        result = split_interest_receipt(10_000, 1_000)
        assert result == {"gross": 10_000.0, "tds": 1_000.0, "net": 9_000.0}

    def test_the_split_always_conserves(self):
        # net + tds must equal gross to the paisa, or the journal entry the
        # controller builds from these three figures will not balance and
        # ERPNext will reject the receipt. Rounding each part independently
        # breaks this: 1.004 / 0.005 rounds to 1.00 / 0.01 / 1.00.
        for gross, tds in [(1.004, 0.005), (10_000, 1_000), (0.01, 0.01),
                           (33.335, 3.335), (999_999.995, 99_999.995)]:
            result = split_interest_receipt(gross, tds)
            assert round(result["net"] + result["tds"], 2) == result["gross"], (
                f"split did not conserve for gross={gross}, tds={tds}: {result}"
            )

    def test_tds_is_not_netted_out_of_the_gross_figure(self):
        # TDS is a recoverable asset, not application of income, so "gross"
        # must survive the split unchanged for the 85% test to use.
        result = split_interest_receipt(10_000, 1_000)
        assert result["gross"] == 10_000.0

    def test_zero_tds_is_allowed(self):
        assert split_interest_receipt(5_000, 0) == {
            "gross": 5_000.0, "tds": 0.0, "net": 5_000.0
        }

    def test_tds_exceeding_gross_is_rejected(self):
        with pytest.raises(ValueError):
            split_interest_receipt(1_000, 1_500)

    def test_negative_gross_is_rejected(self):
        with pytest.raises(ValueError):
            split_interest_receipt(-100, 0)

    def test_negative_tds_is_rejected(self):
        with pytest.raises(ValueError):
            split_interest_receipt(1_000, -50)


# --------------------------------------------------------------------------
# Donated-share disposal deadline
# --------------------------------------------------------------------------

class TestDonatedShareDisposalDeadline:
    def test_deadline_is_one_year_from_fy_end(self):
        # Received mid-year (FY 2026-27, ending 31-Mar-2027): deadline is one
        # year after that FY end, i.e. 31-Mar-2028, not one year from receipt.
        deadline = donated_share_disposal_deadline("2026-06-15")
        assert deadline == datetime.date(2028, 3, 31)

    def test_31_march_receipt_still_falls_in_the_fy_ending_that_day(self):
        # 31-Mar-2027 is the last day of FY 2026-27, so its deadline is the
        # same as any other receipt in that FY: 31-Mar-2028.
        deadline = donated_share_disposal_deadline("2027-03-31")
        assert deadline == datetime.date(2028, 3, 31)

    def test_1_april_receipt_falls_in_the_next_fy(self):
        # One day later the FY rolls to 2027-28 (ending 31-Mar-2028), pushing
        # the deadline a full year further, to 31-Mar-2029.
        deadline = donated_share_disposal_deadline("2027-04-01")
        assert deadline == datetime.date(2029, 3, 31)


# --------------------------------------------------------------------------
# Investment register
# --------------------------------------------------------------------------

def tx(investment_id, kind, amount, tds=0, date="2026-06-15", fund="CORPUS"):
    return {
        "investment": investment_id, "kind": kind, "date": date,
        "amount": amount, "tds": tds, "fund": fund,
    }


class TestBuildInvestmentRegister:
    def test_book_value_after_part_redemption_is_cost_less_redemption(self):
        # Carried at cost, not fair value: a 3,00,000 purchase partly redeemed
        # for 1,00,000 leaves a book value of 2,00,000, not a market value.
        investments = [investment(investment="INV-1", amount=300_000)]
        transactions = [
            tx("INV-1", "Purchase", 300_000, date="2026-04-10"),
            tx("INV-1", "Redemption", 100_000, date="2026-09-01"),
        ]
        register = build_investment_register(investments, transactions, FUNDS)
        row = register["rows"][0]
        assert (row["cost"], row["redeemed"], row["book_value"]) == (
            300_000, 100_000, 200_000,
        )

    def test_interest_is_income_earned_and_carries_its_tds(self):
        investments = [investment(investment="INV-1", amount=300_000)]
        transactions = [
            tx("INV-1", "Purchase", 300_000, date="2026-04-10"),
            tx("INV-1", "Interest", 24_000, tds=2_400, date="2027-03-31"),
        ]
        register = build_investment_register(investments, transactions, FUNDS)
        row = register["rows"][0]
        assert row["income_earned"] == 24_000
        assert row["tds"] == 2_400
        # Interest never touches cost or book value.
        assert row["book_value"] == 300_000

    def test_by_mode_groups_book_value_and_counts_across_investments(self):
        investments = [
            investment(investment="INV-1", amount=200_000, mode_clause="11(5)(iii)"),
            investment(investment="INV-2", amount=100_000, mode_clause="11(5)(iii)"),
            investment(
                investment="INV-3", amount=50_000, mode_clause="11(5)(v)",
                instrument_type="Government Security",
            ),
        ]
        transactions = [
            tx("INV-1", "Purchase", 200_000, date="2026-04-10"),
            tx("INV-2", "Purchase", 100_000, date="2026-04-10"),
            tx("INV-3", "Purchase", 50_000, date="2026-04-10"),
        ]
        register = build_investment_register(investments, transactions, FUNDS)
        assert register["by_mode"]["11(5)(iii)"]["book_value"] == 300_000
        assert register["by_mode"]["11(5)(iii)"]["count"] == 2
        assert register["by_mode"]["11(5)(v)"]["book_value"] == 50_000
        assert register["by_mode"]["11(5)(v)"]["count"] == 1

    def test_non_compliant_instrument_is_surfaced_in_totals(self):
        # An FCRA fund now holding equity - e.g. after an auto-rollover changed
        # the instrument - must show up as non-compliant book value even though
        # no new transaction flags it.
        investments = [
            investment(
                investment="INV-1", fund="FCRA-GEN", amount=100_000,
                mode_clause="11(5)(vii)", is_equity=1, issuer_is_psu=1,
            ),
            investment(investment="INV-2", fund="CORPUS", amount=50_000),
        ]
        transactions = [
            tx("INV-1", "Purchase", 100_000, date="2026-04-10", fund="FCRA-GEN"),
            tx("INV-2", "Purchase", 50_000, date="2026-04-10"),
        ]
        register = build_investment_register(investments, transactions, FUNDS)
        rows_by_id = {row["investment"]: row for row in register["rows"]}
        assert rows_by_id["INV-1"]["is_compliant"] is False
        assert rows_by_id["INV-1"]["violations"] != []
        assert rows_by_id["INV-2"]["is_compliant"] is True
        assert register["totals"]["non_compliant_book_value"] == 100_000
        assert register["totals"]["book_value"] == 150_000

    def test_as_on_clips_transactions_to_that_date(self):
        investments = [investment(investment="INV-1", amount=300_000)]
        transactions = [
            tx("INV-1", "Purchase", 300_000, date="2026-04-10"),
            tx("INV-1", "Redemption", 100_000, date="2026-12-01"),
        ]
        as_of_mid_year = build_investment_register(
            investments, transactions, FUNDS, as_on="2026-06-30"
        )
        as_of_year_end = build_investment_register(
            investments, transactions, FUNDS, as_on="2027-03-31"
        )
        assert as_of_mid_year["rows"][0]["book_value"] == 300_000  # redemption not yet clipped in
        assert as_of_year_end["rows"][0]["book_value"] == 200_000

    def test_totals_sum_every_row(self):
        investments = [
            investment(investment="INV-1", amount=200_000),
            investment(investment="INV-2", amount=100_000, fund="GEN"),
        ]
        transactions = [
            tx("INV-1", "Purchase", 200_000, date="2026-04-10"),
            tx("INV-2", "Purchase", 100_000, date="2026-04-10", fund="GEN"),
            tx("INV-1", "Interest", 5_000, tds=500, date="2027-01-01"),
        ]
        register = build_investment_register(investments, transactions, FUNDS)
        totals = register["totals"]
        assert totals["cost"] == 300_000
        assert totals["book_value"] == 300_000
        assert totals["income_earned"] == 5_000
        assert totals["tds"] == 500

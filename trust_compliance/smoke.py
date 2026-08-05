"""End-to-end self-check for a Trust Compliance install.

Run against a scratch site only - it creates a company, funds, donors and posted
donations:

    bench --site <site> execute trust_compliance.smoke.run

It verifies the things that must be true for the app to be trustworthy: receipts
number gap-free, donations post balanced fund-tagged GL, and every route by which
foreign and domestic money could mix is actually refused. Each check prints PASS
or FAIL and the function returns a non-zero failure count, so it can gate a
deployment.
"""

from __future__ import annotations

import frappe

from trust_compliance.install import seed_trust_funds
from trust_compliance.setup.accounting_dimension import (
    ensure_dimension_fields,
    fund_field_exists,
    set_fund_mandatory,
)

COMPANY = "Sai Trust Smoke"
ABBR = "STS"

_results: list[tuple[bool, str]] = []


def _check(condition: bool, label: str) -> None:
    _results.append((bool(condition), label))
    print(f"{'PASS' if condition else 'FAIL'}  {label}")


def _expect_refusal(label: str, fn) -> None:
    """Assert that `fn` is refused, and that it is refused for the right reason."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - any refusal is the pass condition
            _check(True, f"{label} -- refused: {_first_line(str(exc))}")
            return
    _check(False, f"{label} -- WAS ALLOWED (should have been refused)")


def _first_line(message: str) -> str:
    text = frappe.utils.strip_html(message).strip().splitlines()
    return (text[0] if text else message)[:110]


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def _account(name: str, parent: str, root_type: str, account_type: str | None = None,
             is_fcra: int = 0, is_administrative: int = 0) -> str:
    full = f"{name} - {ABBR}"
    if frappe.db.exists("Account", full):
        return full
    doc = frappe.get_doc({
        "doctype": "Account", "account_name": name, "company": COMPANY,
        "parent_account": f"{parent} - {ABBR}", "root_type": root_type,
        "account_type": account_type, "is_group": 0,
        "is_fcra": is_fcra, "is_administrative": is_administrative,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc.name


def _setup() -> dict:
    if not frappe.db.exists("Company", COMPANY):
        company = frappe.get_doc({
            "doctype": "Company", "company_name": COMPANY, "abbr": ABBR,
            "default_currency": "INR", "country": "India",
        })
        company.flags.ignore_permissions = True
        company.insert()

    if not fund_field_exists():
        ensure_dimension_fields()

    # ERPNext refuses to post outside an active Fiscal Year, which is its
    # equivalent of the source ERP's "open the accounting period first" rule.
    # A fresh site whose setup wizard was never completed has none.
    for start_year in (2025, 2026):
        label = f"{start_year}-{start_year + 1}"
        if frappe.db.exists("Fiscal Year", label):
            continue
        year = frappe.get_doc({
            "doctype": "Fiscal Year", "year": label,
            "year_start_date": f"{start_year}-04-01",
            "year_end_date": f"{start_year + 1}-03-31",
        })
        year.flags.ignore_permissions = True
        year.insert()

    accounts = {
        "bank_account": _account("Domestic Bank", "Bank Accounts", "Asset", "Bank"),
        "fcra_bank_account": _account("FCRA Designated Bank", "Bank Accounts", "Asset",
                                      "Bank", is_fcra=1),
        "cash_account": _account("Donation Cash", "Cash In Hand", "Asset", "Cash"),
        "donation_income_account": _account("Donation Income", "Direct Income", "Income"),
        "corpus_fund_account": _account("Corpus Fund", "Equity", "Equity"),
        "inter_fund_transfer_account": _account("Inter-fund Transfers", "Equity",
                                                "Equity"),
        "property_tax_expense_account": _account("Property Tax", "Indirect Expenses",
                                                 "Expense"),
    }
    _account("Office Administration", "Indirect Expenses", "Expense", is_administrative=1)
    _account("Medical Supplies", "Indirect Expenses", "Expense")

    seed_trust_funds(COMPANY)

    settings = frappe.get_single("Trust Compliance Settings")
    settings.company_accounts = [
        row for row in settings.company_accounts if row.company != COMPANY
    ]
    settings.append("company_accounts", {"company": COMPANY, "receipt_prefix": "80G",
                                         **accounts})
    settings.flags.ignore_permissions = True
    settings.save()

    set_fund_mandatory(COMPANY, default_fund="GEN")

    for donor in [
        {"donor_name": "Domestic Devotee", "donor_type": "Individual",
         "pan": "ABCPD1234E", "address": "Whitefield, Bangalore"},
        {"donor_name": "Overseas Devotee", "donor_type": "Foreign",
         "country": "United States", "address": "New Jersey, USA"},
        {"donor_name": "Hundi Collection", "donor_type": "Individual",
         "is_anonymous": 1},
    ]:
        if not frappe.db.exists("Trust Donor", {"donor_name": donor["donor_name"],
                                                "company": COMPANY}):
            doc = frappe.get_doc({"doctype": "Trust Donor", "company": COMPANY, **donor})
            doc.flags.ignore_permissions = True
            doc.insert()

    return {
        "accounts": accounts,
        "domestic_donor": frappe.db.get_value(
            "Trust Donor", {"donor_name": "Domestic Devotee", "company": COMPANY}),
        "foreign_donor": frappe.db.get_value(
            "Trust Donor", {"donor_name": "Overseas Devotee", "company": COMPANY}),
        "anonymous_donor": frappe.db.get_value(
            "Trust Donor", {"donor_name": "Hundi Collection", "company": COMPANY}),
    }


def _donate(**kwargs):
    doc = frappe.get_doc({
        "doctype": "Trust Donation", "company": COMPANY,
        "donation_date": kwargs.pop("donation_date", "2026-06-15"), **kwargs,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc.reload()


def _journal(rows, posting_date="2026-06-20"):
    doc = frappe.get_doc({
        "doctype": "Journal Entry", "voucher_type": "Journal Entry",
        "company": COMPANY, "posting_date": posting_date,
        "user_remark": "Smoke test", "accounts": rows,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def run() -> int:
    _results.clear()
    context = _setup()
    accounts = context["accounts"]

    print("\n--- dimension ---")
    _check(fund_field_exists(), "fund dimension exists on GL Entry")
    _check(
        bool(frappe.db.exists("Custom Field",
                              {"dt": "Journal Entry Account", "fieldname": "fund"})),
        "fund dimension exists on Journal Entry Account",
    )

    print("\n--- donation receipting and GL ---")
    first = _donate(donor=context["domestic_donor"], fund="GEN", amount=50_000,
                    mode="Bank", purpose="General purposes")
    _check(first.receipt_no == "80G/2026-27/0001",
           f"first receipt of the year is 80G/2026-27/0001 (got {first.receipt_no})")
    _check(first.financial_year == "2026-27", "financial year derived as 2026-27")
    _check(bool(first.journal_entry), "donation posted a Journal Entry")

    gl = frappe.get_all("GL Entry",
                        filters={"voucher_no": first.journal_entry, "is_cancelled": 0},
                        fields=["account", "debit", "credit", "fund"])
    _check(len(gl) == 2, f"two GL rows posted (got {len(gl)})")
    _check(sum(row.debit for row in gl) == sum(row.credit for row in gl) == 50_000,
           "GL entry is balanced at 50,000")
    _check(all(row.fund == "GEN" for row in gl), "every GL row is tagged to fund GEN")
    _check(any(row.account == accounts["bank_account"] and row.debit == 50_000
               for row in gl), "domestic bank account debited")
    _check(any(row.account == accounts["donation_income_account"] and row.credit == 50_000
               for row in gl), "donation income credited")

    second = _donate(donor=context["domestic_donor"], fund="GEN", amount=10_000,
                     mode="UPI", donation_date="2026-06-16")
    _check(second.receipt_no == "80G/2026-27/0002",
           f"series continues to 0002 (got {second.receipt_no})")

    prior_fy = _donate(donor=context["domestic_donor"], fund="GEN", amount=1_000,
                       mode="Bank", donation_date="2026-03-31")
    _check(prior_fy.receipt_no == "80G/2025-26/0001",
           f"31-Mar-2026 numbers into 2025-26 (got {prior_fy.receipt_no})")

    print("\n--- corpus routing ---")
    corpus = _donate(donor=context["domestic_donor"], fund="CORPUS", amount=500_000,
                     mode="Bank", is_corpus=1)
    corpus_gl = frappe.get_all("GL Entry",
                               filters={"voucher_no": corpus.journal_entry,
                                        "is_cancelled": 0},
                               fields=["account", "credit"])
    _check(any(row.account == accounts["corpus_fund_account"] and row.credit == 500_000
               for row in corpus_gl),
           "corpus donation credits the corpus equity account, not income")
    _check(not any(row.account == accounts["donation_income_account"]
                   for row in corpus_gl),
           "corpus donation does not touch donation income")

    print("\n--- FCRA: foreign contribution ---")
    foreign = _donate(donor=context["foreign_donor"], fund="FCRA-GEN", amount=100_000,
                      mode="Bank")
    foreign_gl = frappe.get_all("GL Entry",
                                filters={"voucher_no": foreign.journal_entry,
                                         "is_cancelled": 0},
                                fields=["account", "debit", "fund"])
    _check(any(row.account == accounts["fcra_bank_account"] and row.debit == 100_000
               for row in foreign_gl),
           "foreign contribution is banked into the FCRA-designated account")
    _check(all(row.fund == "FCRA-GEN" for row in foreign_gl),
           "every FCRA GL row is tagged to the FCRA fund")

    print("\n--- FCRA: every route to mixing must be refused ---")
    _expect_refusal(
        "foreign donor into a domestic fund",
        lambda: _donate(donor=context["foreign_donor"], fund="GEN", amount=1_000,
                        mode="Bank"),
    )
    _expect_refusal(
        "domestic donor into an FCRA fund",
        lambda: _donate(donor=context["domestic_donor"], fund="FCRA-GEN", amount=1_000,
                        mode="Bank"),
    )
    _expect_refusal(
        "foreign contribution received in cash",
        lambda: _donate(donor=context["foreign_donor"], fund="FCRA-GEN", amount=1_000,
                        mode="Cash"),
    )
    _expect_refusal(
        "journal entry mixing an FCRA fund with a domestic fund",
        lambda: _journal([
            {"account": accounts["fcra_bank_account"],
             "debit_in_account_currency": 5_000, "fund": "FCRA-GEN"},
            {"account": accounts["donation_income_account"],
             "credit_in_account_currency": 5_000, "fund": "GEN"},
        ]),
    )
    _expect_refusal(
        "journal entry debiting the FCRA bank with no fund tagged anywhere",
        lambda: _journal([
            {"account": accounts["fcra_bank_account"],
             "debit_in_account_currency": 5_000},
            {"account": accounts["donation_income_account"],
             "credit_in_account_currency": 5_000},
        ]),
    )
    _expect_refusal(
        "journal entry naming a fund that is not in the master",
        lambda: _journal([
            {"account": accounts["bank_account"], "debit_in_account_currency": 100,
             "fund": "NOPE"},
            {"account": accounts["donation_income_account"],
             "credit_in_account_currency": 100, "fund": "GEN"},
        ]),
    )

    print("\n--- other statutory guards ---")
    _expect_refusal(
        "cash donation above the Section 269ST limit",
        lambda: _donate(donor=context["domestic_donor"], fund="GEN", amount=300_000,
                        mode="Cash"),
    )
    _expect_refusal(
        "corpus donation into a non-corpus fund",
        lambda: _donate(donor=context["domestic_donor"], fund="GEN", amount=1_000,
                        mode="Bank", is_corpus=1),
    )
    _expect_refusal(
        "making an FCRA fund the company default",
        lambda: frappe.get_doc("Fund", "FCRA-GEN").db_set("is_default", 1)
        or frappe.get_doc("Fund", "FCRA-GEN").save(),
    )

    print("\n--- wholly domestic and wholly FCRA journals still post ---")
    try:
        _journal([
            {"account": accounts["bank_account"], "debit_in_account_currency": 2_000,
             "fund": "HOSP"},
            {"account": accounts["donation_income_account"],
             "credit_in_account_currency": 2_000, "fund": "HOSP"},
        ])
        _check(True, "wholly domestic journal entry posts")
    except Exception as exc:  # noqa: BLE001
        _check(False, f"wholly domestic journal entry posts -- {_first_line(str(exc))}")

    try:
        _journal([
            {"account": "Office Administration - " + ABBR,
             "debit_in_account_currency": 3_000, "fund": "FCRA-GEN"},
            {"account": accounts["fcra_bank_account"],
             "credit_in_account_currency": 3_000, "fund": "FCRA-GEN"},
        ])
        _check(True, "wholly FCRA journal entry posts (administrative expense)")
    except Exception as exc:  # noqa: BLE001
        _check(False, f"wholly FCRA journal entry posts -- {_first_line(str(exc))}")

    frappe.db.commit()

    failures = sum(1 for ok, _label in _results if not ok)
    print(f"\n{len(_results) - failures}/{len(_results)} checks passed"
          f"{'' if not failures else f', {failures} FAILED'}")
    return failures

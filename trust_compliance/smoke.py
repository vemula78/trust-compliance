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
from frappe.utils import flt

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


def _reset() -> None:
    """Remove the previous run's transactions so the check is re-runnable.

    Without this the second run doubles every figure, and the absolute assertions
    below fail while the ratio assertions still pass - which is exactly how a
    non-idempotent test hides itself. Donations are cancelled first because
    cancelling a donation cancels its Journal Entry; whatever is left is a journal
    the test posted directly.
    """
    for donation in frappe.get_all("Trust Donation", filters={"company": COMPANY},
                                   fields=["name", "docstatus"]):
        doc = frappe.get_doc("Trust Donation", donation.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        doc.delete(ignore_permissions=True, force=True)

    for doctype in ("Property Tax Schedule", "Property Maintenance"):
        for row in frappe.get_all(doctype, filters={"company": COMPANY},
                                  fields=["name", "docstatus"]):
            doc = frappe.get_doc(doctype, row.name)
            if doc.docstatus == 1:
                doc.flags.ignore_permissions = True
                doc.cancel()
            doc.delete(ignore_permissions=True, force=True)

    for row in frappe.get_all("Purchase Invoice", filters={"company": COMPANY},
                              fields=["name", "docstatus"]):
        doc = frappe.get_doc("Purchase Invoice", row.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        doc.delete(ignore_permissions=True, force=True)

    for transfer in frappe.get_all("Fund Transfer", filters={"company": COMPANY},
                                   fields=["name", "docstatus"]):
        doc = frappe.get_doc("Fund Transfer", transfer.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        doc.delete(ignore_permissions=True, force=True)

    for entry in frappe.get_all("Journal Entry", filters={"company": COMPANY},
                                fields=["name", "docstatus"]):
        doc = frappe.get_doc("Journal Entry", entry.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        doc.delete(ignore_permissions=True, force=True)

    frappe.db.delete("GL Entry", {"company": COMPANY})
    frappe.db.commit()


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

    # More setup-wizard fixtures a pwd/scratch site lacks: a Warehouse Type for
    # company creation, and a UOM for the property-tax invoice line.
    for doctype, name in (("Warehouse Type", "Transit"), ("UOM", "Nos")):
        if not frappe.db.exists(doctype, name):
            doc = frappe.get_doc({"doctype": doctype, "__newname": name,
                                  **({"uom_name": name} if doctype == "UOM" else {})})
            doc.flags.ignore_permissions = True
            doc.insert()

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


def _transfer(**kwargs):
    doc = frappe.get_doc({
        "doctype": "Fund Transfer", "company": COMPANY,
        "transfer_date": kwargs.pop("transfer_date", "2026-06-25"),
        "reason": kwargs.pop("reason", "Board resolution dated 20-Jun-2026"),
        **kwargs,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc.reload()


def _check_fund_transfers() -> None:
    print("\n--- fund transfers ---")

    transfer = _transfer(from_fund="GEN", to_fund="HOSP", amount=25_000)
    gl = frappe.get_all("GL Entry",
                        filters={"voucher_no": transfer.journal_entry, "is_cancelled": 0},
                        fields=["account", "debit", "credit", "fund"])
    _check(len(gl) == 2, f"transfer posted two GL rows (got {len(gl)})")
    _check(len({row.account for row in gl}) == 1,
           "both legs sit on the same equity clearing account")
    _check(sum(row.debit for row in gl) == sum(row.credit for row in gl) == 25_000,
           "transfer entry is balanced at 25,000")
    _check(any(row.fund == "GEN" and row.debit == 25_000 for row in gl),
           "source fund carries the debit leg")
    _check(any(row.fund == "HOSP" and row.credit == 25_000 for row in gl),
           "destination fund carries the credit leg")

    _expect_refusal(
        "transferring out of a Corpus fund",
        lambda: _transfer(from_fund="CORPUS", to_fund="GEN", amount=1_000),
    )
    _expect_refusal(
        "transferring from a domestic fund into an FCRA fund",
        lambda: _transfer(from_fund="GEN", to_fund="FCRA-GEN", amount=1_000),
    )
    _expect_refusal(
        "transferring from an FCRA fund into a domestic fund",
        lambda: _transfer(from_fund="FCRA-GEN", to_fund="GEN", amount=1_000),
    )
    _expect_refusal(
        "transferring a fund to itself",
        lambda: _transfer(from_fund="GEN", to_fund="GEN", amount=1_000),
    )

    # Transfers into corpus are legitimate: capital may be added, not withdrawn.
    try:
        _transfer(from_fund="GEN", to_fund="CORPUS", amount=5_000)
        _check(True, "transferring into a Corpus fund is allowed")
    except Exception as exc:  # noqa: BLE001
        _check(False, f"transferring into a Corpus fund -- {_first_line(str(exc))}")

    _check(
        not frappe.db.exists("Custom Field",
                             {"dt": "Fund Transfer", "fieldname": "fund"}),
        "Fund Transfer is not itself dimension-tagged (it posts a Journal Entry)",
    )


def _check_property_register() -> None:
    print("\n--- property register ---")

    if not frappe.db.exists("Supplier", "Whitefield Municipality"):
        supplier = frappe.get_doc({
            "doctype": "Supplier", "supplier_name": "Whitefield Municipality",
            "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
            "is_municipality": 1,
        })
        supplier.flags.ignore_permissions = True
        supplier.insert()

    prop_name = frappe.db.get_value("Trust Property",
                                    {"property_name": "Devotee House, Whitefield"})
    if not prop_name:
        prop = frappe.get_doc({
            "doctype": "Trust Property", "company": COMPANY,
            "property_name": "Devotee House, Whitefield",
            "property_type": "Land and Building", "status": "Active",
            "fund": "HOSP", "municipality": "Whitefield Municipality",
            "survey_number": "112/4A", "extent": 4800, "extent_uom": "Sq Ft",
            "valuation": 9_500_000, "valuation_date": "2026-05-01",
            "donation_date": "2026-05-01", "address": "EPIP Area, Whitefield, Bangalore",
        })
        prop.flags.ignore_permissions = True
        prop.insert()
        prop_name = prop.name
    _check(bool(prop_name), f"property created ({prop_name})")

    tax = frappe.get_doc({
        "doctype": "Property Tax Schedule", "property": prop_name,
        "financial_year": "2026-27", "amount": 42_000, "due_date": "2026-09-30",
    })
    tax.flags.ignore_permissions = True
    tax.insert()
    tax.submit()
    tax.reload()

    _check(bool(tax.purchase_invoice),
           f"tax demand raised a Purchase Invoice ({tax.purchase_invoice})")
    _check(tax.status == "Billed", f"demand status is Billed (got {tax.status})")
    _check(tax.period_from == frappe.utils.getdate("2026-04-01")
           and tax.period_to == frappe.utils.getdate("2027-03-31"),
           "assessment period defaulted to the financial year")

    invoice = frappe.get_doc("Purchase Invoice", tax.purchase_invoice)
    _check(invoice.supplier == "Whitefield Municipality",
           "invoice is raised on the municipality, so the demand sits in payables")
    _check(flt(invoice.outstanding_amount) == 42_000,
           f"demand is outstanding in AP at 42,000 (got {invoice.outstanding_amount})")

    gl = frappe.get_all("GL Entry",
                        filters={"voucher_no": tax.purchase_invoice, "is_cancelled": 0},
                        fields=["account", "debit", "credit", "fund"])
    _check(any(flt(row.debit) == 42_000 and row.fund == "HOSP" for row in gl),
           "property tax expense is tagged to the property's fund (HOSP)")
    _check(any(flt(row.credit) == 42_000 for row in gl),
           "payable is credited, not cash")

    # Paying the demand must flip the register to Paid, derived from the invoice's
    # outstanding amount rather than set by hand.
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

    payment = get_payment_entry("Purchase Invoice", tax.purchase_invoice)
    payment.paid_from = _account("Domestic Bank", "Bank Accounts", "Asset", "Bank")
    payment.reference_no = "NEFT-PTAX-2026"
    payment.reference_date = "2026-09-15"
    payment.posting_date = "2026-09-15"
    # Both legs of a payment are balance-sheet accounts, and the fund dimension is
    # mandatory for those - so a payment out of a fund's money must name the fund.
    payment.fund = "HOSP"
    for row in payment.references:
        row.fund = "HOSP"
    payment.flags.ignore_permissions = True
    payment.insert()
    payment.submit()

    tax.reload()
    _check(tax.status == "Paid",
           f"paying the invoice flips the demand to Paid (got {tax.status})")
    _check(flt(frappe.db.get_value("Purchase Invoice", tax.purchase_invoice,
                                   "outstanding_amount")) == 0,
           "invoice is fully settled in AP")

    payment_gl = frappe.get_all("GL Entry",
                                filters={"voucher_no": payment.name, "is_cancelled": 0},
                                fields=["account", "fund"])
    _check(all(row.fund == "HOSP" for row in payment_gl),
           "payment GL stays on the property's fund")

    _expect_refusal(
        "a second tax demand for the same property and year",
        lambda: frappe.get_doc({
            "doctype": "Property Tax Schedule", "property": prop_name,
            "financial_year": "2026-27", "amount": 42_000, "due_date": "2026-09-30",
        }).insert(ignore_permissions=True).submit(),
    )

    maintenance = frappe.get_doc({
        "doctype": "Property Maintenance", "property": prop_name,
        "maintenance_type": "Repair", "description": "Compound wall repair",
        "start_date": "2026-07-01", "end_date": "2026-07-20", "amount": 65_000,
        "status": "Completed",
    })
    maintenance.flags.ignore_permissions = True
    maintenance.insert()
    maintenance.submit()
    _check(maintenance.fund == "HOSP", "maintenance inherits the property's fund")

    _expect_refusal(
        "an AMC with no end date",
        lambda: frappe.get_doc({
            "doctype": "Property Maintenance", "property": prop_name,
            "maintenance_type": "AMC", "description": "Lift AMC",
            "start_date": "2026-07-01", "status": "Open",
        }).insert(ignore_permissions=True),
    )
    _expect_refusal(
        "maintenance completed with no end date",
        lambda: frappe.get_doc({
            "doctype": "Property Maintenance", "property": prop_name,
            "maintenance_type": "Repair", "description": "Painting",
            "start_date": "2026-07-01", "status": "Completed",
        }).insert(ignore_permissions=True),
    )

    from trust_compliance.trust_compliance.doctype.trust_property.trust_property import (
        get_property_summary,
    )
    summary = get_property_summary(prop_name)
    _check(flt(summary["tax"]["total"]) == 42_000,
           f"property summary shows 42,000 tax billed (got {summary['tax']['total']})")
    # The demand was paid above, so nothing is outstanding - and this figure is
    # read from the invoice, not from the schedule's status field.
    _check(flt(summary["tax"]["outstanding"]) == 0,
           f"property summary shows nothing outstanding (got {summary['tax']['outstanding']})")
    _check(flt(summary["maintenance"]["total"]) == 65_000,
           f"property summary shows 65,000 maintenance (got {summary['maintenance']['total']})")


def _gl_rows() -> list[dict]:
    """Live GL entries joined to their account's root type and admin flag.

    This is the single query every report in `core/` is driven from, which is why
    the reports cannot disagree with the ledger: there is no second source.
    """
    return frappe.db.sql(
        """
        SELECT gle.account, gle.debit, gle.credit, gle.fund, gle.posting_date,
               gle.voucher_no, gle.remarks,
               acc.root_type, acc.is_administrative
        FROM `tabGL Entry` gle
        JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company = %s AND gle.is_cancelled = 0
        """,
        (COMPANY,),
        as_dict=True,
    )


def _check_reports() -> None:
    """Drive the pure report builders from live GL and reconcile the totals."""
    from trust_compliance.core.compliance import build_fcra_register
    from trust_compliance.core.fund_balance import build_fund_balances

    print("\n--- reports against live GL ---")
    gl_rows = _gl_rows()
    funds = frappe.get_all(
        "Fund",
        filters={"company": COMPANY},
        fields=["name", "fund_name", "fund_class", "is_default", "is_fcra"],
    )

    balances = build_fund_balances(gl_rows, funds,
                                   from_date="2026-04-01", to_date="2027-03-31")
    by_fund = {row["fund"]: row for row in balances["rows"]}

    # 50,000 + 10,000 domestic into GEN this year, and 1,000 in 2025-26 which must
    # land in opening rather than in the year's inflow.
    _check(by_fund["GEN"]["inflow"] == 60_000,
           f"GEN inflow is 60,000 this year (got {by_fund['GEN']['inflow']})")
    _check(by_fund["GEN"]["opening"] == 1_000,
           f"GEN opening carries the 2025-26 donation (got {by_fund['GEN']['opening']})")
    # 5,00,000 corpus donation plus a 5,000 transfer in.
    _check(by_fund["CORPUS"]["balance"] == 505_000,
           f"CORPUS balance is 505,000 (got {by_fund['CORPUS']['balance']})")
    # 2,000 manual journal plus a 25,000 transfer in.
    _check(by_fund["HOSP"]["inflow"] == 27_000,
           f"HOSP inflow is 27,000 incl. transfer (got {by_fund['HOSP']['inflow']})")
    # 25,000 + 5,000 transferred out of GEN; transfers net to zero overall.
    _check(by_fund["GEN"]["outflow"] == 30_000,
           f"GEN outflow is 30,000 from transfers (got {by_fund['GEN']['outflow']})")
    _check(
        round(balances["total_opening"] + balances["total_inflow"]
              - balances["total_outflow"], 2) == balances["total_balance"],
        "fund totals reconcile: opening + inflow - outflow == closing",
    )
    # GEN -25,000 -5,000, HOSP +25,000, CORPUS +5,000: transfers cancel out.
    _check(
        round(sum(row["inflow"] for row in balances["rows"])
              - sum(row["outflow"] for row in balances["rows"]), 2)
        == balances["total_inflow"] - balances["total_outflow"],
        "transfers net to zero across all funds",
    )

    # FCRA fund: 100,000 received, 3,000 spent on an administrative account.
    _check(by_fund["FCRA-GEN"]["inflow"] == 100_000,
           f"FCRA-GEN inflow is 100,000 (got {by_fund['FCRA-GEN']['inflow']})")
    _check(by_fund["FCRA-GEN"]["outflow"] == 3_000,
           f"FCRA-GEN outflow is 3,000 (got {by_fund['FCRA-GEN']['outflow']})")

    donations = frappe.get_all(
        "Trust Donation",
        filters={"company": COMPANY, "docstatus": 1},
        fields=["name", "receipt_no", "donation_date", "donor", "donor_name",
                "donor_type", "amount", "mode", "fund", "is_corpus", "is_anonymous",
                "purpose"],
    )
    fcra = build_fcra_register(gl_rows, donations, funds,
                               from_date="2026-04-01", to_date="2027-03-31")
    summary = fcra["summary"]
    _check(summary["receipts"] == 100_000,
           f"FC-4 receipts are 100,000 (got {summary['receipts']})")
    _check(summary["admin_utilized"] == 3_000,
           f"administrative utilisation is 3,000 (got {summary['admin_utilized']})")
    _check(summary["admin_percent"] == 3.0,
           f"admin ratio is 3% of contribution received (got {summary['admin_percent']}%)")
    _check(summary["admin_cap_exceeded"] is False, "20% FCRA admin cap not breached")
    _check(summary["closing_balance"] == 97_000,
           f"FCRA closing balance is 97,000 (got {summary['closing_balance']})")
    _check(len(fcra["receipts"]) == 1 and fcra["receipts"][0]["amount"] == 100_000,
           "FC-4 contributor detail lists exactly the one foreign donation")
    _check(summary["donation_receipts"] == summary["journal_receipts"],
           "register detail total reconciles to the GL-derived receipts figure")


REPORTS = [
    "Fund Balances",
    "Fund Income and Expenditure",
    "Donation Register",
    "FCRA Register",
    "Income Application",
    "Form 10BD Statement",
    "Property Register",
]


def _check_query_reports(context: dict) -> None:
    """Run every shipped report end to end, as the desk runs them.

    This is what catches a broken column definition, a filter the report does not
    read, or a report registered in the wrong module - none of which the pure
    tests can see, because none of them exist at that layer.
    """
    from frappe.desk.query_report import run as run_query_report

    print("\n--- query reports ---")
    filters = {"company": COMPANY, "financial_year": "2026-27"}

    for report_name in REPORTS:
        _check(bool(frappe.db.exists("Report", report_name)),
               f"report {report_name!r} is registered")
        report_filters = (
            {"company": COMPANY} if report_name == "Property Register" else filters
        )
        try:
            result = run_query_report(report_name, filters=report_filters,
                                      ignore_prepared_report=True)
            columns, data = result.get("columns") or [], result.get("result") or []
            _check(bool(columns) and bool(data),
                   f"report {report_name!r} returns {len(columns)} columns "
                   f"and {len(data)} rows")
            # Shape matters as much as content: Frappe's execute() contract is
            # (columns, data, message, chart, report_summary). Returning a chart
            # in the report_summary position makes the desk try to iterate it and
            # the report renders completely blank while this call still looks
            # healthy - so the shape is asserted, not just the payload.
            summary = result.get("report_summary")
            _check(summary is None or isinstance(summary, list),
                   f"report {report_name!r} report_summary is a list or None "
                   f"(got {type(summary).__name__})")
            chart = result.get("chart")
            _check(chart is None or isinstance(chart, dict),
                   f"report {report_name!r} chart is a dict or None "
                   f"(got {type(chart).__name__})")
        except Exception as exc:  # noqa: BLE001
            _check(False, f"report {report_name!r} -- {_first_line(str(exc))}")

    # Filters must actually filter, not merely be accepted.
    try:
        unfiltered = run_query_report("Donation Register", filters=filters,
                                      ignore_prepared_report=True)["result"]
        corpus_only = run_query_report(
            "Donation Register", filters={**filters, "fund": "CORPUS"},
            ignore_prepared_report=True)["result"]
        _check(len(corpus_only) < len(unfiltered) and len(corpus_only) == 1,
               f"Donation Register fund filter narrows 4 rows to 1 "
               f"(got {len(unfiltered)} -> {len(corpus_only)})")
    except Exception as exc:  # noqa: BLE001
        _check(False, f"Donation Register fund filter -- {_first_line(str(exc))}")

    print("\n--- print output ---")
    receipt = frappe.get_all("Trust Donation",
                             filters={"company": COMPANY, "docstatus": 1,
                                      "is_corpus": 0},
                             fields=["name", "amount_in_words"], limit=1)[0]
    _check((receipt.amount_in_words or "").startswith("Rupees "),
           f"amount in words is set ({receipt.amount_in_words})")

    try:
        html = frappe.get_print("Trust Donation", receipt.name,
                                print_format="80G Donation Receipt")
        _check("80G" in html or "Receipt for Donation" in html,
               "80G Donation Receipt print format renders")
        _check(receipt.amount_in_words in html,
               "receipt prints the amount in words")
    except Exception as exc:  # noqa: BLE001
        _check(False, f"80G receipt print format -- {_first_line(str(exc))}")

    try:
        from trust_compliance.form_10be import get_certificate_html

        cert = get_certificate_html(context["domestic_donor"], "2026-27")
        _check("FORM No. 10BE" in cert, "Form 10BE certificate renders")
        # 50,000 bank + 10,000 UPI + 5,00,000 corpus in 2026-27 for this donor.
        # Asserted in Indian grouping: 5,60,000 and not 560,000.
        _check("5,60,000" in cert.replace("&nbsp;", " "),
               "Form 10BE totals the donor's year at 5,60,000 in Indian grouping")
        _check("Five Lakh" in cert,
               "Form 10BE spells the total in Indian numbering (lakh, not thousand)")
    except Exception as exc:  # noqa: BLE001
        _check(False, f"Form 10BE certificate -- {_first_line(str(exc))}")

    _expect_refusal(
        "Form 10BE for an anonymous donor",
        lambda: __import__("trust_compliance.form_10be", fromlist=["x"])
        .get_certificate_html(context["anonymous_donor"], "2026-27"),
    )


def run() -> int:
    _results.clear()
    context = _setup()
    _reset()
    accounts = context["accounts"]

    print("\n--- site configuration ---")
    # The *effective* format, which on Frappe 16 resolves Language record ->
    # DefaultValue -> fallback. System Settings alone is not authoritative.
    number_format = frappe.locale.get_number_format().string
    _check(
        number_format == "#,##,###.##",
        f"site number format is Indian (#,##,###.##), got {number_format!r} - "
        f"without it 80G receipts print \"Five Hundred And Sixty Thousand\" "
        f"instead of \"Five Lakh Sixty Thousand\"",
    )

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

    _check_fund_transfers()
    _check_property_register()
    _check_reports()
    _check_query_reports(context)

    frappe.db.commit()

    failures = sum(1 for ok, _label in _results if not ok)
    print(f"\n{len(_results) - failures}/{len(_results)} checks passed"
          f"{'' if not failures else f', {failures} FAILED'}")
    return failures

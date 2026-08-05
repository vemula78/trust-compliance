"""Register Fund as an ERPNext Accounting Dimension.

This is the load-bearing integration point. Creating an Accounting Dimension for
the Fund doctype makes ERPNext itself add a `fund` Link field to GL Entry and to
every voucher and voucher line that produces GL - Journal Entry Account, Payment
Entry, Sales and Purchase Invoice and their items and taxes, Expense Claim, Stock
Entry, Asset, Payroll Entry, and anything a future version adds to that list.

The consequence is that fund is not a bolted-on tag: it flows through ERPNext's
own posting engine, its dimension filters, and its Financial Statements, General
Ledger and Trial Balance reports, which all already accept a dimension filter.
Fund-wise reporting therefore mostly comes for free, and the app only has to add
the statements ERPNext has no concept of.
"""

from __future__ import annotations

import frappe

DIMENSION_DOCTYPE = "Fund"
DIMENSION_LABEL = "Fund"


def create_fund_dimension() -> None:
    if frappe.db.exists("Accounting Dimension", DIMENSION_DOCTYPE):
        return

    dimension = frappe.get_doc(
        {
            "doctype": "Accounting Dimension",
            "document_type": DIMENSION_DOCTYPE,
            "label": DIMENSION_LABEL,
            "disabled": 0,
        }
    )
    dimension.flags.ignore_permissions = True
    dimension.insert()


def set_fund_mandatory(company: str, default_fund: str | None = None) -> None:
    """Make the fund dimension mandatory for a company.

    ERPNext holds this per company in the dimension's `dimension_defaults` table,
    with separate flags for balance-sheet and P&L accounts. Both are set: the
    Trust's requirement is that no transaction posts without a fund, and a fund
    balance is a net-asset figure that needs the balance-sheet side tagged too.

    A default fund is also recorded, so ERPNext pre-fills it rather than leaving
    the clerk to pick on every line. That is a convenience, not the enforcement -
    the enforcement is `trust_compliance.fcra`, and fund reports attribute any
    untagged line to the default fund so money is never lost from a report.
    """
    if not frappe.db.exists("Accounting Dimension", DIMENSION_DOCTYPE):
        create_fund_dimension()

    dimension = frappe.get_doc("Accounting Dimension", DIMENSION_DOCTYPE)
    row = next(
        (item for item in dimension.dimension_defaults if item.company == company), None
    )
    if row is None:
        row = dimension.append("dimension_defaults", {"company": company})

    row.reference_document = DIMENSION_DOCTYPE
    row.mandatory_for_bs = 1
    row.mandatory_for_pl = 1
    if default_fund:
        row.default_dimension = default_fund

    dimension.flags.ignore_permissions = True
    dimension.save()

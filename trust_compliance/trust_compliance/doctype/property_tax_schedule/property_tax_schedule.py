"""Property-tax demand, billed through Accounts Payable.

On submit this creates a **Purchase Invoice** against the municipality supplier
rather than posting the expense straight to the tax account. That is deliberate,
and it is a correction of the Next.js implementation, which debited the property
tax expense account and credited cash in one entry:

- A tax demand is a liability from the day it is raised, not from the day it is
  paid. Routing it through AP means the Trust's payables show what it owes local
  bodies, which is what a demand notice actually is.
- Payment then happens through ERPNext's ordinary Payment Entry flow, with bank
  reconciliation, ageing and the supplier ledger all working normally.
- The property-tax expense lands on the property's own fund, because tax on a
  hospital-fund property is the hospital fund's expenditure.

The fund is taken from the property and written onto the invoice's item row, so
the FCRA segregation rule sees it like any other voucher.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from trust_compliance.core.financial_year import financial_year_window, is_financial_year
from trust_compliance.trust_compliance.doctype.trust_compliance_settings.trust_compliance_settings import (
    get_company_accounts,
)


class PropertyTaxSchedule(Document):
    def validate(self):
        self._validate_financial_year()
        self._validate_amount()
        self._validate_period()
        self._validate_no_duplicate_demand()

    def before_submit(self):
        if not self.municipality:
            frappe.throw(
                _(
                    "A municipality is needed to raise the demand: property tax is "
                    "billed to and paid through the local body, so it goes through "
                    "Accounts Payable."
                )
            )

    def on_submit(self):
        invoice = self._create_purchase_invoice()
        self.db_set("purchase_invoice", invoice, update_modified=False)
        self.db_set("status", "Billed", update_modified=False)

    def on_cancel(self):
        self.flags.ignore_links = True
        if self.purchase_invoice:
            invoice = frappe.get_doc("Purchase Invoice", self.purchase_invoice)
            if invoice.docstatus == 1:
                invoice.flags.ignore_permissions = True
                invoice.cancel()
        self.db_set("status", "Unpaid", update_modified=False)

    # -- validation ---------------------------------------------------------

    def _validate_financial_year(self):
        self.financial_year = (self.financial_year or "").strip()
        if not is_financial_year(self.financial_year):
            frappe.throw(
                _('Financial Year must be an Indian financial year such as "2026-27".')
            )

    def _validate_amount(self):
        if flt(self.amount) <= 0:
            frappe.throw(_("Tax demanded must be greater than zero."))

    def _validate_period(self):
        if self.period_from and self.period_to:
            if getdate(self.period_to) < getdate(self.period_from):
                frappe.throw(_("Period To cannot be before Period From."))

        if not self.period_from or not self.period_to:
            self.period_from, self.period_to = (
                str(date) for date in financial_year_window(self.financial_year)
            )

    def _validate_no_duplicate_demand(self):
        """One demand per property per financial year.

        Paying the same demand twice is the failure this guards against - a
        municipality reissuing a notice is a common way for it to happen, and the
        second payment is not easy to recover.
        """
        duplicate = frappe.db.exists(
            "Property Tax Schedule",
            {
                "property": self.property,
                "financial_year": self.financial_year,
                "docstatus": 1,
                "name": ("!=", self.name),
            },
        )
        if duplicate:
            frappe.throw(
                _(
                    "Property {0} already has a submitted tax demand for {1} ({2}). "
                    "Amend that one rather than raising a second demand."
                ).format(self.property_name or self.property, self.financial_year, duplicate),
                title=_("Duplicate Demand"),
            )

    # -- AP posting ---------------------------------------------------------

    def _create_purchase_invoice(self) -> str:
        accounts = get_company_accounts(self.company)
        expense_account = accounts.get("property_tax_expense_account")
        if not expense_account:
            frappe.throw(
                _(
                    "No property tax expense account is configured for {0}. Set it in "
                    "Trust Compliance Settings."
                ).format(self.company),
                title=_("Setup Incomplete"),
            )

        description = _("Property tax for {0}, {1} ({2} to {3})").format(
            self.property_name or self.property, self.financial_year,
            self.period_from, self.period_to,
        )

        invoice = frappe.get_doc(
            {
                "doctype": "Purchase Invoice",
                "company": self.company,
                "supplier": self.municipality,
                "posting_date": frappe.utils.nowdate(),
                "bill_date": frappe.utils.nowdate(),
                "due_date": self.due_date,
                "remarks": description,
                # The fund is needed at parent level as well as on the item row:
                # the item row carries it onto the expense leg, but the payable
                # (Creditors) leg takes its dimension from the parent, and the
                # dimension is mandatory for balance-sheet accounts.
                "fund": self.fund,
                "items": [
                    {
                        "item_name": _("Property Tax"),
                        "description": description,
                        "qty": 1,
                        "rate": flt(self.amount),
                        "expense_account": expense_account,
                        "fund": self.fund,
                        "uom": _default_uom(),
                        "conversion_factor": 1,
                    }
                ],
            }
        )
        invoice.flags.ignore_permissions = True
        # The demand is not stock, and ERPNext should not look for a warehouse.
        invoice.update_stock = 0
        invoice.insert()
        invoice.submit()
        return invoice.name


def _default_uom() -> str:
    """A UOM for the invoice's single charge row.

    A tax demand is not stock and the unit is meaningless, but ERPNext requires
    one on an invoice item. "Nos" is the conventional Frappe fixture and is used
    when present; otherwise the site's stock UOM, or any UOM at all, so this does
    not fail on a site whose setup wizard never ran and which therefore has a
    thinner UOM list than a standard install.
    """
    if frappe.db.exists("UOM", "Nos"):
        return "Nos"

    stock_uom = frappe.db.get_single_value("Stock Settings", "stock_uom")
    if stock_uom and frappe.db.exists("UOM", stock_uom):
        return stock_uom

    any_uom = frappe.db.get_value("UOM", {}, "name")
    if any_uom:
        return any_uom

    frappe.throw(
        _(
            "No Unit of Measure exists on this site, so a property-tax invoice line "
            "cannot be created. Create a UOM such as Nos first."
        ),
        title=_("Setup Incomplete"),
    )


def mark_paid_from_payment(purchase_invoice: str) -> None:
    """Flip the schedule to Paid once its invoice is settled.

    Called from the Purchase Invoice `on_update_after_submit` hook, which is what
    ERPNext fires when an invoice's outstanding amount changes on payment. The
    status is derived from the invoice rather than set by hand, so the register can
    never claim a demand is paid when the ledger says otherwise.
    """
    schedule = frappe.db.get_value(
        "Property Tax Schedule",
        {"purchase_invoice": purchase_invoice, "docstatus": 1},
        ["name", "status"],
        as_dict=True,
    )
    if not schedule:
        return

    outstanding = flt(
        frappe.db.get_value("Purchase Invoice", purchase_invoice, "outstanding_amount")
    )
    status = "Paid" if outstanding <= 0 else "Billed"
    if status != schedule.status:
        frappe.db.set_value(
            "Property Tax Schedule", schedule.name, "status", status,
            update_modified=False,
        )


def on_purchase_invoice_update(doc, method=None) -> None:
    mark_paid_from_payment(doc.name)

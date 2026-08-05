"""Maintenance and AMC records against a property.

Deliberately posts no GL of its own. Maintenance is paid on a vendor's bill, and
that bill is an ordinary ERPNext Purchase Invoice - posting a second entry here
would double-count the expenditure. The `purchase_invoice` link is what keeps the
property's maintenance history and the ledger agreeing, and it is validated
against the property's own company and fund so the link cannot quietly point at
an unrelated bill.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class PropertyMaintenance(Document):
    def validate(self):
        self._validate_dates()
        self._validate_amount()
        self._validate_purchase_invoice()
        self._validate_completion()

    def _validate_dates(self):
        if self.end_date and getdate(self.end_date) < getdate(self.start_date):
            frappe.throw(_("End date cannot be before the start date."))
        if self.maintenance_type == "AMC" and not self.end_date:
            frappe.throw(_("An AMC needs an end date - it is a contract for a period."))

    def _validate_amount(self):
        if flt(self.amount) < 0:
            frappe.throw(_("Amount cannot be negative."))

    def _validate_purchase_invoice(self):
        if not self.purchase_invoice:
            return

        invoice = frappe.db.get_value(
            "Purchase Invoice", self.purchase_invoice,
            ["company", "supplier", "docstatus"], as_dict=True,
        )
        if invoice.company != self.company:
            frappe.throw(
                _("Purchase Invoice {0} belongs to another company.").format(
                    self.purchase_invoice
                )
            )
        if invoice.docstatus == 2:
            frappe.throw(
                _("Purchase Invoice {0} is cancelled.").format(self.purchase_invoice)
            )
        if self.vendor and invoice.supplier != self.vendor:
            frappe.throw(
                _(
                    "Purchase Invoice {0} is from {1}, not from the vendor recorded on "
                    "this maintenance record."
                ).format(self.purchase_invoice, invoice.supplier)
            )

    def _validate_completion(self):
        if self.status == "Completed" and not self.end_date:
            frappe.throw(_("A completed job needs an end date."))

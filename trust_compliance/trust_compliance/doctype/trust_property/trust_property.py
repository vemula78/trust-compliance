"""Donated-property register.

A devotee-donated property has to be tracked for its own sake, not just as a line
in the fixed-asset register: it carries a survey number, a municipality that levies
tax on it, and a maintenance history, and the Trust has to be able to answer "what
does this property cost us and what is it worth" from one screen.

The property belongs to a fund, and that fund is what tax and maintenance on it
post against - tax on a hospital-fund property is the hospital fund's expenditure,
not the general fund's.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class TrustProperty(Document):
    def validate(self):
        self._validate_fund_company()
        self._validate_donor_consistency()
        self._validate_municipality()
        self._validate_valuation()

    def _validate_fund_company(self):
        fund = frappe.db.get_value("Fund", self.fund, ["company", "disabled"], as_dict=True)
        if not fund:
            frappe.throw(_("Fund {0} does not exist.").format(self.fund))
        if fund.company != self.company:
            frappe.throw(
                _("Fund {0} belongs to another company.").format(self.fund)
            )
        if fund.disabled:
            frappe.throw(_("Fund {0} is disabled.").format(self.fund))

    def _validate_donor_consistency(self):
        """A linked donation must belong to the donor and company named here.

        The register is the audit trail for how the Trust came to hold the
        property, so a receipt pointing at a different donor would break exactly
        the link it exists to prove.
        """
        if not self.donation:
            return

        donation = frappe.db.get_value(
            "Trust Donation", self.donation,
            ["donor", "company", "docstatus", "donation_date"], as_dict=True,
        )
        if donation.docstatus != 1:
            frappe.throw(
                _("Donation {0} is not submitted.").format(self.donation)
            )
        if donation.company != self.company:
            frappe.throw(
                _("Donation {0} belongs to another company.").format(self.donation)
            )
        if self.donor and donation.donor != self.donor:
            frappe.throw(
                _(
                    "Donation {0} was received from a different donor than the one "
                    "recorded on this property."
                ).format(self.donation)
            )
        if not self.donor:
            self.donor = donation.donor
        if not self.donation_date:
            self.donation_date = donation.donation_date

    def _validate_municipality(self):
        if not self.municipality:
            return
        if not frappe.db.get_value("Supplier", self.municipality, "is_municipality"):
            frappe.msgprint(
                _(
                    "Supplier {0} is not flagged as a Municipality / Local Body. Flag it "
                    "so property-tax demands are easy to identify in Accounts Payable."
                ).format(self.municipality),
                indicator="orange",
            )

    def _validate_valuation(self):
        if flt(self.valuation) < 0:
            frappe.throw(_("Recorded valuation cannot be negative."))


@frappe.whitelist()
def get_property_summary(property_name: str) -> dict:
    """Tax and maintenance totals for one property, for the register's dashboard.

    Only submitted records count - a draft demand is not yet a liability of the
    Trust, and counting it would overstate what the property costs.
    """
    frappe.get_doc("Trust Property", property_name).check_permission("read")

    tax = frappe.db.sql(
        """
        SELECT COALESCE(SUM(amount), 0) AS total,
               COALESCE(SUM(CASE WHEN status != 'Paid' THEN amount ELSE 0 END), 0) AS outstanding,
               MIN(CASE WHEN status != 'Paid' THEN due_date END) AS next_due
        FROM `tabProperty Tax Schedule`
        WHERE property = %s AND docstatus = 1
        """,
        (property_name,), as_dict=True,
    )[0]

    maintenance = frappe.db.sql(
        """
        SELECT COALESCE(SUM(amount), 0) AS total,
               SUM(CASE WHEN status IN ('Open', 'In Progress') THEN 1 ELSE 0 END) AS open_jobs
        FROM `tabProperty Maintenance`
        WHERE property = %s AND docstatus = 1
        """,
        (property_name,), as_dict=True,
    )[0]

    return {"tax": tax, "maintenance": maintenance}

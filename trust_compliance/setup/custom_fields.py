"""Custom fields this app adds to ERPNext doctypes."""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
    "Account": [
        {
            "fieldname": "trust_compliance_section",
            "fieldtype": "Section Break",
            "label": "Trust Compliance",
            "insert_after": "account_type",
            "collapsible": 1,
        },
        {
            "fieldname": "is_fcra",
            "fieldtype": "Check",
            "label": "FCRA-designated",
            "insert_after": "trust_compliance_section",
            "description": (
                "Foreign contribution only. A journal line posted here must be tagged "
                "to an FCRA fund; a voucher mixing this account with domestic money "
                "cannot be submitted."
            ),
        },
        {
            "fieldname": "is_administrative",
            "fieldtype": "Check",
            "label": "Administrative Expense",
            "insert_after": "is_fcra",
            "depends_on": "eval:doc.root_type=='Expense'",
            "description": (
                "Counts toward the FCRA 20% cap on administrative expenditure, "
                "measured against foreign contribution received in the year."
            ),
        },
    ],
    "Supplier": [
        {
            "fieldname": "is_municipality",
            "fieldtype": "Check",
            "label": "Municipality / Local Body",
            "insert_after": "supplier_group",
            "description": "Property tax is billed to and paid through a municipality supplier.",
        },
    ],
}


def create_trust_custom_fields() -> None:
    create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
    frappe.clear_cache()

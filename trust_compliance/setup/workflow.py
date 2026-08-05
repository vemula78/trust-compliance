"""Optional multi-step approval workflow for Fund Transfer.

Not installed automatically. The built-in control is the permission split -
`Accounts User` drafts, `Accounts Manager` submits - which already means no
transfer happens on one person's authority. A Trust that wants an explicit
Requested -> Approved trail, with the approver recorded on the document and
visible in its timeline, can install this:

    bench --site <site> execute trust_compliance.setup.workflow.create_fund_transfer_workflow

It is opt-in because a Workflow takes over a doctype's submit path entirely, and
imposing one on every install would override whatever approval scheme the Trust
already runs on its other documents.
"""

from __future__ import annotations

import frappe

WORKFLOW_NAME = "Fund Transfer Approval"
STATE_FIELD = "workflow_state"


def create_fund_transfer_workflow() -> str:
    if frappe.db.exists("Workflow", WORKFLOW_NAME):
        return WORKFLOW_NAME

    for state, style in [("Requested", "Warning"), ("Approved", "Success"),
                         ("Rejected", "Danger")]:
        if not frappe.db.exists("Workflow State", state):
            doc = frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state,
                                  "style": style})
            doc.flags.ignore_permissions = True
            doc.insert()

    for action in ["Approve", "Reject"]:
        if not frappe.db.exists("Workflow Action Master", action):
            doc = frappe.get_doc({"doctype": "Workflow Action Master",
                                  "workflow_action_name": action})
            doc.flags.ignore_permissions = True
            doc.insert()

    workflow = frappe.get_doc(
        {
            "doctype": "Workflow",
            "workflow_name": WORKFLOW_NAME,
            "document_type": "Fund Transfer",
            "workflow_state_field": STATE_FIELD,
            "is_active": 1,
            "send_email_alert": 0,
            "states": [
                {
                    "state": "Requested",
                    "doc_status": "0",
                    "allow_edit": "Accounts User",
                    "update_field": None,
                },
                {
                    "state": "Approved",
                    "doc_status": "1",
                    "allow_edit": "Accounts Manager",
                },
                {
                    "state": "Rejected",
                    "doc_status": "0",
                    "allow_edit": "Accounts Manager",
                },
            ],
            "transitions": [
                {
                    "state": "Requested",
                    "action": "Approve",
                    "next_state": "Approved",
                    "allowed": "Accounts Manager",
                    # The requester must not be the approver.
                    "allow_self_approval": 0,
                },
                {
                    "state": "Requested",
                    "action": "Reject",
                    "next_state": "Rejected",
                    "allowed": "Accounts Manager",
                    "allow_self_approval": 0,
                },
            ],
        }
    )
    workflow.flags.ignore_permissions = True
    workflow.insert()
    frappe.db.commit()
    return workflow.name

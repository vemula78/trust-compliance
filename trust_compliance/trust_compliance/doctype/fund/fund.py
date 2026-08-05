"""Fund master.

A Fund is registered as an ERPNext Accounting Dimension by
`trust_compliance.setup.accounting_dimension`, which is what puts a `fund` field
on GL Entry and on every voucher, and makes fund available to ERPNext's own
dimension-wise reporting. This controller only guards the invariants the rest of
the app relies on.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class Fund(Document):
    def validate(self):
        self.fund_code = (self.fund_code or "").strip()
        self._validate_default_fund_is_domestic()
        self._validate_fcra_flag_is_not_flipped_after_postings()

    def on_update(self):
        self._enforce_single_default_per_company()

    def on_trash(self):
        self._block_deletion_when_postings_exist()

    # -- invariants ---------------------------------------------------------

    def _validate_default_fund_is_domestic(self):
        """The default fund absorbs every untagged line, so it must be domestic.

        `validate_fund_segregation` relies on this: an untagged line follows the
        default fund, and if that fund were FCRA an untagged voucher would read as
        foreign contribution. Making the default FCRA would silently invert the
        segregation rule, so it is refused outright.
        """
        if self.is_default and self.is_fcra:
            frappe.throw(
                _(
                    "The default fund absorbs every untagged journal line and must "
                    "therefore be domestic. An FCRA fund cannot be the default."
                ),
                title=_("FCRA Segregation"),
            )

    def _validate_fcra_flag_is_not_flipped_after_postings(self):
        """Flipping is_fcra would reclassify history and every FC-4 already filed."""
        if self.is_new():
            return

        before = self.get_doc_before_save()
        if before is None or bool(before.is_fcra) == bool(self.is_fcra):
            return

        if self._has_postings():
            frappe.throw(
                _(
                    "Fund {0} already carries ledger postings, so its FCRA "
                    "designation cannot be changed - doing so would reclassify "
                    "history and every return already filed from it. Create a "
                    "separate fund and transfer instead."
                ).format(self.name),
                title=_("FCRA Segregation"),
            )

    def _enforce_single_default_per_company(self):
        """Exactly one default per company.

        Postgres/MariaDB cannot express "at most one row with is_default per
        company" as a plain unique index, so it is enforced here: setting a new
        default clears the previous one in the same transaction.
        """
        if not self.is_default:
            return

        others = frappe.get_all(
            "Fund",
            filters={
                "company": self.company,
                "is_default": 1,
                "name": ("!=", self.name),
            },
            pluck="name",
        )
        for other in others:
            frappe.db.set_value("Fund", other, "is_default", 0, update_modified=False)

    def _block_deletion_when_postings_exist(self):
        if self._has_postings():
            frappe.throw(
                _(
                    "Fund {0} carries ledger postings and cannot be deleted. "
                    "Disable it instead, so its history stays reportable."
                ).format(self.name),
                title=_("Cannot Delete"),
            )

    def _has_postings(self) -> bool:
        if not frappe.db.exists("Custom Field", {"dt": "GL Entry", "fieldname": "fund"}):
            return False
        return bool(
            frappe.db.exists("GL Entry", {"fund": self.name, "is_cancelled": 0})
        )


def get_default_fund(company: str) -> str | None:
    """Docname of the company's default fund, or None."""
    return frappe.db.get_value(
        "Fund", {"company": company, "is_default": 1, "disabled": 0}, "name"
    )

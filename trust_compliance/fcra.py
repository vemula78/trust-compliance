"""Frappe adapters for the FCRA segregation rules.

Thin layer: it reads records, hands plain mappings to
`trust_compliance.core.segregation`, and turns the returned strings into
`frappe.throw`. All rule logic lives in the pure core so it stays testable
outside a bench.
"""

from __future__ import annotations

import frappe
from frappe import _

from trust_compliance.core.segregation import validate_fund_segregation

#: Voucher types whose GL entries carry no fund dimension by design and must not
#: be blocked. Period Closing Voucher closes income and expenditure into retained
#: earnings across every fund at once, so it is legitimately "mixed".
EXEMPT_VOUCHER_TYPES = frozenset({"Period Closing Voucher"})


def _fund_master(company: str | None = None) -> list[dict]:
    filters = {"disabled": 0}
    if company:
        filters["company"] = company
    return frappe.get_all(
        "Fund",
        filters=filters,
        fields=["name", "fund_name", "fund_class", "is_default", "is_fcra"],
    )


def _accounts_by_name(account_names: set[str]) -> list[dict]:
    if not account_names:
        return []
    return frappe.get_all(
        "Account",
        filters={"name": ("in", list(account_names))},
        fields=["name", "root_type", "is_fcra", "is_administrative"],
    )


def _throw(errors: list[str]) -> None:
    if not errors:
        return
    frappe.throw(
        "<br>".join(_(error) for error in errors),
        title=_("FCRA Segregation"),
        exc=frappe.ValidationError,
    )


def enforce_on_submitted_voucher(doc, method=None) -> None:
    """Validate segregation against the GL entries this voucher just produced.

    Runs inside the submitting transaction, so raising rolls the voucher back.
    Returns immediately for the vast majority of documents, which produce no GL
    entries at all.
    """
    if doc.doctype in EXEMPT_VOUCHER_TYPES:
        return

    # The dimension only exists once the Accounting Dimension has been created;
    # during install, or if an administrator disables it, there is nothing to check.
    if not _fund_field_exists():
        return

    gl_entries = frappe.get_all(
        "GL Entry",
        filters={
            "voucher_type": doc.doctype,
            "voucher_no": doc.name,
            "is_cancelled": 0,
        },
        fields=["account", "fund", "debit", "credit"],
    )
    if not gl_entries:
        return

    company = getattr(doc, "company", None)
    funds = _fund_master(company)
    if not funds:
        return

    accounts = _accounts_by_name({row["account"] for row in gl_entries if row["account"]})
    lines = [{"fund": row.get("fund"), "account": row.get("account")} for row in gl_entries]

    _throw(validate_fund_segregation(lines, funds, accounts))


def enforce_on_journal_entry_draft(doc, method=None) -> None:
    """Pre-submit check on a Journal Entry's own rows, for early feedback.

    Same rules as `enforce_on_submitted_voucher`; this one exists so a manual
    journal reports the problem while it is still a draft rather than only when
    the accountant tries to submit it.
    """
    if not _fund_field_exists():
        return

    rows = doc.get("accounts") or []
    if not rows:
        return

    funds = _fund_master(getattr(doc, "company", None))
    if not funds:
        return

    accounts = _accounts_by_name({row.account for row in rows if row.get("account")})
    lines = [
        {"fund": row.get("fund"), "account": row.get("account")} for row in rows
    ]

    _throw(validate_fund_segregation(lines, funds, accounts))


def validate_account_flags(doc, method=None) -> None:
    """Guard the two custom flags this app adds to Account.

    An FCRA-designated account must not also be usable for domestic money, and
    the flag must not be flipped once the account carries postings - doing so
    would silently reclassify history and change every FC-4 already filed.
    """
    if not doc.get("is_fcra") and not doc.get("is_administrative"):
        return

    if doc.is_new():
        return

    before = doc.get_doc_before_save()
    if before is None:
        return

    if bool(before.get("is_fcra")) != bool(doc.get("is_fcra")):
        has_postings = frappe.db.exists(
            "GL Entry", {"account": doc.name, "is_cancelled": 0}
        )
        if has_postings:
            frappe.throw(
                _(
                    "Account {0} already carries ledger postings, so its FCRA "
                    "designation cannot be changed. Create a separate account instead."
                ).format(doc.name),
                title=_("FCRA Segregation"),
            )


def _fund_field_exists() -> bool:
    """True once the Fund accounting dimension has created its GL Entry field."""
    return bool(
        frappe.db.exists(
            "Custom Field", {"dt": "GL Entry", "fieldname": "fund"}
        )
    )

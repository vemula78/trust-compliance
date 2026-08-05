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
from trust_compliance.setup.accounting_dimension import fund_field_exists

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

    funds = _fund_master(getattr(doc, "company", None))
    if not funds:
        # No fund master yet, so there is no FCRA wall to protect. This is the
        # only condition under which enforcement legitimately does nothing.
        return

    _require_fund_dimension()

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

    accounts = _accounts_by_name({row["account"] for row in gl_entries if row["account"]})
    lines = [{"fund": row.get("fund"), "account": row.get("account")} for row in gl_entries]

    _throw(validate_fund_segregation(lines, funds, accounts))


def enforce_on_journal_entry_draft(doc, method=None) -> None:
    """Pre-submit check on a Journal Entry's own rows, for early feedback.

    Same rules as `enforce_on_submitted_voucher`; this one exists so a manual
    journal reports the problem while it is still a draft rather than only when
    the accountant tries to submit it.
    """
    rows = doc.get("accounts") or []
    if not rows:
        return

    funds = _fund_master(getattr(doc, "company", None))
    if not funds:
        return

    _require_fund_dimension()

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


def _require_fund_dimension() -> None:
    """Fail closed when the fund dimension is missing but funds are configured.

    ERPNext materialises a dimension's fields through a background job. If that
    job never ran - a down worker on a fresh install - GL Entry has no `fund`
    column, every line reads as untagged, and segregation would appear to pass on
    a voucher that actually mixes foreign and domestic money.

    Silently skipping the check in that state is the worst available behaviour,
    because the accounts team is told the wall is enforced when it is not. So
    posting is refused instead, with the one-line remediation.
    """
    if fund_field_exists():
        return

    frappe.throw(
        _(
            "The Fund accounting dimension has not been applied to GL Entry, so "
            "FCRA segregation cannot be verified and posting is blocked. Run "
            "<code>bench --site &lt;site&gt; execute "
            "trust_compliance.setup.accounting_dimension.ensure_dimension_fields</code> "
            "to finish the setup."
        ),
        title=_("FCRA Segregation Unavailable"),
    )

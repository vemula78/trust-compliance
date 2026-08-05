"""Install and uninstall hooks."""

from __future__ import annotations

import frappe

from trust_compliance.setup.accounting_dimension import create_fund_dimension
from trust_compliance.setup.custom_fields import create_trust_custom_fields


def after_install() -> None:
    create_trust_custom_fields()
    create_fund_dimension()
    _ensure_settings_singleton()
    frappe.db.commit()


def before_uninstall() -> None:
    """Leave the ledger alone.

    The Fund accounting dimension and its `fund` columns are deliberately not
    removed: dropping them would strip the fund attribution off every historical
    GL entry, which is the Trust's statutory record. Uninstalling removes the
    app's own doctypes; the dimension must be disabled by hand if that is really
    wanted.
    """
    frappe.msgprint(
        "The Fund accounting dimension has been left in place so historical GL "
        "entries keep their fund attribution. Disable it manually if required.",
        title="Trust Compliance",
    )


def _ensure_settings_singleton() -> None:
    settings = frappe.get_single("Trust Compliance Settings")
    settings.flags.ignore_permissions = True
    settings.flags.ignore_mandatory = True
    settings.save()


def seed_trust_funds(company: str) -> list[str]:
    """Create the fund master a charitable Trust starts with.

    Idempotent, and safe to call on an existing company. The General Fund is the
    default and is domestic - `validate_fund_segregation` depends on the default
    fund being domestic, so an untagged line can never read as foreign
    contribution.

    Called on demand rather than at install: fund codes are the Trust's choice,
    and creating them before the accounts team has approved the structure would
    put the wrong codes on real postings.
    """
    seeds = [
        {"fund_code": "GEN", "fund_name": "General Fund", "fund_class": "Unrestricted",
         "is_default": 1, "is_fcra": 0,
         "description": "Unrestricted domestic donations, available for any object of the Trust."},
        {"fund_code": "CORPUS", "fund_name": "Corpus Fund", "fund_class": "Corpus",
         "is_default": 0, "is_fcra": 0,
         "description": "Section 11(1)(d) corpus. Capital of the Trust; not spendable and cannot be transferred out."},
        {"fund_code": "HOSP", "fund_name": "Hospital Fund", "fund_class": "Restricted",
         "is_default": 0, "is_fcra": 0,
         "description": "Donor-restricted to the free tertiary hospitals."},
        {"fund_code": "EDU", "fund_name": "Education Fund", "fund_class": "Restricted",
         "is_default": 0, "is_fcra": 0,
         "description": "Donor-restricted to free education, KG to PG."},
        {"fund_code": "FCRA-GEN", "fund_name": "FCRA General Fund",
         "fund_class": "Unrestricted", "is_default": 0, "is_fcra": 1,
         "description": "Foreign contribution received under FCRA. Cannot mix with domestic money."},
    ]

    created = []
    for seed in seeds:
        if frappe.db.exists("Fund", seed["fund_code"]):
            continue
        fund = frappe.get_doc({"doctype": "Fund", "company": company, **seed})
        fund.flags.ignore_permissions = True
        fund.insert()
        created.append(fund.name)

    return created

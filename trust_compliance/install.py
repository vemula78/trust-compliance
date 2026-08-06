"""Install and uninstall hooks."""

from __future__ import annotations

import frappe

from trust_compliance.setup.accounting_dimension import create_fund_dimension
from trust_compliance.setup.custom_fields import create_trust_custom_fields
from trust_compliance.trust_compliance.doctype.investment_mode.investment_mode import (
    create_default_investment_modes,
)


def after_install() -> None:
    create_trust_custom_fields()
    create_fund_dimension()
    # The permitted-mode master is seeded on install, unlike the fund master:
    # section 11(5) is statute and identical for every trust, whereas fund codes
    # are the Trust's own choice.
    create_default_investment_modes()
    _ensure_settings_singleton()
    _adopt_indian_number_format()
    frappe.db.commit()


#: Frappe's own out-of-the-box default. Only this value is replaced - anything
#: else is a choice somebody made, and is left alone.
FRAMEWORK_DEFAULT_NUMBER_FORMAT = "#,###.##"
INDIAN_NUMBER_FORMAT = "#,##,###.##"


def _adopt_indian_number_format() -> None:
    """Set Indian lakh/crore numbering, but only if nothing has been chosen.

    This app exists solely for Indian statutory compliance, and Frappe derives
    Indian grouping *and* Indian amount-in-words from the site's number format.
    Left on the framework default, a fresh install prints "Rupees Five Hundred And
    Sixty Thousand only" and Rs 560,000.00 on an 80G receipt where the law expects
    "Rupees Five Lakh, Sixty Thousand only" and Rs 5,60,000.00 - and on a receipt
    the amount in words is the operative figure, read by the donor and by an
    assessing officer.

    Relying on the administrator to read an install step was tested and found
    wanting: a clean-install rehearsal produced a working system that quietly
    issued wrong receipts. So the default is completed here.

    It is narrow on purpose. Only Frappe's untouched default is replaced; any other
    value means somebody chose it, and a site-global setting is theirs, not ours.
    The document is saved rather than the field written directly, because the
    formatting layer reads the DefaultValue table that only `save()` propagates to.
    """
    current = frappe.db.get_single_value("System Settings", "number_format")
    if current and current != FRAMEWORK_DEFAULT_NUMBER_FORMAT:
        return

    settings = frappe.get_single("System Settings")
    settings.number_format = INDIAN_NUMBER_FORMAT
    settings.flags.ignore_permissions = True
    settings.flags.ignore_mandatory = True
    settings.save()

    frappe.msgprint(
        frappe._(
            "Number format set to {0} for Indian lakh/crore grouping and "
            "amount-in-words, which 80G receipts depend on. Change it in System "
            "Settings if that is not wanted."
        ).format(INDIAN_NUMBER_FORMAT),
        title=frappe._("Trust Compliance"),
    )


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

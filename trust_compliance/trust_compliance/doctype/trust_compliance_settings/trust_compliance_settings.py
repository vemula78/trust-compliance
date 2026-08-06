"""Trust Compliance Settings: the accounts the Trust module posts to, per company.

Accounts are configured, never derived. The Next.js ERP resolved them by hard
coded chart-of-accounts codes ("1001" is the FCRA bank); that cannot work on
ERPNext, where account names are company-suffixed and the chart is the user's.
Requiring explicit configuration also means a misconfiguration fails loudly at
setup rather than silently posting a donation to the wrong account.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

REQUIRED_ROOT_TYPES = {
    "donation_income_account": "Income",
    "corpus_fund_account": "Equity",
    "inter_fund_transfer_account": "Equity",
    "cash_account": "Asset",
    "bank_account": "Asset",
    "fcra_bank_account": "Asset",
    "property_tax_expense_account": "Expense",
    "investment_income_account": "Income",
    "tds_receivable_account": "Asset",
}


#: Frappe switches to Indian lakh/crore grouping - and to Indian wording in
#: `money_in_words` - only when the site's number format is this one.
INDIAN_NUMBER_FORMAT = "#,##,###.##"


class TrustComplianceSettings(Document):
    def validate(self):
        self._warn_if_not_indian_number_format()
        seen: set[str] = set()
        for row in self.company_accounts:
            if row.company in seen:
                frappe.throw(
                    _("Company {0} appears twice in Company Accounts.").format(row.company)
                )
            seen.add(row.company)
            self._validate_row(row)

    def _warn_if_not_indian_number_format(self):
        """Warn - loudly, but do not silently change a global setting.

        Frappe uses Indian lakh/crore grouping and Indian wording in
        `money_in_words` only when the effective number format is #,##,###.##.
        With any other format an 80G receipt prints "Rupees Five Hundred And
        Sixty Thousand only" and Rs 560,000.00 where an Indian statutory receipt
        must read "Rupees Five Lakh, Sixty Thousand only" and Rs 5,60,000.00.

        The amount in words is the operative figure on the receipt, so this is a
        real defect in the document, not a cosmetic preference. It is a
        site-global setting owned by the administrator, so it is flagged here -
        where they are already configuring this app - rather than overwritten.

        On Frappe 16 the format is locale-resolved: the Language record wins over
        the System Settings default. The effective value is read here rather than
        System Settings, because a site can have Indian settings and still print
        non-Indian amounts if its Language record says otherwise.
        """
        current = frappe.locale.get_number_format().string
        if current == INDIAN_NUMBER_FORMAT:
            return

        frappe.msgprint(
            _(
                "The site number format is <b>{0}</b>. Indian lakh/crore grouping and "
                "Indian amount-in-words need <b>{1}</b>: until it is changed, 80G "
                "receipts will print \"Five Hundred And Sixty Thousand\" instead of "
                "\"Five Lakh, Sixty Thousand\". Set it in System Settings, and clear "
                "the Number Format on the active Language record - on Frappe 16 the "
                "Language record overrides the system default."
            ).format(current, INDIAN_NUMBER_FORMAT),
            title=_("Number format is not Indian"),
            indicator="orange",
        )

    def _validate_row(self, row):
        for fieldname, expected_root in REQUIRED_ROOT_TYPES.items():
            account = row.get(fieldname)
            if not account:
                continue

            details = frappe.db.get_value(
                "Account",
                account,
                ["company", "root_type", "is_group", "is_fcra"],
                as_dict=True,
            )
            label = _(self.meta.get_field("company_accounts").options)

            if details.company != row.company:
                frappe.throw(
                    _("Account {0} belongs to {1}, not to {2}.").format(
                        account, details.company, row.company
                    )
                )
            if details.is_group:
                frappe.throw(
                    _("Account {0} is a group account and cannot be posted to.").format(account)
                )
            if details.root_type != expected_root:
                frappe.throw(
                    _(
                        "Account {0} is a {1} account, but {2} must be {3}. "
                        "Corpus is capital of the Trust, not income of the year, so it "
                        "belongs in Equity; posting it to Income would overstate the "
                        "year's income and distort the 85% application test."
                    ).format(
                        account,
                        details.root_type,
                        _(fieldname.replace("_", " ").title()),
                        _(expected_root),
                    )
                )

            if fieldname == "fcra_bank_account" and not details.is_fcra:
                frappe.throw(
                    _(
                        "Account {0} is set as the FCRA-designated bank account but is "
                        "not flagged FCRA on the Account record. Set the flag first, so "
                        "segregation can be enforced against it."
                    ).format(account),
                    title=_("FCRA Segregation"),
                )

            if fieldname != "fcra_bank_account" and details.is_fcra:
                frappe.throw(
                    _(
                        "Account {0} is FCRA-designated and cannot be used as {1}; "
                        "foreign and domestic money must stay in separate accounts."
                    ).format(account, _(fieldname.replace("_", " ").title())),
                    title=_("FCRA Segregation"),
                )


def get_company_accounts(company: str) -> dict:
    """Configured accounts for a company, or a clear error naming what is missing."""
    settings = frappe.get_cached_doc("Trust Compliance Settings")
    for row in settings.company_accounts:
        if row.company == company:
            return row.as_dict()

    frappe.throw(
        _(
            "No Trust Compliance account setup for company {0}. Add a row in "
            "Trust Compliance Settings before receipting donations for it."
        ).format(company),
        title=_("Setup Incomplete"),
    )

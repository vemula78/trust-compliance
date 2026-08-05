app_name = "trust_compliance"
app_title = "Trust Compliance"
app_publisher = "Praveen Vemula"
app_description = (
    "Fund accounting, 80G donation receipting, FCRA segregation and donated-property "
    "management for Indian charitable trusts registered under 12A/12AB, built on ERPNext."
)
app_email = "vemula78@gmail.com"
app_license = "mit"
required_apps = ["erpnext"]

after_install = "trust_compliance.install.after_install"
before_uninstall = "trust_compliance.install.before_uninstall"

# ---------------------------------------------------------------------------
# FCRA segregation enforcement
#
# The rule is enforced on the GL Entries a voucher actually produced rather than
# on each voucher type's own line structure. ERPNext writes GL entries during
# `on_submit`, and app-level `on_submit` hooks run after the document's own, in
# the same database transaction - so by the time this handler runs the entries
# exist and are readable, and a `frappe.throw` rolls the whole submission back.
#
# Doing it here rather than per-doctype matters: it sees the complete, final,
# post-tax GL effect of *any* voucher - Journal Entry, Payment Entry, Purchase
# Invoice, Expense Claim, Payroll Entry, asset depreciation, and anything a
# future ERPNext version or third-party app introduces - so there is no voucher
# type through which foreign and domestic money can be mixed. The wildcard is
# cheap: `on_submit` only fires for submittable doctypes, and the handler returns
# after one indexed lookup when the voucher produced no GL entries.
#
# `Journal Entry.validate` additionally runs the same check pre-submit so a
# manual journal fails with a field-level message while it is still a draft,
# instead of only at submission.
# ---------------------------------------------------------------------------
doc_events = {
    "*": {
        "on_submit": "trust_compliance.fcra.enforce_on_submitted_voucher",
    },
    "Journal Entry": {
        "validate": "trust_compliance.fcra.enforce_on_journal_entry_draft",
    },
    "Account": {
        "validate": "trust_compliance.fcra.validate_account_flags",
    },
}

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["name", "in", [
            "Account-trust_compliance_section",
            "Account-is_fcra",
            "Account-is_administrative",
            "Supplier-is_municipality",
        ]]],
    },
]

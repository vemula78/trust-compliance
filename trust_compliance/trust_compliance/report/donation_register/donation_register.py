"""Donation Register with Section 115BBC anonymous-donation monitoring."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import fmt_money

from trust_compliance import queries
from trust_compliance.core.compliance import build_donation_register


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    queries.require_company_read_permission(company)
    from_date, to_date = queries.window_for(filters)

    donations = queries.donations(company, from_date, to_date)
    if filters.get("fund"):
        donations = [row for row in donations if row.get("fund") == filters["fund"]]
    if filters.get("mode"):
        donations = [row for row in donations if row.get("mode") == filters["mode"]]

    # Filtered before building the summary, not after: the summary (and Section
    # 115BBC anonymous-donation exposure) must describe the same donations the
    # table and chart show, or a Fund/Mode filter makes the narrative contradict
    # the rows beneath it.
    report = build_donation_register(
        donations,
        from_date=from_date,
        to_date=to_date,
        anonymous_threshold=frappe.db.get_single_value(
            "Trust Compliance Settings", "anonymous_donation_threshold"
        ),
    )

    rows = report["rows"]

    data = [
        {
            "donation": row.get("name"),
            "receipt_no": row.get("receipt_no"),
            "donation_date": row.get("donation_date"),
            "donor": row.get("donor"),
            "donor_name": _("Anonymous") if row.get("is_anonymous") else row.get("donor_name"),
            "donor_type": row.get("donor_type"),
            "pan": row.get("donor_pan"),
            "fund": row.get("fund"),
            "mode": row.get("mode"),
            "purpose": row.get("purpose"),
            "amount": row.get("amount"),
            "kind": _("Corpus") if row.get("is_corpus") else _("Income"),
        }
        for row in rows
    ]

    # Frappe's contract is (columns, data, message, chart, report_summary).
    # The chart must sit in position 4; putting it in position 5 makes the desk
    # try to iterate it as a report-summary list and the report renders blank.
    return _columns(), data, _message(report["summary"], company), _chart(rows)


def _message(summary: dict, company: str) -> str:
    currency = frappe.get_cached_value("Company", company, "default_currency")

    def money(value):
        return fmt_money(value, currency=currency)

    lines = [
        _("{0} receipts totalling {1} - {2} income and {3} corpus.").format(
            summary["count"], money(summary["total"]), money(summary["income"]),
            money(summary["corpus"]),
        ),
        _(
            "Section 115BBC: anonymous donations {0}, exempt limit {1} (the higher of "
            "the statutory floor and 5% of total donations)."
        ).format(money(summary["anonymous"]), money(summary["anonymous_exempt_limit"])),
    ]

    if summary["anonymous_threshold_breached"]:
        lines.append(
            "<b>"
            + _(
                "{0} of anonymous donations is taxable at the maximum marginal rate "
                "under Section 115BBC."
            ).format(money(summary["anonymous_taxable"]))
            + "</b>"
        )
    else:
        lines.append(_("Anonymous donations are within the exempt limit."))

    return "<br>".join(lines)


def _chart(rows: list[dict]) -> dict:
    by_fund: dict[str, float] = {}
    for row in rows:
        fund = row.get("fund") or _("Untagged")
        by_fund[fund] = by_fund.get(fund, 0) + (row.get("amount") or 0)

    labels = sorted(by_fund)
    return {
        "data": {
            "labels": labels,
            "datasets": [{"name": _("Donations"), "values": [by_fund[key] for key in labels]}],
        },
        "type": "bar",
    }


def _columns() -> list[dict]:
    """Amount early, long free-text last, for the same reason as the FCRA register:
    a twelve-column register must not push its money off the right edge."""
    return [
        {"fieldname": "receipt_no", "label": _("Receipt No"), "fieldtype": "Data",
         "width": 145},
        {"fieldname": "donation_date", "label": _("Date"), "fieldtype": "Date",
         "width": 95},
        {"fieldname": "donor_name", "label": _("Donor Name"), "fieldtype": "Data",
         "width": 175},
        {"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency",
         "options": "Company:company:default_currency", "width": 130},
        {"fieldname": "fund", "label": _("Fund"), "fieldtype": "Link", "options": "Fund",
         "width": 100},
        {"fieldname": "mode", "label": _("Mode"), "fieldtype": "Data", "width": 85},
        {"fieldname": "kind", "label": _("Nature"), "fieldtype": "Data", "width": 85},
        {"fieldname": "pan", "label": _("PAN"), "fieldtype": "Data", "width": 110},
        {"fieldname": "donor_type", "label": _("Type"), "fieldtype": "Data", "width": 95},
        {"fieldname": "purpose", "label": _("Purpose"), "fieldtype": "Data", "width": 200},
        {"fieldname": "donor", "label": _("Donor"), "fieldtype": "Link",
         "options": "Trust Donor", "width": 120},
        {"fieldname": "donation", "label": _("Donation"), "fieldtype": "Link",
         "options": "Trust Donation", "width": 125},
    ]

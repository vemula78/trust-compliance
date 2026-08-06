"""Property Register: every donated property with its tax and maintenance history.

One row per property, answering the question the Trust actually has to answer -
what do we hold, whose fund holds it, what is outstanding on it, and when is the
next payment due. The tax and maintenance figures are aggregated from submitted
records only: a draft demand is not yet a liability and counting it would overstate
what the property costs.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, fmt_money, getdate, nowdate


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]

    conditions = ["p.company = %(company)s"]
    params: dict = {"company": company}
    if filters.get("fund"):
        conditions.append("p.fund = %(fund)s")
        params["fund"] = filters["fund"]
    if filters.get("status"):
        conditions.append("p.status = %(status)s")
        params["status"] = filters["status"]

    rows = frappe.db.sql(
        f"""
        SELECT p.name AS property_id, p.property_name, p.property_type, p.status, p.fund,
               p.survey_number, p.municipality, p.extent, p.extent_uom,
               p.valuation, p.guideline_value, p.donor, p.donation_date,
               COALESCE(tax.total, 0)        AS tax_paid_or_billed,
               COALESCE(tax.outstanding, 0)  AS tax_outstanding,
               tax.next_due                  AS next_due,
               COALESCE(mnt.total, 0)        AS maintenance_total,
               COALESCE(mnt.open_jobs, 0)    AS open_jobs
        FROM `tabTrust Property` p
        LEFT JOIN (
            -- Outstanding is read from the invoice, not from the schedule's own
            -- status field. The status is a convenience for list filtering; the
            -- ledger is the truth, so the register stays correct even if a status
            -- refresh is ever missed.
            SELECT pts.property,
                   SUM(pts.amount) AS total,
                   SUM(COALESCE(pi.outstanding_amount, pts.amount)) AS outstanding,
                   MIN(CASE WHEN COALESCE(pi.outstanding_amount, pts.amount) > 0
                            THEN pts.due_date END) AS next_due
            FROM `tabProperty Tax Schedule` pts
            LEFT JOIN `tabPurchase Invoice` pi
                   ON pi.name = pts.purchase_invoice AND pi.docstatus = 1
            WHERE pts.docstatus = 1
            GROUP BY pts.property
        ) tax ON tax.property = p.name
        LEFT JOIN (
            SELECT property,
                   SUM(amount) AS total,
                   SUM(CASE WHEN status IN ('Open', 'In Progress') THEN 1 ELSE 0 END) AS open_jobs
            FROM `tabProperty Maintenance`
            WHERE docstatus = 1
            GROUP BY property
        ) mnt ON mnt.property = p.name
        WHERE {" AND ".join(conditions)}
        ORDER BY p.property_name
        """,
        params,
        as_dict=True,
    )

    if filters.get("only_tax_due"):
        rows = [row for row in rows if flt(row.tax_outstanding) > 0]

    data = [dict(row) for row in rows]
    if data:
        data.append({})
        data.append(
            {
                "property_name": _("Total"),
                "valuation": sum(flt(row["valuation"]) for row in rows),
                "tax_paid_or_billed": sum(flt(row["tax_paid_or_billed"]) for row in rows),
                "tax_outstanding": sum(flt(row["tax_outstanding"]) for row in rows),
                "maintenance_total": sum(flt(row["maintenance_total"]) for row in rows),
                "bold": 1,
            }
        )

    return _columns(), data, _message(rows, company)


def _message(rows: list[dict], company: str) -> str:
    if not rows:
        return _("No properties recorded for this company yet.")

    currency = frappe.get_cached_value("Company", company, "default_currency")
    today = getdate(nowdate())

    overdue = [
        row for row in rows
        if flt(row["tax_outstanding"]) > 0 and row["next_due"]
        and getdate(row["next_due"]) < today
    ]
    due_soon = [
        row for row in rows
        if flt(row["tax_outstanding"]) > 0 and row["next_due"]
        and today <= getdate(row["next_due"])
    ]

    lines = [
        _("{0} properties, recorded value {1}.").format(
            len(rows), fmt_money(sum(flt(row["valuation"]) for row in rows), currency=currency)
        )
    ]

    if overdue:
        lines.append(
            "<b style='color:var(--red-600)'>"
            + _("{0} property tax demand(s) are past their due date, totalling {1}.").format(
                len(overdue),
                fmt_money(sum(flt(row["tax_outstanding"]) for row in overdue), currency=currency),
            )
            + "</b>"
        )
    if due_soon:
        lines.append(
            _("{0} demand(s) outstanding but not yet due, totalling {1}.").format(
                len(due_soon),
                fmt_money(sum(flt(row["tax_outstanding"]) for row in due_soon), currency=currency),
            )
        )
    if not overdue and not due_soon:
        lines.append(_("No property tax is outstanding."))

    missing_municipality = [row for row in rows if not row["municipality"]]
    if missing_municipality:
        lines.append(
            _(
                "{0} property(ies) have no municipality recorded, so no tax demand can be "
                "raised against them - and none will appear as due here even if one is."
            ).format(len(missing_municipality))
        )

    return "<br>".join(lines)


def _columns() -> list[dict]:
    currency_options = "Company:company:default_currency"
    return [
        # Deliberately not called "name": frappe's DataTable reserves that key on
        # a row object, and a column using it renders an empty grid.
        {"fieldname": "property_id", "label": _("ID"), "fieldtype": "Link",
         "options": "Trust Property", "width": 110},
        {"fieldname": "property_name", "label": _("Property"), "fieldtype": "Data",
         "width": 200},
        {"fieldname": "fund", "label": _("Fund"), "fieldtype": "Link", "options": "Fund",
         "width": 100},
        {"fieldname": "valuation", "label": _("Recorded Value"), "fieldtype": "Currency",
         "options": currency_options, "width": 140},
        {"fieldname": "tax_outstanding", "label": _("Tax Due"), "fieldtype": "Currency",
         "options": currency_options, "width": 120},
        {"fieldname": "next_due", "label": _("Next Due"), "fieldtype": "Date", "width": 100},
        {"fieldname": "tax_paid_or_billed", "label": _("Tax Billed"), "fieldtype": "Currency",
         "options": currency_options, "width": 120},
        {"fieldname": "maintenance_total", "label": _("Maintenance"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "open_jobs", "label": _("Open Jobs"), "fieldtype": "Int", "width": 90},
        {"fieldname": "property_type", "label": _("Type"), "fieldtype": "Data", "width": 110},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
        {"fieldname": "survey_number", "label": _("Survey No"), "fieldtype": "Data",
         "width": 120},
        {"fieldname": "municipality", "label": _("Municipality"), "fieldtype": "Link",
         "options": "Supplier", "width": 150},
        {"fieldname": "extent", "label": _("Extent"), "fieldtype": "Float", "width": 90},
        {"fieldname": "extent_uom", "label": _("UOM"), "fieldtype": "Data", "width": 80},
        {"fieldname": "donor", "label": _("Donated By"), "fieldtype": "Link",
         "options": "Trust Donor", "width": 130},
    ]

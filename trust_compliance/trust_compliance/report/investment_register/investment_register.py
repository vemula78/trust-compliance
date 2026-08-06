"""Investment Register with a live section 11(5) compliance check.

The register is the schedule an auditor asks for: what the Trust holds, under
which permitted mode, funded from which fund, at what book value, and what income
it produced. Compliance is re-evaluated here rather than trusted from the purchase
- an auto-rollover, a change in Rule 17C, or a mode later disabled can all make an
instrument that was compliant when bought non-compliant today, and section
115BBI taxes the income of a non-compliant investment at 30%. A register that
only showed the status recorded at purchase would hide exactly that.

Book value is cost less redemptions. Trusts carry investments at cost, not fair
value, so no revaluation is applied.

Two standing rules that the figures here depend on, recorded once rather than
repeated in the on-screen message: interest and dividend are income of the year
and never corpus, so they are included in the 85% application test; and TDS is a
recoverable asset, not application of income. The message carries findings only -
an explanation printed on every run stops being read, and a long message also
squeezes the table itself off the screen.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from trust_compliance import queries
from trust_compliance.core.investment import build_investment_register
from trust_compliance.trust_compliance.doctype.trust_investment.trust_investment import (
    get_prohibited_parties,
)


def execute(filters: dict | None = None):
    filters = filters or {}
    company = filters["company"]
    as_on = filters.get("as_on")

    # `frappe.get_all` does not apply permissions, so a user restricted to one
    # company could otherwise read another's investments by typing its name into
    # the filter. The company is checked explicitly before any read happens.
    if not frappe.has_permission("Trust Investment", "report"):
        frappe.throw(_("Not permitted to read investments."), frappe.PermissionError)
    frappe.get_doc("Company", company).check_permission("read")

    report = build_investment_register(
        queries.investments(company),
        queries.investment_transactions(company),
        queries.funds(company),
        as_on=as_on,
        # Read here as well as at purchase: a person becomes an interested person
        # under section 13(3) by being appointed a trustee or by crossing the
        # substantial-contribution threshold, neither of which posts a
        # transaction. Income from an instrument that was clean when bought is
        # tainted from that day, and this register is where it has to show.
        prohibited_parties=get_prohibited_parties(company),
        modes=queries.investment_modes(),
    )

    rows = report["rows"]
    if filters.get("fund"):
        rows = [row for row in rows if row["fund"] == filters["fund"]]
    if filters.get("only_non_compliant"):
        rows = [row for row in rows if not row["is_compliant"]]

    data = [
        {
            "investment": row["investment"],
            "fund": row["fund"],
            "source": _("FCRA") if row["is_fcra"] else _("Domestic"),
            "mode_clause": row["mode_clause"],
            "mode_label": row["mode_label"],
            "instrument_type": row["instrument_type"],
            "issuer": row["issuer"],
            "cost": row["cost"],
            "redeemed": row["redeemed"],
            "book_value": row["book_value"],
            "income_earned": row["income_earned"],
            "tds": row["tds"],
            "compliance": _("Permitted") if row["is_compliant"] else _("Outside 11(5)"),
            "violations": "; ".join(row["violations"]) or None,
        }
        for row in rows
    ]

    if data:
        data.append({})
        data.append(
            {
                "mode_label": _("Total"),
                "cost": sum(flt(row["cost"]) for row in rows),
                "redeemed": sum(flt(row["redeemed"]) for row in rows),
                "book_value": sum(flt(row["book_value"]) for row in rows),
                "income_earned": sum(flt(row["income_earned"]) for row in rows),
                "tds": sum(flt(row["tds"]) for row in rows),
                "bold": 1,
            }
        )

    # (columns, data, message, chart) - the chart must not land in the
    # report_summary slot, which the desk iterates as a list.
    # Totals, warnings and chart are computed from the *visible* rows. Leaving
    # them company-wide made the narrative contradict the schedule beneath it
    # whenever a fund or compliance filter was applied.
    return _columns(), data, _message(rows, company), _chart(rows)


def _message(rows: list[dict], company: str) -> str:
    if not rows:
        return _("No submitted investments for this company yet.")

    currency = frappe.get_cached_value("Company", company, "default_currency")

    def money(value):
        return fmt_money(value, currency=currency)

    lines = [
        _("{0} instruments, book value {1}, income {2} (TDS {3}).").format(
            len(rows),
            money(sum(flt(row["book_value"]) for row in rows)),
            money(sum(flt(row["income_earned"]) for row in rows)),
            money(sum(flt(row["tds"]) for row in rows)),
        )
    ]

    non_compliant = sum(
        flt(row["book_value"]) for row in rows if not row["is_compliant"]
    )
    if non_compliant:
        lines.append(
            "<b style='color:var(--red-600)'>"
            + _(
                "{0} is held outside the forms and modes permitted by section 11(5). "
                "Income from it is specified income taxable at 30% under section "
                "115BBI, and repeated breach puts the 12AB registration at risk."
            ).format(money(non_compliant))
            + "</b>"
        )
    else:
        lines.append(_("Every instrument is within a permitted section 11(5) mode."))

    corpus_value = sum(
        flt(row["book_value"]) for row in rows if row["fund_class"] == "Corpus"
    )
    if corpus_value:
        lines.append(
            _("Of which corpus: {0}, all of which must stay in an 11(5) mode.").format(
                money(corpus_value)
            )
        )

    unverified = sum(
        flt(row["book_value"]) for row in rows if not row.get("citation_verified")
    )
    if unverified:
        lines.append(
            _(
                "{0} sits under a Rule 17C clause whose citation is unverified - confirm "
                "it before quoting it on an audit schedule, then tick Citation Verified."
            ).format(money(unverified))
        )

    return "<br>".join(lines)


def _chart(rows: list[dict]) -> dict:
    by_mode: dict[str, float] = {}
    for row in rows:
        key = row["mode_label"] or row["mode_clause"] or _("Unmapped")
        by_mode[key] = by_mode.get(key, 0.0) + flt(row["book_value"])
    labels = sorted(by_mode)
    values = [by_mode[label] for label in labels]
    return {
        "data": {"labels": labels,
                 "datasets": [{"name": _("Book Value"), "values": values}]},
        "type": "bar",
    }


def _columns() -> list[dict]:
    currency_options = "Company:company:default_currency"
    return [
        {"fieldname": "investment", "label": _("Investment"), "fieldtype": "Link",
         "options": "Trust Investment", "width": 130},
        {"fieldname": "mode_label", "label": _("Permitted Mode"), "fieldtype": "Data",
         "width": 200},
        {"fieldname": "mode_clause", "label": _("Clause"), "fieldtype": "Data",
         "width": 100},
        {"fieldname": "book_value", "label": _("Book Value"), "fieldtype": "Currency",
         "options": currency_options, "width": 130},
        {"fieldname": "income_earned", "label": _("Income"), "fieldtype": "Currency",
         "options": currency_options, "width": 120},
        {"fieldname": "tds", "label": _("TDS"), "fieldtype": "Currency",
         "options": currency_options, "width": 100},
        {"fieldname": "compliance", "label": _("11(5)"), "fieldtype": "Data",
         "width": 110},
        {"fieldname": "fund", "label": _("Fund"), "fieldtype": "Link", "options": "Fund",
         "width": 100},
        {"fieldname": "source", "label": _("Source"), "fieldtype": "Data", "width": 90},
        {"fieldname": "instrument_type", "label": _("Instrument"), "fieldtype": "Data",
         "width": 150},
        {"fieldname": "issuer", "label": _("Issuer"), "fieldtype": "Data", "width": 170},
        {"fieldname": "cost", "label": _("Cost"), "fieldtype": "Currency",
         "options": currency_options, "width": 120},
        {"fieldname": "redeemed", "label": _("Redeemed"), "fieldtype": "Currency",
         "options": currency_options, "width": 120},
        {"fieldname": "violations", "label": _("Violation"), "fieldtype": "Data",
         "width": 300},
    ]

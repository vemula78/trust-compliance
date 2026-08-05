"""Form 10BE certificate of donation.

Form 10BE is issued per donor per financial year, not per receipt, so it cannot
be an ordinary print format on Trust Donation. It is rendered here from the same
`build_form_10bd` computation that produces the 10BD statement, which is what
guarantees the certificate a donor receives and the return filed with the
department carry the same figures.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import fmt_money, money_in_words

from trust_compliance.core.compliance import build_form_10bd
from trust_compliance.core.financial_year import financial_year_window, is_financial_year
from trust_compliance.queries import donations

TEMPLATE = """
<div class="cert">
  <div class="head">
    <div class="org">{{ company }}</div>
    {% if reg and reg.registration_12ab %}<div class="sub">{{ _("Registration under Section 12A / 12AB:") }} {{ reg.registration_12ab }}</div>{% endif %}
    {% if reg and reg.trust_pan %}<div class="sub">{{ _("PAN:") }} {{ reg.trust_pan }}</div>{% endif %}
  </div>

  <div class="form-no">{{ _("FORM No. 10BE") }}</div>
  <div class="rule">{{ _("[See rule 18AB(4)]") }}</div>
  <div class="title">{{ _("Certificate of donation under clause (ix) of sub-section (5) of section 80G") }}</div>

  <table class="grid">
    <tr><td class="lbl">{{ _("Name of the donor") }}</td><td><b>{{ donor.donor_name }}</b></td></tr>
    <tr><td class="lbl">{{ _("Address of the donor") }}</td><td>{{ donor.address or "&mdash;" }}</td></tr>
    <tr>
      <td class="lbl">{{ _("Unique identification number") }}</td>
      <td>
        {% if donor.pan %}{{ donor.pan }} <span class="muted">({{ _("Permanent Account Number") }})</span>
        {% else %}<span class="warn">{{ _("Not available - Form 10BD cannot be filed without it") }}</span>{% endif %}
      </td>
    </tr>
    <tr><td class="lbl">{{ _("Financial year of receipt") }}</td><td>{{ financial_year }}</td></tr>
    <tr><td class="lbl">{{ _("80G approval number") }}</td>
      <td>{% if reg and reg.registration_80g %}{{ reg.registration_80g }}{% if reg.registration_80g_date %} {{ _("dated") }} {{ frappe.format(reg.registration_80g_date, {"fieldtype": "Date"}) }}{% endif %}{% else %}<span class="warn">{{ _("Not configured") }}</span>{% endif %}</td>
    </tr>
  </table>

  <table class="detail">
    <thead>
      <tr>
        <th>{{ _("Type of donation") }}</th>
        <th>{{ _("Mode of receipt") }}</th>
        <th class="num">{{ _("Receipts") }}</th>
        <th class="num">{{ _("Amount") }}</th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr>
        <td>{{ _(row.donation_type) }}</td>
        <td>{{ _(row.mode) }}</td>
        <td class="num">{{ row.receipt_count }}</td>
        <td class="num">{{ frappe.format(row.amount, {"fieldtype": "Currency", "options": currency}) }}</td>
      </tr>
      {% endfor %}
      <tr class="total">
        <td colspan="3">{{ _("Total donation received during the year") }}</td>
        <td class="num">{{ total_formatted }}</td>
      </tr>
    </tbody>
  </table>

  <div class="words">{{ _("In words") }}: <i>{{ total_in_words }}</i></div>

  <div class="decl">
    {{ _("I certify that the above particulars are true and correct to the best of my knowledge and belief, and that the donation stated above has been received by the Trust during the financial year mentioned.") }}
  </div>

  <table class="sign">
    <tr>
      <td>
        {{ _("Place") }}: ____________________<br><br>
        {{ _("Date") }}: {{ frappe.format(today, {"fieldtype": "Date"}) }}
      </td>
      <td class="right">
        <div class="line"></div>
        {% if reg and reg.authorised_signatory %}<b>{{ reg.authorised_signatory }}</b><br>{% endif %}
        {{ reg.signatory_designation if reg and reg.signatory_designation else _("Authorised Signatory") }}<br>
        {{ company }}
      </td>
    </tr>
  </table>
</div>

<style>
  body { background: #fff; }
  .cert { font-family: "Lato", "Helvetica Neue", Arial, sans-serif; color: #1a1a1a;
    max-width: 780px; margin: 24px auto; padding: 30px 34px; border: 1px solid #d8d8d8; }
  .head { text-align: center; border-bottom: 2px solid #1a1a1a; padding-bottom: 10px; }
  .org { font-family: "Playfair Display", Georgia, serif; font-size: 21px; font-weight: 700; }
  .sub { font-size: 10.5px; color: #555; margin-top: 2px; }
  .form-no { text-align: center; font-weight: 700; font-size: 14px; margin-top: 18px;
    letter-spacing: 1px; }
  .rule { text-align: center; font-size: 10.5px; color: #666; }
  .title { font-family: "Playfair Display", Georgia, serif; text-align: center;
    font-size: 13.5px; font-weight: 700; margin: 8px auto 20px; max-width: 560px;
    line-height: 1.45; }
  .grid { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
  .grid td { border: 1px solid #e2e2e2; padding: 7px 10px; font-size: 12px; }
  .lbl { color: #555; width: 250px; background: #fafafa; }
  .muted { color: #777; font-size: 10.5px; }
  .warn { color: #a11; font-weight: 600; }
  .detail { width: 100%; border-collapse: collapse; }
  .detail th { background: #f3f3f3; border: 1px solid #ddd; padding: 7px 10px;
    font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.6px; text-align: left; }
  .detail td { border: 1px solid #e2e2e2; padding: 7px 10px; font-size: 12px; }
  .num { text-align: right; }
  .total td { font-weight: 700; background: #fafafa; }
  .words { margin-top: 10px; font-size: 11.5px; }
  .decl { margin-top: 20px; font-size: 11.5px; line-height: 1.6; color: #333; }
  .sign { width: 100%; margin-top: 36px; font-size: 11.5px; }
  .sign td { vertical-align: bottom; }
  .right { text-align: right; }
  .line { border-top: 1px solid #333; width: 210px; margin-left: auto; margin-bottom: 5px; }
  @media print { .cert { border: none; margin: 0; } }
</style>
"""


@frappe.whitelist()
def get_certificate_html(donor: str, financial_year: str) -> str:
    """Render the Form 10BE certificate for one donor and financial year."""
    if not is_financial_year(financial_year):
        frappe.throw(
            _('Financial Year must be an Indian financial year such as "2026-27".')
        )

    donor_doc = frappe.get_doc("Trust Donor", donor)
    donor_doc.check_permission("read")

    if donor_doc.is_anonymous:
        frappe.throw(
            _(
                "Donor {0} is recorded as anonymous. Form 10BE certifies a named "
                "donor's donation and cannot be issued for anonymous receipts."
            ).format(donor_doc.donor_name)
        )

    from_date, to_date = financial_year_window(financial_year)
    company = donor_doc.company

    all_donations = donations(company, from_date, to_date)
    donor_donations = [row for row in all_donations if row.donor == donor]

    if not donor_donations:
        frappe.throw(
            _("Donor {0} has no submitted donations in {1}.").format(
                donor_doc.donor_name, financial_year
            )
        )

    statement = build_form_10bd(donor_donations, from_date=from_date, to_date=to_date)
    total = statement["summary"]["reported_total"]
    currency = frappe.get_cached_value("Company", company, "default_currency")

    settings = frappe.get_cached_doc("Trust Compliance Settings")
    reg = next(
        (row for row in settings.company_accounts if row.company == company), None
    )

    return frappe.render_template(
        TEMPLATE,
        {
            "donor": donor_doc,
            "company": company,
            "financial_year": financial_year,
            "rows": statement["rows"],
            "currency": currency,
            "total_formatted": fmt_money(total, currency=currency),
            "total_in_words": money_in_words(total, currency),
            "reg": reg,
            "today": frappe.utils.nowdate(),
            "_": _,
            "frappe": frappe,
        },
    )

"""Section 11(2) / Form 10 accumulation record.

Purely a statutory record: it posts no GL entry. Its only effect is that
`build_income_application` counts it as "accumulated" when measuring the 85%
application requirement, which is what lets a trust apply less than 85% in a year
without falling short.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from trust_compliance.core.financial_year import is_financial_year

#: Section 11(2) caps the accumulation period at five years.
MAX_PERIOD_YEARS = 5


class Form10Accumulation(Document):
    def validate(self):
        self.financial_year = (self.financial_year or "").strip()

        if not is_financial_year(self.financial_year):
            frappe.throw(
                _('Financial Year must be an Indian financial year such as "2026-27".')
            )

        if flt(self.amount) <= 0:
            frappe.throw(_("Amount accumulated must be greater than zero."))

        if not (1 <= (self.period_years or 0) <= MAX_PERIOD_YEARS):
            frappe.throw(
                _(
                    "Section 11(2) permits accumulation for one to {0} years; {1} was "
                    "entered."
                ).format(MAX_PERIOD_YEARS, self.period_years)
            )

        if not (self.purpose or "").strip():
            frappe.throw(
                _(
                    "Form 10 requires the specific purpose the income is set apart "
                    "for. A general purpose is not sufficient in law."
                )
            )

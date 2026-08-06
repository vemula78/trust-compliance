"""Master of the investment modes a 12A/12AB trust is permitted to hold.

Section 11(5) lists the permitted modes and Rule 17C extends them. The list is a
master record rather than a Select option list or a constant in the UI because
Rule 17C is amended by notification: a new clause has to be addable by the
accounts team without an app release, and a withdrawn clause has to be
*disabled* rather than deleted, because investments already made under it must
keep their citation for the assessing officer.

Why this matters: an investment outside 11(5) makes that income taxable at 30%
under section 115BBI, and since the Finance Act 2021 corpus keeps its 11(1)(d)
exemption only while it is held in an 11(5) mode and separately identifiable. So
the citation on every instrument is a statutory field, not a note.

The rule table itself lives in `trust_compliance.core.investment.PERMITTED_MODES`
and stays the authority. This master is seeded from it and is validated against
it, so a clause typed in by hand that the rules do not recognise is flagged at
the point it is created rather than at the point an investment is refused.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from trust_compliance.core.investment import PERMITTED_MODES, is_permitted_mode

#: Clauses inserted by Rule 17C rather than by section 11(5) itself. The seed has
#: no statute key, so it is derived from the citation: a Rule 17C clause is cited
#: as 17C(...). Anything else is read as a section 11(5) clause.
RULE_17C_MARKER = "17c"


class InvestmentMode(Document):
    def validate(self):
        self.clause = (self.clause or "").strip()
        self._warn_if_unrecognised_clause()
        self._warn_if_speculative_allows_equity()

    def _warn_if_unrecognised_clause(self):
        """Flag a clause the core rule table does not know.

        Creating the record is still allowed - a notification can add a clause
        before the app is updated - but `validate_investment_mode` matches on the
        clause string, so an investment citing an unrecognised clause will be
        refused. Saying so here is the difference between a five-second fix and a
        confusing rejection later.
        """
        if is_permitted_mode(self.clause):
            return

        frappe.msgprint(
            _(
                "Clause <b>{0}</b> is not in the section 11(5) / Rule 17C table this "
                "app validates against, so an investment citing it will be refused as "
                "a non-permitted mode. Check the citation, or update "
                "<code>trust_compliance.core.investment.PERMITTED_MODES</code> if the "
                "clause was added by a later notification."
            ).format(self.clause),
            title=_("Clause not recognised"),
            indicator="orange",
        )

    def _warn_if_speculative_allows_equity(self):
        """A speculative mode that also permits equity is almost certainly a typo.

        Not refused, because the two flags are independent in principle, but the
        combination is what an FCRA fund is barred from twice over and is worth a
        second look before it is saved.
        """
        if self.is_speculative and self.allows_equity:
            frappe.msgprint(
                _(
                    "Mode {0} is flagged both speculative and equity-permitting. An "
                    "FCRA fund can hold neither. Confirm both flags are intended."
                ).format(self.clause),
                indicator="orange",
            )


def create_default_investment_modes() -> list[str]:
    """Seed the permitted-mode master from the core rule table. Idempotent.

    Existing records are left untouched rather than overwritten: the accounts team
    may have added notes or disabled a withdrawn clause, and re-running the
    installer must not undo that. Only missing clauses are inserted, so this is
    safe to call on every install and on upgrade after a notification adds a
    clause to `PERMITTED_MODES`.
    """
    created: list[str] = []

    for clause, spec in PERMITTED_MODES.items():
        citation = spec.get("clause") or clause
        if frappe.db.exists("Investment Mode", citation):
            continue

        mode = frappe.get_doc(
            {
                "doctype": "Investment Mode",
                "clause": citation,
                "label": spec.get("label") or citation,
                "statute": _statute_for(citation),
                "is_speculative": 1 if spec.get("is_speculative") else 0,
                "allows_equity": 1 if spec.get("allows_equity") else 0,
                "citation_verified": 1 if spec.get("verified") else 0,
                "disabled": 0,
                "notes": _seed_note(spec),
            }
        )
        mode.flags.ignore_permissions = True
        mode.insert()
        created.append(mode.name)

    return created


def _statute_for(citation: str) -> str:
    """Which enactment a clause comes from, derived from how it is cited."""
    return "Rule 17C" if RULE_17C_MARKER in citation.lower() else "Section 11(5)"


def _seed_note(spec: dict) -> str:
    """Carry the core table's `verified` caveat onto the record the user edits.

    The Rule 17C sub-clause numbering in the core table is a reconstruction, not a
    transcription of the notified rule. A wrong citation on a Form 10B annexure is
    worse than none, because the reader takes it at face value - so the caveat is
    written where the accounts team will see it, on the record they are expected to
    correct.
    """
    if spec.get("verified"):
        return ""
    return (
        "Sub-clause numbering not verified against the notified text of Rule 17C. "
        "Have the Trust's auditor confirm the citation and correct this record."
    )

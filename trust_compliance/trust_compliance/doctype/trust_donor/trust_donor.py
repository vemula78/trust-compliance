"""Donor master."""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document

#: PAN format mandated for Form 10BD reporting.
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

#: Fourth character of a PAN encodes the holder's status. Only these are
#: consistent with the donor types this app models.
PAN_HOLDER_TYPE = {"P": "Individual", "C": "Company", "T": "Trust", "H": "Individual",
                   "F": "Company", "A": "Trust", "B": "Trust", "L": "Company",
                   "J": "Company", "G": "Trust"}


class TrustDonor(Document):
    def validate(self):
        self._normalise()
        self._validate_pan()
        self._validate_foreign_donor_has_country()
        self._validate_anonymous_donor_is_not_identified()
        self._validate_interested_person_is_identified()

    def _normalise(self):
        self.donor_name = (self.donor_name or "").strip()
        if self.pan:
            self.pan = self.pan.strip().upper()

    def _validate_pan(self):
        if not self.pan:
            return
        if not PAN_PATTERN.match(self.pan):
            frappe.throw(
                _("PAN {0} is not in AAAAA9999A format.").format(self.pan),
                title=_("Invalid PAN"),
            )

        # The fourth character encodes holder status; a mismatch with the donor
        # type is usually a data-entry error and would be rejected by the
        # Form 10BD utility months later, so it is caught here instead.
        expected = PAN_HOLDER_TYPE.get(self.pan[3])
        if expected and self.donor_type in {"Individual", "Company", "Trust"}:
            if expected != self.donor_type:
                frappe.msgprint(
                    _(
                        "PAN {0} has holder status '{1}', which reads as {2} rather "
                        "than {3}. Check the PAN or the donor type before filing 10BD."
                    ).format(self.pan, self.pan[3], _(expected), _(self.donor_type)),
                    indicator="orange",
                    title=_("PAN and donor type disagree"),
                )

    def _validate_foreign_donor_has_country(self):
        if self.donor_type == "Foreign" and not self.country:
            frappe.throw(
                _(
                    "A foreign donor needs a country: FC-4 reports foreign "
                    "contribution country-wise."
                ),
                title=_("FCRA"),
            )

    def _validate_anonymous_donor_is_not_identified(self):
        """An anonymous donor with a PAN is a contradiction, and a filing risk.

        Anonymous donations are excluded from Form 10BD and monitored under
        115BBC. If the donor is in fact identified, marking them anonymous
        understates the 10BD statement.
        """
        if self.is_anonymous and self.pan:
            frappe.throw(
                _(
                    "Donor {0} is marked anonymous but carries a PAN. An identified "
                    "donor must be reported in Form 10BD; clear one or the other."
                ).format(self.donor_name),
                title=_("Section 115BBC"),
            )

    def _validate_interested_person_is_identified(self):
        """Section 13(3) describes named persons, so the record must name one.

        An anonymous collection is by definition an unidentified giver; it cannot
        be established as an author, trustee, substantial contributor or their
        concern. Allowing the flag there would also be actively harmful: the
        investment check refuses any instrument naming a flagged record, so a
        flagged hundi record would refuse lawful investments for a reason nobody
        could substantiate at audit.
        """
        if self.is_interested_person and self.is_anonymous:
            frappe.throw(
                _(
                    "Donor {0} is marked anonymous, so it cannot also be an "
                    "interested person under section 13(3) - that section applies "
                    "to identified persons. Clear one or the other."
                ).format(self.donor_name),
                title=_("Section 13(3)"),
            )

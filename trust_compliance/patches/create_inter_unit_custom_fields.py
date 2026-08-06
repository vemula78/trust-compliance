"""Add the inter-unit fields to Journal Entry on an existing install.

`after_install` creates this app's custom fields, which is enough for a new site
but does nothing for a site that already has the app - and the fields are not
optional: `queries.inter_unit_gl_rows` joins on `is_inter_unit`, so without them
the Inter-Unit Eliminations report errors rather than showing an empty schedule.

`create_custom_fields` skips fields that already exist, so this is safe to re-run.
"""

from __future__ import annotations

from trust_compliance.setup.custom_fields import create_trust_custom_fields


def execute() -> None:
    create_trust_custom_fields()

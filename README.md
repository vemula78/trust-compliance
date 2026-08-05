# Trust Compliance

Fund accounting, 80G donation receipting and FCRA segregation for Indian charitable
trusts registered under section 12A/12AB, built as an app on **ERPNext**.

ERPNext is a mature double-entry ERP but has no concept of a fund, of foreign
contribution kept legally separate from domestic money, or of the returns an Indian
charitable trust has to file. This app adds those, using ERPNext's own mechanisms
rather than a parallel ledger.

## What it adds

| | |
|---|---|
| **Fund** | Fund master with the four classes (Corpus, Restricted, Designated, Unrestricted), registered as an ERPNext **Accounting Dimension** so `fund` appears on GL Entry and on every voucher ERPNext posts from. |
| **FCRA segregation** | Foreign and domestic money can never mix inside one voucher. Enforced on the GL entries a voucher actually produced, inside the submitting transaction — see below. |
| **Trust Donor** | Donor master with PAN validation (including holder-status cross-check against donor type), country for FC-4, and anonymous-donor handling. |
| **Trust Donation** | Receipting with gap-free `80G/<FY>/<seq>` numbering per financial year, automatic balanced GL posting, corpus-versus-income routing, Section 269ST cash limit, and a PAN requirement above a configurable value because Form 10BD cannot be filed without one. |

## Design

**All rules live in `trust_compliance/core/`, which imports no frappe.** Those
modules take plain mappings and return plain data, so the entire rule set is
unit-tested outside a bench:

```bash
python3 -m pytest tests/ -q          # 50 tests, no bench needed
```

There is also an end-to-end self-check that runs against a real site. It creates a
company, funds, donors and posted donations, then asserts that receipts number
gap-free, that donations post balanced fund-tagged GL, that every route by which
foreign and domestic money could mix is refused, and that the fund and FC-4
reports reconcile against the GL it just wrote. It is idempotent — it resets its
own prior run — and returns a non-zero failure count so it can gate a deployment:

```bash
bench --site <site> execute trust_compliance.smoke.run
```

Verified on ERPNext 16.31.0 / Frappe 16.30.0: 40/40 checks pass.

The frappe-facing code (`fcra.py`, the doctype controllers) reads records, hands
mappings to the core, and turns returned strings into `frappe.throw`. This mirrors
the `accounting.ts` / repository split in the Next.js ERP the logic was ported
from, and it is what makes a divergence between the two implementations show up
as a test failure rather than as a wrong number in a filed return.

**Fund is an ERPNext Accounting Dimension, not a custom tag.** Creating the
dimension makes ERPNext add the `fund` field to GL Entry and to every voucher and
voucher line that posts — Journal Entry, Payment Entry, Sales and Purchase
Invoice and their items and taxes, Expense Claim, Stock Entry, Payroll Entry,
Asset. Fund therefore flows through ERPNext's existing posting engine, its
dimension filters, and its General Ledger / Trial Balance / Financial Statements
reports, all of which already accept a dimension filter. The app only has to add
the statements ERPNext has no concept of.

**FCRA segregation is enforced on produced GL entries, not per voucher type.**
ERPNext writes GL entries during `on_submit`, and app-level `on_submit` hooks run
after the document's own, in the same transaction. So a single wildcard hook reads
the voucher's final, post-tax GL effect and rolls the whole submission back if it
mixes foreign and domestic money. There is no voucher type — present or future,
core or third-party — through which the wall can be crossed. `Journal Entry` also
gets a pre-submit check so a manual journal fails while it is still a draft.

Three rules are applied (`core/segregation.py`):

1. **Mixing** — every line in a voucher must resolve to funds with the same FCRA
   status. An untagged line follows the company default fund, which is required to
   be domestic, so a half-tagged voucher touching an FCRA fund reads as mixed
   rather than being silently accepted.
2. **Unknown fund** — a line naming a fund absent from the master is refused,
   because which side of the wall it belongs to cannot be proven.
3. **Account/fund pairing** — a line posted to an FCRA-designated account must
   resolve to an FCRA fund. This is what stops a journal from debiting the FCRA
   bank against a domestic credit, since such a voucher tags no fund at all and
   would otherwise read as wholly domestic.

**Accounts are configured, never derived.** `Trust Compliance Settings` holds the
donation-income, corpus, cash, bank and FCRA-designated accounts per company, and
validates each against the root type it must have — corpus into Equity, not
Income, because corpus is capital of the Trust and routing it through income
would overstate the year's income and distort the 85% application test.

## Install

```bash
bench get-app /path/to/trust_compliance
bench --site <site> install-app trust_compliance
```

Then, in this order:

1. Flag the FCRA-designated bank account: **Account → Trust Compliance → FCRA-designated**.
2. Flag administrative expense accounts the same way (they count toward the FCRA 20% cap).
3. Create the fund master. `trust_compliance.install.seed_trust_funds(company)` creates a
   conventional starting set; fund codes are the Trust's choice, so this is a
   deliberate opt-in rather than something the installer does.
4. Fill in **Trust Compliance Settings → Company Accounts**.
5. Optionally make the dimension mandatory:
   `trust_compliance.setup.accounting_dimension.set_fund_mandatory(company, default_fund)`.

## Known gaps

Tracked deliberately, not hidden:

- **In-kind donations** post the GL effect correctly but do not yet create the
  ERPNext Asset register record, which needs a fixed-asset Item. Donated
  *property* — the dominant in-kind case — is the Property register's job.
- **Property register, property tax, maintenance, program accounting** (Phase 11
  of the source ERP) are not ported yet.
- **Reports** — FC-4, Form 10BD/10BE, 85% application and the fund-wise
  statements exist as computations in `core/compliance.py` with full test
  coverage, but are not yet exposed as Frappe reports or print formats.
- **Fund transfers** and **Form 10 accumulation** records are not ported yet.

## Provenance

Ported from the Trust layer (Phases 9–10) of a Next.js + Prisma accounting ERP,
preserving the bases of measurement exactly — the FCRA 20% cap measured against
contribution *received* rather than utilised, fund balances on a net-asset basis
that reads an equity debit as an outflow, and receipt numbering that skips rather
than ever re-issuing a number. The `tests/` suite asserts those behaviours so the
two implementations cannot drift silently.

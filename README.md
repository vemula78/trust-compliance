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
| **Fund Transfer** | Both legs post to one equity clearing account, so the trial balance is untouched and the whole movement is carried by the fund dimension. Corpus is one-way; FCRA and domestic funds cannot be bridged. |
| **Property register** | Donated properties with survey number, municipality, extent and valuation; property-tax demands billed **through Accounts Payable**; maintenance and AMC records linked to the vendor's bill. |

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

Verified on ERPNext 16.31.0 / Frappe 16.30.0: 109/109 checks pass.

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
6. **Set the number format to `#,##,###.##`.** Not cosmetic: the amount in words is
   the operative figure on an 80G receipt, and Frappe only uses Indian lakh/crore
   wording when this format is effective. Otherwise a receipt reads *"Rupees Five
   Hundred And Sixty Thousand only"* instead of *"Rupees Five Lakh, Sixty Thousand
   only"*. On **Frappe 16 this is locale-resolved** — the active `Language`
   record's Number Format overrides the System Settings default — so set System
   Settings *and* make sure the Language record does not contradict it. Trust
   Compliance Settings warns when the effective format is not Indian.

## Reports

Seven script reports, all driven from one GL query (`trust_compliance/queries.py`) so
no two can disagree with the ledger, and all computed by the tested pure functions:

| Report | Notes |
|---|---|
| **Fund Balances** | Opening / inflow / outflow / closing net assets per fund. |
| **Fund Income and Expenditure** | The per-fund statement, as an indented tree. Equity — corpus and inter-fund transfers — excluded by construction. |
| **Donation Register** | With Section 115BBC monitoring against the higher of the statutory floor and 5% of total donations. |
| **FCRA Register** | Contributor-wise receipts, utilisation with administrative classification, and the 20% cap measured against contribution *received*. Warns when ledger receipts exceed receipted donations, i.e. foreign contribution posted by journal entry with no contributor row to file. |
| **Income Application** | 85% application tracking. Labelled a working paper, with every simplification stated on the report itself. |
| **Form 10BD Statement** | One row per donor per donation type per mode, matching the filing utility. Flags rows with no PAN rather than dropping the donor. |

| **Property Register** | One row per property with its fund, recorded value, tax outstanding, next due date and maintenance spend. Outstanding is read from the invoice, not from the schedule's status field. |

Plus the **80G Donation Receipt** print format, and a **Form 10BE certificate**
rendered per donor per financial year from the same computation that produces the
10BD statement — so the certificate a donor holds and the return filed with the
department cannot disagree. It is reachable from a button on Trust Donor.

## Upgrading

`bench migrate` does **not** re-sync an existing Workspace — Frappe treats
workspaces as user-customisable once created, so a release that adds doctypes or
reports will not show them in the sidebar. After upgrading:

```bash
bench --site <site> execute frappe.delete_doc --kwargs '{"doctype":"Workspace","name":"Trust Compliance","force":1,"ignore_permissions":1}'
bench --site <site> migrate
```

That recreates the workspace from the app's definition. Anything an administrator
customised on it by hand is lost, which is why it is a deliberate step rather than
something the app does on migrate.

## Known gaps

Tracked deliberately, not hidden:

- **In-kind donations** post the GL effect correctly but do not yet create the
  ERPNext Asset register record, which needs a fixed-asset Item. Donated
  *property* — the dominant in-kind case — is the Property register's job.
- **Property register, property tax, maintenance, program accounting** (Phase 11
  of the source ERP) are not ported yet.
- **CSV export shape** for Form 10BD is the report's own export, not the utility's
  exact template. The columns are named to match; the mapping has not been tested
  against a live filing.
- **Program / inter-unit accounting** (Trust → hospital, Trust → school transfers
  with elimination on consolidation, and program budget-vs-utilisation) is the
  remaining piece of Phase 11 and is not built.
- **Property tax reminders** are not automated. The Property Register shows what is
  overdue and what is due next, but nothing emails anyone; a Notification on
  Property Tax Schedule would cover it.
- **Payments must name the fund.** Because the dimension is mandatory for
  balance-sheet accounts, a Payment Entry settling a fund's bill has to carry the
  fund on the parent and on its references. That is correct for fund accounting —
  money leaves a specific fund's bank — but it is extra keying, and a default
  dimension per company only pre-fills the general fund.

## Provenance

Ported from the Trust layer (Phases 9–10) of a Next.js + Prisma accounting ERP,
preserving the bases of measurement exactly — the FCRA 20% cap measured against
contribution *received* rather than utilised, fund balances on a net-asset basis
that reads an equity debit as an outflow, and receipt numbering that skips rather
than ever re-issuing a number. The `tests/` suite asserts those behaviours so the
two implementations cannot drift silently.

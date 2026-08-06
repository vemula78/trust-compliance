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
| **Trust Donor** | Donor master with PAN validation (including holder-status cross-check against donor type), country for FC-4, anonymous-donor handling, and the **section 13(3) interested-person** flag the investment check reads. |
| **Trust Donation** | Receipting with gap-free `80G/<FY>/<seq>` numbering per financial year, automatic balanced GL posting, corpus-versus-income routing, Section 269ST cash limit, and a PAN requirement above a configurable value because Form 10BD cannot be filed without one. |
| **Fund Transfer** | Both legs post to one equity clearing account, so the trial balance is untouched and the whole movement is carried by the fund dimension. Corpus is one-way; FCRA and domestic funds cannot be bridged. |
| **Property register** | Donated properties with survey number, municipality, extent and valuation; property-tax demands billed **through Accounts Payable**; maintenance and AMC records linked to the vendor's bill. |
| **Investments** | Corpus and other funds invested only in the forms and modes permitted by **section 11(5)** (extended by Rule 17C), held as a maintainable master rather than hardcoded. Compliance is re-checked on the register, not just at purchase. Interest and dividend are booked as **income of the year, never corpus**. |
| **Inter-unit transfers** | A grant from the Trust to one of its hospitals or schools posts in **both units' books in one step** — expense and bank in the paying unit, bank and grant income in the receiving one — and both legs are flagged in the ledger so a consolidated statement can eliminate them. Corpus cannot be paid out and foreign contribution cannot be transferred at all (FCRA s.7). |
| **Program accounting** | Programs are ERPNext **Projects**, so the dimension is already on every GL Entry. Utilisation is read off the ledger, fund by fund, against the ERPNext **Budget** set on the program. |

### Why an inter-unit transfer is two entries and one elimination

Each unit of the Trust keeps its own books and files its own return, so a grant to a
hospital is real expenditure in the Trust's accounts — application of its income
under section 11(1)(a) — and real income in the hospital's. Both entries have to
stand.

At *group* level they are the same money seen twice. A consolidation that added them
would inflate group income and group expenditure by the amount transferred and show
the group applying income it had only moved between its own pockets. ERPNext's
Consolidated Financial Statement does not eliminate this, so both legs carry
`is_inter_unit` and the counterparty unit in the ledger itself, and the **Inter-Unit
Eliminations** report is the disclosure that goes with the consolidation: how much to
remove from each side, per pair of units, with the two sides reconciled against each
other. If they differ, one leg was cancelled or edited alone — a real defect that a
single total would hide.

### Why the investment module refuses rather than warns

Investing outside a section 11(5) mode makes that income *specified income*, taxable
at 30% under **section 115BBI**, with repeated breach putting the 12AB registration
at risk under 12AB(4). Since Finance Act 2021 a corpus donation keeps its
11(1)(d) exemption **only** while it stays in an 11(5) mode and separately
identifiable. So the rules are enforced at posting time:

- The instrument's mode must map to a permitted 11(5) / Rule 17C clause.
- Equity shares are permitted only in a **public sector company** (11(5)(vii)).
- An investment funded from an **FCRA** fund may not use a speculative mode —
  FCRA s.8(1) with FCRR Rule 4 forbid using foreign contribution for speculation, so
  bank deposits are allowed and equity is not. Income on an FCRA investment is
  itself foreign contribution and returns to the FCRA fund.
- **One funding fund per instrument.** A deposit bought from a pool holding mixed
  FCRA and domestic money, or mixed corpus and unrestricted money, makes FC-4 and
  corpus identification unprovable at audit, so co-funding is impossible by design.
- Interest and dividend credit an **income** account, never the corpus equity
  account — crediting corpus-FD interest back to corpus would silently remove it
  from the 85% application test. TDS is booked as a **recoverable asset**, and
  reinvested interest is *not* application of income.
- Funds may not be invested with, or in a concern of, a **section 13(3) interested
  person** — an author or founder, a trustee or manager, a substantial contributor,
  their relatives, or a concern in which any of them has a substantial interest.
  Mark the person on their **Trust Donor** record (`Interested Person u/s 13(3)`,
  with the limb of 13(3) that applies) and both the counterparty and the issuer are
  refused from then on. The register re-checks it, because a person *becomes*
  interested — appointed a trustee, or crossing the contribution threshold —
  without any transaction being posted, and that taints income from an instrument
  that was clean when bought.

## Design

**All rules live in `trust_compliance/core/`, which imports no frappe.** Those
modules take plain mappings and return plain data, so the entire rule set is
unit-tested outside a bench:

```bash
python3 -m pytest tests/ -q          # 90 tests, no bench needed
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

Verified on ERPNext 16.31.0 / Frappe 16.30.0: **146/146 checks pass on a clean
install** - a site created with `bench new-site --install-app erpnext`, the app added
with `bench get-app`, and nothing else pre-provisioned. Re-running it on the same
site passes identically, so it is genuinely idempotent rather than order-dependent.

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
bench get-app /path/to/trust_compliance     # add --skip-assets if the bench has no Node
bench --site <site> install-app trust_compliance
```

Two things worth knowing before you run that:

- **`bench get-app` runs `bench build`, which needs Node.** This app ships no bundled
  assets — no `package.json`, no `*.bundle.js`, no `public/` — so `--skip-assets` is
  safe and loses nothing. It matters on a container-split deployment (the official
  `frappe/erpnext` *backend* image has no Node, because assets are prebuilt in the
  frontend image), where `get-app` otherwise fails at the build step *after* it has
  already cloned and pip-installed the app.
- **The app must be a git repository.** `bench get-app` clones it, and bench derives
  `sites/apps.txt` from the apps directory. An app copied in without its `.git` gets
  silently dropped from `apps.txt`, which then surfaces as a baffling
  `NameError: trust_compliance is not defined` from any `bench execute`.

Then, in this order:

1. Flag the FCRA-designated bank account: **Account → Trust Compliance → FCRA-designated**.
2. Flag administrative expense accounts the same way (they count toward the FCRA 20% cap).
3. Create the fund master. `trust_compliance.install.seed_trust_funds(company)` creates a
   conventional starting set; fund codes are the Trust's choice, so this is a
   deliberate opt-in rather than something the installer does.
4. Fill in **Trust Compliance Settings → Company Accounts**.
5. Optionally make the dimension mandatory:
   `trust_compliance.setup.accounting_dimension.set_fund_mandatory(company, default_fund)`.
6. **Mark the section 13(3) interested persons** on Trust Donor — the authors and
   founders, trustees and managers, substantial contributors, their relatives, and
   the concerns they control. The investment check can only refuse a person somebody
   has marked, so an unmarked trustee's company is an accepted investment. Create a
   Trust Donor record for a concern the Trust has never received a donation from.
7. **Number format — handled for you, with one caveat.** Installing the app sets the
   number format to `#,##,###.##` if the site is still on Frappe's untouched default,
   because Indian lakh/crore grouping *and* Indian amount-in-words both derive from
   it, and on an 80G receipt the amount in words is the operative figure. A clean-install
   rehearsal showed that leaving this to a manual step produced a working system that
   quietly issued receipts reading *"Rupees Five Hundred And Sixty Thousand only"*
   instead of *"Rupees Five Lakh, Sixty Thousand only"*.

   If the format had already been changed from the default, the app leaves it alone —
   a site-global setting is the administrator's. The caveat: on **Frappe 16 the format
   is locale-resolved**, so the active `Language` record's Number Format overrides the
   System Settings value. Trust Compliance Settings warns whenever the *effective*
   format is not Indian, which catches that case.

## Reports

Ten script reports, all driven from one GL query (`trust_compliance/queries.py`) so
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
| **Investment Register** | Holdings at cost with the 11(5) clause re-checked per row, income and TDS shown separately, and any violation named. |
| **Program Utilisation** | Grant received, spent, budget and utilisation per program, with the funds that paid for it. Spending tagged to no program is disclosed rather than pooled into an "unassigned" row, because that difference is exactly what reconciles this report to the Income and Expenditure statement. |
| **Inter Unit Eliminations** | What a consolidated statement must remove, per pair of units, with the paying unit's expense reconciled against the receiving unit's grant income. |

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

Custom fields this app adds to ERPNext doctypes *are* created on migrate, by a patch
in `trust_compliance/patches.txt` — `after_install` alone would leave an existing
site without them, and a missing `is_inter_unit` column makes the eliminations report
error rather than show an empty schedule.

The **Transfers to Institutions** and **Grants Received** accounts must be set in
Trust Compliance Settings for each unit that pays or receives an inter-unit transfer.
Both are checked at posting time: the paying side must be an Expense account and the
receiving side Income, because the elimination pairs one against the other.

## Known gaps

Tracked deliberately, not hidden:

- **In-kind donations** post the GL effect correctly but do not yet create the
  ERPNext Asset register record, which needs a fixed-asset Item. Donated
  *property* — the dominant in-kind case — is the Property register's job.
- **The elimination is a disclosure, not an adjustment.** ERPNext's Consolidated
  Financial Statement still shows both legs; the Inter-Unit Eliminations report says
  what to take out of it and the adjustment is made by whoever prepares the
  consolidated accounts. Overriding ERPNext's own consolidation report to apply it
  automatically would mean maintaining a fork of that report through every ERPNext
  release, against a group of three or four units where the figure is one line.
- **A program budget is not enforced, only reported.** ERPNext's Budget can stop a
  posting that exceeds it, but only for the accounts and document types configured
  on the Budget record itself; nothing here adds an enforcement of its own, and a
  program can be overspent. The report names it in red.
- **The section 13(3) check depends on the flag being set, and matches the issuer
  by name.** The rule is live, but it can only refuse a person the trustees have
  marked on their Trust Donor record; nothing derives interested-person status, and
  a substantial contributor crossing the threshold is not detected from the
  donation ledger. The `counterparty` link is matched reliably; the free-text
  `issuer` is matched on the donor's name, case- and space-insensitively, so a
  spelling variant escapes it. Concerns the Trust has never received a donation
  from need a Trust Donor record created for them before they can be flagged.
- **No Rule 17C clauses ship.** An earlier version seeded a plausible `17C(i)`–`17C(v)`
  table; an independent audit established it was materially wrong (the current rule
  has Public Account of India at (ii), the housing-authority deposit at (iii), and
  runs to (x)). Shipping nothing is deliberate — a wrong statutory citation on an
  audit schedule is worse than none. Add the notified Rule 17C clauses to the
  **Investment Mode** master; they take effect immediately, because the master is
  the authority, not the code.
- **`donated_share_disposal_deadline` is implemented and tested but unused.**
  Shares arriving as an in-kind donation must be converted to a permitted mode
  within a year of the FY end; nothing yet enforces or alerts on that deadline.
- **The clause is self-certified against the instrument.** The app checks that the
  mode exists, is not withdrawn, and permits equity if the instrument is equity —
  but not that the instrument genuinely satisfies the clause. An unguaranteed
  private debenture entered as `11(5)(iii)` (a scheduled-bank deposit) will pass.
  An allowed-instrument list per mode would close this.
- **PSU status is a self-certified checkbox** against a free-text issuer, so
  `issuer_is_psu` ticked on a private company passes.
- **No unique instrument identity.** `folio_no` is optional and non-unique, so the
  same physical deposit can be entered twice under two funds. One fund per
  *record* is enforced; one record per *deposit* is not.
- **Single currency assumed.** Amounts are written to account-currency fields
  without an exchange rate, so a non-INR investment account would misstate or fail
  to balance.
- **Investment income is tagged to the funding fund**, so a corpus fund's balance
  includes interest not yet applied. That is required for FCRA (income of foreign
  contribution *is* foreign contribution) and keeps traceability, but it means the
  corpus fund reads higher than its spendable-corpus figure. Moving that income to
  a spendable fund is a deliberate Fund Transfer, not automatic. Confirm the policy
  with the Trust's auditor.
- **No accrual, rollover or revaluation events.** Only Interest, Dividend,
  Redemption and Maturity are modelled. Accrued-but-unreceived interest on a
  mercantile basis, and auto-rollover of a cumulative deposit (which needs a fresh
  11(5) check), are not handled.
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

Ported from the Trust layer (Phases 9–11) of a Next.js + Prisma accounting ERP,
preserving the bases of measurement exactly — the FCRA 20% cap measured against
contribution *received* rather than utilised, fund balances on a net-asset basis
that reads an equity debit as an outflow, and receipt numbering that skips rather
than ever re-issuing a number. The `tests/` suite asserts those behaviours so the
two implementations cannot drift silently.

Two things were changed rather than copied, both because the source could not do
better. Its elimination reported a single total — the debit value removed, which for
one transfer of X reads 2X; here the two sides are reported separately and reconciled,
so one leg cancelled alone is visible instead of hidden inside a doubled figure. And
its program report had no budget column at all: its budget line was keyed on
(cost centre, account, period) with no project on it, so a program budget could not
be derived. ERPNext's Budget can be set against a Project, so budget-versus-utilisation
is delivered here — the one Phase 11 item the source ERP left open.

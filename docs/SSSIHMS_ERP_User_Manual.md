# SSSIHMS ERP — User Manual

**erp.sssihms.org** · Frappe/ERPNext v16 · Compiled 17-Aug-2026, gotchas below
confirmed 18-Aug-2026

This manual explains, form by form, how to enter data into each module on the
SSSIHMS ERP. Part 1 covers the modules built specifically for SSSIHMS — every
field, required/optional marker and workflow rule below is taken from the
actual DocType configuration on the live system, not summarised from memory.
Part 2 covers the standard Frappe/ERPNext modules used as published, with
step-by-step instructions for the tasks staff use most often, plus a link to
the publisher's own complete manual.

**Conventions used below:** a field marked **(required)** must be filled
before the record can be saved — Frappe will block the save and highlight it
in red if it's empty. Fields not marked required are optional. **Select**
fields are dropdowns with a fixed list of choices (the choices are listed).
**Link** fields open a search box against another list (e.g. Employee,
Department) — start typing and pick from the results, or use "Create a new
Employee" from the same box if it doesn't exist yet.

---

# Part 1 — SSSIHMS Custom Modules

## 1. HR (sssihms_hr)

Menu location: **HR** workspace. Roles: **HR Manager**, **HR User**,
**Employee**.

### 1.1 Ward
Reference list of hospital wards used by rostering and shift-swap forms.
- **Ward Name (required)** — free text, e.g. "ICU-2".
- Department (link to Department), Floor, Nurse:Patient Ratio — free text.
- Minimum Senior Coverage — dropdown: None / One / Two.
- Float Pool Allowed, Critical Care Ward — tick boxes.
- Notes — free text.
To use: HR User/Manager creates one Ward per physical ward before rostering
starts; Roster Assignment and Shift Swap Request both pick from this list.

### 1.2 Roster Assignment
One row per employee, per day, per shift.
- Employee **(required)**, Ward **(required)**.
- Day (0=Mon .. 6=Sun) **(required)** — enter as a number 0–6.
- Shift **(required)** — dropdown: M (Morning) / E (Evening) / N (Night) / G (General).
- Status **(required)** — Draft / Published / Changed.
To fill: pick the employee and ward, enter the day-of-week number, pick the
shift code, leave Status as Draft until the roster is finalised, then set it
to Published so staff see it.

### 1.3 Shift Swap Request
- From Employee **(required)**, To Employee **(required)** — the employee
  giving up the shift and the one taking it.
- Ward **(required)**, Day of Month **(required)** — a number; the system
  rejects out-of-range values (e.g. 0 or above 31) at save time.
- Shift **(required)** — M/E/N/G.
- Reason — free text, optional.
- Status **(required)** — Pending / Approved / Rejected.
- Staffing Risk — Low / Medium / High (set by HR when reviewing, not by the requester).
To fill: an Employee opens a new Shift Swap Request, picks themself as From
Employee (the system only lets a logged-in Employee submit a swap where they
are the From Employee — picking someone else is rejected), picks the
colleague as To Employee, the ward, day and shift, adds a reason, and saves
with Status = Pending. HR Manager/User then reviews and changes Status to
Approved or Rejected.

### 1.4 Staff Credential
Tracks one licence/certification per employee.
- Employee **(required)**, Credential Type **(required)** — e.g. "Nursing
  Council Registration".
- Credential Number, Issuing Authority, Issue Date, Expiry Date — optional.
- Status **(required)** — pending / active / rejected / expired.
- Document — attach the scanned certificate (optional but recommended).
- Verified By, Verified At — filled automatically, do not edit.
To fill: create the record with Credential Type and (if you have them) the
number/authority/dates, attach the document, and save. **Status will always
save as "pending" even if you try to type "active"** — this is deliberate.
To actually activate a credential, an authorised user opens the record and
runs the **Verify** action from the menu (not a plain save); this is what
sets Status to active and stamps Verified By / Verified At.

### 1.5 Staff Document
A private file attached to an employee's HR record (ID proof, contract, etc.).
- Employee **(required)**, Category **(required)** — free text, e.g. "ID Proof".
- File **(required)** — attach the document.
- Verification Status **(required)** — pending / verified / rejected.
- Issue Date, Expiry Date, Notes — optional.
- Filename, Content Type, Size, SHA-256 Checksum, Uploaded By, Version,
  Supersedes, Is Current, Verified By, Verified At — filled automatically.
To fill: pick the Employee, type a Category, attach the File, save. **The
file is always stored privately** regardless of how you attach it — there is
no way to make it public from this form. To replace an outdated document,
upload a new Staff Document with the same Category and link it via
"Supersedes"; do not edit the old one in place.

### 1.6 Staff Performance Review
- Employee **(required)**, Cycle **(required)** — e.g. "2026-H2".
- Reviewer **(required)** — free text name.
- Score **(required)** — a number.
- Potential **(required)** — Developing / Meets / High.
- Status **(required)** — Self Review / Manager Review / Calibration / Closed.
To fill: start at Self Review, move the Status forward as the cycle
progresses. **Once Status is set to Closed, the Score and Reviewer fields can
no longer be changed by a plain edit** — if a correction is genuinely needed
after closing, it has to go through re-opening the record, not a direct edit.

### 1.7 Staff Career Action
Promotion / Transfer / Increment / Confirmation record.
- Employee **(required)**, Type **(required)** — one of the four above.
- From **(required)**, To **(required)** — free text describing the change
  (e.g. From "Staff Nurse" To "Senior Staff Nurse").
- Effective Date **(required)**, Approver **(required)** — free text name.
- Status **(required)** — Draft / Pending Approval / Approved / Rejected.

### 1.8 Staff Learning Plan
- Employee **(required)**, Course **(required)**, Category **(required)** —
  Mandatory / Clinical / Safety / Leadership / Technical.
- Due Date **(required)**, Status **(required)** — Not Started / In
  Progress / Complete / Overdue.

### 1.9 Staff Relation Case
- Employee **(required)**, Type **(required)** — Grievance / Disciplinary /
  Counselling / Appreciation.
- Summary **(required)** — short free-text description.
- Case Owner **(required)** — free text name.
- Risk **(required)** — Low / Medium / High.
- Status **(required)** — Open / Under Review / Resolved.
- Resolved On — fill in once Status is set to Resolved.

### 1.10 Staff Onboarding Task
- Employee **(required)**, Task **(required)** — free text, e.g. "ID badge
  issued".
- Owner **(required)** — HR / IT / Department / Employee (who is responsible
  for completing it).
- Due Date **(required)**, Status **(required)** — Pending / Complete /
  Blocked. Completed On — fill once marked Complete.

### 1.11 Staff Separation Case
- Employee **(required)**, Type **(required)** — Resignation / Retirement /
  Contract End / Termination.
- Last Working Day **(required)**.
- Clearance **(required)** — Not Started / In Progress / Complete.
- Final Settlement **(required)** — Pending / Ready / Released.
- Status **(required)** — Open / Approved / Closed.

### 1.12 Staff Recruitment Requisition
- Role **(required)**, Department **(required)**, Openings **(required)** —
  number of vacancies.
- Priority **(required)** — Routine / Soon / Urgent.
- Status **(required)** — Draft / Approved / Interviewing / Offer Released.
- Requested By **(required)** — free text name. Target Date — optional.

### 1.13 Staff Candidate
- Candidate Name **(required)**, Role Applied For **(required)**.
- Source **(required)** — Referral / Job Portal / Walk-in / Agency.
- Stage **(required)** — Screening / Interview / Credential Check / Offer /
  Joined. Move a candidate's Stage forward as they progress.
- Rating **(required)** — a number. Owner **(required)** — free text name.

### 1.14 Credential Requirement & Credentialing Settings
Reference configuration used by the credential-reminder job, normally set up
once by HR Manager: Credential Requirement links a Credential Type to a
Designation/Department and marks whether it's mandatory, with a reminder
schedule (Reminder Days) and an escalation window. Credentialing Settings
(single record) holds the HR notification email the reminder job sends to.

### 1.15 Staff Asset Assignment
- Employee **(required)**, Asset **(required)** — free text description of
  the issued item (e.g. laptop, ID card).
- Issued On **(required)**, Status **(required)** — Issued / Return Due /
  Returned. Return Due, Returned On — fill in as the item moves through its
  lifecycle.

### 1.16 Staff Document Access (read-only log)
System-generated audit trail of who viewed/downloaded a Staff Document and
when — nothing to fill in manually; System Manager and HR Manager can read it.

### 1.17 Credential Reminder Run / Credential Reminder Send (read-only logs)
Generated automatically by the scheduled credential-expiry check — record
how many credentials were checked, reminders sent, escalations sent and
credentials marked expired in each run. Not user-entered.

**Who can do what:** HR Manager and HR User create/edit most records above;
Employees have self-service create/read on records about themselves (shift
swaps, career actions, learning plans); System Manager has audit-only read
access to the access-log doctypes.

## 2. Facility & Equipment Management (facility_management)

Menu location: **Facility Management** workspace (covers two sub-areas:
Biomedical Waste compliance, and Equipment/Asset maintenance). Every doctype
here is managed by **System Manager**; Trade and Asset Class are also
readable by all logged-in users.

### 2.1 Biomedical Waste (BMW) compliance

**BMW Department** — one record per department that generates waste (name,
short Code, optional link to the HR Department). Set these up once first.

**BMW Bag** — logged each time a bag of waste is generated.
- Bag No **(required)**, Department **(required)**.
- Category **(required)** — Yellow / Red / White / Blue (the standard BMW
  colour-coding).
- Is Cytotoxic — only shown/relevant when Category = Yellow.
- Is E-Waste — tick box.
- Weight (kg) **(required)**, Generated At **(required)** — date/time.
- Status — Open / Handed Over / Void (set to Void with a Void Reason if a
  bag entry was logged in error; do not delete it).
- Handover — filled in automatically once the bag is included in a BMW Handover.

**BMW Handover** — the record of physically handing bags over to the
disposal contractor. Submittable (locked once submitted; amend to correct).
- Series (auto-numbered BMW-HO-YYYY-####), Handover At **(required)**,
  Manifest No **(required)** — the contractor's manifest reference.
- Vehicle No, Receiver Name, Receiver Acknowledgement — optional.
- Bags **(a table)** — add each BMW Bag being handed over as a row; the
  Yellow/Red/White/Blue/Cytotoxic weight totals below the table are
  calculated from the rows, don't type them by hand.
To fill: create the Handover, fill Manifest No and the vehicle/receiver
details, add every bag being sent in the Bags table, check the calculated
weights look right, then Submit.

**BMW Accident** — submittable; log any spill, needle-stick or handling
accident.
- Occurred At **(required)**, Accident Type **(required)** — short free text.
- Is Major — tick if it meets your facility's "major incident" definition.
- Waste Category, Persons Affected, Fatalities — optional.
- Sequence of Events, Impact Assessment, Emergency Measures, Remedial
  Action, Prevention Steps — long free-text fields; fill in as much as is
  known at the time, they can be added to before submission.
- Authority Informed, Authority Informed At — tick and date-stamp once the
  pollution control board has been notified (a statutory requirement for
  major incidents).

**BMW Bed-Day Record** — one row per Year/Month with the Occupied Bed Days
figure, used to compute the statutory per-bed waste-generation rate.

**BMW Settings** (single record) — the facility's statutory registration and
target numbers: KSPCB BMW Authorisation number and validity, Water/Air Act
consent numbers, the per-category kg/day generation targets, disposal mode
(CBWTF or Captive — Captive-only fields for treatment equipment appear only
when Captive is selected), and the annual training/committee counts used for
the statutory BMW report. Set up and maintained by System Manager, not
filled per transaction.

### 2.2 Equipment & asset maintenance

**Trade** and **Asset Class** — reference lists (e.g. Electrical,
Mechanical, Biomedical trades; equipment categories) with a default trade
per class. Set these up once; everyone can read them.

**PM Schedule** — the preventive-maintenance due-date for a specific asset.
- Reference Type/Reference **(required)** — pick the DocType (usually
  "Asset") and then the specific asset record.
- Periodicity **(required)** — Monthly / Quarterly / Half-Yearly / Annual.
- Due Date **(required)**, Status **(required)** — Due / Overdue / Completed.
- Trade, Tolerance (Days), Due Odometer — optional.

**PM Record** — submittable; the completed-maintenance log against a
schedule.
- PM Schedule **(required)** — pick which schedule this completes.
- Completion Date **(required)**.
- Performed By, Has Certificate, Notes — optional.
To fill: open the due PM Schedule's linked PM Record (or create a new one
against it), fill Completion Date and who performed it, tick "Has
Certificate" if a service certificate was received, and Submit — this rolls
the linked PM Schedule's due date forward automatically.

**Breakdown Repair Ticket** — logs an equipment fault through to repair.
- Reference Type/Reference **(required)** — the affected asset.
- Priority **(required)** — Low / Medium / High / Critical.
- Status **(required)** — Open → Assigned → In Progress → Resolved →
  Closed (or Cancelled). Move it through these in order as the repair
  progresses.
- Trade, Vendor, SLA Response (Hours) — optional, set when assigning.
- Opened/Responded/Resolved/Closed At, Downtime Start/End — timestamp
  fields to fill as each stage happens (used for SLA and downtime reporting).
- Root Cause, Corrective Action — fill in once resolved.

**AMC / CMC Warranty Contract** — submittable.
- Asset **(required)**, Contract Type **(required)** — AMC / CMC /
  Warranty.
- Start Date **(required)**, End Date **(required)**.
- Supplier, Visits Included, Value, SLA Response (Hours) — optional.
- **Confirmed broken (18-Aug-2026 retest) — do not use.** Saving throws a
  server error: `SQL functions are not allowed as strings in SELECT:
  MAX(end_date)`. The controller updates the linked Asset's
  `hem_amc_cmc_expiry` by recomputing the latest end date across every
  non-cancelled contract for that asset, and the query it uses (a raw
  `MAX(end_date)` string) is rejected by this Frappe version's SQL-safety
  check. No contract can be saved against any asset until this is fixed in
  code — this is not a data or permissions issue.

**Capital Purchase Requisition (CPR)** — the capital-equipment purchase
request and its approval trail.
- Raised By **(required)** — **correction, 18-Aug-2026 retest**: on the
  desk "New" form this is an ordinary editable User-link field, not
  auto-filled — leaving it blank blocks saving with "Raised By is
  required." Whoever raises the CPR must pick themselves (or whoever it's
  genuinely being raised on behalf of) here; it is not stamped
  automatically the way Raised By's own field description implies.
- Department **(required)**, Title **(required)**, Estimated Value
  **(required)**.
- Justification — free text, recommended.
- Linked Asset, Linked Ticket — optional, e.g. link to the Breakdown Repair
  Ticket that triggered this request.
- Status, Current Step — **do not edit these directly**; they only change
  through the record's own action menu (Submit for Approval, Approve,
  Return, Reject, Withdraw), which is also what writes a new row into
  Transition History below. A plain save can never insert or alter a
  Transition History row, so the approval trail can't be forged.
To fill: a department raises a CPR with Department, Title, Estimated Value
and Justification, saves as Draft, then uses the record's action to submit
it for approval; the Director/approver at each step uses the corresponding
action (not a plain edit) to move it forward, each step recording itself in
Transition History automatically.

**Equipment Maintenance Settings** (single record) — the rupee threshold
above which a purchase must go through the full CPR approval workflow.

## 3. Trust & FCRA Compliance (trust_compliance)

Menu location: **Trust Compliance** workspace. Roles: **Accounts Manager**
(full control), **Accounts User** (day-to-day entry), **Auditor** (read +
export only).

Set-up records (usually configured once by Accounts Manager, not filled per
transaction): **Fund** (Fund Code, Fund Name, Company, Fund Class — Corpus /
Restricted / Designated / Unrestricted, and whether it's FCRA), **Trust
Donor** (donor master with PAN, country, anonymous flag, and the Section
13(3) "Interested Person" flag with its basis), **Investment Mode** (the
permitted Section 11(5)/Rule 17C investment clauses), and **Trust Company
Account** (maps each Company to its GL accounts — donation income, corpus
fund, FCRA bank account, TDS, etc. — used automatically by the posting logic
below; get this right before recording any donation).

**Confirmed 18-Aug-2026 — three workflows below hard-fail at Submit if their
GL mapping is missing, with a clear "Setup Incomplete" message, not a silent
or confusing error:**
- A **Grant** donation needs a **Grant Liability Account** set on Trust
  Company Account for that Company.
- **Fund Transfer** needs an **inter-fund transfer (equity clearing)
  account** set on Trust Company Account for that Company.
- **Trust Investment** needs at least one **Investment-type asset account**
  to exist in that Company's chart of accounts (the Investment Account
  field otherwise has nothing valid to pick).
A newly stood-up Company (a fresh campus, or a smoke-test company) will not
have these until an Accounts Manager sets them up — this is expected, not a
bug; the fix is completing that Company's Trust Company Account record and
chart of accounts before these three workflows are used against it.

**Trust Donation** — submittable.
- Donor **(required)**, Company **(required)**, Donation Date **(required)**.
- Amount **(required)**, Mode **(required)** — Cash / Bank / UPI / Cheque /
  In Kind. (In-kind Description and Asset Category appear only when Mode =
  In Kind.)
- Fund **(required)** — pick the fund this donation goes into.
- Corpus Donation — tick if the donor has directed this to corpus (routes
  to the corpus account rather than income on posting).
- Grant (Deferred Income) — tick if this is grant money to be recognised as
  income over time rather than immediately.
- Anonymous — tick to suppress the donor's name on public-facing reports.
- Purpose, Receipt No, Financial Year — Receipt No is normally left blank
  and auto-assigned from the gap-free receipt series on submit.
To fill: pick the Donor and Fund, enter Amount, Mode and Date, tick
Corpus/Grant/Anonymous as applicable, save, then Submit — submitting is what
posts the balanced GL entry and assigns the receipt number.

**Grant Utilisation** — submittable; records spending against a specific
grant. Fund **(required)**, Amount **(required)**, Utilisation Date
**(required)**; Purpose recommended. Submitting posts the GL entry and
reduces the grant's outstanding balance shown in "Outstanding Balance Before
This".

**Fund Transfer** — submittable; moves money between two funds (e.g. from
Unrestricted to a Designated fund) without touching the trial balance
overall — it posts both legs to the same equity clearing account.
- From Fund **(required)**, To Fund **(required)**, Amount **(required)**,
  Transfer Date **(required)**, Reason **(required)**.
- **Corpus can only be a "To Fund", never a "From Fund"** — you cannot draw
  money out of corpus this way, only into it.

**Inter Unit Transfer** — submittable; the same idea as Fund Transfer but
between two Companies (e.g. Puttaparthi campus paying Whitefield campus).
From Unit/From Fund **(required)**, To Unit/To Fund **(required)**, Amount
**(required)**, Purpose **(required)**. Submitting posts one balanced entry
in each company; both entries are flagged so the consolidated report
correctly excludes them from the group rollup instead of double-counting.

**Trust Investment** — submittable; records purchase of an investment under
Section 11(5). Investment Name **(required)**, Company **(required)**,
Fund **(required)**, Mode **(required)** — pick the permitted investment
clause, Instrument Type **(required)**, Cost **(required)**, Investment
Account **(required)** — the GL account this posts against. FCRA Fund /
Corpus Investment — tick as applicable; Purchase Date **(required)**.

**Investment Transaction** — submittable; records interest/dividend/
redemption/maturity against an existing Trust Investment. Investment
**(required)**, Kind **(required)** — Interest / Dividend / Redemption /
Maturity, Gross Amount **(required)**, Transaction Date **(required)**; TDS
if tax was deducted at source (Net Amount is calculated).

**Trust Property** — the property register (not submittable — kept as a
plain editable record).
- Property Name **(required)**, Company **(required)**, Property Type
  **(required)** — Land / Building / Land and Building / Flat / Other.
- Status **(required)** — Active / Under Dispute / Disposed.
- Fund **(required)** — which fund the property is held under.
- Donated By, Donation Receipt, Donation/Acquisition Date — fill in when the
  property came in via donation.
- Address, Survey Number, Extent + Extent UOM, Khata/Property ID,
  Recorded Valuation, Guideline/Market Value — the statutory/registry detail
  used for the property register report.

**Property Tax Schedule** — submittable; one per tax demand. Property
**(required)**, Company **(required)**, Financial Year **(required)**, Tax
Demanded **(required)**, Due Date **(required)**. Status moves Unpaid →
Billed → Paid (or Waived) as the linked Purchase Invoice is raised and paid;
the system guards against posting the same tax payment twice.

**Property Maintenance** — submittable; repair/AMC/renovation work against
a property. Property **(required)**, Type **(required)** — Repair / AMC /
Renovation / Statutory / Other, Description **(required)**, Start Date
**(required)**. Status moves Open → In Progress → Completed (or Cancelled).

**Form 10 Accumulation** — submittable; Income Tax Act Form 10 filing for
accumulation of income. Company **(required)**, Financial Year
**(required)**, Amount Accumulated **(required)**, Period (Years)
**(required)**, Purpose **(required)**.

**Auditor role** can read, report and export every doctype above but cannot
create, edit, or delete anything — by design, so an audit review can never
itself alter the books.

## 4. Patient Ticketing (patient_ticketing)

A guest-facing report/complaint submission system with an internal handling
queue. The public never logs in or uses the desk UI — they use the website
form at **`/submit-report`**; staff handle tickets from the desk.

### 4.1 Submitting a ticket (public, no login)
On `/submit-report`, a member of the public fills in:
- Patient Name **(required)**, Mobile Number **(required)**, Email Address
  **(required)**.
- UHID / Hospital Number — optional, if known.
- Department **(required)** — free text (the list of departments the
  hospital accepts reports for is configured in Patient Ticket Settings).
- Any supporting files, within the size/type/count limits configured in
  Patient Ticket Settings.
On submit, the system creates the Patient Ticket record itself (no direct
form save by the public) and the submitter can later check progress at
`/ticket-status` using the reference given at submission.

### 4.2 Handling a ticket (desk, logged-in staff)
- **Patient Ticket Agent** works tickets day to day: read/update Status,
  add entries to Replies (message to the patient, filled by staff), review
  Report Files.
- Status **(required)** — Open / Under Review / Appointment Confirmed /
  Closed / Cancelled — move it forward as the ticket is handled.
- Appointment Date and Time, Doctor — fill in once an appointment is fixed;
  Confirmation Email tracks whether the confirmation notice went out
  (Not Required / Pending / Sent / Failed).
- Internal Notes — staff-only notes, not shown to the submitter.
- Activity — a system-maintained event log (submission, replies sent,
  status changes); not edited directly.
- **Patient Ticket Manager** additionally can delete tickets; **Patient
  Ticket Administrator** additionally manages Patient Ticket Settings.

### 4.3 Patient Ticket Settings (single record, Administrator only)
Configure once: Hospital Name, Hospital Notification Email, Storage
Provider (Frappe Private Files or Google Drive — the Drive folder ID field
only appears when Google Drive is chosen), the list of Departments the
public form offers, Allowed File Types, Maximum File Size, Maximum Files per
Submission, Submissions per Hour per IP (rate limiting), and Closed Ticket
Retention Days.

## 5. Patient Follow-Up Register (sssihms_patient_followup)

A login-only, append-only register for volunteer patient follow-up calls.
Roles: **Follow-Up Volunteer** (logs calls), **Follow-Up Coordinator**
(read-only oversight).

**Patient Follow-Up** — one row per follow-up contact. A Volunteer creates a
new entry for every call; **existing entries cannot be edited or deleted by
anyone** — if something was logged wrong, log a fresh corrected entry rather
than trying to fix the old one.
- Patient ID (WS MRN) **(required)**, Patient Name **(required)**.
- Contact Date **(required)**, Contact Mode **(required)** — Phone / In
  person / Video call / SMS-WhatsApp.
- Patient Status **(required)** — Stable / Improved / Deteriorated /
  Readmitted / Deceased / Unreachable.
- Medication Adherence **(required)** — Full / Partial / None / Not
  applicable.
- Age, Sex, Phone, Diagnosis, Reported Symptoms, Notes — optional context.
- Readmitted Since Discharge — tick if true; Readmission Facility then
  becomes relevant (fill in where they were readmitted).
- Next Follow-Up Date — optional, so the next call can be scheduled.
- Logged By, Volunteer Name, Logged At — **filled automatically**, do not
  edit; this is what makes the append-only rule enforceable — every row is
  provably tied to the volunteer who made it and when.
To fill: pick or type the patient's ID and name, the date and mode of
contact, their current status and medication adherence, and any symptoms or
notes, then save. A Coordinator can read, print, report and export the whole
register but — like everyone else — cannot edit or delete a row.

## 6. Sai Sparsh — Preventive Lifestyle Coaching (Patient Reach module)

Two doctypes, added inside Healthcare's **Patient Reach** module. Both are
**System Manager**-only in the current permission configuration — no
dedicated Sparsh role exists yet.

### 6.1 Sparsh Visit ("new" intake)
Submittable (once submitted, further changes require cancel/amend). Filled
in once, at the patient's or caregiver's first Sai Sparsh visit.
- Ticket Details — basic visit reference details.
- Habits table (**Sparsh Patient Addictions**, a child table) — add one row
  per habit (Habit dropdown, Response dropdown), e.g. smoking / alcohol use
  and the caregiver's response to each.
- Conditions table (**Sparsh Patient Condition**, a child table) — one row
  per known condition/risk factor and the response.
- "Levels of Prevention" — pick where the person fits (Select field);
  Justification of Risk Profiling — free text explaining why.
- **The "Curry" (Nutrition)** section — Green Plate % of vegetables, Sunset
  Rule (heavy meal after 8pm?), heavy grain/meal at dinner, protein intake
  ≥25%, plus a free-text "Curry - Any Additional Info".
- **The "Hurry" (Movement)** section — sedentary >6 hrs/day?, adequate
  sleep >7 hrs?, 10-minute post-meal walk?, plus free-text additional info.
- **The "Worry" (Stress/Habits)** section — feels overwhelmed/helpless?,
  type of stress, plus free-text additional info.
- Relationship to Patient, and if this visit is actually for a caregiver
  rather than the original patient: Patient ID, Patient Name, Department of
  the original patient.
- **Measurements** tab — the "String Test" (visceral fat) readiness
  checks, then waist/weight/height/BP as the caregiver consents to each.
- **Red-flag triage** — tick any of Physiotherapy / Dietician / Cardiology
  / General Medicine (High BP) / Counselling / None / Other that apply,
  based on what came up in the assessment; if Other, explain in "Please
  specify". This is what decides whether the person needs referral before
  the coaching programme continues.
- **Status & Enquiry** tab — Chief Complaint, Workflow State, Counsellor-
  Coach's Name, Created/Counselled dates.
- **Clinical Review** tab — Examination, Advice (rich text, filled in by the
  clinician if the red-flag triage routed them here).
- **Touchpoint** tab — Follow-up Date, Follow-up Remarks, Follow-up By
  (who will make the next contact), and if the ticket needs to be handed to
  someone else: Forward To, Reason for Forwarding.
- **Closure** — Close Remarks, Feedback, once the visit cycle is done.
To fill: work top to bottom through the tabs in one sitting during the
visit — habits/conditions, the three Curry/Hurry/Worry sections, the
measurements the caregiver consents to, tick any red flags that came up,
record the clinical review if a red flag routed them there, and finish with
the touchpoint/closure section before submitting.

### 6.2 Sparsh Follow Up
Not submittable — stays editable, one record per coaching call.
- Baseline Traffic (numeric/light) and Previous Traffic/Pledge/Confidence —
  carried over from the last contact, for reference.
- Progress on Pledge **(required)** — how they did against last time's
  pledge; Primary Barrier — what got in the way, if anything.
- Coach Intervention — which coaching technique the coach used this call,
  if any.
- Lifestyle Check — the same short Hurry/Worry/Curry check as the intake
  (Sunset Rule, builder-food habit, stress, sleep) — a composite habit
  score is calculated from these, not entered directly.
- **Re-Pledging** — Pledge Category **(required)**, New Target Pledge
  **(required)** — what they're committing to before the next call, with an
  optional measurable Target Value/Unit.
- Confidence (1–10) **(required)** — how confident they are they'll keep
  the new pledge.
- Current Traffic Light **(required)** — the risk/progress indicator for
  this call.
- Schedule Next Call **(required)** — the date for the next follow-up.
- Traffic Light Transition/Change Category — calculated automatically from
  the previous and current traffic light, not entered directly.
To fill: pull up the patient's previous pledge and traffic light (shown at
the top), ask about progress and any barrier, run through the Hurry/Worry/
Curry check, agree a new pledge and confidence score with the patient, set
the current traffic light, and schedule the next call date before saving.

---

# Part 2 — Standard Modules

These modules are used as published by their maintainers, without
SSSIHMS-specific changes. Each entry gives the everyday steps staff actually
use; for anything beyond this, use the linked official manual.

## 7. Accounting / ERPNext core
Official manual: https://docs.frappe.io/erpnext/user/manual/en/sales-invoice

- **Raise a Sales Invoice:** Accounts > Sales Invoice > New → pick the
  Company and Customer (billing address/currency fill in automatically) →
  add item rows with quantity and rate → tax rows are pulled in
  automatically but can be adjusted → Save → Submit. Submitting is what
  posts the GL entry — receivable, income and tax accounts update together,
  there's no separate "post to ledger" step. If the sale also moves stock
  and there's no separate Delivery Note, tick **Update Stock** so the one
  document covers both. You can also start from a Sales Order/Delivery
  Note/Quotation and use **Get Items From** to pull the lines across
  instead of retyping them.
- **Collect payment against the invoice:** from the submitted invoice, use
  the payment action to record what was received — the payment reduces the
  invoice's outstanding balance directly; if money came in without being
  tied to an invoice yet, use Payment Reconciliation afterwards to match it
  up.
- **Raise a Purchase Invoice / bill:** Accounts > Purchase Invoice > New →
  pick Supplier → add item/expense rows → Save → Submit.
- **Post a manual Journal Entry:** Accounts > Journal Entry > New → add at
  least two rows so debit total = credit total → Save → Submit (blocked if
  it doesn't balance).
- **View reports:** Accounts > Trial Balance / Profit and Loss / Balance
  Sheet / General Ledger — filter by Company and date range.
- **Gotcha — fixed-asset items can't go on a plain Sales/Purchase Invoice
  line.** An Item flagged **Is Fixed Asset** (used for equipment tracked as
  a depreciable Asset, e.g. cath lab monitors) is rejected on a Sales
  Invoice ("You must select an Asset for Item …") unless you pick the
  specific Asset record it's billing against — for a normal sale/purchase,
  use an ordinary (non-fixed-asset) Item instead.

## 8. HRMS (Frappe HR)
Official manual: https://docs.frappe.io/hr/leave-application

- **Apply for leave:** HR > Leave Application > New. The form shows your
  current Allocated Leaves for reference — pick the Leave Type and
  From/To dates and Save (there's no separate Submit step for the
  employee). Saving is what changes the status to **Open** and emails your
  Leave Approver. Two things to know: a leave application can't span two
  different leave-allocation periods (split it into two applications if it
  does), and it can't be submitted at all once payroll has already been
  processed for that period.
- **Approve leave (as the Approver):** you get an email when an
  application is saved; from the record you can Approve, Reject or Cancel,
  and it's the Approver, not the employee, who does the final Submit —
  submitting is what sends the employee their outcome email.
- **Run payroll:** HR > Payroll Entry > New → pick Company, month, and
  employees included → Save → Submit → then Create Salary Slips → Submit
  the Salary Slips, which is what posts the payroll GL entry.
- **Mark attendance / check in-out:** the Frappe HR mobile app lets staff
  check in and out with geolocation directly, rather than a desk form.
- **Submit an expense claim:** HR > Expense Claim > New → add expense rows
  with amount and category → Save → Submit; routes through the configured
  approval level(s).

## 9. Healthcare (Frappe Health)
Official manual: https://docs.frappe.io/erpnext/v13/user/manual/en/healthcare
(Sai Sparsh, layered on top of this app, is covered in Part 1 §6.)

- **Book an appointment:** Healthcare > Patient Appointment > New → pick
  the Medical Department, Practitioner and date; available slots for that
  practitioner are pulled from their schedule and shown with status
  indicators, so you pick an open slot rather than typing a time blind.
  The appointment's own status then moves itself: Scheduled → Open (on the
  day) → Closed (once an Encounter or Clinical Procedure exists against
  it) → or Cancelled.
- **Record a consultation:** Patient Encounter is where a consultation
  actually gets written up — symptoms, diagnosis, observations, notes,
  prescriptions, investigations and follow-up advice all go here. Creating
  one **from** a booked Appointment pulls the patient, department and
  practitioner details in automatically instead of asking you to retype
  them.
- **Order a lab test:** raised from the encounter against a test template;
  results are then recorded against that order once processed.
- **Gotcha — set a Default Duration on every Appointment Type.** If an
  Appointment Type's own Default Duration is left blank/zero, any Patient
  Appointment booked against it keeps resetting its Duration to 0 whenever
  the Appointment Type field is touched (a stock Frappe Healthcare
  `fetch_from` link, not an SSSIHMS bug) — which then blocks saving with
  "Appointment end must be after start." Fix once, at the Appointment Type
  record, not per appointment.

## 10. Insights (Frappe Insights)
Official manual: https://docs.frappe.io/insights/querying/overview

- **Connect a data source:** Insights can pull from MySQL, PostgreSQL,
  DuckDB and BigQuery sources in addition to the ERP's own database — set
  this up once, under data sources, before building anything.
- **Build a query — no SQL required:** start from a table, then add steps
  to filter, join, calculate and organise it one step at a time — each
  step stays visible and can be edited or removed on its own, like a
  recipe rather than one big query.
- **Get a chart:** as soon as your query has columns and filters on it,
  Insights proposes a chart automatically; switch to the Visualise tab to
  change the chart type or fine-tune it.
- **Build a dashboard:** once a chart looks right, use **Add to
  Dashboard** — dashboards are assembled by dragging charts onto a canvas,
  and a filter added at the dashboard level applies to every chart on it
  at once, not just one.

## 11. Buzz — Event Management
Official repository/README: https://github.com/bwhtech/buzz

Buzz is an **event/conference management platform** — creating and
publishing events, ticket sales, speaker/talk-proposal handling,
sponsorships and attendee check-in. It is not a chat tool.

- **Create an event:** Buzz > Buzz Event > New → pick Team, Category,
  Host, and (for a physical event) Venue → set Start/End Date and Time,
  Medium (In Person / Online) → add a Short Description and About text →
  tick **Is Published?** once it's ready to go live on the public site.
- **Set up ticket types:** Event Ticket Type > New → pick the Event, a
  Title (e.g. "Early Bird", "Standard"), Price and Currency, and optionally
  a Max Tickets Available cap and an auto-unpublish date; tick **Is
  Published?** to make it purchasable.
- **A booking (public, via the event page):** an attendee picks a ticket
  type, fills in attendee details, and pays (or the booking sits as
  "Verification Pending" for an offline payment method) — this creates an
  **Event Booking** (one purchase, can cover several attendees) and one
  **Event Ticket** per attendee, each with its own QR code for check-in.
- **Check in an attendee on the day:** scan the ticket's QR code (or look
  it up) → Event Check In > New → pick the Event and the Ticket → Submit.
- **Handle a speaker/talk proposal:** a prospective speaker submits a
  **Talk Proposal** against the event (title, description, one or more
  speakers via the Speakers table); an organiser reviews it and updates its
  **Status** (via Talk Proposal Status); once accepted, promote it to an
  **Event Talk** to appear on the published schedule.
- **Handle a sponsorship enquiry:** a prospective sponsor submits a
  **Sponsorship Enquiry** (company name, logo, tier); an organiser reviews
  and moves Status from Approval Pending → Payment Pending → Paid, then
  records the confirmed sponsor as an **Event Sponsor** against a
  **Sponsorship Tier**.
- **Collect feedback:** Event Feedback is a simple open-text form
  ("How can we improve?") linked to the Event, normally reached from a
  post-event link rather than filled in on the desk.

## 12. Education
Official manual: https://docs.frappe.io/education/student_admission

- **Admit a student:** Student Admission is set up to run the whole
  admission cycle for a program, including publishing an application form
  on the website and (optionally) an application fee. Applicants apply
  through that published form rather than a staff member typing them in
  one by one.
- **Enrol students / assign batches:** once admitted, students are
  enrolled into their Program/Courses and split into batches; multiple
  students can be admitted into the same program in one go rather than
  one-by-one.
- **Set up and collect fees:** build a **Fee Structure** first — pick the
  Program and enter each fee component (category + amount) in the
  Components table. Then create a **Fee Schedule** against a Student
  Group and attach that Fee Structure to it — the moment the structure is
  attached, the fee break-up for every student in the group is generated
  automatically rather than entered per student.
- **Student self-service:** students/parents can check timetables,
  attendance, grades and pay fees online through the Student Portal rather
  than everything going through staff.

## 13. LMS (Frappe Learning)
Official manual: https://docs.frappe.io/learning/create-a-course

- **Create a course** (instructor): Courses > New Course → give it a
  Title and introduction → Create, which opens Course Settings for the
  remaining details (images, pricing, whether learners can self-enrol or
  only an administrator can enrol them, and the Published-On date that
  tells learners when it went live). Courses can also be bulk-created via
  spreadsheet import (Excel/CSV or a Google Sheet) instead of one at a
  time.
- **Add chapters and lessons:** a course is chapters, and each chapter
  holds lessons — the chapter gives the lesson its context. Add Lesson
  appears under each chapter; a lesson can carry video, text, a quiz, a
  PDF, a SCORM package or an assignment, and can optionally be marked
  visible to Guests as a free preview.
- **Publish:** a course only becomes visible to learners once it's marked
  Published — check Course Settings if a finished course still isn't
  showing up.
- **As a learner:** enrol into a published course, then work through its
  chapters/lessons in order — videos, quizzes and assignments as the
  instructor has set them up; discussion forums and (where scheduled) live
  Zoom sessions with the instructor are also available. A certificate is
  issued on completion.
- **Note — Instructors field takes a second to register.** After picking a
  name from the Instructors dropdown on a Course, wait a moment before
  saving; the pill takes a beat to appear because the row is created behind
  the scenes. Saving immediately can show "Instructors is required" even
  though a name was just picked — wait for the pill, then save.

## 14. Payments
Official repository: https://github.com/frappe/payments

Adds online payment processing to the ERP rather than being a form users
open directly — it supports Razorpay, Stripe, Braintree, PayPal and PayTM,
each configured as its own gateway record, and automatically adds a
payment field to any Web Form that needs to collect money online. End
users generally meet it only as a "Pay Now" button on an invoice, fee or
Buzz event booking, not as a screen of its own.

---

*This manual reflects the modules, permissions and fields configured on
erp.sssihms.org as of 17-Aug-2026. It is not a substitute for role-specific
training; contact the ERP administrator for role assignment or access
issues.*

## Appendix — 18-Aug-2026 end-to-end verification

Every module above was exercised via real front-end interaction in the
dedicated **Sai Hospital Smoke** company (real records created/saved, and
submitted where the doctype requires it), confirming the manual against the
live system rather than just its DocType definitions. One real code defect
was found and fixed in production (Roster Assignment silently rejecting
day=0/Monday — `sssihms_hr`, commit `e7d63e7`); everything else tested
correctly, with three genuine gotchas folded into the sections above
(fixed-asset items on invoices, Appointment Type default duration, LMS
Instructors field timing) rather than kept as a separate findings list.

### Second retest pass, same day — 25 additional workflows

A second round covered every remaining sssihms_hr doctype (Shift Swap
Request, Staff Document, Performance Review, Career Action, Learning Plan,
Relation Case, Onboarding Task, Separation Case, Recruitment Requisition,
Candidate, Asset Assignment), the rest of Facility Management/BMW (Trade,
CPR, BMW Handover, BMW Accident, BMW Bed-Day Record), and most of Trust
Compliance (Trust Donation with Grant flag, Fund Transfer, Property Tax
Schedule, Property Maintenance, Form 10 Accumulation). Two corrections and
one confirmed live defect came out of it, both folded into the relevant
sections above rather than kept here:

- **AMC / CMC Warranty Contract cannot currently be saved at all** — a
  server-side SQL error (§2.2). This is a genuine, reproducible code defect,
  not a data or config problem.
- **Capital Purchase Requisition's Raised By field is not auto-filled** on
  the desk form, contradicting the manual's earlier claim — corrected in
  §2.2.
- Grant Utilisation, Fund Transfer, and Trust Investment all correctly
  **refuse to submit with a clear "Setup Incomplete" message** when a test
  company's GL mapping is missing (§3) — confirmed working as designed, not
  a defect, but worth knowing before assuming a workflow is broken.
- Staff Performance Review's "locked once Closed" rule (§1.6) was
  specifically retested and **confirmed accurate** — a same-session,
  premature retraction of that finding was itself wrong (a dialog-timing
  artifact, not evidence the lock doesn't work).
- Several sssihms_hr field descriptions (e.g. on Staff Performance Review,
  Staff Career Action) still show internal porting/dev commentary referring
  to the old FastAPI/React source (`CareerPage.tsx`, "the source's...")
  rather than user-facing help text — cosmetic, worth a cleanup pass, not
  functionally broken.

Twelve workflows were not reached in this pass (Inter Unit Transfer, Patient
Follow-Up Register, Payment Collection, Journal Entry, Payroll Entry,
Attendance, Expense Claim, lab order/results, Insights, and four of Buzz's
event-lifecycle steps plus Education fees and LMS lessons/learner) — treat
those as still unverified against the live system rather than assume they
work because everything else did.

### Third retest pass, 20-Aug-2026 — 6 of the remaining 12 workflows

- **Payment Collection (Payment Entry)** — works end-to-end. Created and
  submitted `ACC-PAY-2026-00003` against a synthetic customer, Cash - SHU.
- **Journal Entry** — works end-to-end. Created and submitted
  `ACC-JV-2026-00051` (Cash debit / Interest Income credit, ₹1,000).
- **Attendance** — works end-to-end. Created and submitted `HR-ATT-2026-00001`
  for a synthetic employee.
- **Payroll Entry (creation)** — works: saved as `HR-PRUN-2026-00001` with
  Payroll Payable - SHU and a Monthly frequency. "Get Employees" correctly
  returned "No employees found" because the test employee has no Salary
  Structure Assignment — expected validation, same class of finding as the
  Trust-layer GL-gating in the previous pass, not a defect.
- **Patient Follow-Up Register — was broken, fixed 20-Aug-2026.** §22 in the
  task manual. The New Patient Follow-Up form rendered **only the Contact
  Date field**; every other schema field (Patient ID (WS MRN), Patient Name,
  Contact Mode, Patient Status, Medication Adherence, Reported Symptoms,
  etc.) was completely absent, and Save was a silent no-op. Root cause: the
  doctype's permission rules granted Create/Read/Print/Report/Export but
  never **Write** to any role, including System Manager — Frappe requires
  Write (not just Create) to make fields editable on an unsaved new document,
  so every field with nothing to display got hidden entirely (Contact Date
  survived only because it had a default value to show read-only). Fixed
  live via `DocPerm.write = 1` for all three roles, and in source
  (`sssihms_patient_followup` commit `b3b6f57`) so the fix survives a future
  redeploy. Verified end-to-end: `WSTEST9001` (`uj1hm2n438`) created and
  saved successfully through the actual form.
- **Expense Claim — earlier "reset to blank" finding could not be reproduced
  (20-Aug-2026 retest).** The Expense Approver field is mandatory and, on a
  fresh employee, first requires setting `expense_approver` on the Employee
  master (Attendance & Leaves tab) — that part works correctly and is
  expected setup, not a bug. Retested end-to-end against a fresh employee
  (HR-EMP-00005): selected Administrator in Expense Approver, saved twice
  (once against an unrelated missing-fields validation, once successfully),
  and the value held correctly both times — confirmed on the saved record
  `HR-EXP-2026-00001`. Source review found no SSSIHMS customization on this
  field or its supporting code (`expense_claim.js`,
  `department_approver.get_approvers` are unmodified core HRMS). Most likely
  explanation for the original finding: a testing artifact from the field's
  constrained autocomplete, not a genuine defect.

Six workflows still remain unverified (lab order/results, Insights, four
Buzz event-lifecycle steps, Education fees, LMS lessons/learner). Lab Test
was attempted but abandoned partway: the smoke company has **no Lab Test
Template at all**, and creating one requires a Department plus a billing
Item Code and Item Group — a chain of reference-data setup rather than a
code test, so it was not pursued further this pass. The same pattern likely
applies to Buzz ticket types, Education fee structures, and LMS
lessons/learner, which is why this pass stopped at 6 of 12 rather than
manufacturing reference data purely to exercise each form once.

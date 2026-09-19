# LSS Bot ERP — Technical Blueprint

**Status:** proposal for approval. No ERP code has been written.
**Prepared against:** commit `51c1f85`, inspected 19 September 2026.
**Answers:** Master Specification §79 (items 1–51) and its closing question, "identify any significant School ERP requirement still missing".

Read Part 0 first. Everything after it follows from what is actually in the database
today, not from what the specification assumes is there.

---

## Contents

| Part | Covers | §79 items |
|---|---|---|
| 0 | What exists today — verified inventory | 1, 2, 3, 4, 8 |
| 1 | Foundations: identity, masters, numbering, RBAC, audit, events | 5, 6, 7, 10, 11, 12, 21, 39, 40, 41, 44 |
| 2 | Migration and backward compatibility | 9, 47, 48 |
| 3 | Module blueprints | 13–20, 22–38, 42, 43 |
| 4 | Cross-cutting: security, backup, testing, deployment, flags | 45, 46, 49, 50 |
| 5 | Recommended development phases | 51 |
| 6 | Gaps in the specification, and decisions needed | — |

---

## One concern, stated once

The specification describes roughly two years of work for a small team: seven major
domains (admissions, HR, payroll, attendance, examinations, fees, double-entry
accounting) plus reporting, RBAC and AI on top. It is coherent and it can be built as
written. What belongs on record before we start is that the **sequence** matters more
than the scope: if the foundations in Part 1 are not laid first, each later module
invents its own idea of what a "class" is, and the system becomes unfixable at about
module four. Part 5 sets that sequence. Nothing else in this document asks you to
reduce the scope.

---

# PART 0 — WHAT EXISTS TODAY

Verified by reading the code and querying a running instance of the schema. Row counts
below come from the **local development database**, which holds 6 users — it is not
production. Getting the real production inventory is step one of Part 2, and several
decisions here (duplicate handling, how much class-name cleanup is needed) cannot be
finalised until that report exists.

## 0.1 The stack (§79.1)

| Layer | What it is | Where |
|---|---|---|
| API | FastAPI, 16 routers, all under `/api` | [main.py](../backend-python/main.py) |
| ORM | SQLAlchemy 2.x async + asyncpg | [config/database.py](../backend-python/config/database.py) |
| Schema | PostgreSQL, 27 tables, 13 Alembic migrations | [alembic/versions](../backend-python/alembic/versions) |
| Background work | Celery + Redis | [celery_app.py](../backend-python/celery_app.py) |
| Files | MinIO (documents, recordings); local disk for submissions | [services/storage_service.py](../backend-python/services/storage_service.py) |
| Vectors | Milvus | [services/vector_service.py](../backend-python/services/vector_service.py) |
| Live classes | LiveKit, self-hosted | [services/livekit_service.py](../backend-python/services/livekit_service.py) |
| Frontend | React 18, Vite, Tailwind, React Router v6 | [frontend/src](../frontend/src) |

`init_db()` only verifies the connection — it does **not** call `create_all`. The schema
belongs to Alembic alone. That is the right foundation for an ERP migration, and we keep it.

## 0.2 Authentication (§79.2)

- JWT, HS256, payload `{id, exp}`, 7-day expiry — [middleware/auth.py:16](../backend-python/middleware/auth.py#L16).
- `get_current_user` decodes the token and re-loads the `User` row on **every** request, so a
  deactivated account stops working at its next call and a role change takes effect
  immediately. Nothing role-related is baked into the token. This is precisely what makes
  the RBAC upgrade in §1.5 safe to do without invalidating anyone's session.
- `require_roles("admin", …)` is a flat string comparison against `users.role`
  — [middleware/auth.py:142](../backend-python/middleware/auth.py#L142).
- Separate short-lived, purpose-scoped tokens already exist for browser-initiated media
  fetches (`create_scoped_token`). Good pattern — reuse it for voucher PDFs and payslips.
- Passwords are hashed; `must_change_password` is implemented and honoured by the frontend
  router. **First-login password change (§10) already works and does not need building.**

## 0.3 People (§79.3, §79.4)

There is **one** table for every human: `users` — [models/models.py:18](../backend-python/models/models.py#L18).

```
id (uuid string)   name   login_id (unique)   email   password_hash   role
class_name         section   father_name   subjects[]   assigned_classes[]
assigned_sections[]   is_active   must_change_password   last_login
```

- `role` is one of `student`, `teacher`, `admin`. (`principal` and `accountant` appear once
  each as string literals and are wired to nothing.)
- **Students:** `login_id` is the registration number; `class_name`, `section` and
  `father_name` are populated by the Excel importer
  — [services/student_excel_import_service.py](../backend-python/services/student_excel_import_service.py).
- **Teachers:** `login_id` is a registration number of the form `2024LSS001`;
  `assigned_classes`, `assigned_sections` and `subjects` are JSON arrays
  — [services/teacher_import_service.py](../backend-python/services/teacher_import_service.py).
- **18 tables carry 24 foreign keys to `users.id`.** Every one of them breaks if a user row
  is deleted or re-created. This is the concrete, database-level reason behind the
  specification's "never re-create accounts" rule — it is not merely a policy.

**Fields the ERP needs that exist nowhere today** (confirmed by search, not assumed):
GR No., Admission No., application and registration numbers as distinct fields, date of
birth, gender, B-Form/CNIC, contact number, address, photograph, admission date, previous
school, family or sibling link, guardian record, employee number, designation, department,
joining date, qualification, salary, bank details, employment status.

The only student identifier that exists is the registration number — and it is already
doing double duty as the login ID.

## 0.4 The central problem: class and section are free text

There is no `classes` table, no `sections` table, no `subjects` table and no
`academic_sessions` table. A class is a string, stored independently on **nine tables** —
`users`, `assignments`, `question_papers`, `lesson_plans`, `documents` (as `class_level`),
`online_class_schedules`, `online_class_sessions`, `online_class_participants` and
`ai_usage_events` — and those strings disagree with each other by design: students
carry `"Class 5"`, teachers are assigned `"Grade 5"`, and teacher sections are combined
strings like `"Grade 5 - A"`.

The system copes through a normalizer — `normalize_class()` in the importer, wrapped by
[services/class_matching.py](../backend-python/services/class_matching.py) — which is
already authorization-critical: it is what stops a student joining another section's
classroom. There is also a `curriculum_mappings` table, but it maps a class to a
*different class's books* (Pre-Board → Class 9 material); it is not a class master.

This is adequate for a chatbot and a classroom. It **cannot** carry fee structures,
promotion, examination rolls or report cards, because each of those must state "this
student, in this class, in this section, during this session" and get the same answer
twice. Fixing it is the highest-value foundation work, and §1.2 does it without changing
a single line of existing behaviour.

## 0.5 What already exists that the ERP spec asks for

Worth knowing before anyone rebuilds it:

| Spec asks for | Already built |
|---|---|
| First-login password change (§10) | `must_change_password` + `/auth/force-change-password` |
| Bulk student onboarding + credential sheets (§9, §10) | Excel importer, Celery-backed, with **rollback** and per-row error log |
| Approval workflow + audit trail for content (§43, §69) | `ReviewableMixin` + `content_revisions` + [services/audit_service.py](../backend-python/services/audit_service.py) |
| Attendance derived automatically (§33) | From LiveKit join/leave webhooks, with raw evidence retained — [services/attendance_service.py](../backend-python/services/attendance_service.py) |
| Teacher access follows assigned classes (§31) | `class_matching.teacher_may_teach` |
| Notifications (§74) | `notifications` table — in-app only |
| Document storage + conversion/OCR (§67) | MinIO + `document_service` + converter container |

The approval-and-revision pattern in `audit_service` is sound; Part 1 generalises it
rather than replacing it.

## 0.6 Two things to fix regardless of the ERP

1. **A production password is hard-coded in source and committed to git** —
   [main.py:78](../backend-python/main.py#L78) seeds `admin@lss.edu.pk` with a literal
   password. It must move to an environment variable, with `must_change_password=True`.
2. **The master specification document itself contains plaintext initial passwords** for
   the Owner, ERP Manager and Principal accounts. Those accounts will be seeded from
   environment variables and forced to change on first login. Treat the passwords printed
   in the specification as already compromised: change them at first login, and never
   reuse them elsewhere.

---

# PART 1 — FOUNDATIONS

Everything in Part 1 is additive. No existing table is dropped, no existing column is
removed or renamed, and no existing endpoint changes its response. That is what makes
§2 and §3 of the master specification ("protect the existing LSS Bot", "zero disruption")
achievable rather than aspirational.

## 1.1 Identity: extend, never replace (§79.10, §79.11, §79.12)

`users` stays exactly as it is and remains the single authentication record. ERP detail
goes into **profile tables** hanging off it, one row per user:

```
users (unchanged)
  ├── student_profiles   (user_id PK/FK → users.id)   GR No., Admission No., DOB, gender,
  │                                                    B-Form, photo, admission date,
  │                                                    previous school, family_id, status
  ├── employee_profiles  (user_id PK/FK → users.id)   Employee No., CNIC, designation,
  │                                                    department, joining date, employment
  │                                                    type/status, qualification, bank
  └── guardians ──┐
                  └── families (family_id)  ←── student_profiles.family_id
```

Why profiles rather than widening `users`:

- Every existing query, serializer and dashboard keeps working untouched — there is no way
  for an ERP column to change what `/auth/me` or a teacher dashboard returns.
- Student fields and employee fields have nothing in common; one wide table would be
  two-thirds NULL and would invite the wrong joins.
- Personnel data (CNIC, salary, bank) sits in its own table, so database-level access
  control can be applied to it. On a single `users` table it could not be.

**Three identity rules that prevent trouble later:**

1. `users.id` is the permanent internal identity (§7 of the master spec). GR No.,
   Admission No. and Employee No. are institutional numbers *carried by* the profile —
   never the primary key, never a foreign key target.
2. One human may legitimately hold two accounts (a teacher who is also a parent; a staff
   member's child). We do **not** force one login per person. Instead, `families` and
   `guardians` link the *records*, and a staff-child fee concession resolves through the
   family link, not through account identity.
3. `student_profiles.status` (`active`, `withdrawn`, `graduated`, `struck_off`) is the ERP
   status; `users.is_active` remains the login switch. They are set together by service
   code, never independently by hand, but they answer different questions and reports must
   use the ERP one.

## 1.2 The class master, and the bridge to free text (§79.21)

New tables:

```
academic_sessions   id, name "2026-2027", start_date, end_date, status (planning|active|closed)
classes             id, canonical_name "Class 5", level (pre_primary|primary|middle|secondary),
                    sort_order, is_active
sections            id, class_id, name "A", capacity, class_teacher_id → users.id
subjects            id, name, short_name, applies_to_levels[], is_active
class_subjects      class_id, subject_id, is_optional          (which subjects a class studies)
enrollments         id, student_user_id, session_id, class_id, section_id, roll_no,
                    status (enrolled|promoted|retained|withdrawn|graduated),
                    enrolled_on, left_on
class_aliases       class_id, alias "Grade 5"   (seeded from the existing normalizer)
```

`enrollments` is the keystone. "Which class is this student in" stops being a string on
`users` and becomes a row per session, which is what makes promotion, historical report
cards and last-year's-defaulters possible at all.

**The bridge.** `class_matching.class_key()` already reduces every spelling to one
canonical key. We keep that function and give it a second job: resolving a legacy string
to a `class_id`. Existing tables gain **nullable** `class_id` / `section_id` /
`session_id` columns *beside* their existing string columns:

- Backfill populates the IDs from the strings, using the same normalizer.
- New writes populate both (dual-write) for the whole transition.
- Reads in existing code keep using the strings and are not touched.
- New ERP code reads only the IDs.
- Any row whose class string cannot be resolved lands in an **exception queue** for the
  office to fix — it is never guessed at. `class_key()` already fails closed on an
  unrecognised value, and we keep that behaviour.

Dropping the string columns is a later, optional contraction step, and is not part of
this programme.

## 1.3 Number series (§79.6, §79.7)

One generic table serves GR No., Admission No., application number, employee number,
voucher number, receipt number and journal number:

```
number_series   id, scope ("gr_no"|"admission_no"|"employee_no"|"voucher"|…),
                pattern ("LSS-{seq:05d}", "{session}-{seq:04d}"), next_value,
                reset_policy (never|per_session), is_active
```

Allocation happens inside the caller's transaction with `SELECT … FOR UPDATE` on the
series row, so two admissions recorded at the same second cannot receive the same GR No.
Patterns are configurable from the Owner's settings screen, as §8 of the master
specification requires.

Two rules the specification is emphatic about and which the schema will enforce:

- **GR No. and Admission No. are separate columns with separate series.** They are never
  derived from each other, even if LSS currently keeps them numerically aligned.
- GR No. is unique, indexed, immutable after admission, and searchable everywhere —
  a single `q=` global search resolves GR No., Admission No., registration number, student
  name, father name, CNIC and Employee No. against one indexed view.

Existing registration numbers are preserved as `student_profiles.registration_no` (a copy
of today's `login_id`), so nobody loses the number they already use, and the login ID
never changes.

## 1.4 Money and dates: two conventions fixed now

- **All monetary columns are `NUMERIC(14,2)`, never float.** The existing `submissions.grade`
  is a float, which is fine for marks; for money it would produce statements that are off by
  a paisa and a finance team that stops trusting the system. Currency is PKR only; no
  multi-currency support is being built.
- **All timestamps are stored UTC and rendered in Asia/Karachi.** The code currently uses
  naive `utcnow()`. Fee due dates, attendance dates and payroll months are *calendar*
  values and are stored as `DATE`, not timestamps, so a voucher due on the 10th is due on
  the 10th regardless of server timezone.

## 1.5 RBAC: permissions beside roles, not instead of them (§79.39, §79.40)

The specification's role list (Owner, ERP & Accounts Manager, Principal, Coordinator,
Examination Officer, Accountant, Cashier, Admission Officer, Teacher, Auditor, Parent,
Student) cannot be served by today's single `users.role` string. But that string is guarding
**93 `require_roles(...)` call sites and 45 direct role comparisons**, and changing its
meaning would be the single most likely way to break a live dashboard.

**Approach: keep the string, add a permission layer next to it.**

```
roles              id, key ("erp_accounts_manager"), name, is_system, rank
permissions        key ("fee.voucher.create"), module, description
role_permissions   role_id, permission_key
user_roles         user_id, role_id, granted_by, granted_at        (a user may hold several)
```

- `users.role` continues to hold the user's **primary** role and keeps its existing values
  for every existing account. Existing `require_roles(...)` checks are not edited.
- New ERP endpoints use a new dependency, `require_permission("payroll.approve")`, which
  resolves the user's roles → permissions (cached per request).
- A compatibility shim grants legacy roles their equivalent permission sets:
  `admin` → the full ERP operational set, `teacher` → teaching permissions,
  `student` → student permissions. So an existing admin keeps working on day one without
  any data change.
- The frontend's `ProtectedRoute` ([App.jsx:36](../frontend/src/App.jsx#L36)) gains an
  optional `requiredPermission` prop; the existing `allowedRoles` prop keeps working
  unchanged, and `/auth/me` starts returning a `permissions` array alongside `role`.

**Owner-only powers (master spec §82.B16) are enforced in three independent places**, because
a single check in application code is not a security boundary:

1. Permission level — a set of `owner.*` permissions that no other role may be granted.
2. Invariant level — service code refuses to modify, demote, deactivate or delete an
   account holding the Owner role, and refuses to grant the Owner role, regardless of the
   caller's permissions.
3. Database level — the application's database user has **no DELETE or UPDATE grant on the
   audit tables** (§1.6). This is what makes "Javaid cannot tamper with audit logs" true
   rather than merely intended.

The four senior accounts are seeded by an idempotent bootstrap script reading credentials
from the environment, with `must_change_password=True`.

> **Open question (blocking for this section only):** §82 of the specification states
> "the following four senior management accounts" but the copy provided is truncated part-way
> through the Principal's section C3. Owner (Aamir Jabbar), ERP & Accounts Manager (Javaid)
> and Principal (Makhdooma) are fully specified; the fourth account is not. The rest of the
> blueprint does not depend on it, but the RBAC seed does — see Part 6.

## 1.6 Audit trail (§79.41)

Generalise the existing pattern rather than inventing a second one.
[services/audit_service.py](../backend-python/services/audit_service.py) already writes
version-and-approval history for lesson plans and question papers into `content_revisions`.
We add:

```
audit_log   id, occurred_at, actor_user_id, actor_name, actor_role, ip, request_id,
            entity_type, entity_id, action, old_value (jsonb), new_value (jsonb),
            reason, approval_ref
```

- Append-only; no UPDATE or DELETE grant for the application role.
- Written in the **same transaction** as the change, so an audited change cannot commit
  without its audit row. (This differs deliberately from `audit_service`, which swallows
  failures — correct for a lesson plan, wrong for a salary revision.)
- Mandatory on: students, GR/Admission numbers, families, employees, employee numbers,
  salary structures, payroll runs, attendance corrections, marks, weightage schemes,
  result publication, fee structures, concessions, receipts, refunds, journal entries,
  permissions and role grants.
- `reason` is a required field for any correction made after a record has been published
  or approved.

## 1.7 Events, without new infrastructure (§79.44)

The specification's event list (§75: `STUDENT_ADMISSION_CONFIRMED`, `TEACHER_APPOINTED`,
`PAYROLL_APPROVED`, `PAYMENT_RECEIVED`, `RESULT_PUBLISHED`) is the right shape. It does
**not** need a message broker — Celery and Redis are already deployed.

**Transactional outbox:**

```
domain_events   id, event_type, payload (jsonb), occurred_at,
                status (pending|processing|done|failed), attempts, last_error,
                dedupe_key (unique)
```

The business change and its event row commit together. A Celery beat task drains the
outbox and dispatches to registered handlers. Every handler is idempotent and keyed on
`dedupe_key`, so a retry cannot post a fee twice or issue a second voucher. Failed events
surface on the exceptions dashboard (§73 of the master spec) instead of vanishing into a
log.

This gives the "enter once, everything knows" behaviour with the operational simplicity of
the stack we already run.

---

# PART 2 — MIGRATION AND BACKWARD COMPATIBILITY

## 2.1 Expand / migrate / contract (§79.9)

Every schema change follows the same three-beat pattern, and only the first two beats are
in scope for this programme:

1. **Expand** — add new tables and nullable columns. Old code is unaffected because nothing
   it reads has changed.
2. **Migrate** — backfill, then dual-write. Both representations are correct at once. This
   state is stable and can last months.
3. **Contract** — remove the old column. *Deliberately deferred.* There is no deadline on
   the legacy string columns, and leaving them costs almost nothing.

Nothing in this programme requires downtime for a schema change, and no migration deletes
a row. Withdrawal, graduation and staff exit are status changes; deletion is never used on
a record with history.

## 2.2 Step one: the production inventory report (§79.9)

Before any ERP migration is written, a read-only script runs against a **restored copy** of
the production database and produces a report covering:

- counts by role, active/inactive, and never-logged-in;
- every distinct `class_name` and `section` string in each of the nine tables that store
  them, with counts, and which ones the normalizer **cannot** resolve;
- suspected duplicate students (same normalized name + father name + class; same
  registration number in different spellings);
- suspected duplicate teachers;
- students with no class, no section, or a class no longer taught;
- registration-number format conformance and collisions;
- orphaned rows — assignments, papers, plans, participants pointing at deleted or inactive
  users;
- probable sibling groups (same father name + contact), as a *proposal* for family linking,
  never an automatic merge.

This report is the input to every migration decision, and it is also the input to the
office's data-cleanup work, which can start immediately and in parallel with development.

## 2.3 Mapping existing people (§79.3, §79.4)

**Students.** For every `users` row with `role='student'`: create `student_profiles` with
`registration_no = login_id`, carry over `father_name`, allocate a GR No. only where LSS has
no existing one to enter, and create an `enrollments` row for the current session from the
existing `class_name`/`section`. No ID changes, no password resets, no new accounts.

**Teachers.** For every `users` row with `role='teacher'`: create `employee_profiles`,
allocate an Employee No., and convert `assigned_classes` / `assigned_sections` JSON into
`teacher_assignments` rows (session, class, section, subject) — while **leaving the JSON
columns in place and dual-written**, because `class_matching.teacher_may_teach` reads them
and classroom authorization depends on it.

**Missing fields.** ERP screens show a completion state per record — "Payroll needs: CNIC,
joining date, bank account" — and ask only for what is absent. Nothing already known is
ever re-requested (§4 of the master specification). Records with missing mandatory fields
are listed on an exceptions screen; they are not blocked from operating in the meantime.

## 2.4 Backward-compatibility guardrail (§79.8)

Concrete and testable, not a promise:

1. **A legacy contract test suite is written first**, before any ERP migration —
   pytest against the running API, pinning the exact response shape of student login,
   teacher login, `/auth/me`, the student and teacher dashboards, assignments list and
   submit, question paper generation, lesson plan CRUD, the chat endpoint, online class
   join, and classroom authorization for both the allowed and the denied case. The project
   already has `pytest.ini` and a `tests/` directory to build on.
2. That suite runs on every commit and against staging after every migration. **A
   red legacy test blocks the release**, whatever else is ready.
3. Every migration ships with a tested `downgrade()`, and every backfill is re-runnable
   (idempotent) so a partial run can simply be repeated.
4. Staging is refreshed from a production restore before each phase is validated — never
   validated against seeded test data alone.

## 2.5 Rollback (§79.48)

Three levels, chosen by what went wrong:

| Level | Mechanism | Recovery |
|---|---|---|
| Feature misbehaving | Feature flag off (§4.4) | Seconds; no data change |
| Bad deployment | Redeploy previous image | Minutes; schema is backward-compatible by design |
| Bad migration | `alembic downgrade` + restore of affected tables from the pre-migration backup | Under an hour |

Because expand/migrate keeps the old columns authoritative for old code, a rollback at
level 2 is safe at any point during the transition — the previous release can read the
database the new release wrote. That property is the whole reason for the pattern, and it
must not be traded away for tidiness.

---

# PART 3 — MODULE BLUEPRINTS

## 3.1 Admissions and family (§79.13, §79.5)

`inquiries → applications → admissions` as distinct records, so an inquiry that never
converts leaves a trace and the conversion funnel is reportable.

- On admission confirmation, a **single transaction** writes: `student_profiles` (GR No.,
  Admission No. allocated from their series), family link, `enrollments` row, `users`
  account with a temporary password and `must_change_password=True`, and a
  `STUDENT_ADMISSION_CONFIRMED` event. Everything downstream — fee account, attendance
  eligibility, examination roll, online-class membership — is driven by handlers on that
  event, not by the admission screen.
- **Family matching** is a suggestion, never an automatic merge: on entry of father name +
  CNIC + contact, candidate families are ranked and offered ("3 children of Muhammad Aslam,
  0300-1234567 — link to this family?"). The operator confirms. B-Form/CNIC is the strong
  key; name plus phone is a weak key and is presented as such.
- Sibling and family-level concessions attach to `families`, and resolve per student at
  voucher generation — so adding a third child automatically re-evaluates the discount
  rather than requiring anyone to remember.

## 3.2 HR, personnel files, appointment letters (§79.14, §79.15, §79.16)

- `employee_profiles`, `employee_documents` (MinIO-backed, one row per document with type,
  issue date and version), `employment_events` (joining, confirmation, increment, transfer,
  resignation, clearance).
- Personnel documents are private: served only through a permission-checked endpoint that
  issues a short-lived scoped token, reusing the `create_scoped_token` mechanism already in
  [middleware/auth.py](../backend-python/middleware/auth.py). Never a public bucket URL.
- **Appointment letters:** management uploads the existing LSS DOCX template with
  `{{Placeholder}}` fields; generation fills it from structured data and renders to DOCX and
  PDF. The project already has `docx_service` and `pdf_service` to build on. The generated
  letter is stored in the personnel file with issue date, employee number, salary,
  designation and document version.
- **The letter is not the salary record.** `salary_structures` is authoritative (§79.17);
  the letter is a rendering of it at a point in time. This is the single most important rule
  in the HR module, because it is what lets payroll run without a human reading documents.

## 3.3 Salary and payroll (§79.17, §79.18, §79.19)

```
salary_structures        employee_id, effective_from, effective_to (null = current),
                         basic, approved_by, approved_at, reason, supersedes_id
salary_components        structure_id, type (allowance|deduction), code, calculation
                         (fixed|percent_of_basic), amount_or_rate, is_taxable
payroll_runs             session/month, status (draft|calculated|approved|paid), totals,
                         approved_by, locked_at
payroll_lines            run_id, employee_id, structure_id snapshot, gross, each component,
                         arrears, bonus, advance_recovery, loan_recovery, tax, net
employee_advances/loans  principal, instalment, outstanding, schedule
```

- Salary is **never** updated in place — a revision closes the current structure with an
  `effective_to` and inserts a new one (§79.25 of the master spec). Full history is
  therefore free, and a payslip from two years ago still reproduces exactly.
- A payroll line **snapshots** the components it was computed from, so approving a run
  freezes it. A later salary correction cannot silently change a payslip that has been
  issued.
- Proration for mid-month joining, leaving and unpaid leave is a configurable policy
  (calendar days vs. working days) — and it needs a **leave module** as its input, which
  the specification does not currently define. See Part 6.
- Approving a run emits `PAYROLL_APPROVED`, whose handlers generate payslips, post the
  accounting entry (§3.7) and produce the bank transfer file. Nobody types a salary journal
  entry by hand.

## 3.4 Attendance (§79.20)

Two sources, one register:

```
attendance_days      session_id, class_id, section_id, date, marked_by, marked_at, status
attendance_records   day_id, student_user_id, status (present|absent|leave|late|half_day),
                     source (teacher|online_class|correction), note
```

- The teacher's screen is the mobile-first flow from §32 of the master specification: open,
  see the class list pre-loaded, everyone defaults to present, tap the absentees, save. One
  screen, no typing, no horizontal scrolling.
- The online-class attendance already produced by
  [services/attendance_service.py](../backend-python/services/attendance_service.py) feeds
  in as a **proposal** with `source='online_class'`; the teacher confirms or overrides. The
  existing derivation logic and its raw event evidence are kept as-is.
- Corrections are permitted, audited, and require a reason — never a silent overwrite.
- "Which classes have not submitted attendance today" is an exceptions-dashboard query, and
  is the one report that makes the module self-enforcing.

## 3.5 Examinations, marks, results (§79.22–§79.27)

```
exams              session_id, name, term, type (monthly|mid|final), sequence, status
exam_subjects      exam_id, class_id, subject_id, max_marks, passing_marks,
                   theory/practical split, exam_date, weightage_within_subject
marks              exam_subject_id, student_user_id, obtained, is_absent, is_exempt,
                   entered_by, entered_at, status (draft|submitted|approved|published)
grade_scales       scheme, min_percent, grade, grade_point, remark
result_schemes     session_id, class_id (or level), name "Annual 2026-27"
scheme_components  scheme_id, exam_id, weight_percent      (validated to total 100)
```

**The single calculation engine (§79.24, §79.25, §79.26 — master spec §81.F).** One service,
`services/results_engine.py`, computes every derived number. Marks entry, the exam ledger,
the combined ledger, the report card and the analytics dashboard all call it. No percentage,
weighted mark or grade is computed anywhere else — not in a route, not in a PDF template,
not in the frontend. This is the only way to guarantee the specification's requirement that
a ledger and a report card can never disagree.

Weightage is data (`scheme_components`), configurable per session and per class, validated
to total 100% before a scheme can be used to publish. Never hard-coded.

Validation at entry (§79.23): above maximum, negative, missing, duplicate, wrong
student/subject, and a teacher entering marks for a class they are not assigned to — the
last one checked through the same `class_matching` authorization already protecting
classrooms. Absent and exempt are explicit states, not zero, because they behave differently
in an average.

Approval: teacher entry → submit (locks the teacher's edit) → coordinator review →
examination officer → principal approval → publish. Publication emits `RESULT_PUBLISHED`.
Any post-publication correction requires a reason, re-runs the engine, regenerates affected
ledgers and report cards, and is audited.

Report cards (§79.27) are rendered from the engine's output via the existing PDF service,
individually or as one combined class PDF, and are exposed on the student dashboard.

## 3.6 Fees (§79.28–§79.32)

```
fee_heads          code, name, type (recurring|one_time), is_refundable, gl_account_id
fee_structures     session_id, class_id, head_id, amount, effective_from
student_fee_plan   student_user_id, session_id, head_id, amount override, reason
concessions        scope (student|family), head_id (or all), type (fixed|percent),
                   value, effective_from/to, approved_by, category, document_ref
vouchers           voucher_no, student_user_id, month, due_date, status, totals
voucher_lines      voucher_id, head_id, amount, concession_amount, net
receipts           receipt_no, voucher_id, amount, method, bank_ref, received_by,
                   received_at, reversal_of
student_ledger     student_user_id, date, description, debit, credit, running balance,
                   source_type/source_id
```

- Voucher generation is a Celery job over a class, section or the whole school; it reads the
  fee structure, applies concessions, carries arrears forward, and allocates voucher numbers
  from the number series. A student already billed for that month is skipped, not
  double-billed — the run is re-runnable by design.
- **Payment posting is idempotent**, keyed on the bank's transaction reference. This is the
  one place where a retry or a duplicated bank file would otherwise corrupt real money.
- Partial payment, overpayment (credit carried forward), unidentified payment (suspense
  account until matched), reversal and refund are all first-class states with their own
  accounting treatment — not manual adjustments.
- Orphan concession (master spec §55) is a concession category like any other, with its
  supporting documents held behind a permission that most roles do not have.
- **Defaulter List – All Active** (master spec §57) is a single report served by an indexed
  query over enrollment status and ledger balance, with aging buckets computed in SQL. It
  must return for the whole school in seconds, which means the running balance is maintained
  incrementally, not recomputed per student per request.

## 3.7 Accounting (§79.33, §79.34, §79.35, §79.37)

Proper double entry, with one rule: **nothing writes to the ledger except the posting
service.**

```
gl_accounts     code, name, type (asset|liability|equity|income|expense), parent_id,
                is_postable
journals        date, period, source_type, source_id, dedupe_key (unique),
                memo, posted_by, reversal_of
journal_lines   journal_id, account_id, debit, credit, cost_centre
```

- Business events post; humans do not. Fee received, payroll approved, expense recorded,
  refund issued — each has a posting rule mapping it to accounts, driven off the event
  outbox with the event's `dedupe_key` as the journal's idempotency key.
- Debits equal credits, enforced by a database constraint, not by application hope.
- Periods lock; a correction in a locked period is a reversal plus a re-post, never an edit.
- Trial balance, P&L, balance sheet and cash flow are queries over `journal_lines` with no
  separate summary tables to drift out of step.
- **Bank reconciliation (§79.32):** statement import (CSV/Excel — see Part 6 on bank APIs),
  automatic matching on amount + date + reference, an unmatched queue for human decision,
  and duplicate detection. AI may rank candidate matches; it never confirms one.

## 3.8 Reporting and dashboards (§79.36, §79.37)

- A shared query layer with filter, sort, group, aggregate, subtotal and drill-down, and one
  export path to PDF, Excel, CSV and print. Every module's reports use it, so exports behave
  identically everywhere.
- Long or large reports run as Celery jobs and land in MinIO with a short-lived download
  link — a 1,200-row defaulter PDF must not occupy a web worker.
- **Read models for dashboards.** Management dashboard figures (collections today,
  outstanding, attendance %, payroll total) are maintained incrementally by event handlers,
  not recomputed live. A dashboard that runs eleven full-table aggregates on every load is
  the first thing to fall over in March.
- The dynamic report builder (master spec §64) is deliberately the **last** thing built: it
  is only safe once the underlying models are stable, and 90% of its value is covered by the
  fixed reports.

## 3.9 AI assistant (§79.38)

The existing AI services stay as they are. The management assistant is a **separate**
service with a different safety model from the curriculum chatbot:

- It answers from **tools, not from the database directly** — a fixed set of parameterised,
  permission-checked query functions (`count_absent_today`, `list_active_defaulters`,
  `payroll_summary`). It never writes generated SQL against production.
- Every tool call runs as the asking user, through the same permission layer as the UI. A
  coordinator asking about salaries gets the same refusal the screen would give.
- It reports figures with their as-of time, and links to the underlying report rather than
  restating long lists.
- Document OCR (master spec §67) extracts to a **review screen**, never straight into a
  record. Low-confidence fields are flagged for confirmation.

## 3.10 Existing modules: what changes (§79.42, §79.43)

Almost nothing, and that is the point.

| Module | Change |
|---|---|
| Online classes | Gains `session_id`/`class_id`/`section_id` alongside its string columns; membership driven by `enrollments` once backfilled. `class_matching` authorization keeps working throughout. |
| Lesson plans | Gains session/class/subject foreign keys beside existing fields. Approval workflow and revisions unchanged. |
| Question papers | Unchanged. Optionally linked to an `exam` so a generated paper and the exam it belongs to are connected. |
| Assignments | Gains class/section foreign keys. Marks stay where they are — assignment grades are not exam marks and are not merged. |
| Chat / RAG | Untouched. |
| Teacher dashboard | Extended with attendance, marks entry and payslips; existing tiles keep their current behaviour and data source. |
| Student dashboard | Extended with fee vouchers, report cards and attendance; nothing removed. |

---

# PART 4 — CROSS-CUTTING

## 4.1 Security (§79.45)

- Personnel and financial data sit in their own tables, so access is controlled at both the
  application and database layer. The application's database role holds no DELETE on
  `audit_log` or `journals`.
- CNIC, bank account and salary are permission-gated at field level in the serializers —
  a coordinator listing employees sees names and designations, not bank details.
- All document access is through permission-checked endpoints issuing short-lived scoped
  tokens (the mechanism already in `middleware/auth.py`); no bucket is public.
- Secrets move entirely to environment variables, including the seeded admin password
  (§0.6). JWT secret rotation is supported by accepting the previous key for one expiry
  window.
- Rate limiting already exists (`middleware/rate_limit.py`) and extends to the new login-
  adjacent and export endpoints.
- PII handling, retention and who may export bulk student data need a written policy — see
  Part 6.

## 4.2 Backup and recovery (§79.46)

State the targets explicitly, because "we take backups" is not a recovery plan:

- Nightly full `pg_dump` plus continuous WAL archiving → **RPO ≈ 5 minutes, RTO ≈ 1 hour.**
- MinIO bucket replication for documents and recordings.
- **A restore is rehearsed monthly** into staging, and the staging refresh doubles as the
  proof. A backup that has never been restored is not a backup.
- Before every production migration: a verified dump, restore-tested, retained for 30 days.

## 4.3 Testing (§79.47)

| Layer | What |
|---|---|
| Legacy contract suite | §2.4 — blocks release on failure |
| Unit | The calculation engines: results/weightage, payroll, fee and concession, aging, posting rules. These are pure functions and must be tested exhaustively, including absent students, mid-month joiners, 100%-concession students and reversals. |
| Integration | Each event chain end to end: admission → account + fee + roll; payroll approval → payslip + journal; payment → ledger + receipt + journal. |
| Migration | Backfill idempotence, downgrade, and a full run against a production restore with row-count and checksum comparison. |
| Performance | Whole-school voucher generation, the all-active defaulter report, and a bulk report card run, at realistic volumes. |
| UAT | By the actual users — Javaid on fees and payroll, the Principal on results, two teachers on mobile attendance and marks entry. |

## 4.4 Deployment and feature flags (§79.49, §79.50)

- Docker Compose as today; migrations run as an explicit step before the new image serves
  traffic, never automatically on container start.
- A `feature_flags` table (key, enabled, roles, note) read through a cached service. Every
  new module ships behind a flag, defaulting off.
- Rollout per module: enabled for Owner only → the two or three staff who use it → their
  role → everyone. A module can be switched off mid-morning without a deployment, which is
  what makes a bad Monday recoverable.
- Existing functionality is never behind a flag — it simply keeps working.

---

# PART 5 — RECOMMENDED DEVELOPMENT PHASES (§79.51)

Ordering logic: foundations first, then the modules in the order that removes the most
manual work per week of development, with one hard constraint — **accounting must follow
fees and payroll**, because it exists to receive their postings.

| Phase | Contents | Visible to |
|---|---|---|
| **0. Inventory & cleanup** | Production inventory report (§2.2); office begins data cleanup; legacy contract test suite; move seeded admin password to env | Nobody — but it de-risks everything after it |
| **1. Foundations** | Sessions, classes, sections, subjects, enrollments + backfill and dual-write; profile tables; number series; RBAC + the senior accounts; audit log; event outbox; feature flags | Owner/admin screens only |
| **2. People & admissions** | Admissions, families, guardians, student and teacher provisioning on events, missing-field completion screens, personnel files | Office, HR |
| **3. Daily attendance** | Mobile teacher register, online-class proposals, correction workflow, attendance reports | Every teacher — the first phase the school *feels* |
| **4. Fees** | Fee heads and structures, concessions, vouchers, collection, receipts, student ledger, defaulters incl. Defaulter List – All Active | Accounts — the largest single reduction in manual work |
| **5. HR & payroll** | Salary structures, appointment letter engine, monthly payroll, payslips, bank file, payroll reports | HR, accounts |
| **6. Accounting** | Chart of accounts, posting service, automatic entries from phases 4–5, expenses, vendors, reconciliation, financial statements | Accounts, Owner |
| **7. Examinations** | Exam configuration, date sheets, marks entry, results engine, weightage schemes, ledgers, report cards, combined report cards, analytics | Teachers, exam office, parents |
| **8. Management layer** | Dashboards, dynamic report builder, AI management assistant, exception queues, parent portal | Management |

Two notes on this order:

- **Phase 7 (examinations) can be pulled earlier** if the academic calendar demands it — it
  depends only on Phase 1, not on fees or payroll. The order above optimises for
  administrative workload; if the school would rather have report cards before payroll, move
  7 ahead of 4 and nothing breaks. That is your call, and it is worth making deliberately.
- Phases 4, 5 and 6 are effectively one financial programme. Shipping 4 and 5 without 6
  is fine temporarily; shipping 6 without 4 and 5 is not, because it would have nothing to
  post.

---

# PART 6 — GAPS IN THE SPECIFICATION, AND DECISIONS NEEDED

## 6.1 Significant ERP requirements the specification does not cover

These are real holes, found by working through the specification against what a Pakistani
private school actually runs on. Listed with why each matters.

1. **Staff leave and staff attendance.** §24 requires prorated salary for unpaid leave, but
   no module produces leave data. Payroll cannot be correct without it. *Needs to be in
   Phase 5 at the latest.*
2. **Parent portal and parent accounts.** "Parent" appears in the role list and parents are
   expected to see report cards and vouchers, but no parent account lifecycle, linking rule
   or login is specified. *Decide: parent logins, or SMS + student dashboard only.*
3. **Communication — SMS/WhatsApp/email.** Fee reminders, absence alerts and result
   notifications are how a school actually collects money and manages attendance. The system
   has in-app notifications only. *This is the largest missing piece by practical impact.*
4. **Timetable / period scheduling.** Needed for date sheets without conflicts, teacher
   period allocation and substitution. Only `online_class_schedules` exists.
5. **Roll number assignment.** Roll No. appears throughout the ledger specification (§81)
   with no rule for how it is assigned, or whether it is stable across a session.
6. **Certificates.** School leaving, character, bonafide — mentioned only in passing under
   GR No. Each is a template document with a register and a serial number.
7. **Tax, EOBI and provident fund.** §19 says "taxes where applicable". Pakistani salary tax
   slabs change annually and must be configurable data, not code. *Confirm whether LSS
   withholds tax, and whether EOBI/PF apply.*
8. **Transport module.** Transport appears as a fee head; routes, stops, vehicles and
   per-stop fares do not exist. *Confirm whether LSS runs its own transport.*
9. **Multi-campus.** If LSS has, or may open, a second campus, `campus_id` costs almost
   nothing now and is a painful retrofit later. *Needs an answer before Phase 1 is built.*
10. **Exam edge cases.** Optional and elective subjects, theory/practical splits, absent vs.
    exempt vs. zero, re-sit exams, grace marks, and whether position/rank is published at
    all. Each of these always arrives at the worst moment.
11. **Security deposit refund on withdrawal**, and the withdrawal/clearance workflow
    generally.
12. **Offline tolerance** for mobile attendance and marks entry on weak connections —
    queue-and-sync, or accept that both need a live connection.
13. **Student photographs** — capture, storage, size policy, and their use on report cards
    and ID cards.
14. **Library, inventory/asset register, hostel, canteen** — named here only so their
    absence is a decision rather than an oversight.
15. **Data retention and PII policy** — who may bulk-export student data, how long
    withdrawn students' records are kept, and what is redacted for an auditor.

## 6.2 Decisions needed before Phase 1

Only the first is blocking; the rest shape the schema and are far cheaper answered now.

1. **The fourth senior management account.** §82 states there are four; the provided copy is
   truncated inside the Principal's section C3. Owner, ERP & Accounts Manager and Principal
   are specified — the fourth is not. *Blocking for the RBAC seed.*
2. **Multi-campus, yes or no** (gap 9).
3. **GR No. and Admission No. formats**, and their starting values — including whether
   existing students already have GR numbers on paper that must be entered rather than
   generated.
4. **Employee number format** and starting value.
5. **Academic session naming** and the current session's exact start and end dates.
6. **The official class list**, with the canonical spelling of every class LSS runs,
   including pre-primary levels and Pre-Board. The normalizer's list
   ([student_excel_import_service.py](../backend-python/services/student_excel_import_service.py))
   is a good starting point but was built for importing, not as policy.
7. **Parent access model** (gap 2) and **SMS provider** (gap 3).
8. **Whether examinations move ahead of fees** in the phase order (Part 5).

---

## What happens next

On approval of this blueprint, Phase 0 starts: the production inventory report and the
legacy contract test suite. Both are read-only, neither changes production, and together
they turn the rest of this programme from a plan into something measurable — and they will
almost certainly change some of the detail above, which is the point of running them first.

"""
Reconciling an updated student list against the live database.

The school sends one spreadsheet containing *everybody* — the students who were
already in LSS Bot before the summer, and the admissions taken since — and the
job is to end up with one record per child. Not two.

The danger is obvious and worth naming: a matching mistake either creates a
duplicate child (two accounts, two fee ledgers, two report cards) or writes one
child's GR number onto another child's record. Both are worse than doing
nothing, and neither announces itself. So:

  * **Nothing is written until a human has seen what will happen.** `preview()`
    reads the file and reports; `apply()` does the work. They are separate
    calls and the preview is the only way to reach the apply.
  * **Matches are ranked by how much they can be trusted.** A registration
    number is the number the child already logs in with — that is certainty. A
    name is not, and a name-only match is reported for confirmation rather than
    acted on.
  * **An existing child is only ever added to.** Their login, password, account
    id, dashboard and history are never touched. The importer fills blanks and
    updates ERP profile fields; it cannot rename an account or reset anything.
  * **Ambiguity stops.** If one spreadsheet row could be two children, or two
    rows point at one child, that row is set aside for a person to resolve.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import Enrollment, SchoolClass, Section, StudentProfile
from models.models import User
from services.erp import audit
from services.erp.setup import current_session
from services.student_excel_import_service import normalize_class, normalize_section

logger = logging.getLogger("agent")


class ReconcileError(RuntimeError):
    """Something about the file the office needs to fix."""


# ─── Reading the spreadsheet ──────────────────────────────────────────────────
# Header names are matched loosely, because every school spreadsheet spells
# them differently and asking for an exact template is how a migration stalls
# for a week.

FIELD_PATTERNS: dict[str, tuple[str, ...]] = {
    "registration_no": ("registration", "regno", "reg no", "reg#", "lss no", "lssno",
                        "student id", "studentid", "user id", "login"),
    "gr_no": ("gr", "grno", "gr no", "gr#", "general register"),
    "admission_no": ("admission no", "admissionno", "adm no", "admno", "admission#"),
    "name": ("student name", "name of student", "studentname", "name", "child name"),
    "father_name": ("father", "father name", "fathername", "fathers name",
                    "guardian name", "parent name"),
    "mother_name": ("mother", "mother name", "mothername"),
    "class_name": ("class", "grade", "class name", "classname", "admitted to"),
    "section": ("section", "sec"),
    "roll_no": ("roll", "roll no", "rollno", "roll#"),
    "date_of_birth": ("dob", "date of birth", "birth date", "birthdate", "b.date"),
    "gender": ("gender", "sex"),
    "b_form": ("b-form", "bform", "b form", "cnic", "nic", "form b"),
    "phone": ("phone", "mobile", "contact", "cell", "contact no"),
    "address": ("address", "residence", "home address"),
    "admission_date": ("admission date", "date of admission", "doa", "joining date"),
    "previous_school": ("previous school", "last school", "prev school"),
}


def _normalise_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(value or "").strip().lower())


def _match_field(header: str) -> str | None:
    """Which field a column header means, or None if we do not recognise it."""
    cleaned = _normalise_header(header)
    if not cleaned:
        return None

    # Exact first, so a column literally called "class" does not match
    # "class name" patterns belonging to something else.
    for field, patterns in FIELD_PATTERNS.items():
        if cleaned in patterns:
            return field

    # Then the *longest* matching pattern, not the first. "Father's Name"
    # normalises to "fathers name", which contains both "father" and "name" —
    # and declaration order is not specificity, so first-match assigned it to
    # the student's own name column and silently lost every father.
    best_field, best_length = None, 0
    for field, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            if pattern in cleaned and len(pattern) > best_length:
                best_field, best_length = field, len(pattern)
    return best_field


def _cell(value: Any) -> str:
    """A cell as clean text. Excel turns numbers into floats; a registration
    number read as 119013.0 matches nothing."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _as_date(value: Any) -> date | None:
    text = _cell(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d.%m.%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def read_rows(content: bytes) -> tuple[list[dict], list[str], list[str]]:
    """Parse the workbook. Returns (rows, recognised fields, ignored headers)."""
    try:
        workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:                        # noqa: BLE001
        raise ReconcileError(f"That file could not be read as an Excel workbook ({exc}).")

    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)

    header_row = None
    for candidate in rows_iter:
        if candidate and sum(1 for c in candidate if _cell(c)) >= 2:
            header_row = candidate
            break
    if header_row is None:
        raise ReconcileError("That file appears to be empty.")

    mapping: dict[int, str] = {}
    ignored: list[str] = []
    for index, header in enumerate(header_row):
        field = _match_field(header)
        if field and field not in mapping.values():
            mapping[index] = field
        elif _cell(header):
            ignored.append(_cell(header))

    if "name" not in mapping.values():
        raise ReconcileError(
            "No student-name column was found. The sheet needs a column headed "
            "'Student Name' (or similar)."
        )

    rows: list[dict] = []
    for number, raw in enumerate(rows_iter, start=2):
        if not raw or not any(_cell(c) for c in raw):
            continue
        row: dict[str, Any] = {"_row": number}
        for index, field in mapping.items():
            if index < len(raw):
                row[field] = _cell(raw[index])
        if row.get("name"):
            rows.append(row)

    return rows, sorted(set(mapping.values())), ignored


# ─── Matching ─────────────────────────────────────────────────────────────────

_ABBREVIATIONS = {
    "M": "MUHAMMAD", "MD": "MUHAMMAD", "MOHD": "MUHAMMAD", "MUHD": "MUHAMMAD",
    "MOHAMMAD": "MUHAMMAD", "MOHAMMED": "MUHAMMAD", "MUHAMMED": "MUHAMMAD",
    "SYED": "SYED", "MST": "", "MR": "", "MRS": "",
}


def normalise_person(value: str | None) -> str:
    """A name reduced to something comparable.

    Upper-cased, punctuation dropped, and the handful of abbreviations that
    appear constantly in Pakistani records expanded — "M. SAIFULLAH" and
    "MUHAMMAD SAIFULLAH" are the same father, and a migration that treats them
    as two people creates two families.
    """
    if not value:
        return ""
    text = re.sub(r"[^A-Za-z ]", " ", str(value).upper())
    words = [w for w in text.split() if w]
    expanded = []
    for word in words:
        replacement = _ABBREVIATIONS.get(word, word)
        if replacement:
            expanded.append(replacement)
    return " ".join(expanded)


def normalise_registration(value: str | None) -> str:
    """Registration numbers compare without spacing or case. Leading zeros are
    kept — LSS0119013 is not LSS119013."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


MATCH_REGISTRATION = "registration"
MATCH_GR = "gr_no"
MATCH_NAME = "name"
MATCH_NONE = "new"
MATCH_AMBIGUOUS = "ambiguous"

# Only these are acted on without a human looking at the individual row.
TRUSTED_MATCHES = (MATCH_REGISTRATION, MATCH_GR)


class Existing:
    """The live students, indexed the three ways a row might identify one."""

    def __init__(self, students: list[tuple[User, StudentProfile | None]]):
        self.by_registration: dict[str, list[User]] = {}
        self.by_gr: dict[str, list[User]] = {}
        self.by_name: dict[str, list[User]] = {}
        self.profiles: dict[str, StudentProfile | None] = {}

        for user, profile in students:
            self.profiles[user.id] = profile

            for key in filter(None, {
                normalise_registration(user.login_id),
                normalise_registration(profile.registration_no if profile else None),
            }):
                self.by_registration.setdefault(key, []).append(user)

            if profile and profile.gr_no:
                self.by_gr.setdefault(normalise_registration(profile.gr_no), []).append(user)

            name_key = f"{normalise_person(user.name)}|{normalise_person(user.father_name)}"
            if name_key.strip("|"):
                self.by_name.setdefault(name_key, []).append(user)

    def find(self, row: dict) -> tuple[str, User | None, str]:
        """(how it matched, who, why) for one spreadsheet row."""
        registration = normalise_registration(row.get("registration_no"))
        if registration:
            hits = self.by_registration.get(registration, [])
            if len(hits) == 1:
                return MATCH_REGISTRATION, hits[0], f"registration number {row['registration_no']}"
            if len(hits) > 1:
                return MATCH_AMBIGUOUS, None, f"{len(hits)} students share registration {row['registration_no']}"

        gr = normalise_registration(row.get("gr_no"))
        if gr:
            hits = self.by_gr.get(gr, [])
            if len(hits) == 1:
                return MATCH_GR, hits[0], f"GR number {row['gr_no']}"
            if len(hits) > 1:
                return MATCH_AMBIGUOUS, None, f"{len(hits)} students share GR number {row['gr_no']}"

        name_key = f"{normalise_person(row.get('name'))}|{normalise_person(row.get('father_name'))}"
        if name_key.strip("|"):
            hits = self.by_name.get(name_key, [])
            if len(hits) == 1:
                return MATCH_NAME, hits[0], "same name and father's name"
            if len(hits) > 1:
                return MATCH_AMBIGUOUS, None, f"{len(hits)} students have this name and father"

        return MATCH_NONE, None, "not found — treated as a new admission"


# ─── What would change ────────────────────────────────────────────────────────

# Fields the importer may fill on an existing student. Deliberately excludes
# anything to do with the account: login, password, role, id.
UPDATABLE = (
    "gr_no", "admission_no", "date_of_birth", "gender", "b_form",
    "phone", "address", "admission_date", "previous_school",
)


def _planned_changes(row: dict, profile: StudentProfile | None) -> dict:
    """Only what is genuinely new. A blank cell never blanks a stored value —
    an incomplete spreadsheet must not erase what the office already typed."""
    changes: dict[str, Any] = {}
    for field in UPDATABLE:
        incoming = row.get(field)
        if not incoming:
            continue
        value = _as_date(incoming) if field in ("date_of_birth", "admission_date") else incoming
        if value in (None, ""):
            continue
        current = getattr(profile, field, None) if profile else None
        if current in (None, "") or str(current) != str(value):
            changes[field] = value
    return changes


async def _plan(db: AsyncSession, content: bytes) -> dict:
    """The full plan — every row, untrimmed. Writes nothing."""
    rows, fields, ignored = read_rows(content)

    result = await db.execute(
        select(User, StudentProfile)
        .join(StudentProfile, StudentProfile.user_id == User.id, isouter=True)
        .where(User.role == "student")
    )
    existing = Existing(list(result.all()))

    result = await db.execute(select(SchoolClass))
    classes = {c.canonical_name: c for c in result.scalars().all()}

    matched: list[dict] = []
    needs_review: list[dict] = []
    new_students: list[dict] = []
    problems: list[dict] = []
    seen_students: dict[str, int] = {}

    for row in rows:
        how, user, why = existing.find(row)

        canonical = normalize_class(row.get("class_name")) if row.get("class_name") else None
        if row.get("class_name") and not canonical:
            problems.append({
                "row": row["_row"], "name": row.get("name"),
                "problem": f"class '{row['class_name']}' was not recognised",
            })
            continue

        if how == MATCH_AMBIGUOUS:
            needs_review.append({
                "row": row["_row"], "name": row.get("name"),
                "father_name": row.get("father_name"),
                "gr_no": row.get("gr_no"), "reason": why, "kind": "ambiguous",
            })
            continue

        if user is not None:
            # Two rows claiming the same child is a problem in the file, and
            # acting on both would apply one child's data twice.
            if user.id in seen_students:
                needs_review.append({
                    "row": row["_row"], "name": row.get("name"),
                    "reason": f"also matched by row {seen_students[user.id]}",
                    "kind": "duplicate_row",
                })
                continue
            seen_students[user.id] = row["_row"]

            changes = _planned_changes(row, existing.profiles.get(user.id))
            entry = {
                "row": row["_row"],
                "student_id": user.id,
                "existing_name": user.name,
                "file_name": row.get("name"),
                "login_id": user.login_id,
                "matched_by": how,
                "why": why,
                "changes": {k: str(v) for k, v in changes.items()},
                "class_in_file": canonical,
                "class_now": user.class_name,
            }
            if how in TRUSTED_MATCHES:
                matched.append(entry)
            else:
                # Every review entry carries `reason` and `kind`, whatever put
                # it there — one shape for the screen to read, rather than
                # three that happen to overlap.
                needs_review.append({**entry, "kind": "name_only", "reason": why})
            continue

        if not canonical:
            problems.append({
                "row": row["_row"], "name": row.get("name"),
                "problem": "new student with no class — cannot be admitted",
            })
            continue

        new_students.append({
            "row": row["_row"],
            "name": row.get("name"),
            "father_name": row.get("father_name"),
            "gr_no": row.get("gr_no"),
            "class_name": canonical,
            "section": normalize_section(row.get("section")) if row.get("section") else None,
            "known_class": canonical in classes,
        })

    # A child in the database who is not in the file at all: probably left, but
    # never assumed — the office is told, and nothing happens to them.
    in_file = set(seen_students)
    missing = [
        {"student_id": user.id, "name": user.name, "login_id": user.login_id,
         "class_name": user.class_name}
        for user, _ in await _all_students(db)
        if user.id not in in_file
    ]

    return {
        "rows_read": len(rows),
        "columns_recognised": fields,
        "columns_ignored": ignored,
        "summary": {
            "will_update": len(matched),
            "will_create": len(new_students),
            "needs_review": len(needs_review),
            "problems": len(problems),
            "in_database_but_not_in_file": len(missing),
        },
        "matched": matched,
        "new_students": new_students,
        "needs_review": needs_review,
        "problems": problems,
        "not_in_file": missing,
    }


# How much of the plan a screen is sent. The counts in `summary` are always the
# real ones; these caps only stop a browser being handed 750 rows it will not
# draw. `apply()` uses the full plan, never this.
DISPLAY_LIMIT = 500
NOT_IN_FILE_LIMIT = 200


async def preview(db: AsyncSession, content: bytes) -> dict:
    """What the file would do, trimmed for a screen. Writes nothing."""
    plan = await _plan(db, content)
    return {
        **plan,
        "matched": plan["matched"][:DISPLAY_LIMIT],
        "new_students": plan["new_students"][:DISPLAY_LIMIT],
        "not_in_file": plan["not_in_file"][:NOT_IN_FILE_LIMIT],
        "truncated": (
            len(plan["matched"]) > DISPLAY_LIMIT
            or len(plan["new_students"]) > DISPLAY_LIMIT
        ),
    }


async def _all_students(db: AsyncSession):
    result = await db.execute(
        select(User, StudentProfile)
        .join(StudentProfile, StudentProfile.user_id == User.id, isouter=True)
        .where(User.role == "student")
    )
    return list(result.all())


# ─── Applying ─────────────────────────────────────────────────────────────────

async def apply(
    db: AsyncSession,
    content: bytes,
    *,
    actor: User | None = None,
    create_new: bool = True,
    include_name_matches: bool = False,
) -> dict:
    """Do the work the preview described.

    `include_name_matches` is off by default: a name-only match is acted on
    only when somebody has looked at the list and said so.
    """
    # The *full* plan, not the trimmed preview: applying the display list
    # would update the first 500 children and quietly skip the rest.
    plan = await _plan(db, content)
    rows, _, _ = read_rows(content)
    by_row = {row["_row"]: row for row in rows}

    updated = created = 0
    updated_fields: dict[str, int] = {}

    entries = list(plan["matched"])
    if include_name_matches:
        entries += [e for e in plan["needs_review"] if e.get("kind") == "name_only"]

    for entry in entries:
        row = by_row.get(entry["row"])
        if row is None:
            continue

        result = await db.execute(
            select(StudentProfile).where(StudentProfile.user_id == entry["student_id"])
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            result = await db.execute(select(User).where(User.id == entry["student_id"]))
            student = result.scalar_one()
            profile = StudentProfile(
                user_id=student.id, registration_no=student.login_id, source="import",
            )
            db.add(profile)
            await db.flush()

        changes = _planned_changes(row, profile)
        if not changes:
            continue

        before = {k: str(getattr(profile, k, None)) for k in changes}
        for field, value in changes.items():
            # A GR number already held by another child is a data error worth
            # stopping on, not writing over.
            if field == "gr_no":
                clash = await db.execute(
                    select(StudentProfile.user_id).where(
                        StudentProfile.gr_no == str(value),
                        StudentProfile.user_id != profile.user_id,
                    )
                )
                if clash.scalar_one_or_none():
                    continue
            setattr(profile, field, value)
            updated_fields[field] = updated_fields.get(field, 0) + 1

        audit.record(
            db, actor=actor, entity_type=audit.STUDENT, action="reconciled",
            entity_id=profile.user_id,
            old_value=before, new_value={k: str(v) for k, v in changes.items()},
            reason="Updated from the school's master student list",
        )
        updated += 1

    await db.commit()

    if create_new:
        created = await _create_new_students(db, plan["new_students"], by_row, actor)

    audit.record(
        db, actor=actor, entity_type=audit.SETUP, action="student_list_reconciled",
        new_value={"updated": updated, "created": created,
                   "fields": updated_fields,
                   "left_for_review": len(plan["needs_review"])},
    )
    await db.commit()

    return {
        "updated": updated,
        "created": created,
        "fields_filled": updated_fields,
        "left_for_review": len(plan["needs_review"]),
        "problems": len(plan["problems"]),
    }


async def _create_new_students(db, new_students, by_row, actor) -> int:
    """Admit the children who are not in the database yet.

    Routed through the ordinary admission path so they get everything an
    admission gets — GR and admission numbers, a family, an enrolment, an
    account, and the event that tells the rest of the system.
    """
    from services.erp import admissions as admissions_service

    session = await current_session(db)
    if session is None:
        raise ReconcileError("There is no active academic session.")

    result = await db.execute(select(SchoolClass))
    classes = {c.canonical_name: c for c in result.scalars().all()}
    result = await db.execute(select(Section))
    sections = list(result.scalars().all())

    created = 0
    for entry in new_students:
        row = by_row.get(entry["row"])
        if row is None:
            continue
        school_class = classes.get(entry["class_name"])
        if school_class is None:
            continue

        section = next(
            (s for s in sections
             if s.class_id == school_class.id
             and normalize_section(s.name) == entry.get("section")),
            None,
        ) if entry.get("section") else None

        admission = await admissions_service.create_admission(
            db,
            data={
                "student_name": row.get("name"),
                "father_name": row.get("father_name"),
                "mother_name": row.get("mother_name"),
                "date_of_birth": _as_date(row.get("date_of_birth")),
                "gender": (row.get("gender") or "").lower()[:10] or None,
                "b_form": row.get("b_form"),
                "phone": row.get("phone"),
                "address": row.get("address"),
                "previous_school": row.get("previous_school"),
                "class_applied_id": school_class.id,
                "section_id": section.id if section else None,
                "status": "approved",
                "inquiry_source": "master list import",
            },
            actor=actor,
        )
        # A GR number from the school's register is the school's, not ours.
        if row.get("gr_no"):
            admission.gr_no = row["gr_no"]
        if row.get("admission_no"):
            admission.admission_no = row["admission_no"]

        await admissions_service.confirm_admission(db, admission, actor=actor)
        created += 1
        await db.commit()

    return created

"""
Class / section matching for classroom authorization.

Class names are written differently in different parts of LSS Bot: students
carry "Class 5", teachers are assigned "Grade 5", and a teacher's sections are
stored as combined strings like "Grade 5 - A". A classroom must not care which
vocabulary a record happens to use — a Class 5 student belongs in their Grade 5
teacher's room — so every comparison goes through the canonical form produced by
the existing importer normalizers rather than through string equality.

This module is authorization-critical: `student_may_join` and
`teacher_may_teach` are the only things standing between a student and another
section's classroom.
"""
from __future__ import annotations

from services.student_excel_import_service import normalize_class, normalize_section


def class_key(value: str | None) -> str:
    """Canonical comparison key for any class label.

    "Grade 5", "Class 5", "5", "V", "Five" and "Class 5 - A" all reduce to the
    same key. Returns "" when the value cannot be recognised, which never
    compares equal to anything (an unmatched class must fail closed).
    """
    if not value:
        return ""
    # Drop a trailing section suffix ("Grade 5 - A") before normalising.
    head = str(value).split(" - ")[0]
    canonical = normalize_class(head)
    return (canonical or "").strip().lower()


def section_key(value: str | None) -> str:
    """Canonical comparison key for a section, "" when unset."""
    if not value:
        return ""
    canonical = normalize_section(value)
    return (canonical or "").strip().lower()


def same_class(a: str | None, b: str | None) -> bool:
    key_a, key_b = class_key(a), class_key(b)
    return bool(key_a) and key_a == key_b


def same_section(session_section: str | None, user_section: str | None) -> bool:
    """A session with no section targets the whole class, so any section fits.

    A student with no recorded section may join a whole-class session but not a
    section-specific one — guessing which section they belong to would be worse
    than asking the office to fix their record.
    """
    target = section_key(session_section)
    if not target:
        return True
    return section_key(user_section) == target


def parse_teacher_sections(user, class_name: str) -> list[str]:
    """Sections a teacher handles for one class, from their "Grade 5 - A" list."""
    wanted = class_key(class_name)
    out: list[str] = []
    for combo in (getattr(user, "assigned_sections", None) or []):
        if " - " not in str(combo):
            continue
        head, _, tail = str(combo).partition(" - ")
        if class_key(head) != wanted:
            continue
        section = normalize_section(tail)
        if section and section not in out:
            out.append(section)
    return out


def teacher_classes(user) -> list[str]:
    """A teacher's assigned classes, canonicalised and de-duplicated."""
    out: list[str] = []
    for raw in (getattr(user, "assigned_classes", None) or []):
        canonical = normalize_class(raw)
        if canonical and canonical not in out:
            out.append(canonical)
    return out


def teacher_may_teach(user, class_name: str, section: str | None, subject: str) -> tuple[bool, str]:
    """May this teacher start a class for this class/section/subject?

    Returns (allowed, reason). A teacher with nothing assigned yet is allowed —
    the same deliberate fallback the rest of the app uses so a new teacher is
    never locked out — but a teacher WITH assignments is held to them.
    """
    if getattr(user, "role", None) != "teacher":
        return False, "Only teachers can start a class."

    assigned_classes = teacher_classes(user)
    if assigned_classes and not any(same_class(c, class_name) for c in assigned_classes):
        return False, f"You are not assigned to {class_name}."

    sections = parse_teacher_sections(user, class_name)
    if section and sections and not any(section_key(s) == section_key(section) for s in sections):
        return False, f"You are not assigned to {class_name} section {section}."

    subjects = getattr(user, "subjects", None) or []
    if subjects and subject and subject not in subjects:
        return False, f"You do not teach {subject}."

    return True, ""


def student_may_join(user, session) -> tuple[bool, str]:
    """May this student join this session? Class AND section must both match."""
    if getattr(user, "role", None) != "student":
        return False, "Only students join a class this way."
    if not same_class(user.class_name, session.class_name):
        return False, "This class is for a different class group."
    if not same_section(session.section, user.section):
        return False, "This class is for a different section."
    return True, ""


def is_young_class(class_name: str | None, young_classes: list[str] | None) -> bool:
    """Pre-Nursery…Class 2 get the simplified classroom (spec §5)."""
    if not class_name:
        return False
    target = class_key(class_name)
    for candidate in (young_classes or []):
        if class_key(candidate) == target:
            return True
    return False

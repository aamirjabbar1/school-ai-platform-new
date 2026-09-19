"""
Student list reconciliation.

The failure modes here are expensive and quiet: a duplicated child gets two fee
ledgers and two report cards, and a mis-matched row writes one child's GR number
onto another child's record. Neither announces itself, so the matching rules are
pinned hard.

The names below are drawn from the shape of the real data: 755 students, all
logging in with an `LSS#########` registration number, names stored in capitals,
fathers recorded as "M. SAIFULLAH" as often as "MUHAMMAD SAIFULLAH".
"""
import pytest

from services.erp.student_reconcile import (
    MATCH_AMBIGUOUS, MATCH_GR, MATCH_NAME, MATCH_NONE, MATCH_REGISTRATION,
    TRUSTED_MATCHES, UPDATABLE, Existing, _match_field, _planned_changes,
    normalise_person, normalise_registration,
)


class _User:
    def __init__(self, id, login_id, name, father_name=None, class_name=None):
        self.id = id
        self.login_id = login_id
        self.name = name
        self.father_name = father_name
        self.class_name = class_name


class _Profile:
    def __init__(self, user_id, gr_no=None, registration_no=None, **kwargs):
        self.user_id = user_id
        self.registration_no = registration_no
        # Defaults first, then what the test actually passed — the other way
        # round silently blanks gr_no, which is also in UPDATABLE.
        for key in UPDATABLE:
            setattr(self, key, kwargs.get(key))
        self.gr_no = gr_no


def _existing():
    return Existing([
        (_User("u1", "LSS0119013", "MUHAMMAD SHAHEER SHAREEF", "WAHEED AHMED CHAUDHARY"),
         _Profile("u1", gr_no="00412")),
        (_User("u2", "LSS0223096", "ZAINAB SAIFULLAH", "M. SAIFULLAH"), _Profile("u2")),
        (_User("u3", "LSS0221124", "ESHAL KARIM", "SHAHZAD KARIM"), None),
    ])


class TestHeaderMatching:
    """Every school spells its columns differently; demanding an exact template
    is how a migration stalls for a week."""

    @pytest.mark.parametrize("header,field", [
        ("Registration Number", "registration_no"),
        ("Reg No", "registration_no"),
        ("LSS No", "registration_no"),
        ("GR#", "gr_no"),
        ("GR No.", "gr_no"),
        ("Student Name", "name"),
        ("Name of Student", "name"),
        ("Father Name", "father_name"),
        ("Father's Name", "father_name"),
        ("Class", "class_name"),
        ("Section", "section"),
        ("DOB", "date_of_birth"),
        ("Date of Birth", "date_of_birth"),
        ("B-Form", "b_form"),
        ("Mobile", "phone"),
    ])
    def test_headers_people_actually_type(self, header, field):
        assert _match_field(header) == field

    def test_an_unknown_column_is_ignored_not_guessed(self):
        assert _match_field("Remarks by Coordinator") is None
        assert _match_field("") is None


class TestNormalisation:

    def test_registration_numbers_compare_without_punctuation(self):
        assert normalise_registration("lss 0119013") == "LSS0119013"
        assert normalise_registration("LSS-0119013") == "LSS0119013"

    def test_leading_zeros_are_significant(self):
        """LSS0119013 is not LSS119013 — dropping a zero matches the wrong
        child."""
        assert normalise_registration("LSS0119013") != normalise_registration("LSS119013")

    def test_excel_turning_a_number_into_a_float_is_handled(self):
        from services.erp.student_reconcile import _cell
        assert _cell(119013.0) == "119013"

    def test_the_abbreviation_every_pakistani_record_uses(self):
        """'M. SAIFULLAH' and 'MUHAMMAD SAIFULLAH' are one father. Treating
        them as two creates two families and breaks the sibling discount."""
        assert normalise_person("M. SAIFULLAH") == normalise_person("MUHAMMAD SAIFULLAH")
        assert normalise_person("Mohd Aslam") == normalise_person("MUHAMMAD ASLAM")

    def test_case_and_spacing_do_not_matter(self):
        assert normalise_person("  zainab   saifullah ") == "ZAINAB SAIFULLAH"

    def test_a_missing_name_normalises_to_nothing(self):
        assert normalise_person(None) == ""


class TestMatching:

    def test_a_registration_number_is_certainty(self):
        how, user, _ = _existing().find({"registration_no": "LSS0223096", "name": "anything"})
        assert how == MATCH_REGISTRATION
        assert user.id == "u2"

    def test_a_registration_number_beats_a_conflicting_name(self):
        """The number the child logs in with wins. A renamed child is still
        the same child."""
        how, user, _ = _existing().find({
            "registration_no": "LSS0223096", "name": "ZAINAB S.", "father_name": "SOMEBODY ELSE",
        })
        assert how == MATCH_REGISTRATION and user.id == "u2"

    def test_a_gr_number_matches_when_there_is_no_registration_number(self):
        how, user, _ = _existing().find({"gr_no": "00412", "name": "SHAHEER"})
        assert how == MATCH_GR and user.id == "u1"

    def test_name_and_father_match_only_as_a_last_resort(self):
        how, user, _ = _existing().find({
            "name": "Eshal Karim", "father_name": "Shahzad Karim",
        })
        assert how == MATCH_NAME and user.id == "u3"

    def test_a_name_only_match_is_not_trusted(self):
        """Two children can share a name. This one goes to a human."""
        assert MATCH_NAME not in TRUSTED_MATCHES
        assert MATCH_REGISTRATION in TRUSTED_MATCHES
        assert MATCH_GR in TRUSTED_MATCHES

    def test_an_unknown_child_is_a_new_admission(self):
        how, user, _ = _existing().find({"name": "NEW CHILD", "father_name": "NEW FATHER"})
        assert how == MATCH_NONE and user is None

    def test_two_children_with_one_name_stop_rather_than_guess(self):
        twins = Existing([
            (_User("a", "LSS1", "ALI KHAN", "HUR HUSSAIN"), None),
            (_User("b", "LSS2", "ALI KHAN", "HUR HUSSAIN"), None),
        ])
        how, user, why = twins.find({"name": "ALI KHAN", "father_name": "HUR HUSSAIN"})
        assert how == MATCH_AMBIGUOUS
        assert user is None
        assert "2 students" in why

    def test_a_father_written_two_ways_still_matches_his_child(self):
        how, user, _ = _existing().find({
            "name": "ZAINAB SAIFULLAH", "father_name": "MUHAMMAD SAIFULLAH",
        })
        assert how == MATCH_NAME and user.id == "u2"


class TestPlannedChanges:

    def test_a_blank_cell_never_erases_a_stored_value(self):
        """An incomplete spreadsheet must not wipe what the office typed."""
        profile = _Profile("u1", gr_no="00412", phone="03001234567")
        changes = _planned_changes({"gr_no": "", "phone": None}, profile)
        assert changes == {}

    def test_a_new_gr_number_is_filled_in(self):
        profile = _Profile("u2")
        assert _planned_changes({"gr_no": "00997"}, profile) == {"gr_no": "00997"}

    def test_an_unchanged_value_is_not_rewritten(self):
        profile = _Profile("u1", gr_no="00412")
        assert _planned_changes({"gr_no": "00412"}, profile) == {}

    def test_a_changed_value_is_reported(self):
        profile = _Profile("u1", gr_no="00412")
        assert _planned_changes({"gr_no": "00500"}, profile) == {"gr_no": "00500"}

    def test_dates_are_parsed_from_the_formats_people_type(self):
        profile = _Profile("u1")
        for written in ("2015-04-12", "12/04/2015", "12-04-2015"):
            changes = _planned_changes({"date_of_birth": written}, profile)
            assert str(changes["date_of_birth"]) == "2015-04-12", written

    def test_a_student_with_no_profile_yet_still_gets_changes(self):
        assert _planned_changes({"gr_no": "00997"}, None) == {"gr_no": "00997"}


class TestWhatCannotBeTouched:
    """The promise to 755 families: their child keeps their login."""

    def test_the_importer_cannot_change_an_account(self):
        for field in ("login_id", "password_hash", "role", "id", "is_active"):
            assert field not in UPDATABLE, f"{field} must never be importable"

    def test_it_only_writes_erp_profile_fields(self):
        assert set(UPDATABLE) <= {
            "gr_no", "admission_no", "date_of_birth", "gender", "b_form",
            "phone", "address", "admission_date", "previous_school",
        }

    def test_nothing_is_deleted(self):
        import inspect
        from services.erp import student_reconcile
        source = inspect.getsource(student_reconcile)
        assert "db.delete" not in source
        assert ".delete()" not in source

    def test_preview_writes_nothing(self):
        import inspect
        from services.erp import student_reconcile
        source = inspect.getsource(student_reconcile.preview)
        assert "db.add" not in source
        assert "commit" not in source

    def test_a_child_missing_from_the_file_is_reported_not_removed(self):
        """Probably left, never assumed. The office is told; nothing happens."""
        import inspect
        from services.erp import student_reconcile
        source = inspect.getsource(student_reconcile.preview)
        assert "not_in_file" in source

    def test_a_gr_number_held_by_another_child_is_refused(self):
        import inspect
        from services.erp import student_reconcile
        source = inspect.getsource(student_reconcile.apply)
        assert "StudentProfile.gr_no == str(value)" in source


class TestTheWholeFileIsApplied:
    """A migration that updates the first 500 children and quietly skips the
    rest looks exactly like one that worked. It happened; this stops it."""

    def test_apply_uses_the_untrimmed_plan(self):
        import inspect
        from services.erp import student_reconcile
        source = inspect.getsource(student_reconcile.apply)
        assert "_plan(db, content)" in source
        assert "preview(db, content)" not in source

    def test_preview_trims_only_for_display(self):
        import inspect
        from services.erp import student_reconcile
        source = inspect.getsource(student_reconcile.preview)
        assert "DISPLAY_LIMIT" in source
        assert "truncated" in source

    def test_the_summary_counts_are_never_trimmed(self):
        """The screen may show 500 rows; it must still say 739."""
        import inspect
        from services.erp import student_reconcile
        source = inspect.getsource(student_reconcile._plan)
        assert '"will_update": len(matched)' in source

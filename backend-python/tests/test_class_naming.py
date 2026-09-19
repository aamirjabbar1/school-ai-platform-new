"""
Class-name normalisation.

`normalize_class` is authorization-critical — `services/class_matching` uses it
to decide whether a student may enter a classroom — and it is also the gate
every imported student passes through. A class it cannot read is a child the
ERP cannot place.

LSS names its sections "Two-Go Green" and "Nursery-Go Yellow". The numbered
ones always worked, because a number could be found in them. The pre-primary
ones did not, because they were matched against an exact list — so every
Pre-Nursery, Nursery and Prep child silently failed to resolve. That is the
whole of Amna's school, and it is pinned here.
"""
import pytest

from services.student_excel_import_service import (
    CANONICAL_CLASSES, normalize_class, normalize_section,
)


class TestTheLssNamingPattern:

    @pytest.mark.parametrize("written,expected", [
        ("Two-Go Green", "Class 2"),
        ("Ten-Go Red", "Class 10"),
        ("One-Go Blue", "Class 1"),
        ("Nursery-Go Yellow", "Nursery"),
        ("Prep-Go Green", "KG"),
        ("KG-Go Green", "KG"),
        ("Pre-Nursery-Go Blue", "Pre-Nursery"),
        ("TWO-GO GREEN", "Class 2"),
        ("Two Go Green", "Class 2"),
    ])
    def test_sections_named_the_way_the_school_names_them(self, written, expected):
        assert normalize_class(written) == expected

    def test_pre_nursery_is_not_read_as_nursery(self):
        """They are different classes with different fees."""
        assert normalize_class("Pre-Nursery-Go Blue") == "Pre-Nursery"
        assert normalize_class("Nursery-Go Yellow") == "Nursery"


class TestExistingBehaviourIsUnchanged:
    """Everything already in the production database must keep resolving the
    way it resolved yesterday."""

    def test_every_canonical_class_resolves_to_itself(self):
        for canonical in CANONICAL_CLASSES:
            assert normalize_class(canonical) == canonical, canonical

    @pytest.mark.parametrize("written,expected", [
        ("Class 5", "Class 5"), ("Grade 5", "Class 5"), ("5", "Class 5"),
        ("V", "Class 5"), ("Five", "Class 5"), ("5-A", "Class 5"),
        ("class 5 boys", "Class 5"),
        ("Pre-Nine", "Class 8"),        # the LSS Pre-Board convention
        ("Prep", "KG"),
    ])
    def test_the_spellings_in_production(self, written, expected):
        assert normalize_class(written) == expected

    @pytest.mark.parametrize("written", ["", "   ", "Staff Room", "Library", "Alumni", "Unknown"])
    def test_a_class_that_is_not_a_class_fails_closed(self, written):
        """An unrecognised value must never compare equal to anything — it is
        what stops a student walking into another section's classroom."""
        assert normalize_class(written) is None

    def test_none_is_handled(self):
        assert normalize_class(None) is None


class TestSections:

    def test_a_short_code_is_upper_cased(self):
        assert normalize_section("a") == "A"

    def test_a_named_section_keeps_its_name(self):
        assert normalize_section("Go Green") == "Go Green"

    def test_the_section_keyword_is_stripped(self):
        assert normalize_section("Section B") == "B"

    def test_the_encoded_sections_in_production_survive(self):
        """Production stores "-VI-B-I" style sections; they must come back
        unchanged rather than being mangled into something shorter."""
        for written in ("-VI-B-I", "-III-G-I", "-IX-G"):
            assert normalize_section(written) == written

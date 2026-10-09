"""Unit tests for EMIS lookup model helpers (no database needed)."""

import pytest

from integrations.models import EmisSchool, EmisTeacherRegistrationStatus


class TestRegistrationStatusBadgeClass:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Full Registration", "bg-reg-full"),
            ("Full Registration with Conditions", "bg-reg-conditional"),
            ("Conditional Full", "bg-reg-conditional"),
            ("Provisional Registration", "bg-reg-provisional"),
            ("Limited Authority to Teach", "bg-reg-limited"),
            ("Expired", "bg-reg-expired"),
            ("FULL", "bg-reg-full"),
            ("Something Else", "bg-secondary"),
            ("", "bg-secondary"),
        ],
    )
    def test_label_maps_to_palette_class(self, label, expected):
        status = EmisTeacherRegistrationStatus(code="X", label=label)
        assert status.badge_class == expected

    def test_str_is_label(self):
        status = EmisTeacherRegistrationStatus(code="FULL", label="Full Registration")
        assert str(status) == "Full Registration"


def test_school_str_includes_name_and_number():
    school = EmisSchool(emis_school_no="SCH001", emis_school_name="Betio Primary")
    assert str(school) == "Betio Primary (SCH001)"

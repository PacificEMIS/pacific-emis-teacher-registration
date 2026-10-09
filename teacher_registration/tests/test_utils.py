"""Unit tests for registration number generation and related pure helpers."""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from integrations.models import EmisTeacherRegistrationStatus
from teacher_registration.models import compute_valid_until, registration_upload_path
from teacher_registration.utils import (
    base36_encode,
    calculate_check_digit,
    generate_teacher_registration_number,
    validate_registration_number,
)

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DOB = date(1990, 5, 17)


class TestBase36Encode:
    @pytest.mark.parametrize(
        ("number", "expected"),
        [(0, "0"), (9, "9"), (10, "A"), (35, "Z"), (36, "10"), (1295, "ZZ"), (1296, "100")],
    )
    def test_known_values(self, number, expected):
        assert base36_encode(number) == expected

    @pytest.mark.parametrize("number", [1, 42, 999_999, 2**32 - 1])
    def test_round_trips_through_int(self, number):
        assert int(base36_encode(number), 36) == number


class TestCalculateCheckDigit:
    @pytest.mark.parametrize("value", ["26A7K9", "000000", "ZZZZZZ", "12abcd"])
    def test_returns_single_alphabet_character(self, value):
        check = calculate_check_digit(value)
        assert len(check) == 1
        assert check in ALPHABET

    def test_is_case_insensitive(self):
        assert calculate_check_digit("26a7k9") == calculate_check_digit("26A7K9")

    def test_characters_outside_alphabet_add_nothing_but_keep_their_position(self):
        """Characterises current behaviour: a '-' contributes 0 to the sum but
        still shifts the doubling parity of everything before it."""
        assert calculate_check_digit("-26A7K9") == calculate_check_digit("26A7K9")
        assert calculate_check_digit("26A7K9-") != calculate_check_digit("26A7K9")

    def test_single_substitution_changes_check_digit(self):
        base = "26A7K9"
        original = calculate_check_digit(base)
        for position in range(len(base)):
            replacement = "B" if base[position] != "B" else "C"
            mutated = base[:position] + replacement + base[position + 1:]
            assert calculate_check_digit(mutated) != original, mutated


class TestGenerateTeacherRegistrationNumber:
    def test_format(self):
        """TR{YY}-{HASH}-{CHECK}: hash is base36 of a 32-bit value, so 4 to 7 characters."""
        number = generate_teacher_registration_number("A123456", DOB, 2026)
        prefix, hash_part, check = number.split("-")
        assert prefix == "TR26"
        assert 4 <= len(hash_part) <= 7
        assert all(c in ALPHABET for c in hash_part)
        assert len(check) == 1 and check in ALPHABET
        assert check == calculate_check_digit("26" + hash_part)

    def test_is_deterministic(self):
        first = generate_teacher_registration_number("A123456", DOB, 2026)
        second = generate_teacher_registration_number("A123456", DOB, 2026)
        assert first == second

    def test_normalises_national_id_whitespace_and_case(self):
        canonical = generate_teacher_registration_number("A123456", DOB, 2026)
        assert generate_teacher_registration_number("  a123456 ", DOB, 2026) == canonical

    def test_differs_by_national_id(self):
        a = generate_teacher_registration_number("A123456", DOB, 2026)
        b = generate_teacher_registration_number("A123457", DOB, 2026)
        assert a != b

    def test_differs_by_date_of_birth(self):
        a = generate_teacher_registration_number("A123456", DOB, 2026)
        b = generate_teacher_registration_number("A123456", date(1990, 5, 18), 2026)
        assert a != b

    def test_year_only_changes_prefix_not_hash(self):
        n2025 = generate_teacher_registration_number("A123456", DOB, 2025)
        n2026 = generate_teacher_registration_number("A123456", DOB, 2026)
        assert n2025[:4] == "TR25"
        assert n2026[:4] == "TR26"
        assert n2025[5:9] == n2026[5:9]

    def test_depends_on_secret_key(self, settings):
        settings.SECRET_KEY = "key-one"
        first = generate_teacher_registration_number("A123456", DOB, 2026)
        settings.SECRET_KEY = "key-two"
        second = generate_teacher_registration_number("A123456", DOB, 2026)
        assert first != second

    def test_generated_number_validates(self):
        number = generate_teacher_registration_number("A123456", DOB, 2026)
        assert validate_registration_number(number)

    @pytest.mark.parametrize("national_id", [None, "", "   "])
    def test_requires_national_id(self, national_id):
        with pytest.raises(ValidationError, match="National ID"):
            generate_teacher_registration_number(national_id, DOB, 2026)

    def test_requires_date_of_birth(self):
        with pytest.raises(ValidationError, match="Date of birth"):
            generate_teacher_registration_number("A123456", None, 2026)

    @pytest.mark.parametrize("year", [None, 0])
    def test_requires_approval_year(self, year):
        with pytest.raises(ValidationError, match="Approval year"):
            generate_teacher_registration_number("A123456", DOB, year)


class TestValidateRegistrationNumber:
    """validate_registration_number() accepts TR{YY}-{HASH}-{CHECK} with a hash of
    4 to 7 base36 characters, which covers everything generate() produces."""

    @pytest.fixture
    def valid(self):
        """The shortest accepted shape, with a correct check digit."""
        return "TR26-A7K9-" + calculate_check_digit("26A7K9")

    @pytest.mark.parametrize("hash_part", ["A7K9", "EFAM2A", "1483E95"])
    def test_accepts_hash_lengths_the_generator_produces(self, hash_part):
        number = f"TR26-{hash_part}-" + calculate_check_digit("26" + hash_part)
        assert validate_registration_number(number) is True

    @pytest.mark.parametrize("hash_part", ["A7K", "12345678", "A7K!", "A7-9"])
    def test_rejects_hash_of_wrong_length_or_alphabet(self, hash_part):
        number = f"TR26-{hash_part}-" + calculate_check_digit("26" + hash_part)
        assert validate_registration_number(number) is False

    def test_rejects_non_numeric_year(self):
        assert validate_registration_number("TRAB-A7K9-" + calculate_check_digit("ABA7K9")) is False

    def test_accepts_well_formed_number(self, valid):
        assert validate_registration_number(valid) is True

    def test_accepts_lowercase_check_digit(self, valid):
        assert validate_registration_number(valid[:-1] + valid[-1].lower()) is True

    def test_accepts_generated_number(self):
        number = generate_teacher_registration_number("A123456", DOB, 2026)
        assert validate_registration_number(number) is True

    @pytest.mark.parametrize(
        "value", [None, "", "TR26-A7K9", "TR26-A7K9-CC", "XX26-A7K9-C", "TR26A7K9-C-"]
    )
    def test_rejects_malformed(self, value):
        assert validate_registration_number(value) is False

    def test_rejects_wrong_check_digit(self, valid):
        wrong = "A" if valid[-1] != "A" else "B"
        assert validate_registration_number(valid[:-1] + wrong) is False

    def test_rejects_corrupted_hash(self, valid):
        replacement = "0" if valid[5] != "0" else "1"
        assert validate_registration_number(valid[:5] + replacement + valid[6:]) is False

    def test_rejects_wrong_separator(self, valid):
        assert validate_registration_number(valid.replace("-", "_")) is False


class TestComputeValidUntil:
    """Pure function in models.py; the status instance is never saved."""

    GRANTED = datetime(2026, 1, 1, 12, 0, tzinfo=dt_timezone.utc)

    @staticmethod
    def status(value, unit):
        return EmisTeacherRegistrationStatus(
            code="X", label="X", validity_value=value, validity_unit=unit
        )

    @pytest.mark.parametrize(
        ("value", "unit", "delta"),
        [
            (30, "minutes", timedelta(minutes=30)),
            (6, "hours", timedelta(hours=6)),
            (90, "days", timedelta(days=90)),
            (3, "years", timedelta(days=3 * 365)),
        ],
    )
    def test_each_unit(self, value, unit, delta):
        assert compute_valid_until(self.GRANTED, self.status(value, unit)) == self.GRANTED + delta

    def test_years_are_365_days_not_calendar_years(self):
        """Characterises current behaviour: leap days are not accounted for."""
        granted = datetime(2024, 1, 1, tzinfo=dt_timezone.utc)
        expected = datetime(2024, 12, 31, tzinfo=dt_timezone.utc)
        assert compute_valid_until(granted, self.status(1, "years")) == expected

    def test_none_status_never_expires(self):
        assert compute_valid_until(self.GRANTED, None) is None

    @pytest.mark.parametrize(
        ("value", "unit"), [(None, "days"), (0, "days"), (5, ""), (5, "weeks")]
    )
    def test_incomplete_or_unknown_validity_never_expires(self, value, unit):
        assert compute_valid_until(self.GRANTED, self.status(value, unit)) is None


class TestRegistrationUploadPath:
    def test_pending_registration_path(self):
        doc = SimpleNamespace(registration=SimpleNamespace(id=7), school_staff=None)
        assert registration_upload_path(doc, "cert.pdf") == "registrations/7/cert.pdf"

    def test_approved_staff_path(self):
        doc = SimpleNamespace(registration=None, school_staff=SimpleNamespace(id=3))
        assert registration_upload_path(doc, "cert.pdf") == "staff/3/cert.pdf"

    def test_orphan_path(self):
        doc = SimpleNamespace(registration=None, school_staff=None)
        assert registration_upload_path(doc, "cert.pdf") == "documents/cert.pdf"

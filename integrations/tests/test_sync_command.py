"""emis_sync_lookups management command against a recorded-style payload."""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from integrations import models as m

pytestmark = pytest.mark.django_db

PAYLOAD = {
    "schoolCodes": [{"C": "SCH1", "N": "Betio Primary"}, {"C": "", "N": "ignored"}],
    "levels": [{"C": 1, "N": "Class 1"}],
    "teacherRoles": [{"C": "T", "N": "Teacher"}],
    "warehouseYears": [{"C": 2026, "FormattedYear": "2026-27"}],
    "subjects": [{"C": "MATH", "N": "Mathematics"}],
    "teacherQuals": [{"C": "BED", "N": "Bachelor of Education"}],
    "maritalStatus": [{"C": "M", "N": "Married"}],
    "islands": [{"C": "TAR", "N": "Tarawa"}],
    "teacherStatus": [{"C": "PERM", "N": "Permanent"}],
    "teacherRegStatus": [{"C": "FULL", "N": "Full Registration"}],
    "educationLevels": [{"C": "PRI", "N": "Primary"}],
    "teacherLinkTypes": [{"C": "PHOTO", "N": "Passport Photo"}],
    "gender": [{"C": "F", "N": "Female"}],
    "teacherPdFocuses": [{"C": "LIT", "N": "Literacy"}],
    "teacherPdFormats": [{"C": "WS", "N": "Workshop"}],
    "teacherPdTypes": [{"C": "CERT", "N": "Certificate"}],
    "nationalities": [{"C": "KI", "N": "I-Kiribati"}],
}


def run(payload=PAYLOAD):
    out = StringIO()
    with patch("integrations.management.commands.emis_sync_lookups.EmisClient") as client_class:
        client_class.return_value.get_core_lookups.return_value = payload
        call_command("emis_sync_lookups", stdout=out)
    return out.getvalue()


def test_creates_every_lookup_table():
    output = run()

    assert m.EmisSchool.objects.get(emis_school_no="SCH1").emis_school_name == "Betio Primary"
    assert m.EmisSchool.objects.count() == 1  # blank code skipped
    assert m.EmisClassLevel.objects.get(code="1").label == "Class 1"
    assert m.EmisWarehouseYear.objects.get(code="2026").label == "2026-27"
    assert m.EmisTeacherRegistrationStatus.objects.get(code="FULL").label == "Full Registration"
    assert m.EmisNationality.objects.get(code="KI").label == "I-Kiribati"
    for model in (
        m.EmisJobTitle, m.EmisSubject, m.EmisTeacherQual, m.EmisMaritalStatus, m.EmisIsland,
        m.EmisTeacherStatus, m.EmisEducationLevel, m.EmisTeacherLinkType, m.EmisGender,
        m.EmisTeacherPdFocus, m.EmisTeacherPdFormat, m.EmisTeacherPdType,
    ):
        assert model.objects.count() == 1, model.__name__
    assert "Schools +1/0" in output
    assert "Nationalities +1/0" in output


def test_rerun_updates_labels_and_keeps_local_flags():
    run()
    status = m.EmisTeacherRegistrationStatus.objects.get(code="FULL")
    status.active = False
    status.validity_value, status.validity_unit = 3, "years"
    status.save()
    school = m.EmisSchool.objects.get(emis_school_no="SCH1")
    school.active = False
    school.save()

    payload = {**PAYLOAD, "teacherRegStatus": [{"C": "FULL", "N": "Full Registration (renamed)"}]}
    output = run(payload)

    status.refresh_from_db()
    assert status.label == "Full Registration (renamed)"
    assert status.active is False
    assert (status.validity_value, status.validity_unit) == (3, "years")
    school.refresh_from_db()
    assert school.active is False
    assert "Schools +0/1" in output
    assert "Teacher Registration Status +0/1" in output


def test_missing_label_falls_back_to_code():
    run({"subjects": [{"C": "X", "N": None}]})
    assert m.EmisSubject.objects.get(code="X").label == "X"


def test_empty_payload_is_a_noop():
    output = run({})
    assert m.EmisSchool.objects.count() == 0
    assert "Schools +0/0" in output


def test_api_failure_rolls_back_nothing_and_propagates():
    with patch("integrations.management.commands.emis_sync_lookups.EmisClient") as client_class:
        client_class.return_value.get_core_lookups.side_effect = RuntimeError("EMIS down")
        with pytest.raises(RuntimeError, match="EMIS down"):
            call_command("emis_sync_lookups", stdout=StringIO())
    assert m.EmisSchool.objects.count() == 0

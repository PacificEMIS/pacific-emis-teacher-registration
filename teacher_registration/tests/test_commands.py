"""check_expired_registrations management command."""

from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

import pytest
import time_machine
from django.contrib.sites.models import Site
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from core.models import SchoolStaff
from core.tests.factories import SchoolStaffFactory, UserFactory
from integrations.tests.factories import EmisTeacherRegistrationStatusFactory
from teacher_registration import constants
from teacher_registration.models import RegistrationChangeLog
from teacher_registration.tests.factories import TeacherRegistrationFactory

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=dt_timezone.utc)


def run():
    out, err = StringIO(), StringIO()
    with time_machine.travel(NOW, tick=False):
        call_command("check_expired_registrations", stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


@pytest.fixture
def expired_status():
    return EmisTeacherRegistrationStatusFactory(code="EXP", label="Expired")


@pytest.fixture
def full_status():
    return EmisTeacherRegistrationStatusFactory(code="FULL", label="Full Registration")


def teacher(valid_until, status, app_status=constants.APPROVED, email="t@example.org"):
    staff = SchoolStaffFactory(
        user=UserFactory(email=email),
        staff_type=SchoolStaff.TEACHING_STAFF,
        teacher_registration_status=status,
        registration_application_status=app_status,
        registration_granted_at=NOW - timedelta(days=400),
        registration_valid_until=valid_until,
    )
    TeacherRegistrationFactory(
        user=staff.user, status=constants.APPROVED, approved_staff_profile=staff, reviewed_at=NOW - timedelta(days=400)
    )
    return staff


def test_expires_only_past_due_approved_registrations(expired_status, full_status):
    past = teacher(NOW - timedelta(minutes=1), full_status)
    future = teacher(NOW + timedelta(days=1), full_status, email="f@example.org")
    never = teacher(None, full_status, email="n@example.org")
    already = teacher(NOW - timedelta(days=5), expired_status, app_status=constants.EXPIRED, email="a@example.org")

    out, _ = run()

    past.refresh_from_db()
    assert past.registration_application_status == constants.EXPIRED
    assert past.teacher_registration_status == expired_status
    for staff in (future, never):
        staff.refresh_from_db()
        assert staff.registration_application_status == constants.APPROVED
    assert "Expired 1 registration(s)." in out


def test_logs_against_latest_registration_and_emails_teacher(expired_status, full_status):
    staff = teacher(NOW - timedelta(days=1), full_status)
    Site.objects.update_or_create(pk=1, defaults={"domain": "reg.example.org", "name": "reg"})

    run()

    log = RegistrationChangeLog.objects.get()
    assert log.registration == staff.registration_history.get()
    assert (log.old_value, log.new_value) == (constants.APPROVED, constants.EXPIRED)
    assert log.changed_by is None
    assert "Previous status: Full Registration" in log.notes

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["t@example.org"]
    assert "https://reg.example.org/registration/renew/" in mail.outbox[0].body


def test_site_domain_with_scheme_is_used_verbatim(expired_status, full_status):
    teacher(NOW - timedelta(days=1), full_status)
    Site.objects.update_or_create(pk=1, defaults={"domain": "http://localhost:8000/", "name": "dev"})
    run()
    assert "http://localhost:8000/registration/renew/" in mail.outbox[0].body


def test_refuses_to_run_without_an_expired_status(full_status):
    staff = teacher(NOW - timedelta(days=1), full_status)
    out, err = run()
    assert "No EmisTeacherRegistrationStatus with 'expired'" in err
    staff.refresh_from_db()
    assert staff.registration_application_status == constants.APPROVED
    assert "Expired" not in out


def test_picks_first_when_several_expired_statuses(full_status):
    first = EmisTeacherRegistrationStatusFactory(code="AEXP", label="Expired")
    EmisTeacherRegistrationStatusFactory(code="BEXP", label="Expired (legacy)")
    staff = teacher(NOW - timedelta(days=1), full_status)
    run()
    staff.refresh_from_db()
    assert staff.teacher_registration_status == first


def test_email_failure_does_not_abort(expired_status, full_status):
    a = teacher(NOW - timedelta(days=1), full_status, email="a@example.org")
    b = teacher(NOW - timedelta(days=2), full_status, email="b@example.org")
    with patch(
        "teacher_registration.management.commands.check_expired_registrations.send_teacher_registration_expired_email",
        side_effect=ConnectionError("smtp down"),
    ):
        out, err = run()
    for staff in (a, b):
        staff.refresh_from_db()
        assert staff.registration_application_status == constants.EXPIRED
    assert "Could not send expiry email" in err
    assert "Expired 2 registration(s)." in out


def test_expired_teacher_can_then_renew(expired_status, full_status, client):
    staff = teacher(NOW - timedelta(days=1), full_status)
    run()
    client.force_login(staff.user)
    with time_machine.travel(NOW, tick=False):
        response = client.get("/registration/renew/")
    assert response.status_code == 302
    assert staff.user.teacher_registrations.filter(registration_type="renewal").exists()

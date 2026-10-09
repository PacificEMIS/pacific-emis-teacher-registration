"""Fixtures shared by the teacher_registration view-flow tests."""

from datetime import datetime, timezone as dt_timezone

import pytest

from core import permissions as p
from core.models import SchoolStaff
from core.tests.factories import GroupFactory, SchoolStaffFactory, UserFactory, system_user
from integrations.tests.factories import (
    EmisGenderFactory,
    EmisTeacherLinkTypeFactory,
    EmisTeacherRegistrationStatusFactory,
)
from teacher_registration import constants

FORMSET_PREFIXES = ("education_records", "training_records", "claimed_appointments")


def formset_management(total=0, initial=0, prefixes=FORMSET_PREFIXES):
    """Management-form fields for the inline formsets on the registration form."""
    data = {}
    for prefix in prefixes:
        data.update({
            f"{prefix}-TOTAL_FORMS": str(total),
            f"{prefix}-INITIAL_FORMS": str(initial),
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
        })
    return data


def registration_form_data(registration, gender, **overrides):
    """A complete, submittable payload for the registration edit form."""
    data = {
        "first_name": "Teua",
        "last_name": "Tekanene",
        "email": registration.user.email,
        "teacher_category": registration.teacher_category,
        "title": "Mr",
        "date_of_birth": "1990-05-17",
        "gender": gender.pk,
        "national_id_number": registration.national_id_number or "NID-001",
        "phone_number": "+686 11111",
        "residential_address": "Bairiki",
        "highest_qualification": "bachelors",
        "years_of_experience": "3",
        **formset_management(),
    }
    data.update(overrides)
    return data


@pytest.fixture
def gender():
    return EmisGenderFactory(code="F", label="Female")


@pytest.fixture
def admin_user():
    """An Admins-group user with an email address, so admin notifications have a recipient."""
    user = system_user(p.GROUP_SYSTEM_ADMINS)
    user.email = "admin@example.org"
    user.save()
    return user


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


@pytest.fixture
def signatory():
    user = UserFactory(username="signer@example.org", first_name="Sina", last_name="Signer")
    user.groups.add(GroupFactory(name=p.GROUP_REGISTRATION_SIGNATORIES))
    return user


@pytest.fixture
def full_status():
    return EmisTeacherRegistrationStatusFactory(
        code="FULL", label="Full Registration", validity_value=3, validity_unit="years"
    )


@pytest.fixture
def conditional_status():
    return EmisTeacherRegistrationStatusFactory(
        code="FULLCOND", label="Full Registration with Conditions", validity_value=1, validity_unit="years"
    )


@pytest.fixture
def expired_status():
    return EmisTeacherRegistrationStatusFactory(code="EXP", label="Expired")


@pytest.fixture
def photo_link_type():
    return EmisTeacherLinkTypeFactory(code="PHOTO", label="Passport Photo")


@pytest.fixture
def applicant():
    return UserFactory(username="teua@example.org", email="teua@example.org")


@pytest.fixture
def applicant_client(applicant):
    """A separate client from `client`/`admin_client`, so both can be logged in at once."""
    from django.test import Client

    applicant_client = Client()
    applicant_client.force_login(applicant)
    return applicant_client


def approved_teacher(user=None, status=None, granted=None, valid_until=None, **extra):
    """An approved teaching-staff profile."""
    granted = granted or datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
    kwargs = dict(
        staff_type=SchoolStaff.TEACHING_STAFF,
        national_id_number=extra.pop("national_id_number", "T-100"),
        teacher_registration_number=extra.pop("teacher_registration_number", "TR26-TEACH1-X"),
        teacher_registration_status=status,
        registration_application_status=constants.APPROVED,
        registration_granted_at=granted,
        registration_valid_until=valid_until,
        **extra,
    )
    if user is not None:
        kwargs["user"] = user
    return SchoolStaffFactory(**kwargs)

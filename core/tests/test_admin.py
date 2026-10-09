"""
Django admin smoke tests: every registered ModelAdmin's changelist, add form,
and change form render for a superuser, with one row of each model present
so list_display callables and inlines are exercised.
"""

from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib import admin
from django.urls import reverse

from core.models import EducationInstitution, SchoolStaff, StaffTeachingDuty
from core.tests.factories import GroupFactory, SchoolStaffAssignmentFactory, SystemUserFactory, UserFactory
from integrations.models import EmisWarehouseYear
from integrations.tests import factories as lookup_factories
from teacher_registration import constants
from teacher_registration.tests.factories import (
    ClaimedDutyFactory,
    EducationRecordFactory,
    RegistrationConditionFactory,
    RegistrationDocumentFactory,
    TeacherRegistrationFactory,
    TrainingRecordFactory,
)

pytestmark = pytest.mark.django_db

PROJECT_APPS = {"core", "teacher_registration", "integrations", "auth"}


@pytest.fixture
def superuser_client(client):
    client.force_login(UserFactory(is_superuser=True, is_staff=True))
    return client


@pytest.fixture
def one_of_everything():
    """One saved row per project model, so change pages have something to open."""
    registration = TeacherRegistrationFactory(status=constants.APPROVED)
    EducationRecordFactory(registration=registration)
    TrainingRecordFactory(registration=registration)
    ClaimedDutyFactory(appointment__registration=registration)
    RegistrationDocumentFactory(registration=registration)
    RegistrationConditionFactory(registration=registration)
    registration.change_logs.create(field_name="status", new_value="approved")

    staff = SchoolStaffAssignmentFactory(
        school_staff__staff_type=SchoolStaff.TEACHING_STAFF,
        school_staff__registration_granted_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
    )
    StaffTeachingDuty.objects.create(assignment=staff, year_level=lookup_factories.EmisClassLevelFactory())
    SystemUserFactory()
    GroupFactory(name="Admins")
    EducationInstitution.objects.create(code="USP", name="University of the South Pacific")
    EmisWarehouseYear.objects.create(code="2026", label="2026")
    for name in dir(lookup_factories):
        factory = getattr(lookup_factories, name)
        if name.endswith("Factory") and isinstance(factory, type):
            factory()


def registered_models():
    return sorted(
        (model for model in admin.site._registry if model._meta.app_label in PROJECT_APPS),
        key=lambda m: m._meta.label,
    )


BROKEN_ADMIN_FORMS = {}


def model_params():
    for model in registered_models():
        marks = []
        reason = BROKEN_ADMIN_FORMS.get(model._meta.label)
        if reason:
            marks.append(pytest.mark.xfail(strict=True, reason=reason))
        yield pytest.param(model, id=model._meta.label, marks=marks)


@pytest.mark.parametrize("model", registered_models(), ids=lambda m: m._meta.label)
def test_changelist_renders(superuser_client, one_of_everything, model):
    info = f"{model._meta.app_label}_{model._meta.model_name}"
    assert superuser_client.get(reverse(f"admin:{info}_changelist")).status_code == 200


@pytest.mark.parametrize("model", list(model_params()))
def test_add_page_renders(superuser_client, one_of_everything, model):
    info = f"{model._meta.app_label}_{model._meta.model_name}"
    add = superuser_client.get(reverse(f"admin:{info}_add"))
    assert add.status_code in (200, 403), f"{info} add page"


@pytest.mark.parametrize("model", list(model_params()))
def test_change_page_renders_for_an_existing_row(superuser_client, one_of_everything, model):
    row = model._default_manager.first()
    assert row is not None, f"no {model._meta.label} row created by the fixture"
    info = f"{model._meta.app_label}_{model._meta.model_name}"
    response = superuser_client.get(reverse(f"admin:{info}_change", args=[row.pk]))
    assert response.status_code == 200


def test_changelist_search_does_not_crash(superuser_client, one_of_everything):
    for model in registered_models():
        model_admin = admin.site._registry[model]
        if not model_admin.search_fields:
            continue
        info = f"{model._meta.app_label}_{model._meta.model_name}"
        response = superuser_client.get(reverse(f"admin:{info}_changelist"), {"q": "x"})
        assert response.status_code == 200, info


def test_project_models_are_registered():
    labels = {m._meta.label for m in registered_models()}
    for expected in (
        "core.SchoolStaff", "core.SystemUser", "core.SchoolStaffAssignment",
        "teacher_registration.TeacherRegistration", "teacher_registration.RegistrationDocument",
        "teacher_registration.RegistrationChangeLog", "integrations.EmisSchool",
        "integrations.EmisTeacherRegistrationStatus", "auth.User",
    ):
        assert expected in labels, expected

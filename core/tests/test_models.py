"""Unit tests for small core model helpers."""

from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import OrgSettings
from core.tests.factories import SchoolStaffAssignmentFactory, SchoolStaffFactory

pytestmark = pytest.mark.django_db


class TestOrgSettingsSingleton:
    def test_load_creates_the_single_row(self):
        assert OrgSettings.objects.count() == 0
        row = OrgSettings.load()
        assert row.pk == 1
        assert OrgSettings.objects.count() == 1

    def test_load_twice_returns_same_row(self):
        assert OrgSettings.load().pk == OrgSettings.load().pk
        assert OrgSettings.objects.count() == 1

    def test_save_always_targets_pk_one(self):
        OrgSettings.load()
        OrgSettings(pk=99).save()
        assert OrgSettings.objects.count() == 1
        assert OrgSettings.objects.get().pk == 1


class TestSchoolStaffAssignment:
    def test_is_active_when_no_end_date(self):
        assert SchoolStaffAssignmentFactory(end_date=None).is_active is True

    def test_is_inactive_with_any_end_date(self):
        future = timezone.now().date() + timedelta(days=30)
        assert SchoolStaffAssignmentFactory(end_date=future).is_active is False

    def test_active_assignments_includes_open_and_not_yet_ended(self):
        staff = SchoolStaffFactory()
        open_assignment = SchoolStaffAssignmentFactory(school_staff=staff, end_date=None)
        future = SchoolStaffAssignmentFactory(
            school_staff=staff, end_date=timezone.now().date() + timedelta(days=1)
        )
        today = SchoolStaffAssignmentFactory(school_staff=staff, end_date=timezone.now().date())
        SchoolStaffAssignmentFactory(
            school_staff=staff, end_date=timezone.now().date() - timedelta(days=1)
        )

        assert set(staff.active_assignments) == {open_assignment, future, today}

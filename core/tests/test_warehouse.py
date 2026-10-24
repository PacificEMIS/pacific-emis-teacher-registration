"""
Warehouse views (core/migrations/0031) and the helper module that reads them.

The views are the single source for the summary report, the dashboard and the
KEMIS feed (issue #119), so these tests pin the row shapes and the counting
rules rather than any one screen.
"""

from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.urls import reverse
from django.utils import timezone

from core import warehouse
from core.models import SchoolStaff
from core.tests.factories import (
    SchoolStaffAssignmentFactory,
    SchoolStaffFactory,
    SystemUserFactory,
    UserFactory,
    system_user,
)
from core import permissions as p
from integrations.tests.factories import (
    EmisIslandFactory,
    EmisSchoolFactory,
    EmisTeacherRegistrationStatusFactory,
)
from teacher_registration import constants
from teacher_registration.models import RegistrationChangeLog, TeacherRegistration
from teacher_registration.tests.factories import TeacherRegistrationFactory

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc


def registered_teacher(**overrides):
    defaults = dict(
        staff_type=SchoolStaff.TEACHING_STAFF,
        registration_application_status=constants.APPROVED,
        registration_granted_at=datetime(2026, 1, 15, tzinfo=UTC),
        registration_valid_until=timezone.now() + timedelta(days=400),
    )
    defaults.update(overrides)
    return SchoolStaffFactory(**defaults)


def log(registration, new_value, changed_at=None, by=None):
    entry = RegistrationChangeLog.objects.create(
        registration=registration, field_name="status", old_value="", new_value=new_value, changed_by=by
    )
    if changed_at:
        RegistrationChangeLog.objects.filter(pk=entry.pk).update(changed_at=changed_at)
    return entry


class TestCurrent:
    def test_row_shape_and_current_school(self):
        status = EmisTeacherRegistrationStatusFactory(code="FULL", label="Full registration")
        island = EmisIslandFactory(code="TRW", label="Tarawa")
        teacher = registered_teacher(
            teacher_registration_number="TR26-AAA-1",
            teacher_registration_status=status,
            home_island=island,
            date_of_birth=datetime(1990, 5, 17).date(),
        )
        old_school, new_school = EmisSchoolFactory(), EmisSchoolFactory()
        SchoolStaffAssignmentFactory(
            school_staff=teacher, school=old_school,
            start_date=datetime(2020, 1, 1).date(), end_date=datetime(2024, 12, 31).date(),
        )
        SchoolStaffAssignmentFactory(school_staff=teacher, school=new_school, start_date=datetime(2025, 1, 1).date())

        (row,) = warehouse.current()
        assert row["registration_number"] == "TR26-AAA-1"
        assert row["application_status"] == constants.APPROVED
        assert row["registration_status_code"] == "FULL"
        assert row["registration_status_label"] == "Full registration"
        assert row["granted_at"] == datetime(2026, 1, 15).date()
        assert row["days_to_expiry"] > 0
        assert row["birth_year"] == 1990
        assert (row["home_island_code"], row["home_island_label"]) == ("TRW", "Tarawa")
        assert row["school_no"] == new_school.emis_school_no
        assert row["school_name"] == new_school.emis_school_name
        assert row["staff_id"] == teacher.pk

    def test_only_registered_teaching_staff(self):
        registered_teacher(teacher_registration_number="A")
        expired = registered_teacher(
            teacher_registration_number="B",
            registration_application_status=constants.EXPIRED,
            registration_valid_until=timezone.now() - timedelta(days=3),
        )
        SchoolStaffFactory(staff_type=SchoolStaff.NON_TEACHING_STAFF)
        SchoolStaffFactory(staff_type=SchoolStaff.TEACHING_STAFF, registration_application_status=constants.DRAFT)

        rows = warehouse.current()
        assert [r["registration_number"] for r in rows] == ["A", "B"]
        assert rows[1]["days_to_expiry"] < 0
        assert rows[1]["school_no"] is None
        assert expired.pk == rows[1]["staff_id"]


class TestMonthly:
    def test_counts_by_calendar_month(self):
        registration = TeacherRegistrationFactory(submitted=True)
        TeacherRegistration.objects.filter(pk=registration.pk).update(
            submitted_at=datetime(2026, 3, 5, tzinfo=UTC), created_at=datetime(2026, 2, 20, tzinfo=UTC)
        )
        log(registration, constants.APPROVED, changed_at=datetime(2026, 3, 30, tzinfo=UTC))
        log(registration, constants.REJECTED, changed_at=datetime(2026, 4, 2, tzinfo=UTC))
        registered_teacher(
            registration_granted_at=datetime(2026, 3, 31, 23, 0, tzinfo=UTC),
            registration_valid_until=datetime(2029, 3, 31, tzinfo=UTC),
        )

        rows = {r["month"]: r for r in warehouse.monthly()}
        assert "2026-02" in rows  # first month = earliest application
        assert rows["2026-03"]["submitted"] == 1
        assert rows["2026-03"]["approved"] == 1
        assert rows["2026-03"]["granted"] == 1
        assert rows["2026-04"]["rejected"] == 1
        assert rows["2029-03"]["expiring"] == 1  # range extends to the last expiry
        assert all(
            rows[m]["submitted"] == 0 for m in rows if m not in {"2026-03"}
        )

    def test_expiring_window_and_last_months(self):
        now = timezone.now()
        in_two_months = warehouse._add_months(warehouse._month_start(now), 2) + timedelta(days=3)
        registered_teacher(registration_valid_until=in_two_months)
        registered_teacher(registration_valid_until=now + timedelta(days=800))  # beyond 12 months

        upcoming = warehouse.expiring(months=12)
        assert upcoming == [{"month": in_two_months.strftime("%Y-%m"), "count": 1}]

        recent = warehouse.last_months(warehouse.monthly(), 6, now=now)
        assert len(recent) == 6
        assert recent[-1]["month"] == now.strftime("%Y-%m")


class TestEventsAndActivity:
    def test_events_cursor_and_names(self):
        reviewer = UserFactory(first_name="Ana", last_name="Reviewer")
        registration = TeacherRegistrationFactory()
        first = log(registration, constants.SUBMITTED, by=reviewer)
        second = log(registration, constants.UNDER_REVIEW, by=None)

        rows, next_after_id = warehouse.events(after_id=0, limit=1)
        assert [r["id"] for r in rows] == [first.pk] and next_after_id == first.pk
        assert rows[0]["changed_by"] == "Ana Reviewer"
        assert rows[0]["registration_type"] == TeacherRegistration.INITIAL

        rows, next_after_id = warehouse.events(after_id=first.pk, limit=10)
        assert [r["id"] for r in rows] == [second.pk] and next_after_id is None
        assert rows[0]["changed_by"] is None

    def test_activity_covers_every_audited_model(self):
        editor = UserFactory(first_name="", last_name="", username="clerk@example.org")
        teacher = registered_teacher(teacher_registration_number="TR26-ACT-1", created_by=editor)
        SchoolStaffAssignmentFactory(school_staff=teacher)
        SystemUserFactory()
        registration = TeacherRegistrationFactory(approved_staff_profile=teacher)

        rows, next_since = warehouse.activity()
        assert next_since is None
        by_type = {r["record_type"]: r for r in rows}
        assert {"school_staff", "school_staff_assignment", "system_user", "teacher_registration"} <= set(by_type)
        assert by_type["school_staff"]["label"] == "TR26-ACT-1"
        assert by_type["school_staff"]["created_by"] == "clerk@example.org"  # username fallback
        assert by_type["school_staff_assignment"]["staff_id"] == teacher.pk
        assert by_type["teacher_registration"]["registration_id"] == registration.pk
        assert by_type["teacher_registration"]["staff_id"] == teacher.pk

    def test_activity_since_is_inclusive_and_paged(self):
        a = SchoolStaffFactory()
        b = SchoolStaffFactory()
        SchoolStaff.objects.filter(pk=a.pk).update(last_updated_at=datetime(2026, 1, 1, tzinfo=UTC))
        SchoolStaff.objects.filter(pk=b.pk).update(last_updated_at=datetime(2026, 1, 2, tzinfo=UTC))

        rows, next_since = warehouse.activity(limit=1)
        assert rows[0]["record_id"] == a.pk and next_since == datetime(2026, 1, 1, tzinfo=UTC)
        rows, _ = warehouse.activity(since=next_since, limit=10)
        assert [r["record_id"] for r in rows] == [a.pk, b.pk]

        newest = warehouse.recent_activity(limit=1)
        assert newest[0]["record_id"] == b.pk


class TestSummaryAndVersion:
    def test_summary_shape(self):
        status = EmisTeacherRegistrationStatusFactory(code="PROV", label="Provisional")
        island = EmisIslandFactory(code="BET", label="Betio")
        teacher = registered_teacher(teacher_registration_status=status, home_island=island)
        SchoolStaffAssignmentFactory(school_staff=teacher, school=EmisSchoolFactory(active=True))
        SchoolStaffFactory(staff_type=SchoolStaff.NON_TEACHING_STAFF)
        TeacherRegistrationFactory(submitted=True)
        TeacherRegistrationFactory(status=constants.REJECTED)

        s = warehouse.summary()
        assert s["schema_version"] == 1
        assert s["staff"] == {
            "total": 2, "teaching": 1, "non_teaching": 1, "unassigned_to_school": 1, "added_last_30_days": 2,
        }
        assert s["active_schools"] >= 1
        assert s["applications"]["total"] == 2
        by_status = {r["code"]: r for r in s["applications"]["by_status"]}
        assert set(by_status) == {c for c, _ in constants.REGISTRATION_APPLICATION_STATUS_CHOICES}
        assert by_status[constants.SUBMITTED]["count"] == 1
        assert by_status[constants.SUBMITTED]["label"] == "Submitted"
        assert by_status[constants.DRAFT]["count"] == 0
        assert s["registration_status"] == [{"code": "PROV", "label": "Provisional", "count": 1}]
        assert s["home_island"] == [{"code": "BET", "label": "Betio", "count": 1}]
        assert s["expiring"] == []

        schools = warehouse.school_staff_counts(limit=10)
        assert schools[0]["staff_count"] == 1 and schools[0]["registered_teachers"] == 1

    def test_version_counts_and_last_change(self):
        registration = TeacherRegistrationFactory(submitted=True)
        entry = log(registration, constants.SUBMITTED, changed_at=datetime(2099, 1, 1, tzinfo=UTC))
        registered_teacher()

        v = warehouse.version()
        assert v["app"] == warehouse.APP_NAME
        assert v["counts"] == {"registered_teachers": 1, "open_applications": 1, "events": 1}
        assert v["last_change_at"] == datetime(2099, 1, 1, tzinfo=UTC)
        assert entry.pk  # the change log row is what moved last_change_at


class TestDashboardUsesWarehouse:
    def test_kpis_and_activity_feed(self, client):
        admin = system_user(p.GROUP_SYSTEM_ADMINS)
        client.force_login(admin)
        teacher = registered_teacher(teacher_registration_number="TR26-DSH-1")
        TeacherRegistrationFactory(ready=True)
        TeacherRegistrationFactory(status=constants.REJECTED)

        response = client.get(reverse("dashboard"))
        assert response.status_code == 200
        ctx = response.context
        assert ctx["staff_teacher_count"] == 1
        assert ctx["pending_reg_ready_for_approval"] == 1
        assert ctx["pending_reg_rejected"] == 1
        assert ctx["pending_reg_total"] == 2
        events = ctx["recent_events"]
        staff_event = next(e for e in events if e["entity"] == "School staff: TR26-DSH-1")
        assert staff_event["action"] == "Created"
        assert staff_event["url"] == reverse("core:staff_detail", args=[teacher.pk])
        assert any(e["entity"].startswith("Teacher registration:") and e["url"] is None for e in events)

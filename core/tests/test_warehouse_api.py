"""
/api/warehouse/ feed (core/api.py): auth, shapes, cursors, CSV and errors.

Counting rules live in test_warehouse.py; here we pin what a consumer sees on
the wire per docs/plans/kemis-data-feed.md, section 2.
"""

import csv
import io
import json
from datetime import datetime, timezone as dt_timezone

import pytest
from django.urls import reverse

from core.models import SchoolStaff
from core.tests.factories import SchoolStaffFactory, UserFactory
from core.tests.test_warehouse import log, registered_teacher
from teacher_registration import constants
from teacher_registration.tests.factories import TeacherRegistrationFactory

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc
AUTH = {"HTTP_AUTHORIZATION": "Bearer test-warehouse-key"}


def get(client, name, data=None, **extra):
    return client.get(reverse(f"warehouse_api:{name}"), data or {}, **{**AUTH, **extra})


def body(response):
    assert response["Content-Type"].startswith("application/json")
    return json.loads(response.content)


class TestAuth:
    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"HTTP_AUTHORIZATION": "Bearer wrong-key"},
            {"HTTP_AUTHORIZATION": "Basic test-warehouse-key"},
            {"HTTP_AUTHORIZATION": "test-warehouse-key"},
            {"HTTP_AUTHORIZATION": "Bearer "},
        ],
    )
    def test_missing_or_bad_key_is_401(self, client, headers):
        response = client.get(reverse("warehouse_api:version"), **headers)
        assert response.status_code == 401
        assert body(response) == {"detail": "a valid bearer key is required"}
        assert response["WWW-Authenticate"].startswith("Bearer")

    def test_any_configured_key_works(self, client):
        for key in ("test-warehouse-key", "test-warehouse-key-rotated"):
            response = client.get(reverse("warehouse_api:version"), HTTP_AUTHORIZATION=f"Bearer {key}")
            assert response.status_code == 200, key

    def test_no_keys_configured_switches_the_feed_off(self, client, settings):
        settings.WAREHOUSE_API_KEYS = []
        assert get(client, "version").status_code == 401

    def test_session_login_is_not_enough(self, client):
        client.force_login(UserFactory(is_superuser=True, is_staff=True))
        assert client.get(reverse("warehouse_api:version")).status_code == 401

    def test_only_get(self, client):
        response = client.post(reverse("warehouse_api:version"), **AUTH)
        assert response.status_code == 405
        assert response["Allow"] == "GET"

    def test_unknown_route_is_json_404(self, client):
        response = client.get("/api/warehouse/teacherregistration/nope", **AUTH)
        assert response.status_code == 404
        assert body(response) == {"detail": "unknown warehouse endpoint"}

    def test_responses_are_not_cacheable(self, client):
        assert "no-store" in get(client, "version")["Cache-Control"]


class TestObjects:
    def test_version(self, client):
        registration = TeacherRegistrationFactory(submitted=True)
        log(registration, constants.SUBMITTED, changed_at=datetime(2099, 1, 1, 12, 30, tzinfo=UTC))
        registered_teacher()

        payload = body(get(client, "version"))
        assert payload["app"] == "pacific-emis-teacher-registration"
        assert payload["schema_version"] == 1
        assert payload["generated_at"].endswith("Z")
        assert payload["last_change_at"] == "2099-01-01T12:30:00Z"
        assert payload["counts"] == {"registered_teachers": 1, "open_applications": 1, "events": 1}

    def test_summary(self, client):
        registered_teacher()
        TeacherRegistrationFactory(ready=True)

        payload = body(get(client, "summary"))
        assert set(payload) == {
            "schema_version", "generated_at", "as_of", "staff", "active_schools",
            "applications", "registration_status", "home_island", "expiring",
        }
        assert payload["staff"]["teaching"] == 1
        assert payload["applications"]["total"] == 1
        by_status = {r["code"]: r["count"] for r in payload["applications"]["by_status"]}
        assert by_status[constants.READY_FOR_APPROVAL] == 1
        assert payload["as_of"] == payload["generated_at"][:10]

    def test_objects_are_json_only(self, client):
        response = get(client, "summary", {"format": "csv"})
        assert response.status_code == 400
        assert body(response) == {"detail": "this endpoint is JSON only"}


class TestLists:
    def test_monthly_rows(self, client):
        teacher = registered_teacher(
            registration_granted_at=datetime(2026, 3, 10, tzinfo=UTC),
            registration_valid_until=datetime(2028, 3, 10, tzinfo=UTC),
        )
        # The month range starts at the earliest record, so the grant must not predate it.
        SchoolStaff.objects.filter(pk=teacher.pk).update(created_at=datetime(2026, 3, 1, tzinfo=UTC))
        payload = body(get(client, "monthly"))
        assert payload["count"] == len(payload["results"]) > 0
        row = payload["results"][0]
        assert set(row) == {"month", "submitted", "approved", "rejected", "granted", "expiring"}
        granted = {r["month"]: r["granted"] for r in payload["results"]}
        assert granted["2026-03"] == 1

    def test_current_rows_and_date_formats(self, client):
        teacher = registered_teacher(
            teacher_registration_number="TR26-API-1",
            registration_granted_at=datetime(2026, 1, 15, tzinfo=UTC),
            registration_valid_until=datetime(2029, 1, 15, 23, 59, tzinfo=UTC),
        )
        SchoolStaff.objects.filter(pk=teacher.pk).update(created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))

        payload = body(get(client, "current"))
        assert payload["count"] == 1
        (row,) = payload["results"]
        assert row["registration_number"] == "TR26-API-1"
        assert row["granted_at"] == "2026-01-15"
        assert row["valid_until"] == "2029-01-15"
        assert row["created_at"] == "2026-01-02T03:04:05Z"
        assert row["school_no"] is None  # null, not ""
        assert "staff_id" in row and "days_to_expiry" in row

    def test_unknown_format(self, client):
        response = get(client, "current", {"format": "xml"})
        assert response.status_code == 400
        assert body(response) == {"detail": "format must be json or csv"}

    def test_csv(self, client):
        registered_teacher(teacher_registration_number="TR26-CSV-1")
        response = get(client, "current", {"format": "csv"})
        assert response.status_code == 200
        assert response["Content-Type"] == "text/csv; charset=utf-8"
        assert response["Content-Disposition"] == 'attachment; filename="teacherregistration-current.csv"'
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
        assert rows[0][:2] == ["registration_number", "application_status"]
        assert rows[1][0] == "TR26-CSV-1"
        assert rows[1][rows[0].index("school_no")] == ""  # null becomes empty cell

    def test_csv_with_no_rows_is_empty(self, client):
        response = get(client, "current", {"format": "csv"})
        assert response.status_code == 200
        assert response.content == b""


class TestEvents:
    def test_cursor_paging(self, client):
        reviewer = UserFactory(first_name="Ana", last_name="Reviewer")
        registration = TeacherRegistrationFactory()
        first = log(registration, constants.SUBMITTED, by=reviewer, changed_at=datetime(2026, 2, 1, tzinfo=UTC))
        second = log(registration, constants.UNDER_REVIEW)

        payload = body(get(client, "events", {"limit": 1}))
        assert payload["count"] == 1
        assert payload["next_after_id"] == first.pk
        row = payload["results"][0]
        assert row["id"] == first.pk
        assert row["changed_at"] == "2026-02-01T00:00:00Z"
        assert row["changed_by"] == "Ana Reviewer"
        assert row["changed_by_id"] == reviewer.pk
        assert row["field"] == "status"
        assert row["new_value"] == constants.SUBMITTED

        payload = body(get(client, "events", {"after_id": payload["next_after_id"], "limit": 1000}))
        assert [r["id"] for r in payload["results"]] == [second.pk]
        assert payload["next_after_id"] is None

    @pytest.mark.parametrize(
        ("params", "detail"),
        [
            ({"after_id": "abc"}, "after_id must be an integer"),
            ({"after_id": "-1"}, "after_id must be at least 0"),
            ({"limit": "0"}, "limit must be at least 1"),
            ({"limit": "ten"}, "limit must be an integer"),
        ],
    )
    def test_bad_parameters(self, client, params, detail):
        response = get(client, "events", params)
        assert response.status_code == 400
        assert body(response) == {"detail": detail}

    def test_limit_is_capped(self, client):
        registration = TeacherRegistrationFactory()
        log(registration, constants.SUBMITTED)
        payload = body(get(client, "events", {"limit": 999999}))
        assert payload["count"] == 1 and payload["next_after_id"] is None

    def test_csv(self, client):
        log(TeacherRegistrationFactory(), constants.SUBMITTED)
        response = get(client, "events", {"format": "csv"})
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
        assert rows[0][0] == "id" and len(rows) == 2


class TestActivity:
    def test_since_is_inclusive_and_paged(self, client):
        a, b = SchoolStaffFactory(), SchoolStaffFactory()
        SchoolStaff.objects.filter(pk=a.pk).update(last_updated_at=datetime(2026, 1, 1, tzinfo=UTC))
        SchoolStaff.objects.filter(pk=b.pk).update(last_updated_at=datetime(2026, 1, 2, 10, 0, tzinfo=UTC))

        payload = body(get(client, "activity", {"limit": 1}))
        assert payload["next_since"] == "2026-01-01T00:00:00Z"
        assert payload["results"][0]["record_id"] == a.pk
        assert set(payload["results"][0]) == {
            "record_type", "record_id", "label", "staff_id", "registration_id", "created_at",
            "created_by_id", "created_by", "last_updated_at", "last_updated_by_id", "last_updated_by",
        }

        payload = body(get(client, "activity", {"since": payload["next_since"]}))
        assert [r["record_id"] for r in payload["results"]] == [a.pk, b.pk]
        assert payload["next_since"] is None

        # Offsets other than Z are honoured; naive values are read as UTC.
        payload = body(get(client, "activity", {"since": "2026-01-02T22:00:00+12:00"}))
        assert [r["record_id"] for r in payload["results"]] == [b.pk]
        payload = body(get(client, "activity", {"since": "2026-01-02T10:00:00"}))
        assert [r["record_id"] for r in payload["results"]] == [b.pk]

    def test_bad_since(self, client):
        response = get(client, "activity", {"since": "yesterday"})
        assert response.status_code == 400
        assert body(response)["detail"].startswith("since must be an ISO 8601 datetime")

    def test_csv(self, client):
        SchoolStaffFactory()
        response = get(client, "activity", {"format": "csv"})
        assert response["Content-Disposition"] == 'attachment; filename="teacherregistration-activity.csv"'
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
        assert rows[0][0] == "record_type"

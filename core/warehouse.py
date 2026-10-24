"""
Read access to the `warehouse` schema (issue #119).

The views are defined in core/migrations/0031_warehouse_views.py. This module
is the only place that queries them, and it returns plain dicts so the same
data serves the Teacher Registration Summary report, the dashboard and the
/api/warehouse/ endpoints without any of them re-deriving a figure.

Shapes follow docs/plans/kemis-data-feed.md, section 2.
"""

from django.db import connection
from django.utils import timezone

from teacher_registration import constants

SCHEMA_VERSION = 1
APP_NAME = "pacific-emis-teacher-registration"

APPLICATION_STATUS_LABELS = dict(constants.REGISTRATION_APPLICATION_STATUS_CHOICES)

DEFAULT_PAGE = 1000
MAX_PAGE = 5000


def _rows(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _one(sql, params=None):
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _clamp_limit(limit):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_PAGE
    return max(1, min(limit, MAX_PAGE))


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


def staff_summary():
    """Headline counts: total, teaching, non_teaching, unassigned_to_school, ..."""
    return _one("SELECT * FROM warehouse.staff_summary")


def application_status_counts():
    """Every application status in workflow order, zero-filled, with labels."""
    counts = {r["code"]: r["count"] for r in _rows("SELECT code, count FROM warehouse.application_status_counts")}
    return [
        {"code": code, "label": label, "count": counts.get(code, 0)}
        for code, label in constants.REGISTRATION_APPLICATION_STATUS_CHOICES
    ]


def registration_status_counts():
    return _rows(
        "SELECT code, label, count FROM warehouse.registration_status_counts ORDER BY count DESC, label"
    )


def home_island_counts():
    return _rows("SELECT code, label, count FROM warehouse.home_island_counts ORDER BY count DESC, label")


def school_staff_counts(limit=None):
    sql = (
        "SELECT school_no, school_name, staff_count, registered_teachers "
        "FROM warehouse.school_staff_counts ORDER BY staff_count DESC, school_name"
    )
    if limit:
        return _rows(sql + " LIMIT %s", [int(limit)])
    return _rows(sql)


def monthly():
    """One row per calendar month (UTC); `month_start` is a tz-aware datetime."""
    return _rows(
        "SELECT month, month_start, submitted, approved, rejected, granted, expiring "
        "FROM warehouse.registration_monthly ORDER BY month_start"
    )


def expiring(months=12, rows=None):
    """Registrations expiring per month from the current month, next `months` months."""
    rows = monthly() if rows is None else rows
    start = _month_start(timezone.now())
    end = _add_months(start, months)
    return [
        {"month": r["month"], "count": r["expiring"]}
        for r in rows
        if start <= r["month_start"] < end and r["expiring"]
    ]


def summary():
    """The contract's `summary` object; also what the report and dashboard render."""
    staff = staff_summary()
    by_status = application_status_counts()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": timezone.now(),
        "as_of": timezone.now().date(),
        "staff": {
            "total": staff["total"],
            "teaching": staff["teaching"],
            "non_teaching": staff["non_teaching"],
            "unassigned_to_school": staff["unassigned_to_school"],
            "added_last_30_days": staff["added_last_30_days"],
        },
        "active_schools": staff["active_schools"],
        "applications": {
            "total": sum(r["count"] for r in by_status),
            "by_status": by_status,
        },
        "registration_status": registration_status_counts(),
        "home_island": home_island_counts(),
        "expiring": expiring(),
    }


# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------


def current():
    """One row per registered teaching staff member (approved or expired)."""
    return _rows(
        "SELECT registration_number, application_status, registration_status_code, "
        "registration_status_label, granted_at, valid_until, days_to_expiry, gender_code, "
        "birth_year, home_island_code, home_island_label, school_no, school_name, "
        "job_title_code, highest_qualification, years_of_experience, staff_id, "
        "created_at, last_updated_at "
        "FROM warehouse.registration_current ORDER BY registration_number, staff_id"
    )


def events(after_id=0, limit=DEFAULT_PAGE):
    """Workflow change log after `after_id`, oldest first. Returns (rows, next_after_id)."""
    limit = _clamp_limit(limit)
    rows = _rows(
        "SELECT id, changed_at, registration_id, registration_type, registration_number, staff_id, "
        "field, old_value, new_value, changed_by_id, changed_by, notes "
        "FROM warehouse.registration_events WHERE id > %s ORDER BY id LIMIT %s",
        [int(after_id or 0), limit],
    )
    next_after_id = rows[-1]["id"] if len(rows) == limit else None
    return rows, next_after_id


def activity(since=None, limit=DEFAULT_PAGE):
    """Record activity at or after `since`, oldest first. Returns (rows, next_since)."""
    limit = _clamp_limit(limit)
    where, params = "", []
    if since is not None:
        where = "WHERE last_updated_at >= %s "
        params.append(since)
    rows = _rows(
        "SELECT record_type, record_id, label, staff_id, registration_id, created_at, created_by_id, "
        "created_by, last_updated_at, last_updated_by_id, last_updated_by "
        f"FROM warehouse.record_activity {where}"
        "ORDER BY last_updated_at, record_type, record_id LIMIT %s",
        params + [limit],
    )
    next_since = rows[-1]["last_updated_at"] if len(rows) == limit else None
    return rows, next_since


def recent_activity(limit=10):
    """Newest records first, for the dashboard feed."""
    return _rows(
        "SELECT record_type, record_id, label, staff_id, registration_id, created_at, created_by, "
        "last_updated_at, last_updated_by "
        "FROM warehouse.record_activity ORDER BY last_updated_at DESC, record_type, record_id LIMIT %s",
        [int(limit)],
    )


def last_change_at():
    row = _one(
        "SELECT GREATEST((SELECT max(last_updated_at) FROM warehouse.record_activity), "
        "(SELECT max(changed_at) FROM warehouse.registration_events)) AS last_change_at"
    )
    return row["last_change_at"] if row else None


def version():
    staff = staff_summary()
    return {
        "app": APP_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": timezone.now(),
        "last_change_at": last_change_at(),
        "counts": {
            "registered_teachers": staff["registered_teachers"],
            "open_applications": staff["open_applications"],
            "events": staff["events"],
        },
    }


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _month_start(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(dt, months):
    month_index = dt.month - 1 + months
    return dt.replace(year=dt.year + month_index // 12, month=month_index % 12 + 1)


def last_months(rows, count, now=None):
    """
    The `count` most recent months up to and including the current one, from
    monthly() rows. Months before the first record are padded with zeros so a
    chart always has `count` bars.
    """
    this_month = _month_start(now or timezone.now())
    by_start = {r["month_start"]: r for r in rows}
    out = []
    for offset in range(count - 1, -1, -1):
        start = _add_months(this_month, -offset)
        out.append(
            by_start.get(start)
            or {
                "month": start.strftime("%Y-%m"),
                "month_start": start,
                "submitted": 0,
                "approved": 0,
                "rejected": 0,
                "granted": 0,
                "expiring": 0,
            }
        )
    return out


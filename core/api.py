"""
/api/warehouse/ endpoints for central KEMIS (issue #119).

A read-only, token-authenticated feed over the `warehouse` schema. Every view
reads through core.warehouse so the numbers are the same ones the summary
report and the dashboard show. Contract: docs/plans/kemis-data-feed.md, section 2.

Authentication is a bearer key from the WAREHOUSE_API_KEYS environment variable
(comma-separated so a key can be rotated). No key configured means the feed is
switched off: every request gets 401.
"""

import csv
import hmac
import json
import logging
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from core import warehouse

logger = logging.getLogger(__name__)

FEED_NAME = "teacherregistration"


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _iso(value):
    """Datetimes as ISO 8601 in UTC with a Z suffix; dates as YYYY-MM-DD."""
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value, dt_timezone.utc)
        return value.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


class FeedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (datetime, date)):
            return _iso(o)
        if isinstance(o, Decimal):
            return int(o) if o == o.to_integral_value() else float(o)
        return super().default(o)


class BadRequest(Exception):
    """A query parameter the client got wrong; rendered as a 400 with the message."""


def _json(payload, status=200):
    return JsonResponse(payload, status=status, encoder=FeedJSONEncoder, json_dumps_params={"ensure_ascii": False})


def _error(detail, status):
    return _json({"detail": detail}, status=status)


def _envelope(results, **extra):
    payload = {
        "schema_version": warehouse.SCHEMA_VERSION,
        "generated_at": timezone.now(),
        "count": len(results),
    }
    payload.update(extra)
    payload["results"] = results
    return payload


def _csv(rows, filename):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    writer = csv.writer(response)
    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow("" if v is None else _iso(v) for v in row.values())
    return response


def _render_list(request, rows, filename, **extra):
    fmt = request.GET.get("format", "json").lower()
    if fmt == "csv":
        return _csv(rows, filename)
    if fmt != "json":
        raise BadRequest("format must be json or csv")
    return _json(_envelope(rows, **extra))


def _render_object(request, payload):
    fmt = request.GET.get("format", "json").lower()
    if fmt != "json":
        raise BadRequest("this endpoint is JSON only")
    return _json(payload)


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


def _int_param(request, name, default, minimum):
    raw = request.GET.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        raise BadRequest(f"{name} must be an integer")
    if value < minimum:
        raise BadRequest(f"{name} must be at least {minimum}")
    return value


def _limit_param(request):
    value = _int_param(request, "limit", warehouse.DEFAULT_PAGE, 1)
    return min(value, warehouse.MAX_PAGE)


def _since_param(request):
    raw = request.GET.get("since")
    if raw in (None, ""):
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        raise BadRequest("since must be an ISO 8601 datetime, e.g. 2026-10-24T03:10:00Z")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    return parsed


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def _presented_key(request):
    header = request.headers.get("Authorization", "")
    scheme, _, key = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return key.strip()


def _key_is_valid(presented):
    if not presented:
        return False
    # Compare against every configured key so timing does not reveal which one matched.
    matched = False
    for configured in settings.WAREHOUSE_API_KEYS:
        if hmac.compare_digest(presented.encode(), configured.encode()):
            matched = True
    return matched


def feed_view(view):
    """Bearer-key auth, GET only, JSON errors. Applied to every /api/warehouse/ view."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method != "GET":
            response = _error("method not allowed", 405)
            response["Allow"] = "GET"
            return response
        if not _key_is_valid(_presented_key(request)):
            logger.warning("warehouse API: rejected request to %s from %s", request.path, _client_ip(request))
            response = _error("a valid bearer key is required", 401)
            response["WWW-Authenticate"] = 'Bearer realm="warehouse"'
            return response
        try:
            return view(request, *args, **kwargs)
        except BadRequest as exc:
            return _error(str(exc), 400)

    return never_cache(csrf_exempt(wrapper))


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


@feed_view
def version(request):
    return _render_object(request, warehouse.version())


@feed_view
def summary(request):
    return _render_object(request, warehouse.summary())


@feed_view
def monthly(request):
    rows = warehouse.monthly()
    for row in rows:
        row.pop("month_start", None)  # internal sort key; the contract exposes `month`
    return _render_list(request, rows, f"{FEED_NAME}-monthly")


@feed_view
def current(request):
    return _render_list(request, warehouse.current(), f"{FEED_NAME}-current")


@feed_view
def events(request):
    after_id = _int_param(request, "after_id", 0, 0)
    rows, next_after_id = warehouse.events(after_id=after_id, limit=_limit_param(request))
    return _render_list(request, rows, f"{FEED_NAME}-events", next_after_id=next_after_id)


@feed_view
def activity(request):
    rows, next_since = warehouse.activity(since=_since_param(request), limit=_limit_param(request))
    return _render_list(request, rows, f"{FEED_NAME}-activity", next_since=next_since)


@feed_view
def not_found(request, *args, **kwargs):
    return _error("unknown warehouse endpoint", 404)

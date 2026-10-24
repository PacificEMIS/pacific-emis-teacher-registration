"""
URL configuration for the /api/warehouse/ feed (core/api.py).

Kept out of the `core` namespace on purpose: these views answer with bearer-key
auth and JSON errors, not the login redirects the access matrix expects.
"""

from django.urls import path, re_path

from core import api

app_name = "warehouse_api"

urlpatterns = [
    path("version", api.version, name="version"),
    path(f"{api.FEED_NAME}/summary", api.summary, name="summary"),
    path(f"{api.FEED_NAME}/monthly", api.monthly, name="monthly"),
    path(f"{api.FEED_NAME}/current", api.current, name="current"),
    path(f"{api.FEED_NAME}/events", api.events, name="events"),
    path(f"{api.FEED_NAME}/activity", api.activity, name="activity"),
    # Anything else under /api/warehouse/ is a JSON 404, not the HTML page.
    re_path(r"^.*$", api.not_found, name="not_found"),
]

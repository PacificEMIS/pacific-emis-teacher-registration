"""Project-wide date display formatting (house style, "profile B").

A single source of truth for how dates are shown so the format cannot drift
across templates and views:

- Tables, detail lists, and form inputs use ISO ``YYYY-MM-DD`` directly via the
  built-in filter, e.g. ``{{ value|date:"Y-m-d" }}`` -- ISO is already
  unambiguous and sorts naturally, so it needs no helper.
- Prose, emails, PDFs, and certificates use the spelled-month style
  ``18 Jun 2026`` produced here, so a reader can never misread it as ``mm/dd``
  vs ``dd/mm``.

Use the ``app_date`` template filter (``{% load dates %}``) in templates and the
``app_date`` function in Python (views, generated sentences, emails).
"""

from django.utils.dateformat import format as _dj_format

# Django date-format spec for the prose style, e.g. "18 Jun 2026".
PROSE_DATE_FORMAT = "j M Y"


def app_date(value):
    """Format a date/datetime in the house prose style ("18 Jun 2026").

    Returns an empty string for ``None``/falsy values so it can be used inline
    in f-strings and templates without guarding every call.
    """
    if not value:
        return ""
    return _dj_format(value, PROSE_DATE_FORMAT)

from django import template

from core.dateformat import app_date as _app_date

register = template.Library()


@register.filter
def app_date(value):
    """Render a date/datetime in the house prose style: "18 Jun 2026".

    Use in prose, emails, PDFs, and certificates. For dates in tables, detail
    lists, and form inputs keep the ISO form ``{{ value|date:"Y-m-d" }}``.
    """
    return _app_date(value)

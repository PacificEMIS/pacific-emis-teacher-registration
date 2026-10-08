"""Unit tests for house-style date formatting and the small template filters."""

from datetime import date, datetime, timezone as dt_timezone

import pytest
from django import forms
from django.template import Context, Template

from core.dateformat import PROSE_DATE_FORMAT, app_date


def render(source, **context):
    return Template(source).render(Context(context))


class TestAppDate:
    def test_formats_date_in_prose_style(self):
        assert app_date(date(2026, 6, 18)) == "18 Jun 2026"

    def test_formats_datetime_in_prose_style(self):
        value = datetime(2026, 6, 18, 23, 59, tzinfo=dt_timezone.utc)
        assert app_date(value) == "18 Jun 2026"

    def test_no_zero_padding_on_day(self):
        assert app_date(date(2026, 1, 5)) == "5 Jan 2026"

    @pytest.mark.parametrize("value", [None, "", 0])
    def test_falsy_values_render_empty(self, value):
        assert app_date(value) == ""

    def test_format_constant_is_the_single_source_of_truth(self):
        assert PROSE_DATE_FORMAT == "j M Y"


class TestDatesTemplateFilter:
    def test_filter_matches_python_helper(self):
        assert render("{% load dates %}{{ d|app_date }}", d=date(2026, 6, 18)) == "18 Jun 2026"

    def test_filter_handles_none(self):
        assert render("{% load dates %}[{{ d|app_date }}]", d=None) == "[]"


class TestDictExtras:
    def test_get_item_returns_value(self):
        assert render("{% load dict_extras %}{{ d|get_item:'a' }}", d={"a": "alpha"}) == "alpha"

    def test_get_item_missing_key_is_none(self):
        assert render("{% load dict_extras %}[{{ d|get_item:'zz' }}]", d={"a": 1}) == "[None]"

    def test_get_item_on_non_mapping_is_none(self):
        assert render("{% load dict_extras %}[{{ d|get_item:'a' }}]", d=42) == "[None]"

    def test_getfield_reads_attribute(self):
        class Obj:
            code = "K01"

        assert render("{% load dict_extras %}{{ o|getfield:'code' }}", o=Obj()) == "K01"

    def test_getfield_missing_attribute_is_empty(self):
        assert render("{% load dict_extras %}[{{ o|getfield:'nope' }}]", o=object()) == "[]"


class SampleForm(forms.Form):
    first_name = forms.CharField()


class TestFormExtras:
    def test_form_field_returns_bound_field(self):
        html = render("{% load form_extras %}{{ f|form_field:'first_name' }}", f=SampleForm())
        assert 'name="first_name"' in html

    def test_form_field_unknown_name_is_none(self):
        assert render("{% load form_extras %}[{{ f|form_field:'nope' }}]", f=SampleForm()) == "[None]"

    def test_obj_attr_reads_attribute(self):
        class Obj:
            checklist_applicant_photo = True

        html = render("{% load form_extras %}{{ o|obj_attr:'checklist_applicant_photo' }}", o=Obj())
        assert html == "True"

    def test_obj_attr_missing_attribute_is_none(self):
        assert render("{% load form_extras %}[{{ o|obj_attr:'nope' }}]", o=object()) == "[None]"

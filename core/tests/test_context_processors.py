"""
The deployment name split into the system and its environment, and the
not-production warning every page carries outside production.
"""

import pytest
from django.urls import reverse

from pacemis_teacher_registration.context_processors import emis_context


@pytest.mark.parametrize(
    ("context", "name", "environment"),
    [
        ("KEMIS (Dev)", "KEMIS", "Dev"),
        ("KEMIS (Test)", "KEMIS", "Test"),
        ("FEDEMIS ( Staging )", "FEDEMIS", "Staging"),
        ("KEMIS", "KEMIS", None),
        ("Pacific EMIS", "Pacific EMIS", None),
    ],
)
def test_context_splits_into_name_and_environment(settings, context, name, environment):
    settings.EMIS = {**settings.EMIS, "CONTEXT": context}

    result = emis_context(None)

    assert result["emis_context"] == context
    assert result["emis_name"] == name
    assert result["emis_environment"] == environment


def test_logo_is_the_first_word_of_the_context(settings):
    settings.EMIS = {**settings.EMIS, "CONTEXT": "KEMIS (Dev)"}

    assert emis_context(None)["emis_logo"] == "kemis"


def test_empty_context_yields_nothing(settings):
    settings.EMIS = {**settings.EMIS, "CONTEXT": ""}

    result = emis_context(None)

    assert result == {
        "emis_context": None,
        "emis_logo": "logo",
        "emis_name": None,
        "emis_environment": None,
    }


@pytest.mark.django_db
def test_pages_outside_production_warn_everywhere(client, settings):
    settings.EMIS = {**settings.EMIS, "CONTEXT": "KEMIS (Test)"}

    response = client.get(reverse("teacher_registration:public_landing"))

    html = response.content.decode()
    assert "app-env-banner" in html
    assert "TEST environment" in html
    assert "not the production KEMIS" in html
    assert "[TEST]" in html.split("<title>")[1].split("</title>")[0]


@pytest.mark.django_db
def test_production_pages_carry_no_warning(client, settings):
    settings.EMIS = {**settings.EMIS, "CONTEXT": "KEMIS"}

    response = client.get(reverse("teacher_registration:public_landing"))

    html = response.content.decode()
    assert "app-env-banner" not in html
    assert "app-env-badge" not in html
    assert "not production" not in html

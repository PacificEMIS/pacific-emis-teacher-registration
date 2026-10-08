"""
Smoke tests: prove the test harness, database, and project wiring work.

If these fail, nothing else in the suite is trustworthy.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse


def test_system_checks_pass():
    out = StringIO()
    call_command("check", stdout=out)
    assert "System check identified no issues" in out.getvalue()


@pytest.mark.django_db
def test_no_missing_migrations():
    """Model changes must always be accompanied by a migration."""
    out = StringIO()
    call_command("makemigrations", "--check", "--dry-run", stdout=out)
    assert "No changes detected" in out.getvalue()


@pytest.mark.django_db
def test_public_landing_renders_for_anonymous_user(client):
    response = client.get(reverse("teacher_registration:public_landing"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_dashboard_redirects_anonymous_user_to_login(client):
    response = client.get(reverse("dashboard"))
    assert response.status_code == 302
    assert reverse("account_login") in response["Location"]

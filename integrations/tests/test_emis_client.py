"""EmisClient tests against a mocked EMIS API (no network)."""

import pytest
import requests
import time_machine
from django.conf import settings

from integrations.emis_client import EmisClient

LOGIN_URL = settings.EMIS["LOGIN_URL"]
LOOKUPS_URL = settings.EMIS["LOOKUPS_URL"]


@pytest.fixture
def api(requests_mock):
    requests_mock.post(LOGIN_URL, json={"access_token": "tok-1"})
    requests_mock.get(LOOKUPS_URL, json={"schoolCodes": [{"C": "S1", "N": "One"}]})
    return requests_mock


def test_settings_point_at_a_non_routable_host():
    assert settings.EMIS["BASE_URL"] == "https://emis.invalid"


def test_fetches_token_with_password_grant_then_calls_lookups(api):
    payload = EmisClient().get_core_lookups()

    assert payload == {"schoolCodes": [{"C": "S1", "N": "One"}]}
    login, lookups = api.request_history
    assert login.method == "POST"
    assert "grant_type=password" in login.text
    assert "username=test-user" in login.text
    assert login.timeout == settings.EMIS["TIMEOUT_SECONDS"]
    assert login.verify == settings.EMIS["VERIFY_SSL"]
    assert lookups.headers["Authorization"] == "Bearer tok-1"


def test_accepts_camel_case_token_key(api):
    api.post(LOGIN_URL, json={"accessToken": "tok-camel"})
    EmisClient().get_core_lookups()
    assert api.request_history[-1].headers["Authorization"] == "Bearer tok-camel"


def test_token_is_cached_for_thirty_minutes(api):
    client = EmisClient()
    with time_machine.travel("2026-01-01 10:00:00", tick=False) as traveller:
        client.get_core_lookups()
        traveller.shift(29 * 60)
        client.get_core_lookups()
        assert len([r for r in api.request_history if r.method == "POST"]) == 1
        traveller.shift(2 * 60)
        client.get_core_lookups()
        assert len([r for r in api.request_history if r.method == "POST"]) == 2


def test_login_failure_raises(api):
    api.post(LOGIN_URL, status_code=401, json={"error": "invalid_grant"})
    with pytest.raises(requests.HTTPError):
        EmisClient().get_core_lookups()


def test_lookup_failure_raises(api):
    api.get(LOOKUPS_URL, status_code=500)
    with pytest.raises(requests.HTTPError):
        EmisClient().get_core_lookups()


def test_connection_error_propagates(api):
    api.post(LOGIN_URL, exc=requests.ConnectionError("unreachable"))
    with pytest.raises(requests.ConnectionError):
        EmisClient().get_core_lookups()

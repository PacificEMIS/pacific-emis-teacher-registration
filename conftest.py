"""
Project-wide pytest fixtures.

App-specific fixtures and factories live in each app's tests/ package.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_media_root(settings, tmp_path):
    """Every test writes uploaded files to its own temporary directory."""
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_ROOT.mkdir()


class _InlineThread:
    """Stand-in for threading.Thread that runs the target synchronously.

    core.emails sends notifications on daemon threads. In tests that would
    open a second database connection outside the test transaction and race
    the assertions, so the "thread" runs inline instead. Emails still land in
    django.core.mail.outbox.
    """

    def __init__(self, target=None, daemon=None, args=(), kwargs=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        return None


@pytest.fixture(autouse=True)
def _inline_email_threads(monkeypatch):
    monkeypatch.setattr("core.emails.Thread", _InlineThread)


@pytest.fixture
def google_social_app(db):
    """The allauth Google app row that the login template needs to render."""
    from allauth.socialaccount.models import SocialApp
    from django.contrib.sites.models import Site

    app = SocialApp.objects.create(
        provider="google", name="Google", client_id="test-client", secret="test-secret"
    )
    app.sites.add(Site.objects.get_current())
    return app

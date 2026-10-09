"""allauth adapters and the sign-up signal."""

from types import SimpleNamespace

import pytest
from allauth.account.signals import user_signed_up
from allauth.socialaccount.models import SocialLogin
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from accounts.account_adapter import DomainRestrictedAdapter, EmailAsUsernameSocialAdapter
from accounts.signals import _is_registration_flow, notify_admins_on_signup
from core import permissions as p
from core.tests.factories import UserFactory, add_to_groups

pytestmark = pytest.mark.django_db


def social_login(user=None):
    login = SocialLogin()
    login.user = user or User()
    return login


class TestEmailAsUsernameSocialAdapter:
    def test_email_becomes_username(self):
        adapter = EmailAsUsernameSocialAdapter()
        user = adapter.populate_user(
            None, social_login(), {"email": "Ana@Example.org", "first_name": "Ana", "last_name": "Teata"}
        )
        assert user.username == "Ana@Example.org"
        assert user.email == "Ana@Example.org"
        assert (user.first_name, user.last_name) == ("Ana", "Teata")

    def test_missing_name_parts_become_empty_strings(self):
        """Google omits family_name for single-name accounts; the column is NOT NULL."""
        user = EmailAsUsernameSocialAdapter().populate_user(
            None, social_login(), {"email": "solo@example.org", "first_name": "Solo", "last_name": None}
        )
        assert user.last_name == ""
        user.save()  # must not raise IntegrityError

    def test_no_names_at_all(self):
        user = EmailAsUsernameSocialAdapter().populate_user(None, social_login(), {"email": "x@example.org"})
        assert (user.first_name, user.last_name) == ("", "")

    def test_without_email_falls_back_to_allauth_defaults(self):
        user = EmailAsUsernameSocialAdapter().populate_user(
            None, social_login(), {"username": "nick", "first_name": "N"}
        )
        assert user.username == "nick"
        assert user.email == ""

    def test_configured_as_the_social_adapter(self, settings):
        assert settings.SOCIALACCOUNT_ADAPTER == "accounts.account_adapter.EmailAsUsernameSocialAdapter"
        assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT is True


class TestDomainRestrictedAdapter:
    @staticmethod
    def form(email):
        return SimpleNamespace(cleaned_data={"email": email, "username": email, "password1": "pw-123456"})

    def test_open_for_signup(self):
        assert DomainRestrictedAdapter().is_open_for_signup(None) is True

    def test_no_restriction_by_default(self, settings):
        assert not hasattr(settings, "ALLOWED_SIGNUP_DOMAINS") or not settings.ALLOWED_SIGNUP_DOMAINS
        user = DomainRestrictedAdapter().save_user(None, User(), self.form("x@anything.org"))
        assert user.pk

    def test_rejects_other_domains_when_configured(self, settings):
        settings.ALLOWED_SIGNUP_DOMAINS = ["moe.gov.ki"]
        with pytest.raises(PermissionDenied):
            DomainRestrictedAdapter().save_user(None, User(), self.form("x@gmail.com"))
        assert User.objects.count() == 0

    def test_accepts_allowed_domain_case_insensitively(self, settings):
        settings.ALLOWED_SIGNUP_DOMAINS = ["moe.gov.ki"]
        user = DomainRestrictedAdapter().save_user(None, User(), self.form("Staff@MOE.gov.ki"))
        assert user.pk

    def test_commit_false_does_not_save(self, settings):
        settings.ALLOWED_SIGNUP_DOMAINS = ["moe.gov.ki"]
        user = DomainRestrictedAdapter().save_user(None, User(), self.form("x@moe.gov.ki"), commit=False)
        assert user.pk is None


class TestSignupSignal:
    @pytest.fixture
    def admins(self):
        return add_to_groups(UserFactory(email="admin@example.org"), p.GROUP_ADMINS)

    @staticmethod
    def request(session_next=None, get_next=None):
        factory = RequestFactory()
        request = factory.get("/accounts/google/login/callback/", {"next": get_next} if get_next else {})
        request.session = SessionStore()
        if session_next:
            request.session["next"] = session_next
        return request

    def test_registration_flow_detection(self):
        assert _is_registration_flow(None) is False
        assert _is_registration_flow(self.request()) is False
        assert _is_registration_flow(self.request(session_next="/registration/my-registration/")) is True
        assert _is_registration_flow(self.request(get_next="/registration/start/")) is True
        assert _is_registration_flow(self.request(session_next="/core/staff/")) is False

    def test_signal_notifies_admins_with_pending_users_link(self, admins):
        new_user = UserFactory(email="new@example.org")
        user_signed_up.send(sender=User, request=self.request(), user=new_user)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["admin@example.org"]
        assert "http://testserver/core/pending-users/" in mail.outbox[0].body

    def test_signal_silent_for_registration_flow(self, admins):
        new_user = UserFactory(email="new@example.org")
        user_signed_up.send(
            sender=User, request=self.request(session_next="/registration/my-registration/"), user=new_user
        )
        assert mail.outbox == []

    def test_receiver_without_request(self, admins):
        notify_admins_on_signup(None, UserFactory(email="new@example.org"))
        assert len(mail.outbox) == 1
        assert "pending-users" not in mail.outbox[0].body

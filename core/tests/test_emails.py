"""Email notification tests: recipients, subjects, bodies, and the async wrappers."""

from unittest.mock import patch

import pytest
from django.core import mail

from core import emails, permissions as p
from core.tests.factories import SchoolStaffFactory, UserFactory, add_to_groups
from teacher_registration.tests.factories import TeacherRegistrationFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def managers():
    """Two notification recipients: one Admins, one System Admins."""
    a = add_to_groups(UserFactory(email="a@example.org"), p.GROUP_ADMINS)
    b = add_to_groups(UserFactory(email="b@example.org"), p.GROUP_SYSTEM_ADMINS)
    return a, b


class TestManagerRecipients:
    def test_active_members_with_email_distinct(self, managers):
        a, b = managers
        add_to_groups(a, p.GROUP_SYSTEM_ADMINS)  # in both groups: listed once
        add_to_groups(UserFactory(email="", username="noemail"), p.GROUP_ADMINS)
        add_to_groups(UserFactory(email="inactive@example.org", is_active=False), p.GROUP_ADMINS)
        add_to_groups(UserFactory(email="teacher@example.org"), p.GROUP_TEACHERS)
        assert sorted(emails._get_pending_user_manager_emails()) == ["a@example.org", "b@example.org"]

    def test_no_groups_means_no_recipients(self):
        assert emails._get_pending_user_manager_emails() == []


class TestAdminNotifications:
    def test_new_pending_user(self, managers, settings):
        settings.APP_NAME = "Teacher Registration"
        new_user = UserFactory(first_name="New", last_name="Person", email="new@example.org")
        emails.send_new_pending_user_email(new_user=new_user, pending_users_url="http://x/pending/")

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert sorted(message.to) == ["a@example.org", "b@example.org"]
        assert message.subject.endswith("Teacher Registration: New user awaiting role assignment")
        assert "http://x/pending/" in message.body
        assert "New Person" in message.body
        assert message.alternatives[0][1] == "text/html"
        assert message.from_email == settings.DEFAULT_FROM_EMAIL

    def test_skipped_without_recipients(self):
        emails.send_new_pending_user_email(new_user=UserFactory())
        assert mail.outbox == []

    def test_new_teacher_registration(self, managers):
        registration = TeacherRegistrationFactory()
        emails.send_new_teacher_registration_email(registration=registration, pending_registrations_url="http://x/p/")
        assert "New teacher registration started" in mail.outbox[0].subject
        assert "http://x/p/" in mail.outbox[0].body

    def test_registration_submitted(self, managers):
        registration = TeacherRegistrationFactory(submitted=True)
        emails.send_teacher_registration_submitted_email(registration=registration, review_url="http://x/review/")
        assert "submitted for review" in mail.outbox[0].subject
        assert "http://x/review/" in mail.outbox[0].body


class TestTeacherNotifications:
    def test_approved(self):
        registration = TeacherRegistrationFactory(user=UserFactory(email="t@example.org"))
        emails.send_teacher_registration_approved_email(registration=registration, dashboard_url="http://x/me/")
        message = mail.outbox[0]
        assert message.to == ["t@example.org"]
        assert "approved" in message.subject
        assert "http://x/me/" in message.body

    def test_rejected_includes_reason(self):
        registration = TeacherRegistrationFactory(user=UserFactory(email="t@example.org"))
        emails.send_teacher_registration_rejected_email(
            registration=registration, rejection_reason="Photo too dark", my_registration_url="http://x/me/"
        )
        message = mail.outbox[0]
        assert "requires attention" in message.subject
        assert "Photo too dark" in message.body

    def test_expired(self):
        staff = SchoolStaffFactory(user=UserFactory(email="t@example.org"))
        emails.send_teacher_registration_expired_email(
            staff=staff, renewal_url="http://x/renew/", previous_status_label="Full Registration"
        )
        message = mail.outbox[0]
        assert "expired" in message.subject
        assert "http://x/renew/" in message.body
        assert "Full Registration" in message.body

    @pytest.mark.parametrize("email", ["", "someone@placeholder.invalid"])
    def test_teacher_mails_skipped_for_missing_or_placeholder_address(self, email):
        registration = TeacherRegistrationFactory(user=UserFactory(email=email))
        emails.send_teacher_registration_approved_email(registration=registration)
        emails.send_teacher_registration_rejected_email(registration=registration)
        emails.send_teacher_registration_expired_email(staff=SchoolStaffFactory(user=registration.user))
        assert mail.outbox == []


class TestAsyncWrappers:
    """The conftest runs the background thread inline; the wrapper must still swallow errors."""

    def test_async_wrapper_sends(self, managers):
        emails.send_new_pending_user_email_async(UserFactory(email="n@example.org"))
        assert len(mail.outbox) == 1

    @pytest.mark.parametrize(
        ("wrapper", "sender", "build_kwargs"),
        [
            ("send_new_pending_user_email_async", "send_new_pending_user_email", lambda: {"new_user": UserFactory()}),
            ("send_new_teacher_registration_email_async", "send_new_teacher_registration_email", lambda: {"registration": TeacherRegistrationFactory()}),
            ("send_teacher_registration_submitted_email_async", "send_teacher_registration_submitted_email", lambda: {"registration": TeacherRegistrationFactory()}),
            ("send_teacher_registration_approved_email_async", "send_teacher_registration_approved_email", lambda: {"registration": TeacherRegistrationFactory()}),
            ("send_teacher_registration_rejected_email_async", "send_teacher_registration_rejected_email", lambda: {"registration": TeacherRegistrationFactory()}),
            ("send_teacher_registration_expired_email_async", "send_teacher_registration_expired_email", lambda: {"staff": SchoolStaffFactory()}),
        ],
    )
    def test_async_wrappers_swallow_exceptions(self, wrapper, sender, build_kwargs, caplog):
        with patch.object(emails, sender, side_effect=ConnectionError("smtp down")):
            getattr(emails, wrapper)(**build_kwargs())
        assert any("error sending email" in record.message for record in caplog.records)


def test_send_test_email(settings):
    sender = UserFactory(first_name="Ops")
    emails.send_test_email(recipient="probe@example.org", sent_by=sender)
    message = mail.outbox[0]
    assert message.to == ["probe@example.org"]
    assert message.subject.endswith("Test email")
    assert settings.EMAIL_HOST in message.body

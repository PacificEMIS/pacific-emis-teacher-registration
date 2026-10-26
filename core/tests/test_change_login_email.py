"""
Change sign-in email (issue #122): who may, what is refused, what changes.

The flow must leave the registration, staff record and documents alone, move
only the account's email (and username when it was the email), drop the old
Google link, end open sessions, notify both addresses, and refuse any address
another account already owns.
"""

import pytest
from allauth.account.models import EmailAddress
from allauth.account.utils import filter_users_by_email
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import User
from django.core import mail
from django.test import Client
from django.urls import reverse

from core import permissions as p
from core.tests.factories import SchoolStaffFactory, UserFactory, system_user
from teacher_registration.models import RegistrationChangeLog
from teacher_registration.tests.factories import TeacherRegistrationFactory

pytestmark = pytest.mark.django_db


def change_url(user, next_url=None):
    url = reverse("core:change_login_email", kwargs={"user_id": user.pk})
    return f"{url}?next={next_url}" if next_url else url


def post_change(client, user, new_email, confirm=None, verified=True, next_url=None):
    data = {"new_email": new_email, "new_email_confirm": new_email if confirm is None else confirm}
    if verified:
        data["verified_with_person"] = "on"
    if next_url:
        data["next"] = next_url
    return client.post(change_url(user), data)


def google_applicant(email="old.address@gmail.com"):
    """A teacher who signed in with Google and has a pending application and a document-bearing registration."""
    applicant = UserFactory(username=email, email=email, first_name="Tebwa", last_name="Teacher")
    SocialAccount.objects.create(user=applicant, provider="google", uid="g-123")
    EmailAddress.objects.create(user=applicant, email=email, primary=True, verified=True)
    registration = TeacherRegistrationFactory(user=applicant, submitted=True)
    return applicant, registration


@pytest.fixture
def admins_client(client):
    admin = system_user(p.GROUP_ADMINS)
    client.force_login(admin)
    client.admin = admin
    return client


@pytest.fixture
def system_admin_client():
    other = Client()  # its own client, so it can be used alongside admins_client
    other.force_login(system_user(p.GROUP_SYSTEM_ADMINS))
    return other


class TestAccess:
    def test_system_admins_are_refused(self, system_admin_client):
        applicant, _ = google_applicant()
        assert system_admin_client.get(change_url(applicant)).status_code == 403
        assert post_change(system_admin_client, applicant, "new@example.org").status_code == 403
        applicant.refresh_from_db()
        assert applicant.email == "old.address@gmail.com"

    def test_admins_see_the_page_with_account_facts(self, admins_client):
        applicant, _ = google_applicant()
        response = admins_client.get(change_url(applicant))
        assert response.status_code == 200
        assert response.context["blockers"] == []
        assert response.context["social_providers"] == ["google"]
        assert response.context["registration_count"] == 1
        assert b"Change Sign-in Email" in response.content

    def test_buttons_only_for_admins_group(self, admins_client, system_admin_client):
        applicant = UserFactory()
        url = reverse("core:pending_users_list")
        assert change_url(applicant).encode() in admins_client.get(url).content
        assert change_url(applicant).encode() not in system_admin_client.get(url).content


class TestBlockers:
    def test_superuser_target_is_refused(self, admins_client):
        boss = UserFactory(is_superuser=True, is_staff=True, email="boss@example.org")
        response = admins_client.get(change_url(boss))
        assert any("superuser" in b for b in response.context["blockers"])
        response = post_change(admins_client, boss, "other@example.org")
        assert response.status_code == 302
        boss.refresh_from_db()
        assert boss.email == "boss@example.org"

    def test_own_account_is_refused(self, admins_client):
        me = admins_client.admin
        response = admins_client.get(change_url(me))
        assert any("own account" in b for b in response.context["blockers"])
        post_change(admins_client, me, "other@example.org")
        me.refresh_from_db()
        assert me.email != "other@example.org"


class TestValidation:
    @pytest.mark.parametrize(
        ("new_email", "confirm", "verified", "field", "fragment"),
        [
            ("old.address@gmail.com", None, True, "new_email", "already this account"),
            ("New.Address@example.org", "other@example.org", True, "new_email_confirm", "do not match"),
            ("new.address@example.org", None, False, "verified_with_person", "required"),
            ("not-an-email", None, True, "new_email", "valid email"),
        ],
    )
    def test_rejected_input_changes_nothing(self, admins_client, new_email, confirm, verified, field, fragment):
        applicant, _ = google_applicant()
        response = post_change(admins_client, applicant, new_email, confirm=confirm, verified=verified)
        assert response.status_code == 200
        assert fragment.lower() in " ".join(response.context["form"].errors[field]).lower()
        applicant.refresh_from_db()
        assert applicant.email == "old.address@gmail.com"
        assert SocialAccount.objects.filter(user=applicant).exists()

    @pytest.mark.parametrize("how", ["email", "username", "emailaddress"])
    def test_address_owned_by_another_account_is_refused(self, admins_client, how):
        applicant, _ = google_applicant()
        other = UserFactory(username="other-user", email="other@example.org", first_name="Other", last_name="Person")
        if how == "username":
            User.objects.filter(pk=other.pk).update(username="Taken@Example.org", email="")
        elif how == "emailaddress":
            User.objects.filter(pk=other.pk).update(email="")
            EmailAddress.objects.create(user=other, email="taken@example.org", primary=True, verified=False)
        else:
            User.objects.filter(pk=other.pk).update(email="Taken@Example.org")

        response = post_change(admins_client, applicant, "taken@example.org")
        assert response.status_code == 200
        (error,) = response.context["form"].errors["new_email"]
        assert "already belongs to another account" in error
        assert f"id {other.pk}" in error
        assert "Nothing was changed" in error
        applicant.refresh_from_db()
        assert applicant.email == "old.address@gmail.com"
        assert len(mail.outbox) == 0


class TestChange:
    def test_google_applicant_end_to_end(self, admins_client):
        applicant, registration = google_applicant()
        document_count_before = registration.documents.count() if hasattr(registration, "documents") else None

        # The applicant is signed in somewhere else right now.
        other_browser = Client()
        other_browser.force_login(applicant)
        assert other_browser.get(reverse("dashboard")).status_code in (200, 302)
        assert other_browser.session.get("_auth_user_id") == str(applicant.pk)

        next_url = reverse("teacher_registration:review", kwargs={"pk": registration.pk})
        response = post_change(admins_client, applicant, "New.Address@Example.org", next_url=next_url)
        assert response.status_code == 302 and response["Location"] == next_url

        applicant.refresh_from_db()
        assert applicant.email == "new.address@example.org"
        assert applicant.username == "new.address@example.org"
        assert applicant.first_name == "Tebwa"  # identity untouched

        # Registration still belongs to the same account, nothing else moved.
        registration.refresh_from_db()
        assert registration.user_id == applicant.pk
        if document_count_before is not None:
            assert registration.documents.count() == document_count_before

        # Old Google link gone; allauth bookkeeping points at the new address.
        assert not SocialAccount.objects.filter(user=applicant).exists()
        assert list(EmailAddress.objects.filter(user=applicant).values_list("email", "primary")) == [
            ("new.address@example.org", True)
        ]
        # The precondition for Google auto-connect on next sign-in: the new address resolves to this account.
        assert filter_users_by_email("new.address@example.org") == [applicant]

        # Audit line on the registration, attributed to the admin.
        entry = RegistrationChangeLog.objects.get(registration=registration, field_name="login_email")
        assert (entry.old_value, entry.new_value) == ("old.address@gmail.com", "new.address@example.org")
        assert entry.changed_by == admins_client.admin

        # Open session elsewhere was ended.
        response = other_browser.get(reverse("dashboard"))
        assert response.status_code == 302 and "login" in response["Location"]

        # Both addresses were told.
        recipients = sorted(m.to[0] for m in mail.outbox)
        assert recipients == ["new.address@example.org", "old.address@gmail.com"]
        assert "sign-in email was changed" in mail.outbox[0].subject
        assert "new.address@example.org" in mail.outbox[0].body

    def test_password_account_keeps_its_username(self, admins_client):
        staff = SchoolStaffFactory(user=UserFactory(username="jdoe", email="jdoe@example.org"))
        response = post_change(admins_client, staff.user, "jane.doe@example.org")
        assert response.status_code == 302
        staff.user.refresh_from_db()
        assert staff.user.email == "jane.doe@example.org"
        assert staff.user.username == "jdoe"
        assert not RegistrationChangeLog.objects.filter(field_name="login_email").exists()  # no registration to log on

    def test_moe_staff_account_works_too(self, admins_client):
        officer = system_user(p.GROUP_SYSTEM_STAFF)
        old = officer.email
        assert post_change(admins_client, officer, "officer.new@moe.example").status_code == 302
        officer.refresh_from_db()
        assert officer.email == "officer.new@moe.example"
        assert old != officer.email
        assert len(mail.outbox) == 2

    def test_unsafe_next_falls_back_to_pending_users(self, admins_client):
        applicant = UserFactory(email="a@example.org", username="a@example.org")
        response = post_change(admins_client, applicant, "b@example.org", next_url="https://evil.example/steal")
        assert response.status_code == 302
        assert response["Location"] == reverse("core:pending_users_list")

    def test_email_delivery_failure_does_not_undo_the_change(self, admins_client, settings, monkeypatch):
        applicant, _ = google_applicant()
        from django.core.mail import EmailMultiAlternatives

        def boom(self, fail_silently=False):
            raise ConnectionError("smtp down")

        monkeypatch.setattr(EmailMultiAlternatives, "send", boom)
        response = post_change(admins_client, applicant, "new@example.org")
        assert response.status_code == 302
        applicant.refresh_from_db()
        assert applicant.email == "new@example.org"

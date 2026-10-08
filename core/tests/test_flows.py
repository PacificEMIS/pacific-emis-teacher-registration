"""
End-to-end flows through the Django test client for the core app:
sign-in routing, pending-user role assignment, staff and system-user
administration, settings and utilities.
"""

from io import BytesIO
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core import permissions as p
from core.models import OrgSettings, SchoolStaff, SchoolStaffAssignment, SystemUser
from core.tests.factories import (
    GroupFactory,
    SchoolStaffAssignmentFactory,
    SchoolStaffFactory,
    SystemUserFactory,
    UserFactory,
    school_staff_user,
    system_user,
)
from integrations.models import EmisSchool, EmisTeacherRegistrationStatus
from integrations.tests.factories import (
    EmisJobTitleFactory,
    EmisSchoolFactory,
    EmisTeacherRegistrationStatusFactory,
)
from teacher_registration import constants
from teacher_registration.models import LookupCondition
from teacher_registration.tests.factories import LookupConditionFactory, TeacherRegistrationFactory

pytestmark = pytest.mark.django_db

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def url(name, **kwargs):
    return reverse(f"core:{name}", kwargs=kwargs or None)


def messages_of(response):
    return [str(m) for m in response.context["messages"]] if response.context else []


def png_upload(name="stamp.png"):
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.fixture
def groups():
    """The seeded group rows the forms offer."""
    return {name: GroupFactory(name=name) for name in (
        p.GROUP_ADMINS, p.GROUP_SCHOOL_ADMINS, p.GROUP_SCHOOL_STAFF, p.GROUP_TEACHERS,
        p.GROUP_SYSTEM_ADMINS, p.GROUP_SYSTEM_STAFF, p.GROUP_REGISTRATION_SIGNATORIES,
    )}


@pytest.fixture
def admins_user(groups):
    return school_staff_user(p.GROUP_ADMINS)


@pytest.fixture
def admins_client(client, admins_user):
    client.force_login(admins_user)
    return client


@pytest.fixture
def system_admin_client(client, groups):
    client.force_login(system_user(p.GROUP_SYSTEM_ADMINS))
    return client


# ===========================================================================
# Sign-in and post-login routing
# ===========================================================================


class TestSignIn:
    def test_password_login_redirects_to_dashboard(self, client, google_social_app):
        UserFactory(username="pw@example.org", password="password")
        response = client.post(reverse("accounts:login"), {"username": "pw@example.org", "password": "password"})
        assert response["Location"] == reverse("dashboard")

    def test_password_login_respects_next(self, client, google_social_app):
        UserFactory(username="pw@example.org", password="password")
        response = client.post(
            reverse("accounts:login"),
            {"username": "pw@example.org", "password": "password", "next": "/core/staff/"},
        )
        assert response["Location"] == "/core/staff/"

    def test_bad_password_shows_error(self, client, google_social_app):
        UserFactory(username="pw@example.org", password="password")
        response = client.post(reverse("accounts:login"), {"username": "pw@example.org", "password": "wrong"})
        assert response.status_code == 200
        assert any("Invalid username or password" in m for m in messages_of(response))

    def test_get_stores_next_in_session_and_flags_registration_flow(self, client, google_social_app):
        response = client.get(reverse("accounts:login"), {"next": "/registration/my-registration/"})
        assert client.session["next"] == "/registration/my-registration/"
        assert response.context["is_registration_flow"] is True

    def test_logged_in_user_is_sent_on(self, client, google_social_app):
        client.force_login(UserFactory())
        assert client.get(reverse("accounts:login"))["Location"] == reverse("dashboard")
        assert client.get(reverse("accounts:login"), {"next": "/core/staff/"})["Location"] == "/core/staff/"
        unsafe = client.get(reverse("accounts:login"), {"next": "https://evil.example/"})
        assert unsafe["Location"] == reverse("dashboard")

    def test_sign_out(self, client):
        client.force_login(UserFactory())
        response = client.get(reverse("accounts:logout"))
        assert response["Location"] == reverse("accounts:login")


class TestPostLoginRouter:
    def test_app_user_goes_to_dashboard_or_next(self, client):
        client.force_login(school_staff_user(p.GROUP_TEACHERS))
        assert client.get(reverse("accounts:post_login_router"))["Location"] == reverse("dashboard")
        assert client.get(reverse("accounts:post_login_router"), {"next": "/core/staff/"})["Location"] == "/core/staff/"

    def test_unsafe_next_is_ignored(self, client):
        client.force_login(school_staff_user(p.GROUP_TEACHERS))
        response = client.get(reverse("accounts:post_login_router"), {"next": "https://evil.example/x"})
        assert response["Location"] == reverse("dashboard")

    def test_registration_flow_next_is_allowed_without_app_access(self, client):
        client.force_login(UserFactory())
        target = reverse("teacher_registration:my_registration")
        response = client.get(reverse("accounts:post_login_router"), {"next": target})
        assert response["Location"] == target

    def test_session_next_is_consumed(self, client):
        client.force_login(UserFactory())
        session = client.session
        session["next"] = reverse("teacher_registration:my_registration")
        session.save()
        response = client.get(reverse("accounts:post_login_router"))
        assert response["Location"] == reverse("teacher_registration:my_registration")
        assert "next" not in client.session

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (constants.DRAFT, "edit"),
            (constants.SUBMITTED, "edit"),
            (constants.UNDER_REVIEW, "edit"),
            (constants.READY_FOR_APPROVAL, "my_registration"),
            (constants.REJECTED, "my_registration"),
            (constants.APPROVED, "my_registration"),
            (constants.EXPIRED, "my_registration"),
        ],
    )
    def test_user_with_registration_is_routed_to_it(self, client, status, expected):
        user = UserFactory()
        registration = TeacherRegistrationFactory(user=user, status=status)
        client.force_login(user)
        response = client.get(reverse("accounts:post_login_router"))
        if expected == "edit":
            assert response["Location"] == reverse("teacher_registration:edit", kwargs={"pk": registration.pk})
        else:
            assert response["Location"] == reverse("teacher_registration:my_registration")

    def test_approved_teacher_without_group_sees_my_registration(self, client):
        staff = SchoolStaffFactory()
        client.force_login(staff.user)
        response = client.get(reverse("accounts:post_login_router"))
        assert response["Location"] == reverse("teacher_registration:my_registration")

    def test_nobody_goes_to_no_permissions(self, client):
        client.force_login(UserFactory())
        response = client.get(reverse("accounts:post_login_router"))
        assert response["Location"] == reverse("accounts:no_permissions")


# ===========================================================================
# Dashboard
# ===========================================================================


def test_dashboard_counts(admins_client, admins_user):
    SchoolStaffFactory(staff_type=SchoolStaff.TEACHING_STAFF)
    TeacherRegistrationFactory(submitted=True)
    TeacherRegistrationFactory(status=constants.APPROVED)
    response = admins_client.get(reverse("dashboard"))
    context = response.context
    assert context["staff_teacher_count"] == 1
    assert context["admin_count"] == 1
    assert context["pending_reg_submitted"] == 1
    assert context["pending_reg_total"] == 1
    assert context["recent_events"]


# ===========================================================================
# Pending users
# ===========================================================================


class TestPendingUsers:
    def test_list_excludes_profiled_users_and_active_registrants(self, admins_client):
        pending = UserFactory(username="pending@example.org")
        SchoolStaffFactory()
        SystemUserFactory()
        TeacherRegistrationFactory(user=UserFactory(username="applicant@example.org"))
        UserFactory(is_superuser=True)
        approved_applicant = UserFactory(username="done@example.org")
        TeacherRegistrationFactory(user=approved_applicant, status=constants.APPROVED)

        response = admins_client.get(url("pending_users_list"))
        assert set(response.context["page_obj"].object_list) == {pending, approved_applicant}

    def test_search(self, admins_client):
        UserFactory(username="a@example.org", first_name="Anna")
        UserFactory(username="b@example.org", first_name="Bob")
        response = admins_client.get(url("pending_users_list"), {"q": "ann"})
        assert [u.first_name for u in response.context["page_obj"].object_list] == ["Anna"]

    def test_assign_school_staff(self, admins_client, admins_user, groups):
        target = UserFactory()
        response = admins_client.post(
            url("assign_school_staff", user_id=target.pk),
            {"staff_type": SchoolStaff.TEACHING_STAFF, "groups": [groups[p.GROUP_SCHOOL_ADMINS].pk]},
        )
        staff = SchoolStaff.objects.get(user=target)
        assert response["Location"] == url("staff_detail", pk=staff.pk)
        assert staff.staff_type == SchoolStaff.TEACHING_STAFF
        assert staff.created_by == admins_user
        assert list(target.groups.values_list("name", flat=True)) == [p.GROUP_SCHOOL_ADMINS]

    def test_assign_school_staff_requires_a_group(self, admins_client, groups):
        target = UserFactory()
        response = admins_client.post(url("assign_school_staff", user_id=target.pk), {"staff_type": SchoolStaff.TEACHING_STAFF})
        assert response.status_code == 200
        assert "groups" in response.context["form"].errors
        assert not SchoolStaff.objects.filter(user=target).exists()

    def test_system_admin_cannot_grant_admins_group(self, system_admin_client, groups):
        target = UserFactory()
        response = system_admin_client.post(
            url("assign_school_staff", user_id=target.pk),
            {"staff_type": SchoolStaff.TEACHING_STAFF, "groups": [groups[p.GROUP_ADMINS].pk]},
        )
        assert response.status_code == 200
        assert "groups" in response.context["form"].errors
        offered = set(response.context["form"].fields["groups"].queryset.values_list("name", flat=True))
        assert p.GROUP_ADMINS not in offered

    def test_assign_school_staff_already_profiled(self, admins_client, groups):
        staff = SchoolStaffFactory()
        response = admins_client.get(url("assign_school_staff", user_id=staff.user.pk))
        assert response["Location"] == url("pending_users_list")

    def test_assign_system_user(self, admins_client, groups):
        target = UserFactory()
        response = admins_client.post(
            url("assign_system_user", user_id=target.pk),
            {"organization": "MoE", "position_title": "Analyst", "groups": [groups[p.GROUP_SYSTEM_STAFF].pk]},
        )
        profile = SystemUser.objects.get(user=target)
        assert response["Location"] == url("system_user_detail", pk=profile.pk)
        assert profile.organization == "MoE"
        assert target.groups.filter(name=p.GROUP_SYSTEM_STAFF).exists()

    def test_delete_pending_user(self, admins_client):
        target = UserFactory()
        response = admins_client.post(url("delete_pending_user", user_id=target.pk))
        assert response["Location"] == url("pending_users_list")
        assert not User.objects.filter(pk=target.pk).exists()

    def test_delete_refuses_profiled_self_and_superuser(self, admins_client, admins_user):
        profiled = SchoolStaffFactory().user
        superuser = UserFactory(is_superuser=True)
        for target in (profiled, admins_user, superuser):
            admins_client.post(url("delete_pending_user", user_id=target.pk))
            assert User.objects.filter(pk=target.pk).exists()


# ===========================================================================
# School staff administration
# ===========================================================================


class TestStaffAdministration:
    @pytest.fixture
    def staff(self):
        return SchoolStaffFactory()

    def test_add_membership_from_detail_page(self, admins_client, admins_user, staff):
        school, job = EmisSchoolFactory(), EmisJobTitleFactory()
        response = admins_client.post(
            url("staff_detail", pk=staff.pk),
            {"school": school.pk, "job_title": job.pk, "start_date": "2026-01-01"},
        )
        assert response["Location"] == url("staff_detail", pk=staff.pk)
        membership = staff.assignments.get()
        assert membership.school == school
        assert membership.created_by == admins_user

    def test_school_admin_can_only_add_membership_for_own_school(self, client, staff):
        own, other = EmisSchoolFactory(), EmisSchoolFactory()
        admin = school_staff_user(p.GROUP_SCHOOL_ADMINS, schools=[own])
        SchoolStaffAssignmentFactory(school_staff=staff, school=own)
        client.force_login(admin)
        job = EmisJobTitleFactory()

        response = client.post(url("staff_detail", pk=staff.pk), {"school": other.pk, "job_title": job.pk})
        assert response.status_code == 200
        assert "school" in response.context["membership_form"].errors
        assert staff.assignments.count() == 1

        client.post(url("staff_detail", pk=staff.pk), {"school": own.pk, "job_title": job.pk, "start_date": "2026-02-02"})
        assert staff.assignments.count() == 2

    def test_membership_edit_and_delete(self, admins_client, staff):
        membership = SchoolStaffAssignmentFactory(school_staff=staff)
        new_school = EmisSchoolFactory()
        admins_client.post(
            url("staff_membership_edit", staff_id=staff.pk, pk=membership.pk),
            {"school": new_school.pk, "job_title": membership.job_title.pk, "end_date": "2026-12-31"},
        )
        membership.refresh_from_db()
        assert membership.school == new_school
        assert str(membership.end_date) == "2026-12-31"

        admins_client.post(url("staff_membership_delete", staff_id=staff.pk, pk=membership.pk))
        assert not SchoolStaffAssignment.objects.filter(pk=membership.pk).exists()

    def test_membership_lookup_is_scoped_to_staff(self, admins_client, staff):
        other = SchoolStaffAssignmentFactory()
        assert admins_client.get(url("staff_membership_edit", staff_id=staff.pk, pk=other.pk)).status_code == 404

    def test_staff_edit_replaces_school_groups(self, admins_client, staff, groups):
        staff.user.groups.add(groups[p.GROUP_TEACHERS], groups[p.GROUP_SYSTEM_STAFF])
        response = admins_client.post(
            url("staff_edit", pk=staff.pk),
            {"staff_type": SchoolStaff.TEACHING_STAFF, "groups": [groups[p.GROUP_SCHOOL_ADMINS].pk, groups[p.GROUP_ADMINS].pk]},
        )
        assert response["Location"] == url("staff_detail", pk=staff.pk)
        staff.refresh_from_db()
        assert staff.staff_type == SchoolStaff.TEACHING_STAFF
        names = set(staff.user.groups.values_list("name", flat=True))
        assert names == {p.GROUP_SCHOOL_ADMINS, p.GROUP_ADMINS, p.GROUP_SYSTEM_STAFF}

    def test_system_admin_cannot_grant_admins_via_staff_edit(self, system_admin_client, staff, groups):
        response = system_admin_client.post(
            url("staff_edit", pk=staff.pk),
            {"staff_type": SchoolStaff.NON_TEACHING_STAFF, "groups": [groups[p.GROUP_ADMINS].pk]},
        )
        assert response.status_code == 200
        assert "groups" in response.context["form"].errors

    def test_staff_delete_keeps_user(self, admins_client, staff):
        user = staff.user
        response = admins_client.post(url("staff_delete", pk=staff.pk))
        assert response["Location"] == url("staff_list")
        assert not SchoolStaff.objects.filter(pk=staff.pk).exists()
        assert User.objects.filter(pk=user.pk).exists()

    def test_staff_delete_refuses_self(self, admins_client, admins_user):
        own = admins_user.school_staff
        admins_client.post(url("staff_delete", pk=own.pk))
        assert SchoolStaff.objects.filter(pk=own.pk).exists()

    def test_staff_list_search(self, admins_client):
        SchoolStaffFactory(user=UserFactory(first_name="Zane"))
        response = admins_client.get(url("staff_list"), {"q": "zane"})
        assert response.status_code == 200
        assert response.context["page_obj"].paginator.count == 1


class TestSystemUserAdministration:
    def test_edit_updates_profile_groups_and_signature(self, admins_client, admins_user, groups):
        profile = SystemUserFactory()
        profile.user.groups.add(groups[p.GROUP_SYSTEM_STAFF])
        response = admins_client.post(
            url("system_user_edit", pk=profile.pk),
            {
                "organization": "MoE", "position_title": "Registrar",
                "groups": [groups[p.GROUP_SYSTEM_ADMINS].pk, groups[p.GROUP_REGISTRATION_SIGNATORIES].pk],
                "signature": png_upload(),
            },
        )
        assert response["Location"] == url("system_user_detail", pk=profile.pk)
        profile.refresh_from_db()
        assert profile.organization == "MoE"
        assert profile.signature
        assert set(profile.user.groups.values_list("name", flat=True)) == {
            p.GROUP_SYSTEM_ADMINS, p.GROUP_REGISTRATION_SIGNATORIES,
        }

    def test_system_admin_cannot_grant_admins(self, system_admin_client, groups):
        profile = SystemUserFactory()
        response = system_admin_client.post(
            url("system_user_edit", pk=profile.pk),
            {"organization": "", "position_title": "", "groups": [groups[p.GROUP_ADMINS].pk]},
        )
        assert response.status_code == 200
        assert "groups" in response.context["form"].errors

    def test_list_search(self, admins_client, groups):
        SystemUserFactory(user=UserFactory(last_name="Quartz"))
        SystemUserFactory()
        response = admins_client.get(url("system_user_list"), {"q": "quartz"})
        assert response.context["page_obj"].paginator.count == 1


# ===========================================================================
# Settings and utilities
# ===========================================================================


class TestSettings:
    def test_settings_page_lists_lookups_and_saves_stamp(self, admins_client):
        response = admins_client.get(url("settings"))
        slugs = [c["slug"] for c in response.context["lookup_categories"]]
        assert "schools" in slugs and "registration-statuses" in slugs

        admins_client.post(url("settings"), {"stamp": png_upload()})
        assert OrgSettings.load().stamp

    def test_lookup_list_renders_each_slug(self, admins_client):
        for slug in ("schools", "job-titles", "registration-statuses", "link-types", "nationalities"):
            assert admins_client.get(url("settings_lookup_list", slug=slug)).status_code == 200, slug

    def test_lookup_update_toggles_active(self, admins_client):
        school = EmisSchoolFactory(active=True)
        response = admins_client.post(url("settings_lookup_update", slug="schools", pk=school.pk), {"active": "false"})
        assert response.json() == {"ok": True}
        assert EmisSchool.objects.get(pk=school.pk).active is False

    def test_lookup_update_validity_fields(self, admins_client):
        status = EmisTeacherRegistrationStatusFactory()
        admins_client.post(
            url("settings_lookup_update", slug="registration-statuses", pk=status.pk),
            {"validity_value": "5", "validity_unit": "years"},
        )
        status.refresh_from_db()
        assert (status.validity_value, status.validity_unit) == (5, "years")

        admins_client.post(url("settings_lookup_update", slug="registration-statuses", pk=status.pk), {"validity_value": ""})
        assert EmisTeacherRegistrationStatus.objects.get(pk=status.pk).validity_value is None

    def test_lookup_update_unknowns(self, admins_client):
        assert admins_client.post(url("settings_lookup_update", slug="nope", pk="x"), {}).status_code == 404
        assert admins_client.post(url("settings_lookup_update", slug="schools", pk="missing"), {}).status_code == 404

    def test_condition_types_create_and_validate(self, admins_client):
        admins_client.post(url("settings_condition_types"), {"code": "FIRSTAID", "label": "First aid"})
        assert LookupCondition.objects.get(code="FIRSTAID").active is True

        response = admins_client.post(url("settings_condition_types"), {"code": "FIRSTAID", "label": "Dup"}, follow=True)
        assert any("already exists" in m for m in messages_of(response))
        response = admins_client.post(url("settings_condition_types"), {"code": "", "label": "x"}, follow=True)
        assert any("required" in m for m in messages_of(response))
        assert LookupCondition.objects.count() == 1

    def test_condition_type_update(self, admins_client):
        item = LookupConditionFactory(label="Old")
        response = admins_client.post(url("settings_condition_type_update", pk=item.pk), {"label": "New", "active": "false"})
        assert response.json() == {"ok": True}
        item.refresh_from_db()
        assert (item.label, item.active) == ("New", False)
        assert admins_client.post(url("settings_condition_type_update", pk=item.pk), {"label": " "}).status_code == 400
        assert admins_client.post(url("settings_condition_type_update", pk="nope"), {}).status_code == 404

    def test_sync_emis_lookups_reports_result(self, admins_client):
        with patch("core.views.call_command") as call_command:
            call_command.side_effect = lambda name, stdout: stdout.write("Schools +1/0")
            response = admins_client.post(url("sync_emis_lookups"), **AJAX)
        assert response.json() == {"ok": True, "message": "Schools +1/0"}
        call_command.assert_called_once()
        assert call_command.call_args.args[0] == "emis_sync_lookups"

    def test_sync_emis_lookups_reports_failure(self, admins_client):
        with patch("core.views.call_command", side_effect=RuntimeError("boom")):
            response = admins_client.post(url("sync_emis_lookups"), **AJAX)
        assert response.json()["ok"] is False
        assert "boom" in response.json()["message"]

    def test_test_email_sends(self, admins_client, admins_user):
        response = admins_client.post(url("test_email"), {"recipient": "check@example.org"})
        assert response["Location"] == url("test_email")
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["check@example.org"]
        assert "Test email" in mail.outbox[0].subject

    def test_test_email_reports_smtp_failure(self, admins_client):
        with patch("core.views.send_test_email", side_effect=ConnectionRefusedError("no smtp")):
            response = admins_client.post(url("test_email"), {"recipient": "check@example.org"})
        assert response.status_code == 200
        assert any("failed" in m and "no smtp" in m for m in messages_of(response))

    def test_test_email_defaults_to_own_address(self, admins_client, admins_user):
        admins_user.email = "me@example.org"
        admins_user.save()
        response = admins_client.get(url("test_email"))
        assert response.context["form"].initial["recipient"] == "me@example.org"


class TestPdfUtilities:
    @staticmethod
    def two_page_pdf():
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_blank_page(width=200, height=200)
        buffer = BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    def test_merge(self, admins_client):
        from pypdf import PdfReader

        a = SimpleUploadedFile("a.pdf", self.two_page_pdf(), content_type="application/pdf")
        b = SimpleUploadedFile("b.pdf", self.two_page_pdf(), content_type="application/pdf")
        response = admins_client.post(url("pdf_merge"), {"pdf_files": [a, b]})
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert len(PdfReader(BytesIO(response.content)).pages) == 4

    def test_merge_requires_two_pdfs(self, admins_client):
        a = SimpleUploadedFile("a.pdf", self.two_page_pdf(), content_type="application/pdf")
        response = admins_client.post(url("pdf_merge"), {"pdf_files": [a]})
        assert response.status_code == 200
        assert any("at least two" in m for m in messages_of(response))

        a = SimpleUploadedFile("a.pdf", self.two_page_pdf(), content_type="application/pdf")
        txt = SimpleUploadedFile("b.txt", b"x", content_type="text/plain")
        response = admins_client.post(url("pdf_merge"), {"pdf_files": [a, txt]})
        assert any("not a PDF" in m for m in messages_of(response))

    def test_split_and_download(self, admins_client, settings, tmp_path):
        from pypdf import PdfReader

        upload = SimpleUploadedFile("doc.pdf", self.two_page_pdf(), content_type="application/pdf")
        response = admins_client.post(url("pdf_split"), {"pdf_file": upload})
        assert response.status_code == 302, messages_of(response)
        job_id = response["Location"].rstrip("/").split("/")[-1]

        results = admins_client.get(url("pdf_split_results", job_id=job_id))
        assert results.status_code == 200

        page = admins_client.get(url("pdf_split_download", job_id=job_id, page_num=1))
        assert page.status_code == 200
        assert len(PdfReader(BytesIO(b"".join(page.streaming_content))).pages) == 1

        archive = admins_client.get(url("pdf_split_download_all", job_id=job_id))
        assert archive["Content-Type"] == "application/zip"

    def test_split_rejects_single_page_and_non_pdf(self, admins_client):
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        buffer = BytesIO()
        writer.write(buffer)
        single = SimpleUploadedFile("one.pdf", buffer.getvalue(), content_type="application/pdf")
        response = admins_client.post(url("pdf_split"), {"pdf_file": single})
        assert any("only one page" in m for m in messages_of(response))

        txt = SimpleUploadedFile("x.txt", b"x", content_type="text/plain")
        response = admins_client.post(url("pdf_split"), {"pdf_file": txt})
        assert any("Only PDF files" in m for m in messages_of(response))

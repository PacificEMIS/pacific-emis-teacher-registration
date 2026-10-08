"""
End-to-end flows through the Django test client for the registration app:
teacher self-registration, staff registering on behalf, admin review,
renewal, and post-approval teacher administration.
"""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from io import BytesIO

import pytest
import time_machine
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from core.models import SchoolStaff, SchoolStaffAssignment, StaffEducationRecord, StaffTeachingDuty
from core.tests.factories import SchoolStaffAssignmentFactory, UserFactory
from integrations.tests.factories import (
    EmisClassLevelFactory,
    EmisEducationLevelFactory,
    EmisJobTitleFactory,
    EmisSchoolFactory,
    EmisSubjectFactory,
    EmisTeacherLinkTypeFactory,
    EmisTeacherQualFactory,
)
from teacher_registration import constants
from teacher_registration.models import (
    ClaimedDuty,
    RegistrationChangeLog,
    RegistrationCondition,
    RegistrationDocument,
    TeacherRegistration,
)
from teacher_registration.tests.conftest import (
    approved_teacher,
    formset_management,
    registration_form_data,
)
from teacher_registration.tests.factories import (
    ClaimedDutyFactory,
    ClaimedSchoolAppointmentFactory,
    EducationRecordFactory,
    LookupConditionFactory,
    RegistrationDocumentFactory,
    TeacherRegistrationFactory,
    TrainingRecordFactory,
)
from teacher_registration.views import get_required_documents_status

pytestmark = pytest.mark.django_db

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def url(name, **kwargs):
    return reverse(f"teacher_registration:{name}", kwargs=kwargs or None)


def pdf_upload(name="cert.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")


def png_upload(name="photo.png"):
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def messages_of(response):
    return [str(m) for m in response.context["messages"]] if response.context else []


# ===========================================================================
# Teacher self-registration
# ===========================================================================


class TestSelfRegistrationStart:
    def test_public_start_sends_anonymous_to_login_with_next(self, client):
        response = client.get(url("public_start"))
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("accounts:login"))
        assert "next=" in response["Location"]
        assert "my-registration" in response["Location"]

    def test_public_start_sends_authenticated_user_on(self, applicant_client):
        response = applicant_client.get(url("public_start"))
        assert response["Location"] == url("my_registration")

    def test_public_signout_logs_out(self, applicant_client):
        response = applicant_client.get(url("public_signout"))
        assert response["Location"] == url("public_landing")
        assert applicant_client.get(url("my_registration")).status_code == 302

    def test_my_registration_with_nothing_goes_to_create(self, applicant_client):
        response = applicant_client.get(url("my_registration"))
        assert response["Location"] == url("create")

    def test_create_makes_draft_logs_and_notifies_admins(self, applicant_client, applicant, admin_user):
        response = applicant_client.get(url("create"))

        registration = TeacherRegistration.objects.get(user=applicant)
        assert registration.status == constants.DRAFT
        assert registration.registration_type == TeacherRegistration.INITIAL
        assert registration.created_by == applicant
        assert response["Location"] == url("edit", pk=registration.pk)

        log = registration.change_logs.get()
        assert log.new_value == constants.DRAFT
        assert "self-registration" in log.notes

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [admin_user.email]
        assert "New teacher registration started" in mail.outbox[0].subject

    def test_create_reuses_existing_draft(self, applicant_client, applicant):
        draft = TeacherRegistrationFactory(user=applicant)
        response = applicant_client.get(url("create"))
        assert response["Location"] == url("edit", pk=draft.pk)
        assert TeacherRegistration.objects.filter(user=applicant).count() == 1

    def test_create_blocked_while_pending_review(self, applicant_client, applicant):
        TeacherRegistrationFactory(user=applicant, submitted=True)
        response = applicant_client.get(url("create"), follow=True)
        assert TeacherRegistration.objects.filter(user=applicant).count() == 1
        assert any("pending review" in m for m in messages_of(response))

    def test_create_blocked_for_existing_school_staff(self, client):
        teacher = approved_teacher()
        client.force_login(teacher.user)
        response = client.get(url("create"))
        assert response["Location"] == reverse("dashboard")

    def test_my_registration_redirects_to_existing_draft(self, applicant_client, applicant):
        draft = TeacherRegistrationFactory(user=applicant)
        assert applicant_client.get(url("my_registration"))["Location"] == url("edit", pk=draft.pk)

    def test_my_registration_shows_status_once_submitted(self, applicant_client, applicant):
        registration = TeacherRegistrationFactory(user=applicant, submitted=True)
        response = applicant_client.get(url("my_registration"))
        assert response.status_code == 200
        assert list(response.context["registrations"]) == [registration]


class TestRegistrationEdit:
    @pytest.fixture
    def draft(self, applicant):
        return TeacherRegistrationFactory(user=applicant, national_id_number="")

    def test_get_renders_form_with_user_initial(self, applicant_client, draft, applicant):
        response = applicant_client.get(url("edit", pk=draft.pk))
        assert response.status_code == 200
        assert response.context["form"].initial["email"] == applicant.email
        assert response.context["is_admin"] is False

    def test_save_draft_updates_registration_and_user(self, applicant_client, draft, applicant, gender):
        data = registration_form_data(draft, gender, email="new@example.org")
        response = applicant_client.post(url("edit", pk=draft.pk), data)

        assert response["Location"] == url("edit", pk=draft.pk)
        draft.refresh_from_db()
        applicant.refresh_from_db()
        assert draft.status == constants.DRAFT
        assert draft.national_id_number == "NID-001"
        assert draft.gender == gender
        assert draft.last_updated_by == applicant
        assert applicant.first_name == "Teua"
        assert applicant.last_name == "Tekanene"
        assert applicant.email == "new@example.org"
        assert applicant.username == "new@example.org"

    def test_save_draft_tolerates_missing_required_fields(self, applicant_client, draft, gender):
        data = registration_form_data(draft, gender, national_id_number="", date_of_birth="")
        data["gender"] = ""
        response = applicant_client.post(url("edit", pk=draft.pk), data)
        assert response.status_code == 302
        draft.refresh_from_db()
        assert draft.status == constants.DRAFT

    def test_email_locked_for_google_linked_user(self, applicant_client, draft, applicant, gender):
        SocialAccount.objects.create(user=applicant, provider="google", uid="123")
        response = applicant_client.get(url("edit", pk=draft.pk))
        assert response.context["email_editable"] is False

        applicant_client.post(url("edit", pk=draft.pk), registration_form_data(draft, gender, email="hijack@example.org"))
        applicant.refresh_from_db()
        assert applicant.email == "teua@example.org"

    def test_submit_requires_core_fields(self, applicant_client, draft, gender):
        data = registration_form_data(draft, gender, national_id_number="", last_name="", submit="1")
        response = applicant_client.post(url("edit", pk=draft.pk), data)

        assert response.status_code == 200
        errors = messages_of(response)
        assert any("National ID" in m for m in errors)
        assert any("Last name" in m for m in errors)
        draft.refresh_from_db()
        assert draft.status == constants.DRAFT

    def test_submit_success(self, applicant_client, draft, gender, admin_user):
        data = registration_form_data(draft, gender, submit="1")
        response = applicant_client.post(url("edit", pk=draft.pk), data)

        assert response["Location"] == url("my_registration")
        draft.refresh_from_db()
        assert draft.status == constants.SUBMITTED
        assert draft.submitted_at is not None
        assert [m.subject for m in mail.outbox] == [
            m.subject for m in mail.outbox if "submitted for review" in m.subject
        ]
        assert len(mail.outbox) == 1
        assert url("review", pk=draft.pk) in mail.outbox[0].body

    def test_admin_submit_on_behalf_goes_to_pending_list(self, admin_client, draft, gender):
        data = registration_form_data(draft, gender, submit="1")
        response = admin_client.post(url("edit", pk=draft.pk), data)
        assert response["Location"] == url("pending_list")

    def test_education_formset_creates_record(self, applicant_client, draft, gender):
        qual = EmisTeacherQualFactory()
        major = EmisSubjectFactory()
        data = registration_form_data(draft, gender)
        data.update(formset_management(total=1, prefixes=("education_records",)))
        data.update({
            "education_records-0-institution_name": "USP",
            "education_records-0-qualification": qual.pk,
            "education_records-0-major": major.pk,
            "education_records-0-completion_year": "2015",
            "education_records-0-duration_unit": "years",
            "education_records-0-completed": "on",
        })
        applicant_client.post(url("edit", pk=draft.pk), data)
        record = draft.education_records.get()
        assert record.institution_name == "USP"
        assert record.qualification == qual

    def test_invalid_form_shows_errors_and_keeps_draft(self, applicant_client, draft, gender):
        data = registration_form_data(draft, gender, date_of_birth="not-a-date")
        response = applicant_client.post(url("edit", pk=draft.pk), data)
        assert response.status_code == 200
        assert any("date_of_birth" in m for m in messages_of(response))

    def test_non_draft_redirects_owner_and_admin_differently(self, applicant_client, admin_client, applicant):
        submitted = TeacherRegistrationFactory(user=applicant, submitted=True)
        assert applicant_client.get(url("edit", pk=submitted.pk))["Location"] == url("my_registration")
        assert admin_client.get(url("edit", pk=submitted.pk))["Location"] == url("pending_list")


class TestRegistrationSubmitView:
    def test_get_shows_confirmation(self, applicant_client, applicant):
        draft = TeacherRegistrationFactory(user=applicant)
        assert applicant_client.get(url("submit", pk=draft.pk)).status_code == 200

    def test_post_submits_and_notifies(self, applicant_client, applicant, admin_user):
        draft = TeacherRegistrationFactory(user=applicant)
        response = applicant_client.post(url("submit", pk=draft.pk))
        assert response["Location"] == url("my_registration")
        draft.refresh_from_db()
        assert draft.status == constants.SUBMITTED
        assert len(mail.outbox) == 1

    def test_already_submitted_redirects(self, applicant_client, applicant):
        submitted = TeacherRegistrationFactory(user=applicant, submitted=True)
        response = applicant_client.post(url("submit", pk=submitted.pk))
        assert response["Location"] == url("my_registration")


class TestDocuments:
    @pytest.fixture
    def draft(self, applicant):
        return TeacherRegistrationFactory(user=applicant)

    @pytest.fixture
    def link_type(self):
        return EmisTeacherLinkTypeFactory(code="POLCLEAR", label="Police Clearance")

    def test_upload_sets_derived_fields(self, applicant_client, draft, applicant, link_type):
        response = applicant_client.post(
            url("document_upload", registration_pk=draft.pk),
            {"doc_link_type": link_type.pk, "file": pdf_upload("Clearance.PDF")},
        )
        assert response["Location"] == url("edit", pk=draft.pk)
        doc = draft.documents.get()
        assert doc.original_filename == "Clearance.PDF"
        assert doc.file_size == len(b"%PDF-1.4 test")
        assert doc.doc_type == "pdf"
        assert doc.created_by == applicant
        assert doc.file.name.startswith(f"registrations/{draft.pk}/")

    def test_upload_ajax_returns_sidebar(self, applicant_client, draft, link_type):
        response = applicant_client.post(
            url("document_upload", registration_pk=draft.pk),
            {"doc_link_type": link_type.pk, "file": pdf_upload()},
            **AJAX,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert "Police Clearance" in payload["sidebar_html"]

    def test_upload_rejects_disallowed_type(self, applicant_client, draft, link_type):
        bad = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
        response = applicant_client.post(
            url("document_upload", registration_pk=draft.pk),
            {"doc_link_type": link_type.pk, "file": bad},
            **AJAX,
        )
        assert response.status_code == 400
        assert any("Only PDF and image" in e for e in response.json()["errors"])
        assert not draft.documents.exists()

    def test_upload_rejects_oversized_file(self, applicant_client, draft, link_type):
        big = SimpleUploadedFile("big.pdf", b"x" * (10 * 1024 * 1024 + 1), content_type="application/pdf")
        response = applicant_client.post(
            url("document_upload", registration_pk=draft.pk),
            {"doc_link_type": link_type.pk, "file": big},
            **AJAX,
        )
        assert response.status_code == 400
        assert any("10MB" in e for e in response.json()["errors"])

    def test_upload_blocked_once_submitted(self, applicant_client, applicant, link_type):
        submitted = TeacherRegistrationFactory(user=applicant, submitted=True)
        response = applicant_client.post(
            url("document_upload", registration_pk=submitted.pk),
            {"doc_link_type": link_type.pk, "file": pdf_upload()},
            **AJAX,
        )
        assert response.status_code == 400
        assert response.json()["success"] is False

    def test_delete(self, applicant_client, draft):
        doc = RegistrationDocumentFactory(registration=draft)
        response = applicant_client.post(url("document_delete", registration_pk=draft.pk, pk=doc.pk), **AJAX)
        assert response.json()["success"] is True
        assert not RegistrationDocument.objects.filter(pk=doc.pk).exists()

    def test_delete_scoped_to_registration(self, applicant_client, draft):
        other = RegistrationDocumentFactory()
        response = applicant_client.post(url("document_delete", registration_pk=draft.pk, pk=other.pk))
        assert response.status_code == 404
        assert RegistrationDocument.objects.filter(pk=other.pk).exists()

    def test_required_documents_status(self):
        birth = RegistrationDocumentFactory(doc_link_type=EmisTeacherLinkTypeFactory(code="birthcert"))
        statuses = get_required_documents_status([birth])
        by_label = {row["label"]: row["uploaded"] for row in statuses}
        assert by_label["Birth Certificate or Passport"] is True
        assert by_label["Police Clearance"] is False
        assert len(statuses) == 11

    def test_required_documents_status_counts_staff_documents(self):
        staff_doc = RegistrationDocumentFactory(
            registration=None,
            school_staff=approved_teacher(),
            doc_link_type=EmisTeacherLinkTypeFactory(code="NATIONID"),
        )
        by_label = {r["label"]: r["uploaded"] for r in get_required_documents_status([], [staff_doc])}
        assert by_label["National ID Card"] is True


class TestClaimedDuties:
    @pytest.fixture
    def appointment(self, applicant):
        draft = TeacherRegistrationFactory(user=applicant)
        level = EmisEducationLevelFactory(code="JSS", label="Junior Secondary")
        return ClaimedSchoolAppointmentFactory(registration=draft, teacher_level_type=level)

    def test_get_renders_modal_with_subjects_for_secondary(self, applicant_client, appointment):
        response = applicant_client.get(url("manage_claimed_duties", appointment_id=appointment.pk))
        assert response.status_code == 200
        assert response.context["show_subjects"] is True

    def test_get_hides_subjects_for_primary(self, applicant_client, applicant):
        draft = TeacherRegistrationFactory(user=applicant)
        level = EmisEducationLevelFactory(code="PRI", label="Primary")
        appointment = ClaimedSchoolAppointmentFactory(registration=draft, teacher_level_type=level)
        response = applicant_client.get(url("manage_claimed_duties", appointment_id=appointment.pk))
        assert response.context["show_subjects"] is False

    def test_post_expands_groups_into_duties(self, applicant_client, appointment):
        year = EmisClassLevelFactory()
        maths, science = EmisSubjectFactory(), EmisSubjectFactory()
        response = applicant_client.post(
            url("manage_claimed_duties", appointment_id=appointment.pk),
            {"duties[0][year_level]": year.pk, "duties[0][subjects][]": [maths.pk, science.pk]},
        )
        assert response.json()["duties_count"] == 2
        assert set(appointment.claimed_duties.values_list("subject_id", flat=True)) == {maths.pk, science.pk}

    def test_post_keeps_existing_and_removes_dropped(self, applicant_client, appointment):
        year = EmisClassLevelFactory()
        keep = ClaimedDutyFactory(appointment=appointment, year_level=year)
        ClaimedDutyFactory(appointment=appointment, year_level=year)
        applicant_client.post(
            url("manage_claimed_duties", appointment_id=appointment.pk),
            {"duties[0][year_level]": year.pk, "duties[0][subjects][]": [keep.subject_id]},
        )
        assert list(appointment.claimed_duties.values_list("pk", flat=True)) == [keep.pk]

    def test_post_without_subjects_creates_single_subjectless_duty(self, applicant_client, appointment):
        year = EmisClassLevelFactory()
        applicant_client.post(
            url("manage_claimed_duties", appointment_id=appointment.pk),
            {"duties[0][year_level]": year.pk},
        )
        duty = appointment.claimed_duties.get()
        assert duty.subject is None and duty.year_level == year

    def test_post_ignores_inactive_level(self, applicant_client, appointment):
        year = EmisClassLevelFactory(active=False)
        applicant_client.post(
            url("manage_claimed_duties", appointment_id=appointment.pk),
            {"duties[0][year_level]": year.pk},
        )
        assert not appointment.claimed_duties.exists()

    def test_post_blocked_once_submitted(self, applicant_client, appointment):
        appointment.registration.submit()
        response = applicant_client.post(url("manage_claimed_duties", appointment_id=appointment.pk), {})
        assert response.status_code == 400

    def test_post_by_stranger_is_json_403(self, client, appointment):
        client.force_login(UserFactory())
        response = client.post(url("manage_claimed_duties", appointment_id=appointment.pk), {})
        assert response.status_code == 403
        assert response.json()["success"] is False


# ===========================================================================
# Staff registering on behalf of a teacher
# ===========================================================================


class TestStaffRegisterTeacher:
    def test_creates_placeholder_user_and_draft(self, admin_client, admin_user):
        response = admin_client.post(
            url("staff_register_teacher"),
            {"email": "New.Teacher@Example.org", "first_name": "New", "last_name": "Teacher"},
        )
        user = User.objects.get(email="new.teacher@example.org")
        assert user.username == "new.teacher@example.org"
        assert not user.has_usable_password()
        registration = user.teacher_registrations.get()
        assert registration.status == constants.DRAFT
        assert registration.created_by == admin_user
        assert "on behalf" in registration.change_logs.get().notes
        assert response["Location"] == url("edit", pk=registration.pk)
        assert len(mail.outbox) == 1

    def test_existing_user_keeps_names_and_gets_draft(self, admin_client):
        existing = UserFactory(email="old@example.org", first_name="Keep", last_name="")
        admin_client.post(url("staff_register_teacher"), {"email": "old@example.org", "first_name": "X", "last_name": "Filled"})
        existing.refresh_from_db()
        assert existing.first_name == "Keep"
        assert existing.last_name == "Filled"
        assert existing.teacher_registrations.count() == 1

    def test_existing_active_registration_redirects(self, admin_client):
        existing = UserFactory(email="busy@example.org")
        draft = TeacherRegistrationFactory(user=existing)
        response = admin_client.post(url("staff_register_teacher"), {"email": "busy@example.org"})
        assert response["Location"] == url("edit", pk=draft.pk)
        assert existing.teacher_registrations.count() == 1

        draft.submit()
        response = admin_client.post(url("staff_register_teacher"), {"email": "busy@example.org"})
        assert response["Location"] == url("review", pk=draft.pk)

    def test_existing_school_staff_is_refused(self, admin_client):
        teacher = approved_teacher()
        response = admin_client.post(url("staff_register_teacher"), {"email": teacher.user.email}, follow=True)
        assert any("already registered" in m for m in messages_of(response))
        assert not teacher.user.teacher_registrations.exists()

    def test_expired_school_staff_points_to_renew_on_behalf(self, admin_client):
        teacher = approved_teacher()
        teacher.registration_application_status = constants.EXPIRED
        teacher.save()
        response = admin_client.post(url("staff_register_teacher"), {"email": teacher.user.email})
        assert response["Location"] == url("teacher_detail", pk=teacher.pk)

    def test_invalid_email_rerenders(self, admin_client):
        response = admin_client.post(url("staff_register_teacher"), {"email": "nope"})
        assert response.status_code == 200
        assert response.context["form"].errors


# ===========================================================================
# Admin review
# ===========================================================================


class TestPendingList:
    def test_lists_open_statuses_only(self, admin_client):
        shown = [TeacherRegistrationFactory(status=s) for s in (
            constants.DRAFT, constants.SUBMITTED, constants.UNDER_REVIEW,
            constants.READY_FOR_APPROVAL, constants.REJECTED,
        )]
        TeacherRegistrationFactory(status=constants.APPROVED)
        response = admin_client.get(url("pending_list"))
        assert set(response.context["page_obj"].object_list) == set(shown)

    def test_ready_for_approval_sorts_first(self, admin_client):
        draft = TeacherRegistrationFactory()
        ready = TeacherRegistrationFactory(ready=True)
        response = admin_client.get(url("pending_list"))
        assert list(response.context["page_obj"].object_list) == [ready, draft]

    def test_search_and_status_filter(self, admin_client):
        match = TeacherRegistrationFactory(submitted=True, user=UserFactory(first_name="Zelda"))
        TeacherRegistrationFactory(submitted=True)
        response = admin_client.get(url("pending_list"), {"q": "zel", "status": constants.SUBMITTED})
        assert list(response.context["page_obj"].object_list) == [match]

    def test_history_lists_everything(self, admin_client):
        TeacherRegistrationFactory(status=constants.APPROVED)
        TeacherRegistrationFactory()
        response = admin_client.get(url("history"))
        assert response.context["page_obj"].paginator.count == 2


class TestReview:
    @pytest.fixture
    def submitted(self):
        return TeacherRegistrationFactory(submitted=True)

    def test_get_starts_review(self, admin_client, admin_user, submitted):
        response = admin_client.get(url("review", pk=submitted.pk))
        assert response.status_code == 200
        submitted.refresh_from_db()
        assert submitted.status == constants.UNDER_REVIEW
        assert submitted.reviewed_by == admin_user

    def test_get_on_under_review_does_not_log_again(self, admin_client):
        registration = TeacherRegistrationFactory(under_review=True)
        admin_client.get(url("review", pk=registration.pk))
        assert registration.change_logs.count() == 0

    def test_checklist_save_toggles_ready_status(self, admin_client, submitted):
        admin_client.get(url("review", pk=submitted.pk))
        response = admin_client.post(
            url("review", pk=submitted.pk),
            {"submit_action": "save", "checklist_official_photo": "on", "checklist_ready_for_approval": "on"},
        )
        assert response["Location"] == url("review", pk=submitted.pk)
        submitted.refresh_from_db()
        assert submitted.status == constants.READY_FOR_APPROVAL
        assert submitted.checklist_official_photo is True

        admin_client.post(url("review", pk=submitted.pk), {"submit_action": "save"})
        submitted.refresh_from_db()
        assert submitted.status == constants.UNDER_REVIEW
        assert submitted.checklist_official_photo is False

    def test_toggle_ready_ajax(self, admin_client):
        registration = TeacherRegistrationFactory(under_review=True)
        response = admin_client.post(url("toggle_ready", pk=registration.pk), {"ready": "true"})
        assert response.json() == {"ready": True, "status": constants.READY_FOR_APPROVAL}
        response = admin_client.post(url("toggle_ready", pk=registration.pk), {"ready": "false"})
        assert response.json() == {"ready": False, "status": constants.UNDER_REVIEW}

    def test_toggle_ready_refused_outside_review(self, admin_client):
        draft = TeacherRegistrationFactory()
        assert admin_client.post(url("toggle_ready", pk=draft.pk), {"ready": "true"}).status_code == 400

    def test_condition_add_and_remove(self, admin_client, admin_user):
        registration = TeacherRegistrationFactory(under_review=True)
        lookup = LookupConditionFactory(label="Complete first aid")
        response = admin_client.post(
            url("condition_add", pk=registration.pk),
            {"condition": lookup.pk, "notes": "By June", "deadline": "2026-06-30"},
        )
        payload = response.json()
        assert payload["label"] == "Complete first aid"
        assert payload["deadline"] == "2026-06-30"
        condition = RegistrationCondition.objects.get(pk=payload["id"])
        assert condition.registration == registration
        assert condition.created_by == admin_user

        response = admin_client.post(url("condition_remove", pk=condition.pk))
        assert response.json() == {"success": True}
        assert not RegistrationCondition.objects.exists()

    def test_condition_add_refused_outside_review(self, admin_client):
        draft = TeacherRegistrationFactory()
        lookup = LookupConditionFactory()
        assert admin_client.post(url("condition_add", pk=draft.pk), {"condition": lookup.pk}).status_code == 400

    def test_condition_add_invalid_form(self, admin_client):
        registration = TeacherRegistrationFactory(under_review=True)
        response = admin_client.post(url("condition_add", pk=registration.pk), {"condition": "999"})
        assert response.status_code == 400
        assert "condition" in response.json()["error"]

    def _approve_data(self, status, signatory, **extra):
        return {
            "action": "approve",
            "teacher_registration_status": status.pk,
            "signatory": signatory.pk,
            "registration_granted_date": "2026-02-01",
            "comments": "Looks good",
            **extra,
        }

    def test_approve_creates_teacher_and_emails_applicant(
        self, admin_client, admin_user, submitted, full_status, signatory
    ):
        admin_client.get(url("review", pk=submitted.pk))
        response = admin_client.post(url("review", pk=submitted.pk), self._approve_data(full_status, signatory))

        staff = SchoolStaff.objects.get(user=submitted.user)
        assert response["Location"] == url("teacher_detail", pk=staff.pk)
        assert timezone.localtime(staff.registration_granted_at).date() == date(2026, 2, 1)
        assert staff.teacher_registration_status == full_status
        submitted.refresh_from_db()
        assert submitted.status == constants.APPROVED
        assert submitted.signatory == signatory
        assert submitted.reviewer_comments == "Looks good"

        approved_mail = [m for m in mail.outbox if "approved" in m.subject]
        assert len(approved_mail) == 1
        assert approved_mail[0].to == [submitted.user.email]

    def test_approve_requires_status_and_signatory(self, admin_client, submitted, full_status, signatory):
        """The review form reports one missing field at a time: status first, then signatory."""
        admin_client.get(url("review", pk=submitted.pk))
        response = admin_client.post(url("review", pk=submitted.pk), {"action": "approve"})
        assert response.status_code == 200
        assert "teacher_registration_status" in response.context["form"].errors

        response = admin_client.post(
            url("review", pk=submitted.pk), {"action": "approve", "teacher_registration_status": full_status.pk}
        )
        assert "signatory" in response.context["form"].errors
        assert not SchoolStaff.objects.exists()

    def test_conditional_status_requires_a_condition(self, admin_client, submitted, conditional_status, signatory):
        admin_client.get(url("review", pk=submitted.pk))
        response = admin_client.post(url("review", pk=submitted.pk), self._approve_data(conditional_status, signatory))
        assert response.status_code == 200
        assert any("at least one condition" in e for e in response.context["form"].non_field_errors())

        RegistrationCondition.objects.create(registration=submitted, condition=LookupConditionFactory())
        response = admin_client.post(url("review", pk=submitted.pk), self._approve_data(conditional_status, signatory))
        assert response.status_code == 302
        assert SchoolStaff.objects.get().conditions.count() == 1

    def test_approve_model_error_is_shown_not_raised(self, admin_client, full_status, signatory):
        registration = TeacherRegistrationFactory(under_review=True, national_id_number="")
        response = admin_client.post(url("review", pk=registration.pk), self._approve_data(full_status, signatory))
        assert response.status_code == 200
        assert any("Cannot approve registration" in m for m in messages_of(response))
        registration.refresh_from_db()
        assert registration.status == constants.UNDER_REVIEW

    def test_reject_returns_to_draft_and_emails_applicant(self, admin_client, submitted):
        admin_client.get(url("review", pk=submitted.pk))
        response = admin_client.post(
            url("review", pk=submitted.pk), {"action": "reject", "comments": "Photo missing"}
        )
        assert response["Location"] == url("pending_list")
        submitted.refresh_from_db()
        assert submitted.status == constants.DRAFT
        assert submitted.reviewer_comments == "Photo missing"
        rejected_mail = [m for m in mail.outbox if "requires attention" in m.subject]
        assert len(rejected_mail) == 1
        assert "Photo missing" in rejected_mail[0].body

    def test_reject_requires_comments(self, admin_client, submitted):
        admin_client.get(url("review", pk=submitted.pk))
        response = admin_client.post(url("review", pk=submitted.pk), {"action": "reject", "comments": " "})
        assert response.status_code == 200
        assert "comments" in response.context["form"].errors
        submitted.refresh_from_db()
        assert submitted.status == constants.UNDER_REVIEW

    def test_rejected_then_resubmitted_can_be_reviewed_again(self, admin_client, applicant_client, applicant, admin_user):
        registration = TeacherRegistrationFactory(user=applicant, submitted=True)
        admin_client.get(url("review", pk=registration.pk))
        admin_client.post(url("review", pk=registration.pk), {"action": "reject", "comments": "Fix"})
        applicant_client.post(url("submit", pk=registration.pk))
        registration.refresh_from_db()
        assert registration.status == constants.SUBMITTED
        assert registration.reviewer_comments == ""
        admin_client.get(url("review", pk=registration.pk))
        registration.refresh_from_db()
        assert registration.status == constants.UNDER_REVIEW

    def test_registration_delete(self, admin_client):
        registration = TeacherRegistrationFactory(submitted=True)
        user = registration.user
        response = admin_client.post(url("registration_delete", pk=registration.pk))
        assert response["Location"] == url("pending_list")
        assert not TeacherRegistration.objects.filter(pk=registration.pk).exists()
        assert User.objects.filter(pk=user.pk).exists()


# ===========================================================================
# Renewal
# ===========================================================================


class TestRenewal:
    @pytest.fixture
    def expired_teacher(self, full_status):
        teacher = approved_teacher(status=full_status)
        teacher.registration_application_status = constants.EXPIRED
        teacher.phone_number = "+686 77777"
        teacher.save()
        StaffEducationRecord.objects.create(
            school_staff=teacher, institution_name="Old Uni",
            qualification=EmisTeacherQualFactory(), major=EmisSubjectFactory(),
        )
        assignment = SchoolStaffAssignmentFactory(
            school_staff=teacher, teacher_level_type=EmisEducationLevelFactory()
        )
        StaffTeachingDuty.objects.create(assignment=assignment, year_level=EmisClassLevelFactory())
        return teacher

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Known bug: registration_renew() and teacher_renew_on_behalf() copy "
            "SchoolStaffAssignment.teacher_level_type (nullable) into "
            "ClaimedSchoolAppointment.teacher_level_type (NOT NULL). A teacher whose "
            "assignment was added through the staff membership form, which has no "
            "level-type field, gets a 500 instead of a renewal. Fix in a separate commit."
        ),
    )
    def test_renewal_survives_assignment_without_level_type(self, client, full_status):
        teacher = approved_teacher(status=full_status)
        teacher.registration_application_status = constants.EXPIRED
        teacher.save()
        SchoolStaffAssignmentFactory(school_staff=teacher, teacher_level_type=None)
        client.force_login(teacher.user)
        response = client.get(url("registration_renew"))
        assert response.status_code == 302
        assert TeacherRegistration.objects.filter(user=teacher.user).exists()

    def test_not_eligible_when_far_from_expiry(self, client):
        teacher = approved_teacher(valid_until=timezone.now() + timedelta(days=365))
        client.force_login(teacher.user)
        response = client.get(url("registration_renew"), follow=True)
        assert any("not yet eligible" in m for m in messages_of(response))
        assert not TeacherRegistration.objects.exists()

    def test_eligible_within_renewal_window(self, client):
        teacher = approved_teacher(valid_until=timezone.now() + timedelta(days=30))
        client.force_login(teacher.user)
        client.get(url("registration_renew"))
        assert TeacherRegistration.objects.filter(registration_type=TeacherRegistration.RENEWAL).exists()

    def test_expired_teacher_gets_prefilled_renewal(self, client, expired_teacher, admin_user):
        client.force_login(expired_teacher.user)
        response = client.get(url("registration_renew"))

        renewal = TeacherRegistration.objects.get(user=expired_teacher.user)
        assert response["Location"] == url("edit", pk=renewal.pk)
        assert renewal.registration_type == TeacherRegistration.RENEWAL
        assert renewal.teacher_category == TeacherRegistration.CURRENT_TEACHER
        assert renewal.approved_staff_profile == expired_teacher
        assert renewal.national_id_number == "T-100"
        assert renewal.phone_number == "+686 77777"
        assert renewal.education_records.get().institution_name == "Old Uni"
        appointment = renewal.claimed_appointments.get()
        assert appointment.current_school == expired_teacher.assignments.get().school
        assert appointment.claimed_duties.count() == 1
        assert "pre-filled" in renewal.change_logs.get().notes
        assert len(mail.outbox) == 1

    def test_existing_renewal_draft_is_reused(self, client, expired_teacher):
        client.force_login(expired_teacher.user)
        first = client.get(url("registration_renew"))["Location"]
        second = client.get(url("registration_renew"))["Location"]
        assert first == second
        assert TeacherRegistration.objects.count() == 1

    def test_pending_renewal_blocks_another(self, client, expired_teacher):
        TeacherRegistrationFactory(user=expired_teacher.user, renewal=True, submitted=True)
        client.force_login(expired_teacher.user)
        response = client.get(url("registration_renew"), follow=True)
        assert any("pending review" in m for m in messages_of(response))
        assert TeacherRegistration.objects.count() == 1

    def test_my_registration_for_expired_teacher_offers_renewal(self, client, expired_teacher):
        client.force_login(expired_teacher.user)
        response = client.get(url("my_registration"))
        assert response.status_code == 200
        assert response.context["is_expired"] is True
        assert response.context["can_renew"] is True

    def test_my_registration_jumps_to_renewal_draft(self, client, expired_teacher):
        renewal = TeacherRegistrationFactory(user=expired_teacher.user, renewal=True)
        client.force_login(expired_teacher.user)
        assert client.get(url("my_registration"))["Location"] == url("edit", pk=renewal.pk)

    def test_renew_on_behalf(self, admin_client, admin_user, expired_teacher):
        response = admin_client.post(url("teacher_renew_on_behalf", pk=expired_teacher.pk))
        renewal = TeacherRegistration.objects.get(user=expired_teacher.user)
        assert response["Location"] == url("edit", pk=renewal.pk)
        assert renewal.created_by == admin_user
        assert "on behalf" in renewal.change_logs.get().notes

    def test_renew_on_behalf_refused_unless_expired(self, admin_client):
        teacher = approved_teacher()
        response = admin_client.post(url("teacher_renew_on_behalf", pk=teacher.pk), follow=True)
        assert any("Only expired" in m for m in messages_of(response))
        assert not TeacherRegistration.objects.exists()

    def test_renew_on_behalf_existing_renewal_redirects(self, admin_client, expired_teacher):
        renewal = TeacherRegistrationFactory(user=expired_teacher.user, renewal=True, submitted=True)
        response = admin_client.post(url("teacher_renew_on_behalf", pk=expired_teacher.pk))
        assert response["Location"] == url("review", pk=renewal.pk)

    def test_renewal_approved_through_review(self, admin_client, expired_teacher, full_status, signatory):
        renewal = TeacherRegistrationFactory(
            user=expired_teacher.user, renewal=True, under_review=True,
            national_id_number="T-100", approved_staff_profile=expired_teacher,
        )
        response = admin_client.post(url("review", pk=renewal.pk), {
            "action": "approve", "teacher_registration_status": full_status.pk,
            "signatory": signatory.pk, "registration_granted_date": "2026-03-01",
        })
        assert response["Location"] == url("teacher_detail", pk=expired_teacher.pk)
        expired_teacher.refresh_from_db()
        assert expired_teacher.registration_application_status == constants.APPROVED
        assert expired_teacher.teacher_registration_number == "TR26-TEACH1-X"
        assert SchoolStaff.objects.count() == 1

    def test_review_shows_staff_documents_needing_renewal(self, admin_client, expired_teacher):
        needs = EmisTeacherLinkTypeFactory(code="POLCLEAR", needs_renewal=True)
        keeps = EmisTeacherLinkTypeFactory(code="BIRTHCERT", needs_renewal=False)
        RegistrationDocumentFactory(registration=None, school_staff=expired_teacher, doc_link_type=needs)
        RegistrationDocumentFactory(registration=None, school_staff=expired_teacher, doc_link_type=keeps)
        renewal = TeacherRegistrationFactory(
            user=expired_teacher.user, renewal=True, under_review=True, approved_staff_profile=expired_teacher,
        )
        RegistrationDocumentFactory(registration=renewal, doc_link_type=needs)
        response = admin_client.get(url("review", pk=renewal.pk))
        rows = {row["doc"].doc_link_type.code: row for row in response.context["staff_documents"]}
        assert rows["POLCLEAR"]["needs_renewal"] is True and rows["POLCLEAR"]["renewed"] is True
        assert rows["BIRTHCERT"]["needs_renewal"] is False


# ===========================================================================
# Post-approval teacher administration
# ===========================================================================


@pytest.fixture
def teacher(full_status):
    staff = approved_teacher(status=full_status, valid_until=datetime(2029, 1, 1, tzinfo=dt_timezone.utc))
    TeacherRegistrationFactory(user=staff.user, status=constants.APPROVED, approved_staff_profile=staff,
                               reviewed_at=timezone.now())
    return staff


class TestTeacherAdminActions:
    def test_force_expiry(self, admin_client, admin_user, teacher, expired_status):
        response = admin_client.post(url("teacher_force_expiry", pk=teacher.pk), **AJAX)
        assert response.json()["ok"] is True
        teacher.refresh_from_db()
        assert teacher.registration_application_status == constants.EXPIRED
        assert teacher.teacher_registration_status == expired_status
        log = RegistrationChangeLog.objects.get()
        assert log.new_value == constants.EXPIRED
        assert "force-expired" in log.notes
        assert "Full Registration" in log.notes
        assert len(mail.outbox) == 1
        assert "expired" in mail.outbox[0].subject
        assert url("registration_renew") in mail.outbox[0].body

    def test_force_expiry_refused_when_not_approved(self, admin_client, teacher):
        teacher.registration_application_status = constants.EXPIRED
        teacher.save()
        response = admin_client.post(url("teacher_force_expiry", pk=teacher.pk), **AJAX)
        assert response.json()["ok"] is False
        assert not mail.outbox

    def test_edit_granted_at_recomputes_validity_and_logs(self, admin_client, teacher):
        response = admin_client.post(
            url("teacher_edit_granted_at", pk=teacher.pk), {"registration_granted_date": "2025-06-15"}, **AJAX
        )
        assert response.json()["ok"] is True
        teacher.refresh_from_db()
        assert timezone.localtime(teacher.registration_granted_at).date() == date(2025, 6, 15)
        assert teacher.registration_valid_until == teacher.registration_granted_at + timedelta(days=3 * 365)
        log = RegistrationChangeLog.objects.get(field_name="registration_granted_at")
        assert "2025-06-15" in log.new_value
        assert "Valid Until recomputed" in log.notes

    def test_edit_granted_at_rejects_bad_date(self, admin_client, teacher):
        response = admin_client.post(url("teacher_edit_granted_at", pk=teacher.pk), {"registration_granted_date": "x"}, **AJAX)
        assert response.json()["ok"] is False

    def test_resend_renewal_notification(self, admin_client, teacher):
        response = admin_client.post(url("teacher_resend_renewal_notification", pk=teacher.pk), **AJAX)
        assert response.json()["ok"] is True
        assert mail.outbox[0].to == [teacher.user.email]

    def test_edit_professional_section(self, admin_client, teacher):
        response = admin_client.post(
            url("teacher_edit_section", pk=teacher.pk, section="professional"),
            {"highest_qualification": "masters", "years_of_experience": "9", "teacher_payroll_number": "PF9"},
        )
        assert response["Location"] == url("teacher_detail", pk=teacher.pk)
        teacher.refresh_from_db()
        assert teacher.highest_qualification == "masters"
        logs = RegistrationChangeLog.objects.order_by("field_name")
        assert [l.field_name for l in logs] == ["highest_qualification", "teacher_payroll_number", "years_of_experience"]
        assert all("Professional Information edited" in l.notes for l in logs)
        assert logs.get(field_name="years_of_experience").new_value == "9"

    def test_edit_section_without_changes_logs_nothing(self, admin_client, teacher):
        admin_client.post(
            url("teacher_edit_section", pk=teacher.pk, section="professional"),
            {"highest_qualification": teacher.highest_qualification or "", "years_of_experience": "", "teacher_payroll_number": ""},
        )
        assert not RegistrationChangeLog.objects.exists()

    def test_education_record_add_edit_delete(self, admin_client, teacher):
        qual, major = EmisTeacherQualFactory(), EmisSubjectFactory()
        payload = {"institution_name": "USP", "qualification": qual.pk, "major": major.pk, "duration_unit": "years"}
        admin_client.post(url("teacher_record_add", pk=teacher.pk, rtype="education"), payload)
        record = teacher.education_records.get()
        assert record.institution_name == "USP"

        admin_client.post(
            url("teacher_record_edit", pk=teacher.pk, rtype="education", record_pk=record.pk),
            {**payload, "institution_name": "USP Laucala"},
        )
        record.refresh_from_db()
        assert record.institution_name == "USP Laucala"

        admin_client.post(url("teacher_record_delete", pk=teacher.pk, rtype="education", record_pk=record.pk))
        assert not teacher.education_records.exists()
        notes = list(RegistrationChangeLog.objects.order_by("pk").values_list("notes", flat=True))
        assert [n.split(" ")[0] for n in notes] == ["Added", "Edited", "Removed"]

    def test_record_lookup_is_scoped_to_teacher(self, admin_client, teacher):
        other = StaffEducationRecord.objects.create(
            school_staff=approved_teacher(national_id_number="T-2", teacher_registration_number="TR26-OTHER-Y"),
            institution_name="X", qualification=EmisTeacherQualFactory(), major=EmisSubjectFactory(),
        )
        response = admin_client.get(url("teacher_record_edit", pk=teacher.pk, rtype="education", record_pk=other.pk))
        assert response.status_code == 404

    def test_assignment_add_with_duties_then_edit(self, admin_client, teacher):
        school, job = EmisSchoolFactory(), EmisJobTitleFactory()
        year, subject = EmisClassLevelFactory(), EmisSubjectFactory()
        admin_client.post(url("teacher_assignment_add", pk=teacher.pk), {
            "school": school.pk, "job_title": job.pk, "start_date": "2026-01-10",
            "duties[0][year_level]": year.pk, "duties[0][subjects][]": [subject.pk],
        })
        assignment = teacher.assignments.get()
        assert assignment.school == school
        assert assignment.teaching_duties.get().subject == subject

        other_year = EmisClassLevelFactory()
        admin_client.post(url("teacher_assignment_edit", pk=teacher.pk, assignment_pk=assignment.pk), {
            "school": school.pk, "job_title": job.pk, "start_date": "2026-01-10",
            "duties[0][year_level]": other_year.pk,
        })
        duty = assignment.teaching_duties.get()
        assert duty.year_level == other_year and duty.subject is None

    def test_teacher_delete_keeps_user_and_unlinks_registration(self, admin_client, teacher):
        user = teacher.user
        registration = teacher.registration_history.get()
        response = admin_client.post(url("teacher_delete", pk=teacher.pk))
        assert response["Location"] == url("teachers_list")
        assert not SchoolStaff.objects.filter(pk=teacher.pk).exists()
        assert User.objects.filter(pk=user.pk).exists()
        registration.refresh_from_db()
        assert registration.approved_staff_profile is None

    def test_photo_crop_requires_photo(self, admin_client, teacher):
        response = admin_client.post(url("teacher_photo_crop", pk=teacher.pk), {"cropped_image": png_upload()})
        assert response.status_code == 404

    def test_photo_crop_saves_and_removes(self, admin_client, teacher, photo_link_type):
        photo = RegistrationDocumentFactory(registration=None, school_staff=teacher, doc_link_type=photo_link_type)
        response = admin_client.post(url("teacher_photo_crop", pk=teacher.pk), {"cropped_image": png_upload()})
        assert response.json()["success"] is True
        photo.refresh_from_db()
        assert photo.cropped_file
        assert photo.display_image == photo.cropped_file

        response = admin_client.post(url("teacher_photo_crop", pk=teacher.pk), {"action": "remove"})
        assert response.json() == {"success": True, "removed": True}
        photo.refresh_from_db()
        assert not photo.cropped_file

    def test_photo_crop_rejects_invalid_image(self, admin_client, teacher, photo_link_type):
        RegistrationDocumentFactory(registration=None, school_staff=teacher, doc_link_type=photo_link_type)
        bad = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
        response = admin_client.post(url("teacher_photo_crop", pk=teacher.pk), {"cropped_image": bad})
        assert response.status_code == 400

    def test_teacher_detail_shows_passport_photo(self, admin_client, teacher, photo_link_type):
        photo = RegistrationDocumentFactory(registration=None, school_staff=teacher, doc_link_type=photo_link_type)
        response = admin_client.get(url("teacher_detail", pk=teacher.pk))
        assert response.context["passport_photo"] == photo


class TestTeachersList:
    def test_filters_and_sorting(self, admin_client, full_status):
        school_a, school_b = EmisSchoolFactory(), EmisSchoolFactory()
        alpha = approved_teacher(user=UserFactory(last_name="Alpha"), national_id_number="A", teacher_registration_number="TR26-A-1")
        beta = approved_teacher(user=UserFactory(last_name="Beta"), national_id_number="B", teacher_registration_number="TR26-B-2")
        SchoolStaffAssignmentFactory(school_staff=alpha, school=school_a)
        SchoolStaffAssignmentFactory(school_staff=beta, school=school_b)
        beta.registration_application_status = constants.EXPIRED
        beta.save()

        rows = lambda params: list(admin_client.get(url("teachers_list"), params).context["page_obj"].object_list)
        assert rows({}) == [alpha, beta]
        assert rows({"sort": "name", "dir": "desc"}) == [beta, alpha]
        assert rows({"q": "bet"}) == [beta]
        assert rows({"school": school_a.emis_school_no}) == [alpha]
        assert rows({"registration_application_status": constants.EXPIRED}) == [beta]

    def test_non_teaching_staff_excluded(self, admin_client):
        approved_teacher()
        from core.tests.factories import SchoolStaffFactory
        SchoolStaffFactory()
        assert admin_client.get(url("teachers_list")).context["page_obj"].paginator.count == 1

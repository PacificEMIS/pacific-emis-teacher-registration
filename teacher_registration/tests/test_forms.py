"""Form tests for teacher_registration: validation rules, querysets, and save side effects."""

from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from core import permissions as p
from core.models import SchoolStaff, SchoolStaffAssignment, StaffEducationRecord, StaffTrainingRecord
from core.tests.factories import GroupFactory, UserFactory
from integrations.tests.factories import (
    EmisClassLevelFactory,
    EmisEducationLevelFactory,
    EmisGenderFactory,
    EmisJobTitleFactory,
    EmisSchoolFactory,
    EmisSubjectFactory,
    EmisTeacherLinkTypeFactory,
    EmisTeacherPdFocusFactory,
    EmisTeacherQualFactory,
    EmisTeacherRegistrationStatusFactory,
)
from teacher_registration import constants
from teacher_registration.forms import (
    ChecklistOfficialForm,
    ClaimedDutyForm,
    ClaimedSchoolAppointmentForm,
    ClaimedSchoolAppointmentFormSet,
    EducationRecordForm,
    EducationRecordFormSet,
    GroupedDutyForm,
    ProfessionalInfoForm,
    RegistrationConditionForm,
    RegistrationDocumentForm,
    RegistrationReviewForm,
    StaffAssignmentForm,
    StaffEducationRecordForm,
    StaffTeacherCreateForm,
    StaffTrainingRecordForm,
    TeacherRegistrationForm,
    TrainingRecordForm,
    TrainingRecordFormSet,
)
from teacher_registration.tests.factories import (
    LookupConditionFactory,
    RegistrationConditionFactory,
    TeacherRegistrationFactory,
)

pytestmark = pytest.mark.django_db


class TestStaffTeacherCreateForm:
    def test_email_required_and_validated(self):
        assert not StaffTeacherCreateForm({}).is_valid()
        assert not StaffTeacherCreateForm({"email": "nope"}).is_valid()
        assert StaffTeacherCreateForm({"email": "t@example.org"}).is_valid()

    def test_names_optional(self):
        form = StaffTeacherCreateForm({"email": "t@example.org", "first_name": "", "last_name": ""})
        assert form.is_valid()


class TestTeacherRegistrationForm:
    def test_initial_comes_from_instance_user(self):
        registration = TeacherRegistrationFactory(user=UserFactory(first_name="A", last_name="B", email="ab@example.org"))
        form = TeacherRegistrationForm(instance=registration)
        assert form.initial["first_name"] == "A"
        assert form.initial["email"] == "ab@example.org"

    def test_initial_comes_from_user_kwarg_without_instance(self):
        user = UserFactory(first_name="C")
        assert TeacherRegistrationForm(user=user).initial["first_name"] == "C"

    def test_email_disabled_when_not_editable(self):
        form = TeacherRegistrationForm(email_editable=False)
        assert form.fields["email"].disabled is True

    def test_lookup_querysets_exclude_inactive(self):
        active = EmisGenderFactory(active=True)
        EmisGenderFactory(active=False)
        school = EmisSchoolFactory(active=True)
        EmisSchoolFactory(active=False)
        form = TeacherRegistrationForm()
        assert list(form.fields["gender"].queryset) == [active]
        assert list(form.fields["nearby_school"].queryset) == [school]

    def test_save_updates_user_name_email_and_username(self):
        registration = TeacherRegistrationFactory()
        form = TeacherRegistrationForm(
            {"first_name": "New", "last_name": "Name", "email": "new@example.org", "teacher_category": "new"},
            instance=registration,
        )
        assert form.is_valid(), form.errors
        form.save()
        registration.user.refresh_from_db()
        assert (registration.user.first_name, registration.user.last_name) == ("New", "Name")
        assert registration.user.email == registration.user.username == "new@example.org"

    def test_save_with_disabled_email_keeps_user_email(self):
        registration = TeacherRegistrationFactory(user=UserFactory(email="keep@example.org"))
        form = TeacherRegistrationForm(
            {"first_name": "X", "last_name": "Y", "email": "other@example.org", "teacher_category": "new"},
            instance=registration, email_editable=False,
        )
        assert form.is_valid(), form.errors
        form.save()
        registration.user.refresh_from_db()
        assert registration.user.email == "keep@example.org"

    def test_save_with_blank_email_keeps_user_email(self):
        registration = TeacherRegistrationFactory(user=UserFactory(email="keep@example.org"))
        form = TeacherRegistrationForm({"first_name": "X", "last_name": "Y", "email": "", "teacher_category": "new"}, instance=registration)
        assert form.is_valid(), form.errors
        form.save()
        registration.user.refresh_from_db()
        assert registration.user.email == "keep@example.org"

    def test_applicant_checklist_fields_cover_every_checklist_item(self):
        fields = set(TeacherRegistrationForm.Meta.fields)
        for suffix, *_ in constants.CHECKLIST_ITEMS:
            assert f"checklist_applicant_{suffix}" in fields, suffix


class TestRegistrationDocumentForm:
    @pytest.fixture
    def link_type(self):
        return EmisTeacherLinkTypeFactory(active=True)

    def test_inactive_link_types_excluded(self, link_type):
        EmisTeacherLinkTypeFactory(active=False)
        assert list(RegistrationDocumentForm().fields["doc_link_type"].queryset) == [link_type]

    @pytest.mark.parametrize("content_type", ["application/pdf", "image/jpeg", "image/png", "image/gif"])
    def test_allowed_types(self, link_type, content_type):
        upload = SimpleUploadedFile("f.bin", b"data", content_type=content_type)
        form = RegistrationDocumentForm({"doc_link_type": link_type.pk}, {"file": upload})
        assert form.is_valid(), form.errors

    def test_disallowed_type(self, link_type):
        upload = SimpleUploadedFile("f.txt", b"data", content_type="text/plain")
        form = RegistrationDocumentForm({"doc_link_type": link_type.pk}, {"file": upload})
        assert "file" in form.errors
        assert "Only PDF and image" in form.errors["file"][0]

    def test_size_limit(self, link_type):
        upload = SimpleUploadedFile("f.pdf", b"x" * (10 * 1024 * 1024 + 1), content_type="application/pdf")
        form = RegistrationDocumentForm({"doc_link_type": link_type.pk}, {"file": upload})
        assert "10MB" in form.errors["file"][0]

    def test_file_and_type_required(self):
        form = RegistrationDocumentForm({}, {})
        assert {"doc_link_type", "file"} <= set(form.errors)

    def test_save_derives_filename_size_and_type(self, link_type):
        registration = TeacherRegistrationFactory()
        upload = SimpleUploadedFile("Scan.JPEG", b"12345", content_type="image/jpeg")
        form = RegistrationDocumentForm({"doc_link_type": link_type.pk}, {"file": upload})
        assert form.is_valid()
        doc = form.save(commit=False)
        doc.registration = registration
        doc.save()
        assert (doc.original_filename, doc.file_size, doc.doc_type) == ("Scan.JPEG", 5, "jpeg")

    def test_save_without_extension_leaves_type_blank(self, link_type):
        registration = TeacherRegistrationFactory()
        upload = SimpleUploadedFile("noext", b"12345", content_type="application/pdf")
        form = RegistrationDocumentForm({"doc_link_type": link_type.pk}, {"file": upload})
        assert form.is_valid()
        doc = form.save(commit=False)
        doc.registration = registration
        doc.save()
        assert doc.doc_type == ""


class TestRegistrationReviewForm:
    @pytest.fixture
    def signatory(self):
        user = UserFactory(first_name="Sig", last_name="Natory")
        user.groups.add(GroupFactory(name=p.GROUP_REGISTRATION_SIGNATORIES))
        return user

    @pytest.fixture
    def status(self):
        return EmisTeacherRegistrationStatusFactory(label="Full Registration")

    def test_signatory_choices_are_active_members_of_the_group(self, signatory):
        inactive = UserFactory(is_active=False)
        inactive.groups.add(GroupFactory(name=p.GROUP_REGISTRATION_SIGNATORIES))
        UserFactory()
        form = RegistrationReviewForm()
        assert list(form.fields["signatory"].queryset) == [signatory]
        assert form.fields["signatory"].label_from_instance(signatory) == "Sig Natory"

    def test_status_choices_exclude_inactive(self, status):
        EmisTeacherRegistrationStatusFactory(active=False)
        assert list(RegistrationReviewForm().fields["teacher_registration_status"].queryset) == [status]

    def test_granted_date_defaults_to_today(self):
        assert RegistrationReviewForm().fields["registration_granted_date"].initial == timezone.localdate()

    def test_reject_requires_comments(self):
        form = RegistrationReviewForm({"action": "reject", "comments": "  "})
        assert not form.is_valid()
        assert "comments" in form.errors

    def test_reject_with_comments_is_valid(self):
        assert RegistrationReviewForm({"action": "reject", "comments": "Missing documents"}).is_valid()

    def test_approve_requires_status_then_signatory(self, status, signatory):
        form = RegistrationReviewForm({"action": "approve"})
        assert "teacher_registration_status" in form.errors
        form = RegistrationReviewForm({"action": "approve", "teacher_registration_status": status.pk})
        assert "signatory" in form.errors
        form = RegistrationReviewForm(
            {"action": "approve", "teacher_registration_status": status.pk, "signatory": signatory.pk}
        )
        assert form.is_valid(), form.errors

    def test_conditional_status_requires_a_condition(self, signatory):
        conditional = EmisTeacherRegistrationStatusFactory(label="Full Registration with Conditions")
        registration = TeacherRegistrationFactory(under_review=True)
        data = {"action": "approve", "teacher_registration_status": conditional.pk, "signatory": signatory.pk}

        form = RegistrationReviewForm(data, registration=registration)
        assert not form.is_valid()
        assert "at least one condition" in form.non_field_errors()[0]

        RegistrationConditionFactory(registration=registration)
        assert RegistrationReviewForm(data, registration=registration).is_valid()

    def test_conditional_check_skipped_without_registration(self, signatory):
        conditional = EmisTeacherRegistrationStatusFactory(label="Full Registration with Conditions")
        form = RegistrationReviewForm(
            {"action": "approve", "teacher_registration_status": conditional.pk, "signatory": signatory.pk}
        )
        assert form.is_valid()

    def test_unknown_action_is_invalid(self):
        assert "action" in RegistrationReviewForm({"action": "maybe"}).errors


class TestRegistrationConditionForm:
    def test_only_active_condition_types_offered(self):
        active = LookupConditionFactory(active=True)
        LookupConditionFactory(active=False)
        assert list(RegistrationConditionForm().fields["condition"].queryset) == [active]

    def test_condition_required_notes_and_deadline_optional(self):
        active = LookupConditionFactory()
        assert "condition" in RegistrationConditionForm({}).errors
        assert RegistrationConditionForm({"condition": active.pk}).is_valid()


def test_official_checklist_form_covers_every_item_plus_ready_flag():
    fields = set(ChecklistOfficialForm.Meta.fields)
    expected = {f"checklist_official_{suffix}" for suffix, *_ in constants.CHECKLIST_ITEMS}
    assert fields == expected | {"checklist_ready_for_approval"}


class TestRecordForms:
    def test_education_requires_institution_qualification_major(self):
        form = EducationRecordForm({})
        assert {"institution_name", "qualification", "major"} <= set(form.errors)

    def test_education_querysets_active_only(self):
        active_qual = EmisTeacherQualFactory(active=True)
        EmisTeacherQualFactory(active=False)
        active_subject = EmisSubjectFactory(active=True)
        EmisSubjectFactory(active=False)
        form = EducationRecordForm()
        assert list(form.fields["qualification"].queryset) == [active_qual]
        for name in ("major", "major2", "minor", "minor2"):
            assert list(form.fields[name].queryset) == [active_subject], name

    def test_education_valid(self):
        form = EducationRecordForm({
            "institution_name": "USP", "qualification": EmisTeacherQualFactory().pk,
            "major": EmisSubjectFactory().pk, "duration_unit": "years", "completed": "on",
        })
        assert form.is_valid(), form.errors

    def test_training_requires_provider_and_title(self):
        assert {"provider_institution", "title"} <= set(TrainingRecordForm({}).errors)
        form = TrainingRecordForm({"provider_institution": "KTC", "title": "Workshop", "duration_unit": "days"})
        assert form.is_valid(), form.errors

    def test_training_querysets_active_only(self):
        active = EmisTeacherPdFocusFactory(active=True)
        EmisTeacherPdFocusFactory(active=False)
        assert list(TrainingRecordForm().fields["focus"].queryset) == [active]

    def test_appointment_required_fields(self):
        form = ClaimedSchoolAppointmentForm({})
        assert {"teacher_level_type", "current_school", "employment_position"} <= set(form.errors)
        form = ClaimedSchoolAppointmentForm({
            "teacher_level_type": EmisEducationLevelFactory().pk,
            "current_school": EmisSchoolFactory().pk,
            "employment_position": EmisJobTitleFactory().pk,
        })
        assert form.is_valid(), form.errors

    def test_appointment_rejects_inactive_school(self):
        inactive = EmisSchoolFactory(active=False)
        form = ClaimedSchoolAppointmentForm({
            "teacher_level_type": EmisEducationLevelFactory().pk,
            "current_school": inactive.pk,
            "employment_position": EmisJobTitleFactory().pk,
        })
        assert "current_school" in form.errors

    def test_duty_form_labels_use_lookup_label(self):
        level = EmisClassLevelFactory(label="Form 3")
        subject = EmisSubjectFactory(label="Maths")
        form = ClaimedDutyForm()
        assert form.fields["year_level"].label_from_instance(level) == "Form 3"
        assert form.fields["subject"].label_from_instance(subject) == "Maths"
        assert ClaimedDutyForm({"year_level": level.pk}).is_valid()

    def test_grouped_duty_form(self):
        level = EmisClassLevelFactory()
        s1, s2 = EmisSubjectFactory(), EmisSubjectFactory()
        form = GroupedDutyForm({"year_level": level.pk, "subjects": [s1.pk, s2.pk]})
        assert form.is_valid()
        assert set(form.cleaned_data["subjects"]) == {s1, s2}
        assert "subjects" in GroupedDutyForm({"year_level": level.pk}).errors


class TestFormsets:
    def test_prefixes_and_extras(self):
        registration = TeacherRegistrationFactory()
        for formset_class, model in (
            (EducationRecordFormSet, "education_records"),
            (TrainingRecordFormSet, "training_records"),
            (ClaimedSchoolAppointmentFormSet, "claimed_appointments"),
        ):
            formset = formset_class(instance=registration, prefix=model)
            assert formset.extra == 1
            assert formset.can_delete is True
            assert formset.min_num == 0
            assert formset.total_form_count() == 1

    def test_education_formset_saves_and_deletes(self):
        registration = TeacherRegistrationFactory()
        qual, major = EmisTeacherQualFactory(), EmisSubjectFactory()
        data = {
            "education_records-TOTAL_FORMS": "1", "education_records-INITIAL_FORMS": "0",
            "education_records-MIN_NUM_FORMS": "0", "education_records-MAX_NUM_FORMS": "1000",
            "education_records-0-institution_name": "USP",
            "education_records-0-qualification": qual.pk,
            "education_records-0-major": major.pk,
            "education_records-0-duration_unit": "years",
        }
        formset = EducationRecordFormSet(data, instance=registration, prefix="education_records")
        assert formset.is_valid(), formset.errors
        formset.save()
        record = registration.education_records.get()

        data.update({
            "education_records-INITIAL_FORMS": "1",
            "education_records-0-id": record.pk,
            "education_records-0-DELETE": "on",
        })
        formset = EducationRecordFormSet(data, instance=registration, prefix="education_records")
        assert formset.is_valid(), formset.errors
        formset.save()
        assert not registration.education_records.exists()


class TestStaffForms:
    def test_professional_info_fields(self):
        assert ProfessionalInfoForm.Meta.fields == ["highest_qualification", "years_of_experience", "teacher_payroll_number"]
        assert ProfessionalInfoForm.Meta.model is SchoolStaff
        assert ProfessionalInfoForm({"highest_qualification": "masters", "years_of_experience": "2"}).is_valid()
        assert "years_of_experience" in ProfessionalInfoForm({"years_of_experience": "-1"}).errors

    def test_staff_record_forms_mirror_registration_forms(self):
        assert StaffEducationRecordForm.Meta.model is StaffEducationRecord
        assert StaffEducationRecordForm.Meta.fields == EducationRecordForm.Meta.fields
        assert StaffTrainingRecordForm.Meta.model is StaffTrainingRecord
        assert StaffTrainingRecordForm.Meta.fields == TrainingRecordForm.Meta.fields

    def test_staff_assignment_form(self):
        assert StaffAssignmentForm.Meta.model is SchoolStaffAssignment
        assert "current_island_station" not in StaffAssignmentForm.Meta.fields
        school, job = EmisSchoolFactory(), EmisJobTitleFactory()
        EmisSchoolFactory(active=False)
        form = StaffAssignmentForm({"school": school.pk, "job_title": job.pk, "start_date": "2026-01-01"})
        assert form.is_valid(), form.errors
        assert list(StaffAssignmentForm().fields["school"].queryset) == [school]
        assert {"school", "job_title"} <= set(StaffAssignmentForm({}).errors)

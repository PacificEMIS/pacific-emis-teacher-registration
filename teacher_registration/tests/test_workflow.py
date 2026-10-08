"""
Workflow tests for TeacherRegistration: every transition, approve() for
initial and renewal registrations, and reject().

Each transition is checked from every status so a change to the allowed
set of source statuses is caught immediately.
"""

from datetime import date, datetime, timedelta, timezone as dt_timezone

import pytest
import time_machine
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from core.models import (
    SchoolStaff,
    SchoolStaffAssignment,
    StaffEducationRecord,
    StaffTeachingDuty,
    StaffTrainingRecord,
)
from core.tests.factories import SchoolStaffFactory, UserFactory
from integrations.tests.factories import EmisTeacherRegistrationStatusFactory
from teacher_registration import constants
from teacher_registration.models import (
    ClaimedSchoolAppointment,
    EducationRecord,
    RegistrationChangeLog,
    RegistrationCondition,
    RegistrationDocument,
    TrainingRecord,
)
from teacher_registration.tests.factories import (
    ClaimedDutyFactory,
    ClaimedSchoolAppointmentFactory,
    EducationRecordFactory,
    RegistrationConditionFactory,
    RegistrationDocumentFactory,
    TeacherRegistrationFactory,
    TrainingRecordFactory,
)
from teacher_registration.utils import generate_teacher_registration_number

pytestmark = pytest.mark.django_db

ALL_STATUSES = [s for s, _ in constants.REGISTRATION_APPLICATION_STATUS_CHOICES]
REVIEWABLE = [constants.SUBMITTED, constants.UNDER_REVIEW, constants.READY_FOR_APPROVAL]


@pytest.fixture
def reviewer():
    return UserFactory(username="reviewer@example.org")


def latest_log(registration):
    return registration.change_logs.order_by("-changed_at", "-pk").first()


# ---------------------------------------------------------------------------
# Simple properties
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_is_editable_and_can_submit_only_in_draft(status):
    registration = TeacherRegistrationFactory(status=status)
    assert registration.is_editable is (status == constants.DRAFT)
    assert registration.can_submit is (status == constants.DRAFT)


# ---------------------------------------------------------------------------
# submit()
# ---------------------------------------------------------------------------


class TestSubmit:
    def test_moves_draft_to_submitted_and_logs(self):
        registration = TeacherRegistrationFactory()
        registration.submit()
        registration.refresh_from_db()

        assert registration.status == constants.SUBMITTED
        assert registration.submitted_at is not None
        log = latest_log(registration)
        assert (log.old_value, log.new_value) == (constants.DRAFT, constants.SUBMITTED)
        assert log.changed_by == registration.user
        assert "submitted" in log.notes.lower()

    def test_logs_acting_user_when_given(self, reviewer):
        registration = TeacherRegistrationFactory()
        registration.submit(user=reviewer)
        assert latest_log(registration).changed_by == reviewer

    def test_resubmission_clears_rejection_state(self):
        registration = TeacherRegistrationFactory(
            reviewer_comments="Missing police clearance", checklist_ready_for_approval=True
        )
        registration.submit()
        registration.refresh_from_db()
        assert registration.reviewer_comments == ""
        assert registration.checklist_ready_for_approval is False

    @pytest.mark.parametrize("status", [s for s in ALL_STATUSES if s != constants.DRAFT])
    def test_rejects_non_draft(self, status):
        registration = TeacherRegistrationFactory(status=status)
        with pytest.raises(ValueError):
            registration.submit()
        registration.refresh_from_db()
        assert registration.status == status
        assert registration.change_logs.count() == 0


# ---------------------------------------------------------------------------
# start_review(), mark_ready_for_approval(), revert_to_under_review()
# ---------------------------------------------------------------------------


class TestStartReview:
    def test_from_submitted(self, reviewer):
        registration = TeacherRegistrationFactory(submitted=True)
        registration.start_review(reviewer)
        registration.refresh_from_db()
        assert registration.status == constants.UNDER_REVIEW
        assert registration.reviewed_by == reviewer
        log = latest_log(registration)
        assert log.notes == "Review started"
        assert log.changed_by == reviewer

    def test_from_rejected_is_a_re_review(self, reviewer):
        registration = TeacherRegistrationFactory(status=constants.REJECTED)
        registration.start_review(reviewer)
        assert registration.status == constants.UNDER_REVIEW
        assert latest_log(registration).notes == "Re-review started"

    @pytest.mark.parametrize(
        "status", [s for s in ALL_STATUSES if s not in (constants.SUBMITTED, constants.REJECTED)]
    )
    def test_rejects_other_statuses(self, reviewer, status):
        registration = TeacherRegistrationFactory(status=status)
        with pytest.raises(ValueError):
            registration.start_review(reviewer)
        registration.refresh_from_db()
        assert registration.status == status


class TestReadyForApproval:
    def test_mark_ready_from_under_review(self, reviewer):
        registration = TeacherRegistrationFactory(under_review=True)
        registration.mark_ready_for_approval(reviewer)
        registration.refresh_from_db()
        assert registration.status == constants.READY_FOR_APPROVAL
        log = latest_log(registration)
        assert (log.old_value, log.new_value) == (constants.UNDER_REVIEW, constants.READY_FOR_APPROVAL)

    @pytest.mark.parametrize("status", [s for s in ALL_STATUSES if s != constants.UNDER_REVIEW])
    def test_mark_ready_rejects_other_statuses(self, reviewer, status):
        registration = TeacherRegistrationFactory(status=status)
        with pytest.raises(ValueError):
            registration.mark_ready_for_approval(reviewer)

    def test_revert_from_ready(self, reviewer):
        registration = TeacherRegistrationFactory(ready=True)
        registration.revert_to_under_review(reviewer)
        registration.refresh_from_db()
        assert registration.status == constants.UNDER_REVIEW
        log = latest_log(registration)
        assert (log.old_value, log.new_value) == (constants.READY_FOR_APPROVAL, constants.UNDER_REVIEW)

    @pytest.mark.parametrize(
        "status", [s for s in ALL_STATUSES if s != constants.READY_FOR_APPROVAL]
    )
    def test_revert_rejects_other_statuses(self, reviewer, status):
        registration = TeacherRegistrationFactory(status=status)
        with pytest.raises(ValueError):
            registration.revert_to_under_review(reviewer)


# ---------------------------------------------------------------------------
# approve() for an initial registration
# ---------------------------------------------------------------------------


@pytest.fixture
def full_registration():
    """An under-review initial registration with every kind of child record."""
    registration = TeacherRegistrationFactory(under_review=True)
    EducationRecordFactory(registration=registration)
    EducationRecordFactory(registration=registration, completed=False, percentage_progress=60)
    TrainingRecordFactory(registration=registration)
    appointment = ClaimedSchoolAppointmentFactory(registration=registration)
    ClaimedDutyFactory(appointment=appointment)
    ClaimedDutyFactory(appointment=appointment, subject=None)
    RegistrationDocumentFactory(registration=registration)
    RegistrationDocumentFactory(registration=registration)
    RegistrationConditionFactory(registration=registration)
    return registration


@pytest.fixture
def full_status():
    return EmisTeacherRegistrationStatusFactory(
        code="FULL", label="Full Registration", validity_value=3, validity_unit="years"
    )


class TestApproveInitial:
    @pytest.mark.parametrize("status", REVIEWABLE)
    def test_allowed_from_reviewable_statuses(self, reviewer, status):
        registration = TeacherRegistrationFactory(status=status)
        staff = registration.approve(reviewer)
        assert isinstance(staff, SchoolStaff)
        assert registration.status == constants.APPROVED

    @pytest.mark.parametrize("status", [s for s in ALL_STATUSES if s not in REVIEWABLE])
    def test_rejects_other_statuses(self, reviewer, status):
        registration = TeacherRegistrationFactory(status=status)
        with pytest.raises(ValueError):
            registration.approve(reviewer)
        assert SchoolStaff.objects.count() == 0

    def test_creates_teaching_staff_with_profile_fields_copied(self, reviewer, full_registration):
        staff = full_registration.approve(reviewer)

        assert staff.user == full_registration.user
        assert staff.staff_type == SchoolStaff.TEACHING_STAFF
        for field in (
            "title", "date_of_birth", "gender", "marital_status", "nationality",
            "national_id_number", "home_island", "phone_number", "phone_home",
            "residential_address", "nearby_school", "business_address",
            "teacher_payroll_number", "highest_qualification", "years_of_experience",
        ):
            assert getattr(staff, field) == getattr(full_registration, field), field
        assert staff.created_by == reviewer
        assert staff.last_updated_by == reviewer
        assert staff.registration_application_status == constants.APPROVED

    def test_registration_number_is_generated_for_current_year(self, reviewer):
        registration = TeacherRegistrationFactory(under_review=True)
        with time_machine.travel(datetime(2027, 3, 1, tzinfo=dt_timezone.utc)):
            staff = registration.approve(reviewer)
        expected = generate_teacher_registration_number(
            registration.national_id_number, registration.date_of_birth, 2027
        )
        assert staff.teacher_registration_number == expected
        assert staff.teacher_registration_number.startswith("TR27-")

    def test_granted_at_defaults_to_now_and_drives_validity(self, reviewer, full_status):
        registration = TeacherRegistrationFactory(under_review=True)
        now = datetime(2026, 6, 1, 9, 0, tzinfo=dt_timezone.utc)
        with time_machine.travel(now, tick=False):
            staff = registration.approve(reviewer, registration_status=full_status)
        assert staff.registration_granted_at == now
        assert staff.registration_valid_until == now + timedelta(days=3 * 365)
        assert staff.teacher_registration_status == full_status

    def test_explicit_granted_at_is_used(self, reviewer, full_status):
        registration = TeacherRegistrationFactory(under_review=True)
        granted = datetime(2025, 1, 15, tzinfo=dt_timezone.utc)
        staff = registration.approve(reviewer, registration_status=full_status, granted_at=granted)
        assert staff.registration_granted_at == granted
        assert staff.registration_valid_until == granted + timedelta(days=3 * 365)

    def test_status_without_validity_never_expires(self, reviewer):
        status = EmisTeacherRegistrationStatusFactory(code="LIFE", label="Lifetime")
        staff = TeacherRegistrationFactory(under_review=True).approve(reviewer, registration_status=status)
        assert staff.registration_valid_until is None

    def test_education_records_are_copied_and_originals_kept(self, reviewer, full_registration):
        originals = list(full_registration.education_records.order_by("institution_name"))
        staff = full_registration.approve(reviewer)

        copies = list(staff.education_records.order_by("institution_name"))
        assert len(copies) == len(originals) == 2
        for original, copy in zip(originals, copies):
            for field in (
                "institution_name", "qualification", "program_name", "major", "major2",
                "minor", "minor2", "completion_year", "duration", "duration_unit",
                "completed", "percentage_progress", "comment",
            ):
                assert getattr(copy, field) == getattr(original, field), field
            assert copy.created_by == reviewer
        assert EducationRecord.objects.filter(registration=full_registration).count() == 2

    def test_training_records_are_copied_and_originals_kept(self, reviewer, full_registration):
        original = full_registration.training_records.get()
        staff = full_registration.approve(reviewer)

        copy = staff.training_records.get()
        for field in (
            "provider_institution", "title", "focus", "general_focus_area", "format",
            "completion_year", "duration", "duration_unit", "effective_date", "expiration_date",
        ):
            assert getattr(copy, field) == getattr(original, field), field
        assert TrainingRecord.objects.filter(registration=full_registration).count() == 1

    def test_appointments_become_open_assignments_with_duties(self, reviewer, full_registration):
        appointment = full_registration.claimed_appointments.get()
        staff = full_registration.approve(reviewer)

        assignment = staff.assignments.get()
        assert assignment.school == appointment.current_school
        assert assignment.job_title == appointment.employment_position
        assert assignment.teacher_level_type == appointment.teacher_level_type
        assert assignment.employment_status == appointment.employment_status
        assert assignment.start_date == appointment.start_date
        assert assignment.end_date is None

        duties = {(d.year_level_id, d.subject_id) for d in assignment.teaching_duties.all()}
        claimed = {(d.year_level_id, d.subject_id) for d in appointment.claimed_duties.all()}
        assert duties == claimed
        assert len(duties) == 2
        assert ClaimedSchoolAppointment.objects.filter(registration=full_registration).exists()

    def test_documents_and_conditions_move_to_staff(self, reviewer, full_registration):
        doc_ids = set(full_registration.documents.values_list("pk", flat=True))
        condition_id = full_registration.conditions.get().pk
        staff = full_registration.approve(reviewer)

        assert set(staff.documents.values_list("pk", flat=True)) == doc_ids
        assert not RegistrationDocument.objects.filter(registration=full_registration).exists()
        moved = RegistrationCondition.objects.get(pk=condition_id)
        assert moved.school_staff == staff
        assert moved.registration is None

    def test_registration_record_is_closed(self, reviewer, full_registration):
        signatory = UserFactory(username="signer@example.org")
        before = datetime(2026, 6, 1, tzinfo=dt_timezone.utc)
        with time_machine.travel(before, tick=False):
            staff = full_registration.approve(
                reviewer, comments="All good", signatory=signatory
            )
        full_registration.refresh_from_db()

        assert full_registration.status == constants.APPROVED
        assert full_registration.reviewed_by == reviewer
        assert full_registration.reviewed_at == before
        assert full_registration.reviewer_comments == "All good"
        assert full_registration.approved_staff_profile == staff
        assert full_registration.signatory == signatory

        log = latest_log(full_registration)
        assert (log.old_value, log.new_value) == (constants.UNDER_REVIEW, constants.APPROVED)
        assert staff.teacher_registration_number in log.notes
        assert str(staff.pk) in log.notes

    @pytest.mark.parametrize("national_id", ["", "   "])
    def test_requires_national_id(self, reviewer, national_id):
        registration = TeacherRegistrationFactory(under_review=True, national_id_number=national_id)
        with pytest.raises(ValidationError, match="National ID"):
            registration.approve(reviewer)
        registration.refresh_from_db()
        assert registration.status == constants.UNDER_REVIEW
        assert SchoolStaff.objects.count() == 0

    def test_rejects_duplicate_national_id(self, reviewer):
        SchoolStaffFactory(national_id_number="DUP-1")
        registration = TeacherRegistrationFactory(under_review=True, national_id_number="DUP-1")
        with pytest.raises(ValidationError, match="already exists"):
            registration.approve(reviewer)
        assert SchoolStaff.objects.count() == 1

    def test_duplicate_national_id_check_is_exact_match(self, reviewer):
        """Characterises current behaviour: the duplicate check is case- and
        whitespace-sensitive even though the registration number normalises both."""
        SchoolStaffFactory(national_id_number="dup-2")
        registration = TeacherRegistrationFactory(under_review=True, national_id_number="DUP-2")
        registration.approve(reviewer)
        assert SchoolStaff.objects.count() == 2


# ---------------------------------------------------------------------------
# approve() for a renewal registration
# ---------------------------------------------------------------------------


@pytest.fixture
def existing_staff(full_status):
    """An approved teacher with a prior registration number, records, and documents."""
    staff = SchoolStaffFactory(
        national_id_number="RENEW-1",
        teacher_registration_number="TR20-OLDNUM-A",
        teacher_registration_status=full_status,
        registration_application_status=constants.APPROVED,
        registration_granted_at=datetime(2020, 1, 1, tzinfo=dt_timezone.utc),
    )
    StaffEducationRecord.objects.create(
        school_staff=staff,
        institution_name="Old University",
        qualification=EducationRecordFactory.qualification.get_factory()(),
        major=EducationRecordFactory.major.get_factory()(),
    )
    StaffTrainingRecord.objects.create(
        school_staff=staff, provider_institution="Old Provider", title="Old Workshop"
    )
    old_assignment = SchoolStaffAssignment.objects.create(
        school_staff=staff,
        school=ClaimedSchoolAppointmentFactory.current_school.get_factory()(),
        job_title=ClaimedSchoolAppointmentFactory.employment_position.get_factory()(),
    )
    StaffTeachingDuty.objects.create(
        assignment=old_assignment, year_level=ClaimedDutyFactory.year_level.get_factory()()
    )
    RegistrationDocumentFactory(registration=None, school_staff=staff, original_filename="old.pdf")
    RegistrationConditionFactory(registration=None, school_staff=staff)
    return staff


@pytest.fixture
def renewal(existing_staff):
    registration = TeacherRegistrationFactory(
        renewal=True,
        under_review=True,
        user=existing_staff.user,
        national_id_number="RENEW-1",
        phone_number="+686 99999",
    )
    EducationRecordFactory(registration=registration, institution_name="New University")
    TrainingRecordFactory(registration=registration, title="New Workshop")
    appointment = ClaimedSchoolAppointmentFactory(registration=registration)
    ClaimedDutyFactory(appointment=appointment)
    RegistrationDocumentFactory(registration=registration, original_filename="new.pdf")
    RegistrationConditionFactory(registration=registration)
    return registration


class TestApproveRenewal:
    def test_updates_existing_staff_and_keeps_registration_number(
        self, reviewer, existing_staff, renewal
    ):
        staff = renewal.approve(reviewer)

        assert staff.pk == existing_staff.pk
        assert SchoolStaff.objects.count() == 1
        assert staff.teacher_registration_number == "TR20-OLDNUM-A"
        assert staff.phone_number == "+686 99999"
        assert staff.last_updated_by == reviewer
        assert staff.registration_application_status == constants.APPROVED

    def test_new_grant_recomputes_validity(self, reviewer, renewal, full_status):
        granted = datetime(2026, 2, 1, tzinfo=dt_timezone.utc)
        staff = renewal.approve(reviewer, registration_status=full_status, granted_at=granted)
        assert staff.registration_granted_at == granted
        assert staff.registration_valid_until == granted + timedelta(days=3 * 365)

    def test_replaces_education_training_and_assignments(self, reviewer, existing_staff, renewal):
        staff = renewal.approve(reviewer)

        assert [r.institution_name for r in staff.education_records.all()] == ["New University"]
        assert [r.title for r in staff.training_records.all()] == ["New Workshop"]
        assignment = staff.assignments.get()
        assert assignment.school == renewal.claimed_appointments.get().current_school
        assert assignment.teaching_duties.count() == 1
        assert StaffTeachingDuty.objects.count() == 1

    def test_keeps_old_documents_and_adds_new_ones(self, reviewer, existing_staff, renewal):
        staff = renewal.approve(reviewer)
        names = sorted(staff.documents.values_list("original_filename", flat=True))
        assert names == ["new.pdf", "old.pdf"]
        assert not renewal.documents.exists()

    def test_replaces_conditions(self, reviewer, existing_staff, renewal):
        new_condition = renewal.conditions.get()
        staff = renewal.approve(reviewer)
        assert list(staff.conditions.values_list("pk", flat=True)) == [new_condition.pk]
        assert RegistrationCondition.objects.count() == 1

    def test_closes_registration_and_logs(self, reviewer, renewal):
        signatory = UserFactory(username="signer2@example.org")
        staff = renewal.approve(reviewer, comments="Renewed", signatory=signatory)
        renewal.refresh_from_db()
        assert renewal.status == constants.APPROVED
        assert renewal.approved_staff_profile == staff
        assert renewal.signatory == signatory
        assert renewal.reviewer_comments == "Renewed"
        log = latest_log(renewal)
        assert "Renewal approved" in log.notes
        assert "TR20-OLDNUM-A" in log.notes

    def test_duplicate_check_ignores_own_profile(self, reviewer, existing_staff, renewal):
        """Same national ID as the teacher's own SchoolStaff is not a duplicate."""
        renewal.approve(reviewer)

    def test_rejects_national_id_belonging_to_someone_else(self, reviewer, existing_staff, renewal):
        SchoolStaffFactory(national_id_number="OTHER-9")
        renewal.national_id_number = "OTHER-9"
        renewal.save()
        with pytest.raises(ValidationError, match="already exists"):
            renewal.approve(reviewer)

    def test_requires_existing_staff_profile(self, reviewer):
        registration = TeacherRegistrationFactory(renewal=True, under_review=True)
        with pytest.raises(ValidationError, match="no existing SchoolStaff"):
            registration.approve(reviewer)

    def test_requires_national_id(self, reviewer, existing_staff, renewal):
        renewal.national_id_number = ""
        renewal.save()
        with pytest.raises(ValidationError, match="National ID"):
            renewal.approve(reviewer)

    def test_renewal_failure_rolls_back_staff_changes(self, reviewer, existing_staff, renewal):
        """The renewal update is atomic: a failure mid-way leaves the staff untouched."""
        renewal.claimed_appointments.get().claimed_duties.create(
            year_level=ClaimedDutyFactory.year_level.get_factory()(), subject=None
        )
        # Two duties with the same year level and no subject violate the
        # StaffTeachingDuty unique constraint when copied.
        duty = renewal.claimed_appointments.get().claimed_duties.filter(subject__isnull=True).get()
        renewal.claimed_appointments.get().claimed_duties.create(
            year_level=duty.year_level, subject=None
        )
        with pytest.raises(IntegrityError):
            renewal.approve(reviewer)
        existing_staff.refresh_from_db()
        assert existing_staff.phone_number != "+686 99999"
        assert existing_staff.education_records.get().institution_name == "Old University"


# ---------------------------------------------------------------------------
# reject()
# ---------------------------------------------------------------------------


class TestReject:
    @pytest.mark.parametrize("status", REVIEWABLE)
    def test_returns_to_draft_with_comments_and_two_log_entries(self, reviewer, status):
        registration = TeacherRegistrationFactory(status=status)
        registration.reject(reviewer, "Missing police clearance")
        registration.refresh_from_db()

        assert registration.status == constants.DRAFT
        assert registration.reviewed_by == reviewer
        assert registration.reviewed_at is not None
        assert registration.reviewer_comments == "Missing police clearance"

        logs = list(registration.change_logs.order_by("pk"))
        assert [(l.old_value, l.new_value) for l in logs] == [
            (status, constants.REJECTED),
            (constants.REJECTED, constants.DRAFT),
        ]
        assert "Missing police clearance" in logs[0].notes
        assert logs[1].notes == "Returned to draft for corrections"

    def test_log_truncates_long_reason(self, reviewer):
        registration = TeacherRegistrationFactory(submitted=True)
        registration.reject(reviewer, "x" * 300)
        first = registration.change_logs.order_by("pk").first()
        assert first.notes == "Registration rejected. Reason: " + "x" * 100

    def test_empty_reason(self, reviewer):
        registration = TeacherRegistrationFactory(submitted=True)
        registration.reject(reviewer, "")
        assert registration.change_logs.order_by("pk").first().notes == "Registration rejected"

    @pytest.mark.parametrize("status", [s for s in ALL_STATUSES if s not in REVIEWABLE])
    def test_rejects_other_statuses(self, reviewer, status):
        registration = TeacherRegistrationFactory(status=status)
        with pytest.raises(ValueError):
            registration.reject(reviewer, "no")
        registration.refresh_from_db()
        assert registration.status == status

    def test_rejected_registration_can_be_resubmitted_and_re_reviewed(self, reviewer):
        registration = TeacherRegistrationFactory(submitted=True)
        registration.reject(reviewer, "Fix it")
        assert registration.is_editable
        registration.submit()
        assert registration.reviewer_comments == ""
        registration.start_review(reviewer)
        assert registration.status == constants.UNDER_REVIEW


# ---------------------------------------------------------------------------
# RegistrationChangeLog, documents, conditions
# ---------------------------------------------------------------------------


class TestChangeLog:
    def test_log_change_stringifies_values(self):
        registration = TeacherRegistrationFactory()
        entry = RegistrationChangeLog.log_change(
            registration=registration, field_name="years_of_experience", old_value=3, new_value=4
        )
        assert (entry.old_value, entry.new_value) == ("3", "4")

    def test_log_change_blanks_falsy_values(self):
        registration = TeacherRegistrationFactory()
        entry = RegistrationChangeLog.log_change(
            registration=registration, field_name="x", old_value=None, new_value=0
        )
        assert (entry.old_value, entry.new_value) == ("", "")

    def test_str(self):
        registration = TeacherRegistrationFactory()
        entry = RegistrationChangeLog.log_change(
            registration=registration, field_name="status", new_value="submitted"
        )
        assert str(entry) == f"{registration.pk}: status -> submitted"


class TestRegistrationDocument:
    def test_owner_is_registration_while_pending(self):
        doc = RegistrationDocumentFactory()
        assert doc.owner == doc.registration

    def test_owner_is_staff_after_move(self):
        staff = SchoolStaffFactory()
        doc = RegistrationDocumentFactory(registration=None, school_staff=staff)
        assert doc.owner == staff

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [("photo.JPG", True), ("photo.png", True), ("scan.pdf", False), ("noext", False)],
    )
    def test_original_is_image(self, filename, expected):
        doc = RegistrationDocumentFactory(original_filename=filename)
        assert doc.original_is_image is expected

    def test_display_image_prefers_crop_then_image_original(self):
        pdf = RegistrationDocumentFactory(original_filename="scan.pdf")
        assert pdf.display_image is None
        image = RegistrationDocumentFactory(original_filename="photo.jpg")
        assert image.display_image == image.file

    def test_must_have_exactly_one_owner(self):
        staff = SchoolStaffFactory()
        with pytest.raises(IntegrityError):
            RegistrationDocumentFactory(school_staff=staff)

    def test_must_have_an_owner(self):
        with pytest.raises(IntegrityError):
            RegistrationDocumentFactory(registration=None, school_staff=None)

    def test_str_uses_link_type_label(self):
        doc = RegistrationDocumentFactory(original_filename="cert.pdf")
        assert str(doc) == f"{doc.doc_link_type.label} - cert.pdf"


class TestRegistrationCondition:
    def test_owner(self):
        condition = RegistrationConditionFactory()
        assert condition.owner == condition.registration
        assert str(condition) == condition.condition.label

    def test_must_have_exactly_one_owner(self):
        with pytest.raises(IntegrityError):
            RegistrationConditionFactory(school_staff=SchoolStaffFactory())

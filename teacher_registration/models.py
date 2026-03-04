"""
Models for the teacher_registration app.

This module contains models for the teacher self-registration workflow:
- TeacherRegistration: Holds registration data while pending approval
- RegistrationDocument: Documents attached to registrations (moved to SchoolStaff on approval)
- RegistrationCondition: Conditions attached to conditional registrations (moved to SchoolStaff on approval)
- LookupCondition: Local lookup table for condition types
- RegistrationChangeLog: Audit trail for registration workflow changes
"""

from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from . import constants
from .utils import generate_teacher_registration_number

from core.models import (
    AuditModel,
    SchoolStaff,
    SchoolStaffAssignment,
    StaffEducationRecord,
    StaffTrainingRecord,
    StaffTeachingDuty,
)
from integrations.models import (
    EmisSchool,
    EmisJobTitle,
    EmisGender,
    EmisMaritalStatus,
    EmisIsland,
    EmisTeacherQual,
    EmisSubject,
    EmisEducationLevel,
    EmisTeacherStatus,
    EmisClassLevel,
    EmisTeacherLinkType,
    EmisTeacherPdType,
    EmisTeacherPdFocus,
    EmisTeacherPdFormat,
    EmisNationality,
)

if TYPE_CHECKING:
    from django.db.models.manager import RelatedManager


def registration_upload_path(instance, filename):
    """
    Generate upload path for registration documents.

    Files are stored under:
    - registrations/{registration_id}/ while pending
    - staff/{school_staff_id}/ after approval (when moved)
    """
    if instance.registration:
        return f"registrations/{instance.registration.id}/{filename}"
    elif instance.school_staff:
        return f"staff/{instance.school_staff.id}/{filename}"
    return f"documents/{filename}"


class TeacherRegistration(AuditModel):
    """
    Teacher registration application.

    Holds all submitted data while pending approval. On approval:
    1. SchoolStaff profile is created with profile data
    2. Documents are moved to SchoolStaff
    3. This record becomes a closed historical record

    Workflow:
        DRAFT -> SUBMITTED -> UNDER_REVIEW -> APPROVED/REJECTED
    """

    # Registration type
    INITIAL = "initial"
    RENEWAL = "renewal"

    TYPE_CHOICES = [
        (INITIAL, "Initial Registration"),
        (RENEWAL, "Renewed Registration"),
    ]

    # Teacher category (determines form sections displayed)
    NEW_TEACHER = "new"
    CURRENT_TEACHER = "current"

    TEACHER_CATEGORY_CHOICES = [
        (NEW_TEACHER, "New Teacher"),
        (CURRENT_TEACHER, "Current Teacher"),
    ]

    # Title choices
    TITLE_MR = "Mr"
    TITLE_MRS = "Mrs"
    TITLE_MISS = "Miss"
    TITLE_MS = "Ms"
    TITLE_DR = "Dr"

    TITLE_CHOICES = [
        (TITLE_MR, "Mr"),
        (TITLE_MRS, "Mrs"),
        (TITLE_MISS, "Miss"),
        (TITLE_MS, "Ms"),
        (TITLE_DR, "Dr"),
    ]

    # -------------------------------------------------------------------------
    # Core fields
    # -------------------------------------------------------------------------

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="teacher_registrations",
        help_text="User submitting this registration",
    )

    registration_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=INITIAL,
    )

    teacher_category = models.CharField(
        max_length=20,
        choices=TEACHER_CATEGORY_CHOICES,
        default=NEW_TEACHER,
        help_text="Determines which form sections are displayed",
    )

    status = models.CharField(
        max_length=20,
        choices=constants.REGISTRATION_APPLICATION_STATUS_CHOICES,
        default=constants.DRAFT,
    )

    # -------------------------------------------------------------------------
    # Profile data (copied to SchoolStaff on approval)
    # -------------------------------------------------------------------------

    # Personal information
    title = models.CharField(
        max_length=10,
        choices=TITLE_CHOICES,
        blank=True,
        verbose_name="Title",
    )
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        verbose_name="Date of birth",
    )
    gender = models.ForeignKey(
        EmisGender,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="registrations",
        verbose_name="Gender",
    )
    marital_status = models.ForeignKey(
        EmisMaritalStatus,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="registrations",
        verbose_name="Marital status",
    )
    nationality = models.ForeignKey(
        EmisNationality,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="registrations",
        verbose_name="Nationality",
    )
    national_id_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="National ID number",
    )
    home_island = models.ForeignKey(
        EmisIsland,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="registrations",
        verbose_name="Home island",
    )

    # Contact information
    phone_number = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Mobile phone",
    )
    phone_home = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Home phone",
    )

    # Residential Address (required)
    residential_address = models.TextField(
        blank=True,
        verbose_name="Residential address",
        help_text="Full residential/home address",
    )
    nearby_school = models.ForeignKey(
        EmisSchool,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="nearby_registrations",
        verbose_name="Nearest school",
        help_text="Nearest school to residential address",
    )

    # Business Address (optional)
    business_address = models.TextField(
        blank=True,
        verbose_name="Business address",
        help_text="Full business/work address (optional)",
    )

    # Professional information
    teacher_payroll_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Teacher Payroll Number (PF Number)",
    )
    highest_qualification = models.CharField(
        max_length=100,
        blank=True,
        choices=[
            ("high_school", "High School"),
            ("certificate", "Certificate"),
            ("diploma", "Diploma"),
            ("bachelors", "Bachelor's Degree"),
            ("masters", "Master's Degree"),
            ("doctorate", "Doctorate"),
        ],
    )
    years_of_experience = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Years of teaching experience",
    )

    # School preference (for initial registration)
    preferred_school = models.ForeignKey(
        EmisSchool,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="registration_preferences",
        verbose_name="Preferred school",
    )
    preferred_job_title = models.ForeignKey(
        EmisJobTitle,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Preferred position",
    )

    # -------------------------------------------------------------------------
    # Workflow timestamps
    # -------------------------------------------------------------------------

    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the registration was submitted for review",
    )

    # -------------------------------------------------------------------------
    # Review fields
    # -------------------------------------------------------------------------

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_registrations",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_comments = models.TextField(
        blank=True,
        help_text="Comments from the reviewer (visible to applicant)",
    )

    # -------------------------------------------------------------------------
    # Checklist fields (Section 7 of official Teacher Application Form)
    # Applicant: self-declaration by the teacher
    # Official: verification by the reviewing officer
    # -------------------------------------------------------------------------

    # Standalone item
    checklist_applicant_form_completed = models.BooleanField(default=False)
    checklist_official_form_completed = models.BooleanField(default=False)

    # Certified copies
    checklist_applicant_birth_cert = models.BooleanField(default=False)
    checklist_official_birth_cert = models.BooleanField(default=False)

    checklist_applicant_national_id = models.BooleanField(default=False)
    checklist_official_national_id = models.BooleanField(default=False)

    checklist_applicant_qualifications = models.BooleanField(default=False)
    checklist_official_qualifications = models.BooleanField(default=False)

    checklist_applicant_english_proficiency = models.BooleanField(default=False)
    checklist_official_english_proficiency = models.BooleanField(default=False)

    checklist_applicant_training_certs = models.BooleanField(default=False)
    checklist_official_training_certs = models.BooleanField(default=False)

    checklist_applicant_statutory_declaration = models.BooleanField(default=False)
    checklist_official_statutory_declaration = models.BooleanField(default=False)

    # Original documents
    checklist_applicant_police_clearance = models.BooleanField(default=False)
    checklist_official_police_clearance = models.BooleanField(default=False)

    checklist_applicant_medical_clearance = models.BooleanField(default=False)
    checklist_official_medical_clearance = models.BooleanField(default=False)

    checklist_applicant_photo = models.BooleanField(default=False)
    checklist_official_photo = models.BooleanField(default=False)

    checklist_applicant_church_reference = models.BooleanField(default=False)
    checklist_official_church_reference = models.BooleanField(default=False)

    checklist_applicant_school_reference = models.BooleanField(default=False)
    checklist_official_school_reference = models.BooleanField(default=False)

    checklist_applicant_fee_receipt = models.BooleanField(default=False)
    checklist_official_fee_receipt = models.BooleanField(default=False)

    # Staff reviewer marks this when all verification is complete
    # and the registration is ready for TRC (committee) approval.
    checklist_ready_for_approval = models.BooleanField(default=False)

    # -------------------------------------------------------------------------
    # Link to approved profile (set on approval)
    # -------------------------------------------------------------------------

    approved_staff_profile = models.ForeignKey(
        SchoolStaff,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="registration_history",
        help_text="Link to SchoolStaff created on approval (audit trail)",
    )

    if TYPE_CHECKING:
        # Type hints for reverse relations
        documents: "RelatedManager[RegistrationDocument]"
        change_logs: "RelatedManager[RegistrationChangeLog]"
        education_records: "RelatedManager[EducationRecord]"
        training_records: "RelatedManager[TrainingRecord]"
        claimed_appointments: "RelatedManager[ClaimedSchoolAppointment]"

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Teacher Registration"
        verbose_name_plural = "Teacher Registrations"

    if TYPE_CHECKING:
        # Type stubs for Django-generated methods (satisfy type checkers)
        def get_status_display(self) -> str: ...
        def get_registration_type_display(self) -> str: ...
        def get_teacher_category_display(self) -> str: ...
        def get_title_display(self) -> str: ...
        def get_gender_display(self) -> str: ...
        def get_highest_qualification_display(self) -> str: ...

    def __str__(self):
        return f"Registration<{self.user}, {self.get_status_display()}>"

    @property
    def is_editable(self):
        """Check if the registration can still be edited."""
        return self.status == constants.DRAFT

    @property
    def can_submit(self):
        """Check if the registration is ready to submit."""
        # Add validation logic here as needed
        return self.status == constants.DRAFT

    # -------------------------------------------------------------------------
    # Workflow methods
    # -------------------------------------------------------------------------

    def submit(self, user=None):
        """Submit the registration for review."""
        if self.status != constants.DRAFT:
            raise ValueError("Only draft registrations can be submitted")

        old_status = self.status
        self.status = constants.SUBMITTED
        self.submitted_at = timezone.now()
        # Clear previous reviewer comments so the rejection banner doesn't persist
        self.reviewer_comments = ""
        # Reset ready-for-approval flag so re-submissions start fresh
        self.checklist_ready_for_approval = False
        self.save(update_fields=["status", "submitted_at", "reviewer_comments", "checklist_ready_for_approval", "last_updated_at"])

        # Log the status change
        RegistrationChangeLog.log_change(
            registration=self,
            field_name="status",
            old_value=old_status,
            new_value=self.status,
            changed_by=user or self.user,
            notes="Registration submitted for review",
        )

    def start_review(self, reviewer):
        """Mark registration as under review."""
        if self.status not in [constants.SUBMITTED, constants.REJECTED]:
            raise ValueError("Only submitted or rejected registrations can be reviewed")

        old_status = self.status
        self.status = constants.UNDER_REVIEW
        self.reviewed_by = reviewer
        self.save(update_fields=["status", "reviewed_by", "last_updated_at"])

        # Log the status change
        notes = (
            "Review started" if old_status == constants.SUBMITTED else "Re-review started"
        )
        RegistrationChangeLog.log_change(
            registration=self,
            field_name="status",
            old_value=old_status,
            new_value=self.status,
            changed_by=reviewer,
            notes=notes,
        )

    def mark_ready_for_approval(self, reviewer):
        """Mark registration as ready for TRC approval."""
        if self.status != constants.UNDER_REVIEW:
            raise ValueError("Only under-review registrations can be marked ready for approval")

        old_status = self.status
        self.status = constants.READY_FOR_APPROVAL
        self.save(update_fields=["status", "last_updated_at"])

        RegistrationChangeLog.log_change(
            registration=self,
            field_name="status",
            old_value=old_status,
            new_value=self.status,
            changed_by=reviewer,
            notes="Marked ready for TRC approval",
        )

    def revert_to_under_review(self, reviewer):
        """Revert a ready-for-approval registration back to under review."""
        if self.status != constants.READY_FOR_APPROVAL:
            raise ValueError("Only ready-for-approval registrations can be reverted to under review")

        old_status = self.status
        self.status = constants.UNDER_REVIEW
        self.save(update_fields=["status", "last_updated_at"])

        RegistrationChangeLog.log_change(
            registration=self,
            field_name="status",
            old_value=old_status,
            new_value=self.status,
            changed_by=reviewer,
            notes="Reverted to under review",
        )

    def approve(self, reviewer, comments="", registration_status=None):
        """
        Approve the registration and create SchoolStaff profile.

        This method:
        1. Validates National ID is present (required for registration number)
        2. Checks for duplicate National ID (prevents collisions)
        3. Generates unique teacher registration number
        4. Creates SchoolStaff with data from this registration (including new fields)
        5. Copies EducationRecords to StaffEducationRecords (preserves originals as audit trail)
        6. Copies TrainingRecords to StaffTrainingRecords (preserves originals as audit trail)
        7. Converts ClaimedSchoolAppointments to SchoolStaffAssignments
        8. Copies ClaimedDuties to StaffTeachingDuties (preserves originals as audit trail)
        9. Moves documents to SchoolStaff (FK swap)
        10. Marks this registration as approved

        Returns:
            SchoolStaff: The created staff profile

        Raises:
            ValueError: If registration status is invalid
            ValidationError: If National ID missing or duplicate National ID exists
        """
        if self.status not in [constants.SUBMITTED, constants.UNDER_REVIEW, constants.READY_FOR_APPROVAL]:
            raise ValueError(
                "Only submitted, under-review, or ready-for-approval registrations can be approved"
            )

        # Dispatch to renewal-specific approval if this is a renewal
        if self.registration_type == self.RENEWAL:
            return self._approve_renewal(reviewer, comments, registration_status)

        # Validate National ID is present (required for registration number generation)
        if not self.national_id_number or not self.national_id_number.strip():
            raise ValidationError(
                "National ID is required for approval. "
                "Please ensure the applicant has provided their National ID/Passport number."
            )

        # Check for duplicate National ID (prevent registration number collisions)
        existing_staff = SchoolStaff.objects.filter(
            national_id_number=self.national_id_number
        ).first()

        if existing_staff:
            raise ValidationError(
                f"A teacher with National ID '{self.national_id_number}' already exists. "
                f"Name: {existing_staff.user.get_full_name() or existing_staff.user.username}. "
                f"Two teachers cannot have the same National ID. This needs to be corrected."
            )

        # Generate teacher registration number
        registration_number = generate_teacher_registration_number(
            national_id=self.national_id_number,
            date_of_birth=self.date_of_birth,
            approval_year=timezone.now().year,
        )

        # Create SchoolStaff profile with all fields
        staff = SchoolStaff.objects.create(
            user=self.user,
            staff_type=SchoolStaff.TEACHING_STAFF,
            # Personal information
            title=self.title,
            date_of_birth=self.date_of_birth,
            gender=self.gender,
            marital_status=self.marital_status,
            nationality=self.nationality,
            national_id_number=self.national_id_number,
            home_island=self.home_island,
            # Contact information
            phone_number=self.phone_number,
            phone_home=self.phone_home,
            # Residential address
            residential_address=self.residential_address,
            nearby_school=self.nearby_school,
            # Business address
            business_address=self.business_address,
            # Professional information
            teacher_payroll_number=self.teacher_payroll_number,
            highest_qualification=self.highest_qualification,
            years_of_experience=self.years_of_experience,
            # Teacher registration number (auto-generated)
            teacher_registration_number=registration_number,
            # Registration status (from EMIS lookup, selected at approval)
            teacher_registration_status=registration_status,
            # Registration application status
            registration_application_status=constants.APPROVED,
            # Audit
            created_by=reviewer,
            last_updated_by=reviewer,
        )

        # Compute registration_valid_until from the selected registration status
        if registration_status and registration_status.validity_value and registration_status.validity_unit:
            unit = registration_status.validity_unit
            value = registration_status.validity_value
            now = timezone.now()
            if unit == "minutes":
                staff.registration_valid_until = now + timedelta(minutes=value)
            elif unit == "hours":
                staff.registration_valid_until = now + timedelta(hours=value)
            elif unit == "days":
                staff.registration_valid_until = now + timedelta(days=value)
            elif unit == "years":
                staff.registration_valid_until = now + timedelta(days=value * 365)
            staff.save(update_fields=["registration_valid_until"])

        # Copy EducationRecords to StaffEducationRecords (preserves originals)
        for edu_record in self.education_records.all():
            StaffEducationRecord.objects.create(
                school_staff=staff,
                institution_name=edu_record.institution_name,
                qualification=edu_record.qualification,
                program_name=edu_record.program_name,
                major=edu_record.major,
                minor=edu_record.minor,
                completion_year=edu_record.completion_year,
                duration=edu_record.duration,
                duration_unit=edu_record.duration_unit,
                completed=edu_record.completed,
                percentage_progress=edu_record.percentage_progress,
                comment=edu_record.comment,
                created_by=reviewer,
                last_updated_by=reviewer,
            )

        # Copy TrainingRecords to StaffTrainingRecords (preserves originals)
        for training_record in self.training_records.all():
            StaffTrainingRecord.objects.create(
                school_staff=staff,
                provider_institution=training_record.provider_institution,
                title=training_record.title,
                focus=training_record.focus,
                format=training_record.format,
                completion_year=training_record.completion_year,
                duration=training_record.duration,
                duration_unit=training_record.duration_unit,
                effective_date=training_record.effective_date,
                expiration_date=training_record.expiration_date,
                created_by=reviewer,
                last_updated_by=reviewer,
            )

        # Convert ClaimedSchoolAppointments to SchoolStaffAssignments
        # Also copy ClaimedDuties to StaffTeachingDuties
        for appointment in self.claimed_appointments.all():
            assignment = SchoolStaffAssignment.objects.create(
                school_staff=staff,
                school=appointment.current_school,
                job_title=appointment.employment_position,
                teacher_level_type=appointment.teacher_level_type,
                start_date=appointment.start_date,
                # end_date is left null (currently active)
                created_by=reviewer,
                last_updated_by=reviewer,
            )

            # Copy ClaimedDuties to StaffTeachingDuties (preserves originals)
            for duty in appointment.claimed_duties.all():
                StaffTeachingDuty.objects.create(
                    assignment=assignment,
                    year_level=duty.year_level,
                    subject=duty.subject,
                    created_by=reviewer,
                    last_updated_by=reviewer,
                )

        # Move documents to SchoolStaff (FK swap)
        self.documents.update(
            school_staff=staff,
            registration=None,
        )

        # Move conditions to SchoolStaff (FK swap)
        self.conditions.update(
            school_staff=staff,
            registration=None,
        )

        # Update registration status
        old_status = self.status
        self.status = constants.APPROVED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.reviewer_comments = comments
        self.approved_staff_profile = staff
        self.save()

        # Log the status change
        RegistrationChangeLog.log_change(
            registration=self,
            field_name="status",
            old_value=old_status,
            new_value=self.status,
            changed_by=reviewer,
            notes=f"Registration approved. SchoolStaff profile created (ID: {staff.pk}). "
                  f"Teacher Registration Number: {registration_number}",
        )

        return staff

    def _approve_renewal(self, reviewer, comments, registration_status):
        """
        Approve a renewal registration and update the existing SchoolStaff profile.

        Unlike initial approval, this method:
        - Updates the existing SchoolStaff instead of creating a new one
        - Keeps the existing teacher registration number
        - Replaces education, training, and assignment records
        - Moves only NEW renewal documents to SchoolStaff (existing docs stay)

        The entire operation is wrapped in a transaction for atomicity.

        Returns:
            SchoolStaff: The updated staff profile

        Raises:
            ValidationError: If National ID missing, duplicate, or no SchoolStaff found
        """
        # Validate National ID is present
        if not self.national_id_number or not self.national_id_number.strip():
            raise ValidationError(
                "National ID is required for approval. "
                "Please ensure the applicant has provided their National ID/Passport number."
            )

        # Check for duplicate National ID (exclude the teacher's own SchoolStaff)
        existing_staff = SchoolStaff.objects.filter(
            national_id_number=self.national_id_number
        ).exclude(user=self.user).first()

        if existing_staff:
            raise ValidationError(
                f"A teacher with National ID '{self.national_id_number}' already exists. "
                f"Name: {existing_staff.user.get_full_name() or existing_staff.user.username}. "
                f"Two teachers cannot have the same National ID. This needs to be corrected."
            )

        # Get the existing SchoolStaff profile
        try:
            staff = self.user.school_staff
        except SchoolStaff.DoesNotExist:
            raise ValidationError(
                "Cannot approve renewal: no existing SchoolStaff profile found for this user."
            )

        with transaction.atomic():
            # Update all personal/professional fields on existing SchoolStaff
            staff.title = self.title
            staff.date_of_birth = self.date_of_birth
            staff.gender = self.gender
            staff.marital_status = self.marital_status
            staff.nationality = self.nationality
            staff.national_id_number = self.national_id_number
            staff.home_island = self.home_island
            staff.phone_number = self.phone_number
            staff.phone_home = self.phone_home
            staff.residential_address = self.residential_address
            staff.nearby_school = self.nearby_school
            staff.business_address = self.business_address
            staff.teacher_payroll_number = self.teacher_payroll_number
            staff.highest_qualification = self.highest_qualification
            staff.years_of_experience = self.years_of_experience
            staff.teacher_registration_status = registration_status
            staff.registration_application_status = constants.APPROVED
            staff.last_updated_by = reviewer
            staff.save()

            # Recalculate registration_valid_until from the selected registration status
            if registration_status and registration_status.validity_value and registration_status.validity_unit:
                unit = registration_status.validity_unit
                value = registration_status.validity_value
                now = timezone.now()
                if unit == "minutes":
                    staff.registration_valid_until = now + timedelta(minutes=value)
                elif unit == "hours":
                    staff.registration_valid_until = now + timedelta(hours=value)
                elif unit == "days":
                    staff.registration_valid_until = now + timedelta(days=value)
                elif unit == "years":
                    staff.registration_valid_until = now + timedelta(days=value * 365)
                staff.save(update_fields=["registration_valid_until"])

            # Replace education records
            staff.education_records.all().delete()
            for edu_record in self.education_records.all():
                StaffEducationRecord.objects.create(
                    school_staff=staff,
                    institution_name=edu_record.institution_name,
                    qualification=edu_record.qualification,
                    program_name=edu_record.program_name,
                    major=edu_record.major,
                    minor=edu_record.minor,
                    completion_year=edu_record.completion_year,
                    duration=edu_record.duration,
                    duration_unit=edu_record.duration_unit,
                    completed=edu_record.completed,
                    percentage_progress=edu_record.percentage_progress,
                    comment=edu_record.comment,
                    created_by=reviewer,
                    last_updated_by=reviewer,
                )

            # Replace training records
            staff.training_records.all().delete()
            for training_record in self.training_records.all():
                StaffTrainingRecord.objects.create(
                    school_staff=staff,
                    provider_institution=training_record.provider_institution,
                    title=training_record.title,
                    focus=training_record.focus,
                    format=training_record.format,
                    completion_year=training_record.completion_year,
                    duration=training_record.duration,
                    duration_unit=training_record.duration_unit,
                    effective_date=training_record.effective_date,
                    expiration_date=training_record.expiration_date,
                    created_by=reviewer,
                    last_updated_by=reviewer,
                )

            # Replace assignments and duties (cascade deletes duties)
            staff.assignments.all().delete()
            for appointment in self.claimed_appointments.all():
                assignment = SchoolStaffAssignment.objects.create(
                    school_staff=staff,
                    school=appointment.current_school,
                    job_title=appointment.employment_position,
                    teacher_level_type=appointment.teacher_level_type,
                    start_date=appointment.start_date,
                    created_by=reviewer,
                    last_updated_by=reviewer,
                )

                for duty in appointment.claimed_duties.all():
                    StaffTeachingDuty.objects.create(
                        assignment=assignment,
                        year_level=duty.year_level,
                        subject=duty.subject,
                        created_by=reviewer,
                        last_updated_by=reviewer,
                    )

            # Move NEW renewal documents to SchoolStaff (existing staff docs stay)
            self.documents.update(
                school_staff=staff,
                registration=None,
            )

            # Replace conditions: delete old from staff, FK-swap new from registration
            staff.conditions.all().delete()
            self.conditions.update(
                school_staff=staff,
                registration=None,
            )

            # Update registration status
            old_status = self.status
            self.status = constants.APPROVED
            self.reviewed_by = reviewer
            self.reviewed_at = timezone.now()
            self.reviewer_comments = comments
            self.approved_staff_profile = staff
            self.save()

            # Log the status change
            RegistrationChangeLog.log_change(
                registration=self,
                field_name="status",
                old_value=old_status,
                new_value=self.status,
                changed_by=reviewer,
                notes=f"Renewal approved. SchoolStaff profile updated (ID: {staff.pk}). "
                      f"Teacher Registration Number: {staff.teacher_registration_number}",
            )

        return staff

    def reject(self, reviewer, comments):
        """
        Reject the registration and return it to draft for corrections.

        The rejection is logged in the change log for audit trail, then the
        registration transitions back to DRAFT so the teacher can correct
        and resubmit. The reviewer_comments are preserved so the teacher
        can see the rejection reason on the edit form.
        """
        if self.status not in [constants.SUBMITTED, constants.UNDER_REVIEW, constants.READY_FOR_APPROVAL]:
            raise ValueError(
                "Only submitted, under-review, or ready-for-approval registrations can be rejected"
            )

        old_status = self.status
        self.status = constants.REJECTED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.reviewer_comments = comments
        self.save()

        # Log the rejection
        RegistrationChangeLog.log_change(
            registration=self,
            field_name="status",
            old_value=old_status,
            new_value=constants.REJECTED,
            changed_by=reviewer,
            notes=(
                f"Registration rejected. Reason: {comments[:100]}"
                if comments
                else "Registration rejected"
            ),
        )

        # Transition back to draft so the teacher can correct and resubmit
        self.status = constants.DRAFT
        self.save(update_fields=["status", "last_updated_at"])

        RegistrationChangeLog.log_change(
            registration=self,
            field_name="status",
            old_value=constants.REJECTED,
            new_value=constants.DRAFT,
            changed_by=reviewer,
            notes="Returned to draft for corrections",
        )


class RegistrationDocument(AuditModel):
    """
    Document attached to a registration or approved staff profile.

    Initially linked to TeacherRegistration while pending.
    On approval, moved to SchoolStaff (registration FK cleared, school_staff FK set).
    """

    # -------------------------------------------------------------------------
    # Ownership - one of these will be set, not both
    # -------------------------------------------------------------------------

    registration = models.ForeignKey(
        TeacherRegistration,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="documents",
        help_text="Registration this document belongs to (while pending)",
    )

    school_staff = models.ForeignKey(
        SchoolStaff,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="documents",
        help_text="Staff profile this document belongs to (after approval)",
    )

    # -------------------------------------------------------------------------
    # Document fields
    # -------------------------------------------------------------------------

    file = models.FileField(
        upload_to=registration_upload_path,
    )

    original_filename = models.CharField(
        max_length=255,
        help_text="Original filename as uploaded",
    )

    file_size = models.PositiveIntegerField(
        help_text="File size in bytes",
    )

    # -------------------------------------------------------------------------
    # Additional document metadata
    # -------------------------------------------------------------------------

    doc_link_type = models.ForeignKey(
        EmisTeacherLinkType,
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name="Document type",
        help_text="Document type from EMIS lookup",
    )

    doc_title = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Document title",
    )

    doc_description = models.TextField(
        blank=True,
        verbose_name="Document description",
        help_text="Optional description or notes",
    )

    doc_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Document date",
        help_text="Date associated with the document (e.g., issue date)",
    )

    doc_type = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="File type",
        help_text="Computed file extension (e.g., pdf, jpg)",
    )

    class Meta:
        ordering = ["doc_link_type", "created_at"]
        verbose_name = "Registration Document"
        verbose_name_plural = "Registration Documents"
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(registration__isnull=False, school_staff__isnull=True)
                    | models.Q(registration__isnull=True, school_staff__isnull=False)
                ),
                name="document_single_owner",
            ),
        ]

    def __str__(self):
        doc_type_label = self.doc_link_type.label if self.doc_link_type else "Document"
        return f"{doc_type_label} - {self.original_filename}"

    @property
    def owner(self):
        """Return the current owner (registration or staff profile)."""
        return self.registration or self.school_staff


class RegistrationChangeLog(models.Model):
    """
    Audit trail for registration workflow changes.

    Tracks status transitions and optionally field-level changes throughout
    the registration lifecycle. Each log entry captures:
    - What changed (field_name, old_value, new_value)
    - When it changed (changed_at)
    - Who made the change (changed_by)
    - Optional notes for context

    Common workflow events logged:
    - Registration created (draft)
    - Registration submitted
    - Review started
    - Registration approved
    - Registration rejected
    """

    if TYPE_CHECKING:
        # Type hints for Django-generated FK id attributes
        registration_id: int

    registration = models.ForeignKey(
        TeacherRegistration,
        on_delete=models.CASCADE,
        related_name="change_logs",
        help_text="Registration this change belongs to",
    )

    field_name = models.CharField(
        max_length=100,
        help_text="Name of the field that changed (e.g., 'status')",
    )

    old_value = models.CharField(
        max_length=255,
        blank=True,
        help_text="Previous value (empty for creation)",
    )

    new_value = models.CharField(
        max_length=255,
        blank=True,
        help_text="New value after the change",
    )

    changed_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this change occurred",
    )

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="registration_changes",
        help_text="User who made this change",
    )

    notes = models.TextField(
        blank=True,
        help_text="Optional context or reason for the change",
    )

    class Meta:
        ordering = ["-changed_at"]
        verbose_name = "Registration Change Log"
        verbose_name_plural = "Registration Change Logs"
        indexes = [
            models.Index(fields=["registration", "-changed_at"]),
        ]

    def __str__(self):
        return f"{self.registration_id}: {self.field_name} -> {self.new_value}"

    @classmethod
    def log_change(
        cls,
        registration,
        field_name,
        old_value="",
        new_value="",
        changed_by=None,
        notes="",
    ):
        """
        Create a change log entry.

        Args:
            registration: TeacherRegistration instance
            field_name: Name of the field that changed
            old_value: Previous value (string representation)
            new_value: New value (string representation)
            changed_by: User who made the change (optional)
            notes: Additional context (optional)

        Returns:
            RegistrationChangeLog: The created log entry
        """
        return cls.objects.create(
            registration=registration,
            field_name=field_name,
            old_value=str(old_value) if old_value else "",
            new_value=str(new_value) if new_value else "",
            changed_by=changed_by,
            notes=notes,
        )


class EducationRecord(AuditModel):
    """
    Education record for a teacher registration.

    Captures formal education qualifications (degrees, diplomas, certificates).
    On registration approval, these are copied to StaffEducationRecord.

    Attributes:
        registration: Parent registration this record belongs to
        institution_name: Name of the educational institution
        qualification: Type of qualification (FK to EmisTeacherQual)
        program_name: Name of the program/course
        major: Primary subject area (FK to EmisSubject)
        minor: Secondary subject area (FK to EmisSubject, optional)
        completion_year: Year of completion
        duration: Length of program
        duration_unit: Unit for duration (years/months)
        completed: Whether the program was completed
        percentage_progress: Progress percentage if not completed
        comment: Additional notes
    """

    # Duration unit choices
    YEARS = "years"
    MONTHS = "months"

    DURATION_UNIT_CHOICES = [
        (YEARS, "Years"),
        (MONTHS, "Months"),
    ]

    registration = models.ForeignKey(
        TeacherRegistration,
        on_delete=models.CASCADE,
        related_name="education_records",
        help_text="Registration this education record belongs to",
    )

    institution_name = models.CharField(
        max_length=255,
        help_text="Name of the educational institution",
    )

    qualification = models.ForeignKey(
        EmisTeacherQual,
        on_delete=models.PROTECT,
        related_name="education_records",
        verbose_name="Qualification type",
    )

    program_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of the program or course",
    )

    major = models.ForeignKey(
        EmisSubject,
        on_delete=models.PROTECT,
        related_name="education_major_records",
        verbose_name="Major subject",
    )

    minor = models.ForeignKey(
        EmisSubject,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="education_minor_records",
        verbose_name="Minor subject",
    )

    completion_year = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Year of completion",
    )

    duration = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Duration of the program",
    )

    duration_unit = models.CharField(
        max_length=10,
        choices=DURATION_UNIT_CHOICES,
        default=YEARS,
    )

    completed = models.BooleanField(
        default=True,
        help_text="Whether the program was completed",
    )

    percentage_progress = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Progress percentage if not completed (0-100)",
    )

    comment = models.TextField(
        blank=True,
        help_text="Additional notes or comments",
    )

    class Meta:
        ordering = ["-completion_year", "institution_name"]
        verbose_name = "Education Record"
        verbose_name_plural = "Education Records"

    def __str__(self):
        return f"{self.qualification} - {self.institution_name}"


class TrainingRecord(AuditModel):
    """
    Training/Professional Development record for a teacher registration.

    Captures professional development, certifications, and training courses.
    On registration approval, these are copied to StaffTrainingRecord.

    Attributes:
        registration: Parent registration this record belongs to
        provider_institution: Name of the training provider
        title: Title of the training/PD program
        focus: Area of focus (FK to EmisTeacherPdFocus)
        format: Delivery format (FK to EmisTeacherPdFormat)
        completion_year: Year of completion
        duration: Length of training
        duration_unit: Unit for duration (days/hours)
        effective_date: When certification becomes effective
        expiration_date: When certification expires
    """

    # Duration unit choices for training
    DAYS = "days"
    HOURS = "hours"

    DURATION_UNIT_CHOICES = [
        (DAYS, "Days"),
        (HOURS, "Hours"),
    ]

    registration = models.ForeignKey(
        TeacherRegistration,
        on_delete=models.CASCADE,
        related_name="training_records",
        help_text="Registration this training record belongs to",
    )

    provider_institution = models.CharField(
        max_length=255,
        help_text="Name of the training provider",
    )

    title = models.CharField(
        max_length=255,
        help_text="Title of the training or PD program",
    )

    focus = models.ForeignKey(
        EmisTeacherPdFocus,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="training_records",
        verbose_name="Focus area",
    )

    format = models.ForeignKey(
        EmisTeacherPdFormat,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="training_records",
        verbose_name="Delivery format",
    )

    completion_year = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Year of completion",
    )

    duration = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Duration of the training",
    )

    duration_unit = models.CharField(
        max_length=10,
        choices=DURATION_UNIT_CHOICES,
        default=HOURS,
    )

    effective_date = models.DateField(
        null=True,
        blank=True,
        help_text="When certification becomes effective",
    )

    expiration_date = models.DateField(
        null=True,
        blank=True,
        help_text="When certification expires",
    )

    class Meta:
        ordering = ["-completion_year", "title"]
        verbose_name = "Training Record"
        verbose_name_plural = "Training Records"

    def __str__(self):
        return f"{self.title} - {self.provider_institution}"


class ClaimedSchoolAppointment(AuditModel):
    """
    Claimed school appointment for current teachers.

    Captures the school appointment details that a current teacher claims
    during registration. On approval, converted to SchoolStaffAssignment.

    Attributes:
        registration: Parent registration this appointment belongs to
        teacher_level_type: Education level (Primary/JSS/SSS)
        current_island_station: Island where school is located
        current_school: The school where teacher claims to work
        start_date: When the appointment started
        end_date: When the appointment ended (optional, for past appointments)
        years_of_experience: Years at this appointment
        employment_position: Job title/role
        employment_status: Employment status
        class_type: Single-grade or Multi-grade (Primary only)
    """

    # Class type choices (Primary teachers only)
    SINGLE_GRADE = "single"
    MULTI_GRADE = "multi"

    CLASS_TYPE_CHOICES = [
        (SINGLE_GRADE, "Single-grade"),
        (MULTI_GRADE, "Multi-grade"),
    ]

    registration = models.ForeignKey(
        TeacherRegistration,
        on_delete=models.CASCADE,
        related_name="claimed_appointments",
        help_text="Registration this appointment belongs to",
    )

    teacher_level_type = models.ForeignKey(
        EmisEducationLevel,
        on_delete=models.PROTECT,
        related_name="claimed_appointments",
        verbose_name="Teacher level",
        help_text="Education level (Primary, JSS, SSS)",
    )

    current_island_station = models.ForeignKey(
        EmisIsland,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="claimed_appointments",
        verbose_name="Island/Station",
    )

    current_school = models.ForeignKey(
        EmisSchool,
        on_delete=models.PROTECT,
        related_name="claimed_appointments",
        verbose_name="Current school",
    )

    start_date = models.DateField(
        null=True,
        blank=True,
        help_text="When this appointment started (maps to SchoolStaffAssignment.start_date)",
    )

    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="When this appointment ended (maps to SchoolStaffAssignment.end_date). Leave blank for current appointments.",
    )

    years_of_experience = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Years of experience",
    )

    employment_position = models.ForeignKey(
        EmisJobTitle,
        on_delete=models.PROTECT,
        related_name="claimed_appointments",
        verbose_name="Position/Role",
    )

    employment_status = models.ForeignKey(
        EmisTeacherStatus,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="claimed_appointments",
        verbose_name="Employment status",
    )

    class_type = models.CharField(
        max_length=10,
        choices=CLASS_TYPE_CHOICES,
        blank=True,
        help_text="Single-grade or Multi-grade (Primary teachers only)",
    )

    class Meta:
        ordering = ["registration", "current_school"]
        verbose_name = "Claimed School Appointment"
        verbose_name_plural = "Claimed School Appointments"

    def __str__(self):
        return f"{self.current_school} - {self.employment_position}"


class ClaimedDuty(AuditModel):
    """
    Claimed teaching duty for JSS/SSS teachers.

    Captures specific subject/year level teaching assignments within
    a ClaimedSchoolAppointment. Only applicable for JSS/SSS teachers.

    Attributes:
        appointment: Parent appointment this duty belongs to
        year_level: Class/year level being taught
        subject: Subject being taught
    """

    appointment = models.ForeignKey(
        ClaimedSchoolAppointment,
        on_delete=models.CASCADE,
        related_name="claimed_duties",
        help_text="School appointment this duty belongs to",
    )

    year_level = models.ForeignKey(
        EmisClassLevel,
        on_delete=models.PROTECT,
        related_name="claimed_duties",
        verbose_name="Year/Class level",
    )

    subject = models.ForeignKey(
        EmisSubject,
        on_delete=models.PROTECT,
        related_name="claimed_duties",
        verbose_name="Subject taught",
    )

    class Meta:
        ordering = ["appointment", "year_level", "subject"]
        verbose_name = "Claimed Duty"
        verbose_name_plural = "Claimed Duties"

    def __str__(self):
        return f"{self.year_level} - {self.subject}"


class LookupCondition(models.Model):
    """
    Local lookup table for registration condition types.

    Managed via Django admin. Not sourced from EMIS integration.
    """

    code = models.CharField(max_length=64, primary_key=True)
    label = models.CharField(max_length=128)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Condition Type"
        verbose_name_plural = "Condition Types"

    def __str__(self):
        return self.label


class RegistrationCondition(AuditModel):
    """
    Condition attached to a conditional registration or approved staff profile.

    Initially linked to TeacherRegistration while under review.
    On approval, moved to SchoolStaff (registration FK cleared, school_staff FK set).
    On renewal approval, old conditions on SchoolStaff are deleted and replaced
    with the new conditions from the renewal registration.
    """

    # -------------------------------------------------------------------------
    # Ownership - one of these will be set, not both
    # -------------------------------------------------------------------------

    registration = models.ForeignKey(
        TeacherRegistration,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="conditions",
        help_text="Registration this condition belongs to (while pending)",
    )

    school_staff = models.ForeignKey(
        SchoolStaff,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="conditions",
        help_text="Staff profile this condition belongs to (after approval)",
    )

    # -------------------------------------------------------------------------
    # Condition fields
    # -------------------------------------------------------------------------

    condition = models.ForeignKey(
        LookupCondition,
        on_delete=models.PROTECT,
        related_name="registration_conditions",
        verbose_name="Condition type",
        help_text="Condition type from local lookup",
    )

    notes = models.TextField(
        blank=True,
        help_text="Free-form notes about this condition",
    )

    class Meta:
        ordering = ["condition", "created_at"]
        verbose_name = "Registration Condition"
        verbose_name_plural = "Registration Conditions"
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(registration__isnull=False, school_staff__isnull=True)
                    | models.Q(registration__isnull=True, school_staff__isnull=False)
                ),
                name="condition_single_owner",
            ),
        ]

    def __str__(self):
        return self.condition.label

    @property
    def owner(self):
        """Return the current owner (registration or staff profile)."""
        return self.registration or self.school_staff

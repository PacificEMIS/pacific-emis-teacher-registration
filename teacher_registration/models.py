"""
Models for the teacher_registration app.

This module contains models for the teacher self-registration workflow:
- TeacherRegistration: Holds registration data while pending approval
- RegistrationDocument: Documents attached to registrations (moved to SchoolStaff on approval)
- RegistrationChangeLog: Audit trail for registration workflow changes
"""

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import AuditModel, SchoolStaff
from integrations.models import EmisSchool, EmisJobTitle

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

    # Status choices
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"

    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (SUBMITTED, "Submitted"),
        (UNDER_REVIEW, "Under Review"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
    ]

    # Registration type
    INITIAL = "initial"
    RENEWAL = "renewal"

    TYPE_CHOICES = [
        (INITIAL, "Initial Registration"),
        (RENEWAL, "Renewal"),
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

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=DRAFT,
    )

    # -------------------------------------------------------------------------
    # Profile data (copied to SchoolStaff on approval)
    # -------------------------------------------------------------------------

    # Personal information
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        verbose_name="Date of birth",
    )
    gender = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ("male", "Male"),
            ("female", "Female"),
            ("other", "Other"),
        ],
    )
    nationality = models.CharField(max_length=100, blank=True)
    national_id_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="National ID number",
    )
    phone_number = models.CharField(max_length=30, blank=True)

    # Address
    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=100, blank=True)

    # Professional information
    teaching_certificate_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Teaching certificate number",
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

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Teacher Registration"
        verbose_name_plural = "Teacher Registrations"

    # Type stubs for Django-generated methods (satisfy type checkers)
    def get_status_display(self) -> str: ...
    def get_registration_type_display(self) -> str: ...
    def get_gender_display(self) -> str: ...
    def get_highest_qualification_display(self) -> str: ...

    def __str__(self):
        return f"Registration<{self.user}, {self.get_status_display()}>"

    @property
    def is_editable(self):
        """Check if the registration can still be edited."""
        return self.status == self.DRAFT

    @property
    def can_submit(self):
        """Check if the registration is ready to submit."""
        # Add validation logic here as needed
        return self.status == self.DRAFT

    # -------------------------------------------------------------------------
    # Workflow methods
    # -------------------------------------------------------------------------

    def submit(self, user=None):
        """Submit the registration for review."""
        if self.status != self.DRAFT:
            raise ValueError("Only draft registrations can be submitted")

        old_status = self.status
        self.status = self.SUBMITTED
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at", "last_updated_at"])

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
        if self.status not in [self.SUBMITTED, self.REJECTED]:
            raise ValueError("Only submitted or rejected registrations can be reviewed")

        old_status = self.status
        self.status = self.UNDER_REVIEW
        self.reviewed_by = reviewer
        self.save(update_fields=["status", "reviewed_by", "last_updated_at"])

        # Log the status change
        notes = "Review started" if old_status == self.SUBMITTED else "Re-review started"
        RegistrationChangeLog.log_change(
            registration=self,
            field_name="status",
            old_value=old_status,
            new_value=self.status,
            changed_by=reviewer,
            notes=notes,
        )

    def approve(self, reviewer, comments=""):
        """
        Approve the registration and create SchoolStaff profile.

        This method:
        1. Creates SchoolStaff with data from this registration
        2. Moves documents to SchoolStaff
        3. Marks this registration as approved

        Returns:
            SchoolStaff: The created staff profile
        """
        if self.status not in [self.SUBMITTED, self.UNDER_REVIEW]:
            raise ValueError(
                "Only submitted or under-review registrations can be approved"
            )

        # Create SchoolStaff profile
        staff = SchoolStaff.objects.create(
            user=self.user,
            staff_type=SchoolStaff.TEACHING_STAFF,
            # Profile fields
            date_of_birth=self.date_of_birth,
            gender=self.gender,
            nationality=self.nationality,
            national_id_number=self.national_id_number,
            phone_number=self.phone_number,
            address_line_1=self.address_line_1,
            address_line_2=self.address_line_2,
            city=self.city,
            province=self.province,
            teaching_certificate_number=self.teaching_certificate_number,
            highest_qualification=self.highest_qualification,
            years_of_experience=self.years_of_experience,
            # Registration status
            registration_status=SchoolStaff.REGISTRATION_VALID,
            # Audit
            created_by=reviewer,
            last_updated_by=reviewer,
        )

        # Move documents to SchoolStaff
        self.documents.update(
            school_staff=staff,
            registration=None,
        )

        # Update registration status
        old_status = self.status
        self.status = self.APPROVED
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
            notes=f"Registration approved. SchoolStaff profile created (ID: {staff.pk})",
        )

        return staff

    def reject(self, reviewer, comments):
        """Reject the registration with comments."""
        if self.status not in [self.SUBMITTED, self.UNDER_REVIEW]:
            raise ValueError(
                "Only submitted or under-review registrations can be rejected"
            )

        old_status = self.status
        self.status = self.REJECTED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.reviewer_comments = comments
        self.save()

        # Log the status change
        RegistrationChangeLog.log_change(
            registration=self,
            field_name="status",
            old_value=old_status,
            new_value=self.status,
            changed_by=reviewer,
            notes=f"Registration rejected. Reason: {comments[:100]}" if comments else "Registration rejected",
        )


class RegistrationDocument(AuditModel):
    """
    Document attached to a registration or approved staff profile.

    Initially linked to TeacherRegistration while pending.
    On approval, moved to SchoolStaff (registration FK cleared, school_staff FK set).
    """

    # Document type choices
    NATIONAL_ID = "national_id"
    BIRTH_CERTIFICATE = "birth_certificate"
    TEACHING_CERTIFICATE = "teaching_certificate"
    DEGREE_CERTIFICATE = "degree_certificate"
    TRANSCRIPT = "transcript"
    PHOTO = "photo"
    OTHER = "other"

    DOCUMENT_TYPE_CHOICES = [
        (NATIONAL_ID, "National ID"),
        (BIRTH_CERTIFICATE, "Birth Certificate"),
        (TEACHING_CERTIFICATE, "Teaching Certificate"),
        (DEGREE_CERTIFICATE, "Degree Certificate"),
        (TRANSCRIPT, "Academic Transcript"),
        (PHOTO, "Passport Photo"),
        (OTHER, "Other"),
    ]

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

    document_type = models.CharField(
        max_length=30,
        choices=DOCUMENT_TYPE_CHOICES,
    )

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

    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional description or notes",
    )

    class Meta:
        ordering = ["document_type", "created_at"]
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

    # Type stub for Django-generated method (satisfy type checkers)
    def get_document_type_display(self) -> str: ...

    def __str__(self):
        return f"{self.get_document_type_display()} - {self.original_filename}"

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

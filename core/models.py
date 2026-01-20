"""
Core models for the Pacific EMIS system.

This module contains fundamental person-related models that are shared across
multiple applications within the Pacific EMIS ecosystem.

Models:
    AuditModel: Abstract base model with audit fields (created_at, created_by, etc.)
    SchoolStaff: School-level user profiles (teachers, principals, etc.)
    SystemUser: System-level user profiles (MOE officials, analysts, etc.)
    SchoolStaffAssignment: Links school staff to schools with job titles
"""

from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from integrations.models import (
    EmisSchool,
    EmisJobTitle,
    EmisWarehouseYear,
    EmisClassLevel,
)

if TYPE_CHECKING:
    from django.db.models.manager import RelatedManager


class AuditModel(models.Model):
    """
    Abstract base model that provides audit fields.

    All models that need audit tracking should inherit from this.
    Provides: created_at, created_by, last_updated_at, last_updated_by
    """

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_created",
    )
    last_updated_at = models.DateTimeField(auto_now=True)
    last_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_updated",
    )

    class Meta:
        abstract = True


class SchoolStaff(AuditModel):
    """
    School-level staff profile for users who work at schools.

    Represents staff members such as teachers, principals, counselors, etc.
    Each SchoolStaff has a one-to-one relationship with a Django User.
    School assignments are managed through SchoolStaffAssignment.

    Attributes:
        user (User): Django user account (one-to-one)
        staff_type (str): Type of staff - Teaching or Non-Teaching
        schools (QuerySet[EmisSchool]): Schools this staff member is assigned to (via SchoolStaffAssignment)
        created_at (datetime): When this record was created
        created_by (User): Who created this record
        last_updated_at (datetime): When this record was last modified
        last_updated_by (User): Who last modified this record

    Example:
        >>> user = User.objects.get(username='jsmith')
        >>> staff = SchoolStaff.objects.create(
        ...     user=user,
        ...     staff_type=SchoolStaff.TEACHING_STAFF,
        ...     created_by=admin_user
        ... )
        >>> assignment = SchoolStaffAssignment.objects.create(
        ...     school_staff=staff,
        ...     school=some_school,
        ...     job_title=teacher_title
        ... )
    """

    TEACHING_STAFF = "teaching"
    NON_TEACHING_STAFF = "non_teaching"

    STAFF_TYPE_CHOICES = [
        (TEACHING_STAFF, "Teaching Staff"),
        (NON_TEACHING_STAFF, "Non-Teaching Staff"),
    ]

    # Registration status choices (for teaching staff)
    REGISTRATION_VALID = "valid"
    REGISTRATION_EXPIRED = "expired"

    REGISTRATION_STATUS_CHOICES = [
        (REGISTRATION_VALID, "Valid"),
        (REGISTRATION_EXPIRED, "Expired"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="school_staff",
        help_text="Django user account for this staff member",
    )

    staff_type = models.CharField(
        max_length=20,
        choices=STAFF_TYPE_CHOICES,
        default=NON_TEACHING_STAFF,
        help_text="Type of staff member - teaching or non-teaching",
    )

    # -------------------------------------------------------------------------
    # Personal information (from teacher registration)
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Professional information (from teacher registration)
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Registration status (for teaching staff only)
    # -------------------------------------------------------------------------

    registration_status = models.CharField(
        max_length=20,
        choices=REGISTRATION_STATUS_CHOICES,
        null=True,
        blank=True,
        help_text="Registration status (only applicable for teaching staff)",
    )
    registration_valid_until = models.DateField(
        null=True,
        blank=True,
        help_text="Date when current registration expires",
    )

    # Many-to-many relationship with schools (through SchoolStaffAssignment)
    schools = models.ManyToManyField(
        EmisSchool,
        through="SchoolStaffAssignment",
        related_name="school_staff_members",
        blank=True,
    )

    if TYPE_CHECKING:
        # Type hint for the reverse relation from SchoolStaffAssignment
        assignments: "RelatedManager[SchoolStaffAssignment]"

    class Meta:
        ordering = ["user_id"]
        verbose_name = "School Staff"
        verbose_name_plural = "School Staff"

    def __str__(self):
        """Return string representation showing the user."""
        return f"SchoolStaff<{self.user}>"

    @property
    def active_assignments(self):
        """
        Get all currently active school assignments.

        Returns assignments where end_date is either null or in the future/today.

        Returns:
            QuerySet[SchoolStaffAssignment]: Active assignments for this staff member
        """
        today = timezone.now().date()
        return self.assignments.filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today)
        )


class SchoolStaffAssignment(AuditModel):
    """
    School assignment for a SchoolStaff member.

    Links a staff member to a specific school with a job title and date range.
    Multiple assignments allow staff to work at different schools over time.

    Attributes:
        school_staff (SchoolStaff): The staff member being assigned
        school (EmisSchool): The school they're assigned to
        job_title (EmisJobTitle): Their role at this school (e.g., Teacher, Principal)
        start_date (date): When the assignment began (optional)
        end_date (date): When the assignment ended (null = currently active)
        created_at (datetime): When this record was created
        created_by (User): Who created this record
        last_updated_at (datetime): When this record was last modified
        last_updated_by (User): Who last modified this record

    Note:
        The is_active property considers an assignment active if end_date is None.
        Use the active_now admin method for date-range-based active status.

    Example:
        >>> assignment = SchoolStaffAssignment.objects.create(
        ...     school_staff=staff,
        ...     school=school,
        ...     job_title=title,
        ...     start_date=date(2024, 1, 1),
        ...     created_by=admin_user
        ... )
    """

    school_staff = models.ForeignKey(
        SchoolStaff,
        on_delete=models.CASCADE,
        related_name="assignments",
        help_text="Staff member being assigned",
    )
    school = models.ForeignKey(
        EmisSchool,
        on_delete=models.PROTECT,
        related_name="staff_assignments",
        help_text="School where staff is assigned",
    )
    job_title = models.ForeignKey(
        EmisJobTitle,
        on_delete=models.PROTECT,
        related_name="job_title_assignments",
        help_text="Job title/role at this school",
    )

    start_date = models.DateField(
        null=True, blank=True, help_text="When this assignment began"
    )
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="When this assignment ended (null = currently active)",
    )

    class Meta:
        indexes = [
            models.Index(fields=["start_date", "end_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["school_staff", "school", "start_date", "end_date"],
                name="uq_school_staff_assignment",
            ),
        ]
        ordering = ["school_staff_id", "school_id", "start_date"]
        verbose_name = "School Staff Assignment"
        verbose_name_plural = "School Staff Assignments"

    def __str__(self):
        """Return string representation showing staff and school."""
        return f"{self.school_staff.user} @ {self.school}"

    @property
    def is_active(self):
        """
        Check if this assignment is marked as active.

        An assignment is considered active if it has no end_date set.
        This is a simple active/inactive flag, not date-range based.

        Returns:
            bool: True if end_date is None, False otherwise

        Note:
            For date-range-based active status (checking if assignment
            is active TODAY), use the admin's active_now method.
        """
        return self.end_date is None


class SystemUser(AuditModel):
    """
    System-level user profile with cross-organizational access.

    Represents users who operate at a system-wide level rather than
    being tied to specific schools. Examples include:
    - Ministry of Education officials
    - District/regional office staff
    - System administrators
    - External consultants
    - Data analysts

    Unlike SchoolStaff (who work at specific schools), SystemUsers
    have permissions across the entire system.

    Attributes:
        user (User): Django user account (one-to-one)
        organization (str): Organization name (e.g., "Ministry of Education")
        position_title (str): Job title within the organization
        created_at (datetime): When this record was created
        created_by (User): Who created this record
        last_updated_at (datetime): When this record was last modified
        last_updated_by (User): Who last modified this record

    Example:
        >>> user = User.objects.get(username='jdoe')
        >>> system_user = SystemUser.objects.create(
        ...     user=user,
        ...     organization="Ministry of Education",
        ...     position_title="Data Analyst",
        ...     created_by=admin_user
        ... )
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="system_user",
        help_text="Django user account for this system user",
    )

    organization = models.CharField(
        max_length=255,
        blank=True,
        help_text="Organization or department (e.g., Ministry of Education, District Office)",
    )
    position_title = models.CharField(
        max_length=255,
        blank=True,
        help_text="Job title or position within the organization",
    )

    class Meta:
        ordering = ["user__last_name", "user__first_name"]
        verbose_name = "System User"
        verbose_name_plural = "System Users"

    def __str__(self):
        """
        Return string representation showing name and organization.

        Returns:
            str: User's full name (or username) with organization in parentheses if set
        """
        name = self.user.get_full_name() or self.user.username
        if self.organization:
            return f"{name} ({self.organization})"
        return name

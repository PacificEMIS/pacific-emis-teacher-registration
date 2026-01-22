"""
Django admin configuration for teacher_registration models.

Provides admin interfaces for:
- TeacherRegistration (with inlines for related models)
- EducationRecord
- TrainingRecord
- ClaimedSchoolAppointment
- ClaimedDuty
- RegistrationDocument
- RegistrationChangeLog
"""

from django.contrib import admin

from teacher_registration.models import (
    TeacherRegistration,
    RegistrationDocument,
    RegistrationChangeLog,
    EducationRecord,
    TrainingRecord,
    ClaimedSchoolAppointment,
    ClaimedDuty,
)


# ---- Inline Admins ----

class RegistrationDocumentInline(admin.TabularInline):
    """Inline admin for registration documents."""

    model = RegistrationDocument
    extra = 0
    fields = ["doc_link_type", "doc_title", "file", "original_filename"]
    readonly_fields = ["original_filename", "file_size"]


class EducationRecordInline(admin.TabularInline):
    """Inline admin for education records."""

    model = EducationRecord
    extra = 0
    autocomplete_fields = ["qualification", "major", "minor"]
    fields = [
        "institution_name",
        "qualification",
        "program_name",
        "major",
        "minor",
        "completion_year",
        "completed",
    ]


class TrainingRecordInline(admin.TabularInline):
    """Inline admin for training records."""

    model = TrainingRecord
    extra = 0
    autocomplete_fields = ["focus", "format"]
    fields = [
        "title",
        "provider_institution",
        "focus",
        "format",
        "completion_year",
        "effective_date",
        "expiration_date",
    ]


class ClaimedDutyInline(admin.TabularInline):
    """Inline admin for claimed duties (nested under ClaimedSchoolAppointment)."""

    model = ClaimedDuty
    extra = 0
    autocomplete_fields = ["year_level", "subject"]
    fields = ["year_level", "subject"]


class ClaimedSchoolAppointmentInline(admin.StackedInline):
    """Inline admin for claimed school appointments."""

    model = ClaimedSchoolAppointment
    extra = 0
    autocomplete_fields = [
        "teacher_level_type",
        "current_island_station",
        "current_school",
        "employment_position",
        "employment_status",
    ]
    fieldsets = (
        (None, {
            "fields": (
                "teacher_level_type",
                ("current_island_station", "current_school"),
                ("start_date", "years_of_experience"),
                ("employment_position", "employment_status"),
                "class_type",
            )
        }),
    )


class RegistrationChangeLogInline(admin.TabularInline):
    """Inline admin for viewing change logs (read-only)."""

    model = RegistrationChangeLog
    extra = 0
    readonly_fields = ["field_name", "old_value", "new_value", "changed_at", "changed_by", "notes"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


# ---- Main Model Admins ----

@admin.register(TeacherRegistration)
class TeacherRegistrationAdmin(admin.ModelAdmin):
    """
    Admin interface for TeacherRegistration.

    Includes inlines for documents, education records, training records,
    and claimed appointments.
    """

    list_display = [
        "id",
        "user",
        "teacher_category",
        "registration_type",
        "status",
        "submitted_at",
        "created_at",
    ]
    list_filter = [
        "status",
        "registration_type",
        "teacher_category",
        "created_at",
        "submitted_at",
    ]
    search_fields = [
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
        "national_id_number",
    ]
    readonly_fields = [
        "created_at",
        "created_by",
        "last_updated_at",
        "last_updated_by",
        "submitted_at",
        "reviewed_at",
        "approved_staff_profile",
    ]
    autocomplete_fields = [
        "user",
        "gender_emis",
        "marital_status",
        "home_island",
        "nearby_school",
        "preferred_school",
        "preferred_job_title",
        "reviewed_by",
    ]
    inlines = [
        EducationRecordInline,
        TrainingRecordInline,
        ClaimedSchoolAppointmentInline,
        RegistrationDocumentInline,
        RegistrationChangeLogInline,
    ]

    fieldsets = (
        ("Status", {
            "fields": (
                ("registration_type", "teacher_category", "status"),
                ("submitted_at", "reviewed_at"),
                ("reviewed_by", "reviewer_comments"),
                "approved_staff_profile",
            )
        }),
        ("User", {
            "fields": ("user",)
        }),
        ("Personal Information", {
            "fields": (
                "title",
                "date_of_birth",
                ("gender", "gender_emis"),
                "marital_status",
                "nationality",
                "national_id_number",
                "home_island",
            )
        }),
        ("Contact Information", {
            "fields": (
                ("phone_number", "phone_home"),
            )
        }),
        ("Residential Address", {
            "fields": (
                "address_line_1",
                "address_line_2",
                ("city", "province"),
                "nearby_school",
            )
        }),
        ("Business Address", {
            "fields": (
                "business_address_line_1",
                "business_address_line_2",
                ("business_city", "business_province"),
            ),
            "classes": ("collapse",),
        }),
        ("Professional Information", {
            "fields": (
                "teacher_payroll_number",
                "highest_qualification",
                "years_of_experience",
            )
        }),
        ("School Preference", {
            "fields": (
                "preferred_school",
                "preferred_job_title",
            )
        }),
        ("Audit", {
            "fields": (
                ("created_at", "created_by"),
                ("last_updated_at", "last_updated_by"),
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(EducationRecord)
class EducationRecordAdmin(admin.ModelAdmin):
    """Admin interface for standalone EducationRecord management."""

    list_display = [
        "registration",
        "institution_name",
        "qualification",
        "major",
        "completion_year",
        "completed",
    ]
    list_filter = ["completed", "qualification", "completion_year"]
    search_fields = ["institution_name", "program_name"]
    autocomplete_fields = ["registration", "qualification", "major", "minor"]


@admin.register(TrainingRecord)
class TrainingRecordAdmin(admin.ModelAdmin):
    """Admin interface for standalone TrainingRecord management."""

    list_display = [
        "registration",
        "title",
        "provider_institution",
        "focus",
        "completion_year",
    ]
    list_filter = ["focus", "format", "completion_year"]
    search_fields = ["title", "provider_institution"]
    autocomplete_fields = ["registration", "focus", "format"]


@admin.register(ClaimedSchoolAppointment)
class ClaimedSchoolAppointmentAdmin(admin.ModelAdmin):
    """Admin interface for ClaimedSchoolAppointment with ClaimedDuty inline."""

    list_display = [
        "registration",
        "current_school",
        "employment_position",
        "teacher_level_type",
        "start_date",
    ]
    list_filter = ["teacher_level_type", "employment_status", "class_type"]
    search_fields = ["current_school__emis_school_name"]
    autocomplete_fields = [
        "registration",
        "teacher_level_type",
        "current_island_station",
        "current_school",
        "employment_position",
        "employment_status",
    ]
    inlines = [ClaimedDutyInline]


@admin.register(ClaimedDuty)
class ClaimedDutyAdmin(admin.ModelAdmin):
    """Admin interface for standalone ClaimedDuty management."""

    list_display = ["appointment", "year_level", "subject"]
    list_filter = ["year_level", "subject"]
    autocomplete_fields = ["appointment", "year_level", "subject"]


@admin.register(RegistrationDocument)
class RegistrationDocumentAdmin(admin.ModelAdmin):
    """Admin interface for RegistrationDocument."""

    list_display = [
        "id",
        "doc_link_type",
        "original_filename",
        "registration",
        "school_staff",
        "created_at",
    ]
    list_filter = ["doc_link_type", "created_at"]
    search_fields = ["original_filename", "doc_title", "doc_description"]
    autocomplete_fields = ["registration", "school_staff", "doc_link_type"]
    readonly_fields = ["file_size", "created_at", "created_by"]


@admin.register(RegistrationChangeLog)
class RegistrationChangeLogAdmin(admin.ModelAdmin):
    """Admin interface for RegistrationChangeLog (read-only audit trail)."""

    list_display = [
        "registration",
        "field_name",
        "old_value",
        "new_value",
        "changed_at",
        "changed_by",
    ]
    list_filter = ["field_name", "changed_at"]
    search_fields = ["registration__user__username", "notes"]
    readonly_fields = [
        "registration",
        "field_name",
        "old_value",
        "new_value",
        "changed_at",
        "changed_by",
        "notes",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

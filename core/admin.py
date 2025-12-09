"""
Django admin configuration for core models.

Provides admin interfaces for:
- User (Django's built-in User model with role assignment filters)
- SchoolStaff
- SchoolStaffAssignment
- SystemUser
"""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from django.utils.html import format_html

from core.models import SchoolStaff, SchoolStaffAssignment, SystemUser
from core.mixins import CreatedUpdatedAuditMixin

User = get_user_model()


# ---- User (Django's built-in User model) ----

class HasRoleFilter(admin.SimpleListFilter):
    """Custom filter to show users by role assignment status."""
    title = "role assignment"
    parameter_name = "role"

    def lookups(self, request, model_admin):
        return (
            ("no_role", "No role assigned"),
            ("school_staff", "Has School Staff profile"),
            ("system_user", "Has System User profile"),
            ("both", "Has both profiles"),
        )

    def queryset(self, request, queryset):
        if self.value() == "no_role":
            return queryset.filter(school_staff__isnull=True, system_user__isnull=True)
        elif self.value() == "school_staff":
            return queryset.filter(school_staff__isnull=False)
        elif self.value() == "system_user":
            return queryset.filter(system_user__isnull=False)
        elif self.value() == "both":
            return queryset.filter(school_staff__isnull=False, system_user__isnull=False)
        return queryset


class CustomUserAdmin(BaseUserAdmin):
    """
    Custom User admin that helps manage role assignments.

    Adds filters to identify users without SchoolStaff or SystemUser profiles,
    making it easy for admins to assign roles to newly signed-up users.
    """
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_active",
        "role_status",
        "date_joined",
    )
    list_filter = (
        HasRoleFilter,
        "is_staff",
        "is_superuser",
        "is_active",
        "date_joined",
    )

    def get_queryset(self, request):
        """Optimize queries by prefetching related profiles."""
        qs = super().get_queryset(request)
        return qs.select_related("school_staff", "system_user")

    def role_status(self, obj):
        """Display whether user has SchoolStaff, SystemUser, or no role assigned."""
        has_school_staff = hasattr(obj, "school_staff")
        has_system_user = hasattr(obj, "system_user")

        if has_school_staff and has_system_user:
            return format_html('<span style="color: orange;">⚠ Both roles</span>')
        elif has_school_staff:
            return format_html('<span style="color: green;">✓ School Staff</span>')
        elif has_system_user:
            return format_html('<span style="color: blue;">✓ System User</span>')
        else:
            return format_html('<span style="color: red;">✗ No role</span>')

    role_status.short_description = "Role Status"


# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


# ---- SchoolStaff and SchoolStaffAssignment ----

class SchoolStaffAssignmentInline(admin.TabularInline):
    """
    Inline admin for SchoolStaffAssignment.

    Allows editing school assignments directly within the SchoolStaff admin page.
    Shows school, job title, and date range for each assignment.
    """
    model = SchoolStaffAssignment
    extra = 1
    autocomplete_fields = ["school", "job_title"]
    fields = ["school", "job_title", "start_date", "end_date"]
    readonly_fields = []


@admin.register(SchoolStaff)
class SchoolStaffAdmin(CreatedUpdatedAuditMixin, admin.ModelAdmin):
    """
    Admin interface for SchoolStaff model.

    Displays user information, active school assignments, and provides
    inline editing of school assignments directly on the staff detail page.
    """
    list_display = ["user", "user_email", "active_assignments_display", "created_at"]
    search_fields = ["user__username", "user__email", "user__first_name", "user__last_name"]
    list_filter = ["created_at", "schools"]
    readonly_fields = ["created_at", "created_by", "last_updated_at", "last_updated_by"]
    autocomplete_fields = ["user"]
    inlines = [SchoolStaffAssignmentInline]

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = "Email"
    user_email.admin_order_field = "user__email"

    def active_assignments_display(self, obj):
        """Show count of active school assignments."""
        count = obj.active_assignments.count()
        if count == 0:
            return format_html('<span style="color: #999;">None</span>')
        return f"{count} school(s)"
    active_assignments_display.short_description = "Active Assignments"


# ---- SystemUser ----

@admin.register(SystemUser)
class SystemUserAdmin(admin.ModelAdmin):
    """
    Admin interface for SystemUser model.

    Displays system-level users (MOE staff, consultants, administrators).
    """
    list_display = ["user", "organization", "position_title", "created_at"]
    search_fields = ["user__username", "user__email", "user__first_name", "user__last_name", "organization"]
    list_filter = ["organization", "created_at"]
    readonly_fields = ["created_at", "created_by", "last_updated_at", "last_updated_by"]

    fieldsets = (
        (None, {
            "fields": ("user", "organization", "position_title")
        }),
        ("Audit", {
            "fields": ("created_at", "created_by", "last_updated_at", "last_updated_by"),
            "classes": ("collapse",),
        }),
    )

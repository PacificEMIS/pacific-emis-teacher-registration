"""
Context processors for core app.

Provides template context variables related to user profiles (SchoolStaff, SystemUser).
"""
from typing import Any

from django.http import HttpRequest
from django.urls import reverse

from core.models import SchoolStaff, SystemUser
from core.permissions import can_access_system_users, can_manage_pending_users, has_app_access


def staff_context(request: HttpRequest) -> dict[str, Any]:
    """
    Adds user_profile_url for linking to the user's own profile page.
    Checks for SchoolStaff, then SystemUser, then falls back to admin user page.

    Also provides:
    - has_app_access: whether user has full app access (profile + group)
    - can_access_system_users: for MOE Staff nav visibility control
    - can_manage_pending_users: for Pending Users management visibility (Admins or System Admins)
    - user_active_registration: the user's active registration (draft/submitted/under_review)
    - user_registration_url: URL to the user's registration edit page
    """
    user = request.user
    context: dict[str, Any] = {
        "staff_pk_for_request_user": None,
        "system_user_pk_for_request_user": None,
        "user_profile_url": None,
        "has_app_access": has_app_access(user),
        "can_access_system_users": can_access_system_users(user),
        "can_manage_pending_users": can_manage_pending_users(user),
        "user_active_registration": None,
        "user_registration_url": None,
    }

    if user.is_authenticated:
        # Check for SchoolStaff profile first
        try:
            staff = SchoolStaff.objects.only("pk").get(user=user)
            context["staff_pk_for_request_user"] = staff.pk
            context["user_profile_url"] = reverse("core:staff_detail", kwargs={"pk": staff.pk})
        except SchoolStaff.DoesNotExist:
            # Check for SystemUser profile
            try:
                system_user = SystemUser.objects.only("pk").get(user=user)
                context["system_user_pk_for_request_user"] = system_user.pk
                context["user_profile_url"] = reverse("core:system_user_detail", kwargs={"pk": system_user.pk})
            except SystemUser.DoesNotExist:
                # Fall back to admin user change page for superusers/staff without a profile
                if user.is_superuser or user.is_staff:
                    context["user_profile_url"] = reverse("admin:auth_user_change", args=[user.pk])

        # Check for active teacher registration (draft, submitted, under_review, or rejected)
        # Import here to avoid circular imports
        from teacher_registration.models import TeacherRegistration

        active_registration = (
            TeacherRegistration.objects.filter(
                user=user,
                status__in=[
                    TeacherRegistration.DRAFT,
                    TeacherRegistration.SUBMITTED,
                    TeacherRegistration.UNDER_REVIEW,
                    TeacherRegistration.REJECTED,
                ],
            )
            .order_by("-created_at")
            .first()
        )
        if active_registration:
            context["user_active_registration"] = active_registration
            # For rejected registrations, go to my_registration view (read-only history)
            # For other statuses, go to edit view
            if active_registration.status == TeacherRegistration.REJECTED:
                context["user_registration_url"] = reverse("teacher_registration:my_registration")
            else:
                context["user_registration_url"] = reverse(
                    "teacher_registration:edit", kwargs={"pk": active_registration.pk}
                )
        elif context["staff_pk_for_request_user"] and not context["has_app_access"]:
            # Approved teacher without app access - show My Registration link
            context["user_registration_url"] = reverse("teacher_registration:my_registration")
            context["is_approved_teacher"] = True

    return context

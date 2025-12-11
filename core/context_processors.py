"""
Context processors for core app.

Provides template context variables related to user profiles (SchoolStaff, SystemUser).
"""
from typing import Any

from django.http import HttpRequest
from django.urls import reverse

from core.models import SchoolStaff, SystemUser
from core.permissions import can_access_system_users, is_admins_group


def staff_context(request: HttpRequest) -> dict[str, Any]:
    """
    Adds user_profile_url for linking to the user's own profile page.
    Checks for SchoolStaff, then SystemUser, then falls back to admin user page.

    Also provides:
    - can_access_system_users: for MOE Staff nav visibility control
    - is_admins_group_user: for Pending Users management visibility
    """
    user = request.user
    context: dict[str, Any] = {
        "staff_pk_for_request_user": None,
        "system_user_pk_for_request_user": None,
        "user_profile_url": None,
        "can_access_system_users": can_access_system_users(user),
        "is_admins_group_user": is_admins_group(user),
    }

    if user.is_authenticated:
        # Check for SchoolStaff profile first
        try:
            staff = SchoolStaff.objects.only("pk").get(user=user)
            context["staff_pk_for_request_user"] = staff.pk
            context["user_profile_url"] = reverse("core:staff_detail", kwargs={"pk": staff.pk})
            return context
        except SchoolStaff.DoesNotExist:
            pass

        # Check for SystemUser profile
        try:
            system_user = SystemUser.objects.only("pk").get(user=user)
            context["system_user_pk_for_request_user"] = system_user.pk
            context["user_profile_url"] = reverse("core:system_user_detail", kwargs={"pk": system_user.pk})
            return context
        except SystemUser.DoesNotExist:
            pass

        # Fall back to admin user change page for superusers/staff without a profile
        if user.is_superuser or user.is_staff:
            context["user_profile_url"] = reverse("admin:auth_user_change", args=[user.pk])

    return context

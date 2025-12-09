"""
Context processors for core app.

Provides template context variables related to user profiles (SchoolStaff, SystemUser).
"""
from django.urls import reverse
from core.models import SchoolStaff, SystemUser


def staff_context(request):
    """
    Adds user_profile_url for linking to the user's own profile page.
    Checks for SchoolStaff, then SystemUser, then falls back to admin user page.
    """
    user = request.user
    context = {
        "staff_pk_for_request_user": None,
        "system_user_pk_for_request_user": None,
        "user_profile_url": None,
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

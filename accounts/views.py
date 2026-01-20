from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.messages import get_messages
from django.shortcuts import render, redirect
from django.urls import reverse, NoReverseMatch
from django.utils.http import url_has_allowed_host_and_scheme
from core.permissions import has_app_access


def _clear_messages(request):
    """Clear all pending messages from the session."""
    storage = get_messages(request)
    # Iterate to mark messages as used/cleared
    for _ in storage:
        pass


def _get_safe_redirect_url(request):
    """
    Get a safe redirect URL from the request (GET or session).
    Returns None if no safe URL is found.
    """
    # Check GET parameter first, then session (AllAuth stores it there)
    next_url = request.GET.get("next") or request.session.get("next")

    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        # Clear from session after use
        if "next" in request.session:
            del request.session["next"]
        return next_url
    return None


def _get_user_active_registration_url(user):
    """
    Check if user has an active registration and return its URL.
    Returns None if no active registration exists.
    """
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
        # For rejected registrations, go to my_registration view (read-only history)
        if active_registration.status == TeacherRegistration.REJECTED:
            return reverse("teacher_registration:my_registration")
        return reverse("teacher_registration:edit", kwargs={"pk": active_registration.pk})
    return None


@login_required
def post_login_router(request):
    """
    Route users after login based on app access and next parameter.

    Priority:
    1. If user has app access: redirect to next URL or dashboard
    2. If user came from registration flow: redirect to that URL
    3. If user has an active registration: redirect to their registration
    4. Otherwise: redirect to no permissions page
    """
    next_url = _get_safe_redirect_url(request)

    # Check if this is a registration flow redirect
    is_registration_flow = next_url and "registration" in next_url

    if has_app_access(request.user):
        # User has full app access, redirect to next or dashboard
        return redirect(next_url or "dashboard")

    if is_registration_flow:
        # User came from registration flow - allow them to continue
        # even without full app access (they're registering!)
        return redirect(next_url)

    # Check if user has an active registration they can continue
    registration_url = _get_user_active_registration_url(request.user)
    if registration_url:
        return redirect(registration_url)

    # Check if user is an approved teacher (has school_staff profile)
    # They should see their registration status page
    if hasattr(request.user, "school_staff"):
        return redirect("teacher_registration:my_registration")

    return redirect("accounts:no_permissions")


@login_required
def no_permissions(request):
    support_email = getattr(settings, "APP_SUPPORT_EMAIL", None)
    return render(
        request, "accounts/no_permissions.html", {"support_email": support_email}
    )


def sign_in(request):
    next_url = request.GET.get("next", "")

    if request.user.is_authenticated:
        # If already logged in, respect the next parameter
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect("dashboard")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.POST.get("next") or request.GET.get("next")
            return redirect(next_url or reverse("dashboard"))
        messages.error(request, "Invalid username or password.")

    # Check if coming from registration flow
    is_registration_flow = "registration" in next_url if next_url else False

    # Store next in session for AllAuth to pick up after OAuth
    if next_url:
        request.session["next"] = next_url

    return render(
        request,
        "accounts/login.html",
        {
            "next": next_url,
            "is_registration_flow": is_registration_flow,
        },
    )


@login_required
def sign_out(request):
    _clear_messages(request)
    logout(request)
    return redirect("accounts:login")


def permission_denied_view(request, exception=None):
    """
    Custom 403 handler that renders a styled forbidden page.
    """
    return render(request, "accounts/forbidden.html", status=403)

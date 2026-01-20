"""
Signals for account-related events.

Handles user signup events, specifically for Google OAuth sign-ins.
"""
from django.dispatch import receiver
from allauth.account.signals import user_signed_up
from django.contrib.auth import get_user_model

from core.emails import send_new_pending_user_email_async

User = get_user_model()


def _is_registration_flow(request):
    """
    Check if the user signed up via the teacher registration flow.

    We check the session 'next' URL which is set when users start registration.
    """
    if not request:
        return False

    next_url = request.session.get("next", "") or request.GET.get("next", "")
    return "registration" in next_url


@receiver(user_signed_up)
def notify_admins_on_signup(request, user, **kwargs):
    """
    When a new user signs up via Google OAuth, notify Admins so they can
    assign the user as School Staff or System User.

    The user is NOT automatically assigned a profile; they remain as a
    'pending user' until an Admin assigns them a role.

    NOTE: If the user is signing up via the teacher self-registration flow,
    we skip this email. They will receive a different notification when they
    start their registration (see teacher_registration.views.registration_create).
    """
    # Skip notification if user came from teacher registration flow
    # They'll get a specific "registration started" email instead
    if _is_registration_flow(request):
        return

    # Build the pending users list URL for the email
    from django.urls import reverse

    pending_users_url = None
    if request:
        pending_users_url = request.build_absolute_uri(
            reverse("core:pending_users_list")
        )

    # Send email notification to Admins (async to not block the request)
    send_new_pending_user_email_async(
        new_user=user,
        pending_users_url=pending_users_url,
    )

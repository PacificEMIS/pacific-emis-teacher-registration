"""
Email notifications for core app.

Handles email notifications for pending user signups.
"""
import logging
from threading import Thread

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

User = get_user_model()


def _get_pending_user_manager_emails():
    """
    Return emails of all active users who can manage pending users.

    This includes users in the 'Admins' and 'System Admins' groups.
    """
    groups = Group.objects.filter(name__in=["Admins", "System Admins"])

    if not groups.exists():
        return []

    # Get all users in either group, deduplicated
    qs = (
        User.objects.filter(groups__in=groups, is_active=True)
        .exclude(email__isnull=True)
        .exclude(email__exact="")
        .distinct()
    )
    return [u.email for u in qs]


def send_new_pending_user_email(*, new_user, pending_users_url=None):
    """
    Send HTML + text email when a new user signs up via Google OAuth.

    Recipients: all users in the "Admins" and "System Admins" groups.
    """
    # Get emails of users who can manage pending users
    recipients = _get_pending_user_manager_emails()

    if not recipients:
        logger.info("send_new_pending_user_email: no recipients, skipping.")
        return

    app_name = getattr(settings, "APP_NAME", "Teacher Registration")
    emis_context = settings.EMIS.get("CONTEXT", "Pacific EMIS")

    context = {
        "new_user": new_user,
        "pending_users_url": pending_users_url,
        "emis_context": emis_context,
        "app_name": app_name,
    }

    subject = f"{emis_context} {app_name}: New user awaiting role assignment"

    text_body = render_to_string("emails/new_pending_user.txt", context)
    html_body = render_to_string("emails/new_pending_user.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


def send_new_pending_user_email_async(new_user, pending_users_url=None):
    """
    Fire-and-forget wrapper: send the email on a background thread so the
    HTTP request isn't blocked by SMTP latency.
    """

    def _worker():
        try:
            send_new_pending_user_email(
                new_user=new_user,
                pending_users_url=pending_users_url,
            )
        except Exception:
            logger.warning(
                "send_new_pending_user_email_async: error sending email "
                "for new user %s",
                new_user.email or new_user.username,
                exc_info=True,
            )

    Thread(target=_worker, daemon=True).start()

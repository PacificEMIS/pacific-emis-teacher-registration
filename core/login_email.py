"""
Change the sign-in email of a user account (issue #122).

A teacher who loses access to the mailbox they applied with cannot sign in
any more. The email lives only on the Django ``User`` row (where it doubles
as the username for Google sign-ins) plus allauth's bookkeeping, so the
application, the staff record and every uploaded document are untouched by
the change. This module holds the checks and the single transaction that
performs it; the view in core/views.py only wires it to a page.

Who may do this is decided by the view (Admins group only). What is refused
regardless of who asks lives in ``login_email_change_blockers``.
"""

import logging

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

User = get_user_model()


def normalize_email(value):
    return (value or "").strip().lower()


def account_using_email(email, exclude_user=None):
    """
    The account that already owns ``email`` as its email, username or an
    allauth email address, or None. A second account for the same person is
    a common outcome of a lost mailbox (they sign up again), and it must be
    dealt with deliberately by staff, never merged or overwritten here.
    """
    email = normalize_email(email)
    if not email:
        return None
    users = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email))
    if exclude_user is not None:
        users = users.exclude(pk=exclude_user.pk)
    user = users.order_by("pk").first()
    if user:
        return user
    rows = EmailAddress.objects.filter(email__iexact=email).select_related("user")
    if exclude_user is not None:
        rows = rows.exclude(user=exclude_user)
    row = rows.order_by("pk").first()
    return row.user if row else None


def login_email_change_blockers(target_user, acting_user):
    """Every reason ``target_user``'s sign-in email must NOT be changed from the app."""
    blockers = []
    if target_user.is_superuser:
        blockers.append("is a superuser (change it in the Django admin instead)")
    if target_user == acting_user:
        blockers.append("is your own account (ask another administrator)")
    return blockers


class ChangeLoginEmailForm(forms.Form):
    new_email = forms.EmailField(
        label="New sign-in email",
        max_length=254,
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "off"}),
    )
    new_email_confirm = forms.EmailField(
        label="Repeat the new sign-in email",
        max_length=254,
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "off"}),
    )
    verified_with_person = forms.BooleanField(
        label=(
            "I have confirmed directly with this person that the new address is theirs "
            "and that they can sign in with it."
        ),
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, target_user, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_user = target_user
        self.conflicting_user = None

    def clean_new_email(self):
        email = normalize_email(self.cleaned_data["new_email"])
        if email == normalize_email(self.target_user.email):
            raise forms.ValidationError("That is already this account's sign-in email.")
        other = account_using_email(email, exclude_user=self.target_user)
        if other is not None:
            self.conflicting_user = other
            who = other.get_full_name() or other.username
            raise forms.ValidationError(
                f"{email} already belongs to another account ({who}, id {other.pk}). "
                "Nothing was changed. Review that account first: if it is a duplicate the same "
                "person created, remove it deliberately via Pending Users, then come back here."
            )
        return email

    def clean(self):
        cleaned = super().clean()
        new_email = cleaned.get("new_email")
        confirm = normalize_email(cleaned.get("new_email_confirm"))
        if new_email and confirm and new_email != confirm:
            self.add_error("new_email_confirm", "The two addresses do not match.")
        return cleaned


def _end_sessions(user):
    """Log the account out everywhere; an old mailbox may be in someone else's hands."""
    ended = 0
    user_id = str(user.pk)
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        if session.get_decoded().get("_auth_user_id") == user_id:
            session.delete()
            ended += 1
    return ended


def apply_login_email_change(target_user, new_email, acting_user):
    """
    Perform the change in one transaction and return what was done.

    - ``User.email`` is replaced. ``User.username`` follows only when it was
      the old email (the convention for Google sign-ins); a hand-picked
      username for a password account is kept.
    - allauth's email addresses for the account are replaced by the new one.
    - Every linked social account (the old Google login) is removed. The new
      Google account links itself on first sign-in because its verified email
      now matches the account.
    - Active sessions of the account are ended.
    - The latest teacher registration, if any, gets an audit line.
    """
    from teacher_registration.models import RegistrationChangeLog, TeacherRegistration

    new_email = normalize_email(new_email)
    old_email = target_user.email
    old_username = target_user.username
    username_follows = (
        not old_username
        or "@" in old_username
        or normalize_email(old_username) == normalize_email(old_email)
    )

    with transaction.atomic():
        target_user.email = new_email
        update_fields = ["email"]
        if username_follows:
            target_user.username = new_email
            update_fields.append("username")
        target_user.save(update_fields=update_fields)

        EmailAddress.objects.filter(user=target_user).delete()
        EmailAddress.objects.create(user=target_user, email=new_email, primary=True, verified=False)

        social = SocialAccount.objects.filter(user=target_user)
        removed_providers = sorted(set(social.values_list("provider", flat=True)))
        social.delete()

        ended_sessions = _end_sessions(target_user)

        registration = TeacherRegistration.objects.filter(user=target_user).order_by("-created_at", "-pk").first()
        if registration is not None:
            limit = RegistrationChangeLog._meta.get_field("old_value").max_length
            RegistrationChangeLog.objects.create(
                registration=registration,
                field_name="login_email",
                old_value=(old_email or "")[:limit],
                new_value=new_email[:limit],
                changed_by=acting_user,
                notes="Sign-in email changed by an administrator",
            )

    logger.warning(
        "Sign-in email of user id=%s changed from %r to %r by %s (id=%s); username %s, "
        "social accounts removed: %s, sessions ended: %s",
        target_user.pk,
        old_email,
        new_email,
        acting_user.username,
        acting_user.pk,
        "updated" if username_follows else "kept",
        ", ".join(removed_providers) or "none",
        ended_sessions,
    )
    return {
        "old_email": old_email,
        "old_username": old_username,
        "new_email": new_email,
        "username_changed": username_follows,
        "removed_providers": removed_providers,
        "ended_sessions": ended_sessions,
        "registration": registration,
    }

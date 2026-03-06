from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.core.exceptions import PermissionDenied


class DomainRestrictedAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return True

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        allowed = getattr(settings, "ALLOWED_SIGNUP_DOMAINS", None)
        if allowed:
            email = (user.email or "").lower()
            if not any(email.endswith("@" + d.lower()) for d in allowed):
                raise PermissionDenied("This email domain is not allowed.")
        if commit:
            user.save()
        return user


class EmailAsUsernameSocialAdapter(DefaultSocialAccountAdapter):
    """
    Custom social account adapter that uses the user's email as their username.

    This provides clearer, more recognizable usernames than the default
    which generates names like "john123" from "john@example.com".
    """

    def populate_user(self, request, sociallogin, data):
        """
        Populate user instance with data from social provider.
        Uses email as username for clarity. Preserves existing names
        (e.g. when staff already entered them for a placeholder user).
        """
        user = super().populate_user(request, sociallogin, data)

        # Use email as username (it's unique and clear)
        email = data.get("email")
        if email:
            user.username = email
            user.email = email

        # Preserve names already set (e.g. by staff during on-behalf registration)
        # Only populate from Google if the user doesn't already have them
        if not user.first_name:
            user.first_name = data.get("first_name", "")
        if not user.last_name:
            user.last_name = data.get("last_name", "")

        return user

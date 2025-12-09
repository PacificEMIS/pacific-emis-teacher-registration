from django.dispatch import receiver
from allauth.account.signals import user_signed_up
from django.contrib.auth import get_user_model

User = get_user_model()


@receiver(user_signed_up)
def log_user_signup(request, user, **kwargs):
    """
    Log when a new user signs up via Google OAuth.

    Note: We do NOT automatically create SchoolStaff or SystemUser profiles.
    Admins must manually assign roles to new users via Django admin.
    """
    # You could add logging here if needed
    pass

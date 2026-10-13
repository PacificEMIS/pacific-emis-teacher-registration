"""
Forms for core models.
"""
from typing import cast

from django import forms
from django.contrib.auth.models import Group
from django.forms import ModelForm

from core.models import OrgSettings, SchoolStaff, SchoolStaffAssignment, SystemUser
from integrations.models import EmisEducationLevel, EmisSchool
from core.permissions import is_admin, is_admins_group, get_user_schools, can_assign_admins_group, GROUP_SYSTEM_ADMINS, _in_group


class SchoolStaffAssignmentForm(ModelForm):
    class Meta:
        model = SchoolStaffAssignment
        fields = ["school", "job_title", "teacher_level_type", "start_date", "end_date"]
        widgets = {
            "school": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "job_title": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "teacher_level_type": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "start_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        """
        Initialize form with user context to restrict school choices.

        Args:
            user: The user creating/editing the membership (for permission filtering)
        """
        super().__init__(*args, **kwargs)

        level_field = cast(forms.ModelChoiceField, self.fields["teacher_level_type"])
        level_field.queryset = EmisEducationLevel.objects.filter(active=True).order_by("label")

        # Get the school field as ModelChoiceField for type checking
        school_field = cast(forms.ModelChoiceField, self.fields["school"])

        # Restrict school choices based on user permissions
        if user and user.is_authenticated:
            if user.is_superuser or is_admin(user):
                # System admins see all active schools
                school_field.queryset = EmisSchool.objects.filter(
                    active=True
                ).order_by("emis_school_name")
            else:
                # School admins see only their active schools
                user_schools = get_user_schools(user)
                school_field.queryset = user_schools.order_by(
                    "emis_school_name"
                )
        else:
            # No user context - restrict to nothing
            school_field.queryset = EmisSchool.objects.none()


# ============================================================================
# SchoolStaff Edit Form
# ============================================================================


class SchoolStaffEditForm(forms.Form):
    """
    Form to edit an existing School Staff member.

    Allows editing staff_type and group memberships.

    Permissions:
    - Django Super Users and Admins group: can edit all fields including groups,
      and can assign any group including Admins.
    - System Admins group: can edit all fields including groups,
      but cannot assign the Admins group.
    - School Admins group: can edit staff_type and groups for staff at their schools,
      but cannot assign the Admins group.
    """

    staff_type = forms.ChoiceField(
        label="Staff type",
        choices=SchoolStaff.STAFF_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    groups = forms.ModelMultipleChoiceField(
        label="Groups",
        queryset=Group.objects.all().order_by("name"),
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        help_text="Select at least one group to assign permissions.",
    )

    def __init__(self, *args, user=None, school_staff=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Determine if user can assign the Admins group
        self.can_assign_admins = False
        if user:
            self.can_assign_admins = user.is_superuser or is_admins_group(user)

        # Filter groups based on user permissions
        if self.can_assign_admins:
            school_groups = ["Admins", "School Admins", "School Staff", "Teachers", "Registration Signatories"]
        else:
            # System Admins and School Admins cannot assign the Admins group
            school_groups = ["School Admins", "School Staff", "Teachers", "Registration Signatories"]

        self.fields["groups"].queryset = Group.objects.filter(
            name__in=school_groups
        ).order_by("name")

        if not self.can_assign_admins:
            self.fields["groups"].help_text = (
                "Select at least one group. Note: Only full Admins can assign the Admins group."
            )

        # Pre-populate with existing values if editing
        if school_staff and not self.is_bound:
            self.initial["staff_type"] = school_staff.staff_type
            # Get current groups that are in our allowed list
            current_groups = school_staff.user.groups.filter(name__in=school_groups)
            self.initial["groups"] = current_groups


# ============================================================================
# User Role Assignment Forms (for Pending Users)
# ============================================================================


class AssignSchoolStaffForm(forms.Form):
    """
    Form to assign a pending user as School Staff.

    Creates a SchoolStaff profile and assigns them to groups.

    - Django Super Users and Admins group: can assign any school-level group including Admins
    - System Admins group: can assign school-level groups except Admins
    """

    staff_type = forms.ChoiceField(
        label="Staff type",
        choices=SchoolStaff.STAFF_TYPE_CHOICES,
        initial=SchoolStaff.NON_TEACHING_STAFF,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    groups = forms.ModelMultipleChoiceField(
        label="Groups",
        queryset=Group.objects.all().order_by("name"),
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        help_text="Select at least one group to assign permissions.",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Determine available groups based on user permissions
        # Superusers and Admins can assign any school-level group including Admins
        # System Admins can assign school-level groups except Admins
        self.can_assign_admins = can_assign_admins_group(user) if user else False

        if self.can_assign_admins:
            school_groups = ["Admins", "School Admins", "School Staff", "Teachers", "Registration Signatories"]
        else:
            # System Admins cannot assign the Admins group
            school_groups = ["School Admins", "School Staff", "Teachers", "Registration Signatories"]

        self.fields["groups"].queryset = Group.objects.filter(
            name__in=school_groups
        ).order_by("name")

        if not self.can_assign_admins:
            self.fields["groups"].help_text = (
                "Select at least one group. Note: Only full Admins can assign the Admins group."
            )


class AssignSystemUserForm(forms.Form):
    """
    Form to assign a pending user as a System User.

    Creates a SystemUser profile and assigns them to groups.

    - Django Super Users and Admins group: can assign any system-level group including Admins
    - System Admins group: can assign system-level groups except Admins
    """

    organization = forms.CharField(
        label="Organization",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g., Ministry of Education",
            }
        ),
        help_text="Organization or department name.",
    )

    position_title = forms.CharField(
        label="Position title",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g., Data Analyst",
            }
        ),
        help_text="Job title or position within the organization.",
    )

    groups = forms.ModelMultipleChoiceField(
        label="Groups",
        queryset=Group.objects.all().order_by("name"),
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        help_text="Select at least one group to assign permissions.",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Determine available groups based on user permissions
        # Superusers and Admins can assign any system-level group including Admins
        # System Admins can assign system-level groups except Admins
        self.can_assign_admins = can_assign_admins_group(user) if user else False

        if self.can_assign_admins:
            system_groups = ["Admins", "System Admins", "System Staff", "Registration Signatories"]
        else:
            # System Admins cannot assign the Admins group
            system_groups = ["System Admins", "System Staff", "Registration Signatories"]

        self.fields["groups"].queryset = Group.objects.filter(
            name__in=system_groups
        ).order_by("name")

        if not self.can_assign_admins:
            self.fields["groups"].help_text = (
                "Select at least one group. Note: Only full Admins can assign the Admins group."
            )


# ============================================================================
# SystemUser Edit Form
# ============================================================================


class SystemUserEditForm(forms.Form):
    """
    Form to edit an existing System User.

    Allows editing organization, position_title, and group memberships.

    Permissions:
    - Django Super Users and Admins group: can edit all fields including groups,
      and can assign any group including Admins.
    - System Admins group: can edit organization and position, and can edit groups
      but cannot assign the Admins group.
    """

    organization = forms.CharField(
        label="Organization",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g., Ministry of Education",
            }
        ),
        help_text="Organization or department name.",
    )

    position_title = forms.CharField(
        label="Position title",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g., Data Analyst",
            }
        ),
        help_text="Job title or position within the organization.",
    )

    signature = forms.ImageField(
        label="Signature",
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control form-control-sm", "accept": "image/*"}),
        help_text="Signature image used on registration certificates. PNG with a transparent background recommended.",
    )

    groups = forms.ModelMultipleChoiceField(
        label="Groups",
        queryset=Group.objects.all().order_by("name"),
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        help_text="Select at least one group to assign permissions.",
    )

    def __init__(self, *args, user=None, system_user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Determine if user can assign the Admins group
        self.can_assign_admins = False
        if user:
            self.can_assign_admins = user.is_superuser or is_admins_group(user)

        # Filter groups based on user permissions
        if self.can_assign_admins:
            system_groups = ["Admins", "System Admins", "System Staff", "Registration Signatories"]
        else:
            # System Admins cannot assign the Admins group
            system_groups = ["System Admins", "System Staff", "Registration Signatories"]

        self.fields["groups"].queryset = Group.objects.filter(
            name__in=system_groups
        ).order_by("name")

        if not self.can_assign_admins:
            self.fields["groups"].help_text = (
                "Select at least one group. Note: Only full Admins can assign the Admins group."
            )

        # Pre-populate with existing values if editing
        if system_user and not self.is_bound:
            self.initial["organization"] = system_user.organization
            self.initial["position_title"] = system_user.position_title
            self.initial["signature"] = system_user.signature
            # Get current groups that are in our allowed list
            current_groups = system_user.user.groups.filter(name__in=system_groups)
            self.initial["groups"] = current_groups


# ============================================================================
# Organization Settings
# ============================================================================


class OrgSettingsForm(ModelForm):
    """Form for org-wide branding settings (currently just the stamp)."""

    class Meta:
        model = OrgSettings
        fields = ["stamp"]
        widgets = {
            "stamp": forms.ClearableFileInput(
                attrs={"class": "form-control form-control-sm", "accept": "image/*"}
            ),
        }


class TestEmailForm(forms.Form):
    """Recipient address for the Utilities > Test Email check."""

    recipient = forms.EmailField(
        label="Send test email to",
        max_length=254,
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
        help_text="Defaults to your own address. Change it to test delivery to another mailbox.",
    )


# ============================================================================
# Self-service profile
# ============================================================================


class MyProfileForm(forms.Form):
    """
    Form for a user to edit their *own* profile.

    Deliberately narrow: it never exposes groups, email, username or any
    flag that affects access. The requesting user is always the subject, so
    the form cannot be pointed at another account.

    Fields offered depend on the profile type:
    - Everyone: first_name, last_name (shown in the header and on certificates)
    - SystemUser: organization, position_title
    - SystemUser in the Registration Signatories group: signature
    """

    first_name = forms.CharField(
        label="First name",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )
    last_name = forms.CharField(
        label="Last name",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )
    organization = forms.CharField(
        label="Organization",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g., Ministry of Education",
            }
        ),
        help_text="Organization or department name.",
    )
    position_title = forms.CharField(
        label="Position title",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g., Registrar",
            }
        ),
        help_text="Printed under your signature on registration certificates.",
    )
    signature = forms.ImageField(
        label="Signature",
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control form-control-sm", "accept": "image/*"}
        ),
        help_text="Signature image used on registration certificates. PNG with a transparent background recommended.",
    )

    def __init__(self, *args, user, profile, can_edit_signature=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.profile = profile
        self.is_system_user = isinstance(profile, SystemUser)
        self.can_edit_signature = self.is_system_user and can_edit_signature

        if not self.is_system_user:
            del self.fields["organization"]
            del self.fields["position_title"]
        if not self.can_edit_signature:
            del self.fields["signature"]

        if not self.is_bound:
            self.initial["first_name"] = user.first_name
            self.initial["last_name"] = user.last_name
            if self.is_system_user:
                self.initial["organization"] = profile.organization
                self.initial["position_title"] = profile.position_title
            if self.can_edit_signature:
                self.initial["signature"] = profile.signature

    def save(self):
        """Apply the cleaned data to the user and their profile row."""
        data = self.cleaned_data
        self.user.first_name = data["first_name"].strip()
        self.user.last_name = data["last_name"].strip()
        self.user.save(update_fields=["first_name", "last_name"])

        if self.is_system_user:
            self.profile.organization = data["organization"]
            self.profile.position_title = data["position_title"]
        if self.can_edit_signature:
            # ClearableFileInput: False when "clear" was ticked, an UploadedFile
            # when a new file was chosen, None when untouched.
            sig = data.get("signature")
            if sig is False:
                self.profile.signature.delete(save=False)
            elif sig:
                self.profile.signature = sig
        self.profile.last_updated_by = self.user
        self.profile.save()
        return self.profile

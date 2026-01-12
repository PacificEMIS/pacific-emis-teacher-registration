"""
Forms for core models.
"""
from typing import cast

from django import forms
from django.contrib.auth.models import Group
from django.forms import ModelForm

from core.models import SchoolStaff, SchoolStaffAssignment, SystemUser
from integrations.models import EmisSchool
from core.permissions import is_admin, is_admins_group, get_user_schools, can_assign_admins_group, GROUP_SYSTEM_ADMINS, _in_group


class SchoolStaffAssignmentForm(ModelForm):
    class Meta:
        model = SchoolStaffAssignment
        fields = ["school", "job_title", "start_date", "end_date"]
        widgets = {
            "school": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "job_title": forms.Select(attrs={"class": "form-select form-select-sm"}),
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
            school_groups = ["Admins", "School Admins", "School Staff", "Teachers"]
        else:
            # System Admins and School Admins cannot assign the Admins group
            school_groups = ["School Admins", "School Staff", "Teachers"]

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
            school_groups = ["Admins", "School Admins", "School Staff", "Teachers"]
        else:
            # System Admins cannot assign the Admins group
            school_groups = ["School Admins", "School Staff", "Teachers"]

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
            system_groups = ["Admins", "System Admins", "System Staff"]
        else:
            # System Admins cannot assign the Admins group
            system_groups = ["System Admins", "System Staff"]

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
            system_groups = ["Admins", "System Admins", "System Staff"]
        else:
            # System Admins cannot assign the Admins group
            system_groups = ["System Admins", "System Staff"]

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
            # Get current groups that are in our allowed list
            current_groups = system_user.user.groups.filter(name__in=system_groups)
            self.initial["groups"] = current_groups

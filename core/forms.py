"""
Forms for core models.
"""
from typing import cast

from django import forms
from django.contrib.auth.models import Group
from django.forms import ModelForm

from core.models import SchoolStaff, SchoolStaffAssignment
from integrations.models import EmisSchool
from core.permissions import is_admin, get_user_schools


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
# User Role Assignment Forms (for Pending Users)
# ============================================================================


class AssignSchoolStaffForm(forms.Form):
    """
    Form to assign a pending user as School Staff.

    Creates a SchoolStaff profile and assigns them to groups.
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter to only school-level groups
        school_groups = ["Admins", "School Admins", "School Staff", "Teachers"]
        self.fields["groups"].queryset = Group.objects.filter(
            name__in=school_groups
        ).order_by("name")


class AssignSystemUserForm(forms.Form):
    """
    Form to assign a pending user as a System User.

    Creates a SystemUser profile and assigns them to groups.
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter to only system-level groups (and Admins which is shared)
        system_groups = ["Admins", "System Admins", "System Staff"]
        self.fields["groups"].queryset = Group.objects.filter(
            name__in=system_groups
        ).order_by("name")

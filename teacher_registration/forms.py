"""
Forms for teacher registration.
"""

from django import forms
from django.contrib.auth import get_user_model

from teacher_registration.models import TeacherRegistration, RegistrationDocument
from integrations.models import EmisSchool, EmisJobTitle

User = get_user_model()


class TeacherRegistrationForm(forms.ModelForm):
    """
    Form for teachers to fill out their registration application.

    Includes personal information, professional details, and school preferences.
    Also allows updating the user's first/last name.
    """

    # User fields (stored on User model, not TeacherRegistration)
    # Not required at form level - validation happens on submit in the view
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    class Meta:
        model = TeacherRegistration
        fields = [
            # Personal information
            "date_of_birth",
            "gender",
            "nationality",
            "national_id_number",
            "phone_number",
            # Address
            "address_line_1",
            "address_line_2",
            "city",
            "province",
            # Professional information
            "teaching_certificate_number",
            "highest_qualification",
            "years_of_experience",
            # School preference
            "preferred_school",
            "preferred_job_title",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "gender": forms.Select(attrs={"class": "form-select"}),
            "nationality": forms.TextInput(attrs={"class": "form-control"}),
            "national_id_number": forms.TextInput(attrs={"class": "form-control"}),
            "phone_number": forms.TextInput(attrs={"class": "form-control"}),
            "address_line_1": forms.TextInput(attrs={"class": "form-control"}),
            "address_line_2": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "province": forms.TextInput(attrs={"class": "form-control"}),
            "teaching_certificate_number": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "highest_qualification": forms.Select(attrs={"class": "form-select"}),
            "years_of_experience": forms.NumberInput(
                attrs={"class": "form-control", "min": "0"}
            ),
            "preferred_school": forms.Select(attrs={"class": "form-select"}),
            "preferred_job_title": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        # Get initial data for first/last name before calling super
        instance = kwargs.get("instance")
        initial = kwargs.get("initial", {})

        # Set initial values for first_name and last_name from user
        if instance and instance.pk and instance.user:
            initial.setdefault("first_name", instance.user.first_name)
            initial.setdefault("last_name", instance.user.last_name)
        elif user:
            initial.setdefault("first_name", user.first_name)
            initial.setdefault("last_name", user.last_name)

        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

        # Filter school and job title choices to active only
        self.fields["preferred_school"].queryset = EmisSchool.objects.filter(
            active=True
        ).order_by("emis_school_name")
        self.fields["preferred_job_title"].queryset = EmisJobTitle.objects.filter(
            active=True
        ).order_by("label")

    def save(self, commit=True):
        """Save the registration and update user's name."""
        instance = super().save(commit=False)

        # Always update user's name from form data
        if instance.user and commit:
            first_name = self.cleaned_data.get("first_name", "")
            last_name = self.cleaned_data.get("last_name", "")
            # Update user model with whatever was submitted
            instance.user.first_name = first_name
            instance.user.last_name = last_name
            instance.user.save(update_fields=["first_name", "last_name"])

        if commit:
            instance.save()

        return instance


class RegistrationDocumentForm(forms.ModelForm):
    """
    Form for uploading a document to a registration.
    """

    class Meta:
        model = RegistrationDocument
        fields = ["document_type", "file", "description"]
        widgets = {
            "document_type": forms.Select(attrs={"class": "form-select"}),
            "file": forms.FileInput(attrs={"class": "form-control"}),
            "description": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Optional description"}
            ),
        }

    def clean_file(self):
        """Validate file size and type."""
        file = self.cleaned_data.get("file")
        if file:
            # Limit file size to 10MB
            max_size = 10 * 1024 * 1024  # 10MB
            if file.size > max_size:
                raise forms.ValidationError(
                    f"File size must be under 10MB. Current size: {file.size / 1024 / 1024:.1f}MB"
                )

            # Allowed file types
            allowed_types = [
                "application/pdf",
                "image/jpeg",
                "image/png",
                "image/gif",
            ]
            if hasattr(file, "content_type") and file.content_type not in allowed_types:
                raise forms.ValidationError(
                    "Only PDF and image files (JPEG, PNG, GIF) are allowed."
                )

        return file

    def save(self, commit=True):
        """Save document with original filename and size."""
        instance = super().save(commit=False)

        if self.cleaned_data.get("file"):
            instance.original_filename = self.cleaned_data["file"].name
            instance.file_size = self.cleaned_data["file"].size

        if commit:
            instance.save()

        return instance


class AdminTeacherRegistrationForm(forms.Form):
    """
    Form for admins to create a registration on behalf of a teacher.

    Creates a new user and registration in one step.
    """

    # User fields
    first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "Optional - leave blank if teacher has no email"}
        ),
        help_text="Leave blank if the teacher doesn't have an email address.",
    )

    # Personal information
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    gender = forms.ChoiceField(
        required=False,
        choices=[("", "---------"), ("male", "Male"), ("female", "Female"), ("other", "Other")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    nationality = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    national_id_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    phone_number = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    # Address
    address_line_1 = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    address_line_2 = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    city = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    province = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    # Professional information
    teaching_certificate_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    highest_qualification = forms.ChoiceField(
        required=False,
        choices=[
            ("", "---------"),
            ("high_school", "High School"),
            ("certificate", "Certificate"),
            ("diploma", "Diploma"),
            ("bachelors", "Bachelor's Degree"),
            ("masters", "Master's Degree"),
            ("doctorate", "Doctorate"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    years_of_experience = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
    )

    # School preference
    preferred_school = forms.ModelChoiceField(
        required=False,
        queryset=EmisSchool.objects.filter(active=True).order_by("emis_school_name"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    preferred_job_title = forms.ModelChoiceField(
        required=False,
        queryset=EmisJobTitle.objects.filter(active=True).order_by("label"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class RegistrationReviewForm(forms.Form):
    """
    Form for admins to approve or reject a registration.
    """

    ACTION_APPROVE = "approve"
    ACTION_REJECT = "reject"

    ACTION_CHOICES = [
        (ACTION_APPROVE, "Approve"),
        (ACTION_REJECT, "Reject"),
    ]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
    )

    comments = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Comments (required for rejection, optional for approval)",
            }
        ),
    )

    def clean(self):
        """Require comments for rejection."""
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        comments = cleaned_data.get("comments", "").strip()

        if action == self.ACTION_REJECT and not comments:
            raise forms.ValidationError(
                {"comments": "Please provide a reason for rejection."}
            )

        return cleaned_data

"""
Forms for teacher registration.
"""

from django import forms
from django.contrib.auth import get_user_model
from django.forms import inlineformset_factory

from teacher_registration.models import (
    TeacherRegistration,
    RegistrationDocument,
    EducationRecord,
    TrainingRecord,
    ClaimedSchoolAppointment,
    ClaimedDuty,
)
from integrations.models import (
    EmisSchool,
    EmisJobTitle,
    EmisGender,
    EmisMaritalStatus,
    EmisIsland,
    EmisTeacherQual,
    EmisSubject,
    EmisEducationLevel,
    EmisTeacherStatus,
    EmisClassLevel,
    EmisTeacherPdFocus,
    EmisTeacherPdFormat,
    EmisTeacherPdType,
    EmisNationality,
    EmisTeacherLinkType,
)

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
            # Teacher category (determines form sections)
            "teacher_category",
            # Personal information
            "title",
            "date_of_birth",
            "gender",
            "gender_emis",
            "marital_status",
            "nationality",
            "national_id_number",
            "home_island",
            # Contact information
            "phone_number",
            "phone_home",
            # Residential address
            "residential_address",
            "nearby_school",
            # Business address
            "business_address",
            # Professional information (legacy - may be derived from EducationRecords)
            "teacher_payroll_number",
            "highest_qualification",
            "years_of_experience",
        ]
        widgets = {
            "teacher_category": forms.RadioSelect(attrs={"class": "form-check-input"}),
            "title": forms.Select(attrs={"class": "form-select"}),
            "date_of_birth": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "gender": forms.Select(attrs={"class": "form-select"}),
            "gender_emis": forms.Select(attrs={"class": "form-select"}),
            "marital_status": forms.Select(attrs={"class": "form-select"}),
            "nationality": forms.Select(attrs={"class": "form-select"}),
            "national_id_number": forms.TextInput(attrs={"class": "form-control"}),
            "home_island": forms.Select(attrs={"class": "form-select"}),
            "phone_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Mobile"}),
            "phone_home": forms.TextInput(attrs={"class": "form-control", "placeholder": "Home"}),
            "residential_address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "nearby_school": forms.Select(attrs={"class": "form-select"}),
            "business_address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "teacher_payroll_number": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "highest_qualification": forms.Select(attrs={"class": "form-select"}),
            "years_of_experience": forms.NumberInput(
                attrs={"class": "form-control", "min": "0"}
            ),
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

        # Filter FK querysets to active records only
        self.fields["gender_emis"].queryset = EmisGender.objects.filter(
            active=True
        ).order_by("label")
        self.fields["marital_status"].queryset = EmisMaritalStatus.objects.filter(
            active=True
        ).order_by("label")
        self.fields["home_island"].queryset = EmisIsland.objects.filter(
            active=True
        ).order_by("label")
        self.fields["nearby_school"].queryset = EmisSchool.objects.filter(
            active=True
        ).order_by("emis_school_name")
        self.fields["nationality"].queryset = EmisNationality.objects.filter(
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

    Fields:
    - doc_link_type: Required - document type from EMIS lookup
    - doc_title: Optional - custom title for the document
    - doc_description: Optional - description/notes
    - doc_date: Optional - date associated with the document (e.g., issue date)
    - file: Required - the file to upload

    Auto-computed on save:
    - original_filename: from uploaded file
    - file_size: from uploaded file
    - doc_type: file extension extracted from filename
    """

    class Meta:
        model = RegistrationDocument
        fields = ["doc_link_type", "doc_title", "doc_description", "doc_date", "file"]
        widgets = {
            "doc_link_type": forms.Select(attrs={"class": "form-select"}),
            "doc_title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Optional title"}
            ),
            "doc_description": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Optional description"}
            ),
            "doc_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "file": forms.FileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter to active document types only
        self.fields["doc_link_type"].queryset = EmisTeacherLinkType.objects.filter(
            active=True
        ).order_by("label")

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
        """Save document with auto-computed fields."""
        instance = super().save(commit=False)

        if self.cleaned_data.get("file"):
            filename = self.cleaned_data["file"].name
            instance.original_filename = filename
            instance.file_size = self.cleaned_data["file"].size
            # Extract file extension for doc_type
            if "." in filename:
                instance.doc_type = filename.rsplit(".", 1)[-1].lower()

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
    residential_address = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    # Professional information
    teacher_payroll_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        label="Teacher Payroll Number (PF Number)",
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


# =============================================================================
# Education and Training Record Forms
# =============================================================================


class EducationRecordForm(forms.ModelForm):
    """
    Form for adding/editing education records.
    """

    class Meta:
        model = EducationRecord
        fields = [
            "institution_name",
            "qualification",
            "program_name",
            "major",
            "minor",
            "completion_year",
            "duration",
            "duration_unit",
            "completed",
            "percentage_progress",
            "comment",
        ]
        widgets = {
            "institution_name": forms.TextInput(attrs={"class": "form-control"}),
            "qualification": forms.Select(attrs={"class": "form-select"}),
            "program_name": forms.TextInput(attrs={"class": "form-control"}),
            "major": forms.Select(attrs={"class": "form-select"}),
            "minor": forms.Select(attrs={"class": "form-select"}),
            "completion_year": forms.NumberInput(attrs={"class": "form-control", "min": "1950", "max": "2100"}),
            "duration": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "duration_unit": forms.Select(attrs={"class": "form-select"}),
            "completed": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "percentage_progress": forms.NumberInput(attrs={"class": "form-control", "min": "0", "max": "100"}),
            "comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter FK querysets to active records only
        self.fields["qualification"].queryset = EmisTeacherQual.objects.filter(
            active=True
        ).order_by("label")
        self.fields["major"].queryset = EmisSubject.objects.filter(
            active=True
        ).order_by("label")
        self.fields["minor"].queryset = EmisSubject.objects.filter(
            active=True
        ).order_by("label")


class TrainingRecordForm(forms.ModelForm):
    """
    Form for adding/editing training records.
    """

    class Meta:
        model = TrainingRecord
        fields = [
            "provider_institution",
            "title",
            "focus",
            "format",
            "completion_year",
            "duration",
            "duration_unit",
            "effective_date",
            "expiration_date",
        ]
        widgets = {
            "provider_institution": forms.TextInput(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={"class": "form-control", "list": "training-title-options"}),
            "focus": forms.Select(attrs={"class": "form-select"}),
            "format": forms.Select(attrs={"class": "form-select"}),
            "completion_year": forms.NumberInput(attrs={"class": "form-control", "min": "1950", "max": "2100"}),
            "duration": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "duration_unit": forms.Select(attrs={"class": "form-select"}),
            "effective_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "expiration_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter FK querysets to active records only
        self.fields["focus"].queryset = EmisTeacherPdFocus.objects.filter(
            active=True
        ).order_by("label")
        self.fields["format"].queryset = EmisTeacherPdFormat.objects.filter(
            active=True
        ).order_by("label")


# =============================================================================
# Current Teacher - School Appointment Forms
# =============================================================================


class ClaimedSchoolAppointmentForm(forms.ModelForm):
    """
    Form for current teachers to claim their school appointment.
    """

    class Meta:
        model = ClaimedSchoolAppointment
        fields = [
            "teacher_level_type",
            "current_island_station",
            "current_school",
            "start_date",
            "years_of_experience",
            "employment_position",
            "employment_status",
            "class_type",
        ]
        widgets = {
            "teacher_level_type": forms.Select(attrs={"class": "form-select", "id": "id_teacher_level_type"}),
            "current_island_station": forms.Select(attrs={"class": "form-select"}),
            "current_school": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "years_of_experience": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "employment_position": forms.Select(attrs={"class": "form-select"}),
            "employment_status": forms.Select(attrs={"class": "form-select"}),
            "class_type": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter FK querysets to active records only
        self.fields["teacher_level_type"].queryset = EmisEducationLevel.objects.filter(
            active=True
        ).order_by("label")
        self.fields["current_island_station"].queryset = EmisIsland.objects.filter(
            active=True
        ).order_by("label")
        self.fields["current_school"].queryset = EmisSchool.objects.filter(
            active=True
        ).order_by("emis_school_name")
        self.fields["employment_position"].queryset = EmisJobTitle.objects.filter(
            active=True
        ).order_by("label")
        self.fields["employment_status"].queryset = EmisTeacherStatus.objects.filter(
            active=True
        ).order_by("label")


class ClaimedDutyForm(forms.ModelForm):
    """
    Form for JSS/SSS teachers to claim their teaching duties (subjects/year levels).
    """

    class Meta:
        model = ClaimedDuty
        fields = [
            "year_level",
            "subject",
        ]
        widgets = {
            "year_level": forms.Select(attrs={"class": "form-select"}),
            "subject": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter FK querysets to active records only
        self.fields["year_level"].queryset = EmisClassLevel.objects.filter(
            active=True
        ).order_by("label")
        self.fields["subject"].queryset = EmisSubject.objects.filter(
            active=True
        ).order_by("label")


# =============================================================================
# Formsets for inline editing
# =============================================================================

# Education record formset - allows adding multiple education records
EducationRecordFormSet = inlineformset_factory(
    TeacherRegistration,
    EducationRecord,
    form=EducationRecordForm,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)

# Training record formset - allows adding multiple training records
TrainingRecordFormSet = inlineformset_factory(
    TeacherRegistration,
    TrainingRecord,
    form=TrainingRecordForm,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)

# Claimed school appointment formset - for current teachers
ClaimedSchoolAppointmentFormSet = inlineformset_factory(
    TeacherRegistration,
    ClaimedSchoolAppointment,
    form=ClaimedSchoolAppointmentForm,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)

# Claimed duty formset - nested under school appointment (for JSS/SSS teachers)
ClaimedDutyFormSet = inlineformset_factory(
    ClaimedSchoolAppointment,
    ClaimedDuty,
    form=ClaimedDutyForm,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)

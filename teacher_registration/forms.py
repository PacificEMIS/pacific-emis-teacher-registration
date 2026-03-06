"""
Forms for teacher registration.
"""

from django import forms
from django.contrib.auth import get_user_model
from django.forms import inlineformset_factory

from teacher_registration.models import (
    TeacherRegistration,
    RegistrationDocument,
    RegistrationCondition,
    EducationRecord,
    TrainingRecord,
    ClaimedSchoolAppointment,
    ClaimedDuty,
    LookupCondition,
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
    EmisTeacherRegistrationStatus,
)

User = get_user_model()


class StaffTeacherCreateForm(forms.Form):
    """
    Form for staff to initiate a registration on behalf of a teacher.

    Collects the teacher's email (required) and optional name to create
    a placeholder User and DRAFT TeacherRegistration.
    """

    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "teacher@gmail.com"}
        ),
    )
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


class TeacherRegistrationForm(forms.ModelForm):
    """
    Form for teachers to fill out their registration application.

    Includes personal information, professional details, and school preferences.
    Also allows updating the user's first/last name and email (when no Google link).
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
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
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
            # Applicant checklist (Section 7)
            "checklist_applicant_form_completed",
            "checklist_applicant_birth_cert",
            "checklist_applicant_national_id",
            "checklist_applicant_qualifications",
            "checklist_applicant_english_proficiency",
            "checklist_applicant_training_certs",
            "checklist_applicant_statutory_declaration",
            "checklist_applicant_police_clearance",
            "checklist_applicant_medical_clearance",
            "checklist_applicant_photo",
            "checklist_applicant_church_reference",
            "checklist_applicant_school_reference",
            "checklist_applicant_fee_receipt",
        ]
        widgets = {
            "teacher_category": forms.RadioSelect(attrs={"class": "form-check-input"}),
            "title": forms.Select(attrs={"class": "form-select"}),
            "date_of_birth": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "gender": forms.Select(attrs={"class": "form-select"}),
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
            # Applicant checklist checkboxes
            "checklist_applicant_form_completed": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_birth_cert": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_national_id": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_qualifications": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_english_proficiency": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_training_certs": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_statutory_declaration": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_police_clearance": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_medical_clearance": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_photo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_church_reference": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_school_reference": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_applicant_fee_receipt": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, user=None, email_editable=True, **kwargs):
        # Get initial data for first/last name and email before calling super
        instance = kwargs.get("instance")
        initial = kwargs.get("initial", {})

        # Set initial values for first_name, last_name, and email from user
        if instance and instance.pk and instance.user:
            initial.setdefault("first_name", instance.user.first_name)
            initial.setdefault("last_name", instance.user.last_name)
            initial.setdefault("email", instance.user.email)
        elif user:
            initial.setdefault("first_name", user.first_name)
            initial.setdefault("last_name", user.last_name)
            initial.setdefault("email", user.email)

        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

        # Make email read-only when User has a linked Google SocialAccount
        if not email_editable:
            self.fields["email"].disabled = True

        # Filter FK querysets to active records only
        self.fields["gender"].queryset = EmisGender.objects.filter(
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
        """Save the registration and update user's name and email."""
        instance = super().save(commit=False)

        # Always update the related User (separate model, not gated by commit)
        if instance.user:
            first_name = self.cleaned_data.get("first_name", "")
            last_name = self.cleaned_data.get("last_name", "")
            instance.user.first_name = first_name
            instance.user.last_name = last_name
            update_fields = ["first_name", "last_name"]

            # Update email+username only if field was editable (not disabled)
            if not self.fields["email"].disabled:
                email = self.cleaned_data.get("email", "")
                if email:
                    instance.user.email = email
                    instance.user.username = email
                    update_fields.extend(["email", "username"])

            instance.user.save(update_fields=update_fields)

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

    teacher_registration_status = forms.ModelChoiceField(
        queryset=EmisTeacherRegistrationStatus.objects.filter(active=True),
        required=False,
        empty_label="— Select registration status —",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Registration Status",
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
        """Require comments for rejection. Require registration status for approval."""
        cleaned_data = super().clean()
        action = cleaned_data.get("action")
        comments = cleaned_data.get("comments", "").strip()

        if action == self.ACTION_REJECT and not comments:
            raise forms.ValidationError(
                {"comments": "Please provide a reason for rejection."}
            )

        if action == self.ACTION_APPROVE and not cleaned_data.get("teacher_registration_status"):
            raise forms.ValidationError(
                {"teacher_registration_status": "Please select a registration status for approval."}
            )

        return cleaned_data


class RegistrationConditionForm(forms.ModelForm):
    """
    Form for adding a condition to a registration during review.
    """

    class Meta:
        model = RegistrationCondition
        fields = ["condition", "notes", "deadline"]
        widgets = {
            "condition": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "Optional notes about this condition",
                }
            ),
            "deadline": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                    "placeholder": "Optional deadline",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["condition"].queryset = LookupCondition.objects.filter(
            active=True
        ).order_by("label")


class ChecklistOfficialForm(forms.ModelForm):
    """
    Form for the official (reviewer) checklist fields.

    Used alongside RegistrationReviewForm on the review page.
    """

    class Meta:
        model = TeacherRegistration
        fields = [
            "checklist_official_form_completed",
            "checklist_official_birth_cert",
            "checklist_official_national_id",
            "checklist_official_qualifications",
            "checklist_official_english_proficiency",
            "checklist_official_training_certs",
            "checklist_official_statutory_declaration",
            "checklist_official_police_clearance",
            "checklist_official_medical_clearance",
            "checklist_official_photo",
            "checklist_official_church_reference",
            "checklist_official_school_reference",
            "checklist_official_fee_receipt",
            "checklist_ready_for_approval",
        ]
        widgets = {
            "checklist_official_form_completed": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_birth_cert": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_national_id": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_qualifications": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_english_proficiency": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_training_certs": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_statutory_declaration": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_police_clearance": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_medical_clearance": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_photo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_church_reference": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_school_reference": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_official_fee_receipt": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "checklist_ready_for_approval": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


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
            "major2",
            "minor",
            "minor2",
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
            "major2": forms.Select(attrs={"class": "form-select"}),
            "minor": forms.Select(attrs={"class": "form-select"}),
            "minor2": forms.Select(attrs={"class": "form-select"}),
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
        self.fields["major2"].queryset = EmisSubject.objects.filter(
            active=True
        ).order_by("label")
        self.fields["minor"].queryset = EmisSubject.objects.filter(
            active=True
        ).order_by("label")
        self.fields["minor2"].queryset = EmisSubject.objects.filter(
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
            "general_focus_area",
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
            "general_focus_area": forms.TextInput(attrs={"class": "form-control"}),
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
            "end_date",
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
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
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

        # Customize display to show only label (not "code -- label")
        self.fields["year_level"].label_from_instance = lambda obj: obj.label
        self.fields["subject"].label_from_instance = lambda obj: obj.label


class GroupedDutyForm(forms.Form):
    """
    Form for entering duties grouped by year level.

    Allows selecting one year level and multiple subjects for that level.
    This form is not bound to a model - it's used for UI convenience and
    gets expanded into individual ClaimedDuty records on save.
    """

    year_level = forms.ModelChoiceField(
        queryset=EmisClassLevel.objects.filter(active=True).order_by("label"),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Year/Class Level",
    )

    subjects = forms.ModelMultipleChoiceField(
        queryset=EmisSubject.objects.filter(active=True).order_by("label"),
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
        label="Subjects",
        help_text="Hold Ctrl (Cmd on Mac) to select multiple subjects",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Customize display to show only label
        self.fields["year_level"].label_from_instance = lambda obj: obj.label
        self.fields["subjects"].label_from_instance = lambda obj: obj.label


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

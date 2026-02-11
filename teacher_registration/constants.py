"""
Shared constants for teacher registration application statuses.

Used by both TeacherRegistration (initial application) and SchoolStaff
(renewals / ongoing registration lifecycle).
"""

# Registration application status values
DRAFT = "draft"
SUBMITTED = "submitted"
UNDER_REVIEW = "under_review"
APPROVED = "approved"
REJECTED = "rejected"
EXPIRED = "expired"

REGISTRATION_APPLICATION_STATUS_CHOICES = [
    (DRAFT, "Draft"),
    (SUBMITTED, "Submitted"),
    (UNDER_REVIEW, "Under Review"),
    (APPROVED, "Approved"),
    (REJECTED, "Rejected"),
    (EXPIRED, "Expired"),
]

# Section 7 Checklist items from the official Teacher Application Form.
# Each tuple: (field_suffix, label, category_heading_or_None, renewal_required)
#   - field_suffix: maps to model fields checklist_applicant_{suffix} / checklist_official_{suffix}
#   - label: display text for the checklist item
#   - category_heading: sub-heading to render before this item (None = same category as previous)
#   - renewal_required: True = required for both initial & renewal; False = already on file for renewals
CHECKLIST_ITEMS = [
    ("form_completed", "The form is completely filled in and signed", None, True),
    ("birth_cert", "Birth certificate or Passport biodata", "Certified copies of your", False),
    ("national_id", "National ID card", None, False),
    ("qualifications", "Qualification (certificates and transcripts)", None, False),
    ("english_proficiency", "Recent English Language Proficiency test results (if any)", None, True),
    ("training_certs", "Certificates from trainings or workshops being attended (if any)", None, True),
    ("statutory_declaration", "Statutory declaration for change in name or surname", None, False),
    ("police_clearance", "Recent Police Clearance", "Original documents", True),
    ("medical_clearance", "Recent Medical Clearance", None, True),
    ("photo", "Recent photo", None, True),
    ("church_reference", "Character Reference from your Church", None, True),
    ("school_reference", "Character reference from school leader or immediate supervisor", None, True),
    ("fee_receipt", "Registration fee receipt", None, True),
]

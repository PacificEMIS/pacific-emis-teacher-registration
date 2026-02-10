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

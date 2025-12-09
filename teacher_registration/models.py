"""
Models for the teacher_registration app.

Note: Teacher model has been moved to core.models.
Note: Student and StudentSchoolEnrolment have been removed (ported from Disability app).
Note: The PermissionsAnchor model has been removed. Access control is now handled
      by the @require_app_access decorator which checks for profile + group membership.
"""

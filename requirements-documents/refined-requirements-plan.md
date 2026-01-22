# Teacher Registration Model Refinement - Implementation Plan

## Overview

Implement comprehensive model enhancements to support the refined Teacher Registration workflow based on `requirements-documents/refined-requirements.md`. This includes new fields, new related models, document type flexibility, and approval workflow updates.

---

## Phase 1: Core Infrastructure

### 1.1 Add EducationInstitution Model (core app)

**File:** `core/models.py`
- Add `EducationInstitution` model (code PK, name, active)
- Used for autocomplete in education/training institution fields

**File:** `core/admin.py`
- Register `EducationInstitutionAdmin`

**Migration:** `core/migrations/0006_educationinstitution.py`

---

## Phase 2: TeacherRegistration Model Enhancements

**File:** `teacher_registration/models.py`

### 2.1 New Teacher Category Field
```python
teacher_category = models.CharField(choices=[NEW_TEACHER, CURRENT_TEACHER])
```
Determines form sections displayed (separate from existing `registration_type` workflow field).

### 2.2 Personal Details Additions
- `title` (choices: Mr, Mrs, Miss, Ms, Dr)
- `gender_emis` (FK to EmisGender) - new field alongside existing `gender`
- `marital_status` (FK to EmisMaritalStatus)
- `home_island` (FK to EmisIsland)

### 2.3 Contact Details Additions
- `phone_home` (CharField)
- `nearby_school` (FK to EmisSchool)
- `business_address_line_1`, `business_address_line_2`, `business_city`, `business_province`

**Migration:** `teacher_registration/migrations/0006_teacherregistration_enhancements.py`

---

## Phase 3: New Related Models

**File:** `teacher_registration/models.py`

### 3.1 EducationRecord Model
- FK to TeacherRegistration (CASCADE)
- `institution_name`, `qualification` (FK EmisTeacherQual), `program_name`
- `major` (FK EmisSubject), `minor` (FK EmisSubject, optional)
- `completion_year`, `duration`, `duration_unit`
- `comment`, `completed`, `percentage_progress`

### 3.2 TrainingRecord Model
- FK to TeacherRegistration (CASCADE)
- `provider_institution`, `title` (autocomplete from EmisTeacherPdType)
- `focus` (FK EmisTeacherPdFocus), `format` (FK EmisTeacherPdFormat)
- `completion_year`, `duration`, `duration_unit`
- `effective_date`, `expiration_date`

### 3.3 ClaimedSchoolAppointment Model (Current Teachers)
- FK to TeacherRegistration (CASCADE)
- `teacher_level_type` (FK EmisEducationLevel)
- `current_island_station` (FK EmisIsland), `current_school` (FK EmisSchool)
- `start_date` (DateField, optional) - maps to SchoolStaffAssignment.start_date on approval
- `years_of_experience`, `employment_position` (FK EmisJobTitle)
- `employment_status` (FK EmisTeacherStatus)
- `class_type` (Single-grade/Multi-grade - Primary only)

> **Approval Mapping:** ClaimedSchoolAppointment → SchoolStaffAssignment (school, job_title, start_date)

### 3.4 ClaimedDuty Model (JSS/SSS Teachers)
- FK to ClaimedSchoolAppointment (CASCADE)
- `year_level` (FK EmisClassLevel), `subject` (FK EmisSubject)

**Migration:** `teacher_registration/migrations/0007_education_training_appointment_models.py`

---

## Phase 4: RegistrationDocument Enhancement

**File:** `teacher_registration/models.py`

### 4.1 New Fields
- `docLinkType` (FK to EmisTeacherLinkType) - replaces hardcoded choices
- `docTitle` (CharField 100)
- `docDescription` (TextField, optional)
- `docDate` (DateField, optional)
- `docType` (CharField - computed file extension)

Keep existing `document_type` CharField during transition for backward compatibility.

**Migration:** `teacher_registration/migrations/0008_registrationdocument_enhancements.py`

---

## Phase 5: SchoolStaff Enhancements

**File:** `core/models.py`

### 5.1 SchoolStaff New Fields (mirror TeacherRegistration)
- `title`, `gender_emis`, `marital_status`, `home_island`
- `phone_home`, business address fields

### 5.2 StaffEducationRecord Model
- Mirrors EducationRecord structure
- FK to SchoolStaff (CASCADE)
- Created on approval from EducationRecord

### 5.3 StaffTrainingRecord Model
- Mirrors TrainingRecord structure
- FK to SchoolStaff (CASCADE)
- Created on approval from TrainingRecord

**File:** `core/admin.py`
- Add inline admins for StaffEducationRecord, StaffTrainingRecord

**Migration:** `core/migrations/0007_schoolstaff_enhancements.py`

---

## Phase 6: Approval Workflow Update

**File:** `teacher_registration/models.py`

Update `TeacherRegistration.approve()` method to:
1. Copy new personal detail fields to SchoolStaff
2. Copy EducationRecords → StaffEducationRecords (preserves original as audit trail)
3. Copy TrainingRecords → StaffTrainingRecords (preserves original as audit trail)
4. Convert ClaimedSchoolAppointments → SchoolStaffAssignments (school, job_title, start_date)
5. Move documents (existing behavior - FK swap)

**Design Decision:** Education/Training records are COPIED (not moved) to preserve the original registration as a complete audit trail of what was claimed at application time. Documents continue to MOVE via FK swap as before.

---

## Phase 7: Forms & Admin

**File:** `teacher_registration/forms.py`
- Update `TeacherRegistrationForm` with new fields
- Add `EducationRecordForm`, `TrainingRecordForm`
- Add `ClaimedSchoolAppointmentForm`, `ClaimedDutyForm`
- Create inline formsets for dynamic form handling

**File:** `teacher_registration/admin.py`
- Register `TeacherRegistrationAdmin` with inlines
- Add `EducationRecordInline`, `TrainingRecordInline`
- Add `ClaimedSchoolAppointmentInline`, `ClaimedDutyInline`

---

## Critical Files

| File | Changes |
|------|---------|
| `teacher_registration/models.py` | TeacherRegistration fields, 4 new models, RegistrationDocument fields, approve() update |
| `core/models.py` | EducationInstitution, SchoolStaff fields, StaffEducationRecord, StaffTrainingRecord |
| `core/admin.py` | EducationInstitution admin, Staff record inlines |
| `teacher_registration/forms.py` | New forms and formsets |
| `teacher_registration/admin.py` | TeacherRegistration admin with inlines |

---

## FK on_delete Strategy

- **PROTECT**: EmisTeacherQual, EmisSubject, EmisEducationLevel, EmisTeacherStatus, EmisJobTitle, EmisClassLevel, EmisSchool (for appointments), EmisTeacherLinkType
- **SET_NULL**: EmisGender, EmisMaritalStatus, EmisIsland, EmisTeacherPdFocus, EmisTeacherPdFormat (optional fields)
- **CASCADE**: Related models to their parent (EducationRecord→Registration, ClaimedDuty→Appointment, etc.)

---

## Verification

1. Run migrations: `python manage.py makemigrations` then `python manage.py migrate`
2. Test EMIS sync: `python manage.py emis_sync_lookups`
3. Django admin: Verify all new models appear with proper inlines
4. Create test registration with education/training records
5. Test approval workflow: Verify records migrate to SchoolStaff
6. Verify existing registrations still work (backward compatibility)

# Teacher Registration Model Refinement - Requirements Analysis

## Source Documents

Two Word documents in `requirements-documents/` (this folder):
1. **Current Teacher Application Form.docx** - For teachers already employed/teaching
2. **New Teacher Application form.docx** - For teachers entering the profession

The main difference: **Current Teachers** have an additional **Section 4: Teaching Details** capturing current school assignment, teaching levels, and subjects taught.

---

## Extracted Data Fields by Section

### SECTION 1: PERSONAL DETAILS (Both Forms)

| Field | Current Model Status |
|-------|---------------------|
| Full Name (Official) | Via Django User (first_name, last_name) |
| National ID | ✅ `national_id_number` |
| Title (Mr/Mrs/Miss/etc) | ❌ Missing |
| Gender | ✅ `gender` → will use FK to `EmisGender` |
| Date of Birth | ✅ `date_of_birth` |
| Marital Status | ❌ Missing → will use FK to `EmisMaritalStatus` |
| Home Island | ❌ Missing → will add FK to `EmisIsland` |
| Passport Photo | Via `RegistrationDocument` → type will be FK to `EmisTeacherLinkType` |

### SECTION 2: CONTACT DETAILS (Both Forms)

| Field | Current Model Status |
|-------|---------------------|
| Telephone (Home) | ❌ Missing (have `phone_number` but single field) |
| Mobile | ✅ Partially (`phone_number`) |
| Email Address | Via Django User |
| Nearby School | ❌ Missing → will add FK to `EmisSchool` (replaces School ID Code + School Name) |
| Residential Address | ✅ Partially (`address_line_1`, `address_line_2`, `city`, `province`) |
| Business Address | ❌ Missing → will add (optional) |

### SECTION 3: EDUCATION AND TRAINING BACKGROUND (Both Forms)

**Education** (multiple entries):
| Field | Current Model Status |
|-------|---------------------|
| School Name / Institution | ❌ Missing → autocomplete from `EducationInstitution` (new model in core: code, name) with free-form fallback |
| Qualification Attained | ❌ Missing → will add FK to `EmisTeacherQual` (replaces `highest_qualification` single field) |
| Program | ❌ Missing |
| Major | ❌ Missing → will add FK to `EmisSubject` |
| Minor | ❌ Missing → will add FK to `EmisSubject` (optional) |
| Completion Year | ❌ Missing → will add |
| Duration | ❌ Missing → will add |
| Duration Unit | ❌ Missing → will add (choices: Hours, Days, Weeks, Months, Years; default: Years) |
| Comment | ❌ Missing → will add (optional) |
| Completed | ❌ Missing → will add (Yes/No) |
| Percentage Progress | ❌ Missing → will add (only shown if Completed is No) |

**Training** (multiple entries, note to user in UI "MAT-PD training and other workshops"):
| Field | Current Model Status |
|-------|---------------------|
| Training Provider/Institution | ❌ Missing → autocomplete from `EducationInstitution` (new model in core: code, name) with free-form fallback |
| Title | ❌ Missing → autocomplete from `EmisTeacherPdType` with free-form fallback |
| Focus | ❌ Missing → will add FK to `EmisTeacherPdFocus` (optional)|
| Format | ❌ Missing → will add FK to `EmisTeacherPdFormat` (optional) |
| Completion Year | ❌ Missing → will add |
| Duration of Training | ❌ Missing → will add |
| Duration Unit | ❌ Missing → will add (choices: Hours, Days, Weeks, Months, Years; default: Days) |
| Effective Date | ❌ Missing → will add |
| Expiration Date | ❌ Missing → will add (optional) |

### SECTION 4: TEACHING DETAILS (Current Teachers Only)

**Claimed School Appointment** (Primary, JSS, SSS):
| Field | Current Model Status |
|-------|---------------------|
| Teacher Level Type | ❌ Missing → will add FK to `EmisEducationLevel` |
| Current Island Station | ❌ Missing → will add FK to `EmisIsland` |
| Current School | ❌ Missing → will add FK to `EmisSchool` (replaces School Code + School Name) |
| Teaching Experience (Years) | ✅ `years_of_experience` |
| Employment Position | ❌ Missing → will add FK to `EmisJobTitle` |
| Employment Status | ❌ Missing → will add FK to `EmisTeacherStatus` |
| Type of Class Taught (Primary only) | ❌ Missing → will add (choices: Single-grade, Multi-grade) |

**Claimed Duties** (JSS/SSS - multiple entries, new model `ClaimedDuty`):
| Field | Current Model Status |
|-------|---------------------|
| School | Auto-populated from Current School in Teaching Details |
| Year Level | ❌ Missing → will add FK to `EmisClassLevel` (single select) |
| Subject | ❌ Missing → will add FK to `EmisSubject` (single select) |

### SECTION 5/6: REQUIRED DOCUMENTS (Both Forms)

All document types will be managed via FK to `EmisTeacherLinkType` (synced from EMIS core API `teacherLinkTypes`).

| Document Type | Design |
|---------------|--------|
| Birth Certificate or Passport Biodata | FK to `EmisTeacherLinkType` |
| National ID Card | FK to `EmisTeacherLinkType` |
| Certificates with Transcripts | FK to `EmisTeacherLinkType` |
| English Language Proficiency Test | FK to `EmisTeacherLinkType` |
| Training/Workshop Certificates | FK to `EmisTeacherLinkType` |
| Statutory Declaration (name change) | FK to `EmisTeacherLinkType` |
| Police Clearance | FK to `EmisTeacherLinkType` |
| Medical Clearance | FK to `EmisTeacherLinkType` |
| Photo | FK to `EmisTeacherLinkType` |
| Church Character Reference | FK to `EmisTeacherLinkType` |
| School Leader/Supervisor Reference | FK to `EmisTeacherLinkType` |
| Registration Fee Receipt | FK to `EmisTeacherLinkType` |

---

## Current EMIS Integration Points

From `integrations/models.py` (all synced via `emis_sync_lookups` management command from EMIS Core API `/api/lookups/collection/core`):

**Original Models:**
- **EmisSchool** - Schools (from `schoolCodes`) - Used for nearby school, current school, preferred school
- **EmisClassLevel** - Class/Year levels (from `levels`) - Used for year levels in Claimed Duties
- **EmisJobTitle** - Teacher roles/job titles (from `teacherRoles`) - Used for employment position
- **EmisWarehouseYear** - School years (from `warehouseYears`)

**New Models Added:**
- **EmisSubject** - Subjects/curriculum areas (from `subjects`) - Used for major/minor in Education, subject in Claimed Duties
- **EmisTeacherQual** - Teacher qualifications (from `teacherQuals`) - Used for qualification attained in Education
- **EmisMaritalStatus** - Marital status options (from `maritalStatus`) - Used in personal details
- **EmisIsland** - Islands/districts (from `islands`) - Used for home island, current island station
- **EmisTeacherStatus** - Teacher registration status (from `teacherRegStatus`) - Used for employment status
- **EmisEducationLevel** - Education levels (from `educationLevels`) - Used for teacher level type (Primary/JSS/SSS)
- **EmisTeacherLinkType** - Document/link types (from `teacherLinkTypes`) - Used for document categories in RegistrationDocument
- **EmisGender** - Gender options (from `gender`) - Used for gender in personal details
- **EmisTeacherPdFocus** - PD focus areas (from `teacherPdFocuses`) - Used for training focus
- **EmisTeacherPdFormat** - PD formats (from `teacherPdFormats`) - Used for training format
- **EmisTeacherPdType** - PD types (from `teacherPdTypes`) - Used for training title autocomplete

---

## Proposed Approach

### 1. Registration Type Field

Add a `registration_type` field with tuple choices to record how the teacher self-registered. This field:
- Determines which form sections to display (New Teacher vs Current Teacher)
- Serves as a historical record of the teacher's initial registration path

```python
REGISTRATION_TYPE_CHOICES = [
    ('NEW_TEACHER', 'New Teacher'),       # Simpler form - no Section 4 (Teaching Details)
    ('CURRENT_TEACHER', 'Current Teacher'), # Full form - includes Section 4 (Teaching Details)
]
registration_type = models.CharField(max_length=20, choices=REGISTRATION_TYPE_CHOICES)
```

### 2. New Models Required

**A. `EducationRecord`** (Many-to-One with TeacherRegistration)
```
- institution_name (autocomplete from EducationInstitution with free-form fallback)
- qualification (FK to EmisTeacherQual)
- program_name (CharField)
- major (FK to EmisSubject)
- minor (FK to EmisSubject, optional)
- completion_year (IntegerField)
- duration (IntegerField)
- duration_unit (choices: Hours, Days, Weeks, Months, Years; default: Years)
- comment (TextField, optional)
- completed (BooleanField)
- percentage_progress (IntegerField, only shown if completed is False)
```

**B. `TrainingRecord`** (Many-to-One with TeacherRegistration)
```
- provider_institution (autocomplete from EducationInstitution with free-form fallback)
- title (autocomplete from EmisTeacherPdType with free-form fallback)
- focus (FK to EmisTeacherPdFocus, optional)
- format (FK to EmisTeacherPdFormat, optional)
- completion_year (IntegerField)
- duration (IntegerField)
- duration_unit (choices: Hours, Days, Weeks, Months, Years; default: Days)
- effective_date (DateField)
- expiration_date (DateField, optional)
```

**C. `ClaimedSchoolAppointment`** (Many-to-One with TeacherRegistration) - For Current Teachers
```
- teacher_level_type (FK to EmisEducationLevel) - Primary/JSS/SSS
- current_island_station (FK to EmisIsland)
- current_school (FK to EmisSchool)
- years_of_experience (IntegerField)
- employment_position (FK to EmisJobTitle)
- employment_status (FK to EmisTeacherStatus)
- class_type (choices: Single-grade, Multi-grade; Primary only)
```

**D. `ClaimedDuty`** (Many-to-One with ClaimedSchoolAppointment) - For JSS/SSS Teachers
```
- school (FK to EmisSchool, auto-populated from parent ClaimedSchoolAppointment)
- year_level (FK to EmisClassLevel)
- subject (FK to EmisSubject)
```

**E. `EducationInstitution`** (New model in core app)
```
- code (CharField, primary key)
- name (CharField)
- active (BooleanField)
```

### 3. TeacherRegistration Model Enhancements

**Personal Details additions:**
- `title` (choices: Mr, Mrs, Miss, Ms, Dr, etc.)
- `gender` (FK to EmisGender) - update existing field
- `marital_status` (FK to EmisMaritalStatus)
- `home_island` (FK to EmisIsland)

**Contact Details additions:**
- `phone_home` (CharField, rename current `phone_number` to `phone_mobile`)
- `nearby_school` (FK to EmisSchool)
- `business_address_line_1` (CharField, optional)
- `business_address_line_2` (CharField, optional)
- `business_city` (CharField, optional)
- `business_province` (CharField, optional)

**Remove/Repurpose:**
- `preferred_school` → keep for New Teachers only (but is current and not preferred)
- `preferred_job_title` → keep for New Teachers only (but is current and not preferred)
- `highest_qualification` → remove (derived from EducationRecord entries)
- Teaching details fields moved to `ClaimedSchoolAppointment` model

### 4. RegistrationDocument Model Enhancement

The `RegistrationDocument` model will be enhanced with the following fields:

```
- docTitle (CharField 100) - Document title
- docDescription (TextField, optional) - Document description
- docDate (DateField, optional) - Document date (e.g., issue date)
- docTags (CharField 400, optional) - Comma-separated tags
- docType (CharField 100) - Computed File type (e.g., PDF, JPG, PNG)
- docLinkType (FK to EmisTeacherLinkType) - Document category/type
```

Document types will be managed via `EmisTeacherLinkType` (synced from EMIS core API `teacherLinkTypes`) rather than hardcoded choices. This allows the MOE to manage document types centrally in EMIS.

In the UI, there will be a pre-defined list of Upload slots for all required documents just like in the word document. the pre-defined list will have the type automatically set (shown as read-onlly) And after that a place where user can upload additional documents (the free form upload will require the user to select a document type).

**Required document types to add to EMIS `teacherLinkTypes`:**
1. National ID
2. Birth Certificate / Passport Biodata
3. Marriage Certificate
4. Academic Certificate/Transcript
5. Teaching Certificate/Transcript
6. Statement of Results
7. Photo/Passport Photo
8. English Language Proficiency Test
9. Training/Workshop Certificate
10. Statutory Declaration (Name Change)
11. Police Clearance
12. Medical Clearance
13. Church Character Reference
14. School Leader/Supervisor Reference
15. Registration Fee Receipt

### 5. Form Workflow

The form UI should adapt based on registration type:
- **New Teacher**: Sections 1, 2, 3, Documents, Declaration
- **Current Teacher**: Sections 1, 2, 3, 4 (Teaching Details), Documents, Declaration

### 6. Validation Rules

Validation should be more like user notes in the UI rather than hard capture validation at this point.

- Police clearance must be < 6 months old
- Medical clearance must be < 6 months (current) or < 1 month (new)
- Photo must be recent
- At least one education record required
- For Current Teachers: current school and teaching details required

---

## Questions for Discussion

1. **Home Island** - ✅ RESOLVED: Uses FK to `EmisIsland` (synced from EMIS Core API `islands`).

2. **Subjects** - ✅ RESOLVED: Uses FK to `EmisSubject` (synced from EMIS Core API `subjects`). Used for major/minor in Education records and subject in Claimed Duties.

3. **Document Expiry Tracking** - ✅ RESOLVED: No. Document expiry will be part of the registration lifecycle, not tracked on individual documents.

4. **Fee Receipt** - ✅ RESOLVED: No payment system integration. Simple receipt scan uploaded as a document.

5. **Renewal vs Current Teacher** - ✅ RESOLVED: Do not modify existing registration types. The "New Teacher vs Current Teacher" distinction is a separate field for form display logic only, not related to the existing registration_type workflow statuses.

6. **SchoolStaff Integration** - ✅ RESOLVED: Yes. Education records and training records will be moved to SchoolStaff on approval (like documents). SchoolStaff becomes the official "source of truth" for the teacher's verified data, while TeacherRegistration remains as the historical application/intake record. This means SchoolStaff will need related models (StaffEducationRecord, StaffTrainingRecord) for the official lifecycle management.

---

## Raw Form Content Reference

### Current Teacher Application Form - Tables

**Table 1: Personal Details**
- Full Name (Official) → via Django User (first_name, last_name)
- National ID → `national_id_number`
- Title → `title` (Mr/Mrs/Miss/Ms/Dr choices)
- Gender → `gender` (FK to EmisGender)
- Date of Birth (DD/MM/YYYY) → `date_of_birth`
- Marital Status → `marital_status` (FK to EmisMaritalStatus)
- Home Island → `home_island` (FK to EmisIsland)

**Table 2: Contact Details**
- Telephone (Home) → `phone_home`
- Mobile → `phone_mobile`
- Email Address → via Django User
- School ID / School Name → `nearby_school` (FK to EmisSchool)
- Residential Address → existing address fields
- *(Added)* Business Address → optional business address fields

**Table 3: Education** *(becomes EducationRecord model - multiple entries)*
- School Name / Institution → `institution_name` (autocomplete with free-form)
- Highest Qualification attained → `qualification` (FK to EmisTeacherQual)
- Program → `program_name`
- Major → `major` (FK to EmisSubject)
- Minor → `minor` (FK to EmisSubject, optional)
- Completion Year → `completion_year`
- *(Added)* Duration → `duration`
- *(Added)* Duration Unit → `duration_unit` (Hours/Days/Weeks/Months/Years)
- *(Added)* Comment → `comment` (optional)
- *(Added)* Completed → `completed` (Yes/No)
- *(Added)* Percentage Progress → `percentage_progress` (if not completed)

**Table 4: Training** *(becomes TrainingRecord model - multiple entries)*
- Training Provider/Institution → `provider_institution` (autocomplete with free-form)
- Continuous Professional Development Title → `title` (autocomplete from EmisTeacherPdType with free-form)
- Duration of Training → `duration`
- *(Added)* Duration Unit → `duration_unit` (Hours/Days/Weeks/Months/Years)
- *(Added)* Focus → `focus` (FK to EmisTeacherPdFocus, optional)
- *(Added)* Format → `format` (FK to EmisTeacherPdFormat, optional)
- *(Added)* Effective Date → `effective_date`
- *(Added)* Expiration Date → `expiration_date` (optional)

**Table 5: Teacher Level Selection**
- Primary Teacher → Go to (i)
- JSS Teacher → Go to (ii)
- SSS Teacher → Go to (iii)

> **UI DESIGN NOTE:** Unlike the paper form which has three separate sections (i, ii, iii), our digital form will use a **single unified section** with conditional field visibility based on the selected Teacher Level Type:
> - **All levels**: Current Island Station, Current School, Teaching Experience, Employment Position, Employment Status
> - **Primary only**: Type of Class Taught (Single-grade/Multi-grade)
> - **JSS/SSS only**: Claimed Duties section (Year Level + Subject combinations)

**Table 6: Primary Teacher Details** *(merged into ClaimedSchoolAppointment model)*
- Current Island Station → `current_island_station` (FK to EmisIsland)
- School Code / School Name → `current_school` (FK to EmisSchool)
- ~~Year Level Teach~~ → *(removed - not applicable for Primary)*
- Teaching Experience (No. of Years) → `years_of_experience`
- Employment Position → `employment_position` (FK to EmisJobTitle)
- Employment Status → `employment_status` (FK to EmisTeacherStatus)
- Type of Class Taught → `class_type` (Single-grade/Multi-grade) *(Primary only)*

**Table 7: JSS Teacher Details** *(merged into ClaimedSchoolAppointment model)*
- Current Island Station → `current_island_station` (FK to EmisIsland)
- School Code / School Name → `current_school` (FK to EmisSchool)
- ~~Year Level Teach~~ → *(removed - captured via ClaimedDuty)*
- Teaching Experience (No. of Years) → `years_of_experience`
- Employment Position → `employment_position` (FK to EmisJobTitle)
- Employment Status → `employment_status` (FK to EmisTeacherStatus)

**Table 8: JSS Subjects Taught** *(becomes ClaimedDuty model - multiple entries)*
- Year Level → `year_level` (FK to EmisClassLevel)
- Subject → `subject` (FK to EmisSubject)

**Table 9: SSS Teacher Details** *(merged into ClaimedSchoolAppointment model)*
- Current Island Station → `current_island_station` (FK to EmisIsland)
- School Code / School Name → `current_school` (FK to EmisSchool)
- ~~Year Level Teach~~ → *(removed - captured via ClaimedDuty)*
- Teaching Experience (No. of Years) → `years_of_experience`
- Employment Position → `employment_position` (FK to EmisJobTitle)
- Employment Status → `employment_status` (FK to EmisTeacherStatus)

**Table 10: SSS Subjects Taught** *(becomes ClaimedDuty model - multiple entries)*
- Year Level → `year_level` (FK to EmisClassLevel)
- Subject → `subject` (FK to EmisSubject)

**Table 11: Checklist**
- Form completely filled and signed
- Certified copies: Birth certificate/Passport, National ID, Qualifications, English proficiency, Training certificates, Statutory declaration
- Original documents: Police Clearance, Medical Clearance, Photo, Church Reference, Supervisor Reference, Fee Receipt

### New Teacher Application Form - Tables

**Table 1: Personal Details** (same as Current Teacher)

**Table 2: Contact Details** (same as Current Teacher)

**Table 3: Education** (same as Current Teacher)

**Table 4: Training** (same as Current Teacher)

**Table 5: Checklist** (similar to Current Teacher, slightly different structure)

---

## Notes

- The New Teacher form does NOT have Section 4 (Teaching Details) since they are not yet employed
- Both forms require the same documents, but medical clearance validity differs (6 months vs 1 month)
- The statutory declaration form is for teachers who have changed their name
- Church reference must come from Pastor, Catechist, Minister, etc.

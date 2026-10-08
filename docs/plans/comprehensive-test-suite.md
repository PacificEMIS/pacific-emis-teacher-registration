# Comprehensive test suite (issue #112)

## Background

The project has no automated tests and no CI. Regressions are caught only by
manual testing. The highest-risk areas are:

- the registration state machine and `approve()` in
  [teacher_registration/models.py](../../teacher_registration/models.py)
- the role and school-scoping predicates in
  [core/permissions.py](../../core/permissions.py)
- the two large view modules, where a template or decorator change silently
  breaks a page

External edges that tests must isolate: PostgreSQL, the EMIS REST API, SMTP
(sent from background threads), Google OAuth via allauth, WeasyPrint PDFs, and
four management commands.

## Safety

The suite is purely additive. No application code changes in any phase.

- Django creates a throwaway `test_<PG_NAME>` database per run and drops it.
  Development data is never touched.
- [settings_test.py](../../pacemis_teacher_registration/settings_test.py)
  redirects uploads to a temporary directory, uses the in-memory email backend,
  points the EMIS client at an unreachable host, and uses fast password hashing.
- Tests mock the EMIS client and run async email wrappers inline.

If a test exposes a real bug, the fix is a separate reviewed commit, never
bundled into a test PR.

## Conventions

- pytest with pytest-django. Tests live in `<app>/tests/` packages, one
  `test_<topic>.py` per concern.
- Factories (factory-boy) live in `<app>/tests/factories.py`; shared fixtures
  in the root `conftest.py` and per-app `tests/conftest.py`.
- PostgreSQL is the test engine, matching production. Do not swap to SQLite.
- Markers: `pdf` for tests needing WeasyPrint native libraries.
- CI runs on every PR: system checks, migration drift check, requirements.txt
  sync check, and the test suite with coverage.

## Phases

Each phase is a small, independently reviewable PR.

0. **Harness** (done): dev deps, pytest config, test settings, root
   `conftest.py`, empty `tests/` packages, smoke tests, GitHub Actions.
1. **Pure unit tests**: registration number generation and check digit,
   `compute_valid_until`, `core/dateformat`, template filters, upload path,
   badge class, and the full permissions matrix (every predicate against every
   role, including school scoping).
2. **Factories and workflow tests**: factories for users per group,
   SchoolStaff, SystemUser, EMIS lookups, registrations in each status,
   documents and records. Every valid transition writes a change-log row;
   every invalid transition raises. `approve()` end to end: staff created,
   records copied, appointments converted, documents moved, national ID
   required, duplicates rejected. Renewal approval, rejection, resubmission.
3. **Access-control matrix and page smoke**: table-driven over every URL in
   the three `urls.py` files. Anonymous redirects to login; each role gets the
   expected 200, 302 or 403. Every page renders for an authorised role.
4. **End-to-end flows through the test client**: teacher create, edit,
   upload, submit. Reviewer start review, toggle ready, approve. Renewal.
   Staff registering on behalf. Pending user assignment. Rejection and
   resubmission.
5. **Forms**: validation rules in `teacher_registration/forms.py`, especially
   conditional requirements by registration type and category.
6. **Edges**: emails via the outbox (subject, recipients, links). Management
   commands, with `check_expired_registrations` under time travel and
   `emis_sync_lookups` fed a recorded JSON payload. `EmisClient` token caching
   and failures via requests-mock. The allauth adapter with a fake social
   login. Certificate and report PDFs by header and page count.
7. **Admin smoke**: changelist and add page for every registered ModelAdmin.
8. **Coverage ratchet**: record measured coverage and fail CI if it drops.
   Optionally a handful of Playwright browser journeys.

## Known findings to fix separately

- `teacher_registration/admin.py`: `TeacherRegistrationAdmin` fieldsets still
  list `address_line_1`, `address_line_2`, `city`, `province` and the
  `business_*` equivalents, which were removed from the model. The admin add
  and change pages for registrations raise `FieldError` (HTTP 500). Tracked
  by strict `xfail` markers in `core/tests/test_admin.py`.
- `core/management/commands/seed_groups.py` lists `core.add_teacher`,
  `core.change_teacher`, `core.delete_teacher` and `core.view_teacher`, but
  there is no `core.Teacher` model, so every run warns "Permission not
  found". Tracked by a strict `xfail` in `core/tests/test_commands.py`.
- `teacher_registration/views.py`: `registration_renew()` and
  `teacher_renew_on_behalf()` copy `SchoolStaffAssignment.teacher_level_type`
  (nullable) into `ClaimedSchoolAppointment.teacher_level_type` (NOT NULL).
  A teacher whose assignment was added through the staff membership form in
  `core`, which has no level-type field, gets a 500 instead of a renewal.
  Tracked by a strict `xfail` in `teacher_registration/tests/test_flows.py`.
- `teacher_registration/views.py`: the `@login_required` intended for
  `document_upload()` sits on the `_is_ajax()` helper defined just above it.
  Anonymous requests still get a 403 from the owner check, so nothing leaks,
  but they should get a login redirect, and `_is_ajax()` would return a
  redirect response instead of a bool if it were ever called for an anonymous
  request. Tracked by a strict `xfail` in `core/tests/test_access_matrix.py`.
- `teacher_registration/utils.py`: `validate_registration_number()` can never
  return True. It requires 12 characters and a 4-character hash, but
  `TR` + `YY` + `-` + 4 + `-` + 1 is 11 characters. Separately,
  `generate_teacher_registration_number()` emits a 6 or 7 character hash
  (base36 of a 32-bit value), not the 4 the docstring example `TR26-A7K9-C`
  shows. The validator is not called anywhere yet, so the bug is latent.
  Tracked by strict `xfail` markers in
  `teacher_registration/tests/test_utils.py`; remove them when fixed.
- `teacher_registration/models.py` (lines 1061 and 1697) uses
  `CheckConstraint(check=...)`, which
  Django 5.1 deprecated in favour of `condition=`. Removed in Django 6.0.

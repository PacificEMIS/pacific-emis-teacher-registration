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
- Known bugs are pinned with `pytest.mark.xfail(strict=True)` and listed under
  "Known findings" below. When a bug is fixed its test XPASSes and the run
  fails until the marker is removed, so the list cannot go stale.
- `core/tests/test_access_matrix.py` fails when a URL is added without a row
  in the matrix, so every new view gets an access-control expectation.
- A pre-push hook in `.pre-commit-config.yaml` runs the local gate before every
  push: system checks, migration drift check, and the test suite with coverage.
  There is deliberately no hosted CI; the project stays vendor-neutral.

## Phases

Each phase is a small, independently reviewable PR.

0. **Harness** (done): dev deps, pytest config, test settings, root
   `conftest.py`, empty `tests/` packages, smoke tests, pre-push hook.
1. **Pure unit tests** (done): registration number generation and check digit,
   `compute_valid_until`, `core/dateformat`, template filters, upload path,
   badge class, and the full permissions matrix (every predicate against every
   role, including school scoping).
2. **Factories and workflow tests** (done): factories for users per group,
   SchoolStaff, SystemUser, EMIS lookups, registrations in each status,
   documents and records. Every valid transition writes a change-log row;
   every invalid transition raises. `approve()` end to end: staff created,
   records copied, appointments converted, documents moved, national ID
   required, duplicates rejected. Renewal approval, rejection, resubmission.
3. **Access-control matrix and page smoke** (done): table-driven over every URL in
   the three `urls.py` files. Anonymous redirects to login; each role gets the
   expected 200, 302 or 403. Every page renders for an authorised role.
4. **End-to-end flows through the test client** (done): teacher create, edit,
   upload, submit. Reviewer start review, toggle ready, approve. Renewal.
   Staff registering on behalf. Pending user assignment. Rejection and
   resubmission.
5. **Forms** (done): validation rules in `teacher_registration/forms.py`, especially
   conditional requirements by registration type and category.
6. **Edges** (done): emails via the outbox (subject, recipients, links). Management
   commands, with `check_expired_registrations` under time travel and
   `emis_sync_lookups` fed a recorded JSON payload. `EmisClient` token caching
   and failures via requests-mock. The allauth adapter with a fake social
   login. Certificate and report PDFs by header and page count.
7. **Admin smoke** (done): changelist and add page for every registered ModelAdmin.
8. **Coverage ratchet** (done): `fail_under = 90` in `pyproject.toml`
   (`[tool.coverage.report]`); measured 93% on completion. Raise the floor as
   coverage grows. Browser journeys with Playwright remain optional future work.

## Known findings to fix separately

None open. The six findings surfaced while building the suite were each fixed
in their own commit on the same branch (admin fieldsets, stale seed_groups
permissions, CheckConstraint argument, document_upload login decorator,
registration number validator, required education level on staff
assignments).

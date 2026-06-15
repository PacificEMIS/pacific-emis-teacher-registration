# Plan: Restore `current_island_station` & `years_of_experience` on staff assignments (with historical backfill)

Status: **Proposed / not started** · Drafted 2026-06

## Goal

Bring two appointment-level fields that are currently dropped at approval back
onto the staff side, and backfill existing `SchoolStaffAssignment` rows from the
historical registration data that still exists.

The fields (present on `ClaimedSchoolAppointment`, absent on
`SchoolStaffAssignment`):

- `current_island_station` (FK to `EmisIsland`)
- `years_of_experience` (PositiveIntegerField)

Each field is independent — we may choose to restore only one. Note
`years_of_experience` at the *appointment* level is debatable (it overlaps with
`SchoolStaff.years_of_experience`, the teacher's total); `current_island_station`
is partly implied by the school but useful to have explicit. Decide per field.

## Background — why this is possible

At approval, `TeacherRegistration.approve()` **copies** appointment data into new
`SchoolStaffAssignment` rows and leaves the source `ClaimedSchoolAppointment`
rows intact (it appends; it never deletes registration history). So the original
values still live on `ClaimedSchoolAppointment` in `staff.registration_history`.

There is **no FK link** from `SchoolStaffAssignment` back to its source
`ClaimedSchoolAppointment`, so historical backfill must match heuristically.

This mirrors the `employment_status` change already shipped (core migration
`0028`) — follow that as the template.

## Part 1 — Capture the data going forward (do this first)

So new approvals/renewals stop losing it and any future backfill only has to
cover the pre-change tail.

1. **Model** — add the field(s) to `SchoolStaffAssignment` (`core/models.py`),
   mirroring the `ClaimedSchoolAppointment` definitions (both nullable). Generate
   a migration (`makemigrations core`); the user runs `migrate`.
2. **Copy at approval** — in `TeacherRegistration.approve()` and
   `_approve_renewal()` (`teacher_registration/models.py`), add the field(s) to
   the `SchoolStaffAssignment.objects.create(...)` calls (same spot as
   `employment_status`).
3. **Renewal pre-fill** — in `teacher_renew_on_behalf` and `registration_renew`
   (`teacher_registration/views.py`), copy the field(s) back staff → registration
   so the round-trip preserves them. Update the "registration-only fields left
   blank" comment.
4. **Form + display** — add the field(s) to `StaffAssignmentForm`
   (`teacher_registration/forms.py`, with active-only queryset filtering for the
   island FK) and surface them in the assignments table on
   `teacher_detail.html`.

### Recommended: add a traceability link

Add `source_claimed_appointment` (nullable FK to `ClaimedSchoolAppointment`) on
`SchoolStaffAssignment`, set in `approve()`/`_approve_renewal()` going forward.
This makes *all future* backfills/audits exact and removes the heuristic-matching
problem for anything approved after this change. It does **not** help historical
rows (they pre-date the link), but it's cheap insurance.

## Part 2 — Backfill historical rows

A management command, e.g. `backfill_assignment_fields`.

### Matching strategy (per assignment)

1. `teacher = assignment.school_staff`.
2. Collect candidate `ClaimedSchoolAppointment`s across
   `teacher.registration_history`. **Prefer the earliest (initial) registration
   whose appointment has a non-null value** — see the renewal gotcha below.
3. Match on `teacher + (school == current_school, job_title ==
   employment_position, teacher_level_type, start_date)`.
4. Outcome:
   - exactly one confident match with non-null source value → fill (only if the
     assignment field is currently null — idempotent).
   - zero matches, or value null everywhere → skip, log as "no source data".
   - more than one match → skip, log as "ambiguous" (never guess).

### The renewal gotcha (must handle)

For renewed teachers, current assignments were delete-and-recreated from the
**renewal** registration, whose pre-fill left these fields blank. The real data
only lives on the **initial** registration's appointments. So the matcher must
search all registrations (earliest-first) for a non-null value — not just the
latest — and accept that the current posting may not line up with the initial
one if it changed between initial and renewal.

### Won't match (expected, acceptable)

- Assignments **added manually** post-approval (no source appointment).
- Assignments **edited** since approval (school/title/level/start_date changed)
  so the match key no longer lines up.

These should be **logged, not silently skipped**.

### Command requirements

- `--dry-run` (default to dry-run; require an explicit flag to write).
- `--fields island,years` to choose which field(s).
- optional `--teacher <registration_number>` to scope to one teacher for testing.
- End-of-run **report**: counts of filled / skipped-no-data / ambiguous /
  unmatched, and a per-row listing for the non-fills so they can be eyeballed.
- Idempotent (only fills nulls); safe to re-run.
- Per-row or batched saves inside `transaction.atomic()`.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Heuristic match picks the wrong appointment | Require a single confident match; log ambiguous, never guess |
| Renewed teachers' data only on initial reg | Search registrations earliest-first for non-null value |
| Edited/manual assignments unmatched | Expected; log them in the report |
| Silent under-coverage reads as "done" | Report must show what was skipped and why |

## Testing

- Unit tests for the matcher with fixtures: initial-only teacher, renewed
  teacher, ambiguous (two same-school appointments), manually-added assignment,
  already-filled (idempotency).
- Run `--dry-run` against a copy of production data and review the report before
  any real write.

## Suggested order

1. Part 1 (fields + migration + copy-forward + form/display). Ship & verify.
2. (Optional, recommended) `source_claimed_appointment` FK set at approval.
3. Backfill command with `--dry-run` + report.
4. Review the dry-run report, then run for real (per field, per scope as needed).

## Key references

- `TeacherRegistration.approve()` / `_approve_renewal()` — `teacher_registration/models.py`
- Renewal pre-fill — `teacher_renew_on_behalf`, `registration_renew` in `teacher_registration/views.py`
- Prior analogous change — `employment_status` (core migration `0028`)
- `StaffAssignmentForm` — `teacher_registration/forms.py`
- Assignments display — `teacher_registration/templates/teacher_registration/teacher_detail.html`

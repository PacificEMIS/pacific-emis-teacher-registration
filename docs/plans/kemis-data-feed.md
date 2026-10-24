# KEMIS data feed (issue #119)

Expose this application's data so the central KEMIS (the pineapples repository: ASP.NET API,
SQL Server warehouse and the AngularJS client with its dashboards) can pull it, store it in its
warehouse and show it in a dashboard alongside the census data.

This document is the contract between the two sides. Section 2 is the only part the KEMIS
side depends on; keep it stable once both sides start building. Sections 3 and 4 are the
work plans for each side.

## 1. Architecture

```
pacific-emis-teacher-registration (Django, PostgreSQL, Linux host)
  warehouse.* views  ->  /api/warehouse/...  (read-only JSON/CSV, bearer key)
                                  |
                                  |  HTTPS pull, scheduled + on demand
                                  v
pineapples (ASP.NET, SQL Server, Windows host)
  staging tables  ->  warehouse.buildTeacherRegistration  ->  warehouse.TeacherRegistration* views
                  ->  api/warehouse/teacherregistration/...
                  ->  Pineapples.Client crossfilter dashboard (Teachers -> Dashboards -> Registration)
```

Design decisions, with reasons:

- **Pull, not push.** Pineapples has no ingest endpoint for external systems, and this app is
  already a public HTTPS site. A read-only, token-protected API is the smallest surface.
- **Registration facts land in the SQL Server warehouse.** That is where they can be joined to
  the school dimension (district, island, authority, school type) and to census teacher counts,
  and where every other dashboard already reads from.
- **No teacher record matching yet.** The feed carries no names, national IDs or birth dates.
  Teacher-grain rows are keyed by registration number and carry school code, gender, birth year
  and home island, which is enough for every planned chart. Matching to KEMIS tID is a later,
  separate piece of work.
- **Audit at snapshot grain.** "Who did what, when, and last" from the created/last-updated
  fields on every record, compiled into one feed. Full history exists only for registration
  status transitions (the change log), which is also exposed. No per-field history is planned.

## 2. API contract (provider: this app)

### 2.1 Access

- Base path: `/api/warehouse/` on the application host.
  Production: `https://kemis-registration.moe.gov.ki/api/warehouse/`.
  Local development: `http://lvh.me:8001/api/warehouse/`.
- Authentication: `Authorization: Bearer <key>` on every request. Missing or unknown key
  returns `401` with `{"detail": "..."}`. There are no sessions, cookies or CSRF.
- Keys are configured on the provider in the environment variable `WAREHOUSE_API_KEYS`
  (comma-separated, so a key can be rotated by adding the new one before removing the old).
  Local development key: `dev-local-key`.
- All responses are JSON, UTF-8. List endpoints also accept `?format=csv`.
- Datetimes are ISO 8601 in UTC with a `Z` suffix. Dates are `YYYY-MM-DD`. Months are `YYYY-MM`.
- Nulls are emitted as JSON `null`, never as empty strings, for non-text fields.
- Codes come first, labels second. Where a value is an EMIS lookup (registration status,
  gender, island) the EMIS code is given so the KEMIS side can join to its own lookup tables.
- Every response carries `generated_at` (when the provider built the response) and
  `schema_version` (integer, currently `1`; bumped only on breaking changes).

### 2.2 Endpoints

All list endpoints return the complete set unless stated. The country scale (a few thousand
teachers) makes paging unnecessary except for the two event feeds.

#### `GET /api/warehouse/version`

Freshness probe. Cheap; consumers should call it first and skip the pull when `last_change_at`
has not moved.

```json
{
  "app": "pacific-emis-teacher-registration",
  "schema_version": 1,
  "generated_at": "2026-10-24T03:10:00Z",
  "last_change_at": "2026-10-23T22:41:07Z",
  "counts": {"registered_teachers": 1342, "open_applications": 57, "events": 9120}
}
```

`last_change_at` is the latest last-updated timestamp across every audited table.

#### `GET /api/warehouse/teacherregistration/summary`

The figures on the Teacher Registration Summary report and the dashboard, as one object.

```json
{
  "schema_version": 1,
  "generated_at": "...",
  "as_of": "2026-10-24",
  "staff": {"total": 1500, "teaching": 1342, "non_teaching": 158,
            "unassigned_to_school": 23, "added_last_30_days": 41},
  "active_schools": 112,
  "applications": {"total": 1611,
                   "by_status": [{"code": "draft", "label": "Draft", "count": 12},
                                 {"code": "submitted", "label": "Submitted", "count": 20},
                                 {"code": "under_review", "label": "Under Review", "count": 15},
                                 {"code": "ready_for_approval", "label": "Ready for Decision Approval/Rejection", "count": 10},
                                 {"code": "approved", "label": "Approved", "count": 1500},
                                 {"code": "rejected", "label": "Rejected", "count": 54}]},
  "registration_status": [{"code": "FULL", "label": "Full registration", "count": 900},
                          {"code": "PROV", "label": "Provisional", "count": 300}],
  "home_island": [{"code": "TRW", "label": "Tarawa", "count": 700}],
  "expiring": [{"month": "2026-11", "count": 14}, {"month": "2026-12", "count": 31}]
}
```

`registration_status` codes are the EMIS `TeacherRegistrationStatus` lookup codes synced from
KEMIS, so they match `lkpTeacherRegistrationStatus` there. `expiring` covers the next 12 months
of `valid_until` for currently approved registrations.

#### `GET /api/warehouse/teacherregistration/monthly`

One row per calendar month since the first application, for trend charts. Replaces the
placeholder "Monthly Registration Trends" chart on the report.

| field | type | meaning |
|---|---|---|
| month | `YYYY-MM` | calendar month, UTC |
| submitted | int | applications submitted in the month |
| approved | int | applications approved in the month |
| rejected | int | applications rejected in the month |
| granted | int | registrations whose validity started in the month (initial and renewals) |
| expiring | int | registrations whose validity ends in the month |

#### `GET /api/warehouse/teacherregistration/current`

One row per registered teaching staff member (approved or expired), the teacher-grain fact.

| field | type | meaning |
|---|---|---|
| registration_number | text | stable key, e.g. `TR26-A7K9-C` |
| application_status | text | `approved` or `expired` |
| registration_status_code | text or null | EMIS lookup code (Full, Provisional, ...) |
| registration_status_label | text or null | |
| granted_at | date or null | start of current validity |
| valid_until | date or null | end of current validity |
| days_to_expiry | int or null | negative when expired, computed at `as_of` |
| gender_code | text or null | EMIS gender code |
| birth_year | int or null | |
| home_island_code | text or null | EMIS island code |
| home_island_label | text or null | |
| school_no | text or null | EMIS `schNo` of the current (open-ended) assignment |
| school_name | text or null | |
| job_title_code | text or null | EMIS job title code of the current assignment |
| highest_qualification | text or null | |
| years_of_experience | int or null | |
| staff_id | int | provider's internal id, for joining to `activity` |
| created_at | datetime | when the staff record was created |
| last_updated_at | datetime | |

`school_no` joins directly to pineapples `Schools.schNo`, which gives district, island,
authority and school type on the KEMIS side. Teachers with no open assignment have
`school_no` null and must still be counted.

#### `GET /api/warehouse/teacherregistration/events?after_id=<int>&limit=<int>`

Registration workflow change log, append-only, ordered by `id`. Default `limit` 1000, maximum
5000. Incremental sync: store the highest `id` seen and pass it back as `after_id`.

| field | type | meaning |
|---|---|---|
| id | int | monotonic, never reused |
| changed_at | datetime | |
| registration_id | int | provider's registration id |
| registration_type | text | `initial` or `renewal` |
| registration_number | text or null | set once approved |
| staff_id | int or null | set once approved, joins to `current.staff_id` |
| field | text | what changed, usually `status` |
| old_value | text | |
| new_value | text | |
| changed_by_id | int or null | acting user id; null for system actions |
| changed_by | text or null | acting user's display name |
| notes | text | |

Response envelope: `{"schema_version", "generated_at", "count", "next_after_id", "results"}`.
`next_after_id` is null when there is nothing more.

#### `GET /api/warehouse/teacherregistration/activity?since=<datetime>&limit=<int>`

Who did what, when, and last, across every audited record. One row per record, snapshot grain:
a later edit overwrites `last_updated_*`; deleted records disappear. Ordered by
`last_updated_at`, then `record_type`, then `record_id`. Default `limit` 1000, maximum 5000.
Incremental sync: pass the greatest `last_updated_at` seen as `since` (inclusive, so re-pull
the boundary and upsert on `(record_type, record_id)`).

| field | type | meaning |
|---|---|---|
| record_type | text | `school_staff`, `school_staff_assignment`, `system_user`, `staff_education_record`, `staff_training_record`, `staff_teaching_duty`, `teacher_registration`, `registration_document`, `education_record`, `training_record`, `claimed_school_appointment`, `claimed_duty`, `registration_condition` |
| record_id | int | |
| label | text | human-readable, e.g. `TR26-A7K9-C`, `Assignment at KIR101` |
| staff_id | int or null | owning registered teacher, when any |
| registration_id | int or null | owning application, when any |
| created_at | datetime | |
| created_by_id | int or null | |
| created_by | text or null | display name |
| last_updated_at | datetime | |
| last_updated_by_id | int or null | |
| last_updated_by | text or null | display name |

Response envelope as for `events`, with `next_since` instead of `next_after_id`.

### 2.3 Errors and limits

- `401` bad or missing key, `404` unknown route, `400` bad query parameter (body says which).
- No rate limit is enforced, but the feeds are meant to be pulled a few times a day, not polled.
- Responses are not cached server-side; the version endpoint exists so the consumer can skip
  unchanged pulls.

## 3. Provider work plan (this repository)

One local commit per phase, same branch.

1. **Warehouse views + honest report.** Add a `warehouse` schema in PostgreSQL through a
   RunSQL migration with views backing every endpoint above: `registration_current`,
   `registration_monthly`, `registration_events`, `record_activity`, plus the small aggregate
   views the summary needs. Refactor the Teacher Registration Summary PDF and the dashboard to
   read these views. Replace the two placeholder sections: "Monthly Registration Trends" becomes
   real monthly approvals and submissions; "Staff Composition" becomes a two-segment donut with
   unassigned staff moved to Additional Statistics as a real number.
2. **API.** `/api/warehouse/...` views with bearer-key auth from `WAREHOUSE_API_KEYS`, JSON and
   CSV renderers, cursor paging for the two feeds, the version endpoint. Tests for auth, shapes,
   cursors and CSV. Local `.env` gets `WAREHOUSE_API_KEYS=dev-local-key`.
3. **Docs and deployment.** README section for the feed, the environment variable in the
   deployment notes.

## 4. Consumer brief (pineapples)

This section is self-contained so another agent can work from it in parallel, in the
pineapples repository. Read that repository's `AGENTS.md` first for its own conventions.

### 4.1 Settings and secrets

- Put the provider URL and key in `web.config` `appSettings`
  (`TeacherRegistration.ApiUrl`, `TeacherRegistration.ApiKey`), read through the existing
  configuration helpers.
- Do **not** store the key in `sysParams`. `DSLookups` exports every sysParams row to clients
  through the lookups collection (`SELECT paramName C, paramText N, paramInt I from sysParams`),
  so a key there is visible to any logged-in user.
- A sysParams row such as `TEACHER_REGISTRATION_FEED` with `paramInt 1` is the right on/off
  switch for the client to show or hide the dashboard, matching how the `EXAM_*` flags are used
  in `DSExam.cs`.

### 4.2 Pull and warehouse build

- **Client.** A small `HttpClient` wrapper under `Pineapples/Providers/` (next to
  `GoogleDriveManager.cs`, the only existing outbound HTTP code) that calls `version`, then
  `summary`, `monthly`, `current`, and the two feeds incrementally. Send
  `Authorization: Bearer <key>`. Respect `schema_version`: refuse to load if it is not `1`.
- **Staging.** Land raw rows in `warehouse.TeacherRegistrationCurrentStage`,
  `...MonthlyStage`, `...EventsStage`, `...ActivityStage` (truncate and reload for the first
  three; upsert for events by `id` and activity by `(record_type, record_id)`). Store the
  provider's `generated_at` and `last_change_at` in a one-row `warehouse.TeacherRegistrationFeed`
  table so the dashboard can show data age.
- **Build.** `warehouse.buildTeacherRegistration` builds the facts from staging and joins
  `school_no` to `Schools` for the standard school dimension (district, island, region,
  authority, school type), exactly as `warehouse.TeacherCertificationSchoolDimension` does.
  Call it from `warehouse.buildWarehouse` after `buildTeacherLocation`, guarded so an empty
  staging set leaves the previous facts untouched rather than wiping them.
- **Views.** `warehouse.TeacherRegistrationSchoolDimension` (one row per registered teacher
  with the full school dimension, the direct analogue of
  `warehouse.TeacherCertificationSchoolDimension`), `warehouse.TeacherRegistrationMonthly`,
  `warehouse.TeacherRegistrationEvents`, `warehouse.TeacherRegistrationActivity`, and a
  coverage view that joins registered-teacher counts per school to the latest-year census
  teacher counts from `warehouse.TeacherLocation` or `warehouse.TeacherCount`.
- **Trigger.** Pull on demand from an admin-only API action and on the schedule that already
  drives the warehouse rebuild. The feeds are small; a full `current` pull is a few hundred KB.
- **Expose.** `WarehouseController` partial `TeacherRegistration.cs` with routes in the house
  style: `teacherregistration/schooldimension/{filterCode?}`, `teacherregistration/monthly`,
  `teacherregistration/coverage/schooldimension/{filterCode?}`, `teacherregistration/events`,
  `teacherregistration/activity`, plus an OData entity for the school-dimension view if the
  pattern is followed for the other teacher feeds. SQL objects go under `SqlScripts/` with the
  usual header block and history log.

### 4.3 Dashboard in Pineapples.Client

Template: the Teacher Certification dashboard from issue 2603, which is the same shape, a
teacher-grain latest-state feed with the school dimension and no year selector. Files to copy
from:

- `Pineapples.Client/src/app/ts/features/Teacher/TeacherCertificationDashboard.Component.ts`,
  a `CrossfilterDashboard` over `warehouse.TeacherCertificationSchoolDimension`.
- The route state in `Pineapples.Client/src/app/ts/features/Teacher/Teacher.Routes.ts` at
  `^/teachers/certification` (`rendermode: "Dashboard"`, component plus `searcher` options
  editor, `coreOptions` resolve, `TeacherRead` permission).
- The navigation install script `SqlScripts/Tools/Navigation/nav-teachers-certification.sql`
  for the menu row under Teachers, Dashboards.
- Widgets in `Pineapples.Client/src/app/ts/features/Dashboard/Widget/` (ECharts bar, stacked
  area, line, crosstab, crossfilter table) and the base classes in `Dashboard/Base/`.

Add a `^/teachers/registration` state, a `teacherRegistrationDashboard` component over
`warehouse.TeacherRegistrationSchoolDimension`, the shared core selectors (district, island,
authority, school type) and a menu row gated by the sysParams flag. Charts, all possible from
this feed:

1. **Headline tiles.** Registered teachers, share with a valid registration, open applications,
   median days from submitted to approved (from events), data age from the feed table.
2. **Registration coverage by school dimension.** Registered teachers per district or island
   against census teacher counts: the share of teachers in the system who hold a registration.
   This is the one chart that needs KEMIS data and the main reason the feed lands in the
   warehouse.
3. **Status mix.** Full, provisional, limited, expired, as a stacked bar per district.
4. **Pipeline and throughput.** Monthly submitted, approved, rejected from `monthly`; backlog
   ageing (days in current status) from `events`.
5. **Expiry horizon.** Registrations expiring per month for the next 12 months, with the list
   behind it from the school-dimension view for follow-up.
6. **Registry activity.** From `activity` and `events`: records created or updated per week,
   approvals per reviewer per month, last activity date per school. A "is the registry alive"
   view for MOE management rather than a public indicator.

Badge colours for registration status are documented in the provider's `AGENTS.md`
(the royal purple scale); reuse them so both systems read the same way. The map view already
supports marker styles per teacher status (see `TeacherMapView.ts`); a "Registration status"
marker style is a natural extension once the school-dimension view exists.

### 4.4 Developing against the provider locally

- Provider dev server: `http://lvh.me:8001`, key `dev-local-key`. All endpoints are live.
  Use the `lvh.me` name rather than the loopback address so the traffic can be routed through a
  local debugging proxy (browsers and .NET both bypass proxies for loopback).
- Smoke test:

```
curl -H "Authorization: Bearer dev-local-key" http://lvh.me:8001/api/warehouse/version
curl -H "Authorization: Bearer dev-local-key" "http://lvh.me:8001/api/warehouse/teacherregistration/current?format=csv" | head
```

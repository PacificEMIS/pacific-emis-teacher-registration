"""
Warehouse views (issue #119).

A `warehouse` schema of read-only PostgreSQL views that present registration
data at the grain KEMIS consumes: one row per registered teacher, monthly
counts, the workflow change log, and a record-activity feed compiled from the
created/last-updated audit fields on every record. The Teacher Registration
Summary report, the dashboard and the /api/warehouse/ endpoints all read these
views, so the three can never disagree.

Maintenance note: PostgreSQL refuses to ALTER the type of a column that a view
depends on. A later migration that changes such a column must drop the schema
first (`DROP SCHEMA warehouse CASCADE`) and recreate the views after the
ALTER. The SQL below is the full definition; copy it forward and edit, do not
import it from here.
"""

from django.db import migrations

USER_DISPLAY = (
    "CASE WHEN {u}.id IS NULL THEN NULL "
    "ELSE COALESCE(NULLIF(TRIM({u}.first_name || ' ' || {u}.last_name), ''), {u}.username) END"
)

CREATE_SQL = f"""
CREATE SCHEMA IF NOT EXISTS warehouse;

-- One row per registered teaching staff member (approved or expired).
CREATE VIEW warehouse.registration_current AS
SELECT s.id AS staff_id,
       s.teacher_registration_number AS registration_number,
       s.registration_application_status AS application_status,
       rs.code AS registration_status_code,
       rs.label AS registration_status_label,
       (s.registration_granted_at AT TIME ZONE 'UTC')::date AS granted_at,
       (s.registration_valid_until AT TIME ZONE 'UTC')::date AS valid_until,
       CASE WHEN s.registration_valid_until IS NULL THEN NULL
            ELSE ((s.registration_valid_until AT TIME ZONE 'UTC')::date - CURRENT_DATE)::int
       END AS days_to_expiry,
       g.code AS gender_code,
       EXTRACT(YEAR FROM s.date_of_birth)::int AS birth_year,
       i.code AS home_island_code,
       i.label AS home_island_label,
       a.school_id AS school_no,
       sch.emis_school_name AS school_name,
       a.job_title_id AS job_title_code,
       NULLIF(s.highest_qualification, '') AS highest_qualification,
       s.years_of_experience,
       s.created_at,
       s.last_updated_at
FROM core_schoolstaff s
LEFT JOIN integrations_emisteacherregistrationstatus rs ON rs.code = s.teacher_registration_status_id
LEFT JOIN integrations_emisgender g ON g.code = s.gender_id
LEFT JOIN integrations_emisisland i ON i.code = s.home_island_id
LEFT JOIN LATERAL (
    SELECT sa.school_id, sa.job_title_id
    FROM core_schoolstaffassignment sa
    WHERE sa.school_staff_id = s.id AND sa.end_date IS NULL
    ORDER BY sa.start_date DESC NULLS LAST, sa.id DESC
    LIMIT 1
) a ON TRUE
LEFT JOIN integrations_emisschool sch ON sch.emis_school_no = a.school_id
WHERE s.staff_type = 'teaching'
  AND s.registration_application_status IN ('approved', 'expired');

-- One row per calendar month (UTC) from the first application to the last expiry.
CREATE VIEW warehouse.registration_monthly AS
WITH bounds AS (
    SELECT date_trunc('month', LEAST(
               COALESCE((SELECT min(created_at) FROM teacher_registration_teacherregistration), now()),
               COALESCE((SELECT min(created_at) FROM core_schoolstaff), now()))) AS first_month,
           date_trunc('month', GREATEST(now(),
               COALESCE((SELECT max(registration_valid_until) FROM core_schoolstaff), now()))) AS last_month
),
months AS (
    SELECT generate_series(first_month, last_month, interval '1 month') AS month_start FROM bounds
),
submitted AS (
    SELECT date_trunc('month', submitted_at) AS m, count(*) AS n
    FROM teacher_registration_teacherregistration WHERE submitted_at IS NOT NULL GROUP BY 1
),
approved AS (
    SELECT date_trunc('month', changed_at) AS m, count(*) AS n
    FROM teacher_registration_registrationchangelog
    WHERE field_name = 'status' AND new_value = 'approved' GROUP BY 1
),
rejected AS (
    SELECT date_trunc('month', changed_at) AS m, count(*) AS n
    FROM teacher_registration_registrationchangelog
    WHERE field_name = 'status' AND new_value = 'rejected' GROUP BY 1
),
granted AS (
    SELECT date_trunc('month', registration_granted_at) AS m, count(*) AS n
    FROM core_schoolstaff WHERE registration_granted_at IS NOT NULL GROUP BY 1
),
expiring AS (
    SELECT date_trunc('month', registration_valid_until) AS m, count(*) AS n
    FROM core_schoolstaff WHERE registration_valid_until IS NOT NULL GROUP BY 1
)
SELECT to_char(mo.month_start, 'YYYY-MM') AS month,
       mo.month_start,
       COALESCE(s.n, 0)::int AS submitted,
       COALESCE(ap.n, 0)::int AS approved,
       COALESCE(r.n, 0)::int AS rejected,
       COALESCE(g.n, 0)::int AS granted,
       COALESCE(e.n, 0)::int AS expiring
FROM months mo
LEFT JOIN submitted s ON s.m = mo.month_start
LEFT JOIN approved ap ON ap.m = mo.month_start
LEFT JOIN rejected r ON r.m = mo.month_start
LEFT JOIN granted g ON g.m = mo.month_start
LEFT JOIN expiring e ON e.m = mo.month_start;

-- Registration workflow change log, append-only, keyed by id.
CREATE VIEW warehouse.registration_events AS
SELECT l.id,
       l.changed_at,
       l.registration_id,
       r.registration_type,
       s.teacher_registration_number AS registration_number,
       r.approved_staff_profile_id AS staff_id,
       l.field_name AS field,
       l.old_value,
       l.new_value,
       l.changed_by_id,
       {USER_DISPLAY.format(u='u')} AS changed_by,
       l.notes
FROM teacher_registration_registrationchangelog l
JOIN teacher_registration_teacherregistration r ON r.id = l.registration_id
LEFT JOIN core_schoolstaff s ON s.id = r.approved_staff_profile_id
LEFT JOIN auth_user u ON u.id = l.changed_by_id;

-- Who created and last touched every audited record, one row per record.
CREATE VIEW warehouse.record_activity AS
WITH records AS (
    SELECT 'school_staff' AS record_type, id AS record_id,
           COALESCE(NULLIF(teacher_registration_number, ''), 'Staff #' || id) AS label,
           id AS staff_id, NULL::bigint AS registration_id,
           created_at, created_by_id, last_updated_at, last_updated_by_id
    FROM core_schoolstaff
    UNION ALL
    SELECT 'school_staff_assignment', id, 'Assignment at ' || school_id,
           school_staff_id, NULL, created_at, created_by_id, last_updated_at, last_updated_by_id
    FROM core_schoolstaffassignment
    UNION ALL
    SELECT 'system_user', id, 'System user #' || id,
           NULL, NULL, created_at, created_by_id, last_updated_at, last_updated_by_id
    FROM core_systemuser
    UNION ALL
    SELECT 'staff_education_record', id, COALESCE(NULLIF(institution_name, ''), 'Education record'),
           school_staff_id, NULL, created_at, created_by_id, last_updated_at, last_updated_by_id
    FROM core_staffeducationrecord
    UNION ALL
    SELECT 'staff_training_record', id, COALESCE(NULLIF(title, ''), 'Training record'),
           school_staff_id, NULL, created_at, created_by_id, last_updated_at, last_updated_by_id
    FROM core_stafftrainingrecord
    UNION ALL
    SELECT 'staff_teaching_duty', d.id, 'Teaching duty',
           a.school_staff_id, NULL, d.created_at, d.created_by_id, d.last_updated_at, d.last_updated_by_id
    FROM core_staffteachingduty d
    JOIN core_schoolstaffassignment a ON a.id = d.assignment_id
    UNION ALL
    SELECT 'teacher_registration', id, registration_type || ' registration #' || id,
           approved_staff_profile_id, id, created_at, created_by_id, last_updated_at, last_updated_by_id
    FROM teacher_registration_teacherregistration
    UNION ALL
    SELECT 'registration_document', id,
           COALESCE(NULLIF(doc_title, ''), NULLIF(original_filename, ''), 'Document'),
           school_staff_id, registration_id, created_at, created_by_id, last_updated_at, last_updated_by_id
    FROM teacher_registration_registrationdocument
    UNION ALL
    SELECT 'education_record', id, COALESCE(NULLIF(institution_name, ''), 'Education record'),
           NULL, registration_id, created_at, created_by_id, last_updated_at, last_updated_by_id
    FROM teacher_registration_educationrecord
    UNION ALL
    SELECT 'training_record', id, COALESCE(NULLIF(title, ''), 'Training record'),
           NULL, registration_id, created_at, created_by_id, last_updated_at, last_updated_by_id
    FROM teacher_registration_trainingrecord
    UNION ALL
    SELECT 'claimed_school_appointment', id, 'Appointment at ' || COALESCE(current_school_id, '?'),
           NULL, registration_id, created_at, created_by_id, last_updated_at, last_updated_by_id
    FROM teacher_registration_claimedschoolappointment
    UNION ALL
    SELECT 'claimed_duty', d.id, 'Claimed duty',
           NULL, ap.registration_id, d.created_at, d.created_by_id, d.last_updated_at, d.last_updated_by_id
    FROM teacher_registration_claimedduty d
    JOIN teacher_registration_claimedschoolappointment ap ON ap.id = d.appointment_id
    UNION ALL
    SELECT 'registration_condition', id, 'Condition',
           school_staff_id, registration_id, created_at, created_by_id, last_updated_at, last_updated_by_id
    FROM teacher_registration_registrationcondition
)
SELECT r.record_type, r.record_id, r.label, r.staff_id, r.registration_id,
       r.created_at, r.created_by_id,
       {USER_DISPLAY.format(u='cu')} AS created_by,
       r.last_updated_at, r.last_updated_by_id,
       {USER_DISPLAY.format(u='uu')} AS last_updated_by
FROM records r
LEFT JOIN auth_user cu ON cu.id = r.created_by_id
LEFT JOIN auth_user uu ON uu.id = r.last_updated_by_id;

-- Single-row headline counts.
CREATE VIEW warehouse.staff_summary AS
SELECT (SELECT count(*) FROM core_schoolstaff)::int AS total,
       (SELECT count(*) FROM core_schoolstaff WHERE staff_type = 'teaching')::int AS teaching,
       (SELECT count(*) FROM core_schoolstaff WHERE staff_type <> 'teaching')::int AS non_teaching,
       (SELECT count(*) FROM core_schoolstaff s
         WHERE NOT EXISTS (SELECT 1 FROM core_schoolstaffassignment a WHERE a.school_staff_id = s.id))::int
           AS unassigned_to_school,
       (SELECT count(*) FROM core_schoolstaff WHERE created_at >= now() - interval '30 days')::int
           AS added_last_30_days,
       (SELECT count(*) FROM integrations_emisschool WHERE active)::int AS active_schools,
       (SELECT count(*) FROM core_schoolstaff
         WHERE staff_type = 'teaching' AND registration_application_status = 'approved')::int
           AS registered_teachers,
       (SELECT count(*) FROM teacher_registration_teacherregistration
         WHERE status IN ('draft', 'submitted', 'under_review', 'ready_for_approval'))::int
           AS open_applications,
       (SELECT count(*) FROM teacher_registration_registrationchangelog)::int AS events;

CREATE VIEW warehouse.application_status_counts AS
SELECT status AS code, count(*)::int AS count
FROM teacher_registration_teacherregistration
GROUP BY status;

CREATE VIEW warehouse.registration_status_counts AS
SELECT rs.code, rs.label, count(s.id)::int AS count
FROM core_schoolstaff s
JOIN integrations_emisteacherregistrationstatus rs ON rs.code = s.teacher_registration_status_id
GROUP BY rs.code, rs.label;

CREATE VIEW warehouse.home_island_counts AS
SELECT i.code, i.label, count(*)::int AS count
FROM core_schoolstaff s
JOIN integrations_emisisland i ON i.code = s.home_island_id
GROUP BY i.code, i.label;

-- Staff currently (open-ended assignment) at each school.
CREATE VIEW warehouse.school_staff_counts AS
SELECT sch.emis_school_no AS school_no,
       sch.emis_school_name AS school_name,
       count(DISTINCT a.school_staff_id)::int AS staff_count,
       count(DISTINCT a.school_staff_id) FILTER (
           WHERE s.staff_type = 'teaching' AND s.registration_application_status = 'approved')::int
           AS registered_teachers
FROM core_schoolstaffassignment a
JOIN integrations_emisschool sch ON sch.emis_school_no = a.school_id
JOIN core_schoolstaff s ON s.id = a.school_staff_id
WHERE a.end_date IS NULL
GROUP BY sch.emis_school_no, sch.emis_school_name;
"""

DROP_SQL = "DROP SCHEMA IF EXISTS warehouse CASCADE;"


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_require_schoolstaffassignment_teacher_level_type"),
        ("integrations", "0008_emisteacherlinktype_needs_renewal"),
        ("teacher_registration", "0028_protect_registration_user"),
    ]

    operations = [
        migrations.RunSQL(CREATE_SQL, reverse_sql=DROP_SQL),
    ]

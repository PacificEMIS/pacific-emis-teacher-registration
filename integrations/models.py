from django.db import models


class EmisSchool(models.Model):
    emis_school_no = models.CharField(max_length=32, primary_key=True)
    emis_school_name = models.CharField(max_length=255)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["emis_school_no"]

    def __str__(self):
        return f"{self.emis_school_name} ({self.emis_school_no})"


class EmisClassLevel(models.Model):
    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.levels.C
    label = models.CharField(max_length=128)  # from core.lookups.levels.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.label}"


class EmisJobTitle(models.Model):
    """
    Lookup table for teacher roles / job titles.
    Mirrors core.lookups.teacherRoles.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.teacherRoles.C
    label = models.CharField(max_length=128)  # from core.lookups.teacherRoles.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Job Title"
        verbose_name_plural = "Job Titles"

    def __str__(self):
        return f"{self.code} — {self.label}"


class EmisWarehouseYear(models.Model):
    """
    Lookup table for warehouse years (with school year formatted)
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.warehouseYears.C
    label = models.CharField(
        max_length=128
    )  # from core.lookups.warehouseYears.FormattedYear
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "School Year"

    def __str__(self):
        return f"{self.label}"


class EmisSubject(models.Model):
    """
    Lookup table for subjects / curriculum areas.
    Mirrors core.lookups.subjects.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.subjects.C
    label = models.CharField(max_length=128)  # from core.lookups.subjects.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["label"]
        verbose_name = "Subject"
        verbose_name_plural = "Subjects"

    def __str__(self):
        return self.label


class EmisTeacherQual(models.Model):
    """
    Lookup table for teacher qualifications.
    Mirrors core.lookups.teacherQuals.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.teacherQuals.C
    label = models.CharField(max_length=128)  # from core.lookups.teacherQuals.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Teacher Qualification"
        verbose_name_plural = "Teacher Qualifications"

    def __str__(self):
        return self.label


class EmisMaritalStatus(models.Model):
    """
    Lookup table for marital status.
    Mirrors core.lookups.maritalStatus.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.maritalStatus.C
    label = models.CharField(max_length=128)  # from core.lookups.maritalStatus.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Marital Status"
        verbose_name_plural = "Marital Statuses"

    def __str__(self):
        return self.label


class EmisIsland(models.Model):
    """
    Lookup table for islands / districts.
    Mirrors core.lookups.islands.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.islands.C
    label = models.CharField(max_length=128)  # from core.lookups.islands.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["label"]
        verbose_name = "Island"
        verbose_name_plural = "Islands"

    def __str__(self):
        return self.label


class EmisTeacherStatus(models.Model):
    """
    Lookup table for teacher registration status.
    Mirrors core.lookups.teacherRegStatus.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.teacherRegStatus.C
    label = models.CharField(max_length=128)  # from core.lookups.teacherRegStatus.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Teacher Status"
        verbose_name_plural = "Teacher Statuses"

    def __str__(self):
        return self.label


class EmisEducationLevel(models.Model):
    """
    Lookup table for education levels.
    Mirrors core.lookups.educationLevels.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.educationLevels.C
    label = models.CharField(max_length=128)  # from core.lookups.educationLevels.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Education Level"
        verbose_name_plural = "Education Levels"

    def __str__(self):
        return self.label


class EmisTeacherLinkType(models.Model):
    """
    Lookup table for teacher link types.
    Mirrors core.lookups.teacherLinkTypes.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.teacherLinkTypes.C
    label = models.CharField(max_length=128)  # from core.lookups.teacherLinkTypes.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Teacher Link Type"
        verbose_name_plural = "Teacher Link Types"

    def __str__(self):
        return self.label


class EmisGender(models.Model):
    """
    Lookup table for gender.
    Mirrors core.lookups.gender.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.gender.C
    label = models.CharField(max_length=128)  # from core.lookups.gender.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Gender"
        verbose_name_plural = "Genders"

    def __str__(self):
        return self.label


class EmisTeacherPdFocus(models.Model):
    """
    Lookup table for teacher PD focuses.
    Mirrors core.lookups.teacherPdFocuses.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.teacherPdFocuses.C
    label = models.CharField(max_length=128)  # from core.lookups.teacherPdFocuses.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Teacher PD Focus"
        verbose_name_plural = "Teacher PD Focuses"

    def __str__(self):
        return self.label


class EmisTeacherPdFormat(models.Model):
    """
    Lookup table for teacher PD formats.
    Mirrors core.lookups.teacherPdFormats.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.teacherPdFormats.C
    label = models.CharField(max_length=128)  # from core.lookups.teacherPdFormats.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Teacher PD Format"
        verbose_name_plural = "Teacher PD Formats"

    def __str__(self):
        return self.label


class EmisTeacherPdType(models.Model):
    """
    Lookup table for teacher PD types.
    Mirrors core.lookups.teacherPdTypes.
    """

    code = models.CharField(
        max_length=16, primary_key=True
    )  # from core.lookups.teacherPdTypes.C
    label = models.CharField(max_length=128)  # from core.lookups.teacherPdTypes.N
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Teacher PD Type"
        verbose_name_plural = "Teacher PD Types"

    def __str__(self):
        return self.label

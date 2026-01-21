from django.contrib import admin
from .models import (
    EmisSchool,
    EmisClassLevel,
    EmisJobTitle,
    EmisWarehouseYear,
    EmisSubject,
    EmisTeacherQual,
    EmisMaritalStatus,
    EmisIsland,
    EmisTeacherStatus,
    EmisEducationLevel,
    EmisTeacherLinkType,
    EmisGender,
    EmisTeacherPdFocus,
    EmisTeacherPdFormat,
    EmisTeacherPdType,
)


@admin.register(EmisSchool)
class EmisSchoolAdmin(admin.ModelAdmin):
    list_display = ("emis_school_no", "emis_school_name", "active")
    search_fields = ("emis_school_no", "emis_school_name")
    list_filter = ("active",)


@admin.register(EmisClassLevel)
class EmisClassLevelAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisJobTitle)
class EmisJobTitleAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisWarehouseYear)
class EmisWarehouseYearAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisSubject)
class EmisSubjectAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisTeacherQual)
class EmisTeacherQualAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisMaritalStatus)
class EmisMaritalStatusAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisIsland)
class EmisIslandAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisTeacherStatus)
class EmisTeacherStatusAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisEducationLevel)
class EmisEducationLevelAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisTeacherLinkType)
class EmisTeacherLinkTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisGender)
class EmisGenderAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisTeacherPdFocus)
class EmisTeacherPdFocusAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisTeacherPdFormat)
class EmisTeacherPdFormatAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)


@admin.register(EmisTeacherPdType)
class EmisTeacherPdTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "active")
    search_fields = ("code", "label")
    list_filter = ("active",)

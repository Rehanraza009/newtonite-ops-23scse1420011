from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(DefaultUserAdmin):
    fieldsets = DefaultUserAdmin.fieldsets + (
        ("Newtonite Info", {"fields": ("job_title",)}),
    )
    list_display = ("username", "email", "first_name", "last_name", "job_title", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name", "job_title")

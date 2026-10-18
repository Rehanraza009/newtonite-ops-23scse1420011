from django.contrib import admin
from .models import Team, TeamMembership


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    extra = 1
    autocomplete_fields = ["user"]


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_restricted", "created_at")
    list_filter = ("is_restricted",)
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [TeamMembershipInline]


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "team", "role", "created_at")
    list_filter = ("role", "team")
    search_fields = ("user__username", "team__name")

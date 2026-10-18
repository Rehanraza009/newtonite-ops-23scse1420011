from django.conf import settings
from django.db import models


class TeamRole(models.TextChoices):
    VIEWER = "viewer", "Viewer"
    MEMBER = "member", "Member"
    LEAD = "lead", "Lead"
    ADMIN = "admin", "Admin"


class Team(models.Model):
    """
    Represents an organizational or operational team (e.g., Incident Management, Billing).
    Items belong to teams, and access control is governed by TeamMembership.
    """
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    is_restricted = models.BooleanField(
        default=False,
        help_text="If restricted, only members/leads/admins can view this team's work items."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_restricted"]),
        ]

    def __str__(self):
        return self.name


class TeamMembership(models.Model):
    """
    Associates a User with a Team under a specific TeamRole.
    Enforces per-team role-based access control.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_memberships",
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=TeamRole.choices,
        default=TeamRole.MEMBER,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["team", "role", "user__username"]
        unique_together = ("user", "team")
        indexes = [
            models.Index(fields=["user", "team"]),
            models.Index(fields=["team", "role"]),
        ]

    def __str__(self):
        return f"{self.user.username} in {self.team.name} ({self.get_role_display()})"

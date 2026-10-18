from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model for Newtonite Operations Hub.
    Extends Django's AbstractUser to allow customized attributes
    and team-scoping helper methods.
    """
    job_title = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["username"]
        indexes = [
            models.Index(fields=["username"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self):
        full = self.get_full_name()
        return f"{full} ({self.username})" if full else self.username

    def get_role_in_team(self, team):
        """Returns the user's role in the specified team, or None if not a member."""
        if self.is_superuser:
            return "admin"
        from teams.models import TeamMembership
        membership = TeamMembership.objects.filter(user=self, team=team).first()
        return membership.role if membership else None

    def has_team_role(self, team, required_roles):
        """
        Check if user has any of the required roles in the given team.
        Superuser always has admin access.
        """
        if self.is_superuser:
            return True
        role = self.get_role_in_team(team)
        if not role:
            return False
        if isinstance(required_roles, str):
            required_roles = [required_roles]
        return role in required_roles

from rest_framework import permissions
from .models import TeamRole, TeamMembership


class TeamPermissionService:
    """
    Centralized authorization service for Team and WorkItem operations.
    Enforces per-team role permissions on the server.
    """

    @staticmethod
    def get_user_role(user, team):
        """Returns the user's role in the team, or None."""
        if not user or not user.is_authenticated:
            return None
        if user.is_superuser:
            return TeamRole.ADMIN
        membership = TeamMembership.objects.filter(user=user, team=team).first()
        return membership.role if membership else None

    @classmethod
    def can_view_team(cls, user, team):
        """
        Determines whether the user can view the team and its items.
        Restricted teams require explicit membership.
        Non-restricted teams allow authenticated user viewing.
        """
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = cls.get_user_role(user, team)
        if team.is_restricted:
            return role is not None
        return True

    @classmethod
    def can_view_workitem(cls, user, item):
        """Check if user can view a specific work item."""
        return cls.can_view_team(user, item.team)

    @classmethod
    def can_create_workitem(cls, user, team):
        """Requires Member, Lead, or Admin role in the team."""
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = cls.get_user_role(user, team)
        return role in (TeamRole.MEMBER, TeamRole.LEAD, TeamRole.ADMIN)

    @classmethod
    def can_update_workitem(cls, user, item):
        """Requires Member, Lead, or Admin role in the item's team."""
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = cls.get_user_role(user, item.team)
        return role in (TeamRole.MEMBER, TeamRole.LEAD, TeamRole.ADMIN)

    @classmethod
    def can_claim_workitem(cls, user, item):
        """Requires Member, Lead, or Admin role in the item's team."""
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = cls.get_user_role(user, item.team)
        return role in (TeamRole.MEMBER, TeamRole.LEAD, TeamRole.ADMIN)

    @classmethod
    def can_transition_workitem(cls, user, item, target_status):
        """
        Enforces workflow permissions:
        - Regular transitions: Member, Lead, Admin
        - Transitioning to 'resolved' (Approval): ONLY Lead or Admin!
        - Rejecting from 'awaiting_approval' back to 'in_progress': ONLY Lead or Admin!
        """
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True

        role = cls.get_user_role(user, item.team)
        if not role or role == TeamRole.VIEWER:
            return False

        # Approval requires Lead or Admin
        if item.status == "awaiting_approval" and target_status in ("resolved", "in_progress"):
            return role in (TeamRole.LEAD, TeamRole.ADMIN)

        # Other valid transitions require at least Member
        return role in (TeamRole.MEMBER, TeamRole.LEAD, TeamRole.ADMIN)

    @classmethod
    def can_comment_workitem(cls, user, item):
        """Viewer, Member, Lead, Admin can comment if they have view access."""
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = cls.get_user_role(user, item.team)
        return role is not None or not item.team.is_restricted


class HasWorkItemAccess(permissions.BasePermission):
    """
    DRF permission class for WorkItem object-level authorization.
    """

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in permissions.SAFE_METHODS:
            return TeamPermissionService.can_view_workitem(request.user, obj)

        return TeamPermissionService.can_update_workitem(request.user, obj)

from django.db import models
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Team, TeamMembership, TeamRole
from .permissions import TeamPermissionService


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def team_list_api(request):
    """
    Returns teams visible to the current user.
    Restricted teams are only returned if the user is a member or superuser.
    """
    user = request.user
    if user.is_superuser:
        teams = Team.objects.all()
    else:
        user_team_ids = TeamMembership.objects.filter(user=user).values_list("team_id", flat=True)
        teams = Team.objects.filter(
            models.Q(is_restricted=False) | models.Q(id__in=user_team_ids)
        ).distinct()

    data = [
        {
            "id": t.id,
            "name": t.name,
            "slug": t.slug,
            "description": t.description,
            "is_restricted": t.is_restricted,
            "user_role": TeamPermissionService.get_user_role(user, t),
        }
        for t in teams
    ]
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def team_members_api(request, team_id):
    """
    Returns members of the given team who can be assigned work items.
    """
    from django.db.models import Q
    team = get_object_or_404(Team, id=team_id)
    if not TeamPermissionService.can_view_team(request.user, team):
        return Response({"detail": "Not found."}, status=404)

    memberships = TeamMembership.objects.filter(team=team).select_related("user")
    data = [
        {
            "id": m.user.id,
            "username": m.user.username,
            "full_name": m.user.get_full_name(),
            "role": m.role,
        }
        for m in memberships
    ]
    return Response(data)

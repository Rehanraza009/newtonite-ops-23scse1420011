from django.urls import path
from . import views

urlpatterns = [
    path("api/teams/", views.team_list_api, name="api_teams_list"),
    path("api/teams/<int:team_id>/members/", views.team_members_api, name="api_team_members"),
]

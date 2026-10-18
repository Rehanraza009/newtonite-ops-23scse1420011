import pytest
from rest_framework.test import APIClient
from accounts.models import User
from teams.models import Team, TeamMembership, TeamRole
from workitems.models import WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client():
    def _auth_client(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client
    return _auth_client


@pytest.fixture
def setup_environment(db):
    """
    Creates standard test teams, users, and memberships.
    """
    # Teams
    open_team = Team.objects.create(
        name="Platform Core",
        slug="platform-core",
        description="Public operational team",
        is_restricted=False,
    )
    restricted_team = Team.objects.create(
        name="Security & Compliance",
        slug="security-compliance",
        description="Restricted audit team",
        is_restricted=True,
    )

    # Users
    admin_user = User.objects.create_superuser(
        username="admin_user",
        email="admin@test.local",
        password="testpassword123",
        job_title="Admin",
    )
    open_lead = User.objects.create_user(
        username="open_lead",
        email="open_lead@test.local",
        password="testpassword123",
        job_title="Platform Lead",
    )
    open_member = User.objects.create_user(
        username="open_member",
        email="open_member@test.local",
        password="testpassword123",
        job_title="Platform Engineer",
    )
    open_viewer = User.objects.create_user(
        username="open_viewer",
        email="open_viewer@test.local",
        password="testpassword123",
        job_title="Auditor",
    )

    restricted_lead = User.objects.create_user(
        username="restricted_lead",
        email="restricted_lead@test.local",
        password="testpassword123",
        job_title="Security Lead",
    )
    restricted_member = User.objects.create_user(
        username="restricted_member",
        email="restricted_member@test.local",
        password="testpassword123",
        job_title="Security Engineer",
    )

    unaffiliated_user = User.objects.create_user(
        username="unaffiliated",
        email="unaffiliated@test.local",
        password="testpassword123",
        job_title="External",
    )

    # Memberships
    TeamMembership.objects.create(user=open_lead, team=open_team, role=TeamRole.LEAD)
    TeamMembership.objects.create(user=open_member, team=open_team, role=TeamRole.MEMBER)
    TeamMembership.objects.create(user=open_viewer, team=open_team, role=TeamRole.VIEWER)

    TeamMembership.objects.create(user=restricted_lead, team=restricted_team, role=TeamRole.LEAD)
    TeamMembership.objects.create(user=restricted_member, team=restricted_team, role=TeamRole.MEMBER)

    return {
        "open_team": open_team,
        "restricted_team": restricted_team,
        "admin_user": admin_user,
        "open_lead": open_lead,
        "open_member": open_member,
        "open_viewer": open_viewer,
        "restricted_lead": restricted_lead,
        "restricted_member": restricted_member,
        "unaffiliated_user": unaffiliated_user,
    }

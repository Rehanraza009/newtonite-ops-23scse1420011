import pytest
from rest_framework import status
from workitems.models import WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType


@pytest.mark.django_db
def test_unauthenticated_request_rejected(api_client):
    """Unauthenticated API requests must be rejected with 401 or 403."""
    resp = api_client.get("/api/items/")
    assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db
def test_whoami_endpoint(setup_environment, auth_client):
    """Verified that whoami returns authenticated user profile and team roles."""
    env = setup_environment
    client = auth_client(env["open_lead"])

    resp = client.get("/api/auth/whoami/")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["username"] == "open_lead"
    assert len(data["teams"]) == 1
    assert data["teams"][0]["team_slug"] == "platform-core"
    assert data["teams"][0]["role"] == "lead"


@pytest.mark.django_db
def test_viewer_cannot_create_work_items(setup_environment, auth_client):
    """Viewers have read-only access and cannot create work items (returns 403)."""
    env = setup_environment
    client = auth_client(env["open_viewer"])

    payload = {
        "title": "Unauthorized ticket by viewer",
        "description": "Should fail",
        "type": WorkItemType.TASK,
        "priority": WorkItemPriority.LOW,
        "team_id": env["open_team"].id,
    }
    resp = client.post("/api/items/", payload, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_member_can_create_work_items(setup_environment, auth_client):
    """Team members can create work items in their team (returns 201)."""
    env = setup_environment
    client = auth_client(env["open_member"])

    payload = {
        "title": "Upgrade Node Memory Limits",
        "description": "Bump cgroup limits on cluster 4",
        "type": WorkItemType.TASK,
        "priority": WorkItemPriority.MEDIUM,
        "team_id": env["open_team"].id,
    }
    resp = client.post("/api/items/", payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["title"] == "Upgrade Node Memory Limits"


@pytest.mark.django_db
def test_cross_team_read_denied_for_restricted_team(setup_environment, auth_client):
    """
    Users outside a restricted team must NOT be able to read its items.
    Returns 404 to avoid leaking existence of restricted tickets.
    """
    env = setup_environment
    # Create item in restricted team
    restricted_item = WorkItem.objects.create(
        title="Restricted Security Vulnerability",
        description="Internal zero-day finding",
        type=WorkItemType.INCIDENT,
        priority=WorkItemPriority.URGENT,
        status=WorkItemStatus.OPEN,
        team=env["restricted_team"],
        creator=env["restricted_lead"],
    )

    # 1. Non-member from another team (open_member) attempts read -> 404
    non_member_client = auth_client(env["open_member"])
    resp = non_member_client.get(f"/api/items/{restricted_item.id}/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # 2. Member of restricted team attempts read -> 200 OK
    member_client = auth_client(env["restricted_member"])
    resp = member_client.get(f"/api/items/{restricted_item.id}/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["id"] == restricted_item.id

    # 3. Superuser attempts read -> 200 OK
    admin_client = auth_client(env["admin_user"])
    resp = admin_client.get(f"/api/items/{restricted_item.id}/")
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_cross_team_write_denied(setup_environment, auth_client):
    """
    Users cannot write or modify another team's items without explicit permissions.
    """
    env = setup_environment
    open_item = WorkItem.objects.create(
        title="Open Team Task",
        description="Public platform task",
        type=WorkItemType.TASK,
        priority=WorkItemPriority.LOW,
        status=WorkItemStatus.OPEN,
        team=env["open_team"],
        creator=env["open_lead"],
    )

    # Unaffiliated user (no membership) attempts update -> 403 Forbidden
    unaffiliated_client = auth_client(env["unaffiliated_user"])
    resp = unaffiliated_client.patch(
        f"/api/items/{open_item.id}/",
        {"title": "Tampered Title", "version": open_item.version},
        format="json",
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN

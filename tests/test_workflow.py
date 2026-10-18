import pytest
from rest_framework import status
from workitems.models import WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType, ActivityEventType


@pytest.mark.django_db
def test_full_allowed_workflow_lifecycle(setup_environment, auth_client):
    """
    Validates end-to-end progression through the strictly allowed workflow:
    Open -> In Progress -> Awaiting Approval -> Resolved (Lead approved) -> Closed.
    """
    env = setup_environment
    member_client = auth_client(env["open_member"])
    lead_client = auth_client(env["open_lead"])

    # 1. Create item in Open state
    item = WorkItem.objects.create(
        title="Payment Ingress Migration",
        description="Migrate routes to envoy gateway",
        type=WorkItemType.TASK,
        priority=WorkItemPriority.MEDIUM,
        status=WorkItemStatus.OPEN,
        team=env["open_team"],
        creator=env["open_member"],
        version=1,
    )

    # 2. Member transitions Open -> In Progress
    resp = member_client.post(f"/api/items/{item.id}/transition/", {"target_status": "in_progress"}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "in_progress"

    # 3. Member transitions In Progress -> Awaiting Approval
    resp = member_client.post(f"/api/items/{item.id}/transition/", {"target_status": "awaiting_approval"}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "awaiting_approval"

    # 4. Lead approves: Awaiting Approval -> Resolved
    resp = lead_client.post(
        f"/api/items/{item.id}/transition/",
        {"target_status": "resolved", "note": "Verified gateway metrics and latency. Approved."},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "resolved"

    # 5. Transition Resolved -> Closed
    resp = lead_client.post(f"/api/items/{item.id}/transition/", {"target_status": "closed"}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "closed"


@pytest.mark.django_db
def test_invalid_transitions_rejected(setup_environment, auth_client):
    """
    Server must reject forbidden / illegal state transitions with 400 Bad Request.
    """
    env = setup_environment
    lead_client = auth_client(env["open_lead"])

    item = WorkItem.objects.create(
        title="Direct Jump Test",
        type=WorkItemType.TASK,
        priority=WorkItemPriority.LOW,
        status=WorkItemStatus.OPEN,
        team=env["open_team"],
        creator=env["open_lead"],
        version=1,
    )

    # Open -> Resolved directly is illegal
    resp = lead_client.post(f"/api/items/{item.id}/transition/", {"target_status": "resolved"}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # Open -> Closed directly is illegal
    resp = lead_client.post(f"/api/items/{item.id}/transition/", {"target_status": "closed"}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_non_lead_cannot_approve(setup_environment, auth_client):
    """
    Security check: Only an authorized Lead of the relevant team can approve an item.
    Regular members, viewers, and leads from OTHER teams must be denied (403 Forbidden).
    """
    env = setup_environment
    item = WorkItem.objects.create(
        title="Critical Database Change",
        type=WorkItemType.TASK,
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.AWAITING_APPROVAL,
        team=env["open_team"],
        creator=env["open_member"],
        version=1,
    )

    # 1. Regular Member tries to approve -> 403 Forbidden
    member_client = auth_client(env["open_member"])
    resp = member_client.post(f"/api/items/{item.id}/transition/", {"target_status": "resolved"}, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # 2. Viewer tries to approve -> 403 Forbidden
    viewer_client = auth_client(env["open_viewer"])
    resp = viewer_client.post(f"/api/items/{item.id}/transition/", {"target_status": "resolved"}, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # 3. Lead of ANOTHER team (restricted_lead) tries to approve -> 403 Forbidden
    other_lead_client = auth_client(env["restricted_lead"])
    resp = other_lead_client.post(f"/api/items/{item.id}/transition/", {"target_status": "resolved"}, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # 4. Authorized Lead of open_team approves -> 200 OK
    proper_lead_client = auth_client(env["open_lead"])
    resp = proper_lead_client.post(f"/api/items/{item.id}/transition/", {"target_status": "resolved"}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "resolved"


@pytest.mark.django_db
def test_lead_rejection_flow(setup_environment, auth_client):
    """
    A Lead can reject an item in 'awaiting_approval' back to 'in_progress'.
    """
    env = setup_environment
    item = WorkItem.objects.create(
        title="Unverified Migration Script",
        type=WorkItemType.TASK,
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.AWAITING_APPROVAL,
        team=env["open_team"],
        creator=env["open_member"],
        version=1,
    )

    lead_client = auth_client(env["open_lead"])
    resp = lead_client.post(
        f"/api/items/{item.id}/transition/",
        {"target_status": "in_progress", "note": "Rollback script missing. Please revise."},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "in_progress"

    item.refresh_from_db()
    assert item.status == WorkItemStatus.IN_PROGRESS
    last_event = item.activity_events.last()
    assert last_event.event_type == ActivityEventType.REJECTED

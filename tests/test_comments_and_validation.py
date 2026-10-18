import pytest
from rest_framework import status
from workitems.models import WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType, Comment, ActivityEventType


@pytest.mark.django_db
def test_comment_creation_and_listing(setup_environment, auth_client):
    """
    Verifies that authenticated users can post and retrieve comments,
    and that an ActivityEvent is recorded for every added comment.
    """
    env = setup_environment
    client = auth_client(env["open_member"])

    item = WorkItem.objects.create(
        title="Incident Discussion Target",
        type=WorkItemType.INCIDENT,
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.IN_PROGRESS,
        team=env["open_team"],
        creator=env["open_member"],
    )

    # 1. Post a valid comment
    resp = client.post(
        f"/api/items/{item.id}/comments/",
        {"content": "Applied hotfix commit #a491f. Memory utilization down to 42%."},
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["author"]["username"] == "open_member"
    assert "Applied hotfix" in data["content"]

    # 2. Verify comment listing
    list_resp = client.get(f"/api/items/{item.id}/comments/")
    assert list_resp.status_code == status.HTTP_200_OK
    assert len(list_resp.json()) == 1

    # 3. Verify activity event recorded
    last_event = item.activity_events.last()
    assert last_event.event_type == ActivityEventType.COMMENT_ADDED


@pytest.mark.django_db
def test_validation_rules(setup_environment, auth_client):
    """
    Verifies input validation on both work items and comments.
    """
    env = setup_environment
    client = auth_client(env["open_member"])

    # 1. Empty title must be rejected
    resp = client.post(
        "/api/items/",
        {
            "title": "   ",
            "team_id": env["open_team"].id,
            "type": WorkItemType.TASK,
            "priority": WorkItemPriority.LOW,
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # 2. Empty comment content must be rejected
    item = WorkItem.objects.create(
        title="Valid Title",
        type=WorkItemType.TASK,
        priority=WorkItemPriority.LOW,
        status=WorkItemStatus.OPEN,
        team=env["open_team"],
        creator=env["open_member"],
    )
    resp = client.post(
        f"/api/items/{item.id}/comments/",
        {"content": "   "},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST

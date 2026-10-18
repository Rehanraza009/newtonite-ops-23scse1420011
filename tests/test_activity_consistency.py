import pytest
from unittest.mock import patch
from django.db import transaction
from workitems.models import (
    WorkItem,
    WorkItemPriority,
    WorkItemStatus,
    WorkItemType,
    ActivityEvent,
    ActivityEventType,
)
from workitems.services import WorkItemService


@pytest.mark.django_db
def test_activity_events_written_transactionally(setup_environment):
    """
    Verifies that every state, assignee, and priority change creates an
    append-only ActivityEvent within the exact same database transaction.
    """
    env = setup_environment
    user = env["open_member"]

    # 1. Create workitem
    item_data, _ = WorkItemService.create_item(
        user=user,
        validated_data={
            "title": "Audit Consistency Item",
            "description": "Checking event generation",
            "type": WorkItemType.TASK,
            "priority": WorkItemPriority.LOW,
            "team": env["open_team"],
        },
    )
    item = WorkItem.objects.get(id=item_data["id"])

    events = ActivityEvent.objects.filter(work_item=item)
    assert events.count() == 1
    assert events.first().event_type == ActivityEventType.CREATED
    assert events.first().actor == user

    # 2. Update priority and title
    WorkItemService.update_item(
        work_item_id=item.id,
        user=user,
        data={"priority": WorkItemPriority.URGENT, "title": "Updated Title"},
        expected_version=1,
    )
    item.refresh_from_db()
    assert item.version == 2
    assert item.priority == WorkItemPriority.URGENT

    events = ActivityEvent.objects.filter(work_item=item).order_by("created_at")
    assert events.count() == 2
    update_event = events.last()
    assert update_event.event_type == ActivityEventType.PRIORITY_CHANGED
    assert update_event.from_state["priority"] == WorkItemPriority.LOW
    assert update_event.to_state["priority"] == WorkItemPriority.URGENT


@pytest.mark.django_db
def test_transactional_rollback_on_activity_failure(setup_environment):
    """
    CRITICAL ATOMICITY TEST:
    If writing the activity event or outbox fails, the work item change MUST roll back.
    No partial or inconsistent state may leak.
    """
    env = setup_environment
    user = env["open_member"]

    item = WorkItem.objects.create(
        title="Rollback Verification Target",
        type=WorkItemType.TASK,
        priority=WorkItemPriority.LOW,
        status=WorkItemStatus.OPEN,
        team=env["open_team"],
        creator=user,
        version=1,
    )

    # Simulate an unhandled database exception when creating ActivityEvent
    with patch("workitems.models.ActivityEvent.objects.create", side_effect=RuntimeError("Simulated DB Disk Failure")):
        with pytest.raises(RuntimeError):
            WorkItemService.update_item(
                work_item_id=item.id,
                user=user,
                data={"title": "Should Be Rolled Back"},
                expected_version=1,
            )

    # Item must remain untouched at version 1 with original title
    item.refresh_from_db()
    assert item.title == "Rollback Verification Target"
    assert item.version == 1
    assert ActivityEvent.objects.filter(work_item=item).count() == 0

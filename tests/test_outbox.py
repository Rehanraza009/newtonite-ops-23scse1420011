import pytest
from unittest.mock import patch
from workitems.models import (
    WorkItem,
    WorkItemPriority,
    WorkItemStatus,
    WorkItemType,
    OutboxMessage,
    OutboxStatus,
)
from workitems.services import WorkItemService
from workitems.outbox import OutboxProcessor, OutboxProcessingError


@pytest.mark.django_db
def test_outbox_event_created_transactionally(setup_environment):
    """
    Verifies that state transitions create OutboxMessage records in the same transaction.
    """
    env = setup_environment
    user = env["open_lead"]

    item = WorkItem.objects.create(
        title="Outbox Event Trigger Item",
        type=WorkItemType.INCIDENT,
        priority=WorkItemPriority.URGENT,
        status=WorkItemStatus.OPEN,
        team=env["open_team"],
        creator=user,
    )

    initial_outbox_count = OutboxMessage.objects.count()

    # Transition item: Open -> In Progress
    WorkItemService.transition_item(
        work_item_id=item.id,
        user=user,
        target_status=WorkItemStatus.IN_PROGRESS,
    )

    assert OutboxMessage.objects.count() == initial_outbox_count + 1
    new_msg = OutboxMessage.objects.order_by("created_at").last()
    assert new_msg.status == OutboxStatus.PENDING
    assert new_msg.payload["work_item_id"] == item.id
    assert new_msg.payload["to_status"] == WorkItemStatus.IN_PROGRESS


@pytest.mark.django_db
def test_outbox_processor_delivers_successfully():
    """
    Verifies OutboxProcessor processes pending messages and marks them DELIVERED.
    """
    msg = OutboxMessage.objects.create(
        topic="workitem.notification",
        payload={"message": "System test event"},
        status=OutboxStatus.PENDING,
    )

    processed = OutboxProcessor.process_pending_batch(limit=10)
    assert processed == 1

    msg.refresh_from_db()
    assert msg.status == OutboxStatus.DELIVERED
    assert msg.processed_at is not None
    assert msg.attempts == 1


@pytest.mark.django_db
def test_outbox_processor_retries_and_marks_failed_on_max_attempts():
    """
    Verifies that when dispatch fails, the processor retries up to max_attempts
    and marks the message FAILED upon exhaustion.
    """
    msg = OutboxMessage.objects.create(
        topic="test.simulate_failure",
        payload={"data": "will_fail"},
        status=OutboxStatus.PENDING,
        attempts=0,
        max_attempts=3,
    )

    # Attempt 1: Fails, stays PENDING for retry
    success1 = OutboxProcessor.process_single_message(msg.id)
    assert success1 is False
    msg.refresh_from_db()
    assert msg.attempts == 1
    assert msg.status == OutboxStatus.PENDING
    assert "Simulated external service unreachable" in msg.last_error

    # Attempt 2: Fails, stays PENDING
    success2 = OutboxProcessor.process_single_message(msg.id)
    assert success2 is False
    msg.refresh_from_db()
    assert msg.attempts == 2
    assert msg.status == OutboxStatus.PENDING

    # Attempt 3: Reaches max_attempts (3), transitions to FAILED
    success3 = OutboxProcessor.process_single_message(msg.id)
    assert success3 is False
    msg.refresh_from_db()
    assert msg.attempts == 3
    assert msg.status == OutboxStatus.FAILED

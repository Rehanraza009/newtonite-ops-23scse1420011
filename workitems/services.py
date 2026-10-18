import hashlib
import json
from django.db import transaction
from django.core.exceptions import PermissionDenied, ValidationError
from teams.permissions import TeamPermissionService
from teams.models import TeamRole
from .models import (
    WorkItem,
    WorkItemStatus,
    WorkItemPriority,
    WorkItemType,
    Comment,
    ActivityEvent,
    ActivityEventType,
    IdempotencyRecord,
    OutboxMessage,
    OutboxStatus,
)


class ConflictError(Exception):
    """Raised when a concurrent state conflict occurs (e.g. already claimed)."""
    def __init__(self, message, current_state=None):
        super().__init__(message)
        self.message = message
        self.current_state = current_state or {}


class StaleUpdateConflictError(ConflictError):
    """Raised when an update specifies a stale version number (HTTP 409)."""
    def __init__(self, current_version, message="Work item was updated by another process.", latest_data=None):
        super().__init__(message, current_state={"current_version": current_version, "latest_data": latest_data})
        self.current_version = current_version
        self.latest_data = latest_data or {}


ALLOWED_TRANSITIONS = {
    WorkItemStatus.OPEN: [WorkItemStatus.IN_PROGRESS],
    WorkItemStatus.IN_PROGRESS: [WorkItemStatus.AWAITING_APPROVAL, WorkItemStatus.CLOSED],
    WorkItemStatus.AWAITING_APPROVAL: [WorkItemStatus.RESOLVED, WorkItemStatus.IN_PROGRESS],
    WorkItemStatus.RESOLVED: [WorkItemStatus.CLOSED],
    WorkItemStatus.CLOSED: [],
}


class WorkItemService:
    """
    Core business logic and transactional boundary for Work Items.
    Guarantees atomic conditional updates, optimistic locking,
    append-only audit history, and outbox event publishing.
    """

    @classmethod
    def claim_item(cls, work_item_id, user):
        """
        Atomically claims an unassigned work item.
        Uses PostgreSQL row-level locking (select_for_update) inside transaction.atomic.
        Guarantees that two concurrent claim requests cannot both succeed.
        """
        with transaction.atomic():
            item = WorkItem.objects.select_for_update().get(id=work_item_id)

            if not TeamPermissionService.can_claim_workitem(user, item):
                raise PermissionDenied("You do not have permission to claim work items in this team.")

            if item.assignee is not None:
                raise ConflictError(
                    f"Work item #{item.id} has already been claimed by {item.assignee.username}."
                )

            old_status = item.status
            old_assignee_name = None

            item.assignee = user
            if item.status == WorkItemStatus.OPEN:
                item.status = WorkItemStatus.IN_PROGRESS

            item.version += 1
            item.save()

            ActivityEvent.objects.create(
                work_item=item,
                actor=user,
                event_type=ActivityEventType.CLAIMED,
                message=f"Claimed by {user.username} (status changed from {old_status} to {item.status})",
                from_state={"assignee": old_assignee_name, "status": old_status},
                to_state={"assignee": user.username, "status": item.status},
            )

            # Enqueue outbox notification
            OutboxMessage.objects.create(
                topic="workitem.claimed",
                payload={
                    "work_item_id": item.id,
                    "title": item.title,
                    "claimed_by": user.username,
                    "team": item.team.name,
                },
            )

            return item

    @classmethod
    def update_item(cls, work_item_id, user, data, expected_version=None):
        """
        Updates an existing work item with optimistic locking check.
        If expected_version differs from stored version, raises StaleUpdateConflictError (HTTP 409).
        Records all field modifications in append-only ActivityEvent history.
        """
        with transaction.atomic():
            item = WorkItem.objects.select_for_update().get(id=work_item_id)

            if not TeamPermissionService.can_update_workitem(user, item):
                raise PermissionDenied("You do not have permission to update work items in this team.")

            if expected_version is not None and int(expected_version) != item.version:
                raise StaleUpdateConflictError(
                    current_version=item.version,
                    message=(
                        f"Conflict: item #{item.id} was modified by another operation. "
                        f"Expected version {expected_version}, but current version is {item.version}."
                    ),
                    latest_data={
                        "id": item.id,
                        "title": item.title,
                        "description": item.description,
                        "status": item.status,
                        "priority": item.priority,
                        "type": item.type,
                        "version": item.version,
                        "assignee_id": item.assignee_id,
                        "updated_at": item.updated_at.isoformat(),
                    },
                )

            changes = {}
            from_state = {}
            to_state = {}

            # Permitted editable fields
            if "title" in data and data["title"] != item.title:
                from_state["title"] = item.title
                to_state["title"] = data["title"]
                item.title = data["title"]
                changes["title"] = True

            if "description" in data and data["description"] != item.description:
                from_state["description"] = item.description
                to_state["description"] = data["description"]
                item.description = data["description"]
                changes["description"] = True

            if "priority" in data and data["priority"] != item.priority:
                from_state["priority"] = item.priority
                to_state["priority"] = data["priority"]
                item.priority = data["priority"]
                changes["priority"] = True

            if "type" in data and data["type"] != item.type:
                from_state["type"] = item.type
                to_state["type"] = data["type"]
                item.type = data["type"]
                changes["type"] = True

            if "due_date" in data:
                new_due = data["due_date"]
                if new_due != item.due_date:
                    from_state["due_date"] = str(item.due_date) if item.due_date else None
                    to_state["due_date"] = str(new_due) if new_due else None
                    item.due_date = new_due
                    changes["due_date"] = True

            if "assignee" in data:
                new_assignee = data["assignee"]
                if new_assignee != item.assignee:
                    from_state["assignee"] = item.assignee.username if item.assignee else None
                    to_state["assignee"] = new_assignee.username if new_assignee else None
                    item.assignee = new_assignee
                    changes["assignee"] = True

            if changes:
                item.version += 1
                item.save()

                event_type = ActivityEventType.FIELD_UPDATED
                if "priority" in changes:
                    event_type = ActivityEventType.PRIORITY_CHANGED
                elif "assignee" in changes:
                    event_type = ActivityEventType.REASSIGNED if item.assignee else ActivityEventType.UNASSIGNED

                ActivityEvent.objects.create(
                    work_item=item,
                    actor=user,
                    event_type=event_type,
                    message=f"Updated: {', '.join(changes.keys())}",
                    from_state=from_state,
                    to_state=to_state,
                )

            return item

    @classmethod
    def transition_item(cls, work_item_id, user, target_status, note=None):
        """
        Executes a workflow state transition according to allowed lifecycle rules.
        Enforces team Lead approval for 'resolved'.
        Rejects invalid transitions and unauthorized approvals.
        """
        with transaction.atomic():
            item = WorkItem.objects.select_for_update().get(id=work_item_id)

            current_status = item.status
            allowed = ALLOWED_TRANSITIONS.get(current_status, [])

            if target_status not in allowed:
                raise ValidationError(
                    f"Invalid transition from '{current_status}' to '{target_status}'. "
                    f"Allowed transitions: {allowed}."
                )

            if not TeamPermissionService.can_transition_workitem(user, item, target_status):
                if current_status == WorkItemStatus.AWAITING_APPROVAL and target_status == WorkItemStatus.RESOLVED:
                    raise PermissionDenied("Only a designated Team Lead or Admin can approve work items.")
                raise PermissionDenied("You do not have permission to perform this state transition.")

            old_status = item.status
            item.status = target_status
            item.version += 1
            item.save()

            if current_status == WorkItemStatus.AWAITING_APPROVAL and target_status == WorkItemStatus.RESOLVED:
                event_type = ActivityEventType.APPROVED
                msg = f"Approved and marked Resolved by Lead {user.username}."
            elif current_status == WorkItemStatus.AWAITING_APPROVAL and target_status == WorkItemStatus.IN_PROGRESS:
                event_type = ActivityEventType.REJECTED
                msg = f"Changes requested / Rejected back to In Progress by Lead {user.username}."
            else:
                event_type = ActivityEventType.STATUS_CHANGED
                msg = f"Status transitioned from {old_status} to {target_status}."

            if note:
                msg += f" Note: {note}"

            ActivityEvent.objects.create(
                work_item=item,
                actor=user,
                event_type=event_type,
                message=msg,
                from_state={"status": old_status},
                to_state={"status": target_status, "note": note},
            )

            # Transactional Outbox event
            OutboxMessage.objects.create(
                topic=f"workitem.{event_type}",
                payload={
                    "work_item_id": item.id,
                    "title": item.title,
                    "from_status": old_status,
                    "to_status": target_status,
                    "actor": user.username,
                    "note": note,
                },
            )

            return item

    @classmethod
    def create_item(cls, user, validated_data, idempotency_key=None):
        """
        Creates a new work item.
        Supports Idempotency-Key: if key was previously processed, returns cached response
        without creating a duplicate record.
        """
        with transaction.atomic():
            if idempotency_key:
                # Lock and check idempotency record
                record = (
                    IdempotencyRecord.objects.select_for_update()
                    .filter(key=idempotency_key)
                    .first()
                )
                if record:
                    return record.response_body, True

            team = validated_data["team"]
            if not TeamPermissionService.can_create_workitem(user, team):
                raise PermissionDenied("You do not have permission to create work items for this team.")

            item = WorkItem.objects.create(
                title=validated_data["title"],
                description=validated_data.get("description", ""),
                type=validated_data.get("type", WorkItemType.TASK),
                priority=validated_data.get("priority", WorkItemPriority.MEDIUM),
                status=validated_data.get("status", WorkItemStatus.OPEN),
                team=team,
                assignee=validated_data.get("assignee"),
                creator=user,
                due_date=validated_data.get("due_date"),
                version=1,
            )

            ActivityEvent.objects.create(
                work_item=item,
                actor=user,
                event_type=ActivityEventType.CREATED,
                message=f"Created by {user.username}",
                from_state={},
                to_state={
                    "title": item.title,
                    "status": item.status,
                    "priority": item.priority,
                    "team": item.team.name,
                },
            )

            # Outbox event
            OutboxMessage.objects.create(
                topic="workitem.created",
                payload={
                    "work_item_id": item.id,
                    "title": item.title,
                    "creator": user.username,
                    "team": item.team.name,
                    "priority": item.priority,
                },
            )

            from .serializers import WorkItemDetailSerializer
            item_data = WorkItemDetailSerializer(item).data

            if idempotency_key:
                IdempotencyRecord.objects.create(
                    key=idempotency_key,
                    user=user,
                    response_status=201,
                    response_body=item_data,
                )

            return item_data, False

    @classmethod
    def add_comment(cls, work_item_id, user, content):
        """
        Adds a comment to a work item and records an ActivityEvent.
        """
        with transaction.atomic():
            item = WorkItem.objects.select_for_update().get(id=work_item_id)
            if not TeamPermissionService.can_comment_workitem(user, item):
                raise PermissionDenied("You do not have permission to comment on this work item.")

            comment = Comment.objects.create(
                work_item=item,
                author=user,
                content=content.strip(),
            )

            ActivityEvent.objects.create(
                work_item=item,
                actor=user,
                event_type=ActivityEventType.COMMENT_ADDED,
                message=f"Added a comment ({len(content.strip())} chars)",
                from_state={},
                to_state={"comment_id": comment.id},
            )

            return comment

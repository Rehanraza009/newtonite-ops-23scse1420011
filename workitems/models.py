import uuid
from django.conf import settings
from django.db import models
from teams.models import Team


class WorkItemType(models.TextChoices):
    INCIDENT = "incident", "Incident"
    CUSTOMER_ISSUE = "customer_issue", "Customer Issue"
    PAYMENT = "payment", "Payment"
    COMPLIANCE = "compliance", "Compliance"
    TASK = "task", "Task"


class WorkItemPriority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class WorkItemStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In Progress"
    AWAITING_APPROVAL = "awaiting_approval", "Awaiting Approval"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


class WorkItem(models.Model):
    """
    Core operational work item entity.
    Tracks critical operational tickets with optimistic locking versioning,
    team-scoping, assignee, status lifecycle and audit trail.
    """
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    type = models.CharField(
        max_length=30,
        choices=WorkItemType.choices,
        default=WorkItemType.TASK,
    )
    priority = models.CharField(
        max_length=20,
        choices=WorkItemPriority.choices,
        default=WorkItemPriority.MEDIUM,
    )
    status = models.CharField(
        max_length=30,
        choices=WorkItemStatus.choices,
        default=WorkItemStatus.OPEN,
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.PROTECT,
        related_name="work_items",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_work_items",
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_work_items",
    )
    due_date = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(
        default=1,
        help_text="Optimistic locking version counter. Incremented on every update."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["type"]),
            models.Index(fields=["team", "status"]),
            models.Index(fields=["assignee", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["due_date"]),
        ]

    def __str__(self):
        return f"[{self.type.upper()}] #{self.id} {self.title} ({self.status})"


class Comment(models.Model):
    """
    Collaborative discussion comment on a WorkItem.
    """
    work_item = models.ForeignKey(
        WorkItem,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="comments",
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["work_item", "created_at"]),
        ]

    def __str__(self):
        return f"Comment by {self.author.username} on item #{self.work_item_id}"


class ActivityEventType(models.TextChoices):
    CREATED = "created", "Created"
    CLAIMED = "claimed", "Claimed"
    UNASSIGNED = "unassigned", "Unassigned"
    REASSIGNED = "reassigned", "Reassigned"
    STATUS_CHANGED = "status_changed", "Status Changed"
    PRIORITY_CHANGED = "priority_changed", "Priority Changed"
    FIELD_UPDATED = "field_updated", "Field Updated"
    COMMENT_ADDED = "comment_added", "Comment Added"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class ActivityEvent(models.Model):
    """
    Append-only immutable audit event trail.
    Every state change, assignment, claim, and approval is recorded
    transactionally within the same database transaction.
    """
    work_item = models.ForeignKey(
        WorkItem,
        on_delete=models.CASCADE,
        related_name="activity_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    event_type = models.CharField(
        max_length=50,
        choices=ActivityEventType.choices,
        default=ActivityEventType.FIELD_UPDATED,
    )
    message = models.CharField(max_length=255)
    from_state = models.JSONField(default=dict, blank=True)
    to_state = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["work_item", "created_at"]),
            models.Index(fields=["event_type"]),
        ]

    def __str__(self):
        actor_name = self.actor.username if self.actor else "System"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {actor_name}: {self.message}"


class IdempotencyRecord(models.Model):
    """
    Idempotency tracking record for state-changing operations.
    Prevents duplicate operations when network retries occur.
    """
    key = models.CharField(max_length=255, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="idempotency_records",
    )
    request_hash = models.CharField(max_length=64, blank=True, default="")
    response_status = models.PositiveIntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["key"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"IdempotencyKey {self.key} ({self.response_status})"


class OutboxStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"


class OutboxMessage(models.Model):
    """
    Transactional Outbox model for reliable asynchronous operations.
    Ensures events are written atomically with the business transaction
    and reliably delivered or retried by an asynchronous worker.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.CharField(max_length=100)
    payload = models.JSONField()
    status = models.CharField(
        max_length=20,
        choices=OutboxStatus.choices,
        default=OutboxStatus.PENDING,
    )
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["topic"]),
        ]

    def __str__(self):
        return f"OutboxMessage {self.id} [{self.topic}] ({self.status})"

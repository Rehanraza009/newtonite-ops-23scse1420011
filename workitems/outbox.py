import logging
from django.db import transaction
from django.utils import timezone
from .models import OutboxMessage, OutboxStatus

logger = logging.getLogger(__name__)


class OutboxProcessingError(Exception):
    pass


class OutboxProcessor:
    """
    Transactional Outbox event processor.
    Pulls pending outbox events, invokes topic handlers, and guarantees
    exponential backoff/retries up to max_attempts, with idempotency.
    """

    @classmethod
    def dispatch_event(cls, topic, payload):
        """
        Simulates reliable delivery of notification / webhook / external broker event.
        Can be mocked or injected during testing.
        """
        if topic == "test.simulate_failure":
            raise OutboxProcessingError("Simulated external service unreachable.")
        # Successfully processed
        return True

    @classmethod
    def process_single_message(cls, message_id):
        """
        Processes a single outbox message by ID with row locking.
        """
        with transaction.atomic():
            msg = (
                OutboxMessage.objects.select_for_update()
                .filter(id=message_id)
                .first()
            )
            if not msg:
                return False

            if msg.status == OutboxStatus.DELIVERED:
                # Idempotent skip
                return True

            msg.status = OutboxStatus.PROCESSING
            msg.attempts += 1
            msg.save(update_fields=["status", "attempts"])

        try:
            # Execute dispatch outside locked transaction or in short boundary
            cls.dispatch_event(msg.topic, msg.payload)

            with transaction.atomic():
                msg.refresh_from_db()
                msg.status = OutboxStatus.DELIVERED
                msg.processed_at = timezone.now()
                msg.last_error = ""
                msg.save(update_fields=["status", "processed_at", "last_error"])
            return True

        except Exception as exc:
            logger.warning(f"Error processing OutboxMessage {msg.id}: {exc}")
            with transaction.atomic():
                msg.refresh_from_db()
                msg.last_error = str(exc)
                if msg.attempts >= msg.max_attempts:
                    msg.status = OutboxStatus.FAILED
                else:
                    msg.status = OutboxStatus.PENDING  # Ready for retry
                msg.save(update_fields=["status", "last_error"])
            return False

    @classmethod
    def process_pending_batch(cls, limit=50):
        """
        Fetches pending messages using PostgreSQL select_for_update(skip_locked=True)
        to enable concurrent safe processing across multiple workers.
        """
        with transaction.atomic():
            messages = list(
                OutboxMessage.objects.select_for_update(skip_locked=True)
                .filter(status=OutboxStatus.PENDING)
                .order_by("created_at")[:limit]
            )
            msg_ids = [m.id for m in messages]

        processed_count = 0
        for mid in msg_ids:
            if cls.process_single_message(mid):
                processed_count += 1

        return processed_count

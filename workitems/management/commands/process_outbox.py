import time
from django.core.management.base import BaseCommand
from workitems.outbox import OutboxProcessor


class Command(BaseCommand):
    help = "Processes pending transactional outbox events with retries and failure handling."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process one batch and exit immediately (useful for cron/tests).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Number of records to fetch per batch.",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=2.0,
            help="Sleep interval in seconds between batches when running continuously.",
        )

    def handle(self, *args, **options):
        once = options["once"]
        batch_size = options["batch_size"]
        interval = options["interval"]

        self.stdout.write(self.style.NOTICE("Starting Outbox Processor worker..."))

        if once:
            count = OutboxProcessor.process_pending_batch(limit=batch_size)
            self.stdout.write(self.style.SUCCESS(f"Processed {count} outbox message(s). Exiting."))
            return

        try:
            while True:
                count = OutboxProcessor.process_pending_batch(limit=batch_size)
                if count > 0:
                    self.stdout.write(self.style.SUCCESS(f"Processed {count} outbox message(s)."))
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.NOTICE("Outbox worker stopped by user."))

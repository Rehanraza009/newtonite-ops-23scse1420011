import os
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from accounts.models import User
from teams.models import Team, TeamMembership, TeamRole
from workitems.models import (
    WorkItem,
    WorkItemType,
    WorkItemPriority,
    WorkItemStatus,
    Comment,
    ActivityEvent,
    ActivityEventType,
)


class Command(BaseCommand):
    help = "Seeds database with demo teams, realistic users across roles, and operational work items."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding Newtonite Operations Hub database..."))

        default_password = os.getenv("DEMO_USER_PASSWORD", "Newtonite2026!")

        # 1. Create Teams
        teams_data = [
            {
                "name": "Platform Core",
                "slug": "platform-core",
                "description": "Core infrastructure, reliability, microservices and distributed tracing.",
                "is_restricted": False,
            },
            {
                "name": "Payments & Billing",
                "slug": "payments-billing",
                "description": "Payment gateways, ledger reconciliation, transaction payouts and merchant billing.",
                "is_restricted": False,
            },
            {
                "name": "Security & Compliance",
                "slug": "security-compliance",
                "description": "SOC2, PCI-DSS compliance, vulnerability triaging and cryptographic access controls.",
                "is_restricted": True,  # Restricted team!
            },
            {
                "name": "Customer Support",
                "slug": "customer-support",
                "description": "Tier-2/3 customer escalations, incident communication and account anomalies.",
                "is_restricted": False,
            },
        ]

        teams = {}
        for t_info in teams_data:
            team, created = Team.objects.get_or_create(
                slug=t_info["slug"],
                defaults={
                    "name": t_info["name"],
                    "description": t_info["description"],
                    "is_restricted": t_info["is_restricted"],
                },
            )
            teams[t_info["slug"]] = team
            action = "Created" if created else "Found existing"
            self.stdout.write(f"  {action} team: {team.name}")

        # 2. Create Users
        users_data = [
            {
                "username": "admin",
                "first_name": "Alex",
                "last_name": "Admin",
                "email": "alex.admin@newtonite.internal",
                "job_title": "Global Operations Director",
                "is_superuser": True,
                "is_staff": True,
            },
            {
                "username": "lead_payments",
                "first_name": "Priya",
                "last_name": "Patel",
                "email": "priya.patel@newtonite.internal",
                "job_title": "Payments Engineering Lead",
                "is_superuser": False,
                "is_staff": False,
            },
            {
                "username": "lead_security",
                "first_name": "Marcus",
                "last_name": "Vance",
                "email": "marcus.vance@newtonite.internal",
                "job_title": "Head of Information Security",
                "is_superuser": False,
                "is_staff": False,
            },
            {
                "username": "lead_platform",
                "first_name": "Sarah",
                "last_name": "Chen",
                "email": "sarah.chen@newtonite.internal",
                "job_title": "Staff Reliability Lead",
                "is_superuser": False,
                "is_staff": False,
            },
            {
                "username": "member_payments",
                "first_name": "Devon",
                "last_name": "Miller",
                "email": "devon.miller@newtonite.internal",
                "job_title": "Senior Billing Engineer",
                "is_superuser": False,
                "is_staff": False,
            },
            {
                "username": "member_security",
                "first_name": "Rachel",
                "last_name": "Foster",
                "email": "rachel.foster@newtonite.internal",
                "job_title": "Security Operations Engineer",
                "is_superuser": False,
                "is_staff": False,
            },
            {
                "username": "member_platform",
                "first_name": "Liam",
                "last_name": "Brooks",
                "email": "liam.brooks@newtonite.internal",
                "job_title": "Cloud Infrastructure Engineer",
                "is_superuser": False,
                "is_staff": False,
            },
            {
                "username": "member_support",
                "first_name": "Elena",
                "last_name": "Rostova",
                "email": "elena.rostova@newtonite.internal",
                "job_title": "Escalations Specialist",
                "is_superuser": False,
                "is_staff": False,
            },
            {
                "username": "viewer_auditor",
                "first_name": "Arthur",
                "last_name": "Pendelton",
                "email": "arthur.pendelton@newtonite.internal",
                "job_title": "External Risk & Compliance Auditor",
                "is_superuser": False,
                "is_staff": False,
            },
            {
                "username": "viewer_guest",
                "first_name": "Chloe",
                "last_name": "Zhao",
                "email": "chloe.zhao@newtonite.internal",
                "job_title": "Operations Trainee",
                "is_superuser": False,
                "is_staff": False,
            },
        ]

        users = {}
        for u_info in users_data:
            user, created = User.objects.get_or_create(
                username=u_info["username"],
                defaults={
                    "first_name": u_info["first_name"],
                    "last_name": u_info["last_name"],
                    "email": u_info["email"],
                    "job_title": u_info["job_title"],
                    "is_superuser": u_info["is_superuser"],
                    "is_staff": u_info["is_staff"],
                },
            )
            user.set_password(default_password)
            user.save()
            users[u_info["username"]] = user
            action = "Created" if created else "Updated password for"
            self.stdout.write(f"  {action} user: {user.username} ({user.job_title})")

        # 3. Create Team Memberships (Role Matrix)
        memberships_data = [
            # Platform Core
            ("lead_platform", "platform-core", TeamRole.LEAD),
            ("member_platform", "platform-core", TeamRole.MEMBER),
            ("viewer_guest", "platform-core", TeamRole.VIEWER),
            # Payments & Billing
            ("lead_payments", "payments-billing", TeamRole.LEAD),
            ("member_payments", "payments-billing", TeamRole.MEMBER),
            ("viewer_auditor", "payments-billing", TeamRole.VIEWER),
            # Security & Compliance (Restricted)
            ("lead_security", "security-compliance", TeamRole.LEAD),
            ("member_security", "security-compliance", TeamRole.MEMBER),
            ("viewer_auditor", "security-compliance", TeamRole.VIEWER),
            # Customer Support
            ("lead_platform", "customer-support", TeamRole.ADMIN),
            ("member_support", "customer-support", TeamRole.MEMBER),
            ("viewer_guest", "customer-support", TeamRole.VIEWER),
        ]

        for u_name, t_slug, role in memberships_data:
            membership, created = TeamMembership.objects.get_or_create(
                user=users[u_name],
                team=teams[t_slug],
                defaults={"role": role},
            )
            if not created and membership.role != role:
                membership.role = role
                membership.save()

        self.stdout.write(self.style.SUCCESS("  Configured team memberships."))

        # 4. Realistic Work Items
        now = timezone.now()
        work_items_seed = [
            {
                "title": "Production Redis Cluster High Memory Saturation",
                "description": "Session cluster eviction rate spiked to 12% following v2.14 release. Key TTL expiry policy needs re-indexing.",
                "type": WorkItemType.INCIDENT,
                "priority": WorkItemPriority.URGENT,
                "status": WorkItemStatus.OPEN,
                "team": teams["platform-core"],
                "creator": users["member_platform"],
                "assignee": None,  # Unassigned urgent
                "due_date": now + timedelta(hours=4),
            },
            {
                "title": "PostgreSQL Connection Pool Exhaustion on Node 3",
                "description": "PgBouncer hitting max client connections during batch settlement window. Investigate persistent idle in transaction locks.",
                "type": WorkItemType.INCIDENT,
                "priority": WorkItemPriority.HIGH,
                "status": WorkItemStatus.IN_PROGRESS,
                "team": teams["platform-core"],
                "creator": users["lead_platform"],
                "assignee": users["member_platform"],
                "due_date": now + timedelta(hours=12),
            },
            {
                "title": "Upgrade Ingress Controller to v1.9 for HTTP/3 Support",
                "description": "Upgrade edge ingress routers with zero-downtime rolling update. Verification plan submitted in comments.",
                "type": WorkItemType.TASK,
                "priority": WorkItemPriority.MEDIUM,
                "status": WorkItemStatus.AWAITING_APPROVAL,
                "team": teams["platform-core"],
                "creator": users["member_platform"],
                "assignee": users["member_platform"],
                "due_date": now + timedelta(days=2),
            },
            {
                "title": "Stripe Webhook Intermittent 504 Gateway Timeouts",
                "description": "Webhook ingestion queue processing delayed by 180s for merchant payouts. Asynchronous dispatcher retry counter triggered.",
                "type": WorkItemType.PAYMENT,
                "priority": WorkItemPriority.URGENT,
                "status": WorkItemStatus.OPEN,
                "team": teams["payments-billing"],
                "creator": users["lead_payments"],
                "assignee": None,  # Unassigned urgent
                "due_date": now + timedelta(hours=6),
            },
            {
                "title": "Merchant Settlement Ledger Reconciliation Mismatch #9402",
                "description": "Automated ledger detected a delta of $4,812.50 across batch #9402 between card processor settlement and balance ledger.",
                "type": WorkItemType.PAYMENT,
                "priority": WorkItemPriority.HIGH,
                "status": WorkItemStatus.IN_PROGRESS,
                "team": teams["payments-billing"],
                "creator": users["member_payments"],
                "assignee": users["member_payments"],
                "due_date": now + timedelta(days=1),
            },
            {
                "title": "Dispute Automated Resolution Rule Update (Regulation E)",
                "description": "Updated dispute evidence submission workflow for 10-day provisional credit window compliance. Requires Lead sign-off before deploy.",
                "type": WorkItemType.PAYMENT,
                "priority": WorkItemPriority.HIGH,
                "status": WorkItemStatus.AWAITING_APPROVAL,
                "team": teams["payments-billing"],
                "creator": users["member_payments"],
                "assignee": users["member_payments"],
                "due_date": now + timedelta(hours=24),
            },
            {
                "title": "Annual SOC2 Type II Evidence Collection & Key Rotation",
                "description": "Quarterly cryptographic KMS key rotation and IAM policy audit for restricted production VPC.",
                "type": WorkItemType.COMPLIANCE,
                "priority": WorkItemPriority.HIGH,
                "status": WorkItemStatus.IN_PROGRESS,
                "team": teams["security-compliance"],
                "creator": users["lead_security"],
                "assignee": users["member_security"],
                "due_date": now + timedelta(days=7),
            },
            {
                "title": "Vulnerability Remediation: CVE-2026-3194 OpenSSL Padding Oracle",
                "description": "Patch base Docker images and verify TLS termination cipher suites across all edge Envoy proxies.",
                "type": WorkItemType.INCIDENT,
                "priority": WorkItemPriority.URGENT,
                "status": WorkItemStatus.AWAITING_APPROVAL,
                "team": teams["security-compliance"],
                "creator": users["member_security"],
                "assignee": users["member_security"],
                "due_date": now + timedelta(hours=18),
            },
            {
                "title": "Tier-2 Escalation: Bulk User Invoice PDF Render Timeout",
                "description": "Customers downloading invoice bundles larger than 50 pages receive gateway 504. Background worker timeout adjustment required.",
                "type": WorkItemType.CUSTOMER_ISSUE,
                "priority": WorkItemPriority.MEDIUM,
                "status": WorkItemStatus.IN_PROGRESS,
                "team": teams["customer-support"],
                "creator": users["member_support"],
                "assignee": users["member_support"],
                "due_date": now + timedelta(days=3),
            },
            {
                "title": "Update Operations Runbook for Incident Escalation Matrix",
                "description": "Updated primary and secondary on-call rotation schedules, escalation pager duty rules and post-mortem SLA requirements.",
                "type": WorkItemType.TASK,
                "priority": WorkItemPriority.LOW,
                "status": WorkItemStatus.RESOLVED,
                "team": teams["customer-support"],
                "creator": users["member_support"],
                "assignee": users["member_support"],
                "due_date": now - timedelta(days=1),
            },
            {
                "title": "Deprecate Legacy Auth v1 Endpoints",
                "description": "All API consumers migrated to OAuth2 session exchange. Legacy v1 basic auth endpoints decommissioned and firewall rules updated.",
                "type": WorkItemType.TASK,
                "priority": WorkItemPriority.LOW,
                "status": WorkItemStatus.CLOSED,
                "team": teams["platform-core"],
                "creator": users["lead_platform"],
                "assignee": users["member_platform"],
                "due_date": now - timedelta(days=5),
            },
        ]

        for item_data in work_items_seed:
            item, created = WorkItem.objects.get_or_create(
                title=item_data["title"],
                team=item_data["team"],
                defaults={
                    "description": item_data["description"],
                    "type": item_data["type"],
                    "priority": item_data["priority"],
                    "status": item_data["status"],
                    "creator": item_data["creator"],
                    "assignee": item_data["assignee"],
                    "due_date": item_data["due_date"],
                    "version": 1,
                },
            )
            if created:
                ActivityEvent.objects.create(
                    work_item=item,
                    actor=item.creator,
                    event_type=ActivityEventType.CREATED,
                    message=f"Created by {item.creator.username}",
                    from_state={},
                    to_state={"status": item.status, "priority": item.priority},
                )
                if item.assignee:
                    ActivityEvent.objects.create(
                        work_item=item,
                        actor=item.assignee,
                        event_type=ActivityEventType.CLAIMED,
                        message=f"Assigned to {item.assignee.username}",
                        from_state={"assignee": None},
                        to_state={"assignee": item.assignee.username},
                    )
                # Add a realistic initial comment
                Comment.objects.create(
                    work_item=item,
                    author=item.creator,
                    content=f"Initial triage complete. Assigned priority: {item.priority.upper()}.",
                )
                self.stdout.write(f"  Created work item: #{item.id} {item.title}")

        self.stdout.write(self.style.SUCCESS("\nDatabase seeding completed successfully!"))
        self.stdout.write(self.style.NOTICE(f"All demo users seeded with password: {default_password}"))

# Engineering Decisions & Architecture Log

## Project: Newtonite Operations Hub (`newtonite-ops`)
**Challenge Context:** "Operations Under Pressure" — Resilient Full-Stack Operations & Incident Management Platform  
**Target Environment:** Python 3.13+, Django 6.1, Django REST Framework 3.18, PostgreSQL 17  

---

## 1. Data Model & Append-Only Activity History

### Context & Requirements
In high-stress operational incident response, tracking ticket mutations without a verifiable audit trail leads to confusion, finger-pointing, and inability to reconstruct critical incident timelines. The application requires an auditable history of status transitions, assignee shifts, priority escalations, and comments.

### Options Considered
1. **Model Field History / Django Simple History (Snapshotting entire rows)**:
   - *Pros*: Drop-in, records complete state of every field.
   - *Cons*: High storage overhead; diffing between versions is expensive; does not inherently capture business event semantics (e.g., distinguishing between a rejection vs. an in-progress transition).
2. **Database Triggers (PostgreSQL Audit Triggers)**:
   - *Pros*: Cannot be bypassed by ORM bugs or raw SQL.
   - *Cons*: Business logic shifts into database scripts, decoupling authorization context (e.g., actor identity, note) from the application layer.
3. **Dedicated Append-Only `ActivityEvent` Model with Structured JSON Payloads (Chosen)**:
   - *Pros*: Explicit, strongly-typed event taxonomy (`created`, `claimed`, `status_changed`, `approved`, `rejected`, `reassigned`, `unassigned`, `priority_changed`, `comment_added`, `field_updated`). Records `actor`, `from_state`, `to_state`, `message`, and timestamp.
   - *Cons*: Requires disciplined service-layer enforcement to ensure every state change generates an event.

### Chosen Approach & Transactional Integrity
We selected the dedicated **Append-Only `ActivityEvent` Model**. All mutations are mediated exclusively through `WorkItemService` within `transaction.atomic()` blocks. The item mutation, version increment, and `ActivityEvent` creation happen in the exact same database transaction. If logging the event fails for any reason, the entire transaction rolls back, guaranteeing zero un-audited state changes.

---

## 2. Concurrency, Locking, and Stale Updates

### Context & Requirements
Under operational pressure, two engineers frequently attempt to claim the same critical unassigned incident at the exact same moment. Additionally, two operators viewing the same ticket concurrently might submit conflicting edits, leading to the "lost update" anomaly.

### Options Considered
1. **Pessimistic Locking (`SELECT FOR UPDATE` on Item Claim) (Chosen for Claims)**:
   - *Pros*: Guarantees mutual exclusion directly at the database engine level. Prevents race conditions before writes happen.
   - *Cons*: Holds row locks for the duration of the transaction; requires low lock contention duration.
2. **Optimistic Concurrency Control (OCC) via Monotonic Version Number (Chosen for Edits/Updates)**:
   - *Pros*: Non-blocking for concurrent readers; perfectly suited for web UIs where users spend minutes inspecting and editing forms before submitting.
   - *Cons*: Requires client reconciliation on conflict.

### Chosen Approach & Implementation Details
We adopted a **Hybrid Concurrency Strategy**:
- **Atomic Claim Protection**:
  In `WorkItemService.claim_item()`, we query `WorkItem.objects.select_for_update().get(id=pk)`. PostgreSQL acquires an exclusive row-level lock on the `workitems_workitem` table.
  ```python
  with transaction.atomic():
      item = WorkItem.objects.select_for_update().get(id=pk)
      if item.assignee is not None:
          raise ConflictError("Work item has already been claimed", ...)
      item.assignee = user
      item.status = WorkItemStatus.IN_PROGRESS
      item.version += 1
      item.save()
  ```
  *Crucial PostgreSQL Edge Case Resolved*: Avoided using `.select_related("assignee")` in conjunction with `select_for_update()` because PostgreSQL 17 disallows row locking on the nullable side of outer joins (`FOR UPDATE cannot be applied to the nullable side of an outer join`).
- **Optimistic Locking on Updates (`version` Precondition)**:
  Every update request (via REST API `PATCH /api/items/<id>/` or form submit) includes the `version` the client read. If `stored_version != submitted_version`, the server aborts with **HTTP 409 Conflict** (`STALE_UPDATE`), returns the fresh server state, and avoids overwriting newer modifications.

---

## 3. Authorization & Team Scoping (RBAC)

### Context & Requirements
Different teams (e.g., Security & Compliance vs. Core Infrastructure) handle sensitive workloads. A global admin or cross-team member must not freely tamper with or inspect restricted team items.

### Options Considered
1. **Django Model-Level Permissions (`django.contrib.auth.models.Permission`)**:
   - *Pros*: Built-in standard.
   - *Cons*: Coarse-grained (global table-level `can_change_workitem`), not scoped per team or membership role.
2. **Third-Party Object Permission Libraries (`django-guardian`)**:
   - *Pros*: Row-level permissions.
   - *Cons*: Heavy database overhead with permission mapping tables; adds unnecessary complexity for an individual student project.
3. **Centralized Service-Layer Permission Matrix (`TeamPermissionService`) (Chosen)**:
   - *Pros*: Explicit, readable, unit-testable in isolation, zero third-party dependencies, centralized in `teams/permissions.py`.
   - *Cons*: Must be referenced consistently across both REST API views and template views.

### Chosen Approach & Role Matrix
We implemented **`TeamPermissionService`** enforcing four hierarchical team roles:
- **Viewer**: Read-only access to items and activity history within the team. Cannot claim, transition, edit, or comment.
- **Member**: Can read items, create new items, claim unassigned items, edit permitted fields, comment, and transition tickets through standard flow (`Open` -> `In Progress` -> `Awaiting Approval`).
- **Lead**: All Member permissions, plus exclusive authority to **Approve** (`Awaiting Approval` -> `Resolved`) or **Reject** back to `In Progress`, and reassign tickets.
- **Admin**: Full administrative authority across the team. Superusers bypass team restrictions globally.

**Restricted Team Boundary Enforcement**:
When `team.is_restricted == True`, users who lack an explicit membership in that team receive **HTTP 403 Forbidden** (or 404 for list isolation) on both read and write attempts.

---

## 4. Search, Pagination, and Database Indexes

### Context & Requirements
Production operation hubs store thousands of tickets. Loading all records to the browser or using un-indexed sequential scans degrades responsiveness under load.

### Options Considered
1. **Full-Text Search Engine (Elasticsearch / Meilisearch)**:
   - *Pros*: Typo tolerance, ranking.
   - *Cons*: Heavy operational overhead, requires external services and sync workers.
2. **PostgreSQL Native Full-Text Search / GIN Indexing vs. B-Tree Filtering (Chosen)**:
   - *Pros*: Standard PostgreSQL capabilities, deterministic, low operational footprint.
3. **Server-Side Deterministic Pagination**:
   - Explicit page-size limit (10 items per page) with ordering by `-created_at, -id` to guarantee deterministic pagination without duplicate or missing items across page boundaries.

### Index Strategy (`workitems/models.py`)
- `db_index=True` on `status`, `priority`, `type`, and `due_date`.
- Composite B-Tree indexes:
  - `["team", "status"]`: Speeds up team-filtered dashboard queries.
  - `["assignee", "status"]`: Accelerates the "Assigned to Me" queue.
  - `["status", "priority"]`: Optimizes "Unassigned Urgent" incident detection.
  - `["created_at", "id"]`: Guarantees deterministic, fast pagination traversal.

---

## 5. Synchronous vs. Asynchronous Work: Transactional Outbox Pattern

### Context & Requirements
When an incident is created or approved, downstream notifications (e.g., Slack/PagerDuty webhooks, email alerts) must be dispatched. Performing external HTTP calls synchronously inside the database transaction risks thread starvation, slow response times, and failure if the external endpoint is unreachable. Conversely, sending notifications in background threads *without* transactional guarantees risks sending alerts for database transactions that ultimately rolled back.

### Options Considered
1. **Direct Celery / Redis Task Scheduling inside View**:
   - *Cons*: "Dual-write" problem — task may queue even if DB commit fails, or DB commits but Redis publish fails.
2. **Transactional Outbox Pattern with DB Storage (Chosen)**:
   - *Pros*: Zero dual-write risk; outbox record is inserted in the exact same PostgreSQL transaction as the item state change.
   - *Cons*: Requires an outbox processing worker.

### Chosen Approach & Implementation
- An `OutboxMessage` table stores payload, topic, retry count, status (`pending`, `delivered`, `failed`), and last error.
- Background delivery worker implemented as a Django management command `python manage.py process_outbox`.
- Supports `--once` for cron jobs, `--batch-size`, and exponential backoff retry handling with a maximum attempt threshold (3 attempts) before marking `failed`.

---

## 6. Scope Intentionally Excluded

To keep the application robust, maintainable, and aligned with the challenge's core focus on correctness under pressure:
1. **Public User Registration**: Seeded enterprise accounts simulate an internal corporate directory (LDAP/SSO model). Public registration is omitted.
2. **Heavy Single Page Application Framework (React/Angular)**: Vanilla JavaScript with server-rendered Django templates eliminates build-step dependencies, bundle hydration bugs, and client-server desynchronization.
3. **External Message Brokers (Kafka/RabbitMQ)**: Replaced with the database-backed Transactional Outbox pattern, providing rock-solid atomicity without external broker failure modes.

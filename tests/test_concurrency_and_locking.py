import threading
import pytest
from rest_framework import status
from django.db import connection
from workitems.models import WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType
from workitems.services import WorkItemService, ConflictError


@pytest.mark.django_db(transaction=True)
def test_concurrent_claims_exactly_one_succeeds(setup_environment, auth_client):
    """
    CRITICAL CONCURRENCY TEST:
    Two users claiming the same unassigned item simultaneously cannot both succeed.
    One succeeds (HTTP 200), and the other fails with HTTP 409 Conflict.
    """
    env = setup_environment

    item = WorkItem.objects.create(
        title="Concurrent Triage Race Target",
        description="Ticket subjected to simulated simultaneous claim race",
        type=WorkItemType.INCIDENT,
        priority=WorkItemPriority.URGENT,
        status=WorkItemStatus.OPEN,
        team=env["open_team"],
        creator=env["open_lead"],
        assignee=None,  # Unassigned
        version=1,
    )

    results = []
    barrier = threading.Barrier(2)

    def attempt_claim(user, client):
        connection.close()  # Ensure clean thread connection
        barrier.wait()  # Synchronize start to create simultaneous race condition
        resp = client.post(f"/api/items/{item.id}/claim/")
        results.append((user.username, resp.status_code, resp.json()))
        connection.close()

    client1 = auth_client(env["open_lead"])
    client2 = auth_client(env["open_member"])

    t1 = threading.Thread(target=attempt_claim, args=(env["open_lead"], client1))
    t2 = threading.Thread(target=attempt_claim, args=(env["open_member"], client2))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    status_codes = [r[1] for r in results]
    assert len(status_codes) == 2

    # Exactly one 200 and one 409
    assert status.HTTP_200_OK in status_codes, f"Expected one 200 OK, got {status_codes}"
    assert status.HTTP_409_CONFLICT in status_codes, f"Expected one 409 Conflict, got {status_codes}"

    # Verify database state
    item.refresh_from_db()
    assert item.assignee is not None
    assert item.status == WorkItemStatus.IN_PROGRESS
    assert item.version == 2


@pytest.mark.django_db
def test_stale_update_returns_409_conflict(setup_environment, auth_client):
    """
    CRITICAL CORRECTNESS TEST:
    Optimistic locking with version precondition.
    If stored version differs from expected version, returns HTTP 409 Conflict,
    preserves latest data, and returns current version in the response.
    """
    env = setup_environment
    item = WorkItem.objects.create(
        title="Initial Document Version",
        description="Original scope",
        type=WorkItemType.TASK,
        priority=WorkItemPriority.LOW,
        status=WorkItemStatus.OPEN,
        team=env["open_team"],
        creator=env["open_member"],
        version=1,
    )

    client1 = auth_client(env["open_member"])
    client2 = auth_client(env["open_lead"])

    # Client 1 updates item from version 1 -> version 2
    resp1 = client1.patch(
        f"/api/items/{item.id}/",
        {"title": "Updated by Client 1", "version": 1},
        format="json",
    )
    assert resp1.status_code == status.HTTP_200_OK
    assert resp1.json()["version"] == 2

    # Client 2 attempts to update using stale version 1
    resp2 = client2.patch(
        f"/api/items/{item.id}/",
        {"title": "Stale Overwrite Attempt", "version": 1},
        format="json",
    )
    assert resp2.status_code == status.HTTP_409_CONFLICT
    err_data = resp2.json()
    assert err_data["error"] == "Conflict"
    assert err_data["code"] == "STALE_UPDATE"
    assert err_data["current_version"] == 2

    # Verify latest database data was NOT overwritten
    item.refresh_from_db()
    assert item.title == "Updated by Client 1"
    assert item.version == 2

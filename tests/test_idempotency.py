import pytest
from rest_framework import status
from workitems.models import WorkItem, WorkItemPriority, WorkItemType


@pytest.mark.django_db
def test_repeated_idempotency_key_creates_only_one_item(setup_environment, auth_client):
    """
    CRITICAL CORRECTNESS TEST:
    Support an Idempotency-Key for create requests.
    Repeating the same key must NOT create another item and returns a consistent response.
    """
    env = setup_environment
    client = auth_client(env["open_member"])

    idempotency_key = "unique-client-key-84839201"
    payload = {
        "title": "Idempotent Work Item Creation",
        "description": "Verifying repeated key replay behavior",
        "type": WorkItemType.TASK,
        "priority": WorkItemPriority.HIGH,
        "team_id": env["open_team"].id,
    }

    # First request
    resp1 = client.post(
        "/api/items/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )
    assert resp1.status_code == status.HTTP_201_CREATED
    data1 = resp1.json()
    item_id = data1["id"]

    # Verify only 1 item exists in DB
    assert WorkItem.objects.filter(title="Idempotent Work Item Creation").count() == 1

    # Second request with identical key (simulating network retry)
    resp2 = client.post(
        "/api/items/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )
    assert resp2.status_code == status.HTTP_200_OK
    assert resp2.headers.get("Idempotent-Replay") == "true"
    data2 = resp2.json()

    # Must return identical item ID
    assert data2["id"] == item_id
    assert data2["title"] == data1["title"]

    # Still only 1 item in DB
    assert WorkItem.objects.filter(title="Idempotent Work Item Creation").count() == 1

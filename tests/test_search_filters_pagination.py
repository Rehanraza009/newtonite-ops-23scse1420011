import pytest
from rest_framework import status
from workitems.models import WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType


@pytest.mark.django_db
def test_server_side_search_and_filtering(setup_environment, auth_client):
    """
    Verifies server-side search across title/description, plus status/priority/type filters.
    """
    env = setup_environment
    client = auth_client(env["open_member"])

    # Create distinct items
    WorkItem.objects.create(
        title="Kafka Broker Rebalance Stalled",
        description="Consumer groups experiencing partition lag",
        type=WorkItemType.INCIDENT,
        priority=WorkItemPriority.URGENT,
        status=WorkItemStatus.OPEN,
        team=env["open_team"],
        creator=env["open_member"],
    )
    WorkItem.objects.create(
        title="PostgreSQL Autovacuum Freeze",
        description="Transaction ID wraparound warning on node 2",
        type=WorkItemType.INCIDENT,
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.IN_PROGRESS,
        team=env["open_team"],
        creator=env["open_member"],
    )
    WorkItem.objects.create(
        title="Routine SSL Certificate Renewal",
        description="Renew wildcard cert for internal domains",
        type=WorkItemType.TASK,
        priority=WorkItemPriority.LOW,
        status=WorkItemStatus.OPEN,
        team=env["open_team"],
        creator=env["open_member"],
    )

    # 1. Search for "Kafka"
    resp = client.get("/api/items/?q=Kafka")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["count"] == 1
    assert data["results"][0]["title"] == "Kafka Broker Rebalance Stalled"

    # 2. Search for "wraparound" in description
    resp = client.get("/api/items/?q=wraparound")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["count"] == 1
    assert resp.json()["results"][0]["title"] == "PostgreSQL Autovacuum Freeze"

    # 3. Filter by priority=urgent
    resp = client.get("/api/items/?priority=urgent")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["count"] == 1

    # 4. Filter by status=open
    resp = client.get("/api/items/?status=open")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["count"] == 2


@pytest.mark.django_db
def test_deterministic_pagination(setup_environment, auth_client):
    """
    Verifies deterministic server-side pagination with page boundaries.
    """
    env = setup_environment
    client = auth_client(env["open_member"])

    # Create 15 items
    for i in range(15):
        WorkItem.objects.create(
            title=f"Bulk Task #{i:02d}",
            type=WorkItemType.TASK,
            priority=WorkItemPriority.MEDIUM,
            status=WorkItemStatus.OPEN,
            team=env["open_team"],
            creator=env["open_member"],
        )

    # Page 1 (limit 10)
    resp1 = client.get("/api/items/?page=1")
    assert resp1.status_code == status.HTTP_200_OK
    data1 = resp1.json()
    assert data1["count"] == 15
    assert len(data1["results"]) == 10
    assert data1["next"] is not None
    assert data1["previous"] is None

    # Page 2
    resp2 = client.get("/api/items/?page=2")
    assert resp2.status_code == status.HTTP_200_OK
    data2 = resp2.json()
    assert len(data2["results"]) == 5
    assert data2["next"] is None
    assert data2["previous"] is not None

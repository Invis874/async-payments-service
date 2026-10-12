import pytest


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_payment_requires_api_key(client):
    r = await client.post(
        "/api/v1/payments",
        json={
            "amount": "100.00",
            "currency": "USD",
            "webhook_url": "https://example.com/hook",
        },
        headers={"Idempotency-Key": "k1"},
    )
    assert r.status_code == 422  # отсутствует X-API-Key


@pytest.mark.asyncio
async def test_create_payment_requires_idempotency_key(client, api_headers):
    r = await client.post(
        "/api/v1/payments",
        json={
            "amount": "100.00",
            "currency": "USD",
            "webhook_url": "https://example.com/hook",
        },
        headers=api_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_payment_success(client, idempotency_headers):
    payload = {
        "amount": "100.50",
        "currency": "USD",
        "description": "Test",
        "metadata": {"order_id": "42"},
        "webhook_url": "https://example.com/hook",
    }
    r = await client.post(
        "/api/v1/payments", json=payload, headers=idempotency_headers
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    assert "payment_id" in body

    # Проверяем GET
    payment_id = body["payment_id"]
    r2 = await client.get(f"/api/v1/payments/{payment_id}", headers=idempotency_headers)
    assert r2.status_code == 200
    detail = r2.json()
    assert detail["amount"] == "100.50"
    assert detail["currency"] == "USD"
    assert detail["metadata"] == {"order_id": "42"}
    assert detail["status"] == "pending"


@pytest.mark.asyncio
async def test_get_payment_not_found(client, api_headers):
    r = await client.get(
        "/api/v1/payments/00000000-0000-0000-0000-000000000000",
        headers=api_headers,
    )
    assert r.status_code == 404
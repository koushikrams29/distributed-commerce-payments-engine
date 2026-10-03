"""End-to-end check of a running stack, entirely through the dashboard's public port.

    cd infra && docker compose -f docker-compose.yml -f docker-compose.app.yml up -d --build --wait
    python scripts/smoke_test.py

Places an order as the seeded shopper and waits for the saga to fulfil it,
while the seeded admin watches the live dashboard socket. Exits non-zero on
the first failed check.
"""

import argparse
import asyncio
import json
import re
import sys
import time
import uuid

import httpx
import websockets

SHOPPER = ("shopper@example.com", "shopper-pass-123")
ADMIN = ("admin@example.com", "admin-pass-123")
FINAL_STATUSES = {"fulfilled", "cancelled", "failed"}


class SmokeTestFailure(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeTestFailure(message)
    print(f"ok    {message}")


def login(client: httpx.Client, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    check(response.status_code == 200, f"{email} can log in")
    return response.json()["access_token"]


def check_static_files(client: httpx.Client) -> None:
    index = client.get("/")
    check(index.status_code == 200, "dashboard page is served")
    check(index.headers.get("cache-control") == "no-cache", "dashboard page is revalidated, not cached")

    asset = re.search(r'/assets/[^"]+\.js', index.text)
    check(asset is not None, "dashboard page references a bundled script")
    cache_control = client.get(asset.group(0)).headers.get("cache-control", "")
    check("immutable" in cache_control, "fingerprinted assets are cached as immutable")

    check(client.get("/orders/some-client-route").status_code == 200, "unknown paths fall back to the app")


def first_product_in_stock(client: httpx.Client, admin_token: str) -> str:
    response = client.get("/api/v1/products", headers={"Authorization": f"Bearer {admin_token}"})
    check(response.status_code == 200, "admin can list products through the gateway")
    body = response.json()
    products = body["items"] if isinstance(body, dict) else body
    in_stock = [p for p in products if p["stock_qty"] > 0]
    check(bool(in_stock), "a seeded product is in stock")
    return in_stock[0]["id"]


async def run(base_url: str, timeout: float) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        check_static_files(client)
        admin_token = login(client, *ADMIN)
        shopper_token = login(client, *SHOPPER)
        shopper = {"Authorization": f"Bearer {shopper_token}"}

        socket_url = re.sub(r"^http", "ws", base_url) + "/ws/dashboard"
        async with websockets.connect(socket_url) as socket:
            await socket.send(json.dumps({"type": "auth", "token": admin_token}))
            ready = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
            check(ready.get("type") == "ready", "dashboard socket upgrades through the proxy and authenticates")

            product_id = first_product_in_stock(client, admin_token)
            response = client.post(
                "/api/v1/orders",
                headers=shopper,
                json={
                    "idempotency_key": f"smoke-{uuid.uuid4()}",
                    "items": [{"product_id": product_id, "qty": 1}],
                },
            )
            check(response.status_code == 201, "shopper can place an order")
            order_id = response.json()["id"]

            events: list[str] = []
            status = response.json()["status"]
            deadline = time.monotonic() + timeout
            while status not in FINAL_STATUSES and time.monotonic() < deadline:
                try:
                    message = json.loads(await asyncio.wait_for(socket.recv(), timeout=1))
                    events.append(message.get("event_type", message.get("type", "?")))
                except TimeoutError:
                    pass
                status = client.get(f"/api/v1/orders/{order_id}", headers=shopper).json()["status"]

            check(status == "fulfilled", f"order {order_id} is fulfilled (last status: {status})")
            check("order.created" in events, f"dashboard streamed the saga live ({len(events)} events)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--timeout", type=float, default=90, help="seconds to wait for the saga")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.base_url.rstrip("/"), args.timeout))
    except SmokeTestFailure as failure:
        sys.exit(f"FAIL  {failure}")
    print("Smoke test passed.")


if __name__ == "__main__":
    main()

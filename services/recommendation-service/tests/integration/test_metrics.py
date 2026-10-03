import uuid

from fastapi.testclient import TestClient

from tests.helpers import auth_header


def test_metrics_label_requests_by_route_template(client: TestClient) -> None:
    product_id = uuid.uuid4()
    client.get(f"/recommendations/{product_id}", headers=auth_header())

    body = client.get("/metrics").text

    assert (
        'http_requests_total{method="GET",route="/recommendations/{product_id}",status="200"}'
        in body
    )
    assert str(product_id) not in body

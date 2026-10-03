from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session")
def rabbitmq_url() -> Iterator[str]:
    from testcontainers.community.rabbitmq import RabbitMqContainer

    # Same image as infra/docker-compose.yml.
    with RabbitMqContainer("rabbitmq:3-management") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5672)
        yield f"amqp://guest:guest@{host}:{port}/"

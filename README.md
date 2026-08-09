# Distributed Commerce & Payments Engine

> Not another Amazon clone — the backend architecture that would actually run one.

[![CI](https://github.com/koushikrams29/distributed-commerce-payments-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/koushikrams29/distributed-commerce-payments-engine/actions/workflows/ci.yml)

📄 **[Product Requirements (PRD)](./docs/PRD.md)** — what the system does, end-to-end user/failure flows, functional requirements.
🏗️ **[Architecture & Technical Design](./docs/ARCHITECTURE.md)** — services, data model, event contracts, full repo scaffold.

## 1. What this is and why it exists

A pure backend, event-driven microservices platform that simulates the core of a real e-commerce + payments system: order lifecycle management, inventory reservation under concurrency, idempotent payment processing, async notifications, and a lightweight recommendation service — all wired together with the reliability patterns (outbox, idempotency keys, distributed locks, rate limiting, distributed tracing) that separate a "CRUD demo" from a system that could survive production traffic.

This project exists to prove one thing under adversarial interview questioning: **I can design and operate a coherent distributed system, not just five apps that happen to share a database.** Every service reuses the same auth, observability, CI/CD, and testing conventions on purpose — the goal is architectural depth, not surface area.

**Status:** 🚧 In progress — Week 1 of build (Phase 1, Weeks 1–8).

## 2. Architecture

```mermaid
graph TD
    Client[React Admin Dashboard] -->|HTTPS| Gateway[FastAPI Gateway / Auth]
    Gateway --> OrderSvc[Order Service]
    Gateway --> InventorySvc[Inventory Service]
    OrderSvc -->|publish| Outbox[(Outbox Table)]
    Outbox -->|relay| Broker[[RabbitMQ]]
    Broker --> PaymentSvc[Payment Service]
    Broker --> NotificationSvc[Notification Service]
    Broker --> RecoSvc[Recommendation Service]
    PaymentSvc -->|SELECT FOR UPDATE + Redlock| Ledger[(Ledger / Postgres)]
    InventorySvc -->|row-level locking| InvDB[(Inventory / Postgres)]
    OrderSvc --> OrderDB[(Orders / Postgres)]
    Gateway -. traces .-> OTel[OpenTelemetry Collector]
    OTel --> Grafana[Prometheus + Grafana]
```

Full architecture, data model, and scaffold: [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md). Full end-to-end flow (happy path + failure/compensation paths): [`docs/PRD.md`](./docs/PRD.md).

## 3. Key engineering decisions & trade-offs

_This section is the living log of "why," not just "what." Full log with reasoning in [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md#13-key-decisions-log) — summarized here._

| Decision | Why | Trade-off accepted |
|---|---|---|
| RabbitMQ over Kafka | Lower operational complexity for a first solo distributed system; still demonstrates outbox/retry/DLQ fully | Less "impressive" than Kafka for partition/consumer-group interview questions — documented as a possible v2 migration |
| `SELECT FOR UPDATE` + Redis Redlock for payment idempotency | Prevent double-spend under concurrent requests | Added write contention under high load |
| Token Bucket in Redis for rate limiting | Simple, well-understood, fast | Not as fair as sliding-window under bursty traffic |
| Saga via orchestration, not choreography | Easier to reason about/debug when implementing the pattern for the first time | Order Service becomes a more central/coupled coordinator |

## 4. Services

- **Order Service** — order lifecycle, saga orchestration across services
- **Inventory Service** — stock reservation with row-level locking to prevent overselling
- **Payment Service** (mocked gateway) — idempotent payment processing, double-spend prevention, ledger-style transaction log
- **Notification Service** — async email/notification dispatch via queue consumers
- **Recommendation Service** — lightweight collaborative-filtering / rules-based recommender
- **Admin Dashboard** (React) — order monitoring, inventory management, live metrics

## 5. Cross-cutting engineering

- Outbox pattern (Postgres → RabbitMQ/Kafka)
- Idempotency keys on all mutating endpoints
- Token Bucket rate limiting in Redis
- OpenTelemetry trace correlation (HTTP → workers → SQL)
- Prometheus + Grafana dashboards
- Full test suite (unit + integration + testcontainers), CI-gated merges
- Docker Compose for local dev; deployed to Render/Railway + Vercel

## 6. Tech stack

Python, FastAPI, PostgreSQL, Redis, RabbitMQ/Kafka, React + TypeScript, Docker, GitHub Actions, OpenTelemetry, Prometheus/Grafana.

## 7. Getting started

```bash
# Placeholder — filled in once the Docker Compose scaffold exists
docker-compose up --build
```

## 8. Test coverage / CI

[![CI](https://img.shields.io/badge/CI-not_yet_configured-lightgrey)]()
[![Coverage](https://img.shields.io/badge/coverage-not_yet_configured-lightgrey)]()

## 9. Demo

_Screenshots / demo GIF / walkthrough video will be added once the system is live._

# Phase 1: Foundation — High-Level Design

> **Objective:** Take the prototype to production-grade. Persistent memory, authentication, multi-tenancy, tool registry, observability, and cost tracking.

---

## Team Thinking

**Product Lead:** "The prototype proved the concept. Now we need it running 24/7, serving multiple teams, with visibility into what agents are doing and how much they cost. No more 'it works on my cluster.'"

**Platform Engineer:** "This is where we earn our keep. Persistent state means databases. Multi-tenancy means isolation. Observability means tracing every agent decision. I need to design the data layer properly."

**Backend Engineer:** "The agent loop from Phase 0 was solid but brittle. I need to refactor it into a proper service — async execution, structured logging, graceful shutdown, health checks that actually mean something."

**SRE:** "I'm joining the team now. My job is to make sure this thing doesn't page us at 3am. That means proper alerting, runbooks, and capacity planning."

**Security Engineer:** "No more 'auth: none.' Every request gets authenticated. Every agent is scoped to a tenant. API keys are rotated. Secrets are never in plaintext."

---

## High-Level Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        UI[Chat UI<br/>React]
        CLI[API Clients]
        SDK[Python SDK]
    end

    subgraph "EKS Cluster"
        subgraph "Ingress & Auth"
            KONG[Kong API Gateway]
            AUTH[Auth Service<br/>JWT Validation]
        end

        subgraph "Core Services"
            AGENT_SVC[Agent Service<br/>FastAPI — Async]
            TOOL_REGISTRY_SVC[Tool Registry Service]
        end

        subgraph "Agent Runtime"
            AGENT_LOOP[Agent Loop<br/>Refactored v2]
            LLM_CLIENT[LLM Client<br/>LiteLLM + Fallback]
            TOOL_EXEC[Tool Executor<br/>Sandboxed]
        end

        subgraph "Data Layer"
            REDIS[Redis<br/>Session State & Cache]
            POSTGRES[PostgreSQL<br/>Tool Registry, Tenants,<br/>Usage Logs]
            VECTOR_DB[Vector Store<br/>pgvector or Qdrant]
        end

        subgraph "Observability"
            OTEL[OpenTelemetry<br/>Collector]
            PROM[Prometheus]
            GRAFANA[Grafana]
            LOKI[Loki<br/>Log Aggregation]
        end
    end

    subgraph "External"
        LLM[LLM Providers]
        ESO[External Secrets<br/>AWS Secrets Manager]
    end

    UI --> KONG
    CLI --> KONG
    SDK --> KONG
    KONG --> AUTH
    AUTH --> AGENT_SVC
    AGENT_SVC --> AGENT_LOOP
    AGENT_LOOP --> LLM_CLIENT
    AGENT_LOOP --> TOOL_EXEC
    TOOL_EXEC --> TOOL_REGISTRY_SVC
    TOOL_REGISTRY_SVC --> POSTGRES
    AGENT_SVC --> REDIS
    AGENT_SVC --> VECTOR_DB
    LLM_CLIENT --> LLM
    ESO --> POSTGRES

    AGENT_SVC --> OTEL
    OTEL --> PROM
    OTEL --> LOKI
    PROM --> GRAFANA
    LOKI --> GRAFANA
```

---

## Multi-Tenancy Model

```mermaid
graph TD
    subgraph "Tenant: Team Alpha"
        A_KEY[API Key: ak_alpha_xxx]
        A_AGENTS[Their Agents]
        A_TOOLS[Their Tools]
        A_MEMORY[Their Memory]
        A_USAGE[Their Usage Quota]
    end

    subgraph "Tenant: Team Beta"
        B_KEY[API Key: ak_beta_xxx]
        B_AGENTS[Their Agents]
        B_TOOLS[Their Tools + Shared Tools]
        B_MEMORY[Their Memory]
        B_USAGE[Their Usage Quota]
    end

    subgraph "Shared"
        SHARED_TOOLS[Platform Tools<br/>web_search, calculator]
    end

    A_TOOLS --> SHARED_TOOLS
    B_TOOLS --> SHARED_TOOLS
```

| Isolation Level | What's Isolated | Implementation |
|----------------|-----------------|----------------|
| **API Keys** | Each tenant has unique keys | Kong consumer groups |
| **Data** | Sessions, memory, logs | Tenant ID column in every table |
| **Tools** | Custom tools per tenant + shared catalog | Tool ownership in registry |
| **Costs** | Token usage tracked per tenant | Metering middleware |
| **Rate Limits** | Per-tenant rate limits | Kong rate limiting plugin |

---

## Component Ownership

| Component | Team | Responsibility |
|-----------|------|---------------|
| **Kong Gateway** | Platform | Routing, rate limiting, SSL termination |
| **Auth Service** | Security | JWT validation, API key management |
| **Agent Service v2** | Backend | Async agent execution, session management |
| **Tool Registry** | Backend | CRUD for tools, schema validation |
| **Redis** | Platform | Deployment, backup, monitoring |
| **PostgreSQL** | Platform | Deployment, migrations, backup |
| **Vector Store** | Backend + Platform | Schema design + operational management |
| **Observability Stack** | SRE | Dashboards, alerts, runbooks |
| **Cost Tracking** | Backend + Product | Metering logic + reporting UI |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| API Gateway | Kong (OSS) | Already in Kubernetes ecosystem, plugin system for auth/rate-limit |
| Database | PostgreSQL (RDS) | Reliable, already operational, pgvector for embeddings |
| Cache/State | Redis (ElastiCache) | Session store, LLM response cache, pub/sub for async |
| Vector Store | pgvector (in Postgres) | One less database to manage, good enough for Phase 1 scale |
| Observability | OpenTelemetry → Prometheus + Grafana + Loki | Standard stack, already partially deployed |
| Auth | API Keys → JWT | Simple to start, JWT for service-to-service auth |
| Async execution | FastAPI background tasks + Redis queue | Lightweight — no Celery yet |

---

## SLA Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| API availability | 99.9% | Uptime of `/health` endpoint |
| Agent response latency (p95) | < 10 seconds | End-to-end including LLM calls |
| Tool registry CRUD | < 200ms p99 | Database operations |
| Error rate | < 1% | Non-4xx server errors |
| Data durability | 99.99% | PostgreSQL with daily backups |

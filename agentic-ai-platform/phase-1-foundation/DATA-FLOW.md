# Phase 1: Foundation — Data Flow Diagrams

> **Objective:** Trace every data path through the production-grade system — auth, state, memory, metering, observability.

---

## 1. Authenticated Request Flow

```mermaid
sequenceDiagram
    actor User
    participant Kong as Kong API Gateway
    participant Auth as Auth Service
    participant Redis as Redis
    participant Agent as Agent Service
    participant PG as PostgreSQL
    participant LLM as LLM Provider

    User->>Kong: POST /api/v1/agent/run<br/>X-API-Key: ak_alpha_xxx

    rect rgb(255, 240, 240)
        Note over Kong,Auth: Authentication & Rate Limiting
        Kong->>Kong: Check rate limit (Redis counter)
        Kong->>Auth: Validate API key
        Auth->>PG: SELECT * FROM api_keys WHERE key_hash = hash(key)
        PG-->>Auth: Key record + tenant_id + scopes
        Auth-->>Kong: ✓ Valid — tenant: alpha, scopes: [agent:run]
        Kong->>Kong: Inject headers: X-Tenant-ID, X-Scopes
    end

    rect rgb(240, 248, 255)
        Note over Kong,Agent: Request Processing
        Kong->>Agent: Forward request + tenant context
        Agent->>Redis: Load session (if session_id provided)
        Redis-->>Agent: Previous messages (or empty)
        Agent->>Agent: Start agent loop
    end

    rect rgb(240, 255, 240)
        Note over Agent,LLM: Agent Execution
        Agent->>LLM: Chat completion (messages + tools)
        LLM-->>Agent: Tool call or final answer
        Agent->>Agent: Execute tool if needed
        Agent->>LLM: Follow-up with tool result
        LLM-->>Agent: Final answer
    end

    rect rgb(255, 255, 240)
        Note over Agent,PG: Post-Processing
        Agent->>Redis: Save updated session
        Agent->>PG: Write usage log (tokens, cost)
        Agent->>PG: Write tool usage log
    end

    Agent-->>Kong: HTTP 200 + JSON response
    Kong-->>User: Response with trace headers
```

---

## 2. Memory Read/Write Flow

```mermaid
flowchart TB
    subgraph "Write Path (after each agent run)"
        W1[Agent produces<br/>final answer] --> W2[Extract key information<br/>from conversation]
        W2 --> W3[Generate embedding<br/>via LLM embedding API]
        W3 --> W4[Write to pgvector<br/>with tenant_id + metadata]
        W1 --> W5[Save full conversation<br/>to Redis with TTL]
    end

    subgraph "Read Path (at start of each agent run)"
        R1[New user prompt arrives] --> R2{Session exists?}
        R2 -->|Yes| R3[Load conversation from Redis]
        R2 -->|No| R4[Start fresh session]

        R1 --> R5[Embed user prompt]
        R5 --> R6[Vector search in pgvector<br/>WHERE tenant_id = current<br/>ORDER BY cosine similarity<br/>LIMIT 5]
        R6 --> R7[Relevant past memories]

        R3 --> R8[Build context]
        R4 --> R8
        R7 --> R8
        R8 --> R9[Inject into system prompt<br/>as 'relevant context']
    end
```

---

## 3. Tool Registry Data Flow

```mermaid
sequenceDiagram
    actor Developer as Tool Developer
    participant API as Tool Registry API
    participant PG as PostgreSQL
    participant Cache as Redis Cache
    participant Agent as Agent Loop

    Note over Developer,Agent: Tool Registration
    Developer->>API: POST /api/v1/tools<br/>{name, description, schema, endpoint}
    API->>API: Validate JSON schema
    API->>PG: INSERT INTO tools
    API->>Cache: Invalidate tool list cache
    API-->>Developer: 201 Created {tool_id}

    Note over Developer,Agent: Agent Uses Tools at Runtime
    Agent->>Cache: Get available tools for tenant
    alt Cache hit
        Cache-->>Agent: Tool list + schemas
    else Cache miss
        Agent->>PG: SELECT * FROM tools<br/>WHERE tenant_id = ? OR tenant_id IS NULL
        PG-->>Agent: Tool records
        Agent->>Cache: Cache with 5min TTL
    end

    Agent->>Agent: Include tool schemas in LLM call
    Agent->>Agent: LLM says: call tool X
    Agent->>Agent: Lookup tool X execution config
    Agent->>Agent: Execute tool (builtin/HTTP/gRPC)
```

---

## 4. Cost & Metering Data Flow

```mermaid
flowchart TD
    subgraph "Real-time Metering"
        A[Every LLM call] --> B[Extract token counts<br/>from response]
        B --> C[Calculate cost<br/>using pricing table]
        C --> D[INCR Redis counter<br/>tenant:{id}:tokens:daily]
        C --> E[INSERT into usage_logs<br/>in PostgreSQL]
    end

    subgraph "Budget Enforcement"
        D --> F{Daily tokens ><br/>tenant budget?}
        F -->|No| G[Allow next request]
        F -->|Yes, soft limit| H[Log warning<br/>Notify tenant admin]
        F -->|Yes, hard limit| I[Reject request<br/>HTTP 429 with reason]
    end

    subgraph "Reporting (Async)"
        E --> J[Nightly aggregation job]
        J --> K[tenant_usage_daily table]
        K --> L[Grafana cost dashboard]
        K --> M[Monthly billing report]
    end
```

---

## 5. Observability Data Flow

```mermaid
flowchart LR
    subgraph "Application Layer"
        APP[Agent Service]
        APP -->|traces| OTEL_SDK[OTel SDK]
        APP -->|metrics| PROM_CLIENT[Prometheus Client]
        APP -->|logs| STDOUT[Structured JSON logs]
    end

    subgraph "Collection Layer"
        OTEL_SDK --> OTEL_COLLECTOR[OTel Collector<br/>DaemonSet]
        PROM_CLIENT --> PROM_SCRAPE[Prometheus Scrape]
        STDOUT --> FLUENTBIT[Fluent Bit<br/>DaemonSet]
    end

    subgraph "Storage Layer"
        OTEL_COLLECTOR --> TEMPO[Tempo<br/>Trace Storage]
        PROM_SCRAPE --> PROM[Prometheus<br/>Metrics Storage]
        FLUENTBIT --> LOKI[Loki<br/>Log Storage]
    end

    subgraph "Visualization"
        TEMPO --> GRAFANA[Grafana]
        PROM --> GRAFANA
        LOKI --> GRAFANA
    end

    subgraph "Alerting"
        PROM --> ALERTMANAGER[Alertmanager]
        ALERTMANAGER --> SLACK[Slack]
        ALERTMANAGER --> PAGERDUTY[PagerDuty]
    end
```

---

## 6. Secret Management Flow

```mermaid
flowchart LR
    subgraph "AWS"
        ASM[AWS Secrets Manager<br/>LLM API keys<br/>DB passwords<br/>Search API keys]
    end

    subgraph "EKS Cluster"
        ESO[External Secrets Operator]
        K8S_SECRET[Kubernetes Secret]
        POD[Agent Service Pod]
    end

    ASM -->|sync every 1 min| ESO
    ESO -->|creates/updates| K8S_SECRET
    K8S_SECRET -->|mounted as env vars| POD

    style ASM fill:#ff9900
    style ESO fill:#326ce5
```

| Secret | Source | Mounted As |
|--------|--------|-----------|
| `OPENAI_API_KEY` | AWS Secrets Manager | Env var |
| `ANTHROPIC_API_KEY` | AWS Secrets Manager | Env var |
| `DATABASE_URL` | AWS Secrets Manager | Env var |
| `REDIS_URL` | AWS Secrets Manager | Env var |
| `SEARCH_API_KEY` | AWS Secrets Manager | Env var |

---

## 7. Database Migration Flow

```mermaid
flowchart TD
    A[Developer writes migration<br/>using Alembic] --> B[PR merged to main]
    B --> C[ArgoCD detects change]
    C --> D[Pre-sync hook runs<br/>migration Job]
    D --> E{Migration succeeds?}
    E -->|Yes| F[ArgoCD deploys<br/>new application version]
    E -->|No| G[Rollback migration<br/>Alert team]
    G --> H[Deployment blocked]
```

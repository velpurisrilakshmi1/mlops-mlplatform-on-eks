# Phase 4: Developer Experience — Data Flow Diagrams

> **Objective:** Trace every interaction path — from developer action to platform response — across portal, CLI, SDK, and playground.

---

## 1. Developer Onboarding Flow — Zero to First Agent

```mermaid
sequenceDiagram
    actor Dev as New Developer
    participant Portal as Developer Portal
    participant IDP as SSO Provider
    participant API as Management API
    participant Template as Template Service
    participant K8s as Kubernetes
    participant Agent as Agent Runtime
    participant PG as Playground

    rect rgb(240, 248, 255)
        Note over Dev,IDP: Step 1 — Sign In
        Dev->>Portal: Navigate to portal
        Portal->>IDP: SSO redirect
        Dev->>IDP: Authenticate
        IDP-->>Portal: Token (tenant: alpha)
    end

    rect rgb(240, 255, 240)
        Note over Dev,Template: Step 2 — Choose Template
        Portal->>Template: GET /templates
        Template-->>Portal: List of starter templates
        Dev->>Portal: Select "RAG Research Assistant"
        Portal->>Template: GET /templates/rag-assistant
        Template-->>Portal: Template with defaults
    end

    rect rgb(255, 255, 240)
        Note over Dev,K8s: Step 3 — Configure & Deploy
        Dev->>Portal: Customize name, model, tools
        Portal->>API: POST /agents (from template)
        API->>API: Validate against tenant quotas
        API->>K8s: Create Agent CRD
        K8s-->>API: Agent deployed
        API-->>Portal: Status: running
    end

    rect rgb(255, 240, 255)
        Note over Dev,Agent: Step 4 — Test in Playground
        Dev->>Portal: Click "Try in Playground"
        Portal->>PG: Create playground session
        PG-->>Portal: Session ready
        Dev->>Portal: "What does our Q3 report say about growth?"
        Portal->>Agent: POST /agent/run (playground mode)
        Agent-->>Portal: Streaming response + steps
        Portal-->>Dev: Answer with reasoning visible
    end
```

---

## 2. CLI → Platform Data Flow

```mermaid
flowchart TD
    subgraph "Developer Machine"
        CLI[agentctl CLI]
        CONFIG[~/.agentctl/config.yaml<br/>api_url, api_key, tenant]
    end

    subgraph "Network"
        TLS[HTTPS / TLS 1.3]
    end

    subgraph "Platform (EKS)"
        GW[API Gateway<br/>Kong]
        AUTH[Auth validation]
        MGMT[Management API]
        RUNTIME[Runtime API]
        SSE[SSE Stream endpoint]
    end

    CLI -->|read| CONFIG
    CLI -->|API key in header| TLS
    TLS --> GW
    GW --> AUTH
    AUTH --> MGMT
    AUTH --> RUNTIME
    RUNTIME --> SSE
    SSE -->|streaming chunks| TLS
    TLS -->|streaming chunks| CLI
```

### Command-to-API Mapping

```mermaid
flowchart LR
    subgraph "CLI Commands"
        C1[agent list]
        C2[agent create]
        C3[agent run 'prompt']
        C4[agent logs]
        C5[workflow run]
        C6[tool register]
    end

    subgraph "API Endpoints"
        A1[GET /api/v1/agents]
        A2[POST /api/v1/agents]
        A3[POST /api/v1/agents/name/run]
        A4[GET /api/v1/agents/name/logs]
        A5[POST /api/v1/workflows/name/run]
        A6[POST /api/v1/tools]
    end

    C1 --> A1
    C2 --> A2
    C3 --> A3
    C4 --> A4
    C5 --> A5
    C6 --> A6
```

---

## 3. SDK Internal Data Flow

```mermaid
sequenceDiagram
    participant App as User's Python App
    participant SDK as agentic-ai SDK
    participant Auth as Auth Module
    participant HTTP as HTTP Client (httpx)
    participant API as Platform API
    participant SSE as SSE Stream

    App->>SDK: agent.run("question")
    SDK->>Auth: Get API key from config/env
    Auth-->>SDK: api_key

    alt Synchronous mode
        SDK->>HTTP: POST /api/v1/agents/{name}/run
        HTTP->>API: Request with auth headers
        API-->>HTTP: JSON response (complete)
        HTTP-->>SDK: Parse response
        SDK-->>App: AgentResult object
    else Streaming mode
        SDK->>HTTP: POST /api/v1/agents/{name}/run?stream=true
        HTTP->>API: Request with auth headers
        API->>SSE: Upgrade to SSE
        loop Each chunk
            SSE-->>HTTP: data: {type: "step", ...}
            HTTP-->>SDK: Parse chunk
            SDK-->>App: yield StreamChunk
        end
        SSE-->>HTTP: data: {type: "done", ...}
        HTTP-->>SDK: Stream complete
        SDK-->>App: Final AgentResult
    end
```

---

## 4. Playground — Session Data Isolation

```mermaid
flowchart TD
    subgraph "Developer A — Playground Session"
        PA[Session: pg-abc123]
        PA_NS["Namespace: playground-abc123<br/>Agent Pod: 1<br/>Redis: isolated key prefix<br/>Memory: session-scoped"]
        PA_QUOTA["Quota:<br/>CPU: 2 cores<br/>Memory: 4 GB<br/>Tokens: 50,000<br/>Duration: 10 min"]
    end

    subgraph "Developer B — Playground Session"
        PB[Session: pg-def456]
        PB_NS["Namespace: playground-def456<br/>Agent Pod: 1<br/>Redis: isolated key prefix<br/>Memory: session-scoped"]
        PB_QUOTA["Quota:<br/>CPU: 2 cores<br/>Memory: 4 GB<br/>Tokens: 50,000<br/>Duration: 10 min"]
    end

    subgraph "Shared Infrastructure"
        REDIS[Redis Cluster<br/>Key prefix isolation]
        LLM[LLM Provider<br/>Shared, metered per session]
        PG[PostgreSQL<br/>Playground data tagged,<br/>auto-deleted on cleanup]
    end

    PA_NS --> REDIS
    PB_NS --> REDIS
    PA_NS --> LLM
    PB_NS --> LLM
    PA_NS --> PG
    PB_NS --> PG

    PA_NS -.-x PB_NS

    style PA_NS fill:#e6f3ff
    style PB_NS fill:#e6ffe6
```

---

## 5. Template Installation Flow

```mermaid
flowchart TD
    subgraph "Template Repository (Git)"
        REPO[templates/<br/>rag-assistant/<br/>code-reviewer/<br/>data-analyst/]
    end

    subgraph "Platform"
        SYNC[Template Sync Job<br/>Polls repo every 5 min]
        CATALOG[Template Catalog<br/>PostgreSQL]
        CACHE[Template Cache<br/>Redis]
    end

    subgraph "Developer Action"
        BROWSE[Browse templates<br/>in Portal or CLI] --> SELECT[Select template]
        SELECT --> CUSTOMIZE[Customize parameters]
        CUSTOMIZE --> INSTANTIATE[Create agent from template]
    end

    REPO --> SYNC
    SYNC --> CATALOG
    CATALOG --> CACHE

    BROWSE --> CACHE
    INSTANTIATE --> API[Management API]
    API --> RESOLVE["Resolve template:<br/>1. Load base config<br/>2. Apply customizations<br/>3. Validate against quotas<br/>4. Generate Agent CRD"]
    RESOLVE --> K8S[Deploy to Kubernetes]
```

---

## 6. Real-Time Monitoring — Portal to Observability Stack

```mermaid
flowchart TD
    subgraph "Developer Portal"
        DASH[Agent Dashboard]
        TRACE[Trace Viewer]
        LOGS[Log Viewer]
        COST[Cost Explorer]
    end

    subgraph "Portal Backend (BFF)"
        BFF_METRICS[Metrics Proxy]
        BFF_TRACES[Trace Proxy]
        BFF_LOGS[Log Proxy]
        BFF_COSTS[Cost Aggregator]
    end

    subgraph "Observability Stack"
        PROM[Prometheus<br/>Metrics]
        TEMPO[Tempo<br/>Traces]
        LOKI[Loki<br/>Logs]
        PG_USAGE[PostgreSQL<br/>Usage & Cost Data]
    end

    DASH --> BFF_METRICS --> PROM
    TRACE --> BFF_TRACES --> TEMPO
    LOGS --> BFF_LOGS --> LOKI
    COST --> BFF_COSTS --> PG_USAGE
```

### Trace Viewer — What the Developer Sees

```mermaid
gantt
    title Agent Run Trace — run_id: abc123
    dateFormat X
    axisFormat %s

    section HTTP
    Request received           :0, 200

    section Auth
    API key validation         :200, 250

    section Agent Loop
    LLM Call #1 (decide tool)  :250, 3400
    Tool: web_search           :3400, 4600
    LLM Call #2 (decide tool)  :4600, 7200
    Tool: calculator           :7200, 7210
    LLM Call #3 (final answer) :7210, 9800

    section Safety
    Output filter              :9800, 9850

    section Response
    Send response              :9850, 9900
```

---

## 7. API Key Self-Service Flow

```mermaid
sequenceDiagram
    actor Dev as Team Lead
    participant Portal as Developer Portal
    participant API as Management API
    participant PG as PostgreSQL
    participant ESO as External Secrets

    Dev->>Portal: Navigate to Settings → API Keys
    Portal->>API: GET /api/v1/keys
    API->>PG: SELECT key_prefix, name, created_at, last_used<br/>FROM api_keys WHERE tenant_id = 'alpha'
    PG-->>API: Key list (prefix only, not full keys)
    API-->>Portal: Display key list

    Dev->>Portal: Click "Create New Key"
    Dev->>Portal: Name: "CI/CD Pipeline Key"<br/>Scopes: [agent:run, agent:read]<br/>Expires: 90 days
    Portal->>API: POST /api/v1/keys

    API->>API: Generate: ak_alpha_<random_32>
    API->>API: Hash key with bcrypt
    API->>PG: INSERT (key_hash, prefix, name, scopes, expires)
    API-->>Portal: Full key shown ONCE

    Portal-->>Dev: "Save this key — it won't be shown again"<br/>ak_alpha_a8f3b2c1d4e5f6a7b8c9d0e1f2a3b4c5

    Note over Dev,Portal: Key is shown only at creation time.<br/>Portal only displays the prefix afterward.
```

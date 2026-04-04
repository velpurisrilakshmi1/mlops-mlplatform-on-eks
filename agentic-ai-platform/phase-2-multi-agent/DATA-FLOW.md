# Phase 2: Multi-Agent & Orchestration — Data Flow Diagrams

> **Objective:** Trace data paths through multi-agent workflows — task decomposition, message routing, shared memory, and result aggregation.

---

## 1. Supervisor Workflow — End-to-End

```mermaid
sequenceDiagram
    actor User
    participant API as API Gateway
    participant Orch as Orchestrator
    participant SUP as Supervisor Agent
    participant NATS as NATS JetStream
    participant RA as Research Agent
    participant AA as Analysis Agent
    participant WA as Writer Agent
    participant MEM as Shared Memory

    User->>API: "Analyze the competitive<br/>landscape for Company X"
    API->>Orch: Create workflow

    rect rgb(240, 248, 255)
        Note over Orch,SUP: Step 1 — Task Decomposition
        Orch->>SUP: Decompose task
        SUP->>SUP: LLM call → plan
        SUP-->>Orch: Plan: research → analyze → write
        Orch->>Orch: Create DAG, persist to DB
    end

    rect rgb(240, 255, 240)
        Note over Orch,RA: Step 2 — Research (no dependencies)
        Orch->>NATS: Publish task → agent.task.alpha.research-agent
        NATS->>RA: Deliver task
        RA->>RA: Web search, document retrieval
        RA->>MEM: Write research_results to shared memory
        RA->>NATS: Publish result → agent.result.alpha.{workflow_id}
        NATS->>Orch: Deliver result
        Orch->>Orch: Mark step "research" completed
    end

    rect rgb(255, 255, 240)
        Note over Orch,AA: Step 3 — Analysis (depends on research)
        Orch->>Orch: Check DAG: analyze deps met ✓
        Orch->>NATS: Publish task → agent.task.alpha.analysis-agent
        NATS->>AA: Deliver task
        AA->>MEM: Read research_results from shared memory
        AA->>AA: Analyze data, identify patterns
        AA->>MEM: Write analysis_results to shared memory
        AA->>NATS: Publish result
        NATS->>Orch: Deliver result
    end

    rect rgb(255, 240, 240)
        Note over Orch,WA: Step 4 — Report Writing (depends on analysis)
        Orch->>NATS: Publish task → agent.task.alpha.writer-agent
        NATS->>WA: Deliver task
        WA->>MEM: Read research_results + analysis_results
        WA->>WA: Compose report
        WA->>NATS: Publish final result
        NATS->>Orch: Deliver result
    end

    Orch->>Orch: All steps complete
    Orch-->>API: Return final report
    API-->>User: Competitive landscape analysis
```

---

## 2. Parallel Execution — Map-Reduce Pattern

```mermaid
sequenceDiagram
    participant Orch as Orchestrator
    participant NATS as NATS
    participant W1 as Worker 1
    participant W2 as Worker 2
    participant W3 as Worker 3
    participant MEM as Shared Memory
    participant RED as Reducer Agent

    Orch->>Orch: Split task into 3 chunks

    par Parallel Dispatch
        Orch->>NATS: chunk_1 → worker
        NATS->>W1: Process chunk 1
    and
        Orch->>NATS: chunk_2 → worker
        NATS->>W2: Process chunk 2
    and
        Orch->>NATS: chunk_3 → worker
        NATS->>W3: Process chunk 3
    end

    par Parallel Execution
        W1->>W1: Process
        W1->>MEM: Write result_1
        W1->>NATS: Done
    and
        W2->>W2: Process
        W2->>MEM: Write result_2
        W2->>NATS: Done
    and
        W3->>W3: Process
        W3->>MEM: Write result_3
        W3->>NATS: Done
    end

    NATS->>Orch: All 3 results received
    Orch->>NATS: Dispatch to reducer
    NATS->>RED: Combine results
    RED->>MEM: Read result_1, result_2, result_3
    RED->>RED: Synthesize
    RED->>NATS: Final combined result
    NATS->>Orch: Workflow complete
```

---

## 3. NATS Message Routing

```mermaid
flowchart TD
    subgraph "Publishers"
        ORCH[Orchestrator]
        AGENTS[Agent Instances]
    end

    subgraph "NATS JetStream"
        subgraph "Stream: AGENT_TASKS"
            T1[agent.task.alpha.research-agent]
            T2[agent.task.alpha.analysis-agent]
            T3[agent.task.beta.research-agent]
        end

        subgraph "Stream: AGENT_RESULTS"
            R1[agent.result.alpha.*]
            R2[agent.result.beta.*]
        end

        subgraph "Stream: AGENT_EVENTS"
            E1[agent.event.alpha.started]
            E2[agent.event.alpha.completed]
            E3[agent.event.alpha.failed]
        end
    end

    subgraph "Consumers (Pull-based)"
        C1[research-agent-alpha<br/>consumer]
        C2[analysis-agent-alpha<br/>consumer]
        C3[research-agent-beta<br/>consumer]
        C4[orchestrator<br/>consumer — all results]
        C5[event-processor<br/>consumer — all events]
    end

    ORCH --> T1
    ORCH --> T2
    ORCH --> T3
    AGENTS --> R1
    AGENTS --> R2
    AGENTS --> E1
    AGENTS --> E2

    T1 --> C1
    T2 --> C2
    T3 --> C3
    R1 --> C4
    R2 --> C4
    E1 --> C5
    E2 --> C5
    E3 --> C5
```

---

## 4. Agent Lifecycle in Kubernetes

```mermaid
flowchart TD
    subgraph "Git Repository"
        CRD_YAML[Agent CRD YAML<br/>committed by developer]
    end

    subgraph "ArgoCD"
        SYNC[GitOps Sync]
    end

    subgraph "EKS Cluster"
        API_SERVER[Kubernetes API Server]
        CONTROLLER[Agent CRD Controller]
        DEPLOY[Agent Deployment]
        SVC[Agent Service]
        KEDA[KEDA ScaledObject]
        CONSUMER[NATS Consumer]
    end

    CRD_YAML --> SYNC
    SYNC --> API_SERVER
    API_SERVER -->|CRD event| CONTROLLER
    CONTROLLER --> DEPLOY
    CONTROLLER --> SVC
    CONTROLLER --> KEDA
    CONTROLLER --> CONSUMER

    KEDA -->|scale event| DEPLOY
    DEPLOY -->|pods| POD1[Agent Pod 1]
    DEPLOY -->|pods| POD2[Agent Pod 2]
    POD1 --> CONSUMER
    POD2 --> CONSUMER
```

---

## 5. Failure & Retry Flow

```mermaid
flowchart TD
    A[Task dispatched to agent] --> B{Agent responds?}
    B -->|Yes, success| C[Mark step completed]
    B -->|Yes, error| D{Retries left?}
    B -->|No response<br/>timeout| D

    D -->|Yes| E[Increment retry count]
    E --> F[Exponential backoff<br/>2^retry × 1s]
    F --> G[Re-dispatch via NATS<br/>to same agent type]
    G --> B

    D -->|No| H{Fallback agent defined?}
    H -->|Yes| I[Route to fallback agent]
    I --> B
    H -->|No| J[Mark step FAILED]
    J --> K{Critical step?}
    K -->|Yes| L[Fail entire workflow]
    K -->|No| M[Continue with<br/>degraded result]

    C --> N[Evaluate next steps in DAG]
```

---

## 6. Shared Memory Read/Write Pattern

```mermaid
flowchart TD
    subgraph "Agent A (Research)"
        A1[Produce research results] --> A2[Write to shared memory]
    end

    subgraph "Shared Memory (Redis)"
        SM["workflow:{id}:context<br/>──────────<br/>research_results: '...'<br/>analysis_results: null<br/>──────────<br/>TTL: workflow timeout + 1hr"]
    end

    subgraph "Agent B (Analysis)"
        B1[Read from shared memory] --> B2[Process research + analyze]
        B2 --> B3[Write analysis results]
    end

    A2 -->|HSET workflow:{id}:context<br/>research_results '...'| SM
    SM -->|HGET workflow:{id}:context<br/>research_results| B1
    B3 -->|HSET workflow:{id}:context<br/>analysis_results '...'| SM
```

| Operation | Redis Command | Complexity |
|-----------|---------------|-----------|
| Write key | `HSET workflow:{id}:context {key} {value}` | O(1) |
| Read key | `HGET workflow:{id}:context {key}` | O(1) |
| Read all | `HGETALL workflow:{id}:context` | O(N) |
| Check exists | `HEXISTS workflow:{id}:context {key}` | O(1) |
| Cleanup | `DEL workflow:{id}:context` (after workflow ends) | O(1) |

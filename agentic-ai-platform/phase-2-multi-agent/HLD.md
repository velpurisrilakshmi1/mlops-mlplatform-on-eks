# Phase 2: Multi-Agent & Orchestration — High-Level Design

> **Objective:** Move from single agents to agent systems — agents that delegate, collaborate, and operate as coordinated teams.

---

## Team Thinking

**Product Lead:** "Single agents hit a ceiling. Complex tasks need specialists — one agent for research, another for analysis, another for writing. Human teams delegate. Agent teams should too."

**Architect:** "This is the hardest phase. Multi-agent introduces distributed state, message routing, failure cascading, and debugging complexity that's an order of magnitude harder than single-agent. We need to get the patterns right."

**Backend Engineer:** "I've been studying the patterns — supervisor, swarm, pipeline, debate. Each fits different use cases. We shouldn't pick one; we should build primitives that support all of them."

**Platform Engineer:** "Kubernetes already solves service orchestration. Can we model agents as Kubernetes-native resources? CRDs, controllers, the whole pattern."

**SRE:** "Multi-agent means one agent's failure cascades to others. I need circuit breakers, fallback behavior, and clear ownership of who owns which agent."

---

## High-Level Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        UI[Agent Studio UI]
        CLI[agentctl CLI]
        API[REST API]
    end

    subgraph "EKS Cluster"
        subgraph "Gateway"
            KONG[Kong API Gateway]
        end

        subgraph "Orchestration Layer"
            ORCH[Orchestrator Service]
            WORKFLOW[Workflow Engine]
            SUPERVISOR[Supervisor Agent Pattern]
        end

        subgraph "Agent Pool"
            A1[Research Agent]
            A2[Analysis Agent]
            A3[Writer Agent]
            A4[Code Agent]
            A5[Custom Agents...]
        end

        subgraph "Communication"
            NATS[NATS JetStream<br/>Message Bus]
            SHARED_MEM[Shared Memory Store<br/>Redis + pgvector]
        end

        subgraph "Control Plane"
            CRD_CTRL[Agent CRD Controller]
            SCALER[Agent Autoscaler<br/>KEDA]
        end

        subgraph "Data Layer"
            PG[PostgreSQL]
            REDIS[Redis]
            VECTOR[pgvector]
        end
    end

    subgraph "External"
        LLM[LLM Providers]
        TOOLS[External Tool APIs]
    end

    UI --> KONG
    CLI --> KONG
    API --> KONG
    KONG --> ORCH
    ORCH --> WORKFLOW
    ORCH --> SUPERVISOR
    SUPERVISOR --> NATS
    NATS --> A1
    NATS --> A2
    NATS --> A3
    NATS --> A4
    A1 --> SHARED_MEM
    A2 --> SHARED_MEM
    A3 --> SHARED_MEM
    A1 --> LLM
    A2 --> LLM
    A3 --> LLM
    A4 --> TOOLS
    CRD_CTRL --> A1
    CRD_CTRL --> A2
    SCALER --> A1
    SCALER --> A2
```

---

## Multi-Agent Patterns

### Pattern 1: Supervisor

```mermaid
graph TD
    USER[User Task] --> SUP[Supervisor Agent]
    SUP -->|"research this"| A1[Research Agent]
    SUP -->|"analyze this data"| A2[Analysis Agent]
    SUP -->|"write the report"| A3[Writer Agent]
    A1 -->|results| SUP
    A2 -->|results| SUP
    A3 -->|results| SUP
    SUP -->|final answer| USER

    style SUP fill:#e6f3ff,stroke:#0066cc
```

**When to use:** Complex tasks that require decomposition. The supervisor decides the plan, delegates to specialists, and synthesizes results.

### Pattern 2: Pipeline

```mermaid
graph LR
    USER[Input] --> A1[Extractor Agent]
    A1 -->|structured data| A2[Validator Agent]
    A2 -->|validated data| A3[Enrichment Agent]
    A3 -->|enriched data| A4[Summary Agent]
    A4 --> OUTPUT[Output]

    style A1 fill:#fff3e6
    style A2 fill:#fff3e6
    style A3 fill:#fff3e6
    style A4 fill:#fff3e6
```

**When to use:** Sequential data processing. Each agent transforms the data and passes it forward.

### Pattern 3: Debate / Consensus

```mermaid
graph TD
    USER[Question] --> MOD[Moderator Agent]
    MOD --> A1[Agent A — Perspective 1]
    MOD --> A2[Agent B — Perspective 2]
    A1 -->|argument| MOD
    A2 -->|argument| MOD
    MOD -->|"respond to A's point"| A2
    MOD -->|"respond to B's point"| A1
    A1 -->|rebuttal| MOD
    A2 -->|rebuttal| MOD
    MOD -->|synthesized answer| USER
```

**When to use:** High-stakes decisions where multiple perspectives reduce error. Code review, risk assessment, diagnosis.

### Pattern 4: Map-Reduce

```mermaid
graph TD
    USER[Big Task] --> SPLIT[Splitter Agent]
    SPLIT --> W1[Worker Agent 1]
    SPLIT --> W2[Worker Agent 2]
    SPLIT --> W3[Worker Agent 3]
    SPLIT --> W4[Worker Agent N]
    W1 --> REDUCE[Reducer Agent]
    W2 --> REDUCE
    W3 --> REDUCE
    W4 --> REDUCE
    REDUCE --> OUTPUT[Combined Result]
```

**When to use:** Parallelizable tasks. Analyze 50 documents, process 100 records, search across multiple sources.

---

## Agent CRD (Custom Resource Definition)

```yaml
apiVersion: agentic.ai/v1alpha1
kind: Agent
metadata:
  name: research-agent
  namespace: tenant-alpha
spec:
  description: "Researches topics using web search and document retrieval"
  model: gpt-4o
  systemPrompt: |
    You are a research specialist. Your job is to find accurate,
    relevant information using the tools available to you.
  tools:
    - web_search
    - document_retrieval
    - summarizer
  memory:
    shortTerm: true
    longTerm: true
  scaling:
    minReplicas: 1
    maxReplicas: 10
    targetConcurrency: 5
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "2"
      memory: "4Gi"
  timeout: 120s
  maxIterations: 10
```

---

## Workflow Definition

```yaml
apiVersion: agentic.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: market-analysis
  namespace: tenant-alpha
spec:
  trigger: api  # or schedule, event
  steps:
    - name: research
      agent: research-agent
      input: "{{ .input.topic }}"
      output: research_results

    - name: analyze
      agent: analysis-agent
      input: "{{ .steps.research.output }}"
      dependsOn: [research]
      output: analysis

    - name: report
      agent: writer-agent
      input: |
        Based on this analysis: {{ .steps.analyze.output }}
        Write a market analysis report.
      dependsOn: [analyze]
      output: final_report

  output: "{{ .steps.report.output }}"
```

---

## Component Ownership

| Component | Team | Responsibility |
|-----------|------|---------------|
| **Orchestrator** | Backend | Task decomposition, agent routing, result aggregation |
| **Workflow Engine** | Backend | DAG execution, step dependencies, retries |
| **Agent CRD Controller** | Platform | Watch CRDs, create/update agent deployments |
| **NATS JetStream** | Platform | Deployment, stream configuration, monitoring |
| **Agent Autoscaler** | Platform + SRE | KEDA triggers, scaling policies |
| **Shared Memory** | Backend | Cross-agent context, conflict resolution |
| **Agent Studio UI** | Frontend | Visual workflow builder, agent configuration |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Message bus | NATS JetStream | Lightweight, persistent, built for Kubernetes, lower ops than Kafka |
| Orchestration | Custom controller + DAG engine | Argo Workflows too heavy for agent-specific needs |
| Agent definition | Kubernetes CRD | Native to the platform, declarative, GitOps-friendly |
| Inter-agent communication | Async message passing (not direct HTTP) | Decoupling, resilience, natural backpressure |
| Shared state | Redis (hot) + pgvector (semantic) | Fast access for active workflows, semantic search for context |
| Autoscaling | KEDA with NATS triggers | Scale agents based on message queue depth, not CPU |

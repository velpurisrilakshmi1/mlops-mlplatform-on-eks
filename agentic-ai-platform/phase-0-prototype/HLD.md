# Phase 0: Prototype — High-Level Design

> **Objective:** Prove the core agent loop works end-to-end on EKS. One agent, one endpoint, a couple of tools, a simple UI.

---

## Team Thinking

**Product Lead:** "We need to validate that an agent running on our existing EKS cluster can receive a task, reason about it, call tools, and return a useful answer — all within acceptable latency. Nothing fancy. Just prove the loop."

**Platform Engineer:** "We already have EKS, ArgoCD, External Secrets, and Terraform. The agent service is just another workload. I'll package it as a Helm chart and deploy it like everything else."

**Backend Engineer:** "I'll build the agent runtime as a FastAPI service. It receives a prompt, talks to an LLM, decides which tool to call, executes it, and returns the result. Stateless for now."

**Frontend Engineer:** "A Streamlit app or a minimal React chat UI. Just enough to demo it. No auth, no persistence."

---

## High-Level Architecture

```mermaid
graph TB
    subgraph "User Layer"
        UI[Chat UI<br/>Streamlit / React]
        API_CLIENT[API Client<br/>curl / Postman]
    end

    subgraph "EKS Cluster"
        subgraph "Ingress"
            NGINX[NGINX Ingress Controller]
        end

        subgraph "Agent Service"
            FASTAPI[Agent API<br/>FastAPI]
            AGENT_LOOP[Agent Reasoning Loop]
            LLM_CLIENT[LLM Client<br/>LiteLLM]
        end

        subgraph "Tool Execution"
            TOOL_ROUTER[Tool Router]
            TOOL_SEARCH[Web Search Tool]
            TOOL_CALC[Calculator Tool]
            TOOL_CODE[Code Executor Tool]
        end
    end

    subgraph "External Services"
        LLM_PROVIDER[LLM Provider<br/>OpenAI / Anthropic / Bedrock]
        SEARCH_API[Search API<br/>SerpAPI / Tavily]
    end

    UI --> NGINX
    API_CLIENT --> NGINX
    NGINX --> FASTAPI
    FASTAPI --> AGENT_LOOP
    AGENT_LOOP --> LLM_CLIENT
    LLM_CLIENT --> LLM_PROVIDER
    AGENT_LOOP --> TOOL_ROUTER
    TOOL_ROUTER --> TOOL_SEARCH
    TOOL_ROUTER --> TOOL_CALC
    TOOL_ROUTER --> TOOL_CODE
    TOOL_SEARCH --> SEARCH_API
```

---

## System Boundaries

```mermaid
C4Context
    title Phase 0 — System Context

    Person(user, "Developer / Demo Audience", "Sends tasks to the agent")
    System(agent_platform, "Agentic AI Platform (Prototype)", "Receives tasks, reasons, uses tools, returns answers")
    System_Ext(llm, "LLM Provider", "Provides language model inference")
    System_Ext(search, "Search API", "Provides web search results")
    System_Ext(eks, "EKS Cluster", "Hosts all platform workloads")

    Rel(user, agent_platform, "Sends prompts via HTTP")
    Rel(agent_platform, llm, "Sends completion requests")
    Rel(agent_platform, search, "Queries for live data")
    Rel(eks, agent_platform, "Runs as a Kubernetes workload")
```

---

## Component Responsibilities

| Component | Responsibility | Owner |
|-----------|---------------|-------|
| **Agent API** | HTTP endpoint, request validation, response formatting | Backend Engineer |
| **Agent Loop** | LLM call → tool decision → tool execution → repeat or return | Backend Engineer |
| **LLM Client** | Abstraction over LLM providers, prompt formatting | Backend Engineer |
| **Tool Router** | Maps tool names to executors, validates tool inputs | Backend Engineer |
| **Tools (2-3)** | Concrete tool implementations (search, calc, code exec) | Backend Engineer |
| **Chat UI** | Simple interface for demo purposes | Frontend Engineer |
| **Helm Chart** | Packaging, deployment config, resource limits | Platform Engineer |
| **Ingress** | Route external traffic to agent service | Platform Engineer |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | No heavy framework (no LangChain) | Keep it simple, understand every line, avoid abstraction tax |
| LLM abstraction | LiteLLM | Swap providers without code changes, test different models easily |
| Deployment | Helm on existing EKS | Leverage existing infra — no new clusters, no new tools |
| UI | Streamlit | Fastest path to a working demo — one Python file |
| State | In-memory only | Prototype scope — persistence comes in Phase 1 |
| Auth | None | Internal demo only — security comes in Phase 1 |

---

## Deployment Topology

```mermaid
graph LR
    subgraph "EKS Cluster — Existing"
        subgraph "Namespace: agentic-ai"
            POD_AGENT[Agent Service Pod<br/>1 replica]
            POD_UI[UI Pod<br/>1 replica]
        end

        subgraph "Namespace: ingress-system"
            INGRESS[NGINX Ingress]
        end

        subgraph "Namespace: argocd"
            ARGO[ArgoCD<br/>GitOps Sync]
        end
    end

    GIT[Git Repo<br/>Helm Chart] --> ARGO
    ARGO --> POD_AGENT
    ARGO --> POD_UI
    INGRESS --> POD_AGENT
    INGRESS --> POD_UI
```

---

## Non-Goals for Phase 0

- No persistent storage
- No authentication or multi-tenancy
- No auto-scaling
- No multi-agent orchestration
- No guardrails or content filtering
- No production SLAs

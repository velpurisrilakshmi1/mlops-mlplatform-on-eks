# Phase 4: Developer Experience & Self-Serve — High-Level Design

> **Objective:** Make the platform accessible to every team — a portal, CLI, SDKs, templates, playground, and documentation that lets someone go from zero to running agent in minutes.

---

## Team Thinking

**Product Lead:** "We built a powerful platform. But right now only the platform team can use it. If adopting the platform requires a Kubernetes expert, we've failed. Every developer should be able to build, deploy, and manage agents without filing a ticket."

**Developer Advocate (new hire):** "I've onboarded onto dozens of platforms. The ones that win have three things: a great getting-started guide, a CLI that doesn't suck, and a playground where you can experiment without breaking anything."

**Frontend Engineer:** "The portal isn't just a dashboard. It's the primary interface for teams. Agent configuration, monitoring, logs, approvals — all in one place. No more switching between Grafana, kubectl, and Slack."

**Backend Engineer:** "The SDK needs to feel like writing normal Python. No 50-line YAML files to create an agent. `Agent(name='my-agent', model='gpt-4o', tools=[search])` — that simple."

**Platform Engineer:** "Self-serve means guardrails. Teams can provision agents without us, but within limits. Quotas, approved models, approved tools. Self-serve doesn't mean free-for-all."

---

## High-Level Architecture

```mermaid
graph TB
    subgraph "Developer Interfaces"
        PORTAL[Developer Portal<br/>Web Application]
        CLI[agentctl CLI<br/>Terminal Tool]
        SDK_PY[Python SDK<br/>pip install agentic-ai]
        SDK_TS[TypeScript SDK<br/>npm install @agentic-ai/sdk]
    end

    subgraph "Platform API Layer"
        API_GW[API Gateway]
        MGMT_API[Management API<br/>CRUD agents, workflows,<br/>tools, tenants]
        RUN_API[Runtime API<br/>Execute agents,<br/>stream responses]
        METRICS_API[Metrics API<br/>Usage, cost,<br/>performance data]
    end

    subgraph "Platform Services"
        TEMPLATE_SVC[Template Service<br/>Starter templates,<br/>example agents]
        PLAYGROUND_SVC[Playground Service<br/>Sandboxed testing<br/>environment]
        DOC_SVC[Documentation<br/>API reference,<br/>guides, tutorials]
    end

    subgraph "Core Platform (Phases 0-3)"
        AGENT_RT[Agent Runtime]
        ORCH[Orchestrator]
        SAFETY[Safety Layer]
        OBS[Observability]
    end

    PORTAL --> API_GW
    CLI --> API_GW
    SDK_PY --> API_GW
    SDK_TS --> API_GW

    API_GW --> MGMT_API
    API_GW --> RUN_API
    API_GW --> METRICS_API

    MGMT_API --> AGENT_RT
    MGMT_API --> ORCH
    RUN_API --> AGENT_RT
    METRICS_API --> OBS

    PORTAL --> PLAYGROUND_SVC
    PORTAL --> TEMPLATE_SVC
    PORTAL --> DOC_SVC
```

---

## Developer Portal — Page Map

```mermaid
graph TD
    HOME[Home / Dashboard<br/>Active agents, recent runs,<br/>cost summary, alerts]

    HOME --> AGENTS[Agents<br/>List, create, configure]
    HOME --> WORKFLOWS[Workflows<br/>Define, visualize, run]
    HOME --> TOOLS[Tool Catalog<br/>Browse, register, test]
    HOME --> MONITORING[Monitoring<br/>Traces, logs, metrics]
    HOME --> SETTINGS[Settings<br/>API keys, team, billing]
    HOME --> PLAYGROUND[Playground<br/>Interactive testing]

    AGENTS --> AGENT_DETAIL[Agent Detail<br/>Config, runs, performance]
    AGENTS --> AGENT_CREATE[Create Agent<br/>Wizard or YAML editor]

    WORKFLOWS --> WF_BUILDER[Visual Workflow Builder<br/>Drag & drop DAG editor]
    WORKFLOWS --> WF_RUNS[Workflow Runs<br/>Status, trace, replay]

    TOOLS --> TOOL_TEST[Tool Tester<br/>Try a tool with sample input]

    MONITORING --> TRACE_VIEW[Trace Viewer<br/>Step-by-step agent reasoning]
    MONITORING --> COST[Cost Explorer<br/>Usage breakdown by agent/team]

    PLAYGROUND --> PG_CHAT[Chat Interface<br/>Talk to your agent]
    PLAYGROUND --> PG_DEBUG[Debug Mode<br/>See reasoning, tool calls, memory]
```

---

## CLI (agentctl) — Command Map

```
agentctl
├── agent
│   ├── list                    List all agents in your tenant
│   ├── create <name>           Create a new agent (interactive or --from-template)
│   ├── deploy <name>           Deploy agent to the platform
│   ├── describe <name>         Show agent config, status, recent runs
│   ├── logs <name>             Stream agent logs
│   ├── run <name> "prompt"     Execute agent with a prompt
│   └── delete <name>           Remove agent
├── workflow
│   ├── list                    List workflows
│   ├── create <name>           Create workflow from YAML
│   ├── run <name> --input {}   Execute workflow
│   ├── status <run-id>         Check workflow run status
│   └── visualize <name>        Print DAG in terminal (ASCII art)
├── tool
│   ├── list                    List available tools
│   ├── register <tool.yaml>    Register a new tool
│   └── test <name> --input {}  Test a tool
├── playground                  Open interactive playground
├── config
│   ├── set-context <tenant>    Switch tenant context
│   └── set-api-key <key>       Configure authentication
└── status                      Platform health, your usage, alerts
```

---

## SDK Design Philosophy

```mermaid
graph LR
    subgraph "Complexity Ladder"
        L1["Level 1: One-liner<br/>agent.run('question')"]
        L2["Level 2: Configuration<br/>Agent(model, tools, memory)"]
        L3["Level 3: Custom Logic<br/>Override reasoning, tool handling"]
        L4["Level 4: Full Control<br/>Custom agents, CRDs, raw API"]
    end

    L1 --> L2 --> L3 --> L4

    style L1 fill:#90EE90
    style L2 fill:#c8e6c9
    style L3 fill:#fff9c4
    style L4 fill:#ffcdd2
```

**Principle:** Simple things are simple. Complex things are possible.

---

## Component Ownership

| Component | Team | Responsibility |
|-----------|------|---------------|
| **Developer Portal** | Frontend + Product | UX design, implementation, user research |
| **agentctl CLI** | Backend | Command implementation, auto-updates |
| **Python SDK** | Backend | API wrappers, agent abstractions |
| **TypeScript SDK** | Backend | API wrappers, frontend integration |
| **Management API** | Backend | CRUD endpoints, validation |
| **Template Service** | Developer Advocate + Backend | Template curation, testing |
| **Playground** | Frontend + Platform | Sandboxed environment, resource limits |
| **Documentation** | Developer Advocate | Guides, API reference, tutorials |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Portal framework | React + Next.js | SSR for docs, rich interactivity for workflow builder |
| CLI framework | Python (Click) | Same language as SDK, cross-platform |
| SDK style | Declarative + imperative | Define agents as objects, override behavior with methods |
| Playground isolation | Dedicated namespace per session, 10-min TTL | No cross-contamination, auto-cleanup |
| Template source | Git repo, synced to platform | Version controlled, community contributions via PR |
| API docs | OpenAPI spec → auto-generated docs | Single source of truth, always in sync |

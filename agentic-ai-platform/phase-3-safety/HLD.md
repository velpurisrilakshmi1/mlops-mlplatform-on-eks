# Phase 3: Safety & Governance — High-Level Design

> **Objective:** Make the platform enterprise-ready — policy enforcement, content safety, audit trails, human-in-the-loop, and sandboxed execution.

---

## Team Thinking

**Product Lead:** "We've proven the technology works. Now we need to prove it's safe enough for regulated industries. Finance, healthcare, legal — they won't touch us without guardrails, audit trails, and compliance controls."

**Security Engineer:** "Agents are the first software that can *decide* to do dangerous things. A SQL injection bug is accidental. An agent that decides to email customer data to an external address is *intentional within its reasoning*. We need a fundamentally different security model."

**Compliance Officer (new hire):** "I need to answer three questions for any auditor: What did the agent do? Who authorized it? Can we prove it? If we can't answer all three, we can't ship to enterprise."

**SRE:** "Guardrails can't add 500ms to every request. Safety has to be fast, or teams will turn it off."

**Architect:** "The safety layer needs to be a sidecar or middleware — not embedded in the agent runtime. Agents shouldn't be able to bypass their own guardrails."

---

## High-Level Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        UI[Agent Studio UI]
        API_IN[API Request]
    end

    subgraph "EKS Cluster"
        subgraph "Safety Layer (Enforced)"
            INPUT_GATE[Input Gate<br/>PII Detection<br/>Prompt Injection Defense<br/>Content Policy]
            OUTPUT_GATE[Output Gate<br/>PII Redaction<br/>Content Filtering<br/>Hallucination Check]
            POLICY[Policy Engine<br/>OPA / Gatekeeper]
            HITL[Human-in-the-Loop<br/>Approval Service]
        end

        subgraph "Agent Runtime"
            AGENT[Agent Service]
            TOOLS[Tool Execution<br/>Sandboxed]
        end

        subgraph "Audit & Compliance"
            AUDIT_LOG[Immutable Audit Log]
            EVAL[Evaluation Framework<br/>Automated Testing]
        end

        subgraph "Sandbox Infrastructure"
            GVISOR[gVisor Runtime<br/>Sandboxed Pods]
        end
    end

    subgraph "Storage"
        PG[PostgreSQL<br/>Audit Tables]
        S3[S3<br/>Immutable Log Archive]
    end

    API_IN --> INPUT_GATE
    INPUT_GATE -->|Blocked| REJECT[Reject with reason]
    INPUT_GATE -->|Passed| POLICY
    POLICY -->|Denied| REJECT
    POLICY -->|Allowed| AGENT
    AGENT -->|High-risk action| HITL
    HITL -->|Approved| TOOLS
    HITL -->|Rejected| AGENT
    AGENT --> OUTPUT_GATE
    OUTPUT_GATE -->|Clean| UI
    OUTPUT_GATE -->|Redacted| UI
    OUTPUT_GATE -->|Blocked| REJECT

    AGENT --> AUDIT_LOG
    TOOLS --> AUDIT_LOG
    HITL --> AUDIT_LOG
    AUDIT_LOG --> PG
    AUDIT_LOG --> S3
    EVAL --> AGENT
```

---

## Safety Layers — Defense in Depth

```mermaid
graph LR
    subgraph "Layer 1: Input"
        L1A[Prompt Injection<br/>Detection]
        L1B[PII Detection<br/>in Input]
        L1C[Content Policy<br/>Check]
    end

    subgraph "Layer 2: Policy"
        L2A[Action Authorization<br/>OPA Policies]
        L2B[Tool Access Control]
        L2C[Budget / Rate Check]
    end

    subgraph "Layer 3: Execution"
        L3A[Sandboxed Runtime<br/>gVisor]
        L3B[Network Policies<br/>Egress Control]
        L3C[Resource Limits]
    end

    subgraph "Layer 4: Output"
        L4A[PII Redaction<br/>in Output]
        L4B[Content Safety<br/>Filter]
        L4C[Factuality Check<br/>when possible]
    end

    subgraph "Layer 5: Audit"
        L5A[Immutable Log]
        L5B[Decision Trail]
        L5C[Compliance Report]
    end

    L1A --> L2A --> L3A --> L4A --> L5A
```

---

## Policy Engine — OPA Integration

```mermaid
graph TD
    subgraph "Policy Definitions (Git)"
        P1["policy: agent-tool-access<br/>research-agent CAN use web_search<br/>research-agent CANNOT use code_executor"]
        P2["policy: action-limits<br/>No agent can send emails<br/>without human approval"]
        P3["policy: data-access<br/>Agents in namespace 'finance'<br/>can access financial data tools"]
    end

    subgraph "OPA Engine"
        OPA[Open Policy Agent<br/>Sidecar or Service]
    end

    subgraph "Enforcement Points"
        E1[Agent Service<br/>Before tool call]
        E2[Tool Registry<br/>Before tool execution]
        E3[Output Gate<br/>Before response sent]
    end

    P1 --> OPA
    P2 --> OPA
    P3 --> OPA
    E1 -->|"Can agent X call tool Y?"| OPA
    E2 -->|"Can this tool access this data?"| OPA
    E3 -->|"Can this data be returned to user?"| OPA
    OPA -->|Allow / Deny + reason| E1
    OPA -->|Allow / Deny + reason| E2
    OPA -->|Allow / Deny + reason| E3
```

---

## Human-in-the-Loop — Approval Flow

```mermaid
sequenceDiagram
    actor User
    participant Agent as Agent Service
    participant HITL as Approval Service
    participant Approver as Human Approver
    participant Tool as High-Risk Tool

    Agent->>Agent: Decides to execute high-risk action<br/>(e.g., "send email to customer")
    Agent->>HITL: Request approval<br/>{action, reason, context}
    HITL->>HITL: Create approval request
    HITL->>Approver: Notify via Slack / UI / Email
    HITL-->>Agent: Approval pending (agent pauses)

    alt Approved
        Approver->>HITL: Approve with optional note
        HITL->>HITL: Log approval decision
        HITL-->>Agent: Approved
        Agent->>Tool: Execute action
    else Rejected
        Approver->>HITL: Reject with reason
        HITL->>HITL: Log rejection
        HITL-->>Agent: Rejected — reason: "..."
        Agent->>Agent: Adjust approach based on rejection
    else Timeout
        HITL->>HITL: 15 min timeout
        HITL-->>Agent: Timed out — treat as rejection
    end
```

---

## Component Ownership

| Component | Team | Responsibility |
|-----------|------|---------------|
| **Input Gate** | Security | PII detection, prompt injection defense, content policy |
| **Output Gate** | Security | PII redaction, content filtering |
| **Policy Engine (OPA)** | Security + Platform | Policy authoring, deployment, enforcement |
| **HITL Service** | Backend | Approval workflow, notification, timeout handling |
| **Audit Log** | Compliance + Platform | Immutable logging, archival, retention |
| **Sandbox Runtime** | Platform | gVisor configuration, security contexts |
| **Evaluation Framework** | Backend + QA | Test authoring, execution, regression detection |
| **Compliance Reporting** | Compliance | Report generation, auditor access |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Policy engine | OPA (Open Policy Agent) | Industry standard, Rego language is expressive, Kubernetes-native |
| PII detection | Presidio (Microsoft) + custom rules | Open source, extensible, supports custom entity types |
| Prompt injection defense | Multi-layer (heuristic + LLM classifier) | No single approach is reliable enough alone |
| Audit storage | PostgreSQL + S3 archive | Queryable in PG, immutable archive in S3 with lifecycle policies |
| Sandbox runtime | gVisor (runsc) | Better security than default runc, less overhead than Firecracker |
| HITL notifications | Slack + Web UI | Where approvers already are |

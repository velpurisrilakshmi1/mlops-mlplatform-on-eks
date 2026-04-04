# Phase 3: Safety & Governance — Data Flow Diagrams

> **Objective:** Trace data through every safety checkpoint — from input filtering to output redaction to immutable audit.

---

## 1. Complete Request Flow with Safety Layers

```mermaid
sequenceDiagram
    actor User
    participant GW as API Gateway
    participant IG as Input Gate
    participant PE as Policy Engine (OPA)
    participant Agent as Agent Service
    participant HITL as HITL Service
    participant Tool as Tool (Sandboxed)
    participant OG as Output Gate
    participant Audit as Audit Log

    User->>GW: POST /api/v1/agent/run<br/>"Find John Smith's salary at john@acme.com"

    rect rgb(255, 230, 230)
        Note over GW,IG: Layer 1 — Input Safety
        GW->>IG: Check input
        IG->>IG: PII scan → found: email, person name
        IG->>IG: Prompt injection scan → clean
        IG->>IG: Redact PII → "Find <PERSON_1>'s salary at <EMAIL_1>"
        IG->>Audit: Log: pii_detected {email: 1, person: 1}
    end

    rect rgb(230, 240, 255)
        Note over IG,PE: Layer 2 — Policy Check
        IG->>PE: Can this tenant run agents?
        PE->>PE: Check budget, rate limit, permissions
        PE-->>IG: Allowed
        PE->>Audit: Log: policy_allowed
    end

    rect rgb(230, 255, 230)
        Note over PE,Agent: Layer 3 — Agent Execution
        IG->>Agent: Redacted prompt + context
        Agent->>Agent: Reasoning: need to search HR database
        Agent->>PE: Can I call tool 'hr_database_query'?
        PE-->>Agent: Requires human approval
        Agent->>HITL: Request approval<br/>"Agent wants to query HR database for salary data"
        HITL->>Audit: Log: approval_requested
    end

    rect rgb(255, 255, 230)
        Note over HITL,Tool: Layer 4 — Human Approval
        HITL-->>User: Slack notification:<br/>"Agent requests access to HR data. Approve?"
        User->>HITL: Approve
        HITL->>Audit: Log: approval_granted {approver, timestamp}
        HITL-->>Agent: Approved
    end

    Agent->>Tool: Execute hr_database_query (sandboxed)
    Tool->>Audit: Log: tool_invoked {tool, input_hash}
    Tool-->>Agent: "Salary: $150,000"

    rect rgb(255, 240, 230)
        Note over Agent,OG: Layer 5 — Output Safety
        Agent->>OG: Response: "<PERSON_1>'s salary is $150,000"
        OG->>OG: Content safety → clean
        OG->>OG: PII check → salary amount (sensitive but allowed per policy)
        OG->>Audit: Log: output_checked {clean: true}
        OG-->>User: Final response
    end
```

---

## 2. Audit Trail — Complete Event Chain

```mermaid
flowchart TD
    subgraph "Single Agent Run — All Audit Events"
        E1["1. agent.run.start<br/>timestamp, tenant, prompt_hash"]
        E2["2. safety.input.scanned<br/>pii_found: 2, injection: none"]
        E3["3. policy.evaluated<br/>tool_access: hr_database → requires_approval"]
        E4["4. approval.requested<br/>action: hr_database_query"]
        E5["5. approval.decided<br/>decision: approved, approver: user@acme.com"]
        E6["6. tool.invoked<br/>tool: hr_database, duration: 340ms"]
        E7["7. llm.called<br/>model: gpt-4o, tokens: 1240, cost: $0.0031"]
        E8["8. safety.output.scanned<br/>pii_redacted: 0, content_safe: true"]
        E9["9. agent.run.completed<br/>duration: 28s, status: success"]
    end

    E1 --> E2 --> E3 --> E4 --> E5 --> E6 --> E7 --> E8 --> E9

    E9 --> HASH[Calculate chain hash<br/>SHA-256 of all events]
    HASH --> PG[(PostgreSQL)]
    HASH --> S3[(S3 Archive<br/>Object Lock)]
```

---

## 3. PII Data Flow — Redaction & Recovery

```mermaid
flowchart TD
    subgraph "Input Path"
        A[Raw user input<br/>'Email john@acme.com<br/>about the project'] --> B[PII Detector<br/>Presidio]
        B --> C{PII found?}
        C -->|Yes| D[Generate redaction tokens]
        D --> E[Store token map<br/>in Redis with TTL]
        D --> F[Replace PII in prompt<br/>'Email &lt;EMAIL_1&gt;<br/>about the project']
    end

    subgraph "Agent Processing"
        F --> G[Agent sees redacted text]
        G --> H[Agent decides to use<br/>email_sender tool]
        H --> I{Tool needs<br/>real email?}
        I -->|Yes| J[De-redact: lookup<br/>token map in Redis]
        J --> K[Tool receives real email<br/>john@acme.com]
        I -->|No| L[Tool receives<br/>redacted version]
    end

    subgraph "Output Path"
        K --> M[Tool output]
        M --> N[Output PII scan]
        N --> O{New PII in output?}
        O -->|Yes| P[Redact new PII]
        O -->|No| Q[Return response]
        P --> Q
    end
```

---

## 4. Policy Decision Data Flow

```mermaid
flowchart TD
    subgraph "Policy Lifecycle"
        A[Security team writes<br/>Rego policy] --> B[Git commit + PR]
        B --> C[Policy CI: syntax check,<br/>unit tests, compat test]
        C --> D[Merge to main]
        D --> E[ArgoCD syncs<br/>policy ConfigMap]
        E --> F[OPA sidecar reloads<br/>every 30s]
    end

    subgraph "Runtime Evaluation"
        G[Agent requests tool call] --> H[Build OPA input]
        H --> I["Input: {<br/>  agent_name, tool_name,<br/>  tenant_id, tenant_tier,<br/>  action_type, time_of_day,<br/>  daily_cost_so_far<br/>}"]
        I --> J[OPA evaluates<br/>all matching rules]
        J --> K{Decision}
        K -->|allow| L[Proceed]
        K -->|deny| M[Block + reason]
        K -->|require_approval| N[Trigger HITL]
    end

    subgraph "Audit"
        L --> O[Log: policy_allowed]
        M --> P[Log: policy_denied + reason]
        N --> Q[Log: policy_approval_required]
    end
```

---

## 5. Human-in-the-Loop — State Machine

```mermaid
stateDiagram-v2
    [*] --> Created: Agent requests approval

    Created --> Notified: Notification sent<br/>(Slack + UI)
    Notified --> Approved: Approver clicks Approve
    Notified --> Rejected: Approver clicks Reject
    Notified --> Escalated: Auto-escalate after 5 min
    Notified --> TimedOut: 15 min with no response

    Escalated --> Approved: Escalation target approves
    Escalated --> Rejected: Escalation target rejects
    Escalated --> TimedOut: Still no response

    Approved --> [*]: Agent proceeds with action
    Rejected --> [*]: Agent adjusts approach
    TimedOut --> [*]: Treated as rejection

    note right of Created
        All state transitions
        are logged to audit trail
    end note
```

### Approval Request Table

```sql
CREATE TABLE approval_requests (
    id UUID PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    run_id UUID NOT NULL,
    agent_name VARCHAR(128),
    action_type VARCHAR(128),
    action_description TEXT,
    context JSONB,
    risk_level VARCHAR(32),     -- 'low', 'medium', 'high', 'critical'
    status VARCHAR(32) DEFAULT 'pending',
    assigned_to VARCHAR(255),
    escalated_to VARCHAR(255),
    decided_by VARCHAR(255),
    decision_note TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    decided_at TIMESTAMPTZ,
    timeout_at TIMESTAMPTZ
);
```

---

## 6. Sandbox — Network & Resource Isolation

```mermaid
flowchart TD
    subgraph "EKS Node"
        subgraph "gVisor Sandbox (runsc)"
            POD[Agent Pod]
            FS[Read-only<br/>Filesystem]
            NET[Network<br/>Restricted]
        end

        subgraph "Allowed Egress"
            NATS[NATS :4222]
            REDIS[Redis :6379]
            PG[Postgres :5432]
            LLM_EP[LLM API Endpoints<br/>api.openai.com<br/>api.anthropic.com]
        end

        subgraph "Blocked"
            INTERNET[Public Internet ✗]
            OTHER_NS[Other Namespaces ✗]
            NODE_META[Node Metadata ✗<br/>169.254.169.254]
        end
    end

    POD --> NATS
    POD --> REDIS
    POD --> PG
    POD --> LLM_EP

    POD -.-x INTERNET
    POD -.-x OTHER_NS
    POD -.-x NODE_META
```

| Resource | Limit | Enforcement |
|----------|-------|-------------|
| CPU | 2 cores max | Kubernetes resource limits |
| Memory | 4 GB max | Kubernetes resource limits + OOM kill |
| Disk | Read-only root fs | securityContext.readOnlyRootFilesystem |
| Network | Allowlist only | NetworkPolicy |
| Process count | 256 max | PID limits via cgroup |
| File descriptors | 1024 max | ulimit via securityContext |
| Execution time | 120s per run | Application-level timeout |

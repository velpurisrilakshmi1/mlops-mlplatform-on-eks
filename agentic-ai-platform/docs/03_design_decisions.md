# Design Decisions (Architecture Decision Records)

Eight decisions made during the design of the Agentic AI Orchestration Platform. Each record follows the format: **Context → Decision → Consequences → Alternatives rejected**.

---

## ADR-001: LangGraph over CrewAI / AutoGen for Agent Orchestration

**Status**: Accepted

### Context

We need an agent orchestration framework that can express: multi-step reasoning loops (ReAct, Plan-and-Execute), multi-agent topologies (supervisor → subagents), human-in-the-loop interrupts, and streaming responses. Three frameworks were evaluated: LangGraph, CrewAI, and Microsoft AutoGen.

### Decision

Use **LangGraph** as the primary agent orchestration framework.

### Consequences

**Positive**
- LangGraph's directed graph model is a natural evolution of Airflow's DAG model — engineers already familiar with DAG-based thinking can adopt it quickly
- Full support for cyclic graphs (agent loops) — unlike Airflow, which is strictly acyclic
- First-class streaming: graphs emit tokens to clients in real time without buffering
- Native HITL support: `interrupt()` nodes pause graph execution and resume from saved checkpoint after human decision
- LangGraph Server provides a production-ready HTTP API (`/runs`, `/threads`, `/assistants`) — agents are called via REST, not imported as library code
- Active development by LangChain Inc. with strong enterprise adoption (Anthropic, Replit, LinkedIn)
- State is a typed Python dict — easy to inspect, debug, and serialize to DynamoDB for checkpointing

**Negative**
- Learning curve for engineers unfamiliar with graph-based programming
- LangGraph Server (the deployed API layer) is relatively new (2024) — less battle-tested than LangChain chains
- Requires understanding of reducers (state update functions) for concurrent node execution

### Alternatives rejected

**CrewAI**: High-level abstraction makes simple agent crews easy to create but production debugging is difficult. Crew configurations are opaque — when an agent fails mid-task, there is no checkpoint to resume from. The role/goal/backstory prompt construction is not inspectable. CrewAI is suitable for demos and prototypes, not for a platform where agents handle consequential actions.

**Microsoft AutoGen**: Research-oriented with conversational multi-agent patterns. AutoGen's `ConversableAgent` model is built for agent-to-agent dialog, not for tool-heavy, stateful production workflows. Limited streaming support. The framework is in heavy flux (v0.4 was a near-complete rewrite).

---

## ADR-002: Temporal over Airflow for Durable Agent Workflows

**Status**: Accepted

### Context

Long-horizon agents (e.g., a research agent that runs for hours, pauses waiting for HITL approval, then continues) need a durable execution framework that can: pause execution for arbitrary durations, guarantee exactly-once tool call execution, replay from failure, and provide a UI for workflow visualization.

The existing platform uses Airflow. Two options were evaluated: retain Airflow, or adopt Temporal.

### Decision

Use **Temporal** for durable agent workflow execution, operating alongside LangGraph (not replacing it).

- **LangGraph handles**: individual agent reasoning loops (think → tool → observe → think), the inner loop within a single run
- **Temporal handles**: the outer workflow that orchestrates multiple agent runs, manages long waits, and guarantees completion

### Consequences

**Positive**
- Temporal's workflow replay model handles arbitrary pauses (HITL wait of hours/days) without polling
- Exactly-once semantics for tool calls — critical for tools with side effects (sending emails, writing to databases)
- Workflows are written in Python (or Go/Java/TypeScript) — no YAML/JSON DSL unlike Airflow's DAG definitions
- Activity retries with configurable backoff are first-class — no need for custom retry logic in agent code
- Temporal Web UI shows workflow execution history, activity timelines, and failure reasons — equivalent to Airflow's task log UI
- Workers autoscale by polling task queue depth — same pattern as Airflow KubernetesExecutor

**Negative**
- New operational dependency — team must learn Temporal concepts (Workflow, Activity, Worker, Task Queue)
- Temporal Server requires PostgreSQL (shared with existing RDS) and Cassandra or PostgreSQL for visibility store
- Not a drop-in replacement for Airflow scheduling (cron-based scheduling is less native in Temporal)

### Alternatives rejected

**Airflow**: Airflow's task model is scheduling-centric and stateless between tasks. Airflow tasks are short-lived functions; agent workflows are long-lived, stateful, and event-driven. An Airflow DAG cannot be paused mid-execution waiting for a human decision without complex XCom + sensor workarounds. KubernetesExecutor spawns fresh pods per task — unsuitable for agents that maintain in-memory conversation state across steps.

---

## ADR-003: LiteLLM as the Unified LLM Gateway

**Status**: Accepted

### Context

The platform needs to route LLM requests to multiple providers (Bedrock, potentially OpenAI for comparison, potentially vLLM in the future). Agents must not embed provider-specific SDK calls — they need a stable interface that survives provider changes.

### Decision

Use **LiteLLM Proxy** deployed on EKS as a single OpenAI-compatible endpoint for all LLM inference.

### Consequences

**Positive**
- Agents use `openai.OpenAI(base_url=LITELLM_BASE_URL)` — a standard interface used by every LangChain/LangGraph integration
- Switching from Bedrock Claude to a vLLM-hosted Llama requires changing the model name string and updating LiteLLM's ConfigMap — **zero application code change**
- Built-in rate limiting per team, per model (Redis-backed) — replaces custom rate limit logic
- Cost callbacks: LiteLLM emits per-request token counts and costs to Langfuse automatically
- Fallback chains configurable declaratively: if `claude-3-5-sonnet` is throttled, fall back to `claude-3-haiku`
- LiteLLM has native support for Bedrock's cross-region inference and model invocation profiles

**Negative**
- Extra network hop: every LLM call goes agent → LiteLLM → Bedrock (adds ~5-10ms)
- LiteLLM is a third-party open-source project — API changes may require updates to the proxy config
- LiteLLM master key must be kept in Secrets Manager and rotated periodically

### Alternatives rejected

**Direct Bedrock SDK calls in agent code**: Provider lock-in baked into every agent. When a model is deprecated or pricing changes, every agent must be updated. No centralized rate limiting or cost tracking without custom code in each agent.

**AWS API Gateway as the LLM proxy**: Would require custom Lambda functions to translate OpenAI API format to Bedrock's request format for every model. LiteLLM already does this for 100+ models. API Gateway adds cost per request at scale.

---

## ADR-004: Langfuse Self-Hosted over LangSmith SaaS

**Status**: Accepted

### Context

LLMOps observability (trace/span collection, token cost tracking, evaluation datasets) is critical for production agents. Two main options: LangSmith (SaaS, by LangChain Inc.) and Langfuse (open-source, self-hostable).

### Decision

Self-host **Langfuse** on EKS backed by the shared RDS Aurora PostgreSQL instance.

### Consequences

**Positive**
- Agent traces contain user inputs and LLM outputs — potentially sensitive PII. Self-hosting keeps all trace data within the VPC, never leaving the AWS account
- Zero per-trace cost: LangSmith charges by events at scale; Langfuse self-hosted costs only RDS storage and S3 trace archive
- Langfuse has native integration with LangChain, LangGraph, LiteLLM (automatic trace injection)
- Full API: Langfuse's SDK exposes datasets, scores, prompts, and evaluations programmatically — used by the Evaluation module
- Grafana datasource: Langfuse metrics (p95 latency, cost, error rate) queryable via Prometheus (Langfuse exposes `/metrics` endpoint)
- Open-source: can fork and add custom trace fields if needed

**Negative**
- Operational responsibility for Langfuse upgrades and RDS schema migrations
- Self-hosted Langfuse lacks some SaaS features (e.g., Langfuse Cloud's automatic PII masking) — compensated by Presidio in the security layer

### Alternatives rejected

**LangSmith (SaaS)**: At 1M traces/month, LangSmith Developer+ plan is ~$39/month — acceptable. But at enterprise scale (10M+ traces), cost becomes significant. More importantly, traces contain conversation data that must not leave the VPC for compliance in most enterprise settings.

**Custom OpenTelemetry backend (Jaeger/Tempo)**: General-purpose tracing stores lack LLM-specific concepts (token counts, model names, prompt templates, evaluation scores). Would require building the LLM-specific layer on top — effectively rebuilding Langfuse.

---

## ADR-005: OpenSearch Serverless for Vector Memory (vs Qdrant on EKS)

**Status**: Accepted with caveat

### Context

Long-term semantic memory requires a vector database for embedding storage and approximate nearest-neighbor (ANN) retrieval. Two options evaluated: OpenSearch Serverless (AWS-managed) and Qdrant (open-source on EKS).

### Decision

Use **OpenSearch Serverless** for production vector memory.

**Caveat for small deployments**: OpenSearch Serverless has a minimum cost of ~$700/month (2 OCU minimum). For development or small teams, the `memory` module supports a feature flag `use_qdrant_fallback = true` that deploys a single-node Qdrant StatefulSet on EKS instead. The Memory Service API is the same in both cases — **zero agent code change**.

### Consequences

**Positive**
- No index management, replication configuration, or upgrade operations
- Auto-scales with query load — no capacity planning for vector search
- IRSA access: `aoss:APIAccessAll` — no credentials to manage
- Supports both k-NN vector search and hybrid search (BM25 + vector) — useful for retrieval-augmented memory

**Negative**
- $700/month minimum regardless of usage — expensive for small/dev deployments
- Less flexible than Qdrant for advanced filtering and payload-based search
- Cold start on first query after idle period

### Alternatives rejected

**Qdrant on EKS** (as primary): Excellent vector database with strong filtering capabilities. However, requires operational management (StatefulSet, PVC snapshots, upgrades). Chosen as the fallback option for cost-constrained deployments via the feature flag.

**Pinecone (SaaS)**: Per-vector pricing at scale and data leaving the VPC make this unsuitable.

**pgvector on RDS**: Good for low-dimensional vectors and small corpora (<1M vectors). Performance degrades significantly at scale due to PostgreSQL's sequential scan for ANN. Acceptable as a Phase 1 bootstrap before migrating to OpenSearch Serverless.

---

## ADR-006: IRSA Per Module Service Account (identical to existing platform)

**Status**: Accepted

### Context

Every module needs access to specific AWS resources (Bedrock, DynamoDB tables, S3 buckets, OpenSearch). The existing MLOps platform uses IRSA (IAM Roles for Service Accounts) with one role per module. This approach should be continued in the agentic platform.

### Decision

**Every module gets exactly one Kubernetes ServiceAccount with one dedicated IAM role scoped to only that module's AWS resources.**

| Module | IAM Role | Key Permissions |
|---|---|---|
| `llm-gateway` | `agenticplatform-litellm-role` | `bedrock:InvokeModel*` on all model ARNs |
| `agent-registry` | `agenticplatform-registry-role` | DynamoDB CRUD on registry tables, S3 on registry bucket |
| `observability` | `agenticplatform-langfuse-role` | S3 write on trace archive bucket |
| `memory` | `agenticplatform-memory-role` | `aoss:APIAccessAll` on OpenSearch collection, DynamoDB CRUD, ElastiCache (via VPC) |
| `orchestration` | `agenticplatform-langgraph-role` | Bedrock (via LiteLLM, not direct), DynamoDB (checkpoint), S3 |
| `tool-registry` | `agenticplatform-mcp-role` | `lambda:InvokeFunction` on registered tool Lambdas |
| `hitl` | `agenticplatform-hitl-role` | SQS send/receive, SNS publish, DynamoDB CRUD on hitl-state |

### Consequences

**Positive**
- Blast radius of a compromised pod is limited to its own module's resources — identical security property to the existing platform
- CloudTrail audits show exactly which pod (via ServiceAccount → IAM role assumption) accessed which resource
- No static credentials anywhere on nodes or in pods
- Follows the principle of least privilege at the pod level

**Negative**
- More IAM roles to manage (one per module vs. one per cluster)
- Each new module requires a new IRSA role Terraform resource — consistent pattern but more code

---

## ADR-007: Feature-Flag `deploy_<module>` Variables for Every Module

**Status**: Accepted

### Context

The existing platform uses `var.deploy_mlflow`, `var.deploy_airflow`, etc. to allow incremental deployment. The same pattern should be applied to all 12 agentic platform modules.

### Decision

Every module has a corresponding `variable "deploy_<module>"` boolean in `variables.tf`, defaulting to `false`. Modules are activated by setting `deploy_<module> = true` in the environment `.tfvars` file.

```hcl
variable "deploy_llm_gateway"    { type = bool; default = false }
variable "deploy_agent_registry" { type = bool; default = false }
variable "deploy_observability"  { type = bool; default = false }
variable "deploy_dev_sandbox"    { type = bool; default = false }
variable "deploy_orchestration"  { type = bool; default = false }
variable "deploy_memory"         { type = bool; default = false }
variable "deploy_tool_registry"  { type = bool; default = false }
variable "deploy_evaluation"     { type = bool; default = false }
variable "deploy_hitl"           { type = bool; default = false }
variable "deploy_security"       { type = bool; default = false }
variable "deploy_multitenancy"   { type = bool; default = false }
variable "deploy_dashboard"      { type = bool; default = false }
```

### Consequences

**Positive**
- Phase 1 deployments use `phase1.tfvars` with only `deploy_llm_gateway`, `deploy_agent_registry`, `deploy_observability`, `deploy_dev_sandbox` set to `true`
- Prevents accidentally deploying expensive Phase 3 resources (WAF, HITL) in a dev environment
- Allows disaster recovery: redeploy only the broken module without touching the rest
- Mirrors the exact pattern the team already knows from the MLOps platform

**Negative**
- Module dependency ordering must be handled explicitly via `depends_on` or by ensuring cross-module `count = 0` modules don't produce broken `output` references

---

## ADR-008: Shared Aurora PostgreSQL Cluster (vs Per-Module RDS Instances)

**Status**: Accepted

### Context

The existing MLOps platform provisions two separate RDS instances: PostgreSQL for Airflow and MySQL for MLflow. The agentic platform needs PostgreSQL for: Langfuse metadata, Agent Registry, Temporal visibility store, Evaluation results — at least 4 databases.

Two options: provision one RDS instance per module (existing pattern), or a single shared Aurora PostgreSQL cluster with separate databases per module.

### Decision

Use a **single RDS Aurora PostgreSQL Serverless v2** cluster with separate databases for each module.

| Module | Database Name | Schema Owner |
|---|---|---|
| Langfuse | `langfuse` | `langfuse_user` |
| Agent Registry | `agent_registry` | `registry_user` |
| Temporal | `temporal` | `temporal_user` |
| Temporal Visibility | `temporal_visibility` | `temporal_user` |
| Evaluation | `evaluation` | `eval_user` |

### Consequences

**Positive**
- Aurora Serverless v2 scales to zero ACUs during off-hours — significant cost savings vs. 4 separate `db.t3.micro` instances running 24/7
- Single endpoint to manage — one security group, one subnet group, one backup policy
- Cross-module queries possible if ever needed (e.g., joining eval results with registry metadata)
- Aurora's read replica add-on is available if any module needs read scaling

**Negative**
- Single point of failure: if the Aurora cluster has an issue, all modules are affected (mitigated by Aurora's multi-AZ automatic failover)
- Per-module users reduce but don't eliminate blast radius for SQL injection in one module affecting another database
- Schema migrations for one module require careful coordination to avoid locking the cluster

### Alternatives rejected

**Separate RDS instances per module** (existing pattern): 4 `db.t3.micro` instances at ~$0.018/hr each = ~$52/month just for idle RDS instances. Aurora Serverless v2 costs ~$0.12/ACU-hour but scales to near-zero when idle — far cheaper for development environments. The existing platform's two-instance pattern made sense for two databases; four-plus instances for this platform is not justified.

**MySQL for some modules**: MySQL is used for MLflow in the existing platform for historical reasons. Standardizing on PostgreSQL across the new platform reduces operational diversity and allows consistent use of PostgreSQL-specific features (JSONB, advisory locks used by Temporal).

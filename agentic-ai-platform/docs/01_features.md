# Platform Features

Twelve core capabilities of the Agentic AI Orchestration Platform.

---

## 1. Agent Orchestration Engine

**Modules**: `orchestration` | **Phase**: 2

The heart of the platform. Two complementary systems handle different orchestration concerns:

**LangGraph Server** — graph-based agent execution engine
- Directed acyclic and cyclic graphs for agent reasoning
- Supports all major reasoning patterns: ReAct, Plan-and-Execute, Reflexion, multi-agent supervisor/subagent topologies
- Streaming-first: token-level streaming responses back to clients
- Thread/run model: each agent invocation is a `run` within a stateful `thread` (conversation)
- HTTP API: `/runs`, `/threads`, `/assistants` endpoints compatible with LangGraph Cloud SDK
- Interrupt nodes: pause execution for HITL approval, resume on human decision
- Built-in checkpointing: agent state persisted to DynamoDB between loop iterations

**Temporal Server + Workers** — durable workflow execution for long-horizon agents
- Guarantees exactly-once execution semantics for tool calls
- Workflow replay: agents can pause for hours (HITL approval, polling) and resume without state loss
- Worker autoscaling: HPA on Temporal task queue depth
- Replaces Airflow's DAG model for stateful, long-running agent pipelines
- Temporal Web UI for workflow visualization (mirrors Airflow UI role in existing platform)

**Key difference from Airflow**: Temporal handles cyclic, conditional, tool-calling loops natively. Airflow DAGs are scheduling-centric and stateless between tasks — unsuitable for agent loops.

---

## 2. Agent Registry

**Modules**: `agent-registry` | **Phase**: 1

Version-controlled catalog of agents, prompt templates, and tool schemas.

**Agent definitions**
- Stored in DynamoDB (`agent-definitions` table): name, version, description, graph_config, default_model, tool_ids
- Serialized LangGraph graphs stored as JSON artifacts in S3 (`agenticplatform-agent-registry` bucket)
- Semantic versioning: promote versions through `dev → staging → production` lifecycle stages
- Container images for custom agent runtimes stored in ECR

**Prompt templates**
- DynamoDB table `prompt-templates`: versioned system prompts, few-shot examples, chain-of-thought instructions
- Variables support: `{customer_name}`, `{context}` interpolation at runtime
- A/B testing: multiple prompt versions active simultaneously, traffic split configured in Evaluation module

**Tool schemas**
- DynamoDB table `tool-schemas`: MCP-compatible JSON Schema definitions for every registered tool
- Links to Tool Registry module for execution routing

**API**
- FastAPI service on EKS, ALB ingress at `/registry/*`
- IRSA role: `DynamoDB:GetItem/PutItem/Query`, `S3:GetObject/PutObject` on registry bucket
- GitHub OAuth: team-scoped access (same pattern as existing platform's webserver auth)

---

## 3. Memory Management

**Modules**: `memory` | **Phase**: 2

Four-tier memory architecture. Each tier serves a different temporal and semantic scope:

| Tier | Technology | Scope | TTL | Use Case |
|---|---|---|---|---|
| In-context | LLM token window | Current request | Request duration | Immediate reasoning context |
| Working memory | ElastiCache Redis | Session / conversation thread | 24 hours | Multi-turn conversation state, tool results |
| Episodic memory | DynamoDB | Agent lifetime | 90 days | Event log: what the agent did, when, and outcome |
| Semantic memory | OpenSearch Serverless | Long-term | Indefinite | Knowledge base, past run insights, retrieved facts |

**Memory Service** (FastAPI on EKS)
- Unified API: `POST /memory/retrieve`, `POST /memory/store`, `DELETE /memory/{id}`
- Abstracts all four tiers — LangGraph nodes call a single service endpoint
- Retrieval-augmented generation: semantic search over OpenSearch returns top-k chunks injected into the LLM prompt
- EFS PVC: memory snapshot export/import for disaster recovery and cross-environment migration

**OpenSearch Serverless**
- Serverless vector collection: no index management, auto-scales with query load
- IRSA access: `aoss:APIAccessAll` scoped to the collection ARN
- Embedding model: Amazon Titan Embeddings v2 via Bedrock (no separate embedding service to manage)

**Redis (ElastiCache)**
- Shared cluster with `llm-gateway` for rate limit state
- Key pattern: `thread:{thread_id}:state` — JSON blob of working memory
- TTL enforcement by Redis natively

---

## 4. Tool Registry + MCP Server

**Modules**: `tool-registry` | **Phase**: 2

Standard interface for all agent tools, implementing the Model Context Protocol (MCP).

**Tool Registry API** (FastAPI)
- CRUD for tool definitions: name, description, input/output JSON Schema, execution_endpoint
- Versioning: tools follow the same semantic versioning as agents
- Discovery: agents query `/tools?capability=web_search` to find tools by capability tag
- ALB ingress at `/tools/*`

**MCP Server** (Python, on EKS)
- Implements MCP protocol: `tools/list`, `tools/call` endpoints
- Routes `tools/call` to the registered execution endpoint (Lambda or internal service)
- Returns structured `ToolResult` with content and error handling
- LangGraph agents consume MCP server directly via `langchain_mcp_adapters`

**Built-in Lambda tools**
- `s3_read`: Read objects from S3 (scoped by IRSA to allowed buckets)
- `dynamodb_query`: Query DynamoDB tables (read-only, scoped by IAM condition)
- `ses_send`: Send emails via SES
- `bedrock_knowledge_base`: Query Bedrock Knowledge Bases
- `http_request`: Outbound HTTP with rate limiting and timeout controls

**API Gateway** — external tool façade
- Public endpoint for tools that need to be called from outside the VPC
- IAM authorizer: only registered agent IRSA roles can invoke

---

## 5. LLM Gateway

**Modules**: `llm-gateway` | **Phase**: 1

Unified, OpenAI-compatible API layer over all LLM providers. Agents never call providers directly.

**LiteLLM Proxy** (Helm chart on EKS)
- OpenAI-compatible REST API: `POST /v1/chat/completions` — zero code change when switching models
- Supported model list (via Bedrock):
  - `anthropic.claude-3-5-sonnet-20241022-v2:0` (default reasoning)
  - `anthropic.claude-3-haiku-20240307-v1:0` (fast/cheap tasks)
  - `meta.llama3-3-70b-instruct-v1:0` (open-weight fallback)
  - `amazon.titan-text-premier-v1:0` (AWS-native tasks)
- Model routing: route by model name, or by `x-litellm-tag: fast|smart|cheap` header
- Fallback chains: if Claude Sonnet is throttled, fall back to Haiku automatically
- Streaming: full token-level streaming support via SSE

**Rate limiting**
- Per-team, per-model limits stored in ElastiCache Redis
- Configurable TPM (tokens per minute) and RPM (requests per minute) per team
- Returns `429` with `Retry-After` header on limit exceeded

**Cost tracking**
- LiteLLM callback: every completion logs tokens + cost to Langfuse trace
- Per-model pricing table configurable in LiteLLM ConfigMap
- Grafana dashboard: per-team, per-model daily spend

**IRSA**
- Service account annotated with `litellm-bedrock-role`
- Policy: `bedrock:InvokeModel*` on all model ARNs in the account
- No static API keys; Bedrock access entirely via IRSA token exchange

---

## 6. Evaluation Framework

**Modules**: `evaluation` | **Phase**: 2

Systematic evaluation of agent quality across runs, prompt versions, and model variants.

**Evaluation Service** (FastAPI on EKS)
- Run evaluation jobs: select a Langfuse dataset + evaluator + agent version
- Evaluators:
  - **LLM-as-judge**: Claude judges response quality on rubric (correctness, helpfulness, safety)
  - **Human scoring**: routes subset to HITL module for human annotation
  - **Custom metrics**: exact-match, BLEU, tool-call-accuracy for structured tasks
- Results stored in Langfuse scores API + RDS `eval_results` table

**A/B testing**
- Define experiment: `control=prompt_v1, treatment=prompt_v2, traffic_split=50%`
- LangGraph routes runs to variant based on thread_id hash
- Statistical significance test run after N samples (configurable)

**Regression testing**
- CI/CD hook: on agent version bump, run regression suite against golden dataset
- GitHub Actions workflow: call Evaluation Service API, fail PR if score drops below threshold
- Prevents deploying agents that regress on known-good test cases

**Grafana dashboards**
- `agent-eval-overview.json`: per-agent mean score over time, pass/fail rate
- `ab-test-results.json`: variant comparison, confidence intervals

---

## 7. LLMOps Observability

**Modules**: `observability` | **Phase**: 1

Complete visibility into agent behavior — traces, token economics, latency, and infrastructure health in one place.

**Langfuse** (self-hosted on EKS, PostgreSQL-backed via RDS)
- Distributed tracing for every LLM call: input, output, latency, token count, cost
- Span hierarchy: `run → agent_node → llm_call / tool_call / memory_retrieval`
- Session grouping: all runs within a `thread_id` grouped into a session
- Prompt management: link traces to the prompt template version used
- Dataset creation: tag traces as evaluation examples directly from the UI
- ALB ingress at `/langfuse/*`

**OpenTelemetry Collector** (DaemonSet)
- Scrapes all agent pods with `otel.io/scrape: "true"` annotation
- Forwards spans to Langfuse via OTLP/HTTP
- Forwards metrics to Prometheus (`otel_*` metric prefix)

**Prometheus + Grafana** (extended from existing monitoring module)
- Retains all existing K8s dashboards (cluster, node, PVC)
- New agent-specific dashboards:
  - `token-cost.json`: daily/hourly token spend by team and model
  - `agent-latency.json`: p50/p95/p99 latency per agent type
  - `llm-error-rate.json`: 4xx/5xx rates from LiteLLM, guardrail blocks, tool errors
  - `memory-retrieval.json`: OpenSearch query latency, cache hit rate

**Key metrics tracked**

| Metric | Source | Alert Threshold |
|---|---|---|
| LLM p99 latency | LiteLLM / Langfuse | > 10s |
| Token cost per team (daily) | LiteLLM callbacks | > budget limit |
| Agent error rate | LangGraph traces | > 5% in 5m |
| OpenSearch query latency | OTel | > 500ms p95 |
| Redis memory usage | ElastiCache CloudWatch | > 80% |
| Temporal worker lag | Temporal metrics | > 100 queued |
| Guardrail block rate | Bedrock / Langfuse | > 1% (investigate prompt injection) |

---

## 8. Human-in-the-Loop (HITL)

**Modules**: `hitl` | **Phase**: 3

Structured human oversight for agent actions that require approval or correction.

**Integration with LangGraph**
- Agents call `interrupt("hitl_approval")` node — execution pauses
- LangGraph persists checkpoint to DynamoDB (Temporal handles long waits via durable timers)
- When human approves/rejects, LangGraph resumes from the saved checkpoint

**HITL Service** (FastAPI + React SPA, on EKS)
- Review queue: pending approvals with full trace context (agent inputs, proposed action, tool args)
- Reviewer assigns: tasks routable to specific teams or individuals
- Decision recording: approve / reject / modify (annotator can edit the agent's proposed action)
- Feedback collection: free-text annotation stored as Langfuse score for training data

**Messaging backbone**
- SQS queue `agent-approval-requests` — HITL service polls for new tasks
- Dead-letter queue: tasks unanswered after 48h routed to DLQ, agent times out gracefully
- SNS topic `agent-notifications`: email + Slack Lambda subscriber for reviewer alerts
- SNS sends `{"task_id": "...", "agent": "...", "action_summary": "...", "review_url": "..."}` to Slack webhook

**DynamoDB state machine**
- `hitl-state` table: `{task_id, status: pending|approved|rejected|expired, reviewer, decision, timestamp}`
- TTL: 7 days (tasks auto-expire from table after resolution)

---

## 9. Multi-tenancy

**Modules**: `multitenancy`, `team-profiles` | **Phase**: 3 (profiles: Phase 1)

Team-level isolation at every layer of the stack.

**Kubernetes isolation**
- One Namespace per team (provisioned by Terraform `for_each` over `team-list.yaml`)
- NetworkPolicy: `deny-all ingress` by default, allow only from same namespace + ingress controller namespace
- ResourceQuota per namespace: CPU/memory limits prevent noisy-neighbor problems

**IAM isolation**
- IAM role per team (`team-{name}-role`) with scoped policies:
  - S3: only `agenticplatform-{team}-*` prefixes
  - DynamoDB: condition `dynamodb:LeadingKeys` = team prefix
  - Bedrock: allow `InvokeModel*` (shared, no per-team restriction needed)
- IRSA: team agent pods use team-scoped IAM role

**Langfuse isolation**
- Langfuse organization per team, project per agent type
- API keys scoped to organization — teams cannot see each other's traces

**Cost attribution**
- All AWS resources tagged `team={name}`, `platform=agenticplatform`
- AWS Cost Explorer tag-based reports: per-team Bedrock spend, DynamoDB read/write units
- Grafana `team-cost.json` dashboard: pulls from AWS Cost Explorer API via CloudWatch

**Team configuration** (`deployment/profiles/team-list.yaml`)
```yaml
teams:
  - name: search-agents
    members: [alice, bob]
    role: AgentDeveloper
    namespace: search-agents
    bedrock_models: [claude-3-5-sonnet, claude-3-haiku]
  - name: data-agents
    members: [carol]
    role: AgentUser
    namespace: data-agents
    bedrock_models: [claude-3-haiku]
```

---

## 10. Security Layer

**Modules**: `security` | **Phase**: 3

Defense-in-depth at the edge, at inference time, within pods, and at policy level.

**AWS WAF** (attached to ALB)
- Managed rule group: `AWSManagedRulesCommonRuleSet` (OWASP Top 10)
- Custom rule: block requests with prompt injection patterns (`ignore previous instructions`, `jailbreak`, etc.)
- Rate limiting: 1000 req/5min per IP

**Bedrock Guardrails**
- PII detection and redaction: SSN, credit card, email, phone — redacted before reaching LLM
- Denied topics: configurable list (e.g., block financial advice generation)
- Content filter: violence, hate speech, sexual content — configurable thresholds
- Grounding filter: prevent hallucinated citations
- All guardrail blocks logged as Langfuse events for audit trail

**Presidio** (Microsoft, on EKS as a sidecar/service)
- Pre-processing: scan user input for PII before it enters LangGraph
- Post-processing: scan LLM output before returning to client
- Custom recognizers: internal entity types (employee IDs, project codes)
- Operates on structured and unstructured text

**OPA (Open Policy Agent)**
- Kubernetes admission controller (via Gatekeeper): enforce pod security standards
- Agent policy: `agent X is not allowed to call tool Y` — policy checked by MCP Server before tool execution
- Prompt policy: block certain prompt templates from being used by unauthorized teams

**KMS**
- Customer-managed key per namespace for envelope encryption of DynamoDB items and S3 objects
- Automatic key rotation enabled

---

## 11. Dev Sandbox

**Modules**: `dev-sandbox` | **Phase**: 1

A pre-configured development environment where engineers can build, test, and iterate on agents interactively.

**Code-Server** (VS Code in browser, on EKS)
- Full VS Code experience in the browser — no local setup required
- Pre-installed extensions: Python, LangChain/LangGraph snippets, Terraform
- EFS home directories: persistent across pod restarts (same EFS provisioner as existing JupyterHub)
- GitHub OAuth: same org-based access control pattern
- ALB ingress at `/code/*`

**JupyterHub** (retained from existing platform)
- Extended with agentic AI environment variables injected into every kernel:
  - `LITELLM_BASE_URL=https://{domain}/llm/v1`
  - `LANGFUSE_SECRET_KEY` (from Secrets Manager via ESO)
  - `AGENT_REGISTRY_URL=https://{domain}/registry`
  - `MEMORY_SERVICE_URL=https://{domain}/memory`
- Custom kernel image: adds `langchain`, `langgraph`, `langfuse`, `anthropic`, `boto3` to the base
- ALB ingress at `/jupyter/*`

**Pre-configured notebooks** (auto-cloned via git-sync lifecycle hook)
- `01_hello_agent.ipynb` — first LangGraph agent calling Bedrock via LiteLLM
- `02_memory_demo.ipynb` — semantic memory store and retrieval
- `03_tool_calling.ipynb` — registering and calling an MCP tool
- `04_evaluation.ipynb` — running an evaluation job via Evaluation Service API

---

## 12. Unified Dashboard

**Modules**: `dashboard` | **Phase**: 3

Single-pane-of-glass for platform operators and team leads.

**React SPA** (on EKS, ALB ingress at `/`)

Sections:
- **Agent Runs**: live feed of active and recent runs across all teams (calls LangGraph Server API)
- **Registry**: browsable catalog of agents, prompts, and tools with version history
- **Observability**: embedded Grafana panels (token cost, latency, error rate) — uses `allow_embedding = true` Grafana config (same pattern as existing platform's Grafana dashboards)
- **HITL Queue**: pending human approval tasks with quick approve/reject actions
- **Cost**: per-team spend this month vs. budget, top models by cost
- **Health**: EKS node status, service health checks, Temporal worker lag

**Mirrors the existing Vue.js dashboard** in the MLOps platform — same Helm chart pattern, same ALB annotation, same GitHub OAuth, upgraded to React for richer state management needed by the agent run stream.

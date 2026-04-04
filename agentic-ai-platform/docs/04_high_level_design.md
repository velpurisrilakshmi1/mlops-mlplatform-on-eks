# High Level Design (HLD)

## Overview

The Agentic AI Orchestration Platform is a multi-tier, multi-tenant infrastructure on AWS designed to host, run, observe, and govern multi-agent AI workloads. It inherits all infrastructure patterns from the MLOps platform in this repository and extends them for agentic concerns: stateful agent reasoning loops, memory persistence, tool execution, LLM inference routing, human oversight, and LLMOps observability.

---

## C4 Level 1 — System Context

```mermaid
C4Context
    title Agentic AI Platform — System Context

    Person(dev, "Agent Developer", "Builds and tests agents in Code-Server / JupyterHub")
    Person(user, "Agent Consumer", "Calls agents via REST API or UI")
    Person(reviewer, "Human Reviewer", "Approves/rejects agent actions in HITL UI")
    Person(ops, "Platform Operator", "Monitors cost, latency, errors in Grafana/Langfuse")

    System(platform, "Agentic AI Platform", "Orchestrates multi-agent AI workflows on EKS with AWS Bedrock inference")

    System_Ext(github, "GitHub", "Source control, OAuth identity provider, CI/CD triggers")
    System_Ext(bedrock, "AWS Bedrock", "Managed LLM inference: Claude, Llama, Titan")
    System_Ext(slack, "Slack / Email", "HITL reviewer notifications via SNS")

    Rel(dev, platform, "Develops agents, registers prompts/tools, views traces")
    Rel(user, platform, "Submits agent runs via REST API")
    Rel(reviewer, platform, "Reviews and approves/rejects agent actions")
    Rel(ops, platform, "Monitors via Grafana + Langfuse dashboards")
    Rel(platform, bedrock, "LLM inference via LiteLLM → Bedrock API")
    Rel(platform, github, "OAuth auth, DAG sync, CI/CD")
    Rel(platform, slack, "HITL notifications via SNS → Lambda → Slack webhook")
```

---

## C4 Level 2 — Container Diagram

```mermaid
graph TB
    subgraph External["External Actors"]
        DEV[Agent Developer]
        USER[Agent Consumer]
        REVIEWER[Human Reviewer]
        OPS[Platform Operator]
    end

    subgraph AWS_Account["AWS Account"]

        subgraph Edge["Edge Layer"]
            WAF[AWS WAF\nInjection defense]
            ALB[Application Load Balancer\nPath-based routing]
            R53[Route 53\nDNS via ExternalDNS]
        end

        subgraph EKS_Cluster["EKS Cluster"]

            subgraph Dev_Tools["Developer Tools"]
                VSCODE[Code-Server\nVS Code in browser]
                JUPYTER[JupyterHub\nNotebooks]
            end

            subgraph Inference["Inference Layer"]
                LITELLM[LiteLLM Proxy\nUnified LLM API]
                GUARDRAILS_SVC[Guardrails Interceptor\nBedrock Guardrails calls]
            end

            subgraph Registry["Registry Layer"]
                AGENT_REG[Agent Registry\nAgents · Prompts · Tools]
            end

            subgraph Orchestration["Orchestration Layer"]
                LANGGRAPH[LangGraph Server\nAgent graph execution]
                TEMPORAL[Temporal\nDurable workflows]
            end

            subgraph Memory["Memory Layer"]
                MEM_SVC[Memory Service\nUnified memory API]
            end

            subgraph Tools["Tool Layer"]
                MCP[MCP Server\nTool protocol executor]
            end

            subgraph Observability["Observability Layer"]
                LANGFUSE[Langfuse\nLLMOps tracing]
                PROMETHEUS[Prometheus\nMetrics]
                GRAFANA[Grafana\nDashboards]
                OTEL[OTel Collector\nSpan aggregator]
            end

            subgraph HITL_Layer["Human Oversight Layer"]
                HITL[HITL Service\nApproval queue + UI]
            end

            subgraph Security_Layer["Security Layer"]
                PRESIDIO[Presidio\nPII detection/redaction]
                OPA[OPA\nPolicy enforcement]
            end

        end

        subgraph AWS_Managed["AWS Managed Services"]
            BEDROCK[AWS Bedrock\nLLM Inference]
            OPENSEARCH[OpenSearch Serverless\nVector memory]
            ELASTICACHE[ElastiCache Redis\nWorking memory]
            DYNAMODB[DynamoDB\nEpisodic memory + state]
            RDS[RDS Aurora PostgreSQL\nMetadata]
            S3[S3\nArtifacts + traces]
            SQS[SQS\nApproval queue]
            SNS[SNS\nNotifications]
            EB[EventBridge\nAgent event bus]
        end

    end

    DEV --> ALB --> VSCODE & JUPYTER
    USER --> WAF --> ALB --> LITELLM
    REVIEWER --> ALB --> HITL
    OPS --> ALB --> GRAFANA & LANGFUSE

    LITELLM --> GUARDRAILS_SVC --> BEDROCK
    LANGGRAPH --> LITELLM
    LANGGRAPH --> MEM_SVC
    LANGGRAPH --> MCP
    LANGGRAPH --> HITL
    TEMPORAL --> LANGGRAPH

    MEM_SVC --> OPENSEARCH & ELASTICACHE & DYNAMODB
    AGENT_REG --> RDS & S3
    LANGFUSE --> RDS & S3
    OTEL --> LANGFUSE & PROMETHEUS --> GRAFANA

    HITL --> SQS & SNS
    PRESIDIO --> LANGGRAPH
    OPA --> MCP & LANGGRAPH
```

---

## System Layers

The platform is structured in six horizontal layers. Each layer has a clear responsibility boundary.

### Layer 1: Edge
| Component | Technology | Responsibility |
|---|---|---|
| Route 53 | AWS Managed DNS | Domain routing, ExternalDNS auto-sync from K8s Ingress |
| AWS WAF | AWS Managed WAF | OWASP Top 10, prompt injection pattern rules, IP rate limiting |
| ALB | AWS ALB (via AWS LBC) | Path-based routing to all EKS services; shared group `agenticplatform` |

**Key decision**: Single ALB for all services (cost-efficient, same pattern as MLOps platform's `mlplatform` group).

### Layer 2: Developer Tools
| Component | Technology | Responsibility |
|---|---|---|
| Code-Server | VS Code in browser | Agent development environment with pre-configured env vars |
| JupyterHub | JupyterHub 2.x | Notebook-based experimentation, extended from existing platform |

Both authenticated via GitHub OAuth (organization + team membership check).

### Layer 3: Inference
| Component | Technology | Responsibility |
|---|---|---|
| LiteLLM Proxy | LiteLLM OSS | Unified OpenAI-compatible API over Bedrock and future providers |
| AWS Bedrock | AWS Managed | LLM inference: Claude 3.5/3 Haiku, Llama 3.3 70B, Titan |
| Bedrock Guardrails | AWS Managed | Pre-inference PII filter, topic denial, content filter |

**Key decision**: LiteLLM creates a provider-agnostic boundary. The orchestration layer never calls Bedrock directly.

### Layer 4: Orchestration
| Component | Technology | Responsibility |
|---|---|---|
| LangGraph Server | LangGraph OSS | Agent graph execution engine; REST API for runs/threads |
| Temporal Server | Temporal OSS | Durable workflow execution for long-horizon agent tasks |
| Temporal Workers | Custom Python | Execute Temporal activities (individual agent tasks) |

**Key decision**: LangGraph handles the inner reasoning loop (think → tool → observe); Temporal handles the outer workflow (sequence of agent tasks with durability guarantees).

### Layer 5: Memory
| Component | Technology | Responsibility |
|---|---|---|
| Memory Service | FastAPI (custom) | Unified API abstracting all four memory tiers |
| OpenSearch Serverless | AWS Managed | Long-term semantic vector memory (embedding search) |
| ElastiCache Redis | AWS Managed | Short-term working memory, conversation state |
| DynamoDB | AWS Managed | Episodic memory (structured event log per agent run) |
| EFS | AWS Managed | Memory snapshot persistence across pod restarts |

### Layer 6: Observability
| Component | Technology | Responsibility |
|---|---|---|
| Langfuse | Self-hosted OSS | LLM trace/span collection, token costs, eval scores |
| OpenTelemetry Collector | CNCF OSS | Span aggregation from all agent pods |
| Prometheus | OSS | Time-series metrics for infra + LLM gateway |
| Grafana | OSS | Unified dashboards: infra + LLMOps metrics |

---

## Deployment Zones

```mermaid
graph LR
    subgraph VPC["VPC: 10.0.0.0/16"]
        subgraph Public["Public Subnets (10.0.4-6.0/24)"]
            NAT[NAT Gateway\nAZ1 only]
            ALB_NODE[ALB\nInternet-facing]
        end
        subgraph Private["Private Subnets (10.0.1-3.0/24)"]
            EKS_NG0[EKS ng0\nt3.small\nmin=0 max=5]
            EKS_NG1[EKS ng1\nt3.medium\nmin=4 max=6]
            EKS_NG_AGENT[EKS ng_agent_worker\nc6i.2xlarge\nmin=2 max=10]
            EKS_NG_GPU[EKS ng_gpu_spot\ng4dn.xlarge\nmin=0 max=3\nSpot + Taint]
            RDS_AURORA[RDS Aurora\nPostgreSQL\nMulti-AZ]
            REDIS[ElastiCache\nRedis]
            EFS_MT[EFS Mount Targets\nAZ1 · AZ2 · AZ3]
        end
    end
    subgraph AWS_Global["AWS Regional Services"]
        OPENSEARCH_SLS[OpenSearch\nServerless]
        DYNAMO_GLOBAL[DynamoDB\nOn-demand]
        BEDROCK_EP[Bedrock\nAPI Endpoint]
        S3_GLOBAL[S3 Buckets]
    end

    ALB_NODE --> EKS_NG0 & EKS_NG1 & EKS_NG_AGENT
    EKS_NG_AGENT --> BEDROCK_EP
    EKS_NG_AGENT --> OPENSEARCH_SLS
    EKS_NG_AGENT --> DYNAMO_GLOBAL
    EKS_NG_AGENT --> S3_GLOBAL
    EKS_NG_AGENT --> RDS_AURORA & REDIS & EFS_MT
```

**New node groups vs existing platform**:

| Node Group | Instance | Min | Max | Purpose |
|---|---|---|---|---|
| `ng0` | t3.small | 0 | 5 | Retained: general workloads |
| `ng1` | t3.medium | 4 | 6 | Retained: baseline workloads |
| `ng_agent_worker` | c6i.2xlarge | 2 | 10 | **New**: LangGraph, Temporal workers, Memory Service |
| `ng_gpu_spot` | g4dn.xlarge | 0 | 3 | **New**: Optional vLLM (Spot, tainted `NoSchedule`) |

---

## Security Architecture

```mermaid
graph TB
    subgraph Network["Network Security"]
        WAF_NET[WAF\nOWASP + prompt injection rules]
        ALB_SEC[ALB\nHTTPS termination\nSecurity Group: 443 only]
        VPC_SEC[VPC\nPrivate subnets for all workloads\nNo direct internet access]
        SG_RDS[SG: RDS\nAllow 5432 from EKS CIDR only]
        SG_REDIS[SG: Redis\nAllow 6379 from EKS CIDR only]
    end

    subgraph Identity["Identity & Access"]
        GITHUB_OAUTH[GitHub OAuth\nTeam-based access to all UIs]
        IRSA[IRSA per module\nPod-level AWS auth via OIDC]
        RBAC[K8s RBAC\nNamespace-scoped roles per team]
        IAM_TEAM[IAM Role per team\nScoped S3 + DynamoDB + Bedrock]
    end

    subgraph Data["Data Security"]
        KMS_ENC[KMS CMK\nEnvelope encryption for S3 + DynamoDB]
        S3_ENC[S3 AES256\nAll buckets encrypted at rest]
        RDS_ENC[RDS Encryption\nStorage encrypted at rest]
        SECRET_MGR[Secrets Manager\nAll credentials injected via ESO]
    end

    subgraph Runtime["Runtime Safety"]
        PRESIDIO_RT[Presidio\nPII redaction before LLM]
        GUARDRAILS_RT[Bedrock Guardrails\nContent filter at inference]
        OPA_RT[OPA\nTool call policy enforcement]
        NETPOL[NetworkPolicy\nDeny-all between namespaces]
    end
```

**IRSA roles created (one per module)**:

| Role | Service Account | Key Permissions |
|---|---|---|
| `agenticplatform-litellm-role` | `llm-gateway-sa` | `bedrock:InvokeModel*` |
| `agenticplatform-registry-role` | `agent-registry-sa` | DynamoDB tables, S3 registry bucket |
| `agenticplatform-langfuse-role` | `observability-sa` | S3 traces bucket |
| `agenticplatform-memory-role` | `memory-sa` | OpenSearch `aoss:APIAccessAll`, DynamoDB episodic, ElastiCache (VPC) |
| `agenticplatform-langgraph-role` | `orchestration-sa` | DynamoDB checkpoint, S3 artifacts |
| `agenticplatform-mcp-role` | `tool-registry-sa` | `lambda:InvokeFunction` (registered tools) |
| `agenticplatform-hitl-role` | `hitl-sa` | SQS send/receive, SNS publish, DynamoDB HITL state |

---

## Multi-tenancy Model

```mermaid
graph LR
    subgraph Team_A["Team: search-agents"]
        NS_A[Namespace:\nsearch-agents]
        ROLE_A[IAM Role:\nteam-search-agents-role]
        LF_A[Langfuse Org:\nsearch-agents]
        S3_A[S3 prefix:\nagents/search-agents/*]
    end

    subgraph Team_B["Team: data-agents"]
        NS_B[Namespace:\ndata-agents]
        ROLE_B[IAM Role:\nteam-data-agents-role]
        LF_B[Langfuse Org:\ndata-agents]
        S3_B[S3 prefix:\nagents/data-agents/*]
    end

    subgraph Shared["Shared Platform Services"]
        LLM_GW[LiteLLM Gateway\nRate limits per team]
        RDS_SHARED[RDS Aurora\nShared cluster, separate DBs]
        DYNAMO_SHARED[DynamoDB\nRow-level team isolation via tag conditions]
        LANGFUSE_SHARED[Langfuse\nSeparate organizations per team]
    end

    NS_A --> ROLE_A --> S3_A
    NS_B --> ROLE_B --> S3_B
    NS_A & NS_B --> LLM_GW
    NS_A & NS_B --> RDS_SHARED
    NS_A & NS_B --> DYNAMO_SHARED
    Team_A --> LF_A
    Team_B --> LF_B
    LF_A & LF_B --> LANGFUSE_SHARED
```

**Isolation mechanisms**:
1. **Network**: Kubernetes NetworkPolicy — `deny-all` ingress per namespace; allow only from `ingress-nginx` / `aws-load-balancer-controller` namespace
2. **Storage**: IAM condition `dynamodb:LeadingKeys` = team name prefix; S3 IAM prefix conditions
3. **Observability**: Separate Langfuse organization per team — teams cannot see each other's traces
4. **Compute**: ResourceQuota per namespace prevents CPU/memory monopolization
5. **Inference**: LiteLLM per-team rate limits (TPM + RPM) prevent cost monopolization

---

## ALB Routing Architecture

```mermaid
graph LR
    subgraph ALB["ALB: agenticplatform-alb"]
        L_LLM["/llm/*"]
        L_REG["/registry/*"]
        L_LF["/langfuse/*"]
        L_GR["/grafana/*"]
        L_CODE["/code/*"]
        L_JUP["/jupyter/*"]
        L_ORCH["/orchestration/*"]
        L_TEMP["/temporal/*"]
        L_MEM["/memory/*"]
        L_TOOLS["/tools/*"]
        L_EVAL["/eval/*"]
        L_HITL["/hitl/*"]
        L_ROOT["/"]
    end

    L_LLM --> SVC_LITELLM[litellm:4000\nns: llm-gateway]
    L_REG --> SVC_REG[agent-registry:8000\nns: agent-registry]
    L_LF --> SVC_LF[langfuse:3000\nns: monitoring]
    L_GR --> SVC_GR[grafana:3000\nns: monitoring]
    L_CODE --> SVC_CODE[code-server:8443\nns: agent-dev]
    L_JUP --> SVC_JUP[hub:8081\nns: agent-dev]
    L_ORCH --> SVC_LG[langgraph-api:8000\nns: orchestration]
    L_TEMP --> SVC_TEMP[temporal-ui:8080\nns: orchestration]
    L_MEM --> SVC_MEM[memory-service:8000\nns: memory]
    L_TOOLS --> SVC_TOOLS[tool-registry:8000\nns: tool-registry]
    L_EVAL --> SVC_EVAL[eval-service:8000\nns: evaluation]
    L_HITL --> SVC_HITL[hitl-service:8000\nns: hitl]
    L_ROOT --> SVC_DASH[dashboard:3000\nns: dashboard]
```

All services annotated with:
```yaml
alb.ingress.kubernetes.io/group.name: agenticplatform
alb.ingress.kubernetes.io/scheme: internet-facing
alb.ingress.kubernetes.io/target-type: ip
```

---

## Phased Deployment Architecture

### Phase 1: Core Platform

What gets deployed and why each is required before the next:

```mermaid
graph TD
    BOOTSTRAP[Bootstrap\nS3 state + DynamoDB lock] --> INFRA

    subgraph INFRA["Infrastructure (always on)"]
        VPC --> EKS --> NET[Networking\nALB + ExternalDNS]
        EKS --> RDS[RDS Aurora\nShared cluster]
        EKS --> PROFILES[Team Profiles\nIAM + RBAC]
        EKS --> ESO[External Secrets\nOperator]
    end

    NET --> P1

    subgraph P1["Phase 1 Modules"]
        GW[llm-gateway\nLiteLLM + Redis]
        REG[agent-registry\nFastAPI + DynamoDB + S3]
        OBS[observability\nLangfuse + Prometheus + Grafana + OTel]
        DEV[dev-sandbox\nCode-Server + JupyterHub]
    end

    P1 --> P2

    subgraph P2["Phase 2 Modules"]
        ORCH[orchestration\nLangGraph + Temporal]
        MEM[memory\nOpenSearch + Redis + DynamoDB]
        TOOLS[tool-registry\nMCP + Lambda]
        EVAL[evaluation\nEval Service]
    end

    P2 --> P3

    subgraph P3["Phase 3 Modules"]
        HITL[hitl\nSQS + React UI]
        SEC[security\nPresidio + OPA + WAF]
        MT[multitenancy\nNS isolation]
        DASH[dashboard\nPortal]
    end
```

**Deployment time estimates** (same approach as existing platform):

| Phase | Estimated Time | Bottleneck |
|---|---|---|
| Bootstrap | 2 min | DynamoDB create |
| Infrastructure (VPC + EKS + RDS + Net) | 25–35 min | EKS cluster provisioning |
| Phase 1 modules | 10–15 min | Helm releases + RDS DB init |
| Phase 2 modules | 15–20 min | OpenSearch Serverless collection |
| Phase 3 modules | 10–15 min | WAF rule group creation |
| **Total cold start** | **~65–85 min** | |

---

## Technology Stack Summary

| Concern | Technology | Hosting | Notes |
|---|---|---|---|
| Container orchestration | EKS 1.30 | AWS Managed | Identical to existing platform |
| LLM inference | AWS Bedrock | AWS Managed | Claude 3.5, Llama 3.3, Titan |
| LLM routing | LiteLLM | EKS | OpenAI-compatible proxy |
| Agent orchestration | LangGraph | EKS | Graph-based, streaming, HITL support |
| Durable workflows | Temporal | EKS | Replaces Airflow for agentic use cases |
| Vector memory | OpenSearch Serverless | AWS Managed | ANN search for semantic retrieval |
| Working memory | ElastiCache Redis | AWS Managed | Short-term conversation state |
| Episodic memory | DynamoDB | AWS Managed | Structured event log, TTL 90d |
| Metadata store | RDS Aurora PostgreSQL | AWS Managed | Langfuse, Registry, Temporal, Eval |
| Artifact storage | S3 | AWS Managed | Agent defs, traces, snapshots |
| LLMOps tracing | Langfuse (self-hosted) | EKS | Full trace/span/cost visibility |
| Infrastructure metrics | Prometheus + Grafana | EKS | Identical to existing platform |
| Span collection | OpenTelemetry Collector | EKS | DaemonSet, forwards to Langfuse + Prometheus |
| Human-in-the-loop | HITL Service | EKS | SQS + React UI + SNS notifications |
| PII detection | Presidio (Microsoft) | EKS | Pre/post LLM call scanning |
| Policy enforcement | OPA + Gatekeeper | EKS | Tool call and prompt policies |
| Edge security | AWS WAF | AWS Managed | OWASP rules + custom prompt injection |
| Guardrails | AWS Bedrock Guardrails | AWS Managed | PII, topic denial, content filter |
| Secret management | AWS Secrets Manager + ESO | AWS Managed | Same ESO pattern as existing platform |
| DNS | Route 53 + ExternalDNS | AWS Managed | Same pattern as existing platform |
| Identity | GitHub OAuth | External | Same org/team pattern as existing platform |
| IaC | Terraform ≥ 1.5.3 | — | All resources managed |

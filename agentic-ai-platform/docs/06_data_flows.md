# Data Flows

End-to-end scenarios showing how data moves through the platform. Each scenario is a realistic use case.

---

## Scenario 1: Standard Agent Run (No HITL)

**User submits a question to a registered agent. Agent thinks, retrieves memory, calls a tool, and returns an answer.**

```mermaid
sequenceDiagram
    actor User
    participant WAF
    participant ALB
    participant LangGraph as LangGraph Server
    participant Langfuse
    participant MemSvc as Memory Service
    participant LiteLLM as LiteLLM Proxy
    participant Guardrails as Bedrock Guardrails
    participant Bedrock
    participant MCP as MCP Server
    participant Lambda as Tool Lambda
    participant DynamoDB

    User->>WAF: POST /orchestration/v1/runs\n{assistant_id: "search-agent", input: "What is X?"}
    WAF->>ALB: Request passes OWASP + injection check
    ALB->>LangGraph: Forward request

    LangGraph->>Langfuse: trace.start(run_id, agent_id, input)
    LangGraph->>DynamoDB: Create checkpoint (run_id, state={messages: [user_msg]})

    Note over LangGraph: Node: retrieve_memory
    LangGraph->>MemSvc: POST /memory/v1/retrieve {query, tiers: [semantic, working]}
    MemSvc->>DynamoDB: Get working memory (thread_id key)
    MemSvc->>OpenSearch: k-NN search (query embedding)
    MemSvc-->>LangGraph: {context_chunks: [...], working_state: {...}}
    LangGraph->>Langfuse: span.end(retrieve_memory, latency)

    Note over LangGraph: Node: call_llm (iteration 1)
    LangGraph->>LiteLLM: POST /v1/chat/completions\n{model: claude-3-5-sonnet, messages: [system+context+user]}
    LiteLLM->>Guardrails: PII scan on input
    Guardrails-->>LiteLLM: Pass (no PII detected)
    LiteLLM->>Bedrock: InvokeModelWithResponseStream
    Bedrock-->>LiteLLM: Token stream → "I should search for X" + tool_call{web_search, query="X"}
    LiteLLM-->>LangGraph: Streamed response with tool_call
    LangGraph->>Langfuse: span.end(call_llm, tokens=1240, cost=$0.002)

    Note over LangGraph: Node: execute_tool
    LangGraph->>MCP: tools/call {name: web_search, arguments: {query: "X"}}
    MCP->>DynamoDB: Get tool schema (tool_id=web_search)
    MCP->>OPA: check policy(team_id, tool_id)
    OPA-->>MCP: allowed=true
    MCP->>Lambda: Invoke agenticplatform-tool-http
    Lambda-->>MCP: Search results JSON
    MCP-->>LangGraph: ToolResult{content: "Search results..."}
    LangGraph->>Langfuse: span.end(execute_tool, tool=web_search)

    Note over LangGraph: Node: call_llm (iteration 2)
    LangGraph->>LiteLLM: POST /v1/chat/completions\n{messages: [..., tool_result]}
    LiteLLM->>Bedrock: InvokeModel (no tool call this time)
    Bedrock-->>LiteLLM: "Based on the search results, X is..."
    LiteLLM-->>LangGraph: Final answer

    Note over LangGraph: Node: store_memory
    LangGraph->>MemSvc: POST /memory/v1/store {tier: episodic, event: completion}
    MemSvc->>DynamoDB: PutItem (episodic event)
    MemSvc->>OpenSearch: Index new memory chunk (upsert)

    LangGraph->>DynamoDB: Update checkpoint (status=completed)
    LangGraph->>Langfuse: trace.end(run_id, output, total_cost)
    LangGraph-->>User: SSE stream: final answer + run_id
```

---

## Scenario 2: Agent Run with HITL (Human Approval Required)

**Agent wants to send an email. The `ses_send` tool has `requires_approval=true`. Execution pauses until a human approves.**

```mermaid
sequenceDiagram
    actor User
    actor Reviewer
    participant LangGraph
    participant MCP
    participant OPA
    participant HITL as HITL Service
    participant DynamoDB
    participant SQS
    participant SNS
    participant Temporal

    User->>LangGraph: POST /orchestration/v1/runs\n{assistant_id: "outreach-agent"}
    Note over LangGraph: Agent reasons, decides to send email

    LangGraph->>MCP: tools/call {name: ses_send, arguments: {to, subject, body}}
    MCP->>DynamoDB: Get tool schema → requires_approval=true
    MCP->>OPA: check policy → allowed
    MCP->>HITL: POST /hitl/v1/tasks {run_id, proposed_action, team_id}
    HITL->>DynamoDB: PutItem (hitl-state, status=pending)
    HITL->>SQS: SendMessage (approval request)
    HITL->>SNS: Publish notification
    SNS->>Lambda: Slack notifier Lambda
    Lambda->>Slack: POST webhook: "Agent wants to send email. Review: /hitl/tasks/abc"

    Note over LangGraph: interrupt() node reached\nLangGraph execution paused\nTemporal durable timer starts (48h timeout)

    LangGraph-->>User: HTTP 202 Accepted + run_id\n{status: "pending_approval"}

    Note over Reviewer: Receives Slack notification
    Reviewer->>HITL: GET /hitl/v1/tasks/abc (React UI)
    HITL->>DynamoDB: Get task → status=pending, proposed_action
    HITL-->>Reviewer: Review UI: email draft, approve/reject/modify buttons

    Reviewer->>HITL: POST /hitl/v1/tasks/abc/decide {decision: "approved", comment: "LGTM"}
    HITL->>DynamoDB: Update task → status=approved, reviewer_id, resolved_at
    HITL->>LangGraph: POST /orchestration/v1/threads/{thread_id}/runs/{run_id}/approve

    Note over LangGraph: Execution resumes from checkpoint
    LangGraph->>MCP: tools/call ses_send (now approved, skip HITL check)
    MCP->>Lambda: Invoke ses_send Lambda
    Lambda-->>MCP: {message_id: "..."}
    MCP-->>LangGraph: ToolResult{content: "Email sent"}

    LangGraph-->>User: SSE: final answer "Email sent successfully"
```

---

## Scenario 3: Developer Registers a New Agent

**Developer writes an agent in Code-Server, tests it in JupyterHub, then registers it in the Agent Registry.**

```mermaid
sequenceDiagram
    actor Dev
    participant CodeServer as Code-Server\n(VS Code)
    participant JupyterHub
    participant LangGraph as LangGraph Server\n(local/dev)
    participant LiteLLM as LiteLLM Proxy
    participant Langfuse
    participant Registry as Agent Registry API
    participant DynamoDB
    participant S3
    participant ECR

    Dev->>CodeServer: Opens /code/ in browser\nGitHub OAuth login
    CodeServer->>Dev: VS Code environment\nwith LITELLM_BASE_URL pre-set

    Note over Dev,CodeServer: Writes agent code in Python
    Dev->>LiteLLM: Test: POST /llm/v1/chat/completions\n(from Code-Server terminal)
    LiteLLM-->>Dev: Streaming response from Claude

    Dev->>JupyterHub: Opens /jupyter/ \nGitHub OAuth login
    Note over Dev,JupyterHub: Runs agent in notebook
    Dev->>LangGraph: POST /orchestration/v1/runs\n(test run with dev agent)
    LangGraph-->>Dev: Run result + trace link

    Dev->>Langfuse: Reviews trace at /langfuse/\nChecks token usage, tool calls, latency

    Note over Dev: Agent looks good — register it
    Dev->>Registry: POST /registry/v1/agents\n{agent_id: "search-agent-v2",\n version: "1.0.0",\n stage: "dev",\n graph_config: {...},\n tool_ids: ["web_search"]}
    Registry->>DynamoDB: PutItem (agent-definitions)
    Registry->>S3: PutObject (serialized graph JSON)
    Registry-->>Dev: {agent_id, version, registry_url}

    Note over Dev: Test in staging
    Dev->>Registry: PATCH /registry/v1/agents/search-agent-v2/1.0.0\n{stage: "staging"}
    Registry->>DynamoDB: UpdateItem (stage=staging)

    Note over Dev: Run evaluation suite
    Dev->>EvalSvc: POST /eval/v1/runs\n{agent_id: "search-agent-v2",\n version: "1.0.0",\n dataset_id: "search-eval-set"}
    EvalSvc->>LangGraph: Run agent against eval dataset
    EvalSvc->>Langfuse: Create scores for each run
    EvalSvc-->>Dev: {eval_run_id, mean_score: 0.87, pass_rate: 0.94}

    Note over Dev: Score above threshold — promote to production
    Dev->>Registry: PATCH /registry/v1/agents/search-agent-v2/1.0.0\n{stage: "production"}
    Registry->>DynamoDB: UpdateItem (stage=production)
```

---

## Scenario 4: Memory Retrieval and Storage Flow

**Detailed flow showing how the four memory tiers interact during a single agent run.**

```mermaid
graph TB
    subgraph AgentRun["Agent Run: run-abc123 / thread-xyz789"]
        MSG[User Message:\n'Continue our analysis\nfrom last week']
    end

    subgraph MemoryRetrieve["Memory Retrieve (beginning of run)"]
        R1[1. Working Memory\nRedis GET thread:xyz789:state\n→ last 5 messages + tool results\nLatency: ~1ms]
        R2[2. Episodic Memory\nDynamoDB Query: agent_id=search-agent\nSK between timestamps\n→ last week's run events\nLatency: ~5ms]
        R3[3. Semantic Memory\nOpenSearch kNN search\nEmbedding: 'analysis last week'\ntop-k=5 relevant chunks\nLatency: ~45ms]
        R4[Memory Service\nMerges + deduplicates results\nReturns 2000 token context window]
    end

    subgraph LLMCall["LLM Call with Context"]
        PROMPT[System: You are a research agent\nContext: {retrieved_memory}\nHistory: {working_memory}\nUser: {new_message}]
    end

    subgraph MemoryStore["Memory Store (end of run)"]
        S1[1. Update Working Memory\nRedis SET thread:xyz789:state\nNew messages appended\nTTL refreshed to 24h]
        S2[2. Write Episodic Event\nDynamoDB PutItem\nevent_type: completion\nsummary: 'User asked about X, agent responded Y'\nTTL: 90 days]
        S3[3. Upsert Semantic Memory\nGenerate embedding for run summary\nOpenSearch index: upsert\nKey insight: 'Analysis conclusion: X leads to Y']
    end

    MSG --> R1 & R2 & R3 --> R4 --> PROMPT
    PROMPT --> S1 & S2 & S3
```

---

## Scenario 5: Evaluation Run and A/B Test

**Platform operator runs an evaluation comparing prompt_v1 vs prompt_v2 on the same test dataset.**

```mermaid
sequenceDiagram
    actor Operator
    participant EvalSvc as Evaluation Service
    participant Registry as Agent Registry
    participant LangGraph
    participant LiteLLM
    participant Bedrock
    participant Langfuse
    participant Grafana

    Operator->>EvalSvc: POST /eval/v1/ab-tests\n{control: {agent_id, prompt: v1},\n treatment: {agent_id, prompt: v2},\n dataset_id: "search-golden-set",\n traffic_split: 50,\n sample_size: 100}

    EvalSvc->>Registry: GET /registry/v1/prompts/search-system/v1
    EvalSvc->>Registry: GET /registry/v1/prompts/search-system/v2

    loop 100 test cases
        EvalSvc->>EvalSvc: Assign variant (hash(test_case_id) % 2)

        alt Variant: control (prompt_v1)
            EvalSvc->>LangGraph: POST /runs\n{prompt_template: v1, input: test_case}
        else Variant: treatment (prompt_v2)
            EvalSvc->>LangGraph: POST /runs\n{prompt_template: v2, input: test_case}
        end

        LangGraph->>LiteLLM: Chat completion
        LiteLLM->>Bedrock: InvokeModel
        Bedrock-->>LangGraph: Response
        LangGraph->>Langfuse: Trace (tagged: ab_test=true, variant=control|treatment)
        LangGraph-->>EvalSvc: Run result

        EvalSvc->>LiteLLM: LLM-as-judge: score response (0-1)
        LiteLLM->>Bedrock: Judge prompt
        Bedrock-->>LiteLLM: Score
        EvalSvc->>Langfuse: POST /api/public/scores\n{run_id, name: "llm_judge_score", value: 0.87}
    end

    EvalSvc->>Langfuse: GET /api/public/scores?tag=ab_test_id=xyz
    Note over EvalSvc: Calculate: mean score per variant\nStatistical significance (t-test)

    EvalSvc-->>Operator: {
        control_mean: 0.78,
        treatment_mean: 0.87,
        p_value: 0.02,
        recommendation: "treatment (prompt_v2) is significantly better"
    }

    Operator->>Grafana: Views ab-test-results dashboard
    Grafana->>Langfuse: Query scores by tag
    Grafana-->>Operator: Score distributions, confidence intervals

    Operator->>Registry: PATCH /registry/v1/prompts/search-system/v2\n{stage: production}
```

---

## Scenario 6: Platform Startup and Bootstrap

**First-time deployment sequence from zero to Phase 1 running.**

```mermaid
graph TD
    subgraph Bootstrap["Step 1: Bootstrap (2 min)"]
        B1[cd deployment/bootstrap\nterraform init && terraform apply]
        B2[Creates:\n- S3 bucket: agenticplatform-terraform-state\n- DynamoDB: agenticplatform-terraform-locks]
    end

    subgraph Infra["Step 2: Infrastructure (25–35 min)"]
        I1[terraform init -backend-config=...\nterraform apply -target=module.vpc]
        I2[VPC: 10.0.0.0/16\n3 AZs · NAT Gateway · Public+Private subnets]
        I3[terraform apply -target=module.eks]
        I4[EKS 1.30 cluster\nng0 + ng1 + ng_agent_worker node groups\nOIDC provider for IRSA]
        I5[terraform apply -target=module.rds]
        I6[RDS Aurora PostgreSQL Serverless v2\nDatabases: langfuse, agent_registry, temporal, evaluation]
        I7[terraform apply -target=module.networking]
        I8[ALB Controller + ExternalDNS installed\nRoute53 zone synced]
        I9[terraform apply -target=module.external_secrets]
        I10[External Secrets Operator installed]
    end

    subgraph Phase1["Step 3: Phase 1 Modules (10–15 min)"]
        P1[terraform apply -var-file=phase1.tfvars]
        P2[llm-gateway:\n- ElastiCache Redis created\n- LiteLLM Helm release deployed\n- IRSA role: bedrock:InvokeModel*\n- ALB rule: /llm/* → litellm:4000]
        P3[agent-registry:\n- DynamoDB tables created\n- S3 bucket: agenticplatform-agent-registry\n- FastAPI Helm release deployed\n- ALB rule: /registry/*]
        P4[observability:\n- S3 bucket: agenticplatform-langfuse-traces\n- Langfuse Helm release deployed\n- Prometheus + Grafana deployed\n- OTel Collector DaemonSet\n- ALB rules: /langfuse/*, /grafana/*]
        P5[dev-sandbox:\n- Code-Server Helm release\n- JupyterHub Helm release\n- GitHub OAuth configured\n- ALB rules: /code/*, /jupyter/*]
    end

    subgraph Verify["Step 4: Verify Phase 1"]
        V1[curl https://agents.example.com/llm/v1/models\n→ 200: model list]
        V2[curl https://agents.example.com/registry/v1/agents\n→ 200: empty list]
        V3[Open https://agents.example.com/langfuse/\n→ Langfuse login via GitHub OAuth]
        V4[Open https://agents.example.com/code/\n→ VS Code interface]
    end

    Bootstrap --> Infra --> Phase1 --> Verify
    B1 --> B2
    I1 --> I2 --> I3 --> I4 --> I5 --> I6 --> I7 --> I8 --> I9 --> I10
    P1 --> P2 & P3 & P4 & P5
```

---

## Scenario 7: Cost Monitoring and Budget Alerting

**How the platform tracks and alerts on LLM spend per team.**

```mermaid
graph LR
    subgraph Generation["Cost Data Generation"]
        LiteLLM[LiteLLM Proxy\nPer-request: tokens + cost\ncalculated from pricing table]
        CB[LiteLLM Callbacks\nPUSH to Langfuse trace\nPUSH to Prometheus counter]
    end

    subgraph Storage["Cost Data Storage"]
        PROM[Prometheus\nlitellm_cost_total label: model, team]
        LF_DB[Langfuse\nCost field on every LLM span]
        CW[CloudWatch\nAWS Bedrock usage metrics\n(ground truth for billing)]
    end

    subgraph Visualization["Visualization"]
        GRAFANA[Grafana: token-cost.json\nDaily spend by team\nBudget gauge: actual vs limit\nTop 5 models by cost]
        LF_DASH[Langfuse: Cost dashboard\nPer-trace cost\nCost per agent type]
    end

    subgraph Alerting["Alerting"]
        PA[Prometheus AlertManager\nAlert: daily_team_cost > budget_limit\nSends SNS → email/Slack]
        LF_ALERT[Langfuse Score Alert\nAlert: cost per run > $1.00\n(LLM running away?)]
    end

    LiteLLM --> CB --> PROM & LF_DB
    CW --> PROM
    PROM --> GRAFANA & PA
    LF_DB --> LF_DASH & LF_ALERT
```

**Budget enforcement hierarchy**:
1. **Hard limit** (LiteLLM per-team TPM/RPM): returns `429` when exceeded — blocks runaway agents immediately
2. **Soft alert** (Prometheus AlertManager): notifies team lead when 80% of daily budget consumed
3. **Audit** (AWS Cost Explorer + resource tags): monthly per-team actual Bedrock spend for finance reporting

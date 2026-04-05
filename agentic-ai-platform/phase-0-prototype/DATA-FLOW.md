# Phase 0: Prototype — Data Flow Diagrams

> **Objective:** Trace every data path through the prototype system — from user input to final response.

---

## 1. End-to-End Request Flow

```mermaid
sequenceDiagram
    actor User
    participant UI as Chat UI
    participant Ingress as NGINX Ingress
    participant API as Agent API (FastAPI)
    participant ALoop as Agent Loop
    participant LLM as LLM Provider
    participant Tools as Tool Router
    participant Search as Web Search API

    User->>UI: Types "What's the weather in NYC?"
    UI->>Ingress: POST /api/v1/agent/run
    Ingress->>API: Route to agent service
    API->>API: Validate request, create session
    API->>ALoop: Start agent reasoning

    rect rgb(240, 248, 255)
        Note over ALoop,LLM: Iteration 1 — Agent decides to use a tool
        ALoop->>LLM: Send messages + tool schemas
        LLM-->>ALoop: tool_call: web_search("weather NYC")
        ALoop->>Tools: Execute web_search
        Tools->>Search: HTTP GET search API
        Search-->>Tools: Search results JSON
        Tools-->>ALoop: "NYC: 72°F, partly cloudy"
        ALoop->>ALoop: Append tool result to messages
    end

    rect rgb(240, 255, 240)
        Note over ALoop,LLM: Iteration 2 — Agent provides final answer
        ALoop->>LLM: Send updated messages
        LLM-->>ALoop: final_answer: "The weather in NYC is 72°F..."
    end

    ALoop-->>API: Return answer + steps
    API-->>Ingress: HTTP 200 JSON response
    Ingress-->>UI: Response
    UI-->>User: Display answer with reasoning steps
```

---

## 2. Tool Execution Flow

```mermaid
flowchart TD
    A[Agent Loop receives<br/>tool_call from LLM] --> B{Which tool?}

    B -->|web_search| C[Web Search Tool]
    B -->|calculator| D[Calculator Tool]
    B -->|code_executor| E[Code Executor Tool]
    B -->|unknown| F[Return error:<br/>'Tool not found']

    C --> C1[Validate input schema]
    C1 --> C2[Call Search API]
    C2 --> C3[Parse top 3 results]
    C3 --> G[Return result string]

    D --> D1[Validate input schema]
    D1 --> D2[Sanitize expression]
    D2 --> D3[Evaluate safely]
    D3 --> G

    E --> E1[Validate input schema]
    E1 --> E2[Spawn subprocess<br/>with timeout]
    E2 --> E3[Capture stdout/stderr]
    E3 --> E4{Exit code?}
    E4 -->|0| G
    E4 -->|non-zero| H[Return error output]

    F --> I[LLM receives error,<br/>tries different approach]
    G --> J[Append to message history]
    H --> J
    J --> K[Next LLM iteration]
```

---

## 3. Session Data Lifecycle

```mermaid
flowchart LR
    subgraph "Request arrives"
        A[POST /agent/run] --> B{session_id<br/>provided?}
        B -->|yes| C[Load existing session]
        B -->|no| D[Generate new session_id]
    end

    subgraph "During execution"
        C --> E[Session messages array]
        D --> E
        E --> F[Append user message]
        F --> G[Agent loop runs]
        G --> H[Append assistant messages]
        H --> I[Append tool results]
        I --> G
    end

    subgraph "After response"
        G --> J[Store updated session]
        J --> K[In-memory dict]
    end

    subgraph "Cleanup"
        L[TTL timer<br/>every 5 min] --> M{Session age > 1hr?}
        M -->|yes| N[Delete session]
        M -->|no| O[Keep]
    end
```

---

## 4. LLM Communication Flow

```mermaid
sequenceDiagram
    participant ALoop as Agent Loop
    participant Client as LLM Client
    participant LiteLLM as LiteLLM
    participant Provider as LLM Provider API

    ALoop->>Client: chat(messages, tools, model)
    Client->>Client: Add default parameters<br/>(temperature, max_tokens)

    Client->>LiteLLM: completion(model, messages, tools)
    LiteLLM->>LiteLLM: Route to correct provider SDK

    LiteLLM->>Provider: HTTP POST /chat/completions
    Provider-->>LiteLLM: Response (200 OK)
    LiteLLM-->>Client: Parsed response object

    Client->>Client: Extract content or tool_calls
    Client-->>ALoop: Structured response

    Note over Client,Provider: On timeout → retry once
    Note over Client,Provider: On 429 → propagate rate limit error
    Note over Client,Provider: On 5xx → try fallback model
```

---

## 5. Data at Rest vs. Data in Flight

```mermaid
graph TB
    subgraph "Data in Flight (HTTP/TLS)"
        D1[User prompt] -->|HTTPS| D2[Agent API]
        D2 -->|HTTPS| D3[LLM Provider]
        D2 -->|HTTPS| D4[Search API]
    end

    subgraph "Data at Rest (In-Memory)"
        D5[Session store<br/>Python dict in pod memory]
        D6[Conversation history<br/>Lost on pod restart]
    end

    subgraph "Data at Rest (Kubernetes)"
        D7[API Keys<br/>K8s Secrets / ESO]
        D8[Configuration<br/>ConfigMap]
    end

    D2 --> D5
    D7 --> D2
    D8 --> D2
```

| Data | Location | Encrypted? | Persistent? |
|------|----------|-----------|-------------|
| User prompts | In-memory | No (in pod) | No |
| LLM responses | In-memory | No (in pod) | No |
| Tool results | In-memory | No (in pod) | No |
| API keys | K8s Secrets | At rest (etcd encryption) | Yes |
| Config | ConfigMap | No | Yes |
| Network traffic | Ingress → Service | TLS terminated at ingress | n/a |

---

## 6. Error Propagation Flow

```mermaid
flowchart TD
    A[User Request] --> B[Agent API]
    B --> C[Agent Loop]
    C --> D[LLM Call]
    C --> E[Tool Execution]

    D -->|Timeout| D1[Retry once]
    D1 -->|Still fails| D2[Return 504<br/>Gateway Timeout]

    D -->|Rate limit 429| D3[Return 429<br/>to user with retry-after]

    D -->|Auth error 401| D4[Return 500<br/>Log critical alert]

    E -->|Tool error| E1[Return error as tool result]
    E1 -->|LLM sees error| E2[LLM tries different tool<br/>or answers without tool]

    E -->|Tool timeout| E3[Kill process]
    E3 --> E1

    C -->|Max iterations| C1[Return partial answer<br/>with steps completed so far]
```

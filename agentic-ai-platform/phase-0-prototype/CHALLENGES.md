# Phase 0: Prototype — Challenges & How We Solved Them

> **The story of what went wrong, what we debated, and what we learned building the first working agent on EKS.**

---

## Challenge 1: "Which agent framework do we even use?"

### The Problem

The team sat down to pick a framework. LangChain, CrewAI, AutoGen, LlamaIndex, Haystack — everyone had a favorite. Opinions were strong. The backend engineer wanted LangChain because of ecosystem size. The platform engineer wanted nothing because "frameworks are tech debt." The product lead just wanted something working by Friday.

### The Debate

| Option | For | Against |
|--------|-----|---------|
| LangChain | Largest ecosystem, most examples | Massive abstraction layer, hard to debug, changes APIs constantly |
| CrewAI | Multi-agent patterns built-in | Overkill for a prototype, opinionated |
| Custom (no framework) | Full control, understand every line | More boilerplate, no community shortcuts |

### How We Solved It

We chose **no framework for the prototype**. Here's why:

1. The core agent loop is ~80 lines of Python. A framework adds hundreds of dependencies for that.
2. Debugging an agent that doesn't work means understanding the loop. Abstractions hide the loop.
3. We can always adopt a framework later. But we can't un-adopt one easily.
4. The team learns more by building it raw. That knowledge pays off in every future phase.

**Rule:** Use LiteLLM as a thin provider abstraction (it stays out of the way), but own the reasoning loop ourselves.

---

## Challenge 2: "LLM responses are unpredictable — tool calling breaks"

### The Problem

During early testing, the agent would:
- Call tools that don't exist (hallucinated tool names)
- Pass malformed JSON as tool arguments
- Get stuck in loops calling the same tool repeatedly
- Ignore tool results and hallucinate answers anyway

### What We Tried (and Failed)

1. **More detailed system prompts** — Helped somewhat, but the LLM still hallucinated tool names ~5% of the time
2. **Strict output parsing** — Broke on every edge case. Regex-based parsing was a nightmare.

### How We Solved It

We switched to **native function/tool calling** provided by the LLM APIs (OpenAI's `tools` parameter, Anthropic's `tool_use`). This means:

- The LLM outputs structured tool calls (not free-text that we parse)
- Tool schemas are sent as part of the API call
- The LLM can only call tools we define
- Arguments are validated against the JSON schema

Additionally:
- **Max iteration guard** (5 loops) prevents infinite loops
- **Tool result size limit** (2000 chars) prevents context overflow
- **Duplicate detection** — if the agent calls the same tool with the same args twice in a row, we inject "You already tried this. Try a different approach." into the context

---

## Challenge 3: "Code execution tool is a security nightmare"

### The Problem

The team wanted a code executor tool — the agent writes Python, executes it, gets the output. But running arbitrary code from an LLM on production infrastructure is terrifying. The platform engineer vetoed it immediately.

### The Debate

**Backend Engineer:** "It's the most powerful tool. Without it, the agent can't do data analysis, can't transform data, can't solve complex problems."

**Platform Engineer:** "It's a remote code execution vulnerability disguised as a feature. An LLM could `import os; os.system('rm -rf /')` or exfiltrate secrets from environment variables."

**Product Lead:** "We need it for the demo. Find a middle ground."

### How We Solved It

Layered sandboxing:

1. **Subprocess isolation** — Code runs in a subprocess, not in the agent process
2. **Timeout** — Hard kill after 10 seconds
3. **No network** — Subprocess has no network access (iptables rules)
4. **No filesystem write** — Read-only filesystem mount
5. **Environment scrubbed** — No API keys, no secrets in the subprocess environment
6. **Import whitelist** — Only `math`, `json`, `datetime`, `statistics`, `collections` available
7. **Resource limits** — cgroup limits on memory (256MB) and CPU

For Phase 0, this is sufficient. Phase 3 will introduce gVisor or Firecracker for proper sandboxing.

---

## Challenge 4: "Latency is terrible — agents take 15-30 seconds to respond"

### The Problem

An agent that calls 2-3 tools requires 2-3 LLM round-trips. Each LLM call takes 3-5 seconds. Plus tool execution time. Total: 10-30 seconds for a single user query. The product lead said "nobody will wait 30 seconds."

### What We Measured

```
Typical 2-tool query breakdown:
  LLM call #1 (decide tool):    3.2s
  Tool execution (web search):   1.1s
  LLM call #2 (decide tool):    2.8s
  Tool execution (calculator):   0.01s
  LLM call #3 (final answer):   2.5s
  ──────────────────────────────
  Total:                         9.6s
```

### How We Solved It

1. **Streaming responses** — Stream the final LLM response back to the user. They see tokens appearing in real-time instead of waiting for completion.
2. **Step reporting** — Send intermediate steps as SSE (Server-Sent Events). The UI shows "Searching the web..." → "Calculating..." → "Composing answer..." — the user sees progress.
3. **Model selection** — Use faster models (GPT-4o-mini) for simple tool routing, full models (GPT-4o) only for the final answer.
4. **Parallel tool calls** — If the LLM requests multiple tools in one turn, execute them in parallel.

Result: Perceived latency dropped from "waiting 15 seconds for a wall of text" to "watching the agent think in real-time." Actual wall-clock time didn't change much, but the UX was dramatically better.

---

## Challenge 5: "We lost all conversation history on every pod restart"

### The Problem

Session state lived in a Python dictionary in memory. Every time the pod restarted (deployment update, scaling event, OOM kill), all active conversations were lost.

### The Temptation

"Let's just add Redis now. It's one line of code."

### How We Solved It (For Now)

We **accepted the limitation** for Phase 0. Here's why:

1. Adding Redis means another service to deploy, configure, monitor, and debug
2. The prototype is for demos — conversations last minutes, not days
3. Scope creep kills prototypes. Redis is planned for Phase 1.

What we did instead:
- Added a TTL cleanup (sessions expire after 1 hour)
- Added a startup log warning: "Session store is in-memory. Data will be lost on restart."
- Documented it as a known limitation
- Created a ticket for Phase 1 persistent memory

---

## Challenge 6: "Docker image is 2.3 GB and takes 8 minutes to build"

### The Problem

The initial Dockerfile installed every possible dependency. PyTorch (for no reason), heavy NLP libraries, development tools. The image was massive.

### How We Solved It

1. **Multi-stage build** — Build stage installs dependencies, final stage copies only what's needed
2. **Minimal base** — `python:3.11-slim` instead of full Python image
3. **Requirements audit** — Removed unused packages. The agent needs: `fastapi`, `uvicorn`, `litellm`, `httpx`, `pydantic`. That's it.
4. **Layer optimization** — Requirements installed first (cached), code copied last (changes often)

Result: Image went from 2.3 GB → 280 MB. Build time from 8 min → 45 seconds.

---

## Challenge 7: "How do we demo this to stakeholders who don't understand agents?"

### The Problem

Stakeholders see a chat interface and think "it's ChatGPT." They don't understand what's different about an agent with tool access running on our infrastructure.

### How We Solved It

The demo was designed to make the **agent reasoning visible**:

1. **Show the steps** — The UI displays each reasoning step: "Thinking..." → "Using tool: web_search" → "Processing results..." → "Final answer"
2. **Show the difference** — First, ask a time-sensitive question without tools (LLM hallucinates). Then ask the same question with tools (agent gets live data).
3. **Show the infrastructure** — Split screen: chat UI on the left, Kubernetes dashboard on the right showing the pod running.
4. **Use business-relevant examples** — Not "what's the weather" but "find the last 3 SEC filings for Company X and summarize the risk factors."

---

## Team Retrospective — Phase 0

### What Went Well
- Deploying on existing EKS was seamless — Helm chart, ArgoCD sync, done
- Not using a heavy framework meant everyone understood the code
- Stakeholder demo created buy-in for Phase 1

### What Didn't Go Well
- Underestimated LLM unpredictability — spent significant time on edge cases
- Code executor security debate delayed us
- Initial Docker image was embarrassingly large

### What We'd Do Differently
- Start with native tool calling from day one (don't try text parsing first)
- Set up Docker image size checks in CI from the start
- Write 3-4 integration tests for the agent loop before building the UI

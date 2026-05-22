# Agent Learning Roadmap

The next five features to add to `jira-agent`. The selection is biased toward
patterns common in production agents and foundational to learning how agents
work — not toward making this a useful Jira admin tool.

The order below is pedagogical: each step gives you something the next one
builds on. You can reorder freely, but if in doubt, work top to bottom.

---

## 1. Agent observability

**What.** Structured logging plus a per-turn trace: every LLM call and tool
call with token counts (prompt + completion), latency, and estimated cost. A
trace ID per turn ties LLM calls and tool calls together. Output goes to a
JSONL file (e.g. `~/.jira_agent/traces.jsonl`) with a compact one-line summary
echoed to stderr.

**Why it teaches a production pattern.** Production agents are *operated*, not
just written. You need to see what the model is doing on every turn — what it
asked, how much it cost, why it called a tool, how long it took. Without that,
every later change is guesswork. Observability comes first because it makes
all subsequent features measurable.

**Touches.** `llm.py` (instrument `chat`), `agent.py` (turn-level trace),
`cli.py` (summary line), new `observability.py` with a `Tracer` / `Logger`.

**Rough scope.** ~50–80 lines plus a JSONL writer. No new dependencies.

---

## 2. Evaluation harness + tests

**What.** Two layers of automated checks:

- **Unit tests** for `dispatch()` and `JiraClient` methods (using `respx` or
  hand-rolled HTTP mocks).
- **Eval scenarios** that script a sequence of canned `ChatCompletionMessage`
  objects and assert the agent calls the right tool with the right arguments
  — e.g., "user asks to create a bug" → expect `create_issue(project_key=...,
  issue_type='Bug', ...)`.

**Why it teaches a production pattern.** Tests are the engineering foundation;
*evals* are the agent-specific one. With them, every later refactor is safe,
and you can measure when the agent gets worse — not just whether it crashes.

**Touches.** New `tests/` directory; `pytest` and `respx` added as dev
dependencies. The mocking patterns here get reused by every later feature.

**Rough scope.** ~150–250 lines including fixtures.

---

## 3. Human-in-the-loop approval

**What.** Classify every tool as read or write. Before any write tool
(`create_issue`, `transition_issue`, `add_comment`, `assign_issue`) runs, the
CLI shows a preview of the action and asks `[y/N]`. On `n`, the dispatch
returns a structured "user declined" error and the model can revise.
Optionally, a `--yolo` flag bypasses approval for trusted sessions.

**Why it teaches a production pattern.** The canonical agent safety pattern:
*tool risk tiers* and *approval interrupts*. Also closes what the README calls
the project's biggest product gap. You will see firsthand how the model
behaves when its actions get rejected — a much deeper lesson than reading
about it.

**Touches.** `tools.py` (tag tool schemas with a risk tier), `agent.py`
(approval hook around `dispatch`), `cli.py` (prompt UI and preview format).

**Rough scope.** ~60–90 lines. The hardest part is the preview format, not
the gate itself.

---

## 4. Explicit session memory

**What.** A typed `SessionState` object on the Agent holding things like
`last_created_issue`, `last_search_results` (top-N issue keys + summaries),
`last_assigned_issue`, `last_transition`. Tools mutate it as a side effect on
success. The state is surfaced to the model either as a compact
`<session_state>` block injected before each LLM call, or via a dedicated
`get_recent_context` read tool — try both approaches and compare them.

**Why it teaches a production pattern.** The distinction between
*conversational context* (the message history) and *agent state* (typed,
queryable, lives outside the transcript) is one of the most important
patterns in production agents. It is the seed of scratchpads, working memory,
and planner state. Concretely, it lets the model resolve "comment on that
bug" reliably and lets you shrink the message history you have to replay.

**Touches.** New `session.py` (the state class and update helpers),
`tools.py` (handlers write to it on success), `agent.py` (inject into the
prompt or expose as a tool).

**Rough scope.** ~80–120 lines.

---

## 5. Reliability & context management

**What.** Two related operational concerns bundled together:

- **Retries with exponential backoff** on transient LLM and Jira failures
  (HTTP 429, 5xx). Configurable max attempts and base delay.
- **Token counting + history compaction.** Track tokens per turn (using
  `tiktoken` or the usage numbers returned by the API), and when the history
  approaches a threshold, summarise older turns into a single compact recap
  message that replaces them.

**Why it teaches a production pattern.** Retries are a basic reliability
concern; compaction is the central scaling problem of conversational agents.
Both teach the difference between "works in a demo" and "works for an
hour-long session."

**Touches.** `llm.py` (retry wrapper, token tracking), `agent.py` (compaction
check after each turn), `config.py` (thresholds and retry parameters).

**Rough scope.** ~80–120 lines. Retries first (smaller); compaction second.

---

## Where to go after these

Patterns that build naturally on 1–5 and would be reasonable next steps:

- **Streaming responses** — incremental token rendering and tool-call delta
  assembly.
- **MCP integration** — replace `tools.py` / `jira_client.py` with an MCP
  server and let the agent discover tools at runtime.
- **Multi-step planning** — a separate planner LLM call that produces a tool
  sequence before execution, with the executor LLM running it.

None are necessary first; all become much easier once 1–5 are in place.

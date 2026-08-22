# Jira Agent

A learning project that connects an OpenAI-compatible LLM to Atlassian Cloud Jira through a local Model Context Protocol (MCP) server. The terminal agent discovers Jira tools at runtime, asks before writes, and sends approved calls to a separate stdio server process.

It is intentionally small and explicit so the full path from a sentence to a Jira REST request remains easy to inspect.

```text
> Create a P1 bug in SCRUM called "Login page hangs on submit"

Proposed Jira write: Create Jira issue (create_issue)
{
  "project_key": "SCRUM",
  "summary": "Login page hangs on submit",
  "issue_type": "Bug",
  "priority": "Highest"
}
Approve? [y/N] y
  -> create_issue({...})
  <- ok: {"id": "10005", "key": "SCRUM-6", ...}

Created P1 bug SCRUM-6: "Login page hangs on submit".
```

## Architecture

```text
+-------------+      +----------------+      +------------------+
| CLI REPL    | ---> | Agent          | ---> | LLM provider     |
| cli.py      |      | agent.py       |      | OpenAI-compatible|
+-------------+      +-------+--------+      +------------------+
                             |
                       MCP over stdio
                             |
                     +-------v--------+      +------------------+
                     | Jira MCP server| ---> | Atlassian Cloud  |
                     | mcp_server.py  | REST | Jira API v3      |
                     +----------------+      +------------------+
```

At startup, the agent launches `jira-agent-mcp`, requests `tools/list`, and converts the discovered MCP schemas into the function format expected by the LLM. There is no static tool registry in the agent.

For each chat turn:

1. The agent sends history and discovered tool schemas to the LLM.
2. Read-only tools run immediately. Tools not explicitly annotated read-only require confirmation.
3. Approved calls cross the stdio MCP boundary and execute through `JiraClient`.
4. Structured MCP results are wrapped in `{"ok": true, "result": ...}`; failures use `{"ok": false, "error": ...}`.
5. Every tool call receives a matching tool response, and the loop stops after at most six iterations.

## Project structure

```text
src/jira_agent/
|-- agent.py          # async LLM tool loop and approval gate
|-- cli.py            # terminal REPL and write confirmation UI
|-- config.py         # separate LLM and Jira configuration
|-- jira_client.py    # thin synchronous Jira REST API v3 client
|-- llm.py            # AsyncOpenAI-compatible model client
|-- mcp_client.py     # stdio lifecycle, discovery, and result adapter
`-- mcp_server.py     # typed MCP tools and Jira-client lifespan

scripts/
|-- ping_llm.py
`-- ping_jira.py

tests/                # REST unit tests, MCP contracts, and agent evals
```

The package installs two commands:

- `jira-agent`: the interactive host and REPL.
- `jira-agent-mcp`: the standalone stdio MCP server.

## MCP tools

The server exposes five typed tools. MCP derives their JSON Schemas from Python type annotations and publishes behavioral annotations for host approval decisions.

| Tool | Jira operation | MCP behavior |
|---|---|---|
| `search_issues` | POST `/rest/api/3/search/jql` | Read-only, idempotent; 1–50 results |
| `create_issue` | POST `/rest/api/3/issue` | Write, non-idempotent |
| `transition_issue` | GET/POST issue transitions | Write, potentially destructive |
| `add_comment` | POST issue comment | Write, non-idempotent |
| `assign_issue` | PUT issue assignee | Write, idempotent |

Descriptions and comments are converted to Atlassian Document Format just before the REST call. Search results wrap user-controlled summaries and display names in `<untrusted>...</untrusted>` delimiters before returning them to the model.

MCP annotations are hints, not enforcement. The bundled `jira-agent` host enforces confirmation; another MCP host is responsible for its own approval policy.

## Setup

Prerequisites:

- Python 3.12, managed by `uv`
- An OpenAI-compatible LLM endpoint and API key
- An Atlassian Cloud site, account, and API token

Install dependencies and create configuration:

```bash
uv sync --group dev
cp .env.example .env
```

Fill in:

```dotenv
LLM_API_KEY=...
LLM_MODEL=...
# LLM_BASE_URL=https://openrouter.ai/api/v1

JIRA_BASE_URL=https://your-site.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=...
```

`.env` is gitignored. Never commit it.

Verify both upstream services:

```bash
uv run python scripts/ping_llm.py
uv run python scripts/ping_jira.py
```

Run the agent:

```bash
uv run jira-agent
```

Write calls display their complete arguments and default to rejection. For a trusted session, confirmation can be disabled explicitly:

```bash
uv run jira-agent --yolo
```

The CLI prints a warning when `--yolo` is active. Exit with `/exit`, `/quit`, Ctrl+D, or Ctrl+C.

## Using the standalone MCP server

`jira-agent-mcp` communicates using newline-delimited MCP messages on stdin/stdout. Do not run it expecting an interactive prompt. A host should launch it with the three `JIRA_*` variables in its process environment.

Generic host configuration shape:

```json
{
  "command": "uv",
  "args": ["--directory", "/absolute/path/to/jira-agent", "run", "jira-agent-mcp"],
  "env": {
    "JIRA_BASE_URL": "https://your-site.atlassian.net",
    "JIRA_EMAIL": "you@example.com",
    "JIRA_API_TOKEN": "your-token"
  }
}
```

The server does not need any `LLM_*` settings. Keep the token in the host's secret/configuration mechanism rather than committing the example above.

## Tests and evals

Run the offline suite:

```bash
uv run pytest
```

The suite covers:

- Jira authentication, endpoint payloads, ADF, transitions, assignment, and errors with mocked HTTP.
- MCP discovery, schemas, annotations, structured output, validation, sanitization, and lifecycle.
- A real packaged stdio subprocess handshake without accessing Jira.
- Canned agent scenarios for discovery, read calls, approved/declined writes, malformed arguments, and runaway-loop protection.

Automated tests never access or modify a real Jira site.

## Design notes

### Runtime discovery

The agent knows no Jira tool names at compile time. `MCPToolClient` obtains the server's current definitions on connection and retains MCP annotations separately from the OpenAI schema sent to the model.

### Async host, synchronous Jira client

The MCP and LLM host path is asynchronous because the MCP client lifecycle is async. Jira REST calls remain synchronous inside the local, single-user stdio server to keep the HTTP layer easy to debug. A concurrent network server would warrant converting `JiraClient` to async.

### Error recovery

Ordinary Jira exceptions become MCP tool errors visible to the model. The host converts those and transport failures into the consistent `ok/error` envelope, allowing the model to correct bad JQL, arguments, or transition names without corrupting conversation history.

### MCP SDK 2.0 stdio bridge

The server uses MCP SDK 2.0 for schemas, dispatch, protocol models, and negotiation. Its entrypoint supplies a native asyncio pipe bridge because the SDK's worker-thread stdio reader can stall in restricted runtimes. The wire protocol and compatibility remain standard MCP.

## Known limitations

- An LLM failure after a user message is appended leaves that unmatched user message in history.
- Search is capped at 50 results and does not expose Jira pagination tokens.
- Transient Jira and LLM failures are not retried automatically.
- User lookup can be ambiguous because `assign_issue` takes the first Jira user-search match.
- Responses are not streamed.
- Only local stdio transport is supported; there is no Streamable HTTP deployment or server-side authentication layer.

See [ROADMAP.md](ROADMAP.md) for the remaining learning milestones.

"""Tool definitions for the LLM and the dispatch layer that runs them.

Two things live here:

1. TOOL_SCHEMAS — OpenAI-format JSON schemas sent to the LLM each turn so
   it knows what tools exist, what arguments they take, and when to use them.
2. dispatch() — turns a (tool_name, arguments) pair from the model into a
   real JiraClient method call, and wraps the result in a {ok, result|error}
   envelope so the model can react to failures.

To add a tool: append a schema to TOOL_SCHEMAS and add a handler to HANDLERS.
"""

from typing import Any, Callable

from .jira_client import JiraClient, JiraError

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_issue",
            "description": (
                "Create a new Jira issue in the given project. "
                "Use for bug reports, tasks, stories, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {
                        "type": "string",
                        "description": "Project key, e.g. 'SCRUM' or 'TEST'.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "One-line title for the issue.",
                    },
                    "issue_type": {
                        "type": "string",
                        "description": "Issue type. Common values: Bug, Task, Story, Epic.",
                        "default": "Task",
                    },
                    "priority": {
                        "type": "string",
                        "description": (
                            "Priority name. One of: Highest, High, Medium, Low, Lowest. "
                            "Map P1->Highest, P2->High, P3->Medium, P4->Low, P5->Lowest."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional longer-form description.",
                    },
                },
                "required": ["project_key", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_issues",
            "description": (
                "Search Jira issues using JQL (Jira Query Language). "
                "Example JQL: 'project = SCRUM AND status = \"To Do\" ORDER BY created DESC'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "jql": {
                        "type": "string",
                        "description": "A valid JQL query string.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of issues to return (default 20).",
                        "default": 20,
                    },
                },
                "required": ["jql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transition_issue",
            "description": (
                "Move an issue to a new workflow state by transition name "
                "(e.g. 'In Progress', 'Done'). If the name is wrong, the error "
                "will list the available transitions for that issue."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_key": {
                        "type": "string",
                        "description": "Issue key, e.g. 'SCRUM-12'.",
                    },
                    "transition_name": {
                        "type": "string",
                        "description": "Name of the workflow transition to apply.",
                    },
                },
                "required": ["issue_key", "transition_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_comment",
            "description": "Add a comment to an existing issue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_key": {
                        "type": "string",
                        "description": "Issue key, e.g. 'SCRUM-12'.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Comment text.",
                    },
                },
                "required": ["issue_key", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_issue",
            "description": (
                "Assign an issue to a user. The assignee can be an email, "
                "display name, 'me' (the authenticated user), or 'unassigned'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_key": {
                        "type": "string",
                        "description": "Issue key, e.g. 'SCRUM-12'.",
                    },
                    "assignee": {
                        "type": "string",
                        "description": "Email, display name, 'me', or 'unassigned'.",
                    },
                },
                "required": ["issue_key", "assignee"],
            },
        },
    },
]


def _create_issue(
    jira: JiraClient,
    project_key: str,
    summary: str,
    issue_type: str = "Task",
    priority: str | None = None,
    description: str | None = None,
) -> dict:
    return jira.create_issue(project_key, summary, issue_type, priority, description)


def _search_issues(jira: JiraClient, jql: str, max_results: int = 20) -> dict:
    raw = jira.search_issues(jql, max_results)
    return {
        "issues": [
            {
                "key": i["key"],
                "summary": i["fields"].get("summary"),
                "status": (i["fields"].get("status") or {}).get("name"),
                "issuetype": (i["fields"].get("issuetype") or {}).get("name"),
                "priority": (i["fields"].get("priority") or {}).get("name"),
                "assignee": (i["fields"].get("assignee") or {}).get("displayName"),
            }
            for i in raw.get("issues", [])
        ]
    }


def _transition_issue(jira: JiraClient, issue_key: str, transition_name: str) -> dict:
    jira.transition_issue(issue_key, transition_name)
    return {"transitioned": issue_key, "to": transition_name}


def _add_comment(jira: JiraClient, issue_key: str, body: str) -> dict:
    result = jira.add_comment(issue_key, body)
    return {"commented_on": issue_key, "comment_id": result.get("id")}


def _assign_issue(jira: JiraClient, issue_key: str, assignee: str) -> dict:
    jira.assign_issue(issue_key, assignee)
    return {"assigned": issue_key, "to": assignee}


HANDLERS: dict[str, Callable[..., dict]] = {
    "create_issue": _create_issue,
    "search_issues": _search_issues,
    "transition_issue": _transition_issue,
    "add_comment": _add_comment,
    "assign_issue": _assign_issue,
}


def dispatch(tool_name: str, arguments: dict[str, Any], jira: JiraClient) -> dict:
    """Run a tool call and return a {ok, result|error} envelope for the LLM."""
    handler = HANDLERS.get(tool_name)
    if handler is None:
        return {"ok": False, "error": f"Unknown tool: {tool_name}"}
    try:
        result = handler(jira, **arguments)
        return {"ok": True, "result": result}
    except JiraError as e:
        return {"ok": False, "error": str(e)}
    except TypeError as e:
        return {"ok": False, "error": f"Invalid arguments: {e}"}
    except Exception as e:
        # Catch-all so dispatch() is total: agent.py relies on every tool_call
        # producing a tool response, otherwise the chat history becomes invalid.
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

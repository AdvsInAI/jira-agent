from typing import Any

import httpx

from .config import Config


class JiraError(Exception):
    """Raised when Jira returns a non-2xx response. Carries the body for debugging."""


class JiraClient:
    """Thin wrapper over the Atlassian Cloud Jira REST API v3.

    Basic auth (email + API token). Responses are returned as parsed JSON.
    Description and comment bodies are wrapped in Atlassian Document Format,
    which the v3 API requires instead of plain strings.
    """

    def __init__(self, config: Config):
        self._base = config.jira_base_url
        self._client = httpx.Client(
            auth=(config.jira_email, config.jira_api_token),
            headers={"Accept": "application/json"},
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "JiraClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._client.request(method, f"{self._base}{path}", **kwargs)
        if resp.status_code >= 400:
            raise JiraError(f"{method} {path} -> {resp.status_code}: {resp.text}")
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def myself(self) -> dict:
        return self._request("GET", "/rest/api/3/myself")

    def create_issue(
        self,
        project_key: str,
        summary: str,
        issue_type: str = "Task",
        priority: str | None = None,
        description: str | None = None,
    ) -> dict:
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        if priority:
            fields["priority"] = {"name": priority}
        if description:
            fields["description"] = _adf_text(description)
        return self._request("POST", "/rest/api/3/issue", json={"fields": fields})

    def search_issues(self, jql: str, max_results: int = 20) -> dict:
        body = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ["summary", "status", "assignee", "issuetype", "priority"],
        }
        return self._request("POST", "/rest/api/3/search/jql", json=body)

    def transition_issue(self, issue_key: str, transition_name: str) -> None:
        transitions = self._request(
            "GET", f"/rest/api/3/issue/{issue_key}/transitions"
        )["transitions"]
        match = next(
            (t for t in transitions if t["name"].lower() == transition_name.lower()),
            None,
        )
        if not match:
            available = ", ".join(t["name"] for t in transitions) or "(none)"
            raise JiraError(
                f"No transition named {transition_name!r} on {issue_key}. "
                f"Available: {available}"
            )
        self._request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/transitions",
            json={"transition": {"id": match["id"]}},
        )

    def add_comment(self, issue_key: str, body: str) -> dict:
        return self._request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/comment",
            json={"body": _adf_text(body)},
        )

    def assign_issue(self, issue_key: str, assignee: str) -> None:
        if assignee.lower() in {"unassigned", "none", ""}:
            account_id = None
        elif assignee.lower() == "me":
            account_id = self.myself()["accountId"]
        else:
            results = self._request(
                "GET", "/rest/api/3/user/search", params={"query": assignee}
            )
            if not results:
                raise JiraError(f"No user found matching {assignee!r}")
            account_id = results[0]["accountId"]
        self._request(
            "PUT",
            f"/rest/api/3/issue/{issue_key}/assignee",
            json={"accountId": account_id},
        )


def _adf_text(text: str) -> dict:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }

import base64
import json

import httpx
import pytest
import respx

from jira_agent.config import JiraConfig
from jira_agent.jira_client import JiraClient, JiraError


@pytest.fixture
def config() -> JiraConfig:
    return JiraConfig(
        jira_base_url="https://example.atlassian.net",
        jira_email="user@example.com",
        jira_api_token="secret-token",
    )


@respx.mock
def test_create_issue_uses_basic_auth_and_adf(config: JiraConfig) -> None:
    route = respx.post("https://example.atlassian.net/rest/api/3/issue").mock(
        return_value=httpx.Response(201, json={"id": "10001", "key": "TEST-1"})
    )

    with JiraClient(config) as client:
        result = client.create_issue(
            "TEST", "Broken login", "Bug", "High", "Steps to reproduce"
        )

    assert result["key"] == "TEST-1"
    request = route.calls.last.request
    expected = base64.b64encode(b"user@example.com:secret-token").decode()
    assert request.headers["Authorization"] == f"Basic {expected}"
    body = request.read().decode()
    assert '"description":{"type":"doc","version":1' in body
    assert '"text":"Steps to reproduce"' in body


@respx.mock
def test_search_issues_posts_jql_and_requested_fields(config: JiraConfig) -> None:
    route = respx.post("https://example.atlassian.net/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": []})
    )

    with JiraClient(config) as client:
        client.search_issues("project = TEST", 7)

    payload = json.loads(route.calls.last.request.content)
    assert payload["jql"] == "project = TEST"
    assert payload["maxResults"] == 7
    assert payload["fields"] == [
        "summary",
        "status",
        "assignee",
        "issuetype",
        "priority",
    ]


@respx.mock
def test_transition_matches_name_and_posts_transition_id(config: JiraConfig) -> None:
    get_route = respx.get(
        "https://example.atlassian.net/rest/api/3/issue/TEST-1/transitions"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"transitions": [{"id": "31", "name": "In Progress"}]},
        )
    )
    post_route = respx.post(
        "https://example.atlassian.net/rest/api/3/issue/TEST-1/transitions"
    ).mock(return_value=httpx.Response(204))

    with JiraClient(config) as client:
        client.transition_issue("TEST-1", "in progress")

    assert get_route.called
    assert json.loads(post_route.calls.last.request.content) == {
        "transition": {"id": "31"}
    }


@respx.mock
def test_transition_error_lists_available_names(config: JiraConfig) -> None:
    respx.get(
        "https://example.atlassian.net/rest/api/3/issue/TEST-1/transitions"
    ).mock(
        return_value=httpx.Response(
            200, json={"transitions": [{"id": "11", "name": "To Do"}]}
        )
    )

    with JiraClient(config) as client:
        with pytest.raises(JiraError, match="Available: To Do"):
            client.transition_issue("TEST-1", "Done")


@respx.mock
def test_assign_me_resolves_account_id(config: JiraConfig) -> None:
    respx.get("https://example.atlassian.net/rest/api/3/myself").mock(
        return_value=httpx.Response(200, json={"accountId": "abc123"})
    )
    route = respx.put(
        "https://example.atlassian.net/rest/api/3/issue/TEST-1/assignee"
    ).mock(return_value=httpx.Response(204))

    with JiraClient(config) as client:
        client.assign_issue("TEST-1", "me")

    assert json.loads(route.calls.last.request.content) == {
        "accountId": "abc123"
    }


@respx.mock
def test_non_success_response_raises_jira_error(config: JiraConfig) -> None:
    respx.get("https://example.atlassian.net/rest/api/3/myself").mock(
        return_value=httpx.Response(401, text="not authenticated")
    )

    with JiraClient(config) as client:
        with pytest.raises(JiraError, match=r"GET /rest/api/3/myself -> 401"):
            client.myself()

"""Smoke test: confirm Jira credentials reach the API.

Calls GET /rest/api/3/myself (read-only) and prints the authenticated user.

Run: uv run python scripts/ping_jira.py
"""

from jira_agent.config import load_jira_config
from jira_agent.jira_client import JiraClient


def main() -> None:
    cfg = load_jira_config()
    client = JiraClient(cfg)
    print(f"Site: {cfg.jira_base_url}")
    me = client.myself()
    print(f"Authenticated as: {me.get('displayName')!r}")
    print(f"  accountId: {me.get('accountId')}")
    print(f"  emailAddress: {me.get('emailAddress')}")


if __name__ == "__main__":
    main()

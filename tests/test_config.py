from jira_agent.config import load_config, load_jira_config


def test_jira_server_config_does_not_require_llm(monkeypatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net/")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    config = load_jira_config()

    assert config.jira_base_url == "https://example.atlassian.net"


def test_full_config_is_split(monkeypatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")
    monkeypatch.setenv("LLM_API_KEY", "llm-token")
    monkeypatch.setenv("LLM_MODEL", "model")

    config = load_config()

    assert config.llm.llm_model == "model"
    assert config.jira.jira_email == "user@example.com"

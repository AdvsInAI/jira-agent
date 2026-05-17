import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class Config:
    llm_api_key: str
    llm_model: str
    llm_base_url: str
    jira_base_url: str
    jira_email: str
    jira_api_token: str


REQUIRED_ENV = [
    "LLM_API_KEY",
    "LLM_MODEL",
    "JIRA_BASE_URL",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
]


def load_config() -> Config:
    load_dotenv()
    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    if missing:
        raise RuntimeError(
            f"Missing env vars: {', '.join(missing)}. "
            f"Copy .env.example to .env and fill it in."
        )
    return Config(
        llm_api_key=os.environ["LLM_API_KEY"],
        llm_model=os.environ["LLM_MODEL"],
        llm_base_url=os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        jira_base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
        jira_email=os.environ["JIRA_EMAIL"],
        jira_api_token=os.environ["JIRA_API_TOKEN"],
    )

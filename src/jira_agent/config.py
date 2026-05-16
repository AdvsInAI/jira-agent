import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    openrouter_api_key: str
    openrouter_model: str
    jira_base_url: str
    jira_email: str
    jira_api_token: str


REQUIRED_ENV = [
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
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
        openrouter_api_key=os.environ["OPENROUTER_API_KEY"],
        openrouter_model=os.environ["OPENROUTER_MODEL"],
        jira_base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
        jira_email=os.environ["JIRA_EMAIL"],
        jira_api_token=os.environ["JIRA_API_TOKEN"],
    )

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")
    app_env: str = "development"
    database_url: str = "sqlite:///./portfolio.db"
    cors_origins: str = "http://localhost:3000"
    github_token: str | None = None
    github_app_id: str | None = None
    github_private_key: str | None = None
    github_webhook_secret: str | None = None
    dashboard_api_key: str | None = None
    portfolio_owner: str | None = None
    portfolio_repo: str | None = None
    llm_provider: str = "openai"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4.1-mini"
    openai_api_key: str | None = None
    groq_api_key: str | None = None
    portfolio_confidence_threshold: float = 0.85
    auto_create_pr: bool = True
    auto_merge: bool = False
    auto_update_skills: bool = True
    auto_update_timeline: bool = True
    auto_update_resume: bool = False
    auto_generate_blog: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()

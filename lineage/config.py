from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    falkor_host: str = "localhost"
    falkor_port: int = 6379
    falkor_password: str | None = None
    anthropic_api_key: str | None = None
    github_token: str | None = None
    llm_model: str = "claude-sonnet-5-5"
    embed_model: str = "BAAI/bge-small-en-v1.5"


@lru_cache
def settings() -> Settings:
    return Settings()

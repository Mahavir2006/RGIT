from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Unprefixed secrets remain compatible with the pipeline .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    urban_sentinel_env: str = "development"
    urban_sentinel_log_level: str = "INFO"
    urban_sentinel_api_host: str = "0.0.0.0"
    urban_sentinel_api_port: int = 8000
    urban_sentinel_review_token: str = "change-me"

    urban_sentinel_llm_provider: str = "none"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-haiku-latest"
    urban_sentinel_llm_timeout_seconds: float = 20.0
    urban_sentinel_llm_max_retries: int = 2
    urban_sentinel_prompt_version: str = "intelligence-v1"

    database_url: str | None = None
    neo4j_uri: str | None = None
    neo4j_user: str = "neo4j"
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"

    urban_sentinel_max_graph_depth: int = 4
    urban_sentinel_association_ambiguity_threshold: float = 0.65
    urban_sentinel_high_impact_severity: float = 0.75
    urban_sentinel_cache_ttl_seconds: int = 300
    urban_sentinel_workflow_timeout_seconds: float = 90.0

    @property
    def env(self) -> str:
        return self.urban_sentinel_env

    @property
    def log_level(self) -> str:
        return self.urban_sentinel_log_level

    @property
    def api_host(self) -> str:
        return self.urban_sentinel_api_host

    @property
    def api_port(self) -> int:
        return self.urban_sentinel_api_port

    @property
    def review_token(self) -> str:
        return self.urban_sentinel_review_token

    @property
    def llm_provider(self) -> str:
        return self.urban_sentinel_llm_provider.lower()

    @property
    def llm_timeout_seconds(self) -> float:
        return self.urban_sentinel_llm_timeout_seconds

    @property
    def llm_max_retries(self) -> int:
        return self.urban_sentinel_llm_max_retries

    @property
    def prompt_version(self) -> str:
        return self.urban_sentinel_prompt_version

    @property
    def max_graph_depth(self) -> int:
        return self.urban_sentinel_max_graph_depth

    @property
    def association_ambiguity_threshold(self) -> float:
        return self.urban_sentinel_association_ambiguity_threshold

    @property
    def high_impact_severity(self) -> float:
        return self.urban_sentinel_high_impact_severity

    @property
    def cache_ttl_seconds(self) -> int:
        return self.urban_sentinel_cache_ttl_seconds

    @property
    def workflow_timeout_seconds(self) -> float:
        return self.urban_sentinel_workflow_timeout_seconds


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

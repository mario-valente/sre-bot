"""Application configuration via environment variables."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via env vars or .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === LLM Configuration ===
    llm_provider: LLMProvider = Field(
        default=LLMProvider.OPENAI,
        description="LLM provider to use (openai or anthropic)",
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        description="OpenAI API key",
    )
    openai_model: str = Field(
        default="gpt-4o",
        description="OpenAI model name",
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        description="Anthropic API key",
    )
    anthropic_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Anthropic model name",
    )
    llm_temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="LLM temperature (lower = more deterministic)",
    )
    llm_max_tokens: int = Field(
        default=4096,
        description="Maximum tokens for LLM response",
    )

    # === Input Sources (Feature Flags) ===
    enable_webhook: bool = Field(
        default=True,
        description="Enable webhook receiver for Alertmanager",
    )
    enable_slack_listener: bool = Field(
        default=True,
        description="Enable Slack event listener for alerts",
    )
    webhook_host: str = Field(
        default="0.0.0.0",
        description="Webhook server host",
    )
    webhook_port: int = Field(
        default=8000,
        description="Webhook server port",
    )

    # === Slack Configuration ===
    slack_bot_token: SecretStr | None = Field(
        default=None,
        description="Slack Bot Token (xoxb-...)",
    )
    slack_app_token: SecretStr | None = Field(
        default=None,
        description="Slack App Token for Socket Mode (xapp-...)",
    )
    slack_signing_secret: SecretStr | None = Field(
        default=None,
        description="Slack Signing Secret for request verification",
    )
    slack_alert_channel: str = Field(
        default="alerts",
        description="Slack channel to monitor for alerts",
    )

    # === Observability Stack ===
    prometheus_url: str = Field(
        default="http://localhost:9090",
        description="Prometheus server URL",
    )
    alertmanager_url: str = Field(
        default="http://localhost:9093",
        description="Alertmanager server URL",
    )
    loki_url: str = Field(
        default="http://localhost:3100",
        description="Loki server URL",
    )
    tempo_url: str = Field(
        default="http://localhost:3200",
        description="Tempo server URL",
    )

    # === GitHub Configuration ===
    github_token: SecretStr | None = Field(
        default=None,
        description="GitHub Personal Access Token",
    )
    github_org: str = Field(
        default="",
        description="Default GitHub organization for repository lookups",
    )

    # === Kubernetes Configuration ===
    kubernetes_enabled: bool = Field(
        default=True,
        description="Enable Kubernetes API integration",
    )
    kubernetes_in_cluster: bool = Field(
        default=False,
        description="Use in-cluster config (True when running inside K8s)",
    )
    kubernetes_config_path: str | None = Field(
        default=None,
        description="Path to kubeconfig file (None = default location)",
    )
    kubernetes_context: str | None = Field(
        default=None,
        description="Kubernetes context to use (None = current context)",
    )
    kubernetes_log_lines: int = Field(
        default=100,
        description="Number of log lines to fetch from pods",
    )

    # === Database Configuration ===
    database_url: str = Field(
        default="sqlite+aiosqlite:///./sre_bot.db",
        description="Database connection URL (SQLite for dev, PostgreSQL for prod)",
    )

    # === Timeouts ===
    log_level: str = Field(
        default="INFO",
        description="Application log level (DEBUG, INFO, WARNING, ERROR)",
    )

    query_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Timeout for observability queries",
    )
    llm_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Timeout for LLM API calls",
    )

    # === Investigation Parameters ===
    lookback_minutes: int = Field(
        default=30,
        description="How far back to look for metrics/logs/traces",
    )
    recent_deploy_hours: int = Field(
        default=2,
        description="Consider deploys within this window as 'recent'",
    )
    correlation_window_minutes: int = Field(
        default=120,
        description="Time window to search for correlated alerts (default: 2 hours)",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are loaded only once.
    """
    return Settings()


# Convenience alias for direct import
settings = get_settings()

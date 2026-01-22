"""
Configuration management for Helpdesk AI.
All configuration is loaded from environment variables.
"""
import os
import sys
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class GLPISettings(BaseSettings):
    """GLPI connection settings."""
    base_url: str = Field(..., validation_alias="GLPI_BASE_URL")
    app_token: str = Field(..., validation_alias="GLPI_APP_TOKEN")
    username: str = Field(..., validation_alias="GLPI_USERNAME")
    password: str = Field(..., validation_alias="GLPI_PASSWORD")
    session_timeout_minutes: int = Field(30, validation_alias="GLPI_SESSION_TIMEOUT_MINUTES")
    max_retries: int = Field(3, validation_alias="GLPI_MAX_RETRIES")
    timeout_seconds: int = Field(30, validation_alias="GLPI_TIMEOUT_SECONDS")

    @field_validator("base_url")
    @classmethod
    def remove_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    class Config:
        env_file = ".env"
        extra = "ignore"


class OpenAISettings(BaseSettings):
    """OpenAI API settings."""
    api_key: str = Field(..., validation_alias="OPENAI_API_KEY")
    model: str = Field(..., validation_alias="OPENAI_MODEL")
    base_url: str = Field("https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL")
    org_id: Optional[str] = Field(None, validation_alias="OPENAI_ORG_ID")
    project_id: Optional[str] = Field(None, validation_alias="OPENAI_PROJECT_ID")
    temperature: float = Field(0.2, validation_alias="OPENAI_TEMPERATURE")
    max_tokens: int = Field(800, validation_alias="OPENAI_MAX_TOKENS")
    timeout_seconds: int = Field(60, validation_alias="OPENAI_TIMEOUT_SECONDS")
    retries: int = Field(3, validation_alias="OPENAI_RETRIES")

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        if v < 0 or v > 2:
            raise ValueError("Temperature must be between 0 and 2")
        return v

    class Config:
        env_file = ".env"
        extra = "ignore"


class RedisSettings(BaseSettings):
    """Redis cache settings."""
    url: str = Field("redis://localhost:6379/0", validation_alias="REDIS_URL")
    kb_cache_ttl: int = Field(3600, validation_alias="REDIS_KB_CACHE_TTL")
    ticket_cache_ttl: int = Field(900, validation_alias="REDIS_TICKET_CACHE_TTL")

    class Config:
        env_file = ".env"
        extra = "ignore"


class AuthSettings(BaseSettings):
    """Authentication settings."""
    enabled: bool = Field(False, validation_alias="AUTH_ENABLED")
    jwt_secret: Optional[str] = Field(None, validation_alias="AUTH_JWT_SECRET")
    token_expiry_minutes: int = Field(60, validation_alias="AUTH_TOKEN_EXPIRY_MINUTES")
    jwt_issuers: Optional[str] = Field(None, validation_alias="AUTH_JWT_ISSUERS")

    @property
    def jwt_issuers_list(self) -> List[str]:
        if self.jwt_issuers:
            return [i.strip() for i in self.jwt_issuers.split(",")]
        return []

    class Config:
        env_file = ".env"
        extra = "ignore"


class AppSettings(BaseSettings):
    """Application settings."""
    env: str = Field("dev", validation_alias="APP_ENV")
    port: int = Field(8000, validation_alias="APP_PORT")
    log_level: str = Field("info", validation_alias="APP_LOG_LEVEL")
    allowed_origins: str = Field("http://localhost:3000", validation_alias="APP_ALLOWED_ORIGINS")
    rate_limit_rpm: int = Field(30, validation_alias="APP_RATE_LIMIT_RPM")
    session_ttl_minutes: int = Field(60, validation_alias="APP_SESSION_TTL_MINUTES")
    max_message_length: int = Field(4000, validation_alias="APP_MAX_MESSAGE_LENGTH")
    secret_key: Optional[str] = Field(None, validation_alias="APP_SECRET_KEY")

    @property
    def allowed_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.env == "prod"

    class Config:
        env_file = ".env"
        extra = "ignore"


class ObservabilitySettings(BaseSettings):
    """Observability settings."""
    otel_enabled: bool = Field(False, validation_alias="OTEL_ENABLED")
    otel_endpoint: str = Field("http://localhost:4317", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    service_name: str = Field("helpdesk-ai", validation_alias="OTEL_SERVICE_NAME")
    metrics_enabled: bool = Field(True, validation_alias="METRICS_ENABLED")
    metrics_port: int = Field(9090, validation_alias="METRICS_PORT")

    class Config:
        env_file = ".env"
        extra = "ignore"


class Settings:
    """Aggregate settings container."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize all settings and validate required variables."""
        self._validate_required_env_vars()

        self.glpi = GLPISettings()
        self.openai = OpenAISettings()
        self.redis = RedisSettings()
        self.auth = AuthSettings()
        self.app = AppSettings()
        self.observability = ObservabilitySettings()

    def _validate_required_env_vars(self):
        """Validate that all required environment variables are set."""
        required_vars = [
            ("GLPI_BASE_URL", "GLPI base URL"),
            ("GLPI_APP_TOKEN", "GLPI application token"),
            ("GLPI_USERNAME", "GLPI username"),
            ("GLPI_PASSWORD", "GLPI password"),
            ("OPENAI_API_KEY", "OpenAI API key"),
            ("OPENAI_MODEL", "OpenAI model name"),
        ]

        missing = []
        for var, description in required_vars:
            if not os.getenv(var):
                missing.append(f"  - {var}: {description}")

        if missing:
            print("ERROR: Missing required environment variables:", file=sys.stderr)
            print("\n".join(missing), file=sys.stderr)
            print("\nPlease set these variables in your .env file or environment.", file=sys.stderr)
            print("See .env.example for reference.", file=sys.stderr)
            sys.exit(1)


def get_settings() -> Settings:
    """Get the singleton settings instance."""
    return Settings()

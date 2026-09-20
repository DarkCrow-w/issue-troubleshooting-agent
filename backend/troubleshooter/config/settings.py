from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_url: str = ""
    source_mode: str = "replay"
    model_mode: str = "offline"
    agent_url: str = "http://127.0.0.1:8001"
    service_token: str = "local-development-only"
    data_dir: Path = PROJECT_ROOT / "data"
    config_path: Path = PROJECT_ROOT / "config/settings.yaml"
    skills_dir: Path = PROJECT_ROOT / "skills"
    replay_path: Path = PROJECT_ROOT / "examples/transaction.json"
    splunk_url: str = ""
    splunk_token: str = ""
    splunk_verify_tls: bool = True
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen3.8-flash"
    llm_context_tokens: int = 32000
    llm_max_output_tokens: int = Field(default=8192, ge=1)
    retention_hours: int = 24
    task_timeout_seconds: int = 180
    max_followups: int = 3
    max_events: int = 10000
    max_bytes: int = 50_000_000
    max_model_calls: int = 8
    max_input_tokens: int = 16000

    @model_validator(mode="after")
    def validate_context_budget(self):
        if self.llm_max_output_tokens >= self.llm_context_tokens:
            raise ValueError("LLM_MAX_OUTPUT_TOKENS 必须小于 LLM_CONTEXT_TOKENS")
        return self


def get_settings() -> Settings:
    return Settings()

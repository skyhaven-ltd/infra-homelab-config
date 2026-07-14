from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    database_url: str
    upload_dir: str
    anthropic_api_key: str
    anthropic_model: str
    worker_token: str

    @staticmethod
    def from_env() -> Settings:
        return Settings(
            database_url=os.environ.get(
                "DATABASE_URL", "sqlite:///./data/bookbuddy.db"
            ),
            upload_dir=os.environ.get("UPLOAD_DIR", "./data/uploads"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8"),
            worker_token=os.environ.get("WORKER_TOKEN", ""),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()

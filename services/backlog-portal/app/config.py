from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Target:
    id: str
    provider: str
    label: str
    organisation: str
    container: str
    item_types: tuple[str, ...]
    project_id: str
    template: str


@dataclass(frozen=True)
class Settings:
    database_url: str
    username: str
    password: str
    worker_token: str
    github_token: str
    azure_devops_token: str
    targets: tuple[Target, ...]

    @staticmethod
    def from_env() -> Settings:
        raw_targets = json.loads(os.environ.get("PORTAL_TARGETS", "[]"))
        targets = tuple(
            Target(
                id=value["id"],
                provider=value["provider"],
                label=value["label"],
                organisation=value["organisation"],
                container=value["container"],
                item_types=tuple(value["item_types"]),
                project_id=value.get("project_id", ""),
                template=value.get(
                    "template",
                    "Produce an implementation-ready backlog item with testable "
                    "acceptance criteria.",
                ),
            )
            for value in raw_targets
        )
        return Settings(
            database_url=os.environ.get(
                "DATABASE_URL", "sqlite:///./data/backlog-portal.db"
            ),
            username=os.environ.get("PORTAL_USERNAME", ""),
            password=os.environ.get("PORTAL_PASSWORD", ""),
            worker_token=os.environ.get("WORKER_TOKEN", ""),
            github_token=os.environ.get("GITHUB_TOKEN", ""),
            azure_devops_token=os.environ.get("AZURE_DEVOPS_TOKEN", ""),
            targets=targets,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass, field
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
    project_url: str = ""
    template_mappings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    database_url: str
    username: str
    password: str
    worker_token: str
    github_token: str
    azure_devops_token: str
    targets: tuple[Target, ...]
    github_organisation: str = "skyhaven-ltd"
    azure_devops_organisation: str = "version1ukdcs"
    github_project_id: str = ""
    github_project_url: str = "https://github.com/orgs/skyhaven-ltd/dashboard"
    template_repository: str = "skyhaven-ltd/.github"

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
                project_url=value.get("project_url", ""),
                template_mappings=dict(value.get("template_mappings", {})),
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
            github_organisation=os.environ.get("GITHUB_ORGANISATION", "skyhaven-ltd"),
            azure_devops_organisation=os.environ.get(
                "AZURE_DEVOPS_ORGANISATION", "version1ukdcs"
            ),
            github_project_id=os.environ.get("GITHUB_PROJECT_ID", ""),
            github_project_url=os.environ.get(
                "GITHUB_PROJECT_URL",
                "https://github.com/orgs/skyhaven-ltd/dashboard",
            ),
            template_repository=os.environ.get(
                "TEMPLATE_REPOSITORY", "skyhaven-ltd/.github"
            ),
        )


TEMPLATE_MAPPINGS = {
    "github": {
        "Bug": ".github/ISSUE_TEMPLATE/bug-report.md",
        "Feature": ".github/ISSUE_TEMPLATE/feature-request.md",
        "Task": ".github/ISSUE_TEMPLATE/task.md",
    },
    "azure_devops": {
        "Bug": ".github/ADO_WORK_ITEM_TEMPLATE/bug.md",
        "Feature": ".github/ADO_WORK_ITEM_TEMPLATE/feature.md",
        "Task": ".github/ADO_WORK_ITEM_TEMPLATE/task.md",
    },
}


def dynamic_target(settings: Settings, provider: str, container: str) -> Target:
    clean_container = container.strip()
    if not clean_container or len(clean_container) > 256:
        raise ValueError("Invalid destination")
    if provider == "github":
        organisation = settings.github_organisation
        project_url = settings.github_project_url
        project_id = settings.github_project_id
        template = "Use the canonical GitHub issue template."
    elif provider == "azure_devops":
        organisation = settings.azure_devops_organisation
        project_url = (
            f"https://dev.azure.com/{organisation}/"
            f"{urllib.parse.quote(clean_container, safe='')}"
        )
        project_id = ""
        template = "Use the canonical Azure DevOps Agile work item template."
    else:
        raise ValueError("Unsupported provider")
    encoded = urllib.parse.quote(clean_container, safe="")
    return Target(
        id=f"{provider}:{encoded}",
        provider=provider,
        label=clean_container,
        organisation=organisation,
        container=clean_container,
        item_types=("Bug", "Feature", "Task"),
        project_id=project_id,
        template=template,
        project_url=project_url,
        template_mappings=TEMPLATE_MAPPINGS[provider],
    )


def target_from_id(settings: Settings, target_id: str) -> Target | None:
    configured = next(
        (target for target in settings.targets if target.id == target_id), None
    )
    if configured is not None:
        return configured
    provider, separator, encoded = target_id.partition(":")
    if not separator or provider not in TEMPLATE_MAPPINGS:
        return None
    try:
        container = urllib.parse.unquote(encoded, errors="strict")
        target = dynamic_target(settings, provider, container)
    except (UnicodeDecodeError, ValueError):
        return None
    return target if target.id == target_id else None


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()

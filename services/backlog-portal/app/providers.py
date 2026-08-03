from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from app.config import Settings, Target
from app.models import Draft


class SubmissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SubmittedItem:
    url: str
    external_id: str


def _request(url: str, headers: dict[str, str], payload: object) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **headers,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise SubmissionError(f"Provider returned HTTP {exc.code}: {detail}") from exc


def submit(settings: Settings, target: Target, draft: Draft) -> SubmittedItem:
    if target.provider == "github":
        return _submit_github(settings, target, draft)
    if target.provider == "azure_devops":
        return _submit_azure_devops(settings, target, draft)
    raise SubmissionError("Unsupported provider")


def _body(draft: Draft) -> str:
    parts = [draft.description.strip()]
    if draft.acceptance_criteria.strip():
        parts.extend(["## Acceptance criteria", draft.acceptance_criteria.strip()])
    if draft.priority.strip():
        parts.extend(["## Priority", draft.priority.strip()])
    return "\n\n".join(parts)


def _submit_github(settings: Settings, target: Target, draft: Draft) -> SubmittedItem:
    if not settings.github_token:
        raise SubmissionError("GitHub credentials are not configured")
    payload: dict[str, object] = {"title": draft.title, "body": _body(draft)}
    labels = [value.strip() for value in draft.labels.split(",") if value.strip()]
    if draft.item_type not in labels:
        labels.append(draft.item_type)
    if labels:
        payload["labels"] = labels
    if draft.assignee:
        payload["assignees"] = [draft.assignee]
    data = _request(
        f"https://api.github.com/repos/{target.organisation}/{target.container}/issues",
        {
            "Authorization": f"Bearer {settings.github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        payload,
    )
    return SubmittedItem(url=data["html_url"], external_id=str(data["number"]))


def _submit_azure_devops(
    settings: Settings, target: Target, draft: Draft
) -> SubmittedItem:
    if not settings.azure_devops_token:
        raise SubmissionError("Azure DevOps credentials are not configured")
    path_type = urllib.parse.quote(draft.item_type, safe="")
    project = urllib.parse.quote(target.container, safe="")
    url = (
        f"https://dev.azure.com/{target.organisation}/{project}/_apis/wit/"
        f"workitems/${path_type}?api-version=7.1"
    )
    operations: list[dict[str, str]] = [
        {"op": "add", "path": "/fields/System.Title", "value": draft.title},
        {
            "op": "add",
            "path": "/fields/System.Description",
            "value": draft.description,
        },
    ]
    optional = {
        "Microsoft.VSTS.Common.AcceptanceCriteria": draft.acceptance_criteria,
        "Microsoft.VSTS.Common.Priority": draft.priority,
        "System.AreaPath": draft.area,
        "System.IterationPath": draft.iteration,
        "System.Tags": "; ".join(
            value.strip() for value in draft.labels.split(",") if value.strip()
        ),
        "System.AssignedTo": draft.assignee,
    }
    operations.extend(
        {"op": "add", "path": f"/fields/{field}", "value": value}
        for field, value in optional.items()
        if value
    )
    auth = base64.b64encode(f":{settings.azure_devops_token}".encode()).decode()
    data = _request(
        url,
        {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json-patch+json",
        },
        operations,
    )
    return SubmittedItem(
        url=data["_links"]["html"]["href"], external_id=str(data["id"])
    )

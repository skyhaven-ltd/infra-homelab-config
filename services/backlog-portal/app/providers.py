from __future__ import annotations

import base64
import json
import re
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


@dataclass(frozen=True)
class IssueTemplate:
    prefix: str
    issue_type: str
    assignees: tuple[str, ...]


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


def _get(url: str, headers: dict[str, str]) -> object:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise SubmissionError(f"Provider returned HTTP {exc.code}: {detail}") from exc


def _add_to_github_project(settings: Settings, project_id: str, item_id: str) -> None:
    mutation = """
    mutation($project: ID!, $item: ID!) {
      addProjectV2ItemById(input: {projectId: $project, contentId: $item}) {
        item { id }
      }
    }
    """
    _request(
        "https://api.github.com/graphql",
        {
            "Authorization": f"Bearer {settings.github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        {"query": mutation, "variables": {"project": project_id, "item": item_id}},
    )


def _github_headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "X-GitHub-Api-Version": "2026-03-10",
    }


def _parse_issue_template(content: str) -> IssueTemplate:
    if not content.startswith("---\n") or "\n---\n" not in content[4:]:
        raise SubmissionError("Canonical issue template has no front matter")
    front_matter = content[4:].split("\n---\n", 1)[0]
    values: dict[str, str] = {}
    for line in front_matter.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip().strip("\"'")
    title = values.get("title", "")
    prefix = title.removesuffix("Placeholder").rstrip()
    issue_type = values.get("type", "")
    if not prefix or not issue_type:
        raise SubmissionError("Canonical template must define title and type")
    assignees = tuple(
        value.strip()
        for value in values.get("assignees", "").split(",")
        if value.strip()
    )
    return IssueTemplate(
        prefix=f"{prefix} ", issue_type=issue_type, assignees=assignees
    )


def _load_issue_template(
    settings: Settings, target: Target, item_type: str
) -> IssueTemplate:
    path = target.template_mappings.get(item_type, "")
    if not path:
        raise SubmissionError(f"No canonical template is mapped for {item_type}")
    encoded_path = urllib.parse.quote(path, safe="/")
    data = _get(
        f"https://api.github.com/repos/{target.organisation}/.github/contents/"
        f"{encoded_path}?ref=main",
        _github_headers(settings),
    )
    if not isinstance(data, dict) or not data.get("content"):
        raise SubmissionError("Canonical issue template could not be read")
    try:
        content = base64.b64decode(str(data["content"])).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise SubmissionError("Canonical issue template is invalid") from exc
    return _parse_issue_template(content)


def _normalise_title(title: str, prefix: str) -> str:
    unprefixed = re.sub(r"^(?:\[(?:BUG|FEATURE|TASK)\]\s*-\s*)+", "", title, flags=re.I)
    return f"{prefix}{unprefixed.strip()}"


def _assign_github_issue_type(
    settings: Settings, target: Target, issue_id: str, issue_type: str
) -> None:
    available = _get(
        f"https://api.github.com/repos/{target.organisation}/{target.container}/issue-types",
        _github_headers(settings),
    )
    match = next(
        (
            value
            for value in available
            if isinstance(value, dict)
            and str(value.get("name", "")).casefold() == issue_type.casefold()
        ),
        None,
    )
    if not match or not match.get("node_id"):
        raise SubmissionError(f"GitHub issue type {issue_type} is unavailable")
    mutation = """
    mutation($issue: ID!, $type: ID!) {
      updateIssueIssueType(input: {issueId: $issue, issueTypeId: $type}) {
        issue { id }
      }
    }
    """
    _request(
        "https://api.github.com/graphql",
        _github_headers(settings),
        {"query": mutation, "variables": {"issue": issue_id, "type": match["node_id"]}},
    )


def submit(settings: Settings, target: Target, draft: Draft) -> SubmittedItem:
    if target.provider == "github":
        return _submit_github(settings, target, draft)
    if target.provider == "azure_devops":
        return _submit_azure_devops(settings, target, draft)
    raise SubmissionError("Unsupported provider")


def _body(draft: Draft) -> str:
    parts = [draft.description.strip(), "## Item type", draft.item_type]
    if draft.acceptance_criteria.strip():
        parts.extend(["## Acceptance criteria", draft.acceptance_criteria.strip()])
    if draft.priority.strip():
        parts.extend(["## Priority", draft.priority.strip()])
    return "\n\n".join(parts)


def _submit_github(settings: Settings, target: Target, draft: Draft) -> SubmittedItem:
    if not settings.github_token:
        raise SubmissionError("GitHub credentials are not configured")
    template = _load_issue_template(settings, target, draft.item_type)
    payload: dict[str, object] = {
        "title": _normalise_title(draft.title, template.prefix),
        "body": _body(draft),
    }
    requested_labels = [
        value.strip() for value in draft.labels.split(",") if value.strip()
    ]
    available = _get(
        f"https://api.github.com/repos/{target.organisation}/{target.container}/labels"
        "?per_page=100",
        _github_headers(settings),
    )
    available_names = {
        str(value["name"]).casefold(): str(value["name"])
        for value in available
        if isinstance(value, dict) and value.get("name")
    }
    labels = [
        available_names[value.casefold()]
        for value in requested_labels
        if value.casefold() in available_names
    ]
    if labels:
        payload["labels"] = labels
    assignees = [draft.assignee] if draft.assignee else list(template.assignees)
    if assignees:
        payload["assignees"] = assignees
    data = _request(
        f"https://api.github.com/repos/{target.organisation}/{target.container}/issues",
        _github_headers(settings),
        payload,
    )
    _assign_github_issue_type(settings, target, data["node_id"], template.issue_type)
    if target.project_id:
        _add_to_github_project(settings, target.project_id, data["node_id"])
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

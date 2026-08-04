import base64
import json
from unittest.mock import patch

from app.config import Settings, Target
from app.models import Draft
from app.providers import (
    _normalise_title,
    _parse_issue_template,
    list_destinations,
    submit,
)


class Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return json.dumps(self.value).encode()


def settings():
    return Settings(
        database_url="sqlite://",
        username="user",
        password="password",
        worker_token="worker",
        github_token="github-token",
        azure_devops_token="ado-token",
        targets=(),
    )


def draft():
    return Draft(
        target_id="target",
        item_type="Feature",
        raw_idea="idea",
        title="A useful feature",
        description="Description",
        acceptance_criteria="- [ ] It works",
        priority="2",
        area="",
        iteration="",
        labels="portal, ready",
        assignee="",
    )


def test_github_issue_is_added_to_selected_project():
    target = Target(
        id="github",
        provider="github",
        label="Board",
        organisation="skyhaven-ltd",
        container="infra-homelab-config",
        item_types=("Feature",),
        project_id="PVT_board",
        template="template",
        template_mappings={"Feature": ".github/ISSUE_TEMPLATE/feature-request.md"},
    )
    responses = [
        Response(
            {
                "content": base64.b64encode(
                    b'---\nname: Feature request\ntitle: "[FEATURE] - Placeholder"\n'
                    b"type: Feature\nassignees: liam-goodchild\n---\nTemplate\n"
                ).decode()
            }
        ),
        Response([{"name": "portal"}]),
        Response(
            {
                "html_url": "https://github.test/issues/12",
                "number": 12,
                "node_id": "I_issue",
            }
        ),
        Response([{"name": "Feature", "node_id": "IT_feature"}]),
        Response({"data": {"updateIssueIssueType": {"issue": {"id": "I_issue"}}}}),
        Response({"data": {"addProjectV2ItemById": {"item": {"id": "PVTI_1"}}}}),
    ]
    with patch("urllib.request.urlopen", side_effect=responses) as urlopen:
        result = submit(settings(), target, draft())

    assert result.url == "https://github.test/issues/12"
    assert result.project_item_id == "PVTI_1"
    template_request = urlopen.call_args_list[0].args[0]
    labels_request = urlopen.call_args_list[1].args[0]
    issue_request = urlopen.call_args_list[2].args[0]
    type_request = urlopen.call_args_list[3].args[0]
    type_update_request = urlopen.call_args_list[4].args[0]
    project_request = urlopen.call_args_list[5].args[0]
    assert template_request.full_url.endswith(
        "/skyhaven-ltd/.github/contents/.github/ISSUE_TEMPLATE/feature-request.md?ref=main"
    )
    assert labels_request.full_url.endswith("/labels?per_page=100")
    assert issue_request.full_url.endswith("/skyhaven-ltd/infra-homelab-config/issues")
    issue_payload = json.loads(issue_request.data)
    assert issue_payload["title"] == "[FEATURE] - A useful feature"
    assert issue_payload["assignees"] == ["liam-goodchild"]
    assert issue_payload["labels"] == ["portal"]
    assert issue_payload["body"] == "Description"
    assert type_request.full_url.endswith(
        "/skyhaven-ltd/infra-homelab-config/issue-types"
    )
    type_payload = json.loads(type_update_request.data)
    assert type_payload["variables"] == {"issue": "I_issue", "type": "IT_feature"}
    project_payload = json.loads(project_request.data)
    assert project_payload["variables"] == {
        "project": "PVT_board",
        "item": "I_issue",
    }


def test_template_metadata_and_title_prefix_are_idempotent():
    template = _parse_issue_template(
        '---\ntitle: "[FEATURE] - Placeholder"\ntype: Feature\nassignees:\n---\n'
    )
    assert template.prefix == "[FEATURE] - "
    assert template.issue_type == "Feature"
    assert _normalise_title("[FEATURE] - [FEATURE] - Useful", template.prefix) == (
        "[FEATURE] - Useful"
    )


def test_github_repositories_are_discovered_dynamically():
    responses = [
        Response(
            [
                {
                    "name": "active-repo",
                    "html_url": "https://github.test/active-repo",
                    "has_issues": True,
                    "archived": False,
                },
                {
                    "name": "archived-repo",
                    "html_url": "https://github.test/archived-repo",
                    "has_issues": True,
                    "archived": True,
                },
            ]
        )
    ]
    with patch("urllib.request.urlopen", side_effect=responses) as urlopen:
        values = list_destinations(settings(), "github")
    assert values == [
        {
            "id": "github:active-repo",
            "name": "active-repo",
            "url": "https://github.test/active-repo",
        }
    ]
    assert "/orgs/skyhaven-ltd/repos?" in urlopen.call_args.args[0].full_url


def test_azure_devops_uses_configured_org_project_and_fields():
    target = Target(
        id="ado",
        provider="azure_devops",
        label="Platform",
        organisation="skyhaven",
        container="Platform Project",
        item_types=("Feature",),
        project_id="",
        template="template",
        template_mappings={"Feature": ".github/ADO_WORK_ITEM_TEMPLATE/feature.md"},
    )
    responses = [
        Response(
            {
                "content": base64.b64encode(
                    b"# Feature\n\n## Problem\nDescribe the problem."
                ).decode()
            }
        ),
        Response({"id": 42, "_links": {"html": {"href": "https://ado.test/items/42"}}}),
    ]
    with patch("urllib.request.urlopen", side_effect=responses) as urlopen:
        result = submit(settings(), target, draft())

    assert result.external_id == "42"
    template_request = urlopen.call_args_list[0].args[0]
    request = urlopen.call_args_list[1].args[0]
    assert template_request.full_url.endswith(
        "/skyhaven-ltd/.github/contents/.github/ADO_WORK_ITEM_TEMPLATE/feature.md?ref=main"
    )
    assert "/skyhaven/Platform%20Project/" in request.full_url
    operations = json.loads(request.data)
    description = next(
        operation["value"]
        for operation in operations
        if operation["path"] == "/fields/System.Description"
    )
    assert description == "Description"
    assert any(
        operation["path"] == "/fields/Microsoft.VSTS.Common.AcceptanceCriteria"
        for operation in operations
    )

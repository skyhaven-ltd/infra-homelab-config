import base64
import json
from unittest.mock import patch

from app.config import Settings, Target
from app.models import Draft
from app.providers import _normalise_title, _parse_issue_template, submit


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
        template_mappings={
            "Feature": ".github/ISSUE_TEMPLATE/feature-request.md"
        },
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
    assert "## Item type\n\nFeature" in issue_payload["body"]
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
    )
    response = Response(
        {"id": 42, "_links": {"html": {"href": "https://ado.test/items/42"}}}
    )
    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = submit(settings(), target, draft())

    assert result.external_id == "42"
    request = urlopen.call_args.args[0]
    assert "/skyhaven/Platform%20Project/" in request.full_url
    operations = json.loads(request.data)
    assert any(
        operation["path"] == "/fields/Microsoft.VSTS.Common.AcceptanceCriteria"
        for operation in operations
    )

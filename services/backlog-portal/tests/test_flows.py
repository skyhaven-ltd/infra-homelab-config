import json
from unittest.mock import patch

from app.models import AuditEvent, Draft
from app.providers import SubmissionError, SubmittedItem


def create_draft(client, auth):
    return client.post(
        "/drafts",
        auth=auth,
        data={
            "target_id": "github-infra",
            "item_type": "Feature",
            "raw_idea": "Create a small portal that captures backlog ideas.",
        },
        follow_redirects=False,
    )


def test_health_does_not_require_login(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/").status_code == 401


def test_intake_is_provider_first_and_has_no_type_control(client, auth):
    html = client.get("/", auth=auth).text
    assert html.index("GitHub") < html.index("Azure DevOps")
    assert 'name="provider"' in html
    assert 'name="item_type"' not in html
    assert "/api/destinations/${provider}" in html
    assert "Loading repositories" in html


def test_dynamic_destinations_require_portal_login(client, auth):
    assert client.get("/api/destinations/github").status_code == 401
    with patch(
        "app.main.providers.list_destinations",
        return_value=[
            {
                "id": "github:infra-homelab-config",
                "name": "infra-homelab-config",
                "url": "https://github.test/infra-homelab-config",
            }
        ],
    ):
        response = client.get("/api/destinations/github", auth=auth)
    assert response.json()["destinations"][0]["name"] == "infra-homelab-config"


def test_submitted_item_link_has_non_overlapping_layout(client, auth):
    css = client.get("/static/app.css", auth=auth).text
    assert ".success .button" in css
    assert "display: inline-block" in css


def test_draft_is_refined_by_worker_then_submitted(client, auth):
    response = create_draft(client, auth)
    assert response.status_code == 303
    assert response.headers["location"] == "/drafts/1"

    worker_headers = {"Authorization": "Bearer worker-secret"}
    claimed = client.post("/worker/jobs/claim", headers=worker_headers).json()["job"]
    assert claimed["draft_id"] == 1
    assert "rough backlog idea" in claimed["prompt"]
    assert "Use the infrastructure template" in claimed["prompt"]

    output = json.dumps(
        {
            "item_type": "Feature",
            "title": "Add backlog intake portal",
            "description": "Provide a focused interface for capturing ideas.",
            "acceptance_criteria": ["A user can review a generated draft"],
            "priority": "2",
            "area": "",
            "iteration": "",
            "labels": ["ai-queue"],
            "assignee": "",
        }
    )
    completed = client.post(
        f"/worker/jobs/{claimed['id']}/complete",
        headers=worker_headers,
        json={"raw_output": output},
    )
    assert completed.status_code == 200
    assert "Add backlog intake portal" in client.get("/drafts/1", auth=auth).text

    with patch(
        "app.main.providers.submit",
        return_value=SubmittedItem("https://github.test/issues/1", "1"),
    ):
        submitted = client.post(
            "/drafts/1/submit",
            auth=auth,
            data={
                "item_type": "Feature",
                "title": "Add backlog intake portal",
                "description": "Provide a focused interface.",
            },
            follow_redirects=False,
        )
    assert submitted.status_code == 303

    from app.database import SessionLocal

    with SessionLocal() as db:
        assert db.get(Draft, 1).state == "submitted"
        actions = [event.action for event in db.query(AuditEvent).all()]
    assert actions == [
        "draft.queued",
        "ai.claimed",
        "classification.completed",
        "ai.completed",
        "provider.submitted",
    ]


def test_every_idea_is_queued_without_keyword_rules(client, auth):
    first = client.post(
        "/drafts",
        auth=auth,
        data={"target_id": "github-infra", "raw_idea": "Set the ADO PAT safely"},
        follow_redirects=False,
    )
    second = client.post(
        "/drafts",
        auth=auth,
        data={"target_id": "github-infra", "raw_idea": "Consider this idea later"},
        follow_redirects=False,
    )
    assert first.status_code == second.status_code == 303

    from app.database import SessionLocal

    with SessionLocal() as db:
        drafts = db.query(Draft).order_by(Draft.id).all()
        assert [draft.state for draft in drafts] == ["queued", "queued"]
        assert (
            db.query(AuditEvent).filter_by(action="classification.completed").count()
            == 0
        )


def test_dynamic_destination_draft_can_be_claimed(client, auth):
    response = client.post(
        "/drafts",
        auth=auth,
        data={
            "target_id": "github:new-repository",
            "raw_idea": "Prepare this unstructured but sufficiently long request",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    claimed = client.post(
        "/worker/jobs/claim",
        headers={"Authorization": "Bearer worker-secret"},
    ).json()["job"]
    assert "skyhaven-ltd / new-repository" in claimed["prompt"]
    assert "Choose exactly one item type" in claimed["prompt"]


def test_invalid_worker_type_uses_valid_fallback_and_remains_editable(client, auth):
    response = client.post(
        "/drafts",
        auth=auth,
        data={"target_id": "github-infra", "raw_idea": "Set the ADO PAT safely"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    headers = {"Authorization": "Bearer worker-secret"}
    job = client.post("/worker/jobs/claim", headers=headers).json()["job"]
    output = json.dumps(
        {
            "item_type": "Unexpected type",
            "title": "Set the ADO PAT",
            "description": "Configure the server-side credential.",
            "acceptance_criteria": ["The project list loads"],
            "priority": "",
            "area": "",
            "iteration": "",
            "labels": [],
            "assignee": "",
        }
    )
    completed = client.post(
        f"/worker/jobs/{job['id']}/complete",
        headers=headers,
        json={"raw_output": output},
    )
    assert completed.status_code == 200

    from app.database import SessionLocal

    with SessionLocal() as db:
        draft = db.get(Draft, 1)
        assert draft.state == "review"
        assert draft.item_type in {"Bug", "Feature", "Task"}
        event = db.query(AuditEvent).filter_by(action="classification.completed").one()
        assert "source=fallback" in event.detail
    review = client.get("/drafts/1", auth=auth).text
    assert 'select name="item_type"' in review


def test_missing_template_mapping_does_not_block_refinement(client, auth, monkeypatch):
    from dataclasses import replace

    from app import main

    target = main.settings.targets[0]
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            targets=(
                replace(target, template_mappings={}),
                *main.settings.targets[1:],
            ),
        ),
    )
    response = client.post(
        "/drafts",
        auth=auth,
        data={"target_id": target.id, "raw_idea": "Fix the broken portal error"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    review = client.get(response.headers["location"], auth=auth)
    assert "Refining your idea" in review.text


def test_submitted_draft_cannot_create_a_duplicate(client, auth):
    from app.database import SessionLocal

    with SessionLocal() as db:
        draft = Draft(
            target_id="github-infra",
            item_type="Task",
            raw_idea="A sufficiently detailed idea",
            title="Existing item",
            description="Already submitted.",
            state="submitted",
            remote_url="https://github.test/issues/1",
        )
        db.add(draft)
        db.commit()
        draft_id = draft.id

    with patch("app.main.providers.submit") as submit:
        response = client.post(
            f"/drafts/{draft_id}/submit",
            auth=auth,
            data={
                "item_type": "Task",
                "title": "Existing item",
                "description": "Already submitted.",
            },
        )
    assert response.status_code == 409
    submit.assert_not_called()


def test_rejects_unknown_target_and_worker_token(client, auth):
    response = client.post(
        "/drafts",
        auth=auth,
        data={"target_id": "evil", "item_type": "Bug", "raw_idea": "Long enough idea"},
    )
    assert response.status_code == 400
    assert client.post("/worker/jobs/claim").status_code == 401


def test_provider_error_returns_review_page(client, auth):
    from app.database import SessionLocal

    with SessionLocal() as db:
        draft = Draft(
            target_id="github-infra",
            item_type="Bug",
            raw_idea="A sufficiently detailed failing idea",
            title="Broken workflow",
            description="The workflow is broken.",
            state="review",
        )
        db.add(draft)
        db.commit()
        draft_id = draft.id

    with patch(
        "app.main.providers.submit",
        side_effect=SubmissionError("GitHub rejected the request"),
    ):
        response = client.post(
            f"/drafts/{draft_id}/submit",
            auth=auth,
            data={
                "item_type": "Bug",
                "title": "Broken workflow",
                "description": "It is broken.",
            },
        )

    assert response.status_code == 502
    assert "GitHub rejected the request" in response.text
    with SessionLocal() as db:
        assert db.get(Draft, draft_id).state == "review"
        assert db.query(AuditEvent).filter_by(action="provider.failed").count() == 1


def test_delete_closes_remote_item_and_is_idempotent(client, auth):
    from app.database import SessionLocal

    with SessionLocal() as db:
        draft = Draft(
            target_id="github-infra",
            item_type="Bug",
            raw_idea="Remove the broken queued item",
            state="submitted",
            remote_url="https://github.test/issues/12",
            remote_external_id="12",
        )
        db.add(draft)
        db.commit()
        draft_id = draft.id

    with patch("app.main.providers.close") as close:
        response = client.post(
            f"/drafts/{draft_id}/delete", auth=auth, follow_redirects=False
        )
        retry = client.post(
            f"/drafts/{draft_id}/delete", auth=auth, follow_redirects=False
        )

    assert response.status_code == retry.status_code == 303
    close.assert_called_once()
    with SessionLocal() as db:
        assert db.get(Draft, draft_id).state == "deleted"
    assert "Remove the broken queued item" not in client.get("/", auth=auth).text


def test_delete_failure_is_recoverable_and_does_not_leak_details(client, auth):
    from app.database import SessionLocal

    with SessionLocal() as db:
        draft = Draft(
            target_id="github-infra",
            item_type="Bug",
            raw_idea="Remove the broken queued item",
            state="submitted",
            remote_external_id="12",
        )
        db.add(draft)
        db.commit()
        draft_id = draft.id

    with patch(
        "app.main.providers.close",
        side_effect=SubmissionError("Provider response contained sensitive detail"),
    ):
        response = client.post(f"/drafts/{draft_id}/delete", auth=auth)

    assert response.status_code == 502
    assert "sensitive detail" not in response.text
    assert "Retry the removal" in response.text
    with SessionLocal() as db:
        assert db.get(Draft, draft_id).state == "sync-failed"


def test_reconcile_reflects_external_resolution_once(client):
    from app.database import SessionLocal

    with SessionLocal() as db:
        draft = Draft(
            target_id="github-infra",
            item_type="Feature",
            raw_idea="A remotely resolved feature",
            state="submitted",
            remote_external_id="13",
        )
        db.add(draft)
        db.commit()
        draft_id = draft.id

    headers = {"Authorization": "Bearer worker-secret"}
    with patch("app.main.providers.is_closed", return_value=True) as is_closed:
        first = client.post("/worker/reconcile", headers=headers)
        second = client.post("/worker/reconcile", headers=headers)

    assert first.json() == {"reconciled": 1}
    assert second.json() == {"reconciled": 0}
    is_closed.assert_called_once()
    with SessionLocal() as db:
        assert db.get(Draft, draft_id).state == "resolved"

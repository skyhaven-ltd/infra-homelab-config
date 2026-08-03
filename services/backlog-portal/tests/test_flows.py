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
        "classification.completed",
        "draft.queued",
        "ai.claimed",
        "ai.completed",
        "provider.submitted",
    ]


def test_missing_type_is_inferred_deterministically_and_retry_is_safe(client, auth):
    first = client.post(
        "/drafts",
        auth=auth,
        data={"target_id": "github-infra", "raw_idea": "Fix the broken workflow error"},
        follow_redirects=False,
    )
    second = client.post(
        "/drafts",
        auth=auth,
        data={"target_id": "github-infra", "raw_idea": "Fix the broken workflow error"},
        follow_redirects=False,
    )
    assert first.status_code == second.status_code == 303

    from app.database import SessionLocal

    with SessionLocal() as db:
        drafts = db.query(Draft).order_by(Draft.id).all()
        assert [draft.item_type for draft in drafts] == ["Bug", "Bug"]
        events = db.query(AuditEvent).filter_by(action="classification.completed").all()
        assert all("source=inferred" in event.detail for event in events)


def test_explicit_type_wins_and_ambiguous_idea_uses_documented_fallback(client, auth):
    explicit = client.post(
        "/drafts",
        auth=auth,
        data={
            "target_id": "github-infra",
            "item_type": "Feature",
            "raw_idea": "Fix the broken workflow error",
        },
        follow_redirects=False,
    )
    fallback = client.post(
        "/drafts",
        auth=auth,
        data={"target_id": "github-infra", "raw_idea": "Consider this idea later"},
        follow_redirects=False,
    )
    assert explicit.status_code == fallback.status_code == 303

    from app.database import SessionLocal

    with SessionLocal() as db:
        drafts = db.query(Draft).order_by(Draft.id).all()
        assert [draft.item_type for draft in drafts] == ["Feature", "Task"]
        details = [
            event.detail
            for event in db.query(AuditEvent)
            .filter_by(action="classification.completed")
            .order_by(AuditEvent.id)
        ]
        assert "source=explicit" in details[0]
        assert "source=fallback" in details[1]


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
            data={"title": "Existing item", "description": "Already submitted."},
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
            data={"title": "Broken workflow", "description": "It is broken."},
        )

    assert response.status_code == 502
    assert "GitHub rejected the request" in response.text
    with SessionLocal() as db:
        assert db.get(Draft, draft_id).state == "review"
        assert db.query(AuditEvent).filter_by(action="provider.failed").count() == 1

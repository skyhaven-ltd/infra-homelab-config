import json
from unittest.mock import patch

from app.models import AuditEvent, Draft
from app.providers import SubmittedItem


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
        "draft.queued",
        "ai.claimed",
        "ai.completed",
        "provider.submitted",
    ]


def test_rejects_unknown_target_and_worker_token(client, auth):
    response = client.post(
        "/drafts",
        auth=auth,
        data={"target_id": "evil", "item_type": "Bug", "raw_idea": "Long enough idea"},
    )
    assert response.status_code == 400
    assert client.post("/worker/jobs/claim").status_code == 401

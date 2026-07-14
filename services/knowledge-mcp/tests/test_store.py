from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from knowledge_mcp.models import MemoryInput
from knowledge_mcp.store import KnowledgeStore


def make_record(**overrides: object) -> MemoryInput:
    values: dict[str, object] = {
        "canonical_key": "skyhaven/homelab:decision:gitops-owner",
        "kind": "decision",
        "scope": "skyhaven/infra-homelab-config",
        "title": "Argo CD owns Kubernetes resources",
        "summary": "Argo CD exclusively applies Kubernetes resources after cluster bootstrap.",
        "detail": (
            "After bootstrap, changes beneath kubernetes are reconciled by Argo CD rather than "
            "being applied manually from an operator workstation."
        ),
        "evidence": ["infra-homelab-config:docs/k8s-gitops-migration-plan.md"],
        "confidence": 1.0,
        "observed_at": datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return MemoryInput.model_validate(values)


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(tmp_path / "knowledge.db")


def test_upsert_is_idempotent(store: KnowledgeStore) -> None:
    record = make_record()
    first = store.upsert(
        record=record,
        idempotency_key="test-idempotency-key-0001",
        allow_similar_create=False,
    )
    second = store.upsert(
        record=record,
        idempotency_key="test-idempotency-key-0001",
        allow_similar_create=False,
    )

    assert first.outcome == "created"
    assert second == first


def test_reusing_idempotency_key_with_different_request_fails(store: KnowledgeStore) -> None:
    store.upsert(
        record=make_record(),
        idempotency_key="test-idempotency-key-0002",
        allow_similar_create=False,
    )

    with pytest.raises(ValueError, match="different request"):
        store.upsert(
            record=make_record(summary="A different durable summary with enough characters."),
            idempotency_key="test-idempotency-key-0002",
            allow_similar_create=False,
        )


def test_same_canonical_key_updates_and_retains_identity(store: KnowledgeStore) -> None:
    first = store.upsert(
        record=make_record(),
        idempotency_key="test-idempotency-key-0003",
        allow_similar_create=False,
    )
    updated = store.upsert(
        record=make_record(summary="Argo CD remains the sole GitOps reconciler after bootstrap."),
        idempotency_key="test-idempotency-key-0004",
        allow_similar_create=False,
    )

    assert updated.outcome == "updated"
    assert updated.memory_id == first.memory_id
    assert updated.version == 2


def test_identical_content_under_a_second_key_is_not_duplicated(store: KnowledgeStore) -> None:
    first = store.upsert(
        record=make_record(),
        idempotency_key="test-idempotency-key-0005",
        allow_similar_create=False,
    )
    duplicate = store.upsert(
        record=make_record(canonical_key="skyhaven/homelab:decision:argo-owner"),
        idempotency_key="test-idempotency-key-0006",
        allow_similar_create=False,
    )

    assert duplicate.outcome == "noop_exact_duplicate"
    assert duplicate.memory_id == first.memory_id


def test_similar_content_requires_review(store: KnowledgeStore) -> None:
    first = store.upsert(
        record=make_record(),
        idempotency_key="test-idempotency-key-0007",
        allow_similar_create=False,
    )
    conflict = store.upsert(
        record=make_record(
            canonical_key="skyhaven/homelab:convention:gitops-owner",
            summary=(
                "Argo CD exclusively applies Kubernetes resources after the initial bootstrap."
            ),
        ),
        idempotency_key="test-idempotency-key-0008",
        allow_similar_create=False,
    )

    assert conflict.outcome == "conflict_requires_review"
    assert conflict.similar_memory_id == first.memory_id


def test_recall_is_scoped_and_excludes_stale_and_expired_records(
    store: KnowledgeStore,
) -> None:
    active = store.upsert(
        record=make_record(),
        idempotency_key="test-idempotency-key-0009",
        allow_similar_create=False,
    )
    stale = store.upsert(
        record=make_record(
            canonical_key="skyhaven/homelab:lesson:manual-kubectl",
            title="Manual kubectl caused configuration drift",
            summary="Manual kubectl changes caused configuration drift from the Git repository.",
            detail="A manual cluster change was reverted because Argo CD reconciled Git state.",
        ),
        idempotency_key="test-idempotency-key-0010",
        allow_similar_create=True,
    )
    store.mark(
        memory_id=stale.memory_id,
        status="stale",
        reason="The lesson was intentionally retired during this test.",
        evidence=["test-suite"],
    )
    store.upsert(
        record=make_record(
            canonical_key="skyhaven/homelab:environment:expired",
            kind="environment_fact",
            title="Expired Argo CD environment fact",
            summary="Argo CD had an old temporary configuration that has now expired.",
            detail="This deliberately expired record verifies recall validity filtering.",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        ),
        idempotency_key="test-idempotency-key-0011",
        allow_similar_create=True,
    )

    recalled = store.recall(
        query="Argo CD Kubernetes",
        scopes=["skyhaven/infra-homelab-config"],
        kinds=None,
        max_results=5,
        max_chars=2_000,
    )

    assert [item.id for item in recalled.results] == [active.memory_id]


def test_get_respects_character_budget(store: KnowledgeStore) -> None:
    created = store.upsert(
        record=make_record(detail="x" * 1_000),
        idempotency_key="test-idempotency-key-0012",
        allow_similar_create=False,
    )

    response = store.get(memory_ids=[created.memory_id], max_chars=500)

    assert response.results == []
    assert response.truncated is True


def test_get_returns_records_and_missing_ids(store: KnowledgeStore) -> None:
    created = store.upsert(
        record=make_record(),
        idempotency_key="test-idempotency-key-0013",
        allow_similar_create=False,
    )

    response = store.get(memory_ids=[created.memory_id, "missing"], max_chars=5_000)

    assert response.results[0].id == created.memory_id
    assert response.missing_ids == ["missing"]
    assert store.get(memory_ids=[], max_chars=500).results == []


def test_recall_handles_no_terms_kind_filters_and_budgets(store: KnowledgeStore) -> None:
    store.upsert(
        record=make_record(),
        idempotency_key="test-idempotency-key-0014",
        allow_similar_create=False,
    )
    store.upsert(
        record=make_record(
            canonical_key="skyhaven/homelab:lesson:argo-reconciliation",
            kind="lesson",
            title="Argo reconciliation restores declared Kubernetes state",
            summary="Argo reconciliation restores Kubernetes resources to their declared state.",
            detail="Drift is reverted to the state declared by Git after reconciliation.",
        ),
        idempotency_key="test-idempotency-key-0015",
        allow_similar_create=True,
    )

    empty = store.recall(
        query="---",
        scopes=None,
        kinds=None,
        max_results=5,
        max_chars=2_000,
    )
    bounded = store.recall(
        query="Argo Kubernetes reconciliation",
        scopes=None,
        kinds=["lesson"],
        max_results=1,
        max_chars=20,
    )

    assert empty.results == []
    assert len(bounded.results) == 1
    assert bounded.results[0].kind == "lesson"
    assert bounded.truncated is True


def test_mark_is_idempotent_and_missing_memory_fails(store: KnowledgeStore) -> None:
    created = store.upsert(
        record=make_record(),
        idempotency_key="test-idempotency-key-0016",
        allow_similar_create=False,
    )

    first = store.mark(
        memory_id=created.memory_id,
        status="stale",
        reason="This record is no longer applicable to the current repository.",
        evidence=["test-suite"],
    )
    second = store.mark(
        memory_id=created.memory_id,
        status="stale",
        reason="This record remains stale after a second verification.",
        evidence=["test-suite"],
    )

    assert first.changed is True
    assert second.changed is False
    with pytest.raises(ValueError, match="memory not found"):
        store.mark(
            memory_id="missing",
            status="stale",
            reason="This missing record cannot be marked as stale.",
            evidence=["test-suite"],
        )


def test_new_memory_can_supersede_an_existing_memory(store: KnowledgeStore) -> None:
    previous = store.upsert(
        record=make_record(),
        idempotency_key="test-idempotency-key-0017",
        allow_similar_create=False,
    )
    replacement = store.upsert(
        record=make_record(
            canonical_key="skyhaven/homelab:decision:gitops-owner-v2",
            title="Flux owns Kubernetes resources",
            summary="Flux now exclusively applies Kubernetes resources after cluster bootstrap.",
            detail="The GitOps controller was deliberately migrated from Argo CD to Flux.",
            supersedes=previous.memory_id,
        ),
        idempotency_key="test-idempotency-key-0018",
        allow_similar_create=True,
    )

    previous_record = store.get(memory_ids=[previous.memory_id], max_chars=5_000).results[0]
    assert replacement.outcome == "created"
    assert previous_record.status == "superseded"


def test_invalid_supersedes_relationship_rolls_back(store: KnowledgeStore) -> None:
    with pytest.raises(ValueError, match="superseded memory not found"):
        store.upsert(
            record=make_record(supersedes="missing"),
            idempotency_key="test-idempotency-key-0019",
            allow_similar_create=False,
        )


def test_memory_input_requires_timezone_and_nonblank_evidence() -> None:
    with pytest.raises(ValueError, match="timezone"):
        make_record(observed_at=datetime(2026, 7, 14, 12, 0))
    with pytest.raises(ValueError, match="cannot be blank"):
        make_record(evidence=[" "])


@pytest.mark.parametrize(
    "secret",
    [
        "-----BEGIN OPENSSH PRIVATE KEY-----",  # gitleaks:allow - rejection fixture
        "ghp_abcdefghijklmnopqrstuvwxyz123456",  # gitleaks:allow - rejection fixture
        "sk-proj-abcdefghijklmnopqrstuvwxyz123456",  # gitleaks:allow - rejection fixture
        "tskey-auth-abcdefghijklmnopqrstuvwxyz123456",  # gitleaks:allow - rejection fixture
        "xoxb-abcdefghijklmnopqrstuvwxyz123456",
    ],
)
def test_upsert_rejects_obvious_secrets(store: KnowledgeStore, secret: str) -> None:
    with pytest.raises(ValueError, match="resembles a secret"):
        store.upsert(
            record=make_record(detail=f"This must never be stored: {secret}"),
            idempotency_key=f"secret-test-{secret[:16]}",
            allow_similar_create=False,
        )

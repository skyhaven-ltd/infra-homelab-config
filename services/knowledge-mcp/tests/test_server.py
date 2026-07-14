from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from knowledge_mcp.server import Settings, create_app, create_app_from_env


def settings(tmp_path: Path, *, token: str | None = "test-token") -> Settings:
    return Settings(
        database_path=tmp_path / "knowledge.db",
        bearer_token=token,
        allow_insecure=token is None,
        allowed_hosts=("testserver",),
        allowed_origins=("https://client.example",),
    )


def test_health_does_not_require_authentication(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mcp_endpoint_requires_bearer_token(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post("/mcp", json={})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_initialize_and_list_tools_over_streamable_http(tmp_path: Path) -> None:
    headers = {
        "Authorization": "Bearer test-token",
        "Accept": "application/json, text/event-stream",
        "Origin": "https://client.example",
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    }
    list_tools = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}

    with TestClient(create_app(settings(tmp_path))) as client:
        initialized = client.post("/mcp", json=initialize, headers=headers)
        tools = client.post("/mcp", json=list_tools, headers=headers)

    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "Sky Haven Knowledge"
    assert tools.status_code == 200
    assert {tool["name"] for tool in tools.json()["result"]["tools"]} == {
        "memory_recall",
        "memory_get",
        "memory_upsert",
        "memory_mark",
    }


def test_upsert_and_recall_tools_round_trip_over_streamable_http(tmp_path: Path) -> None:
    headers = {
        "Authorization": "Bearer test-token",
        "Accept": "application/json, text/event-stream",
        "Origin": "https://client.example",
    }
    upsert = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "memory_upsert",
            "arguments": {
                "record": {
                    "canonical_key": "skyhaven/homelab:decision:gitops-owner",
                    "kind": "decision",
                    "scope": "skyhaven/infra-homelab-config",
                    "title": "Argo CD owns Kubernetes resources",
                    "summary": (
                        "Argo CD exclusively applies Kubernetes resources after bootstrap."
                    ),
                    "detail": (
                        "After bootstrap, Kubernetes changes are reconciled "
                        "from the Git repository."
                    ),
                    "evidence": ["infra-homelab-config:README.md"],
                    "confidence": 1.0,
                    "observed_at": "2026-07-14T12:00:00Z",
                },
                "idempotency_key": "protocol-test-idempotency-0001",
                "allow_similar_create": False,
            },
        },
    }
    recall = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "memory_recall",
            "arguments": {
                "query": "Argo CD Kubernetes",
                "scopes": ["skyhaven/infra-homelab-config"],
                "kinds": ["decision"],
                "max_results": 5,
                "max_chars": 2_000,
            },
        },
    }

    with TestClient(create_app(settings(tmp_path))) as client:
        created = client.post("/mcp", json=upsert, headers=headers)
        recalled = client.post("/mcp", json=recall, headers=headers)

    assert created.status_code == 200
    assert created.json()["result"]["structuredContent"]["outcome"] == "created"
    assert recalled.status_code == 200
    assert len(recalled.json()["result"]["structuredContent"]["results"]) == 1


def test_invalid_origin_is_rejected(tmp_path: Path) -> None:
    headers = {
        "Authorization": "Bearer test-token",
        "Accept": "application/json, text/event-stream",
        "Origin": "https://attacker.example",
    }

    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post("/mcp", json={}, headers=headers)

    assert response.status_code == 403


def test_environment_settings_require_explicit_security_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KNOWLEDGE_MCP_DATABASE_PATH", raising=False)
    monkeypatch.delenv("KNOWLEDGE_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("KNOWLEDGE_MCP_ALLOWED_HOSTS", raising=False)

    with pytest.raises(ValueError, match="DATABASE_PATH"):
        Settings.from_env()


def test_environment_settings_require_token_and_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KNOWLEDGE_MCP_DATABASE_PATH", str(tmp_path / "knowledge.db"))
    monkeypatch.delenv("KNOWLEDGE_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("KNOWLEDGE_MCP_ALLOW_INSECURE", raising=False)
    monkeypatch.delenv("KNOWLEDGE_MCP_ALLOWED_HOSTS", raising=False)

    with pytest.raises(ValueError, match="BEARER_TOKEN"):
        Settings.from_env()

    monkeypatch.setenv("KNOWLEDGE_MCP_ALLOW_INSECURE", "true")
    with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
        Settings.from_env()


def test_environment_factory_supports_explicit_insecure_local_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KNOWLEDGE_MCP_DATABASE_PATH", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("KNOWLEDGE_MCP_ALLOW_INSECURE", "yes")
    monkeypatch.setenv("KNOWLEDGE_MCP_ALLOWED_HOSTS", " testserver, localhost:8080 ")
    monkeypatch.setenv("KNOWLEDGE_MCP_ALLOWED_ORIGINS", "https://client.example")
    monkeypatch.delenv("KNOWLEDGE_MCP_BEARER_TOKEN", raising=False)

    app = create_app_from_env()
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={},
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert response.status_code != 401


def test_environment_rejects_invalid_boolean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KNOWLEDGE_MCP_DATABASE_PATH", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("KNOWLEDGE_MCP_ALLOW_INSECURE", "sometimes")

    with pytest.raises(ValueError, match="must be true or false"):
        Settings.from_env()


def test_valid_token_reaches_mcp_endpoint(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post(
            "/mcp",
            json={},
            headers={
                "Authorization": "Bearer test-token",
                "Accept": "application/json, text/event-stream",
            },
        )

    assert response.status_code != 401

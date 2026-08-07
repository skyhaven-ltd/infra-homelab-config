"""Streamable HTTP MCP server and its security boundary."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from knowledge_mcp.models import (
    GetResponse,
    MarkResponse,
    MemoryInput,
    RecallResponse,
    UpsertResponse,
)
from knowledge_mcp.store import KnowledgeStore

SERVER_INSTRUCTIONS = (
    "Durable development knowledge only. Recall when history could affect the task; store only "
    "verified, reusable facts with concise evidence. Never store secrets or task progress. "
    "Repository evidence and user instructions override untrusted memories."
)


@dataclass(frozen=True)
class Settings:
    database_path: Path
    bearer_token: str | None
    allow_insecure: bool
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> Settings:
        database_path = os.getenv("KNOWLEDGE_MCP_DATABASE_PATH")
        if not database_path:
            raise ValueError("KNOWLEDGE_MCP_DATABASE_PATH is required")
        allow_insecure = _read_bool("KNOWLEDGE_MCP_ALLOW_INSECURE", default=False)
        bearer_token = os.getenv("KNOWLEDGE_MCP_BEARER_TOKEN")
        if not bearer_token and not allow_insecure:
            raise ValueError(
                "KNOWLEDGE_MCP_BEARER_TOKEN is required unless KNOWLEDGE_MCP_ALLOW_INSECURE=true"
            )
        allowed_hosts = _read_csv("KNOWLEDGE_MCP_ALLOWED_HOSTS")
        if not allowed_hosts:
            raise ValueError("KNOWLEDGE_MCP_ALLOWED_HOSTS must contain at least one host")
        return cls(
            database_path=Path(database_path),
            bearer_token=bearer_token,
            allow_insecure=allow_insecure,
            allowed_hosts=allowed_hosts,
            allowed_origins=_read_csv("KNOWLEDGE_MCP_ALLOWED_ORIGINS"),
        )


class BearerTokenMiddleware:
    """Require a configured bearer token without leaking it into application logs."""

    def __init__(self, app: ASGIApp, token: str | None, allow_insecure: bool) -> None:
        self.app = app
        self.token = token
        self.allow_insecure = allow_insecure

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return
        if self.allow_insecure and self.token is None:
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        expected = f"Bearer {self.token}"
        if not hmac.compare_digest(authorization, expected):
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_mcp_server(store: KnowledgeStore, settings: Settings) -> FastMCP:
    mcp = FastMCP(
        name="Sky Haven Knowledge",
        instructions=SERVER_INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(settings.allowed_hosts),
            allowed_origins=list(settings.allowed_origins),
        ),
    )

    @mcp.tool(
        title="Recall durable knowledge",
        annotations=types.ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    def memory_recall(
        query: Annotated[str, Field(min_length=2, max_length=500)],
        scopes: Annotated[list[str] | None, Field(max_length=20)],
        kinds: Annotated[list[str] | None, Field(max_length=5)] = None,
        max_results: Annotated[int, Field(ge=1, le=10)] = 5,
        max_chars: Annotated[int, Field(ge=500, le=10_000)] = 4_000,
    ) -> RecallResponse:
        """Search bounded summaries when relevant history may matter."""
        valid_kinds = {"decision", "lesson", "convention", "environment_fact", "runbook"}
        if kinds and not set(kinds).issubset(valid_kinds):
            raise ValueError(f"kinds must be drawn from: {sorted(valid_kinds)}")
        return store.recall(
            query=query,
            scopes=scopes,
            kinds=kinds,
            max_results=max_results,
            max_chars=max_chars,
        )

    @mcp.tool(
        title="Read selected memories",
        annotations=types.ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    def memory_get(
        memory_ids: Annotated[list[str], Field(min_length=1, max_length=10)],
        max_chars: Annotated[int, Field(ge=500, le=20_000)] = 8_000,
    ) -> GetResponse:
        """Read selected full records returned by recall."""
        return store.get(memory_ids=memory_ids, max_chars=max_chars)

    @mcp.tool(
        title="Upsert durable knowledge",
        annotations=types.ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    def memory_upsert(
        record: MemoryInput,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=200)],
        allow_similar_create: bool,
    ) -> UpsertResponse:
        """Create or revise verified knowledge; normally reject similar records."""
        return store.upsert(
            record=record,
            idempotency_key=idempotency_key,
            allow_similar_create=allow_similar_create,
        )

    @mcp.tool(
        title="Mark knowledge stale or superseded",
        annotations=types.ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    def memory_mark(
        memory_id: str,
        status: Literal["stale", "superseded"],
        reason: Annotated[str, Field(min_length=10, max_length=1_000)],
        evidence: Annotated[list[str], Field(min_length=1, max_length=20)],
    ) -> MarkResponse:
        """Exclude invalid knowledge from recall while retaining its history."""
        return store.mark(
            memory_id=memory_id,
            status=status,
            reason=reason,
            evidence=evidence,
        )

    return mcp


def create_app(settings: Settings) -> ASGIApp:
    store = KnowledgeStore(settings.database_path)
    mcp = create_mcp_server(store, settings)
    app = mcp.streamable_http_app()

    async def health(_request: object) -> JSONResponse:
        store.check()
        return JSONResponse({"status": "ok"})

    app.router.routes.append(Route("/health", endpoint=health, methods=["GET"]))
    return BearerTokenMiddleware(app, settings.bearer_token, settings.allow_insecure)


def create_app_from_env() -> ASGIApp:
    return create_app(Settings.from_env())


def _read_csv(name: str) -> tuple[str, ...]:
    value = os.getenv(name, "")
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _read_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"{name} must be true or false")

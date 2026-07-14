"""Validated inputs and structured MCP tool results."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MemoryKind = Literal["decision", "lesson", "convention", "environment_fact", "runbook"]
MemoryStatus = Literal["active", "stale", "superseded"]


class MemoryInput(BaseModel):
    """A durable, evidenced piece of knowledge proposed by an agent."""

    canonical_key: str = Field(min_length=3, max_length=240)
    kind: MemoryKind
    scope: str = Field(min_length=2, max_length=240)
    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(min_length=10, max_length=1_500)
    detail: str = Field(min_length=10, max_length=12_000)
    evidence: list[str] = Field(min_length=1, max_length=20)
    confidence: float = Field(ge=0, le=1)
    observed_at: datetime
    expires_at: datetime | None = None
    supersedes: str | None = None

    @field_validator("observed_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value

    @field_validator("evidence")
    @classmethod
    def reject_blank_evidence(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("evidence entries cannot be blank")
        return values


class MemoryRecord(BaseModel):
    id: str
    canonical_key: str
    kind: MemoryKind
    scope: str
    title: str
    summary: str
    detail: str
    evidence: list[str]
    confidence: float
    observed_at: str
    expires_at: str | None
    status: MemoryStatus
    supersedes: str | None
    content_hash: str
    version: int
    created_at: str
    updated_at: str


class RecallItem(BaseModel):
    id: str
    canonical_key: str
    kind: MemoryKind
    scope: str
    title: str
    summary: str
    confidence: float
    observed_at: str
    expires_at: str | None
    relevance: float


class RecallResponse(BaseModel):
    query: str
    results: list[RecallItem]
    returned_chars: int
    truncated: bool


class GetResponse(BaseModel):
    results: list[MemoryRecord]
    missing_ids: list[str]
    returned_chars: int
    truncated: bool


class UpsertResponse(BaseModel):
    outcome: Literal[
        "created",
        "updated",
        "noop_exact_duplicate",
        "conflict_requires_review",
    ]
    memory_id: str
    version: int
    message: str
    similar_memory_id: str | None = None
    similarity: float | None = None


class MarkResponse(BaseModel):
    memory_id: str
    status: Literal["stale", "superseded"]
    changed: bool

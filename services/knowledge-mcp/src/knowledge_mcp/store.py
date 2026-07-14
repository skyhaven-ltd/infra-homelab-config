"""SQLite persistence, full-text recall, and deterministic deduplication."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from knowledge_mcp.models import (
    GetResponse,
    MarkResponse,
    MemoryInput,
    MemoryRecord,
    RecallItem,
    RecallResponse,
    UpsertResponse,
)

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*")
_SIMILARITY_THRESHOLD = 0.88
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\btskey-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
)


class KnowledgeStore:
    """Own the knowledge database and all consistency rules."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = NORMAL;

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    canonical_key TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (
                        kind IN ('decision', 'lesson', 'convention', 'environment_fact', 'runbook')
                    ),
                    scope TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
                    observed_at TEXT NOT NULL,
                    expires_at TEXT,
                    status TEXT NOT NULL CHECK (status IN ('active', 'stale', 'superseded')),
                    supersedes TEXT REFERENCES memories(id),
                    content_hash TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK (version >= 1),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(scope, canonical_key)
                );

                CREATE INDEX IF NOT EXISTS memories_content_hash_idx
                    ON memories(scope, content_hash);
                CREATE INDEX IF NOT EXISTS memories_status_idx
                    ON memories(status, expires_at);

                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    title,
                    summary,
                    detail,
                    canonical_key,
                    content='memories',
                    content_rowid='rowid',
                    tokenize='porter unicode61'
                );

                CREATE TRIGGER IF NOT EXISTS memories_fts_insert AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, title, summary, detail, canonical_key)
                    VALUES (new.rowid, new.title, new.summary, new.detail, new.canonical_key);
                END;

                CREATE TRIGGER IF NOT EXISTS memories_fts_delete AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(
                        memories_fts, rowid, title, summary, detail, canonical_key
                    ) VALUES (
                        'delete', old.rowid, old.title, old.summary, old.detail, old.canonical_key
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS memories_fts_update AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(
                        memories_fts, rowid, title, summary, detail, canonical_key
                    ) VALUES (
                        'delete', old.rowid, old.title, old.summary, old.detail, old.canonical_key
                    );
                    INSERT INTO memories_fts(rowid, title, summary, detail, canonical_key)
                    VALUES (new.rowid, new.title, new.summary, new.detail, new.canonical_key);
                END;

                CREATE TABLE IF NOT EXISTS memory_revisions (
                    memory_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    PRIMARY KEY(memory_id, version)
                );

                CREATE TABLE IF NOT EXISTS memory_events (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL REFERENCES memories(id),
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS idempotency_results (
                    idempotency_key TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def check(self) -> None:
        with self._connection() as connection:
            connection.execute("SELECT 1").fetchone()

    def recall(
        self,
        *,
        query: str,
        scopes: list[str] | None,
        kinds: list[str] | None,
        max_results: int,
        max_chars: int,
    ) -> RecallResponse:
        tokens = _TOKEN_PATTERN.findall(query)
        if not tokens:
            return RecallResponse(
                query=query,
                results=[],
                returned_chars=0,
                truncated=False,
            )

        match_expression = " OR ".join(
            f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens
        )
        conditions = [
            "memories.status = 'active'",
            "(memories.expires_at IS NULL OR memories.expires_at > ?)",
        ]
        parameters: list[Any] = [match_expression, _now()]
        if scopes:
            conditions.append(f"memories.scope IN ({_placeholders(scopes)})")
            parameters.extend(scopes)
        if kinds:
            conditions.append(f"memories.kind IN ({_placeholders(kinds)})")
            parameters.extend(kinds)
        parameters.append(max_results + 1)

        sql = f"""
            SELECT memories.*,
                   bm25(memories_fts, 4.0, 2.0, 1.0, 3.0) AS rank
            FROM memories_fts
            JOIN memories ON memories.rowid = memories_fts.rowid
            WHERE memories_fts MATCH ? AND {" AND ".join(conditions)}
            ORDER BY rank ASC, memories.updated_at DESC
            LIMIT ?
        """
        with self._connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()

        results: list[RecallItem] = []
        returned_chars = 0
        truncated = len(rows) > max_results
        for row in rows[:max_results]:
            remaining = max_chars - returned_chars
            if remaining <= 0:
                truncated = True
                break
            summary = row["summary"]
            if len(summary) > remaining:
                summary = summary[: max(0, remaining - 3)] + "..."
                truncated = True
            returned_chars += len(summary)
            rank = abs(float(row["rank"]))
            results.append(
                RecallItem(
                    id=row["id"],
                    canonical_key=row["canonical_key"],
                    kind=row["kind"],
                    scope=row["scope"],
                    title=row["title"],
                    summary=summary,
                    confidence=row["confidence"],
                    observed_at=row["observed_at"],
                    expires_at=row["expires_at"],
                    relevance=round(1 / (1 + rank), 4),
                )
            )
            if returned_chars >= max_chars:
                truncated = True
                break

        return RecallResponse(
            query=query,
            results=results,
            returned_chars=returned_chars,
            truncated=truncated,
        )

    def get(self, *, memory_ids: list[str], max_chars: int) -> GetResponse:
        if not memory_ids:
            return GetResponse(results=[], missing_ids=[], returned_chars=0, truncated=False)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM memories WHERE id IN ({_placeholders(memory_ids)})",
                memory_ids,
            ).fetchall()
        by_id = {row["id"]: row for row in rows}
        results: list[MemoryRecord] = []
        missing: list[str] = []
        returned_chars = 0
        truncated = False
        for memory_id in memory_ids:
            row = by_id.get(memory_id)
            if row is None:
                missing.append(memory_id)
                continue
            record = _row_to_record(row)
            record_chars = len(record.summary) + len(record.detail)
            if returned_chars + record_chars > max_chars:
                truncated = True
                break
            results.append(record)
            returned_chars += record_chars
        return GetResponse(
            results=results,
            missing_ids=missing,
            returned_chars=returned_chars,
            truncated=truncated,
        )

    def upsert(
        self,
        *,
        record: MemoryInput,
        idempotency_key: str,
        allow_similar_create: bool,
    ) -> UpsertResponse:
        _reject_obvious_secrets(record)
        request_payload = {
            "record": record.model_dump(mode="json"),
            "allow_similar_create": allow_similar_create,
        }
        request_hash = _hash_json(request_payload)
        content_hash = _content_hash(record)
        now = _now()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                """
                SELECT request_hash, response_json
                FROM idempotency_results
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if prior:
                if prior["request_hash"] != request_hash:
                    raise ValueError("idempotency_key was already used with a different request")
                connection.rollback()
                return UpsertResponse.model_validate_json(prior["response_json"])

            if record.supersedes:
                superseded = connection.execute(
                    "SELECT id FROM memories WHERE id = ?", (record.supersedes,)
                ).fetchone()
                if superseded is None:
                    raise ValueError(f"superseded memory not found: {record.supersedes}")

            exact = connection.execute(
                """
                SELECT * FROM memories
                WHERE scope = ? AND content_hash = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (record.scope, content_hash),
            ).fetchone()
            if exact:
                response = UpsertResponse(
                    outcome="noop_exact_duplicate",
                    memory_id=exact["id"],
                    version=exact["version"],
                    message="Identical durable knowledge already exists in this scope.",
                )
                self._save_idempotency(connection, idempotency_key, request_hash, response, now)
                connection.commit()
                return response

            existing = connection.execute(
                "SELECT * FROM memories WHERE scope = ? AND canonical_key = ?",
                (record.scope, record.canonical_key),
            ).fetchone()
            if existing:
                self._archive(connection, existing, now)
                version = int(existing["version"]) + 1
                self._update_memory(connection, existing["id"], record, content_hash, version, now)
                self._apply_supersedes(connection, existing["id"], record.supersedes, now)
                response = UpsertResponse(
                    outcome="updated",
                    memory_id=existing["id"],
                    version=version,
                    message="Updated the canonical memory and retained its previous revision.",
                )
                self._event(connection, existing["id"], "updated", {"version": version}, now)
                self._save_idempotency(connection, idempotency_key, request_hash, response, now)
                connection.commit()
                return response

            similar = self._find_similar(connection, record)
            if similar and not allow_similar_create:
                response = UpsertResponse(
                    outcome="conflict_requires_review",
                    memory_id=similar["id"],
                    version=similar["version"],
                    message=(
                        "A semantically similar memory exists. Update its canonical key "
                        "or explicitly allow a separate record after reviewing it."
                    ),
                    similar_memory_id=similar["id"],
                    similarity=similar["similarity"],
                )
                self._save_idempotency(connection, idempotency_key, request_hash, response, now)
                connection.commit()
                return response

            memory_id = str(uuid4())
            self._insert_memory(connection, memory_id, record, content_hash, now)
            self._apply_supersedes(connection, memory_id, record.supersedes, now)
            response = UpsertResponse(
                outcome="created",
                memory_id=memory_id,
                version=1,
                message="Created a new durable memory.",
            )
            self._event(connection, memory_id, "created", {"version": 1}, now)
            self._save_idempotency(connection, idempotency_key, request_hash, response, now)
            connection.commit()
            return response

    def mark(
        self,
        *,
        memory_id: str,
        status: Literal["stale", "superseded"],
        reason: str,
        evidence: list[str],
    ) -> MarkResponse:
        now = _now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                connection.rollback()
                raise ValueError(f"memory not found: {memory_id}")
            changed = row["status"] != status
            if changed:
                self._archive(connection, row, now)
                connection.execute(
                    """
                    UPDATE memories
                    SET status = ?, version = version + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, now, memory_id),
                )
            self._event(
                connection,
                memory_id,
                "marked",
                {"status": status, "reason": reason, "evidence": evidence},
                now,
            )
            connection.commit()
        return MarkResponse(memory_id=memory_id, status=status, changed=changed)

    def _find_similar(
        self, connection: sqlite3.Connection, record: MemoryInput
    ) -> dict[str, Any] | None:
        rows = connection.execute(
            """
            SELECT id, title, summary, version
            FROM memories
            WHERE scope = ? AND status = 'active'
            """,
            (record.scope,),
        ).fetchall()
        proposed = _normalize(f"{record.title} {record.summary}")
        best: dict[str, Any] | None = None
        for row in rows:
            candidate = _normalize(f"{row['title']} {row['summary']}")
            similarity = SequenceMatcher(None, proposed, candidate).ratio()
            if similarity >= _SIMILARITY_THRESHOLD and (
                best is None or similarity > best["similarity"]
            ):
                best = {
                    "id": row["id"],
                    "version": row["version"],
                    "similarity": round(similarity, 4),
                }
        return best

    @staticmethod
    def _insert_memory(
        connection: sqlite3.Connection,
        memory_id: str,
        record: MemoryInput,
        content_hash: str,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO memories (
                id, canonical_key, kind, scope, title, summary, detail, evidence_json,
                confidence, observed_at, expires_at, status, supersedes, content_hash,
                version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, 1, ?, ?)
            """,
            (
                memory_id,
                record.canonical_key,
                record.kind,
                record.scope,
                record.title,
                record.summary,
                record.detail,
                json.dumps(record.evidence, separators=(",", ":")),
                record.confidence,
                record.observed_at.isoformat(),
                record.expires_at.isoformat() if record.expires_at else None,
                record.supersedes,
                content_hash,
                now,
                now,
            ),
        )

    @staticmethod
    def _update_memory(
        connection: sqlite3.Connection,
        memory_id: str,
        record: MemoryInput,
        content_hash: str,
        version: int,
        now: str,
    ) -> None:
        connection.execute(
            """
            UPDATE memories SET
                kind = ?, title = ?, summary = ?, detail = ?, evidence_json = ?,
                confidence = ?, observed_at = ?, expires_at = ?, status = 'active',
                supersedes = ?, content_hash = ?, version = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                record.kind,
                record.title,
                record.summary,
                record.detail,
                json.dumps(record.evidence, separators=(",", ":")),
                record.confidence,
                record.observed_at.isoformat(),
                record.expires_at.isoformat() if record.expires_at else None,
                record.supersedes,
                content_hash,
                version,
                now,
                memory_id,
            ),
        )

    def _apply_supersedes(
        self,
        connection: sqlite3.Connection,
        memory_id: str,
        supersedes: str | None,
        now: str,
    ) -> None:
        if supersedes is None:
            return
        if supersedes == memory_id:
            raise ValueError("a memory cannot supersede itself")
        previous = connection.execute(
            "SELECT * FROM memories WHERE id = ?", (supersedes,)
        ).fetchone()
        if previous is None:
            raise ValueError(f"superseded memory not found: {supersedes}")
        if previous["status"] != "superseded":
            self._archive(connection, previous, now)
            connection.execute(
                """
                UPDATE memories
                SET status = 'superseded', version = version + 1, updated_at = ?
                WHERE id = ?
                """,
                (now, supersedes),
            )
            self._event(
                connection,
                supersedes,
                "superseded",
                {"superseded_by": memory_id},
                now,
            )

    @staticmethod
    def _archive(connection: sqlite3.Connection, row: sqlite3.Row, now: str) -> None:
        record = _row_to_record(row)
        connection.execute(
            """
            INSERT INTO memory_revisions(memory_id, version, record_json, archived_at)
            VALUES (?, ?, ?, ?)
            """,
            (row["id"], row["version"], record.model_dump_json(), now),
        )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        memory_id: str,
        event_type: str,
        payload: dict[str, Any],
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO memory_events(id, memory_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid4()), memory_id, event_type, json.dumps(payload), now),
        )

    @staticmethod
    def _save_idempotency(
        connection: sqlite3.Connection,
        idempotency_key: str,
        request_hash: str,
        response: UpsertResponse,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO idempotency_results(
                idempotency_key, request_hash, response_json, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (idempotency_key, request_hash, response.model_dump_json(), now),
        )


def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        canonical_key=row["canonical_key"],
        kind=row["kind"],
        scope=row["scope"],
        title=row["title"],
        summary=row["summary"],
        detail=row["detail"],
        evidence=json.loads(row["evidence_json"]),
        confidence=row["confidence"],
        observed_at=row["observed_at"],
        expires_at=row["expires_at"],
        status=row["status"],
        supersedes=row["supersedes"],
        content_hash=row["content_hash"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _content_hash(record: MemoryInput) -> str:
    content = record.model_dump(mode="json", exclude={"canonical_key", "scope", "supersedes"})
    return _hash_json(content)


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _placeholders(values: list[Any]) -> str:
    return ",".join("?" for _ in values)


def _reject_obvious_secrets(record: MemoryInput) -> None:
    searchable = "\n".join([record.title, record.summary, record.detail, *record.evidence])
    if any(pattern.search(searchable) for pattern in _SECRET_PATTERNS):
        raise ValueError("memory contains material that resembles a secret")

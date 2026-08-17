"""SQLite persistence layer for multi-session state.

Document model over SQLite: sessions are stored as JSON blobs; events have
real columns for indexed querying (session_id, seq, kind).

All DB work runs on a single-worker thread executor so operations serialize
naturally. WAL mode provides durable commits.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import typing as t
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

EVENT_PRUNE_TRIGGER = 2_000
EVENT_PRUNE_TARGET = 1_500
EVENT_REPLAY_LIMIT = 2_000
MAX_REPLAY_TEXT_BYTES = 256 * 1024
MAX_REPLAY_TOOL_ARGS_BYTES = 32 * 1024
MAX_TOOL_RESULT_CHARS = 2_000
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_ARTIFACTS_PER_SESSION = 100
MAX_ARTIFACT_STORAGE_PER_SESSION = 25 * 1024 * 1024
PRIVATE_DATABASE_FILE_MODE = 0o600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id   TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    ts         TEXT NOT NULL,
    payload    TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events (session_id, kind);
CREATE TABLE IF NOT EXISTS artifacts (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_seq  INTEGER NOT NULL,
    filename   TEXT NOT NULL,
    label      TEXT NOT NULL,
    path       TEXT NOT NULL,
    content    TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, event_seq),
    FOREIGN KEY (session_id, event_seq)
        REFERENCES events(session_id, seq) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_artifacts_session
    ON artifacts (session_id, event_seq);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _secure_database_files(path: str) -> None:
    """Restrict the SQLite database and any active sidecars to its owner."""
    for candidate in (path, f"{path}-wal", f"{path}-shm", f"{path}-journal"):
        try:
            if stat.S_ISLNK(os.lstat(candidate).st_mode):
                raise OSError(f"Refusing SQLite symlink: {candidate}")
            os.chmod(candidate, PRIVATE_DATABASE_FILE_MODE)
        except FileNotFoundError:
            continue


class Database:
    """Async wrapper over a single-threaded SQLite connection."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="al-db")
        self._conn: sqlite3.Connection | None = None

    async def connect(self) -> Database:
        """Open the database connection and initialize its schema."""
        try:
            await self._run(self._connect)
        except BaseException:
            self._executor.shutdown(wait=False)
            raise
        return self

    def _connect(self) -> None:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self._path, flags, PRIVATE_DATABASE_FILE_MODE)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, PRIVATE_DATABASE_FILE_MODE)
            else:
                os.chmod(self._path, PRIVATE_DATABASE_FILE_MODE)
        finally:
            os.close(fd)

        _secure_database_files(self._path)
        conn = sqlite3.connect(self._path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            _secure_database_files(self._path)
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_SCHEMA)
            self._conn = conn
            self._prune_all_events()
            self._migrate_inline_artifacts()
            conn.commit()
            _secure_database_files(self._path)
        except BaseException:
            self._conn = None
            conn.close()
            raise

    def _prune_all_events(self) -> None:
        """Apply current retention to sessions created by older versions."""
        rows = self._c.execute("SELECT DISTINCT session_id FROM events").fetchall()
        for row in rows:
            self._prune_events(str(row["session_id"]))

    def _migrate_inline_artifacts(self) -> None:
        """Move legacy inline artifact contents into bounded snapshot rows."""
        rows = self._c.execute(
            "SELECT session_id, seq, ts, payload FROM events "
            "WHERE kind='file_artifact' ORDER BY session_id, seq"
        ).fetchall()
        migrated_sessions: set[str] = set()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or payload.get("artifact_id"):
                continue
            content = payload.get("content")
            if not isinstance(content, str):
                continue

            session_id = str(row["session_id"])
            migrated_sessions.add(session_id)
            size_bytes = len(content.encode("utf-8"))
            if size_bytes > MAX_ARTIFACT_BYTES:
                self._c.execute(
                    "DELETE FROM events WHERE session_id=? AND seq=?",
                    (session_id, row["seq"]),
                )
                continue

            artifact_id = uuid.uuid4().hex
            filename = str(payload.get("filename") or "artifact.txt")
            label = str(payload.get("label") or filename)
            path = str(payload.get("path") or filename)
            payload.pop("content", None)
            payload.update(
                {
                    "artifact_id": artifact_id,
                    "filename": filename,
                    "label": label,
                    "path": path,
                    "size_bytes": size_bytes,
                }
            )
            self._c.execute(
                "UPDATE events SET payload=? WHERE session_id=? AND seq=?",
                (json.dumps(payload), session_id, row["seq"]),
            )
            self._c.execute(
                "INSERT INTO artifacts "
                "(id, session_id, event_seq, filename, label, path, content, size_bytes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    session_id,
                    row["seq"],
                    filename,
                    label,
                    path,
                    content,
                    size_bytes,
                    row["ts"],
                ),
            )

        for session_id in migrated_sessions:
            self._prune_artifacts(session_id)

    async def close(self) -> None:
        """Close the connection and stop the database executor."""
        await self._run(self._close)
        self._executor.shutdown(wait=True)

    def _close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def _run(self, fn: t.Callable[..., t.Any], *args: t.Any) -> t.Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn, *args)

    @property
    def _c(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected; call connect() first")
        return self._conn

    # --- sessions ----------------------------------------------------------

    async def upsert_session(self, session: dict[str, t.Any]) -> None:
        """Insert or replace a serialized session record."""
        await self._run(self._upsert_session, session)

    def _upsert_session(self, session: dict[str, t.Any]) -> None:
        sid = session["id"]
        self._c.execute(
            "INSERT INTO sessions (id, data) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (sid, json.dumps(session)),
        )
        self._c.commit()

    async def get_session(self, session_id: str) -> dict[str, t.Any] | None:
        """Return a session by ID, or ``None`` when it does not exist."""
        return await self._run(self._get_session, session_id)

    def _get_session(self, session_id: str) -> dict[str, t.Any] | None:
        row = self._c.execute(
            "SELECT data FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        return json.loads(row["data"]) if row else None

    async def list_sessions(self) -> list[dict[str, t.Any]]:
        """Return every stored session."""
        return await self._run(self._list_sessions)

    def _list_sessions(self) -> list[dict[str, t.Any]]:
        rows = self._c.execute("SELECT data FROM sessions").fetchall()
        return [json.loads(r["data"]) for r in rows]

    async def delete_session(self, session_id: str) -> None:
        """Delete a session and its associated events and thread state."""
        await self._run(self._delete_session, session_id)

    def _delete_session(self, session_id: str) -> None:
        self._c.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        self._c.execute("DELETE FROM events WHERE session_id=?", (session_id,))
        self._c.execute("DELETE FROM meta WHERE key=?", (f"thread:{session_id}",))
        self._c.commit()

    # --- events ------------------------------------------------------------

    async def append_event(
        self, session_id: str, kind: str, payload: dict[str, t.Any]
    ) -> int:
        """Append an event and return its per-session sequence number."""
        return await self._run(self._append_event, session_id, kind, payload)

    def _append_event(
        self, session_id: str, kind: str, payload: dict[str, t.Any]
    ) -> int:
        seq = self._insert_event(session_id, kind, payload)
        self._prune_events(session_id)
        self._c.commit()
        return seq

    def _insert_event(
        self, session_id: str, kind: str, payload: dict[str, t.Any]
    ) -> int:
        row = self._c.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM events WHERE session_id=?",
            (session_id,),
        ).fetchone()
        seq = int(row["next"])
        self._c.execute(
            "INSERT INTO events (session_id, seq, kind, ts, payload) VALUES (?, ?, ?, ?, ?)",
            (session_id, seq, kind, _utcnow(), json.dumps(payload)),
        )
        return seq

    def _prune_events(self, session_id: str) -> None:
        """Bound event history, preferring to retain complete user turns."""
        row = self._c.execute(
            "SELECT COUNT(*) AS count FROM events WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if int(row["count"]) <= EVENT_PRUNE_TRIGGER:
            return

        retained = self._c.execute(
            "SELECT seq FROM events WHERE session_id=? ORDER BY seq DESC LIMIT ?",
            (session_id, EVENT_PRUNE_TARGET),
        ).fetchall()
        if not retained:
            return

        candidate = int(retained[-1]["seq"])
        boundary = self._c.execute(
            "SELECT seq FROM events WHERE session_id=? "
            "AND kind='user_message' AND seq>=? ORDER BY seq LIMIT 1",
            (session_id, candidate),
        ).fetchone()
        cutoff = int(boundary["seq"]) if boundary is not None else candidate
        self._c.execute(
            "DELETE FROM events WHERE session_id=? AND seq<?",
            (session_id, cutoff),
        )

    async def get_events(
        self,
        session_id: str,
        kinds: t.Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, t.Any]]:
        """Return ordered events, optionally filtered by event kind."""
        return await self._run(self._get_events, session_id, kinds, limit)

    def _get_events(
        self,
        session_id: str,
        kinds: t.Sequence[str] | None,
        limit: int | None,
    ) -> list[dict[str, t.Any]]:
        if limit is not None and limit <= 0:
            return []

        params: list[t.Any] = [session_id]
        if kinds is not None:
            if not kinds:
                return []
            placeholders = ",".join("?" for _ in kinds)
            where = f"session_id=? AND kind IN ({placeholders})"
            params.extend(kinds)
        else:
            where = "session_id=?"

        select = f"SELECT seq, kind, ts, payload FROM events WHERE {where}"
        if limit is None:
            sql = f"{select} ORDER BY seq"
        else:
            sql = f"SELECT * FROM ({select} ORDER BY seq DESC LIMIT ?) ORDER BY seq"
            params.append(limit)
        rows = self._c.execute(sql, params).fetchall()
        return [
            {
                "seq": r["seq"],
                "kind": r["kind"],
                "ts": r["ts"],
                "payload": json.loads(r["payload"]),
            }
            for r in rows
        ]

    async def append_artifact_event(
        self,
        session_id: str,
        *,
        filename: str,
        label: str,
        path: str,
        content: str,
    ) -> tuple[int, dict[str, t.Any]]:
        """Persist a bounded artifact snapshot and its lightweight chat event."""
        return await self._run(
            self._append_artifact_event,
            session_id,
            filename,
            label,
            path,
            content,
        )

    def _append_artifact_event(
        self,
        session_id: str,
        filename: str,
        label: str,
        path: str,
        content: str,
    ) -> tuple[int, dict[str, t.Any]]:
        size_bytes = len(content.encode("utf-8"))
        if size_bytes > MAX_ARTIFACT_BYTES:
            raise ValueError(
                f"Artifact is {size_bytes} bytes; maximum is {MAX_ARTIFACT_BYTES} bytes"
            )

        artifact_id = uuid.uuid4().hex
        payload: dict[str, t.Any] = {
            "artifact_id": artifact_id,
            "filename": filename,
            "path": path,
            "label": label,
            "size_bytes": size_bytes,
        }
        try:
            seq = self._insert_event(session_id, "file_artifact", payload)
            self._c.execute(
                "INSERT INTO artifacts "
                "(id, session_id, event_seq, filename, label, path, content, size_bytes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    session_id,
                    seq,
                    filename,
                    label,
                    path,
                    content,
                    size_bytes,
                    _utcnow(),
                ),
            )
            self._prune_events(session_id)
            self._prune_artifacts(session_id)
            self._c.commit()
        except BaseException:
            self._c.rollback()
            raise
        return seq, payload

    def _prune_artifacts(self, session_id: str) -> None:
        rows = self._c.execute(
            "SELECT event_seq, size_bytes FROM artifacts "
            "WHERE session_id=? ORDER BY event_seq DESC",
            (session_id,),
        ).fetchall()
        retained_count = 0
        retained_bytes = 0
        evicted: list[int] = []
        for row in rows:
            size_bytes = int(row["size_bytes"])
            if (
                retained_count >= MAX_ARTIFACTS_PER_SESSION
                or retained_bytes + size_bytes > MAX_ARTIFACT_STORAGE_PER_SESSION
            ):
                evicted.append(int(row["event_seq"]))
                continue
            retained_count += 1
            retained_bytes += size_bytes

        if evicted:
            placeholders = ",".join("?" for _ in evicted)
            self._c.execute(
                f"DELETE FROM events WHERE session_id=? AND seq IN ({placeholders})",
                (session_id, *evicted),
            )

    async def get_artifact(
        self, session_id: str, artifact_id: str
    ) -> dict[str, t.Any] | None:
        """Return a stored artifact snapshot owned by the session."""
        return await self._run(self._get_artifact, session_id, artifact_id)

    def _get_artifact(
        self, session_id: str, artifact_id: str
    ) -> dict[str, t.Any] | None:
        row = self._c.execute(
            "SELECT filename, label, path, content, size_bytes, created_at "
            "FROM artifacts WHERE session_id=? AND id=?",
            (session_id, artifact_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": artifact_id,
            "filename": row["filename"],
            "label": row["label"],
            "path": row["path"],
            "content": row["content"],
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"],
        }

    async def clear_events(self, session_id: str) -> None:
        """Delete every event for a session."""
        await self._run(self._clear_events, session_id)

    def _clear_events(self, session_id: str) -> None:
        self._c.execute("DELETE FROM events WHERE session_id=?", (session_id,))
        self._c.commit()

    # --- meta --------------------------------------------------------------

    async def set_meta(self, key: str, value: t.Any) -> None:
        """Store a JSON-serializable metadata value."""
        await self._run(self._set_meta, key, value)

    def _set_meta(self, key: str, value: t.Any) -> None:
        self._c.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        self._c.commit()

    async def get_meta(self, key: str) -> t.Any | None:
        """Return a metadata value, or ``None`` when absent."""
        return await self._run(self._get_meta, key)

    def _get_meta(self, key: str) -> t.Any | None:
        row = self._c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    async def delete_meta(self, key: str) -> None:
        """Delete a metadata value."""
        await self._run(self._delete_meta, key)

    def _delete_meta(self, key: str) -> None:
        self._c.execute("DELETE FROM meta WHERE key=?", (key,))
        self._c.commit()

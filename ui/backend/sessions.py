"""Session lifecycle service.

A session is an agent conversation optionally bound to a paper directory.
Sessions start blank (no paper) and get a paper assigned when the user
creates one or the agent scaffolds one. 1:1 session-paper binding is
enforced — assigning a paper that already has a session is rejected.
"""

from __future__ import annotations

import os
import re
import typing as t
import uuid
from datetime import datetime, timezone

from .db import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_id() -> str:
    return "s-" + uuid.uuid4().hex[:8]


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    return slug or "untitled"


class SessionService:
    """Manages session lifecycle over the SQLite layer."""

    def __init__(self, db: Database, papers_root: str) -> None:
        self.db = db
        self.papers_root = os.path.realpath(os.path.abspath(papers_root))

    @staticmethod
    def _normalize_paper_dir(paper_dir: str) -> str:
        """Resolve and validate an existing ALFRED paper directory."""
        normalized = os.path.realpath(os.path.abspath(os.path.expanduser(paper_dir)))
        if not os.path.isfile(os.path.join(normalized, "paper.yaml")):
            raise ValueError(f"No paper.yaml found at {normalized}")
        return normalized

    async def create_session(
        self,
        *,
        label: str | None = None,
        paper_dir: str | None = None,
        model: str | None = None,
    ) -> dict[str, t.Any]:
        """Create a new session, optionally bound to a paper directory."""
        if paper_dir:
            paper_dir = self._normalize_paper_dir(paper_dir)
            existing = await self._find_session_by_paper(paper_dir)
            if existing:
                raise ValueError(
                    f"A session for this paper already exists: '{existing['label']}'"
                )

        sid = _short_id()
        session: dict[str, t.Any] = {
            "id": sid,
            "label": label or "New Session",
            "paper_dir": paper_dir,
            "model": model,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await self.db.upsert_session(session)
        return session

    async def list_sessions(self) -> list[dict[str, t.Any]]:
        """Return sessions ordered by creation time."""
        sessions = await self.db.list_sessions()
        sessions.sort(key=lambda s: s.get("created_at", ""))
        return sessions

    async def get_session(self, session_id: str) -> dict[str, t.Any] | None:
        """Return a session by ID, or ``None`` when absent."""
        return await self.db.get_session(session_id)

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and report whether it existed."""
        session = await self.db.get_session(session_id)
        if session is None:
            return False
        await self.db.delete_session(session_id)
        return True

    async def set_label(self, session_id: str, label: str) -> dict[str, t.Any] | None:
        """Update a session label and modification timestamp."""
        session = await self.db.get_session(session_id)
        if session is None:
            return None
        session["label"] = label
        session["updated_at"] = _now()
        await self.db.upsert_session(session)
        return session

    async def set_paper(
        self, session_id: str, paper_dir: str
    ) -> dict[str, t.Any] | None:
        """Assign a paper directory to a session. Enforces 1:1 binding."""
        paper_dir = self._normalize_paper_dir(paper_dir)

        existing = await self._find_session_by_paper(paper_dir)
        if existing and existing["id"] != session_id:
            raise ValueError(
                f"A session for this paper already exists: '{existing['label']}'"
            )

        session = await self.db.get_session(session_id)
        if session is None:
            return None
        session["paper_dir"] = paper_dir
        session["updated_at"] = _now()
        await self.db.upsert_session(session)
        return session

    async def set_paper_and_label(
        self, session_id: str, paper_dir: str, label: str
    ) -> dict[str, t.Any] | None:
        """Assign a newly created paper and its label in one database write."""
        paper_dir = self._normalize_paper_dir(paper_dir)

        existing = await self._find_session_by_paper(paper_dir)
        if existing and existing["id"] != session_id:
            raise ValueError(
                f"A session for this paper already exists: '{existing['label']}'"
            )

        session = await self.db.get_session(session_id)
        if session is None:
            return None
        session["paper_dir"] = paper_dir
        session["label"] = label
        session["updated_at"] = _now()
        await self.db.upsert_session(session)
        return session

    async def set_model(self, session_id: str, model: str) -> dict[str, t.Any] | None:
        """Update the model assigned to a session."""
        session = await self.db.get_session(session_id)
        if session is None:
            return None
        session["model"] = model
        session["updated_at"] = _now()
        await self.db.upsert_session(session)
        return session

    async def touch(self, session_id: str) -> None:
        """Update the session's updated_at timestamp."""
        session = await self.db.get_session(session_id)
        if session is None:
            return
        session["updated_at"] = _now()
        await self.db.upsert_session(session)

    async def find_session_by_paper(self, paper_dir: str) -> dict[str, t.Any] | None:
        """Return the session bound to a paper directory, if any."""
        return await self._find_session_by_paper(self._normalize_paper_dir(paper_dir))

    async def _find_session_by_paper(self, paper_dir: str) -> dict[str, t.Any] | None:
        sessions = await self.db.list_sessions()
        paper_dir = os.path.realpath(os.path.abspath(os.path.expanduser(paper_dir)))
        for s in sessions:
            if s.get("paper_dir") and os.path.realpath(s["paper_dir"]) == paper_dir:
                return s
        return None

    def unique_paper_slug(self, title: str) -> str:
        """Return a slug that doesn't collide with existing paper dirs."""
        base = _slugify(title)
        slug = base
        n = 2
        while os.path.exists(os.path.join(self.papers_root, slug)):
            slug = f"{base}-{n}"
            n += 1
        return slug

"""Tests for multi-session: session lifecycle, slug helpers, and paper listing."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import stat
import sys
import typing as t
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# Add paths so we can import backend.* and scripts.*
UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, UI_DIR)
sys.path.insert(0, SCRIPTS_DIR)

import backend.db as db_module  # noqa: E402
import init_template as init_template_module  # noqa: E402
from backend.db import Database  # noqa: E402
from backend.sessions import SessionService  # noqa: E402
from init_template import init_template  # noqa: E402
from scaffold import scaffold_paper  # noqa: E402

# ---------------------------------------------------------------------------
# scaffold_paper
# ---------------------------------------------------------------------------


def _snapshot_tree(root: Path) -> dict[str, tuple[str, bytes | str]]:
    """Capture directory entries and file contents for rollback assertions."""
    snapshot: dict[str, tuple[str, bytes | str]] = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path))
        elif path.is_dir():
            snapshot[relative] = ("directory", b"")
        else:
            snapshot[relative] = ("file", path.read_bytes())
    return snapshot


class TestScaffoldPaper:
    def test_creates_complete_project(self, tmp_path: t.Any) -> None:
        """Scaffolding produces all required files with correct title."""
        import yaml

        paper_dir = str(tmp_path / "my-paper")
        scaffold_paper(paper_dir, title="Custom Title")

        with open(os.path.join(paper_dir, "paper.yaml")) as f:
            data = yaml.safe_load(f)
        assert data["title"] == "Custom Title"
        assert os.path.isdir(os.path.join(paper_dir, "section"))
        assert os.path.isdir(os.path.join(paper_dir, "data"))
        assert os.path.isdir(os.path.join(paper_dir, "figures"))
        assert os.path.isdir(os.path.join(paper_dir, "reviews"))
        assert os.path.isdir(os.path.join(paper_dir, "styles"))
        assert os.path.isfile(os.path.join(paper_dir, "bibliography.bib"))
        assert os.path.isfile(os.path.join(paper_dir, "main.tex"))

    def test_does_not_overwrite_existing_bibliography(self, tmp_path: t.Any) -> None:
        paper_dir = str(tmp_path / "my-paper")
        os.makedirs(paper_dir)
        bib_path = os.path.join(paper_dir, "bibliography.bib")
        with open(bib_path, "w") as f:
            f.write("@article{existing,}")
        scaffold_paper(paper_dir)
        with open(bib_path) as f:
            assert "@article{existing,}" in f.read()

    def test_refuses_to_overwrite_existing_paper(self, tmp_path: t.Any) -> None:
        """Scaffolding cannot replace an existing paper manifest or main file."""
        paper_dir = tmp_path / "existing"
        paper_dir.mkdir()
        (paper_dir / "paper.yaml").write_text("title: Keep Me\n")
        with pytest.raises(FileExistsError, match="Refusing to overwrite"):
            scaffold_paper(str(paper_dir), title="Replacement")
        assert (paper_dir / "paper.yaml").read_text() == "title: Keep Me\n"

    def test_sync_failure_leaves_no_partial_paper(self, tmp_path: t.Any) -> None:
        """A failed staged sync must not publish an orphaned paper directory."""
        paper_dir = tmp_path / "broken"

        with patch("sync.sync", return_value=1):
            with pytest.raises(RuntimeError, match="synchronize"):
                scaffold_paper(str(paper_dir))

        assert not paper_dir.exists()
        assert not list(tmp_path.glob(".broken.scaffold-*"))

    def test_failure_preserves_existing_nonpaper_content(self, tmp_path: t.Any) -> None:
        """Scaffolding rollback must retain content in a pre-existing directory."""
        paper_dir = tmp_path / "existing"
        paper_dir.mkdir()
        (paper_dir / "bibliography.bib").write_text("@article{keep,}\n")
        (paper_dir / "notes.txt").write_text("keep me\n")
        before = _snapshot_tree(paper_dir)

        with patch("sync.sync", return_value=1):
            with pytest.raises(RuntimeError, match="synchronize"):
                scaffold_paper(str(paper_dir))

        assert _snapshot_tree(paper_dir) == before

    def test_publish_failure_restores_existing_directory(self, tmp_path: t.Any) -> None:
        """A failed final directory swap restores the original directory."""
        paper_dir = tmp_path / "existing"
        paper_dir.mkdir()
        (paper_dir / "notes.txt").write_text("original\n")
        before = _snapshot_tree(paper_dir)
        real_replace = os.replace
        replace_count = 0
        publish_failed = False

        def fail_staged_publish(source: str, destination: str) -> None:
            nonlocal publish_failed, replace_count
            if source == str(paper_dir) or destination == str(paper_dir):
                replace_count += 1
            if destination == str(paper_dir) and not publish_failed:
                publish_failed = True
                raise OSError("injected publish failure")
            real_replace(source, destination)

        with patch("scaffold.os.replace", side_effect=fail_staged_publish):
            with pytest.raises(OSError, match="injected publish failure"):
                scaffold_paper(str(paper_dir))

        assert replace_count == 3
        assert _snapshot_tree(paper_dir) == before
        assert not list(tmp_path.glob(".existing.scaffold-*"))
        assert not list(tmp_path.glob(".existing.original-*"))


# ---------------------------------------------------------------------------
# init_template
# ---------------------------------------------------------------------------


class TestInitTemplate:
    @staticmethod
    def _paper(tmp_path: Path) -> Path:
        paper_dir = tmp_path / "paper"
        scaffold_paper(str(paper_dir), title="Transactional Templates")
        (paper_dir / "build").mkdir()
        (paper_dir / "build" / "main.pdf").write_bytes(b"old build")
        return paper_dir

    def test_switch_commits_complete_template(self, tmp_path: Path) -> None:
        paper_dir = self._paper(tmp_path)

        result = init_template(str(paper_dir), "ieee")

        assert result == 0
        assert "template: ieee" in (paper_dir / "paper.yaml").read_text()
        assert "IEEEtran" in (paper_dir / "main.tex").read_text()
        assert (paper_dir / "IEEEtran.cls").is_file()
        assert not (paper_dir / "build").exists()

    def test_sync_failure_preserves_project_byte_for_byte(self, tmp_path: Path) -> None:
        paper_dir = self._paper(tmp_path)
        assert init_template(str(paper_dir), "ieee") == 0
        (paper_dir / "build").mkdir()
        (paper_dir / "build" / "state.aux").write_bytes(b"keep build")
        before = _snapshot_tree(paper_dir)

        with patch("sync.sync", return_value=1):
            result = init_template(str(paper_dir), "acl")

        assert result == 1
        assert _snapshot_tree(paper_dir) == before

    def test_commit_failure_rolls_back_every_replacement(self, tmp_path: Path) -> None:
        paper_dir = self._paper(tmp_path)
        assert init_template(str(paper_dir), "ieee") == 0
        (paper_dir / "build").mkdir()
        (paper_dir / "build" / "state.aux").write_bytes(b"keep build")
        before = _snapshot_tree(paper_dir)
        real_copy = init_template_module._copy_file_atomic
        copy_count = 0

        def fail_during_commit(source: str, destination: str) -> None:
            nonlocal copy_count
            copy_count += 1
            if copy_count == 2:
                raise OSError("injected commit failure")
            real_copy(source, destination)

        with patch(
            "init_template._copy_file_atomic",
            side_effect=fail_during_commit,
        ):
            result = init_template(str(paper_dir), "acl")

        assert result == 1
        assert copy_count == 2
        assert _snapshot_tree(paper_dir) == before

    def test_missing_declared_extra_file_is_a_preflight_error(
        self, tmp_path: Path
    ) -> None:
        paper_dir = self._paper(tmp_path)
        before = _snapshot_tree(paper_dir)
        fake_repo = tmp_path / "fake-repo"
        template_dir = fake_repo / "templates" / "broken"
        template_dir.mkdir(parents=True)
        (template_dir / "template.yaml").write_text(
            "name: Broken\nextra_files:\n  - missing.cls\n"
        )
        (template_dir / "main.tex").write_text("unused\n")

        with patch.object(init_template_module, "_REPO_ROOT", str(fake_repo)):
            result = init_template(str(paper_dir), "broken")

        assert result == 1
        assert _snapshot_tree(paper_dir) == before

    @pytest.mark.parametrize(
        "template_name",
        [
            "aaai2026",
            "acm",
            "cvpr2026",
            "iclr2026",
            "icml2026",
            "lncs",
            "ndss2026",
            "neurips",
            "neurips2026",
        ],
    )
    def test_new_templates_switch_as_complete_units(
        self, tmp_path: Path, template_name: str
    ) -> None:
        paper_dir = self._paper(tmp_path)
        template_dir = (
            Path(init_template_module._REPO_ROOT) / "templates" / template_name
        )
        config = yaml.safe_load((template_dir / "template.yaml").read_text())

        assert init_template(str(paper_dir), template_name) == 0

        assert f"template: {template_name}" in (paper_dir / "paper.yaml").read_text()
        for filename in config["extra_files"]:
            assert (paper_dir / filename).is_file()

    def test_neurips_alias_matches_versioned_template(self) -> None:
        templates = Path(init_template_module._REPO_ROOT) / "templates"
        for filename in ("main.tex", "neurips_2026.sty", "checklist.tex"):
            assert (templates / "neurips" / filename).read_bytes() == (
                templates / "neurips2026" / filename
            ).read_bytes()


# ---------------------------------------------------------------------------
# SessionService: slug helpers
# ---------------------------------------------------------------------------


class TestUniqueSlug:
    def test_converts_title_to_slug(self, tmp_path: t.Any) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        svc = SessionService(db, str(tmp_path / "papers"))
        assert svc.unique_paper_slug("Hello, World! (2024)") == "hello-world-2024"
        asyncio.run(db.close())

    def test_truncates_and_handles_empty(self, tmp_path: t.Any) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        svc = SessionService(db, str(tmp_path / "papers"))
        assert len(svc.unique_paper_slug("a" * 100)) <= 50
        assert svc.unique_paper_slug("") == "untitled"
        assert svc.unique_paper_slug("!!!") == "untitled"
        asyncio.run(db.close())

    def test_appends_suffix_on_collision(self, tmp_path: t.Any) -> None:
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()
        (papers_dir / "my-paper").mkdir()
        (papers_dir / "my-paper-2").mkdir()
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        svc = SessionService(db, str(papers_dir))
        assert svc.unique_paper_slug("My Paper") == "my-paper-3"
        asyncio.run(db.close())


# ---------------------------------------------------------------------------
# SessionService: lifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    def _make_svc(self, tmp_path: t.Any) -> tuple[Database, SessionService]:
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir(exist_ok=True)
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        return db, SessionService(db, str(papers_dir))

    def test_create_and_list(self, tmp_path: t.Any) -> None:
        db, svc = self._make_svc(tmp_path)
        s1 = asyncio.run(svc.create_session(label="Paper A", model="m"))
        s2 = asyncio.run(svc.create_session(label="Paper B", model="m"))
        sessions = asyncio.run(svc.list_sessions())
        assert len(sessions) == 2
        ids = {s["id"] for s in sessions}
        assert s1["id"] in ids
        assert s2["id"] in ids
        asyncio.run(db.close())

    def test_paper_binding_1to1(self, tmp_path: t.Any) -> None:
        """Each paper_dir can only be assigned to one session."""
        db, svc = self._make_svc(tmp_path)
        paper_dir = str(tmp_path / "papers" / "p1")
        os.makedirs(paper_dir)
        (tmp_path / "papers" / "p1" / "paper.yaml").write_text("title: P1\n")
        s1 = asyncio.run(svc.create_session(label="A", model="m"))
        s2 = asyncio.run(svc.create_session(label="B", model="m"))
        asyncio.run(svc.set_paper(s1["id"], paper_dir))
        import pytest

        with pytest.raises(ValueError, match="already exists"):
            asyncio.run(svc.set_paper(s2["id"], paper_dir))
        asyncio.run(db.close())

    def test_find_session_by_paper(self, tmp_path: t.Any) -> None:
        db, svc = self._make_svc(tmp_path)
        paper_dir = str(tmp_path / "papers" / "p1")
        os.makedirs(paper_dir)
        (tmp_path / "papers" / "p1" / "paper.yaml").write_text("title: P1\n")
        s1 = asyncio.run(svc.create_session(label="A", model="m"))
        asyncio.run(svc.set_paper(s1["id"], paper_dir))
        found = asyncio.run(svc.find_session_by_paper(paper_dir))
        assert found is not None
        assert found["id"] == s1["id"]
        asyncio.run(db.close())

    def test_rejects_directory_without_manifest(self, tmp_path: t.Any) -> None:
        """Paper bindings require an existing paper.yaml."""
        import pytest

        db, svc = self._make_svc(tmp_path)
        empty_dir = tmp_path / "papers" / "empty"
        empty_dir.mkdir()
        session = asyncio.run(svc.create_session(label="A", model="m"))
        with pytest.raises(ValueError, match="paper.yaml"):
            asyncio.run(svc.set_paper(session["id"], str(empty_dir)))
        asyncio.run(db.close())

    def test_delete_session(self, tmp_path: t.Any) -> None:
        db, svc = self._make_svc(tmp_path)
        s1 = asyncio.run(svc.create_session(label="A", model="m"))
        asyncio.run(svc.delete_session(s1["id"]))
        sessions = asyncio.run(svc.list_sessions())
        assert len(sessions) == 0
        asyncio.run(db.close())

    def test_set_label_and_model(self, tmp_path: t.Any) -> None:
        db, svc = self._make_svc(tmp_path)
        s1 = asyncio.run(svc.create_session(label="Old", model="old-m"))
        asyncio.run(svc.set_label(s1["id"], "New"))
        asyncio.run(svc.set_model(s1["id"], "new-m"))
        updated = asyncio.run(svc.get_session(s1["id"]))
        assert updated is not None
        assert updated["label"] == "New"
        assert updated["model"] == "new-m"
        asyncio.run(db.close())


# ---------------------------------------------------------------------------
# Database: events
# ---------------------------------------------------------------------------


class TestEventPersistence:
    def _make_session(self, db: Database, sid: str = "s1") -> None:
        asyncio.run(db.upsert_session({"id": sid, "label": "test"}))

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
    def test_connect_restricts_existing_database_and_sidecars(
        self, tmp_path: t.Any
    ) -> None:
        db_path = tmp_path / "state.db"
        sqlite3.connect(db_path).close()
        os.chmod(db_path, 0o644)

        db = Database(str(db_path))
        asyncio.run(db.connect())

        for path in (
            db_path,
            tmp_path / "state.db-wal",
            tmp_path / "state.db-shm",
        ):
            assert path.exists()
            assert stat.S_IMODE(path.stat().st_mode) == 0o600

        asyncio.run(db.close())

    @pytest.mark.skipif(
        not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW is unavailable"
    )
    def test_connect_refuses_database_symlink(self, tmp_path: t.Any) -> None:
        target = tmp_path / "target.db"
        sqlite3.connect(target).close()
        db_path = tmp_path / "state.db"
        db_path.symlink_to(target)

        with pytest.raises(OSError):
            asyncio.run(Database(str(db_path)).connect())

    @pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
    def test_connect_refuses_sqlite_sidecar_symlink(self, tmp_path: t.Any) -> None:
        db_path = tmp_path / "state.db"
        sqlite3.connect(db_path).close()
        target = tmp_path / "target"
        target.write_text("unchanged")
        (tmp_path / "state.db-wal").symlink_to(target)

        with pytest.raises(OSError, match="Refusing SQLite symlink"):
            asyncio.run(Database(str(db_path)).connect())

        assert target.read_text() == "unchanged"

    def test_append_and_get(self, tmp_path: t.Any) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        self._make_session(db)
        asyncio.run(db.append_event("s1", "user_message", {"content": "hello"}))
        asyncio.run(db.append_event("s1", "agent_text", {"content": "world"}))
        events = asyncio.run(db.get_events("s1"))
        assert len(events) == 2
        assert events[0]["kind"] == "user_message"
        asyncio.run(db.close())

    def test_filter_by_kinds(self, tmp_path: t.Any) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        self._make_session(db)
        asyncio.run(db.append_event("s1", "user_message", {"content": "a"}))
        asyncio.run(db.append_event("s1", "system_info", {"content": "b"}))
        asyncio.run(db.append_event("s1", "agent_text", {"content": "c"}))
        events = asyncio.run(db.get_events("s1", kinds=["user_message", "agent_text"]))
        assert len(events) == 2
        asyncio.run(db.close())

    def test_limit_returns_newest_events_in_chronological_order(
        self, tmp_path: t.Any
    ) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        self._make_session(db)
        for index in range(6):
            asyncio.run(db.append_event("s1", "user_message", {"content": str(index)}))

        events = asyncio.run(db.get_events("s1", limit=3))

        assert [event["payload"]["content"] for event in events] == ["3", "4", "5"]
        assert [event["seq"] for event in events] == [4, 5, 6]
        asyncio.run(db.close())

    def test_pruning_starts_at_complete_user_turn(self, tmp_path: t.Any) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        self._make_session(db)

        with (
            patch.object(db_module, "EVENT_PRUNE_TRIGGER", 8),
            patch.object(db_module, "EVENT_PRUNE_TARGET", 5),
        ):
            kinds = [
                "user_message",
                "tool_start",
                "tool_end",
                "generation",
                "user_message",
                "tool_start",
                "tool_end",
                "generation",
                "user_message",
            ]
            for index, kind in enumerate(kinds):
                asyncio.run(db.append_event("s1", kind, {"content": str(index)}))

        events = asyncio.run(db.get_events("s1"))
        assert [event["seq"] for event in events] == [5, 6, 7, 8, 9]
        assert events[0]["kind"] == "user_message"
        asyncio.run(db.close())

    def test_connect_prunes_history_created_by_older_version(
        self, tmp_path: t.Any
    ) -> None:
        db_path = tmp_path / "state.db"
        db = Database(str(db_path))
        asyncio.run(db.connect())
        self._make_session(db)
        asyncio.run(db.close())

        conn = sqlite3.connect(db_path)
        kinds = [
            "user_message",
            "tool_start",
            "tool_end",
            "generation",
            "user_message",
            "tool_start",
            "tool_end",
            "generation",
            "user_message",
        ]
        conn.executemany(
            "INSERT INTO events (session_id, seq, kind, ts, payload) "
            "VALUES ('s1', ?, ?, 'old', '{}')",
            [(index, kind) for index, kind in enumerate(kinds, start=1)],
        )
        conn.commit()
        conn.close()

        with (
            patch.object(db_module, "EVENT_PRUNE_TRIGGER", 8),
            patch.object(db_module, "EVENT_PRUNE_TARGET", 5),
        ):
            migrated = Database(str(db_path))
            asyncio.run(migrated.connect())

        events = asyncio.run(migrated.get_events("s1"))
        assert [event["seq"] for event in events] == [5, 6, 7, 8, 9]
        assert events[0]["kind"] == "user_message"
        asyncio.run(migrated.close())

    def test_artifact_content_is_stored_outside_event_payload(
        self, tmp_path: t.Any
    ) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        self._make_session(db)

        seq, payload = asyncio.run(
            db.append_artifact_event(
                "s1",
                filename="report.md",
                label="Report",
                path="/paper/report.md",
                content="exact snapshot",
            )
        )

        events = asyncio.run(db.get_events("s1"))
        assert seq == 1
        assert "content" not in events[0]["payload"]
        artifact = asyncio.run(db.get_artifact("s1", payload["artifact_id"]))
        assert artifact is not None
        assert artifact["content"] == "exact snapshot"
        asyncio.run(db.close())

    def test_artifact_size_limit_is_measured_in_utf8_bytes(
        self, tmp_path: t.Any
    ) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        self._make_session(db)

        with (
            patch.object(db_module, "MAX_ARTIFACT_BYTES", 4),
            pytest.raises(ValueError, match="maximum is 4 bytes"),
        ):
            asyncio.run(
                db.append_artifact_event(
                    "s1",
                    filename="unicode.md",
                    label="Unicode",
                    path="/paper/unicode.md",
                    content="ééé",
                )
            )

        assert asyncio.run(db.get_events("s1")) == []
        asyncio.run(db.close())

    def test_artifact_count_budget_evicts_oldest_card_and_snapshot(
        self, tmp_path: t.Any
    ) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        self._make_session(db)
        artifact_ids: list[str] = []

        with patch.object(db_module, "MAX_ARTIFACTS_PER_SESSION", 2):
            for index in range(3):
                _, payload = asyncio.run(
                    db.append_artifact_event(
                        "s1",
                        filename=f"report-{index}.md",
                        label=f"Report {index}",
                        path=f"/paper/report-{index}.md",
                        content=f"snapshot {index}",
                    )
                )
                artifact_ids.append(payload["artifact_id"])

        events = asyncio.run(db.get_events("s1", kinds=["file_artifact"]))
        assert len(events) == 2
        assert asyncio.run(db.get_artifact("s1", artifact_ids[0])) is None
        assert asyncio.run(db.get_artifact("s1", artifact_ids[2])) is not None
        asyncio.run(db.close())

    def test_artifact_byte_budget_evicts_oldest_snapshot(self, tmp_path: t.Any) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        self._make_session(db)

        with patch.object(db_module, "MAX_ARTIFACT_STORAGE_PER_SESSION", 10):
            _, first = asyncio.run(
                db.append_artifact_event(
                    "s1",
                    filename="first.md",
                    label="First",
                    path="/paper/first.md",
                    content="ééé",
                )
            )
            _, second = asyncio.run(
                db.append_artifact_event(
                    "s1",
                    filename="second.md",
                    label="Second",
                    path="/paper/second.md",
                    content="ééé",
                )
            )

        assert asyncio.run(db.get_artifact("s1", first["artifact_id"])) is None
        assert asyncio.run(db.get_artifact("s1", second["artifact_id"])) is not None
        asyncio.run(db.close())

    def test_clear_events_cascades_to_artifacts(self, tmp_path: t.Any) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        self._make_session(db)
        _, payload = asyncio.run(
            db.append_artifact_event(
                "s1",
                filename="report.md",
                label="Report",
                path="/paper/report.md",
                content="snapshot",
            )
        )

        asyncio.run(db.clear_events("s1"))

        assert asyncio.run(db.get_artifact("s1", payload["artifact_id"])) is None
        asyncio.run(db.close())

    def test_connect_upgrades_legacy_database_without_losing_inline_artifact(
        self, tmp_path: t.Any
    ) -> None:
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE sessions (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE events (
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                kind TEXT NOT NULL,
                ts TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (session_id, seq)
            );
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO sessions VALUES ('s1', '{"id":"s1","label":"legacy"}');
            INSERT INTO events VALUES (
                's1', 1, 'file_artifact', 'old',
                '{"filename":"old.md","content":"legacy snapshot"}'
            );
            """
        )
        conn.commit()
        conn.close()

        db = Database(str(db_path))
        asyncio.run(db.connect())

        legacy = asyncio.run(db.get_events("s1"))
        assert "content" not in legacy[0]["payload"]
        legacy_artifact = asyncio.run(
            db.get_artifact("s1", legacy[0]["payload"]["artifact_id"])
        )
        assert legacy_artifact is not None
        assert legacy_artifact["content"] == "legacy snapshot"
        _, payload = asyncio.run(
            db.append_artifact_event(
                "s1",
                filename="new.md",
                label="New",
                path="/paper/new.md",
                content="new snapshot",
            )
        )
        assert asyncio.run(db.get_artifact("s1", payload["artifact_id"])) is not None
        asyncio.run(db.close())

    def test_migration_drops_oversized_legacy_card_not_source_file(
        self, tmp_path: t.Any
    ) -> None:
        db_path = tmp_path / "state.db"
        source = tmp_path / "large.md"
        source.write_text("12345")
        db = Database(str(db_path))
        asyncio.run(db.connect())
        self._make_session(db)
        asyncio.run(
            db.append_event(
                "s1",
                "file_artifact",
                {
                    "filename": source.name,
                    "path": str(source),
                    "content": source.read_text(),
                },
            )
        )
        asyncio.run(db.close())

        with patch.object(db_module, "MAX_ARTIFACT_BYTES", 4):
            migrated = Database(str(db_path))
            asyncio.run(migrated.connect())

        assert asyncio.run(migrated.get_events("s1")) == []
        assert source.read_text() == "12345"
        asyncio.run(migrated.close())

    def test_clear(self, tmp_path: t.Any) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        self._make_session(db)
        asyncio.run(db.append_event("s1", "user_message", {"content": "a"}))
        asyncio.run(db.clear_events("s1"))
        events = asyncio.run(db.get_events("s1"))
        assert len(events) == 0
        asyncio.run(db.close())

    def test_meta(self, tmp_path: t.Any) -> None:
        db = Database(str(tmp_path / "state.db"))
        asyncio.run(db.connect())
        asyncio.run(db.set_meta("key", "val"))
        assert asyncio.run(db.get_meta("key")) == "val"
        assert asyncio.run(db.get_meta("missing")) is None
        asyncio.run(db.close())

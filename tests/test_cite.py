"""Tests for scripts/cite.py — key generation and bib file manipulation."""

from __future__ import annotations

import sys

import cite
import pytest
from cite import _add_bibtex_entry, _key_exists, _make_cite_key

# ---------------------------------------------------------------------------
# Citation key generation
# ---------------------------------------------------------------------------


class TestMakeCiteKey:
    def test_basic(self):
        paper = {"authors": [{"name": "Ashish Vaswani"}], "year": 2017}
        assert _make_cite_key(paper) == "vaswani2017"

    def test_no_authors(self):
        assert _make_cite_key({"authors": [], "year": 2025}) == "unknown2025"

    def test_no_year(self):
        assert _make_cite_key({"authors": [{"name": "Jane Doe"}]}) == "doe"

    def test_strips_non_alpha_from_surname(self):
        paper = {"authors": [{"name": "José García-López"}], "year": 2024}
        assert _make_cite_key(paper) == "garcalpez2024"


class TestApiKeyArguments:
    def test_reads_api_key_from_named_environment_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALFRED_TEST_S2_KEY", "dummy-secret")
        monkeypatch.setattr(cite, "_api_key", None)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cite.py",
                "search",
                "query",
                "--api-key-env",
                "ALFRED_TEST_S2_KEY",
            ],
        )
        monkeypatch.setattr(cite, "cmd_search", lambda *args, **kwargs: 0)

        with pytest.raises(SystemExit) as exc_info:
            cite.main()

        assert exc_info.value.code == 0
        assert cite._api_key == "dummy-secret"

    @pytest.mark.parametrize(
        "legacy_arguments",
        [
            ["--api-key", "sk-dummy-not-a-secret"],
            ["--api-key=sk-dummy-not-a-secret"],
        ],
    )
    def test_rejects_raw_api_key_argument(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        legacy_arguments: list[str],
    ) -> None:
        raw_key = "sk-dummy-not-a-secret"
        monkeypatch.setattr(
            sys,
            "argv",
            ["cite.py", "search", "query", *legacy_arguments],
        )

        with pytest.raises(SystemExit) as exc_info:
            cite.main()

        assert exc_info.value.code == 2
        stderr = capsys.readouterr().err
        assert "invalid command-line arguments" in stderr
        assert raw_key not in stderr

    def test_help_hides_legacy_api_key_alias(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["cite.py", "search", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            cite.main()

        stdout = capsys.readouterr().out
        assert exc_info.value.code == 0
        assert "--api-key-env API_KEY_ENV" in stdout
        assert "--api-key API_KEY_ENV" not in stdout


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestKeyExists:
    def test_finds_existing_key(self):
        bib = "@article{smith2025,\n  title={Test},\n}"
        assert _key_exists(bib, "smith2025") is True

    def test_missing_key(self):
        assert _key_exists("@article{smith2025,\n}", "jones2024") is False

    def test_no_partial_match(self):
        """smith2025 should not match smith2025long."""
        assert _key_exists("@article{smith2025long,\n}", "smith2025") is False

    def test_works_across_entry_types(self):
        assert _key_exists("@inproceedings{devlin2019,\n}", "devlin2019") is True


# ---------------------------------------------------------------------------
# BibTeX entry addition
# ---------------------------------------------------------------------------


class TestAddBibtexEntry:
    def test_appends_and_replaces_key(self, tmp_path):
        bib_path = str(tmp_path / "test.bib")
        with open(bib_path, "w") as f:
            f.write("% existing\n")
        bibtex = "@article{ORIGINAL_KEY,\n  title={Test Paper},\n  year={2025},\n}"
        assert _add_bibtex_entry(bib_path, bibtex, "smith2025") is True
        content = open(bib_path).read()
        assert content.startswith("% existing\n")
        assert "@article{smith2025," in content
        assert "ORIGINAL_KEY" not in content

    def test_rejects_duplicate(self, tmp_path):
        bib_path = str(tmp_path / "test.bib")
        with open(bib_path, "w") as f:
            f.write("@article{smith2025,\n  title={Existing},\n}\n")
        bibtex = "@article{KEY,\n  title={New},\n}"
        assert _add_bibtex_entry(bib_path, bibtex, "smith2025") is False

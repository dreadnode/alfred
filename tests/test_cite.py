"""Tests for scripts/cite.py — key generation and bib file manipulation."""

from __future__ import annotations

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
        key = _make_cite_key(paper)
        assert "2024" in key
        assert key[:-4].isalpha()  # surname portion is pure alpha


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

class TestKeyExists:
    def test_finds_existing_key(self):
        bib = '@article{smith2025,\n  title={Test},\n}'
        assert _key_exists(bib, "smith2025") is True

    def test_missing_key(self):
        assert _key_exists('@article{smith2025,\n}', "jones2024") is False

    def test_no_partial_match(self):
        """smith2025 should not match smith2025long."""
        assert _key_exists('@article{smith2025long,\n}', "smith2025") is False

    def test_works_across_entry_types(self):
        assert _key_exists('@inproceedings{devlin2019,\n}', "devlin2019") is True


# ---------------------------------------------------------------------------
# BibTeX entry addition
# ---------------------------------------------------------------------------

class TestAddBibtexEntry:
    def test_appends_and_replaces_key(self, tmp_path):
        bib_path = str(tmp_path / "test.bib")
        with open(bib_path, "w") as f:
            f.write("% existing\n")
        bibtex = '@article{ORIGINAL_KEY,\n  title={Test Paper},\n  year={2025},\n}'
        assert _add_bibtex_entry(bib_path, bibtex, "smith2025") is True
        content = open(bib_path).read()
        assert "@article{smith2025," in content
        assert "ORIGINAL_KEY" not in content

    def test_rejects_duplicate(self, tmp_path):
        bib_path = str(tmp_path / "test.bib")
        with open(bib_path, "w") as f:
            f.write('@article{smith2025,\n  title={Existing},\n}\n')
        bibtex = '@article{KEY,\n  title={New},\n}'
        assert _add_bibtex_entry(bib_path, bibtex, "smith2025") is False

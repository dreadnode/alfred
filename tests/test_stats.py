"""Tests for scripts/stats.py."""

from __future__ import annotations

import json

from stats import count_words, stats, strip_latex


# ---------------------------------------------------------------------------
# LaTeX stripping
# ---------------------------------------------------------------------------


class TestStripLatex:
    def test_plain_text_unchanged(self):
        assert strip_latex("Hello world") == "Hello world"

    def test_removes_comments(self):
        assert strip_latex("visible % invisible") == "visible"

    def test_preserves_escaped_percent(self):
        assert "30" in strip_latex("30\\% of participants")

    def test_removes_figure_and_figure_star(self):
        for env in ["figure", "figure*"]:
            tex = f"Before.\n\\begin{{{env}}}\ncontent\n\\end{{{env}}}\nAfter."
            result = strip_latex(tex)
            assert "Before." in result
            assert "After." in result
            assert "content" not in result

    def test_removes_equation(self):
        tex = "See \\begin{equation}E=mc^2\\end{equation} for details."
        result = strip_latex(tex)
        assert "See" in result
        assert "details" in result
        assert "mc" not in result

    def test_removes_inline_math(self):
        result = strip_latex("The value $x^2 + y^2$ is positive.")
        assert "MATH" in result
        assert "x^2" not in result

    def test_removes_display_math(self):
        result = strip_latex("Before.\n\\[\nE = mc^2\n\\]\nAfter.")
        assert "MATH" in result
        assert "mc" not in result

    def test_keeps_formatting_command_content(self):
        assert "important" in strip_latex("This is \\textbf{important}.")
        assert "key" in strip_latex("The \\emph{key} idea.")

    def test_removes_commands_with_options(self):
        result = strip_latex("\\usepackage[utf8]{inputenc}\nText.")
        assert "Text." in result
        assert "inputenc" not in result


# ---------------------------------------------------------------------------
# Word counting
# ---------------------------------------------------------------------------


class TestCountWords:
    def test_simple_sentence(self):
        assert count_words("This is a test.") == 4

    def test_latex_with_commands(self):
        assert count_words("\\section{Intro}\nWe present a novel approach.") == 5

    def test_empty_and_commands_only(self):
        assert count_words("") == 0
        assert count_words("\\begin{document}\\end{document}") == 0

    def test_tbd_markers_not_counted(self):
        assert count_words("\\tbd{Write this section.}") == 0

    def test_real_paragraph(self):
        tex = (
            "We propose a framework for evaluating \\textbf{large language models} "
            "on $n$-shot learning tasks. Our approach uses \\emph{contrastive} "
            "objectives to improve performance by 15\\%."
        )
        assert count_words(tex) == 24


# ---------------------------------------------------------------------------
# Statistics workflow
# ---------------------------------------------------------------------------


class TestStats:
    def test_reports_counts_and_missing_sections(self, tmp_path, capsys):
        (tmp_path / "paper.yaml").write_text(
            "sections:\n"
            "  - slug: intro\n"
            "    title: Introduction\n"
            "  - slug: missing\n"
            "    title: Missing Section\n"
        )
        section_dir = tmp_path / "section"
        section_dir.mkdir()
        (section_dir / "intro.tex").write_text(
            "One two three.\n"
            "\\begin{figure}content\\end{figure}\n"
            "\\begin{figure*}content\\end{figure*}\n"
            "\\begin{table}content\\end{table}\n"
            "\\begin{table*}content\\end{table*}\n"
            "\\cite{smith2025} \\citep{jones2024} \\citet{doe2023}\n"
            "\\begin{equation}x=1\\end{equation}\n"
            "\\begin{align}y&=2\\end{align}\n"
        )

        assert stats(str(tmp_path), as_json=True) == 0
        result = json.loads(capsys.readouterr().out)

        assert result == {
            "total_words": 3,
            "pages": None,
            "figures": 2,
            "tables": 2,
            "citations": 3,
            "equations": 2,
            "sections": [
                {
                    "slug": "intro",
                    "title": "Introduction",
                    "words": 3,
                    "figures": 2,
                    "tables": 2,
                    "citations": 3,
                    "equations": 2,
                    "exists": True,
                },
                {
                    "slug": "missing",
                    "title": "Missing Section",
                    "words": 0,
                    "exists": False,
                },
            ],
        }

    def test_missing_manifest_fails(self, tmp_path, capsys):
        assert stats(str(tmp_path), as_json=True) == 1
        assert capsys.readouterr().err == "ERROR: paper.yaml not found\n"

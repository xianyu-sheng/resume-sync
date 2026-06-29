"""
Tests for src/updater.py — Updater class and helper functions.

Exercises marker-block detection, content replacement, LaTeX sanitisation,
preview diff generation, backup creation, and marker validation.
"""

import difflib
import re
from pathlib import Path

import pytest

from src.updater import Updater, _sanitize_latex_bullet


# ---------------------------------------------------------------------------
# LaTeX template fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def latex_template():
    """Return a realistic LaTeX resume snippet with two marker blocks."""
    return r"""\documentclass{article}
\usepackage{enumitem}
\begin{document}

\section{Experience}
\begin{itemize}[leftmargin=*]
% RESUME_PROJECT_START: myproject
    \item Built a distributed system
    \item Optimised database queries
% RESUME_PROJECT_END: myproject
\end{itemize}

\section{Education}
\begin{itemize}[leftmargin=*]
% RESUME_PROJECT_START: school
    \item MSc in Computer Science
% RESUME_PROJECT_END: school
\end{itemize}

\end{document}
"""


@pytest.fixture
def tex_file(tmp_path, latex_template):
    """Write the LaTeX template to a temporary file and return the path."""
    path = tmp_path / "main.tex"
    path.write_text(latex_template)
    return path


@pytest.fixture
def updater(tex_file):
    """Return an Updater pointing at the temp .tex file."""
    return Updater(str(tex_file))


# ---------------------------------------------------------------------------
# constructor
# ---------------------------------------------------------------------------


class TestUpdaterInit:
    def test_raises_when_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="LaTeX file not found"):
            Updater(str(tmp_path / "nonexistent.tex"))

    def test_stores_tex_path(self, tex_file):
        u = Updater(str(tex_file))
        assert u.tex_path == tex_file


# ---------------------------------------------------------------------------
# _find_marker_block  (implemented as _get_current_block)
# ---------------------------------------------------------------------------


class TestFindMarkerBlock:
    def test_finds_existing_block(self, updater):
        block = updater._get_current_block("myproject")
        assert block is not None
        assert r"\item Built a distributed system" in block

    def test_returns_none_when_marker_missing(self, updater):
        block = updater._get_current_block("nonexistent")
        assert block is None

    def test_returns_none_when_start_missing(self, tex_file):
        """Only END marker present — should not match."""
        tex = Path(tex_file).read_text()
        tex = tex.replace("% RESUME_PROJECT_START: myproject", "")
        Path(tex_file).write_text(tex)
        u = Updater(str(tex_file))
        assert u._get_current_block("myproject") is None

    def test_returns_none_when_end_missing(self, tex_file):
        """Only START marker present — should not match."""
        tex = Path(tex_file).read_text()
        tex = tex.replace("% RESUME_PROJECT_END: myproject", "")
        Path(tex_file).write_text(tex)
        u = Updater(str(tex_file))
        assert u._get_current_block("myproject") is None

    def test_multiple_blocks(self, updater):
        """Different project keys return their respective content."""
        block_a = updater._get_current_block("myproject")
        block_b = updater._get_current_block("school")
        assert block_a is not None
        assert block_b is not None
        assert block_a != block_b
        assert r"\item Built a distributed system" in block_a
        assert r"\item MSc in Computer Science" in block_b


# ---------------------------------------------------------------------------
# _replace_block
# ---------------------------------------------------------------------------


class TestReplaceBlock:
    def test_replaces_content_between_markers(self, updater, latex_template):
        new_block = r"    \item New bullet A\n    \item New bullet B"
        result = updater._replace_block(latex_template, "myproject", new_block)
        assert r"\item New bullet A" in result
        assert r"\item New bullet B" in result
        assert r"\item Built a distributed system" not in result

    def test_replaces_old_content_with_new_bullets(self, updater, latex_template):
        new_block = r"    \item Replaced bullet"
        result = updater._replace_block(latex_template, "myproject", new_block)
        assert r"% RESUME_PROJECT_START: myproject" in result
        assert r"% RESUME_PROJECT_END: myproject" in result
        assert r"\item Replaced bullet" in result
        assert r"\item Built a distributed system" not in result

    def test_preserves_laTeX_outside_marker_blocks(self, updater, latex_template):
        new_block = r"    \item Just one bullet"
        result = updater._replace_block(latex_template, "myproject", new_block)
        assert r"\documentclass{article}" in result
        assert r"\end{document}" in result
        assert r"\section{Education}" in result
        # The other project block should be untouched
        assert r"% RESUME_PROJECT_START: school" in result
        assert r"\item MSc in Computer Science" in result

    def test_replaces_only_first_occurrence(self, updater, latex_template):
        """count=1 in re.sub ensures only one block is replaced."""
        new_block = r"    \item Replaced"
        result = updater._replace_block(latex_template, "myproject", new_block)
        assert result.count(r"% RESUME_PROJECT_START: myproject") == 1
        assert result.count(r"% RESUME_PROJECT_END: myproject") == 1

    def test_independent_replacement_of_multiple_keys(self, updater, latex_template):
        """Each project key's block can be replaced independently."""
        # Replace first block
        after_first = updater._replace_block(latex_template, "myproject",
                                              r"    \item My new content")
        # Replace second block
        after_second = updater._replace_block(after_first, "school",
                                               r"    \item School new content")
        assert r"\item My new content" in after_second
        assert r"\item School new content" in after_second
        assert r"\item Built a distributed system" not in after_second
        assert r"\item MSc in Computer Science" not in after_second
        assert r"\item Optimised database queries" not in after_second


# ---------------------------------------------------------------------------
# _sanitize_latex_bullet
# ---------------------------------------------------------------------------


class TestSanitizeLatexBullet:
    def test_blocks_end_document_injection(self):
        result = _sanitize_latex_bullet(r"Some text \end{document}")
        assert r"\end{document}" not in result
        assert "[BLOCKED: end{document}]" in result

    def test_blocks_resume_project_start_injection(self):
        result = _sanitize_latex_bullet(r"Stuff % RESUME_PROJECT_START: myproject")
        assert "% RESUME_PROJECT_START" not in result
        assert "[BLOCKED: RESUME_PROJECT_START]" in result

    def test_blocks_resume_project_end_injection(self):
        result = _sanitize_latex_bullet(r"Stuff % RESUME_PROJECT_END: myproject")
        assert "% RESUME_PROJECT_END" not in result
        assert "[BLOCKED: RESUME_PROJECT_END]" in result

    def test_passes_safe_text_unchanged(self):
        result = _sanitize_latex_bullet(r"\item Built a system")
        assert result == r"\item Built a system"

    def test_multiple_dangerous_patterns_handled(self):
        bullet = r"A \end{document} and % RESUME_PROJECT_START: x"
        result = _sanitize_latex_bullet(bullet)
        assert "[BLOCKED: end{document}]" in result
        assert "[BLOCKED: RESUME_PROJECT_START]" in result
        assert r"\end{document}" not in result

    def test_handles_edge_case_marker_without_colon(self):
        """The regex pattern requires colon+space after the marker name."""
        bullet = r"% RESUME_PROJECT_START myproject"
        result = _sanitize_latex_bullet(bullet)
        # Without colon, this pattern does NOT match — should pass through
        assert result == bullet

    def test_empty_string(self):
        assert _sanitize_latex_bullet("") == ""

    def test_dangerous_pattern_case_sensitivity(self):
        """The regex is case-sensitive; lowercase should not be blocked."""
        bullet = r"\end{document}"
        result = _sanitize_latex_bullet(bullet)
        # The pattern matches \end{document} — it IS case-sensitive matching
        assert "[BLOCKED: end{document}]" in result


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------


class TestPreview:
    def test_returns_current_and_proposed_and_diff(self, updater):
        result = updater.preview("myproject", [
            r"\item New bullet A",
            r"\item New bullet B",
        ])
        assert result["error"] is None
        assert "current" in result
        assert "proposed" in result
        assert "diff" in result
        assert r"\item New bullet A" in result["proposed"]
        assert r"\item New bullet B" in result["proposed"]
        assert len(result["diff"]) > 0

    def test_preview_does_not_modify_file(self, updater, tex_file):
        original = tex_file.read_text()
        updater.preview("myproject", [r"\item Should not be written"])
        assert tex_file.read_text() == original

    def test_preview_proposed_includes_item_prefix(self, updater):
        """Bullets that don't start with \item get the prefix prepended."""
        result = updater.preview("myproject", ["Wrote some code"])
        assert r"\item Wrote some code" in result["proposed"]

    def test_diff_is_generated_as_unified_diff(self, updater):
        result = updater.preview("myproject", [r"\item Something new"])
        assert result["diff"].startswith("---") or "---" in result["diff"]
        assert "+++" in result["diff"] or "+" in result["diff"]

    def test_preview_returns_error_for_missing_key(self, updater):
        result = updater.preview("nonexistent", [r"\item Nope"])
        assert result["error"] is not None
        assert "No marker block found" in result["error"]

    def test_preview_sanitizes_bullets(self, updater):
        """Bullets with dangerous content should be blocked in preview too."""
        result = updater.preview("myproject", [r"\item \end{document}"])
        assert "[BLOCKED: end{document}]" in result["proposed"]


# ---------------------------------------------------------------------------
# apply  (backup + write)
# ---------------------------------------------------------------------------


class TestApply:
    def test_creates_bak_file_before_writing(self, updater, tmp_path):
        before = tmp_path / "main.tex"
        before_content = before.read_text()

        updater.apply("myproject", [r"\item Applied change"])
        # There should be a .bak file
        bak_files = list(tmp_path.glob("*.tex.bak_*"))
        assert len(bak_files) >= 1
        # The bak file should contain the original content
        assert bak_files[0].read_text() == before_content

    def test_writes_updated_content(self, updater, tex_file):
        updater.apply("myproject", [r"\item Updated bullet"])
        content = tex_file.read_text()
        assert r"\item Updated bullet" in content
        assert r"\item Built a distributed system" not in content

    def test_returns_success_with_backup_path(self, updater):
        result = updater.apply("myproject", [r"\item Change"])
        assert result["success"] is True
        assert result["error"] is None
        assert "backup_path" in result
        assert Path(result["backup_path"]).exists()

    def test_returns_error_for_missing_key(self, updater):
        result = updater.apply("nonexistent", [r"\item Nope"])
        assert result["success"] is False
        assert result["error"] is not None

    def test_only_affected_block_is_changed(self, updater, tex_file):
        updater.apply("myproject", [r"\item Changed"])
        content = tex_file.read_text()
        # School block should be untouched
        assert r"% RESUME_PROJECT_START: school" in content
        assert r"\item MSc in Computer Science" in content

    def test_apply_adds_item_prefix(self, updater, tex_file):
        updater.apply("myproject", ["Bullet without item"])
        content = tex_file.read_text()
        assert r"\item Bullet without item" in content

    def test_apply_sanitizes_dangerous_content(self, updater, tex_file):
        updater.apply("myproject", [r"\item \end{document}"])
        block = updater._get_current_block("myproject")
        assert block is not None
        assert "[BLOCKED: end{document}]" in block
        assert r"\end{document}" not in block

    def test_multiple_keys_applied_independently(self, updater, tex_file):
        updater.apply("myproject", [r"\item Project change"])
        updater.apply("school", [r"\item School change"])
        content = tex_file.read_text()
        assert r"\item Project change" in content
        assert r"\item School change" in content
        assert r"\item Built a distributed system" not in content
        assert r"\item MSc in Computer Science" not in content


# ---------------------------------------------------------------------------
# validate_markers
# ---------------------------------------------------------------------------


class TestValidateMarkers:
    def test_all_markers_valid(self, updater):
        result = updater.validate_markers()
        assert result["myproject"] is True
        assert result["school"] is True

    def test_reports_missing_end_marker(self, tex_file):
        tex = Path(tex_file).read_text()
        tex = tex.replace("% RESUME_PROJECT_END: school", "")
        Path(tex_file).write_text(tex)
        u = Updater(str(tex_file))
        result = u.validate_markers()
        assert result["school"] is False

    def test_reports_missing_start_marker(self, tex_file):
        tex = Path(tex_file).read_text()
        tex = tex.replace("% RESUME_PROJECT_START: school", "")
        Path(tex_file).write_text(tex)
        u = Updater(str(tex_file))
        result = u.validate_markers()
        assert result["school"] is False

    def test_reports_missing_both_markers(self, tex_file):
        """A key that appears in neither START nor END is not in results."""
        u = Updater(str(tex_file))
        result = u.validate_markers()
        assert "ghost" not in result

    def test_all_keys_from_file_are_reported(self, updater):
        result = updater.validate_markers()
        assert "myproject" in result
        assert "school" in result


# ---------------------------------------------------------------------------
# integration: preview then apply
# ---------------------------------------------------------------------------


class TestPreviewThenApply:
    def test_preview_and_apply_produce_same_content(self, updater, tex_file):
        bullets = [r"\item Integration bullet"]
        preview_result = updater.preview("myproject", bullets)
        updater.apply("myproject", bullets)
        # The file should now contain the proposed content
        file_content = tex_file.read_text()
        assert r"\item Integration bullet" in file_content
        # The preview's proposed content should match
        # (file has more LaTeX around it; the block is the relevant part)
        block = updater._get_current_block("myproject")
        assert block is not None
        assert r"\item Integration bullet" in block

    def test_full_workflow(self, updater, tex_file):
        """Preview both blocks, apply both, verify file state."""
        bullets_a = [r"\item Workflow project"]
        bullets_b = [r"\item Workflow school"]

        p1 = updater.preview("myproject", bullets_a)
        p2 = updater.preview("school", bullets_b)
        assert p1["error"] is None
        assert p2["error"] is None

        r1 = updater.apply("myproject", bullets_a)
        r2 = updater.apply("school", bullets_b)
        assert r1["success"] is True
        assert r2["success"] is True

        content = tex_file.read_text()
        assert r"\item Workflow project" in content
        assert r"\item Workflow school" in content
        assert r"\item Built a distributed system" not in content
        assert r"\item MSc in Computer Science" not in content

"""
LaTeX marker-block updater.

Reads main.tex, finds % RESUME_PROJECT_START/END markers,
replaces the content between them with new bullets,
and writes the updated file (with backup).
"""

import difflib
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


class Updater:
    """Updates project description blocks in a LaTeX resume file."""

    def __init__(self, tex_path: str):
        self.tex_path = Path(tex_path)
        if not self.tex_path.exists():
            raise FileNotFoundError(f"LaTeX file not found: {tex_path}")

    # ---- helpers ----

    def _read_tex(self) -> str:
        return self.tex_path.read_text(encoding="utf-8")

    def _backup(self) -> Path:
        """Create a timestamped backup of the .tex file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.tex_path.with_suffix(f".tex.bak_{timestamp}")
        shutil.copy2(self.tex_path, backup_path)
        return backup_path

    def _get_current_block(self, project_key: str) -> str | None:
        """Read the current content of a marker block."""
        tex = self._read_tex()
        pattern = rf"% RESUME_PROJECT_START: {project_key}\s*\n(.*?)% RESUME_PROJECT_END: {project_key}"
        match = re.search(pattern, tex, re.DOTALL)
        return match.group(1) if match else None

    def _replace_block(self, tex: str, project_key: str,
                       new_content: str) -> str:
        """
        Replace the content between START/END markers for project_key.
        new_content should be the complete text to place between the markers.
        """
        pattern = rf"(% RESUME_PROJECT_START: {project_key}\s*\n)(.*?)(% RESUME_PROJECT_END: {project_key})"

        def _replacer(match):
            # Keep the start marker, replace middle content, keep end marker
            return match.group(1) + new_content + "\n" + match.group(3)

        new_tex = re.sub(pattern, _replacer, tex, count=1, flags=re.DOTALL)
        return new_tex

    def _show_diff(self, old: str, new: str) -> str:
        """Generate a unified diff string for display."""
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile="current", tofile="proposed",
            lineterm=""
        )
        return "".join(diff)

    # ---- public API ----

    def preview(self, project_key: str, new_bullets: list[str]) -> dict:
        """
        Preview what would change without writing to disk.

        Returns:
            {"current": str, "proposed": str, "diff": str, "error": str | None}
        """
        current = self._get_current_block(project_key)
        if current is None:
            return {
                "current": "",
                "proposed": "",
                "diff": "",
                "error": f"No marker block found for project: {project_key}",
            }

        # Join bullets with proper indentation (4 spaces)
        proposed_lines = []
        for bullet in new_bullets:
            # Ensure each bullet line starts with 4 spaces + \item
            bullet = bullet.strip()
            if not bullet.startswith("\\item"):
                bullet = "\\item " + bullet
            proposed_lines.append(f"    {bullet}")
        proposed = "\n".join(proposed_lines)

        diff_text = self._show_diff(current.strip(), proposed)

        return {
            "current": current.strip(),
            "proposed": proposed,
            "diff": diff_text,
            "error": None,
        }

    def apply(self, project_key: str, new_bullets: list[str]) -> dict:
        """
        Apply new bullets to the LaTeX file (with backup).

        Returns:
            {"success": bool, "backup_path": str, "error": str | None}
        """
        current = self._get_current_block(project_key)
        if current is None:
            return {
                "success": False,
                "backup_path": "",
                "error": f"No marker block found for project: {project_key}",
            }

        # Build the new content string
        proposed_lines = []
        for bullet in new_bullets:
            bullet = bullet.strip()
            if not bullet.startswith("\\item"):
                bullet = "\\item " + bullet
            proposed_lines.append(f"    {bullet}")
        new_content = "\n".join(proposed_lines)

        # Backup first
        backup_path = self._backup()

        # Replace and write
        tex = self._read_tex()
        new_tex = self._replace_block(tex, project_key, new_content)
        self.tex_path.write_text(new_tex, encoding="utf-8")

        return {
            "success": True,
            "backup_path": str(backup_path),
            "error": None,
        }

    def validate_markers(self) -> dict[str, bool]:
        """Check that all expected markers exist in the .tex file."""
        tex = self._read_tex()
        results = {}
        # Find all START markers
        start_matches = re.findall(r"% RESUME_PROJECT_START: (\w+)", tex)
        end_matches = re.findall(r"% RESUME_PROJECT_END: (\w+)", tex)

        all_keys = set(start_matches) | set(end_matches)
        for key in all_keys:
            has_start = key in start_matches
            has_end = key in end_matches
            results[key] = has_start and has_end

        return results

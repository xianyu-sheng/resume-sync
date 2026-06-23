"""
PDF compilation with latexmk, output management, and error handling.

Runs latexmk -xelatex from the resume source directory, copies the
resulting PDF to the configured output path, and manages backups.
"""

import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


class Builder:
    """Compiles LaTeX resume and manages PDF output."""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        build_cfg = self.config.get("build", {})
        self.engine = build_cfg.get("engine", "latexmk")
        self.args = build_cfg.get("args", ["-xelatex", "-interaction=nonstopmode"])
        self.backup_enabled = build_cfg.get("backup", True)
        self.backup_dir = Path(build_cfg.get("backup_dir", "backups"))

    # ---- helpers ----

    def _get_resume_dir(self) -> Path:
        """Return the directory containing main.tex."""
        tex_path = self.config["resume"]["tex_path"]
        return Path(tex_path).parent

    def _get_pdf_path(self) -> Path:
        """Return the expected PDF output path (alongside main.tex)."""
        tex_path = Path(self.config["resume"]["tex_path"])
        return tex_path.with_suffix(".pdf")

    def _get_output_path(self) -> Path:
        """Return the target PDF output path from config."""
        return Path(self.config["resume"]["pdf_output"])

    def _clean_aux_files(self, work_dir: Path) -> None:
        """Remove latexmk auxiliary files."""
        patterns = ["*.aux", "*.log", "*.out", "*.toc", "*.lof", "*.lot",
                     "*.bbl", "*.blg", "*.synctex.gz", "*.fdb_latexmk",
                     "*.fls", "*.nav", "*.snm", "*.vrb"]
        for pat in patterns:
            for f in work_dir.glob(pat):
                try:
                    f.unlink()
                except OSError:
                    pass

    def _parse_errors(self, log_text: str) -> list[str]:
        """Extract LaTeX error lines from log output."""
        errors = []
        for line in log_text.split("\n"):
            if line.startswith("!") or "Error:" in line:
                errors.append(line.strip())
                # Also grab the context line that follows
        return errors[:20]  # limit to 20

    def _copy_with_retry(self, src: Path, dst: Path, retries: int = 3) -> bool:
        """Copy file, retrying on permission error (e.g. file locked by viewer)."""
        for attempt in range(retries):
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                return True
            except PermissionError:
                if attempt < retries - 1:
                    time.sleep(1)
                else:
                    raise
        return False

    def _create_backup(self, pdf_path: Path) -> Path | None:
        """Create a timestamped backup of the compiled PDF."""
        if not self.backup_enabled:
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"Agent开发简历_{timestamp}.pdf"
        backup_path = self.backup_dir / backup_name
        shutil.copy2(pdf_path, backup_path)
        return backup_path

    # ---- public API ----

    def compile(self) -> dict:
        """
        Compile the LaTeX resume to PDF.

        Returns:
            {"success": bool, "pdf_path": str, "backup_path": str | None,
             "errors": [...], "warnings": [...], "output": str}
        """
        work_dir = self._get_resume_dir()
        tex_file = Path(self.config["resume"]["tex_path"]).name
        output_path = self._get_output_path()

        # Build command
        cmd = [self.engine] + self.args + [str(tex_file)]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=300,  # 5 min max for compilation
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "pdf_path": "",
                "backup_path": None,
                "errors": ["Compilation timed out after 5 minutes"],
                "warnings": [],
                "output": "",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "pdf_path": "",
                "backup_path": None,
                "errors": [f"latexmk not found. Is TeX Live in PATH? Engine: {self.engine}"],
                "warnings": [],
                "output": "",
            }

        combined_output = result.stdout + "\n" + result.stderr
        errors = self._parse_errors(combined_output)

        if result.returncode != 0:
            return {
                "success": False,
                "pdf_path": "",
                "backup_path": None,
                "errors": errors or ["latexmk exited with code " + str(result.returncode)],
                "warnings": [],
                "output": combined_output[-3000:],  # last 3000 chars
            }

        # Locate compiled PDF
        pdf_path = self._get_pdf_path()
        if not pdf_path.exists():
            return {
                "success": False,
                "pdf_path": "",
                "backup_path": None,
                "errors": [f"PDF not found at expected location: {pdf_path}"],
                "warnings": [],
                "output": combined_output[-3000:],
            }

        # Create backup
        backup_path = self._create_backup(pdf_path)

        # Copy to output location (with retry on file lock)
        try:
            self._copy_with_retry(pdf_path, output_path)
        except PermissionError:
            return {
                "success": True,
                "pdf_path": str(pdf_path),
                "backup_path": str(backup_path) if backup_path else None,
                "errors": [],
                "warnings": [f"Could not overwrite {output_path} — file is locked. PDF at {pdf_path}"],
                "output": combined_output[-3000:],
            }

        # Clean aux files
        self._clean_aux_files(work_dir)

        return {
            "success": True,
            "pdf_path": str(output_path),
            "backup_path": str(backup_path) if backup_path else None,
            "errors": [],
            "warnings": [],
            "output": combined_output[-3000:],
        }

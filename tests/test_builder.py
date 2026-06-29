"""Tests for Builder class — PDF compilation, error handling, backups."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.builder import Builder


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def builder() -> Builder:
    """Create a Builder with a test configuration (no real LaTeX)."""
    b = Builder.__new__(Builder)
    b.config = {
        "resume": {
            "tex_path": "D:/resume/main.tex",
            "pdf_output": "D:/resume/output.pdf",
        },
        "build": {
            "engine": "latexmk",
            "args": ["-xelatex", "-interaction=nonstopmode"],
            "backup": True,
            "backup_dir": "backups",
        },
    }
    b.engine = "latexmk"
    b.args = ["-xelatex", "-interaction=nonstopmode"]
    b.backup_enabled = True
    b.backup_dir = Path("backups")
    return b


@pytest.fixture
def mock_completed_process() -> MagicMock:
    """Return a MagicMock that mimics a successful subprocess.CompletedProcess."""
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.returncode = 0
    cp.stdout = b""
    cp.stderr = b""
    return cp


# ═══════════════════════════════════════════════════════════════════
# _find_latexmk
# ═══════════════════════════════════════════════════════════════════


class TestFindLatexmk:
    """Locating the latexmk executable."""

    def test_uses_engine_from_config(self, builder: Builder):
        """The engine attribute should default to ``latexmk``."""
        assert builder.engine == "latexmk"

    def test_custom_engine(self):
        """Builder should honour a different engine in config."""
        b = Builder.__new__(Builder)
        b.config = {
            "resume": {"tex_path": "main.tex", "pdf_output": "out.pdf"},
            "build": {
                "engine": "pdflatex",
                "args": ["-interaction=nonstopmode"],
                "backup": False,
                "backup_dir": "backups",
            },
        }
        b.engine = "pdflatex"
        assert b.engine == "pdflatex"


# ═══════════════════════════════════════════════════════════════════
# _build_command
# ═══════════════════════════════════════════════════════════════════


class TestBuildCommand:
    """Constructing the latexmk command."""

    def test_constructs_correct_latexmk_command(self, builder: Builder):
        """The command list should be ``[engine] + args + [tex_filename]``."""
        with patch("src.builder.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=b"", stderr=b""
            )
            with patch.object(builder, "_create_backup", return_value=None):
                with patch.object(builder, "_copy_with_retry"):
                    with patch.object(builder, "_clean_aux_files"):
                        with patch.object(Path, "exists", return_value=True):
                            builder.compile()

        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert cmd[0] == "latexmk"
        assert "-xelatex" in cmd
        assert "-interaction=nonstopmode" in cmd
        # The last argument should be the .tex filename
        assert cmd[-1] == "main.tex"

    def test_uses_cwd_of_resume_dir(self, builder: Builder):
        with patch("src.builder.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=b"", stderr=b""
            )
            with patch.object(builder, "_create_backup", return_value=None):
                with patch.object(builder, "_copy_with_retry"):
                    with patch.object(builder, "_clean_aux_files"):
                        with patch.object(Path, "exists", return_value=True):
                            builder.compile()

        _args, kwargs = mock_run.call_args
        assert kwargs["cwd"] == str(Path("D:/resume"))

    def test_respects_custom_args(self, builder: Builder):
        """Custom args in config should appear in the command."""
        builder.args = ["-pdf", "-silent"]
        with patch("src.builder.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=b"", stderr=b""
            )
            with patch.object(builder, "_create_backup", return_value=None):
                with patch.object(builder, "_copy_with_retry"):
                    with patch.object(builder, "_clean_aux_files"):
                        with patch.object(Path, "exists", return_value=True):
                            builder.compile()

        args, _kwargs = mock_run.call_args
        cmd = args[0]
        assert "-pdf" in cmd
        assert "-silent" in cmd


# ═══════════════════════════════════════════════════════════════════
# _parse_errors
# ═══════════════════════════════════════════════════════════════════


class TestExtractErrors:
    """Parsing LaTeX log output for error lines."""

    def test_finds_lines_starting_with_exclamation(self, builder: Builder):
        log = """\
This is XeTeX, Version 3.14159265
! Undefined control sequence.
l.12 \\foo
! LaTeX Error: File `missing.tex' not found.
"""
        errors = builder._parse_errors(log)
        assert len(errors) == 2
        assert "! Undefined control sequence." in errors
        assert "! LaTeX Error: File `missing.tex' not found." in errors

    def test_finds_lines_containing_Error_colon(self, builder: Builder):
        log = """\
Some output
Error: Cannot find file
more output
! Fatal error occurred.
"""
        errors = builder._parse_errors(log)
        assert "Error: Cannot find file" in errors
        assert "! Fatal error occurred." in errors

    def test_returns_empty_list_for_clean_log(self, builder: Builder):
        log = """\
This is XeTeX, Version 3.14159265
Output written on main.pdf (1 page).
Transcript written on main.log.
"""
        assert builder._parse_errors(log) == []

    def test_limits_to_20_errors(self, builder: Builder):
        log = "\n".join("! Error number " + str(i) for i in range(50))
        errors = builder._parse_errors(log)
        assert len(errors) == 20

    def test_strips_whitespace_from_error_lines(self, builder: Builder):
        log = "! Extra space error  \n! Another  "
        errors = builder._parse_errors(log)
        assert errors == ["! Extra space error", "! Another"]

    def test_handles_empty_log(self, builder: Builder):
        assert builder._parse_errors("") == []


# ═══════════════════════════════════════════════════════════════════
# _clean_aux_files
# ═══════════════════════════════════════════════════════════════════


class TestCleanAuxFiles:
    """Removing latexmk auxiliary files."""

    def test_removes_expected_aux_extensions(self, builder: Builder):
        """All standard auxiliary extensions should be globbed."""
        ext_map = {
            "*.aux": ["main.aux"],
            "*.log": ["main.log"],
            "*.out": ["main.out"],
            "*.toc": ["main.toc"],
            "*.lof": [],
            "*.lot": [],
            "*.bbl": [],
            "*.blg": [],
            "*.synctex.gz": ["main.synctex.gz"],
            "*.fdb_latexmk": ["main.fdb_latexmk"],
            "*.fls": ["main.fls"],
            "*.nav": [],
            "*.snm": [],
            "*.vrb": [],
        }
        with patch.object(Path, "glob") as mock_glob:
            # Make glob return the expected files for each pattern
            def side_effect(pattern: str):
                files = ext_map.get(pattern, [])
                return [Path(f) for f in files]

            mock_glob.side_effect = side_effect

            with patch.object(Path, "unlink") as mock_unlink:
                builder._clean_aux_files(Path("D:/resume"))

                # Should have called glob for each pattern
                assert mock_glob.call_count == len(ext_map)
                # Should have unlinked every listed file
                assert mock_unlink.call_count == sum(
                    len(v) for v in ext_map.values()
                )

    def test_silently_ignores_oserror(self, builder: Builder):
        """OSError during unlink should be caught and ignored."""
        with patch.object(Path, "glob", return_value=[Path("main.aux")]):
            with patch.object(
                Path, "unlink", side_effect=OSError("Permission denied")
            ):
                # Should not raise
                builder._clean_aux_files(Path("D:/resume"))

    def test_calls_glob_on_work_dir(self, builder: Builder):
        with patch.object(Path, "glob", return_value=[]) as mock_glob:
            builder._clean_aux_files(Path("D:/project"))
            # Should call glob on each pattern
            patterns_called = [call[0][0] for call in mock_glob.call_args_list]
            assert "*.aux" in patterns_called
            assert "*.log" in patterns_called
            assert "*.out" in patterns_called
            assert "*.fdb_latexmk" in patterns_called


# ═══════════════════════════════════════════════════════════════════
# _copy_with_retry  (复制 PDF 时的文件锁定重试)
# ═══════════════════════════════════════════════════════════════════


class TestCopyWithRetry:
    """Copying the PDF with retry on permission errors."""

    def test_succeeds_on_first_attempt(self, builder: Builder):
        src = Path("src.pdf")
        dst = Path("dst.pdf")
        with patch("shutil.copy2") as mock_copy:
            result = builder._copy_with_retry(src, dst)
            assert result is True
            mock_copy.assert_called_once_with(src, dst)

    def test_retries_on_permission_error_then_succeeds(
        self, builder: Builder
    ):
        """Should retry when file is locked, and succeed on a later attempt."""
        src = Path("src.pdf")
        dst = Path("dst.pdf")
        copy_mock = MagicMock()
        # Fail first 2 times, succeed on 3rd
        copy_mock.side_effect = [
            PermissionError("locked"),
            PermissionError("locked"),
            None,
        ]
        with patch("shutil.copy2", copy_mock):
            with patch("time.sleep") as mock_sleep:
                result = builder._copy_with_retry(src, dst, retries=3)
                assert result is True
                assert copy_mock.call_count == 3
                assert mock_sleep.call_count == 2

    def test_raises_after_all_retries_exhausted(self, builder: Builder):
        """Should re-raise PermissionError after all retries fail."""
        src = Path("src.pdf")
        dst = Path("dst.pdf")
        with patch("shutil.copy2", side_effect=PermissionError("locked")):
            with patch("time.sleep"):
                with pytest.raises(PermissionError):
                    builder._copy_with_retry(src, dst, retries=3)

    def test_creates_parent_directory(self, builder: Builder):
        """Should create parent directories of dst before copying."""
        src = Path("src.pdf")
        dst = Path("subdir/dst.pdf")
        with patch("shutil.copy2") as mock_copy:
            with patch.object(Path, "mkdir") as mock_mkdir:
                result = builder._copy_with_retry(src, dst)
                assert result is True
                mock_mkdir.assert_called_once_with(
                    parents=True, exist_ok=True
                )
                mock_copy.assert_called_once_with(src, dst)

    def test_default_retries_arg(self, builder: Builder):
        """Default retries should be 3."""
        src = Path("src.pdf")
        dst = Path("dst.pdf")
        with patch("shutil.copy2", side_effect=PermissionError("locked")):
            with patch("time.sleep"):
                with pytest.raises(PermissionError):
                    # Use default retries=3
                    builder._copy_with_retry(src, dst)


# ═══════════════════════════════════════════════════════════════════
# _create_backup
# ═══════════════════════════════════════════════════════════════════


class TestCreateBackup:
    """Creating timestamped PDF backups."""

    def test_creates_backup_in_backup_dir(self, builder: Builder):
        pdf_path = Path("D:/resume/main.pdf")
        with patch("shutil.copy2") as mock_copy:
            with patch.object(Path, "mkdir") as mock_mkdir:
                with patch(
                    "src.builder.datetime"
                ) as mock_dt:
                    mock_dt.now.return_value.strftime.return_value = (
                        "20260628_120000"
                    )
                    backup = builder._create_backup(pdf_path)

        assert backup is not None
        assert backup.parent == Path("backups")
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_copy.assert_called_once_with(pdf_path, backup)

    def test_backup_filename_contains_timestamp(self, builder: Builder):
        pdf_path = Path("D:/resume/main.pdf")
        with patch("shutil.copy2"):
            with patch.object(Path, "mkdir"):
                with patch(
                    "src.builder.datetime"
                ) as mock_dt:
                    mock_dt.now.return_value.strftime.return_value = (
                        "20260628_120000"
                    )
                    backup = builder._create_backup(pdf_path)

        assert backup is not None
        assert "20260628_120000" in backup.name

    def test_backup_filename_uses_pdf_stem(self, builder: Builder):
        pdf_path = Path("D:/resume/main.pdf")
        with patch("shutil.copy2"):
            with patch.object(Path, "mkdir"):
                with patch(
                    "src.builder.datetime"
                ) as mock_dt:
                    mock_dt.now.return_value.strftime.return_value = (
                        "20260628_120000"
                    )
                    backup = builder._create_backup(pdf_path)

        assert backup is not None
        # The stem comes from config's pdf_output filename
        assert backup.name.startswith("output_")

    def test_returns_none_when_backup_disabled(self, builder: Builder):
        builder.backup_enabled = False
        pdf_path = Path("D:/resume/main.pdf")
        with patch("shutil.copy2") as mock_copy:
            backup = builder._create_backup(pdf_path)
            assert backup is None
            mock_copy.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# build  /  compile
# ═══════════════════════════════════════════════════════════════════


class TestCompile:
    """Top-level ``compile()``: success, error, timeout, and missing executable."""

    # -- Successful compilation -----------------------------------

    def test_returns_success_on_clean_compilation(
        self, builder: Builder, mock_completed_process: MagicMock
    ):
        with patch("src.builder.subprocess.run") as mock_run:
            mock_run.return_value = mock_completed_process
            with patch.object(Path, "exists", return_value=True):
                with patch.object(
                    builder, "_create_backup", return_value=Path("backup.pdf")
                ):
                    with patch.object(builder, "_copy_with_retry"):
                        with patch.object(builder, "_clean_aux_files"):
                            result = builder.compile()

        assert result["success"] is True
        assert result["pdf_path"] == str(Path("D:/resume/output.pdf"))
        assert result["backup_path"] == "backup.pdf"
        assert result["errors"] == []
        assert result["warnings"] == []

    def test_success_includes_output(
        self, builder: Builder, mock_completed_process: MagicMock
    ):
        mock_completed_process.stdout = b"Output written on main.pdf"
        with patch("src.builder.subprocess.run") as mock_run:
            mock_run.return_value = mock_completed_process
            with patch.object(Path, "exists", return_value=True):
                with patch.object(builder, "_create_backup", return_value=None):
                    with patch.object(builder, "_copy_with_retry"):
                        with patch.object(builder, "_clean_aux_files"):
                            result = builder.compile()

        assert "Output written on main.pdf" in result["output"]

    # -- Compilation errors ---------------------------------------

    def test_returns_error_dict_with_extracted_errors(
        self, builder: Builder, mock_completed_process: MagicMock
    ):
        mock_completed_process.returncode = 1
        mock_completed_process.stdout = b"! Undefined control sequence.\n! LaTeX Error."
        mock_completed_process.stderr = b""
        with patch("src.builder.subprocess.run") as mock_run:
            mock_run.return_value = mock_completed_process
            result = builder.compile()

        assert result["success"] is False
        assert result["pdf_path"] == ""
        assert len(result["errors"]) == 2
        assert "! Undefined control sequence." in result["errors"]
        assert "! LaTeX Error." in result["errors"]

    def test_error_without_exclamation_uses_return_code_fallback(
        self, builder: Builder, mock_completed_process: MagicMock
    ):
        """If _parse_errors returns empty but returncode != 0, generate a fallback."""
        mock_completed_process.returncode = 2
        mock_completed_process.stdout = b"Warning: no errors here"
        mock_completed_process.stderr = b""
        with patch("src.builder.subprocess.run") as mock_run:
            mock_run.return_value = mock_completed_process
            result = builder.compile()

        assert result["success"] is False
        assert len(result["errors"]) == 1
        assert "latexmk exited with code 2" in result["errors"][0]

    # -- Timeout handling -----------------------------------------

    def test_handles_timeout_gracefully(self, builder: Builder):
        with patch(
            "src.builder.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd="latexmk", timeout=300
            ),
        ):
            result = builder.compile()

        assert result["success"] is False
        assert result["pdf_path"] == ""
        assert len(result["errors"]) == 1
        assert "Compilation timed out" in result["errors"][0]

    # -- Missing latexmk ------------------------------------------

    def test_handles_missing_latexmk(self, builder: Builder):
        with patch(
            "src.builder.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            result = builder.compile()

        assert result["success"] is False
        assert result["pdf_path"] == ""
        assert len(result["errors"]) == 1
        assert "latexmk not found" in result["errors"][0]

    # -- PDF not found after compilation --------------------------

    def test_pdf_not_found_after_compilation(
        self, builder: Builder, mock_completed_process: MagicMock
    ):
        with patch("src.builder.subprocess.run") as mock_run:
            mock_run.return_value = mock_completed_process
            with patch.object(
                Path, "exists", return_value=False
            ):  # PDF not found
                result = builder.compile()

        assert result["success"] is False
        assert result["pdf_path"] == ""
        assert any("PDF not found" in e for e in result["errors"])

    # -- File lock / PermissionError on copy ---------------------

    def test_permission_error_on_copy_yields_warning(
        self, builder: Builder, mock_completed_process: MagicMock
    ):
        with patch("src.builder.subprocess.run") as mock_run:
            mock_run.return_value = mock_completed_process
            with patch.object(Path, "exists", return_value=True):
                with patch.object(
                    builder, "_create_backup", return_value=None
                ):
                    with patch.object(
                        builder,
                        "_copy_with_retry",
                        side_effect=PermissionError("locked"),
                    ):
                        with patch.object(builder, "_clean_aux_files"):
                            result = builder.compile()

        assert result["success"] is True  # compilation itself succeeded
        assert result["pdf_path"] == str(Path("D:/resume/main.pdf"))
        assert len(result["warnings"]) == 1
        assert "locked" in result["warnings"][0].lower() or "locked" in result[
            "warnings"
        ][0]

    # -- Auxiliary files cleanup ----------------------------------

    def test_clean_aux_called_on_success(
        self, builder: Builder, mock_completed_process: MagicMock
    ):
        with patch("src.builder.subprocess.run") as mock_run:
            mock_run.return_value = mock_completed_process
            with patch.object(Path, "exists", return_value=True):
                with patch.object(builder, "_create_backup", return_value=None):
                    with patch.object(builder, "_copy_with_retry"):
                        with patch.object(
                            builder, "_clean_aux_files"
                        ) as mock_clean:
                            builder.compile()

        mock_clean.assert_called_once()

    # -- _parse_errors is called with combined output ------------

    def test_parse_errors_called_with_combined_output(
        self, builder: Builder, mock_completed_process: MagicMock
    ):
        mock_completed_process.stdout = b"stdout line\n"
        mock_completed_process.stderr = b"stderr line\n"
        with patch("src.builder.subprocess.run") as mock_run:
            mock_run.return_value = mock_completed_process
            with patch.object(Path, "exists", return_value=True):
                with patch.object(builder, "_create_backup", return_value=None):
                    with patch.object(builder, "_copy_with_retry"):
                        with patch.object(builder, "_clean_aux_files"):
                            with patch.object(
                                builder, "_parse_errors"
                            ) as mock_parse:
                                builder.compile()
                                # _parse_errors should receive combined stdout+stderr
                                combined = mock_parse.call_args[0][0]
                                assert "stdout line" in combined
                                assert "stderr line" in combined

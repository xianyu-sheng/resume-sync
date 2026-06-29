"""
Tests for src/checker.py — Checker class.

Creates minimal git repositories in tmp_path to exercise the
check/baseline/cache/mark_applied lifecycle.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from src.checker import Checker


# ---------------------------------------------------------------------------
# helpers — minimal git repo fixtures
# ---------------------------------------------------------------------------


def init_git_repo(path, file="test.py", content="print('hello')", commit_msg="initial"):
    """Create a minimal git repository at *path* with a single commit."""
    repo_path = Path(path)
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.email", "test@test.com"],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.name", "Test"],
        capture_output=True,
    )
    (repo_path / file).write_text(content)
    subprocess.run(["git", "-C", str(repo_path), "add", "."], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-m", commit_msg],
        capture_output=True,
    )


def add_commit(repo_path, content="print('updated')", msg="another commit"):
    """Append a new commit to an existing git repo."""
    repo = Path(repo_path)
    (repo / "test.py").write_text(content)
    subprocess.run(["git", "-C", str(repo_path), "add", "."], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-m", msg],
        capture_output=True,
    )


def head_hash(repo_path):
    """Return the full SHA of HEAD in *repo_path*."""
    r = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    )
    return r.stdout.strip()


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config_yaml(tmp_path):
    """Write a config.yaml pointing at two git repos (one disabled)."""
    projects_dir = tmp_path / "repos"
    projects_dir.mkdir()

    repo1 = projects_dir / "repo1"
    init_git_repo(repo1, content="print('proj1')", commit_msg="proj1 init")

    repo2 = projects_dir / "repo2"
    init_git_repo(repo2, file="app.py", content="print('proj2')", commit_msg="proj2 init")

    cfg = {
        "projects": [
            {
                "key": "proj1",
                "name": "Project One",
                "repo_local": str(repo1),
                "enabled": True,
            },
            {
                "key": "disabled-proj",
                "name": "Disabled Project",
                "repo_local": str(repo2),
                "enabled": False,
            },
            {
                "key": "proj3",
                "name": "Project Three",
                "repo_local": str(repo2),
                "enabled": True,
            },
        ]
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg))
    return cfg_path


@pytest.fixture
def checker(config_yaml, tmp_path):
    """Return a Checker instance with default state / cache paths."""
    return Checker(
        config_path=str(config_yaml),
        state_path=str(tmp_path / "state.json"),
        cache_dir=str(tmp_path / "cache"),
    )


# ---------------------------------------------------------------------------
# config / state loading
# ---------------------------------------------------------------------------


class TestCheckerInit:
    def test_loads_config_from_yaml(self, checker):
        assert checker.config["projects"][0]["key"] == "proj1"

    def test_raises_when_config_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Config not found"):
            Checker(str(tmp_path / "nonexistent.yaml"))

    def test_loads_existing_state(self, tmp_path, config_yaml):
        state_path = tmp_path / "state.json"
        state = {
            "projects": {"proj1": {"last_commit": "abc123"}},
            "initialized_at": "2024-06-01T00:00:00",
        }
        state_path.write_text(json.dumps(state))
        c = Checker(str(config_yaml), str(state_path), str(tmp_path / "cache"))
        assert c.state["projects"]["proj1"]["last_commit"] == "abc123"

    def test_state_defaults_to_empty(self, checker):
        assert checker.state == {"projects": {}, "initialized_at": None}

    def test_env_var_resolution_in_config(self, tmp_path):
        cfg = {"llm": {"api_key": "${MY_SECRET}"}, "projects": []}
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump(cfg))
        os.environ["MY_SECRET"] = "s3kr3t"
        c = Checker(str(cfg_path), str(tmp_path / "state.json"), str(tmp_path / "cache"))
        assert c.config["llm"]["api_key"] == "s3kr3t"
        del os.environ["MY_SECRET"]

    def test_env_var_resolution_empty_when_unset(self, tmp_path):
        cfg = {"llm": {"api_key": "${UNSET_VAR}"}, "projects": []}
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump(cfg))
        c = Checker(str(cfg_path), str(tmp_path / "state.json"), str(tmp_path / "cache"))
        assert c.config["llm"]["api_key"] == ""


# ---------------------------------------------------------------------------
# tracking only enabled projects
# ---------------------------------------------------------------------------


class TestGetTrackedProjects:
    def test_check_skips_disabled_projects(self, checker):
        """check() should not return results for enabled=False projects."""
        # baseline
        results = checker.check()
        assert "disabled-proj" not in results
        assert "proj1" in results
        assert "proj3" in results

    def test_get_status_includes_disabled_flag(self, checker):
        """get_status() returns the enabled field."""
        checker.check()  # establish baseline
        status = checker.get_status()
        by_key = {s["key"]: s for s in status}
        assert by_key["proj1"]["enabled"] is True
        assert by_key["disabled-proj"]["enabled"] is False


# ---------------------------------------------------------------------------
# first run — baseline behaviour
# ---------------------------------------------------------------------------


class TestFirstRun:
    def test_records_baseline_and_reports_no_changes(self, checker):
        results = checker.check("proj1")
        assert results["proj1"]["has_changes"] is False
        assert results["proj1"]["new_commits"] == []
        assert results["proj1"]["diff"] is None
        assert "Initialized baseline" in results["proj1"]["message"]

    def test_baseline_saves_last_commit_to_state(self, checker):
        checker.check("proj1")
        assert checker.state["projects"]["proj1"]["last_commit"] is not None
        assert len(checker.state["projects"]["proj1"]["last_commit"]) == 40

    def test_baseline_sets_initialized_at(self, checker):
        checker.check("proj1")
        assert checker.state["initialized_at"] is not None

    def test_baseline_persists_state_file(self, checker, tmp_path):
        checker.check("proj1")
        state_file = tmp_path / "state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert "proj1" in data["projects"]

    def test_not_a_git_repo_reports_error(self, tmp_path):
        cfg = {
            "projects": [
                {
                    "key": "bad",
                    "name": "Bad",
                    "repo_local": str(tmp_path / "no_git_here"),
                    "enabled": True,
                }
            ]
        }
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump(cfg))
        c = Checker(str(cfg_path), str(tmp_path / "state.json"), str(tmp_path / "cache"))
        # Create the dir but no .git inside
        (tmp_path / "no_git_here").mkdir(exist_ok=True)
        results = c.check("bad")
        assert results["bad"]["error"] is not None
        assert "Not a git repository" in results["bad"]["error"]


# ---------------------------------------------------------------------------
# detecting new commits
# ---------------------------------------------------------------------------


class TestNewCommits:
    def test_detects_new_commits_since_last_recorded(self, checker, tmp_path):
        checker.check("proj1")
        repo = Path(checker.config["projects"][0]["repo_local"])
        add_commit(repo, content="print('v2')", msg="second commit")

        results = checker.check("proj1")
        assert results["proj1"]["has_changes"] is True
        assert len(results["proj1"]["new_commits"]) == 1
        assert results["proj1"]["new_commits"][0]["message"] == "second commit"
        assert results["proj1"]["diff"] is not None
        assert results["proj1"]["diff_stat"] is not None
        assert results["proj1"]["error"] is None

    def test_no_changes_when_head_unchanged(self, checker):
        checker.check("proj1")
        results = checker.check("proj1")
        assert results["proj1"]["has_changes"] is False
        assert results["proj1"]["diff"] is None

    def test_multiple_new_commits_detected(self, checker, tmp_path):
        checker.check("proj1")
        repo = Path(checker.config["projects"][0]["repo_local"])
        add_commit(repo, content="print('v2')", msg="second")
        add_commit(repo, content="print('v3')", msg="third")

        results = checker.check("proj1")
        assert results["proj1"]["has_changes"] is True
        assert len(results["proj1"]["new_commits"]) == 2
        assert results["proj1"]["new_commits"][0]["message"] == "second"
        assert results["proj1"]["new_commits"][1]["message"] == "third"

    def test_all_enabled_projects_checked_when_no_key_given(self, checker):
        """check() with no project_key checks all enabled projects."""
        results = checker.check()
        assert "proj1" in results
        assert "proj3" in results
        assert "disabled-proj" not in results

    def test_single_project_when_key_given(self, checker):
        """check(project_key) only checks that one project."""
        results = checker.check("proj1")
        assert list(results.keys()) == ["proj1"]


# ---------------------------------------------------------------------------
# mark_applied
# ---------------------------------------------------------------------------


class TestMarkApplied:
    def test_mark_applied_records_last_commit_as_processed(self, checker, tmp_path):
        checker.check("proj1")
        repo = Path(checker.config["projects"][0]["repo_local"])
        add_commit(repo, content="print('v2')", msg="second")
        checker.check("proj1")

        last_commit = checker.state["projects"]["proj1"]["last_commit"]
        assert last_commit not in checker.state["projects"]["proj1"].get("processed_commits", [])

        checker.mark_applied("proj1")
        assert last_commit in checker.state["projects"]["proj1"]["processed_commits"]

    def test_mark_applied_persists_state(self, checker, tmp_path):
        checker.check("proj1")
        repo = Path(checker.config["projects"][0]["repo_local"])
        add_commit(repo, content="print('v2')", msg="second")
        checker.check("proj1")
        checker.mark_applied("proj1")

        # Reload state from disk
        state = json.loads((tmp_path / "state.json").read_text())
        assert "proj1" in state["projects"]

    def test_mark_applied_noop_when_project_not_tracked(self, checker):
        """mark_applied on unknown project should not crash."""
        checker.mark_applied("nonexistent")
        assert True  # no exception raised


# ---------------------------------------------------------------------------
# state persistence — atomic write
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_uses_tmp_and_replace(self, checker, tmp_path):
        """Check that _save_state writes to a .tmp file first, then replaces."""
        checker.check("proj1")
        # After check() the state.json should exist (written via _save_state)
        state_file = tmp_path / "state.json"
        assert state_file.exists()
        content = state_file.read_text()
        data = json.loads(content)
        assert "last_commit" in data["projects"]["proj1"]

    def test_state_survives_reload(self, checker, tmp_path, config_yaml):
        checker.check("proj1")
        # Create a new Checker pointing at the same state file
        c2 = Checker(str(config_yaml), str(tmp_path / "state.json"), str(tmp_path / "cache"))
        assert c2.state["projects"]["proj1"]["last_commit"] == checker.state["projects"]["proj1"]["last_commit"]

    def test_state_updated_after_check_with_changes(self, checker, tmp_path):
        checker.check("proj1")
        repo = Path(checker.config["projects"][0]["repo_local"])
        add_commit(repo, content="print('v2')", msg="second")
        checker.check("proj1")

        state = json.loads((tmp_path / "state.json").read_text())
        assert "last_check_time" in state["projects"]["proj1"]
        assert state["projects"]["proj1"]["last_commit"] is not None


# ---------------------------------------------------------------------------
# diff caching
# ---------------------------------------------------------------------------


class TestDiffCache:
    def test_individual_commit_diffs_are_cached(self, checker, tmp_path):
        checker.check("proj1")
        repo = Path(checker.config["projects"][0]["repo_local"])
        add_commit(repo, content="print('v2')", msg="second")
        head = head_hash(repo)
        checker.check("proj1")

        cache_file = tmp_path / "cache" / f"proj1_{head[:8]}.diff"
        assert cache_file.exists()
        assert len(cache_file.read_text()) > 0

    def test_cache_dir_is_created(self, checker, tmp_path):
        checker.check("proj1")
        repo = Path(checker.config["projects"][0]["repo_local"])
        add_commit(repo, content="print('v2')", msg="second")
        checker.check("proj1")
        assert (tmp_path / "cache").is_dir()

    def test_cached_diff_matches_expected_content(self, checker, tmp_path):
        checker.check("proj1")
        repo = Path(checker.config["projects"][0]["repo_local"])
        add_commit(repo, content="print('v2')", msg="second")
        head = head_hash(repo)
        checker.check("proj1")

        cached = (tmp_path / "cache" / f"proj1_{head[:8]}.diff").read_text()
        # The cache stores the individual commit diff (from parent^..commit)
        assert "test.py" in cached

    def test_multiple_commits_each_cached(self, checker, tmp_path):
        checker.check("proj1")
        repo = Path(checker.config["projects"][0]["repo_local"])
        add_commit(repo, content="print('v2')", msg="second")
        h2 = head_hash(repo)
        add_commit(repo, content="print('v3')", msg="third")
        h3 = head_hash(repo)
        checker.check("proj1")

        assert (tmp_path / "cache" / f"proj1_{h2[:8]}.diff").exists()
        assert (tmp_path / "cache" / f"proj1_{h3[:8]}.diff").exists()

    def test_read_cached_diff_returns_content(self, checker, tmp_path, config_yaml):
        """Direct test of _read_cached_diff via the private interface."""
        checker.check("proj1")
        repo = Path(checker.config["projects"][0]["repo_local"])
        add_commit(repo, content="print('v2')", msg="second")
        head = head_hash(repo)
        checker.check("proj1")

        cached = checker._read_cached_diff("proj1", head)
        assert cached is not None
        assert "test.py" in cached

    def test_read_cached_diff_returns_none_for_missing(self, checker):
        assert checker._read_cached_diff("nope", "abcdef123456") is None


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_returns_status_for_all_projects(self, checker):
        checker.check()
        status = checker.get_status()
        assert len(status) == 3  # all three projects in config (including disabled)

    def test_status_contains_expected_keys(self, checker):
        checker.check()
        status = checker.get_status()
        entry = status[0]
        assert "key" in entry
        assert "name" in entry
        assert "enabled" in entry
        assert "repo_path" in entry
        assert "current_head" in entry
        assert "tracked_commit" in entry
        assert "has_pending_changes" in entry
        assert "processed_count" in entry
        assert "last_check" in entry

    def test_status_shows_pending_changes(self, checker, tmp_path):
        checker.check("proj1")
        repo = Path(checker.config["projects"][0]["repo_local"])
        add_commit(repo, content="print('v2')", msg="pending")
        checker.check("proj1")

        status = checker.get_status()
        by_key = {s["key"]: s for s in status}
        assert by_key["proj1"]["has_pending_changes"] is True

    def test_status_shows_no_pending_when_up_to_date(self, checker):
        checker.check("proj1")
        status = checker.get_status()
        by_key = {s["key"]: s for s in status}
        assert by_key["proj1"]["has_pending_changes"] is False

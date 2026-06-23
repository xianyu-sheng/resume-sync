"""
Git repository change detection with caching.

Reads config.yaml, checks local git repos for new commits since last
recorded state, extracts diffs, and manages the state.json + cache.
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


class Checker:
    """Checks tracked git repositories for changes."""

    def __init__(self, config_path: str = "config.yaml",
                 state_path: str = "state.json",
                 cache_dir: str = "cache"):
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)
        self.cache_dir = Path(cache_dir)
        self.config = self._load_config()
        self.state = self._load_state()

    # ---- config / state I/O ----

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config not found: {self.config_path}")
        with open(self.config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        # Resolve env-var placeholders
        self._resolve_env_vars(cfg, {})
        return cfg

    @staticmethod
    def _resolve_env_vars(obj, _path):
        """Replace '${VAR_NAME}' strings in config with env-var values."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                    env_var = v[2:-1]
                    obj[k] = os.environ.get(env_var, "")
                elif isinstance(v, (dict, list)):
                    Checker._resolve_env_vars(v, None)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, str) and item.startswith("${") and item.endswith("}"):
                    env_var = item[2:-1]
                    obj[i] = os.environ.get(env_var, "")
                elif isinstance(item, (dict, list)):
                    Checker._resolve_env_vars(item, None)

    def _load_state(self) -> dict:
        if self.state_path.exists():
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"projects": {}, "initialized_at": None}

    def _save_state(self) -> None:
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    # ---- git helpers ----

    @staticmethod
    def _git(repo_path: str, *args: str) -> subprocess.CompletedProcess:
        cmd = ["git", "-C", repo_path] + list(args)
        return subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=120, encoding="utf-8", errors="replace"
        )

    def _get_head(self, repo_path: str) -> str | None:
        """Return current HEAD commit hash, or None if not a git repo."""
        r = self._git(repo_path, "rev-parse", "HEAD")
        if r.returncode == 0:
            return r.stdout.strip()
        return None

    def _get_new_commits(self, repo_path: str, since_commit: str) -> list[dict]:
        """Return list of {hash, message, date} for commits since `since_commit`."""
        r = self._git(
            repo_path, "log",
            f"{since_commit}..HEAD",
            "--pretty=format:%H||%s||%ci",
            "--reverse"
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        commits = []
        for line in r.stdout.strip().split("\n"):
            parts = line.split("||", 2)
            if len(parts) == 3:
                commits.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "date": parts[2],
                })
        return commits

    def _get_diff(self, repo_path: str, since_commit: str) -> str:
        """Return git diff between since_commit and HEAD."""
        r = self._git(repo_path, "diff", f"{since_commit}..HEAD")
        if r.returncode == 0:
            return r.stdout.strip()
        return ""

    def _get_diff_stat(self, repo_path: str, since_commit: str) -> str:
        """Return git diff --stat summary."""
        r = self._git(repo_path, "diff", "--stat", f"{since_commit}..HEAD")
        if r.returncode == 0:
            return r.stdout.strip()
        return ""

    # ---- cache ----

    def _cache_diff(self, project_key: str, commit_hash: str, diff: str) -> Path:
        """Save diff to cache directory and return path."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self.cache_dir / f"{project_key}_{commit_hash[:8]}.diff"
        cache_file.write_text(diff, encoding="utf-8")
        return cache_file

    def _read_cached_diff(self, project_key: str, commit_hash: str) -> str | None:
        cache_file = self.cache_dir / f"{project_key}_{commit_hash[:8]}.diff"
        if cache_file.exists():
            return cache_file.read_text(encoding="utf-8")
        return None

    def _mark_processed(self, project_key: str, commit_hash: str) -> None:
        """Mark a commit as 'processed' (already reflected in resume)."""
        proj_state = self.state.setdefault("projects", {}).setdefault(project_key, {})
        processed = proj_state.setdefault("processed_commits", [])
        if commit_hash not in processed:
            processed.append(commit_hash)

    # ---- public API ----

    def check(self, project_key: str | None = None) -> dict[str, dict]:
        """
        Check specified project (or all enabled projects) for changes.

        Returns:
            {project_key: {
                "has_changes": bool,
                "new_commits": [...],
                "diff": str | None,
                "diff_stat": str | None,
                "error": str | None,
            }}
        """
        results: dict[str, dict] = {}

        for proj in self.config.get("projects", []):
            key = proj["key"]
            if project_key and key != project_key:
                continue
            if not proj.get("enabled", True):
                continue

            repo_path = proj["repo_local"]
            if not os.path.isdir(os.path.join(repo_path, ".git")):
                results[key] = {
                    "has_changes": False,
                    "new_commits": [],
                    "diff": None,
                    "diff_stat": None,
                    "error": f"Not a git repository: {repo_path}",
                }
                continue

            current_head = self._get_head(repo_path)
            if current_head is None:
                results[key] = {
                    "has_changes": False,
                    "new_commits": [],
                    "diff": None,
                    "diff_stat": None,
                    "error": f"Cannot read HEAD from: {repo_path}",
                }
                continue

            proj_state = self.state.get("projects", {}).get(key, {})
            last_commit = proj_state.get("last_commit")

            # First run: record baseline, no changes reported
            if last_commit is None:
                self.state.setdefault("projects", {})[key] = {
                    "last_commit": current_head,
                    "last_check_time": datetime.now().isoformat(),
                    "processed_commits": [],
                }
                if self.state.get("initialized_at") is None:
                    self.state["initialized_at"] = datetime.now().isoformat()
                self._save_state()
                results[key] = {
                    "has_changes": False,
                    "new_commits": [],
                    "diff": None,
                    "diff_stat": None,
                    "message": f"Initialized baseline at {current_head[:8]}",
                    "error": None,
                }
                continue

            # No new commits
            if current_head == last_commit:
                proj_state["last_check_time"] = datetime.now().isoformat()
                self._save_state()
                results[key] = {
                    "has_changes": False,
                    "new_commits": [],
                    "diff": None,
                    "diff_stat": None,
                    "error": None,
                }
                continue

            # New commits detected
            new_commits = self._get_new_commits(repo_path, last_commit)
            if not new_commits:
                # HEAD moved but no commits in range (unusual — maybe force push)
                results[key] = {
                    "has_changes": False,
                    "new_commits": [],
                    "diff": None,
                    "diff_stat": None,
                    "error": "HEAD changed but no commits found — possible force push?",
                }
                continue

            # Extract diff (use cache if available)
            diff = None
            diff_stat = None
            for commit in new_commits:
                cached = self._read_cached_diff(key, commit["hash"])
                if cached is not None:
                    if diff is None:
                        diff = cached
                    else:
                        diff += "\n\n" + cached
                    if diff_stat is None:
                        diff_stat = ""
                    diff_stat += f"\n[{commit['hash'][:8]}] {commit['message']} (cached)"
                else:
                    # Get full diff from last_commit to HEAD
                    if diff is None:
                        diff = self._get_diff(repo_path, last_commit)
                        diff_stat = self._get_diff_stat(repo_path, last_commit)
                        # Cache the per-commit diff
                        for c in new_commits:
                            individual_diff = self._get_diff(repo_path, f"{c['hash']}^")
                            if individual_diff:
                                self._cache_diff(key, c["hash"], individual_diff)

            # Update state
            proj_state["last_commit"] = current_head
            proj_state["last_check_time"] = datetime.now().isoformat()
            self._save_state()

            results[key] = {
                "has_changes": True,
                "new_commits": new_commits,
                "diff": diff,
                "diff_stat": diff_stat,
                "current_head": current_head,
                "error": None,
            }

        return results

    def mark_applied(self, project_key: str) -> None:
        """Mark all pending commits for a project as processed."""
        proj_state = self.state.get("projects", {}).get(project_key, {})
        last_commit = proj_state.get("last_commit")
        if last_commit:
            self._mark_processed(project_key, last_commit)
            self._save_state()

    def get_status(self) -> list[dict]:
        """Return status summary for all projects."""
        status = []
        for proj in self.config.get("projects", []):
            key = proj["key"]
            repo_path = proj["repo_local"]
            current_head = self._get_head(repo_path)
            proj_state = self.state.get("projects", {}).get(key, {})
            last_commit = proj_state.get("last_commit")
            processed = proj_state.get("processed_commits", [])

            has_changes = (
                current_head is not None
                and last_commit is not None
                and current_head != last_commit
            )

            status.append({
                "key": key,
                "name": proj["name"],
                "enabled": proj.get("enabled", True),
                "repo_path": repo_path,
                "current_head": current_head[:8] if current_head else None,
                "tracked_commit": last_commit[:8] if last_commit else None,
                "has_pending_changes": has_changes,
                "processed_count": len(processed),
                "last_check": proj_state.get("last_check_time"),
            })
        return status

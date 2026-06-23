"""
Resume-Sync CLI — automated resume update tool.

Usage:
    python -m src.cli check              # Check all projects for changes
    python -m src.cli check omniagent    # Check specific project
    python -m src.cli plan               # Generate update suggestions
    python -m src.cli plan omniagent     # Generate for specific project
    python -m src.cli plan --dry-run     # Print prompts without calling LLM
    python -m src.cli apply              # Apply updates (interactive confirm)
    python -m src.cli apply --yes        # Skip confirmation
    python -m src.cli build              # Compile PDF
    python -m src.cli run                # Full pipeline: check → plan → apply → build
    python -m src.cli daemon             # Single check + notify cycle
    python -m src.cli install            # Install Windows scheduled task
    python -m src.cli uninstall          # Remove Windows scheduled task
    python -m src.cli status             # Show tracking status
"""

import argparse
import io
import subprocess
import sys
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.checker import Checker
from src.generator import Generator
from src.updater import Updater
from src.builder import Builder
from src.notifier import notify_build_success, notify_build_failure

CONFIG_PATH = str(PROJECT_ROOT / "config.yaml")


# ============================================================
# Subcommand handlers
# ============================================================

def cmd_check(args):
    """Check projects for git changes."""
    checker = Checker(config_path=CONFIG_PATH)
    project = args.project if hasattr(args, 'project') else None
    results = checker.check(project_key=project)

    found_changes = False
    for key, result in results.items():
        if result.get("message"):
            print(f"\n[{key}] {result['message']}")
        elif result.get("error"):
            print(f"\n[{key}] ❌ Error: {result['error']}")
        elif result.get("has_changes"):
            found_changes = True
            commits = result["new_commits"]
            print(f"\n[{key}] 🔔 {len(commits)} new commit(s):")
            for c in commits:
                print(f"  {c['hash'][:8]}  {c['date'][:19]}  {c['message'][:100]}")
            if result.get("diff_stat"):
                print(f"\n  Changed files:")
                for line in result["diff_stat"].split("\n")[:15]:
                    print(f"    {line}")
        else:
            print(f"\n[{key}] ✅ No new changes")

    if not found_changes and not any(r.get("message") for r in results.values()):
        print("\nAll projects up to date.")


def cmd_plan(args):
    """Generate resume update suggestions via LLM."""
    checker = Checker(config_path=CONFIG_PATH)
    generator = Generator(config_path=CONFIG_PATH)

    project = args.project if hasattr(args, 'project') else None
    dry_run = args.dry_run if hasattr(args, 'dry_run') else False
    results = checker.check(project_key=project)

    tex_path = checker.config["resume"]["tex_path"]

    for key, result in results.items():
        if result.get("message"):
            print(f"[{key}] {result['message']}")
            continue
        if result.get("error"):
            print(f"[{key}] ❌ Error: {result['error']}")
            continue
        if not result.get("has_changes"):
            print(f"[{key}] No changes — nothing to plan.")
            continue

        # Resolve repo path
        repo_path = ""
        for proj in checker.config.get("projects", []):
            if proj["key"] == key:
                repo_path = proj["repo_local"]
                break

        print(f"\n{'='*60}")
        print(f"[{key}] Generating update suggestions...")
        print(f"{'='*60}")

        if dry_run:
            prompt = generator.generate_dry_run(
                key, result["diff"], tex_path, repo_path
            )
            print("\n--- DRY RUN: Prompt that would be sent to LLM ---\n")
            print(prompt[:3000])
            print("\n... (truncated)")
        else:
            gen_result = generator.generate(
                key, result["diff"], tex_path, repo_path
            )

            if gen_result.get("error"):
                print(f"❌ LLM error: {gen_result['error']}")
                continue

            if not gen_result.get("requires_update"):
                print(f"  Changes detected but LLM judged they don't warrant a resume update.")
                print(f"  Summary: {gen_result.get('summary', 'N/A')}")
                _save_plan(key, gen_result)
                continue

            print(f"\n  Summary: {gen_result.get('summary', 'N/A')}")
            print(f"\n  Proposed new bullets:")
            for i, bullet in enumerate(gen_result.get("bullets", []), 1):
                print(f"    {i}. {bullet.strip()[:120]}...")

            # Show diff against current .tex
            updater = Updater(tex_path)
            preview = updater.preview(key, gen_result.get("bullets", []))
            if preview.get("diff"):
                print(f"\n  --- Diff against current main.tex ---")
                for line in preview["diff"].split("\n")[:40]:
                    print(f"  {line}")

            _save_plan(key, gen_result)
            print(f"\n  Plan saved to {PROJECT_ROOT / 'cache' / f'{key}_plan.json'}")
            print(f"  Run 'python -m src.cli apply' to apply these changes.")


def _save_plan(project_key: str, gen_result: dict) -> None:
    """Save generated plan to cache for later apply."""
    import json
    cache_dir = PROJECT_ROOT / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    plan_file = cache_dir / f"{project_key}_plan.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump(gen_result, f, indent=2, ensure_ascii=False)


def _load_plan(project_key: str) -> dict | None:
    """Load a previously saved plan from cache."""
    import json
    plan_file = PROJECT_ROOT / "cache" / f"{project_key}_plan.json"
    if plan_file.exists():
        with open(plan_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def cmd_apply(args):
    """Apply generated plan to main.tex."""
    import yaml
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    skip_confirm = args.yes if hasattr(args, 'yes') else False
    tex_path = config["resume"]["tex_path"]
    updater = Updater(tex_path)

    for proj in config.get("projects", []):
        key = proj["key"]
        if not proj.get("enabled", True):
            continue

        plan = _load_plan(key)
        if plan is None:
            print(f"[{key}] No plan found. Run 'plan' first.")
            continue
        if not plan.get("requires_update"):
            print(f"[{key}] Plan says no update needed — skipping.")
            continue

        bullets = plan.get("bullets", [])
        if not bullets:
            print(f"[{key}] Empty bullet list — skipping.")
            continue

        preview = updater.preview(key, bullets)
        if preview.get("error"):
            print(f"[{key}] ❌ {preview['error']}")
            continue

        print(f"\n{'='*60}")
        print(f"[{key}] Applying update...")
        print(f"{'='*60}")
        print(f"\n{preview['diff']}")

        if not skip_confirm:
            answer = input("\nApply this change? [y/N] ").strip().lower()
            if answer != "y":
                print("  Skipped.")
                continue

        result = updater.apply(key, bullets)
        if result.get("success"):
            print(f"  ✅ Updated! Backup saved to {result['backup_path']}")
            # Mark as processed
            checker = Checker(config_path=CONFIG_PATH)
            checker.mark_applied(key)
        else:
            print(f"  ❌ Failed: {result['error']}")

    print("\nRun 'python -m src.cli build' to compile the updated PDF.")


def cmd_build(args):
    """Compile LaTeX resume to PDF."""
    builder = Builder(config_path=CONFIG_PATH)
    print("Compiling PDF...")
    result = builder.compile()

    if result["success"]:
        print(f"✅ PDF compiled successfully")
        print(f"   Output: {result['pdf_path']}")
        if result.get("backup_path"):
            print(f"   Backup: {result['backup_path']}")
        notify_build_success(result["pdf_path"])
    else:
        print(f"❌ Compilation failed")
        for err in result.get("errors", []):
            print(f"   Error: {err}")
        for warn in result.get("warnings", []):
            print(f"   Warning: {warn}")
        notify_build_failure(len(result.get("errors", [])))


def cmd_run(args):
    """Full pipeline: check → plan → apply → build."""
    # Run check
    checker = Checker(config_path=CONFIG_PATH)
    results = checker.check()

    any_changes = any(r.get("has_changes") for r in results.values())
    if not any_changes:
        print("No changes detected across all projects. Exiting.")
        return

    # Run plan
    print("\n--- Generating update plans ---")
    generator = Generator(config_path=CONFIG_PATH)
    tex_path = checker.config["resume"]["tex_path"]

    for key, result in results.items():
        if not result.get("has_changes"):
            continue

        repo_path = ""
        for proj in checker.config.get("projects", []):
            if proj["key"] == key:
                repo_path = proj["repo_local"]
                break

        gen_result = generator.generate(key, result["diff"], tex_path, repo_path)
        if gen_result.get("error"):
            print(f"[{key}] LLM error: {gen_result['error']}")
            continue
        if not gen_result.get("requires_update"):
            print(f"[{key}] No resume update needed.")
            continue

        _save_plan(key, gen_result)
        print(f"[{key}] Plan generated: {gen_result.get('summary', '')}")

        # Apply
        updater = Updater(tex_path)
        bullets = gen_result.get("bullets", [])
        preview = updater.preview(key, bullets)
        if preview.get("error"):
            print(f"[{key}] Preview error: {preview['error']}")
            continue

        print(f"\n[{key}] Diff:")
        for line in preview["diff"].split("\n")[:20]:
            print(f"  {line}")

        apply_result = updater.apply(key, bullets)
        if apply_result.get("success"):
            print(f"[{key}] ✅ Applied. Backup: {apply_result['backup_path']}")
            checker.mark_applied(key)
        else:
            print(f"[{key}] ❌ {apply_result['error']}")

    # Build
    print("\n--- Compiling PDF ---")
    cmd_build(args)


def cmd_daemon(args):
    """Run a single daemon check cycle."""
    from src.daemon import run_check
    run_check(config_path=CONFIG_PATH)


def cmd_install(args):
    """Install Windows scheduled task for periodic checking."""
    python_exe = sys.executable
    daemon_script = str(PROJECT_ROOT / "src" / "daemon.py")
    task_name = "ResumeSync"

    # Remove existing task if any
    subprocess.run(
        ["schtasks", "/Delete", "/TN", task_name, "/F"],
        capture_output=True
    )

    # Create new task: runs at user logon, repeats every 30 min
    cmd = [
        "schtasks", "/Create",
        "/TN", task_name,
        "/SC", "MINUTE",
        "/MO", "30",
        "/TR", f'"{python_exe}" "{daemon_script}"',
        "/F",
        "/RL", "LIMITED",
        "/IT",  # interactive — can show toasts
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"✅ Scheduled task '{task_name}' installed (every 30 min).")
        print(f"   The daemon will check for project updates and notify you.")
    else:
        print(f"❌ Failed to install scheduled task:")
        print(result.stderr)


def cmd_uninstall(args):
    """Remove Windows scheduled task."""
    task_name = "ResumeSync"
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", task_name, "/F"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"✅ Scheduled task '{task_name}' removed.")
    else:
        print(f"Scheduled task '{task_name}' not found or already removed.")


def cmd_status(args):
    """Show tracking status for all projects."""
    checker = Checker(config_path=CONFIG_PATH)
    status_list = checker.get_status()

    print(f"\n{'Key':<14} {'Name':<14} {'HEAD':<10} {'Tracked':<10} {'Pending':<8} {'Enabled'}")
    print("-" * 68)
    for s in status_list:
        pending = "YES" if s["has_pending_changes"] else "—"
        print(f"{s['key']:<14} {s['name']:<14} {s['current_head'] or 'N/A':<10} "
              f"{s['tracked_commit'] or 'NEW':<10} {pending:<8} {str(s['enabled'])}")


# ============================================================
# Entry point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Resume-Sync — Automated resume update from git activity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.cli check                 # Check all projects
  python -m src.cli plan omniagent        # Plan updates for omniagent
  python -m src.cli plan --dry-run        # See what prompt would be sent to LLM
  python -m src.cli apply --yes           # Apply all pending updates
  python -m src.cli build                 # Compile PDF after manual edits
  python -m src.cli run                   # Full pipeline
  python -m src.cli install               # Set up auto-check every 30 min
        """,
    )
    sub = parser.add_subparsers(dest="command")

    # check
    p_check = sub.add_parser("check", help="Check projects for git changes")
    p_check.add_argument("project", nargs="?", help="Project key to check (optional)")

    # plan
    p_plan = sub.add_parser("plan", help="Generate update suggestions via LLM")
    p_plan.add_argument("project", nargs="?", help="Project key to plan (optional)")
    p_plan.add_argument("--dry-run", action="store_true",
                        help="Print prompt without calling LLM")

    # apply
    p_apply = sub.add_parser("apply", help="Apply pending updates to resume")
    p_apply.add_argument("--yes", action="store_true",
                         help="Skip confirmation prompt")

    # build
    sub.add_parser("build", help="Compile resume PDF")

    # run
    sub.add_parser("run", help="Full pipeline: check → plan → apply → build")

    # daemon
    sub.add_parser("daemon", help="Single daemon check cycle (for scheduled task)")

    # install / uninstall
    sub.add_parser("install", help="Install Windows scheduled task")
    sub.add_parser("uninstall", help="Remove Windows scheduled task")

    # status
    sub.add_parser("status", help="Show tracking status for all projects")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    handlers = {
        "check": cmd_check,
        "plan": cmd_plan,
        "apply": cmd_apply,
        "build": cmd_build,
        "run": cmd_run,
        "daemon": cmd_daemon,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "status": cmd_status,
    }

    handler = handlers.get(args.command)
    if handler:
        handler(args)


if __name__ == "__main__":
    main()

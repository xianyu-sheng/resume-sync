# Resume-Sync

> Auto-detect Git project changes → LLM generates resume bullets → update LaTeX source → compile PDF — all automated.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **:book: Chinese documentation:** [README_CN.md](README_CN.md)

---

## The Problem

During job hunting, every time you push code to your project repos, you have to **manually** go into Overleaf, update the project descriptions on your resume, recompile the PDF, and download it again. This process is repetitive, easy to forget, and produces inconsistent bullet quality.

**Resume-Sync** automates the entire loop: detects new commits in your tracked projects, calls an LLM to analyze code changes and generate high-quality resume bullets, updates LaTeX source files, compiles the PDF locally, and overwrites your resume file — all you need to do is review a diff and press `y`.

---

## Workflow

```
You commit code to your local project repo
       |
[check]   Read local HEAD, compare against last recorded commit
       |  New commits?
[plan]    Extract git diff -> LLM analyzes changes -> generate candidate bullets
       |  User confirms
[apply]   Replace marker blocks in main.tex (% RESUME_PROJECT_START/END)
       |
[build]   latexmk -xelatex -> output PDF -> overwrite target file
       |
[notify]  Windows Toast notification "Resume updated" (Windows only;
          silently skipped on Linux/macOS)
```

### Polish Mode (No New Commits Required)

```
No need to wait for new commits
       |
[polish]  Read current bullets -> LLM restructures expression
         |-- Break up walls of text (single sentence <= 80 chars)
         |-- Priority clipping (each bullet <= 2 quantified numbers)
         |-- Flatten nested parentheses / front-load core claims
         |-- Merge fragmented entries
       |  User reviews diff
[apply]   Replace marker blocks
       |
[build]   Compile PDF
```

---

## Prerequisites

### Operating System

| OS | Support |
|----|---------|
| **Windows 10/11** | Full support (including desktop notifications) |
| **Ubuntu 22.04/24.04** | Core features complete, desktop notifications unavailable |
| **macOS** | Core features complete, desktop notifications unavailable |

### Software Dependencies

| Software | Version | Verification |
|----------|---------|-------------|
| **Python** | 3.10+ | `python --version` |
| **Git** | Any | `git --version` |
| **TeX Live** | With `latexmk` + `xelatex` | `latexmk --version` |

Additional TeX Live packages for Chinese resumes:
```bash
tlmgr install ctex xecjk fontspec
```

### Project Repositories

- Each tracked project must be a **local Git repository** (has a `.git` directory).
- The tool **never clones** any remote repository — it only reads local repos on your disk.
- Repository paths are configured via `config.yaml`.

### LaTeX Resume

- Your resume must be written in **LaTeX** (this tool does not support Word/PDF input).
- Each project section in your `.tex` file must be wrapped in **marker comments** (see "LaTeX Marker Specification" below).
- For Chinese resumes, the `ctex` package is required (`\documentclass{ctexart}` or `\usepackage{ctex}`).

### LLM API Key

- Requires a **DeepSeek API Key** (or any OpenAI-compatible API key).
- Register at: [platform.deepseek.com](https://platform.deepseek.com)
- Modify `api_base` and `model` in `config.yaml` to switch to a different LLM provider.

---

## Quick Start

```bash
# 1. Clone this repository
git clone https://github.com/xianyu-sheng/resume-sync.git
cd resume-sync

# 2. Install Python dependencies
pip install -r requirements.txt
#    (or: pip install -e .  — also provides the `resume-sync` command)

# 3. Set DeepSeek API Key
# Windows (PowerShell):
[Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', 'sk-your-key', 'User')
#   Restart your terminal after setting the environment variable
# Linux/macOS:
export DEEPSEEK_API_KEY=sk-your-key

# 4. Edit config.yaml with your paths (see Configuration section below)

# 5. Add marker comments to your LaTeX resume (see Marker Specification section below)

# 6. Initialize tracking baseline
python -m src.cli status
```

---

## Configuration

**All paths are configured via `config.yaml` — no hardcoded paths in the code.**

```yaml
resume:
  tex_path: "/path/to/your/resume/main.tex"     # LaTeX source path
  pdf_output: "/path/to/your/resume.pdf"         # Compiled PDF output path

projects:
  - key: my-project                    # Project identifier (matches LaTeX marker)
    name: "My Project"                 # Project name (used in LLM prompts)
    repo_local: "/path/to/your/project" # Local Git repository path
    enabled: true                      # Whether to track this project

llm:
  provider: "deepseek"
  api_key: "${DEEPSEEK_API_KEY}"       # Read from env var (never write plaintext keys here)
  api_base: "https://api.deepseek.com/v1"
  model: "deepseek-chat"               # DeepSeek model ID

build:
  engine: "latexmk"
  args: ["-xelatex", "-interaction=nonstopmode"]
  backup: true
  backup_dir: "backups"                # Absolute path also supported

review:
  enabled: true                        # Enable multi-round self-review
  max_rounds: 3                        # Max review rounds (generate -> review -> revise -> ...)
  pass_threshold: 8.5                  # Minimum weighted score to pass

daemon:
  interval_minutes: 30                 # Background check interval
  auto_apply: false                    # false = notify only, do not auto-modify resume
  notify_on_change: true
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | Yes |

Use the `${VARIABLE_NAME}` syntax in `config.yaml` to reference environment variables, keeping your API key out of the git repository.

---

## Usage

### Basic Commands

```bash
cd resume-sync

# All commands below also work via the installed entry point:
#   resume-sync status   (instead of: python -m src.cli status)

# Show tracking status for all projects
python -m src.cli status

# Check projects for new commits
python -m src.cli check              # Check all
python -m src.cli check my-project   # Check a specific project

# Generate update suggestions (calls LLM)
python -m src.cli plan               # Plan for all changed projects
python -m src.cli plan my-project    # Plan for a specific project
python -m src.cli plan --dry-run     # Print prompt without calling API

# Apply updates to LaTeX file
python -m src.cli apply              # Interactive confirmation
python -m src.cli apply --yes        # Skip confirmation

# Compile PDF
python -m src.cli build

# Full pipeline: check -> plan -> apply -> build
python -m src.cli run

# Readability optimization (no new commits required)
python -m src.cli polish               # Polish all enabled projects
python -m src.cli polish my-project    # Polish a specific project
python -m src.cli polish --apply       # Skip confirmation, apply directly
```

### Daemon Mode

```bash
# Windows: install scheduled task (auto-starts on login, checks every 30 min)
python -m src.cli install

# Run one daemon check cycle (for scheduled task invocation)
python -m src.cli daemon

# Continuous loop mode (Ctrl+C to stop)
python src/daemon.py --loop

# Windows: remove scheduled task
python -m src.cli uninstall

# Linux: use cron instead of install/uninstall. Example crontab entry:
#   */30 * * * * cd /path/to/resume-sync && /usr/bin/python3 -m src.cli daemon
# See SETUP.md for the full Ubuntu step-by-step guide.
```

### Typical Daily Workflow

```bash
# === Daily use ===
# 1. Daemon detects new commits in background
#    (Windows: toast notification pops up; Linux/macOS: check `status` output)
# 2. Open terminal
python -m src.cli plan my-project
# 3. Review LLM-generated bullets and diff
# 4. Confirm and build
python -m src.cli apply --yes
python -m src.cli build
# 5. Resume PDF updated successfully
```

---

## LaTeX Marker Specification

The tool locates project description blocks in your LaTeX source using specific comment markers. **Content outside these markers is never touched.**

In your `.tex` file, wrap your project's `\item` entries with markers:

```latex
\begin{itemize}
    % RESUME_PROJECT_START: my-project
    \item \textbf{Description:} ...
    \item \textbf{Core Engine:} ...
    \item \textbf{Ecosystem:} ...
    % RESUME_PROJECT_END: my-project
\end{itemize}
```

### Rules

- `START` and `END` must be paired, placed inside the same `itemize` (or similar list environment).
- The key (`my-project`) must **exactly match** the project's `key` in `config.yaml`.
- Content outside the marker comments (project titles, tech stack lines, links) is never modified.
- The tool performs a **complete replacement** of the bullet list within the marker block (not incremental editing).

---

## Adding a New Tracking Project

Three steps:

### 1. Add markers in `main.tex`

```latex
% RESUME_PROJECT_START: new_project
\item \textbf{Description:} ...
% RESUME_PROJECT_END: new_project
```

### 2. Add configuration in `config.yaml`

```yaml
projects:
  - key: new_project
    name: "New Project"
    repo_local: "/path/to/your/project"
    enabled: true
```

### 3. Initialize baseline

```bash
python -m src.cli check new_project
```

---

## Architecture

```
resume-sync/
├── config.yaml              # All configuration (paths, LLM, build params)
├── state.json               # Runtime state (auto-managed, not committed to Git)
├── requirements.txt         # Python dependencies (PyYAML + openai)
├── .gitignore
├── cache/                   # Diff cache (indexed by commit hash)
├── backups/                 # Timestamped backups of PDF and .tex files
├── src/
│   ├── __init__.py
│   ├── cli.py               # CLI entry point (argparse subcommands)
│   ├── checker.py           # Git change detection + state management + caching
│   ├── generator.py         # LLM resume bullet generation (OpenAI-compatible API + hierarchy-aware)
│   ├── updater.py           # LaTeX marker block parsing and replacement
│   ├── builder.py           # latexmk compilation + PDF output + error handling
│   ├── notifier.py          # Windows Toast native notifications
│   └── daemon.py            # Background polling mode (for scheduled task)
├── agent.yaml               # Agent Manifest (self-description for Agent Hub integration)
├── SETUP.md                 # Ubuntu setup guide (step-by-step for AI coding tools)
└── README.md
```

### Data Flow

```
config.yaml ----> checker.py ----> state.json
                    |
              agent.yaml ----> discovers scheduled_agents (scheduling relationships)
                    |
              generator.py ----> LLM API (DeepSeek / OpenAI-compatible)
                    |
              updater.py  ----> main.tex (LaTeX source with marker comments)
                    |
              builder.py  ----> resume.pdf (compiled output)
                    |
              notifier.py ----> Windows Toast desktop notification
```

### Multi-Role Review Architecture (Generate -> Review -> Revise)

The core generation pipeline is not a single LLM call — it simulates a **Proposer-Critique-Judge** three-state adversarial pipeline:

```
Round 1 - Generator (Proposer)
          |  Generates initial draft (following 9 FAANG resume insights)
Round 2 - Reviewer (Critic)
          |  10-dimension scoring system scores each bullet
          |  Flags inflated/vague/process-oriented language
          |-- Weighted score >= 8.5 AND all dimensions >= 5? -> Pass, output directly
          |-- Otherwise -> Enter revision round
Round 3 - Reviser (Judge)
          |  Surgical revision: only fix problematic bullets, leave passing ones intact
          |  Revised bullets sent back to Round 2 for re-review
          ... repeats until pass or max rounds reached (default 3 rounds)
```

#### 10-Dimension Scoring System

| Dimension | Weight | Core Question |
|-----------|--------|---------------|
| Quantification Hardness | 1.5 | Are there concrete numbers? Measured or estimated? |
| Personal Contribution Differentiation | 1.5 | Can the reader tell "what you did vs what the team did"? |
| Technical Depth | 1.2 | Does it explain WHY+HOW, or just WHAT? |
| Narrative Arc | 1.0 | Is there a complete "problem -> solution -> result" arc? |
| Adversarial Question Survival | 1.5 | "How did you measure that?" "What was your contribution share?" — can you answer? |
| Conciseness & Scannability | 1.2 | Single sentence <= 80 chars? No walls of text? HR can scan in 2 seconds? |
| LaTeX Compliance | 1.0 | Are special characters properly escaped? |
| Verb Strength | 0.8 | "Participated in/Used" or "Led/Built from scratch"? |
| Scale Perception | 1.0 | Can the reader sense the project's scale? (LoC/modules/agents) |
| Redundancy | 0.8 | Are adjacent bullets saying the same thing? |

### Polish Pipeline (Readability Optimization)

Optimizes the expression structure of existing resume bullets, **no code changes required**:

```
Round 1 - Polisher
          |  Receives current bullets -> priority clipping -> break walls of text -> merge fragments
Round 2 - Polish Reviewer (Readability Auditor)
          |  5-dimension readability review: text-wall / bracket nesting / scannability / info redundancy / info density
          |-- All dimensions >= 8.5? -> Pass
          |-- Otherwise -> Revise and re-review (max 3 rounds)
```

**Polish Rules:**
- **Priority Clipping:** Each bullet gets <= 1 core claim + 2 supporting data points. If more than 2 numbers, clip.
- **Split Iron Law:** After splitting, each resulting bullet must have >= 2 sentences AND at least 1 quantified number. No split otherwise.
- **Merge First:** If adjacent bullets describe different aspects of the same thing, merge them.
- **Target Count:** 4-6 bullets per project.

Polish uses an **independent reviewer** (`SYSTEM_POLISH_REVIEWER`) focused solely on readability dimensions, separate from the FAANG content reviewer.

**Hash Deduplication:** In `run` mode, the polish phase compares the current bullet hash against the last-polished hash. If unchanged, the LLM call is skipped to save tokens.

### Hierarchy-Aware Generation

When a tracked project is an **orchestration/scheduling system** (e.g., Agent Hub), resume-sync automatically reads the project's `agent.yaml`, discovers `scheduled_agents` declarations, and injects sub-project relationship context into the LLM generation prompt.

**Comparison:**

| Without Hierarchy Awareness | With Hierarchy Awareness |
|--------------------------|-------------------------|
| "Developed Agent Hub, a multi-agent scheduling system" | "Designed a multi-agent collaborative scheduling framework (Agent Manifest protocol + LLM intent routing + DAG parallel scheduling), orchestrating 3 heterogeneous specialized agents (code generation, quality diagnostics, resume sync) via CLI Bridge with zero-intrusion integration" |
| Resume reads like several independent projects | Resume demonstrates system architecture ability and engineering depth |

**How it works (automatic, no extra configuration):**

```
1. generator.py reads <project>/agent.yaml
       |
2. Found scheduled_agents field?
       | Yes
3. Build hierarchy context (sub-agent names, roles, interface types)
       |
4. Inject into LLM generation prompt
       |
5. LLM produces architecture-aware resume description
       | No
6. Use standard prompt (no special handling)
```

**`scheduled_agents` Protocol** (declare in your project's `agent.yaml`):

```yaml
# Example: Agent Hub's agent.yaml
name: agent-hub
display_name: "Agent Hub Scheduler"
protocol: internal

scheduled_agents:
  - name: omniagent
    repo: D:/OmniAgent_CLI
    role: "General-purpose AI Coding Agent - code analysis, generation, refactoring"
    interface: cli
  - name: smartbench
    repo: D:/SmartBench
    role: "Code quality diagnostic engine"
    interface: cli
  - name: resume-sync
    repo: D:/resume-sync
    role: "Automated resume syncer"
    interface: cli
```

> **Design Principle:** `scheduled_agents` is an optional extension field of the Agent Manifest protocol. resume-sync reads it but does not require it — if the project's `agent.yaml` lacks this field, the generation pipeline proceeds normally with no impact. This feature is fully transparent to the user.

---

## Caching Strategy

- **`state.json`**: Records the last-checked commit hash for each project, used for incremental comparison. **Should not be committed to Git** (excluded in `.gitignore`).
- **`cache/*.diff`**: caches diff content by `{project}_{commit_hash[:8]}.diff`, avoiding repeated `git diff` execution for the same commit.
- **`processed_commits`**: Tracks which commits have been reflected in the resume. Supports `mark_applied()`.
- **First Run**: Records current HEAD as the baseline, does not trigger updates (prevents generating changes for historical code).

---

## Security Design

| Mechanism | Description |
|-----------|-------------|
| **Marker Block Isolation** | Only modifies content inside `% RESUME_PROJECT_START/END` markers |
| **Auto Backup** | Creates `.bak_{timestamp}` copies before every `.tex` write |
| **PDF Backup** | Creates timestamped backups in `backups/` before every PDF compilation |
| **Interactive Confirmation** | `apply` requires `y` confirmation by default |
| **File Lock Handling** | Retries 3 times when PDF is locked by a reader, never corrupts the original file |
| **Compilation Failure Protection** | Failed compilation does not overwrite the original PDF; `.tex` is never rolled back |
| **`auto_apply: false`** | Background daemon only notifies by default, never auto-modifies the resume |
| **API Key Protection** | Referenced via environment variable `${DEEPSEEK_API_KEY}`, never stored in plaintext in config.yaml |

---

## FAQ

### Q: DeepSeek API call fails?

Verify the environment variable is set correctly (should start with `sk-`):

- Windows PowerShell: `echo $env:DEEPSEEK_API_KEY`
- Linux/macOS: `echo $DEEPSEEK_API_KEY`

If using an old terminal window, close and reopen it for the variable to take effect. Ensure your DeepSeek account has sufficient balance.

### Q: PDF compilation fails with "fontspec.sty not found"?

Make sure a full TeX Live installation is present, particularly `xelatex` and Chinese packages:
```bash
tlmgr install ctex xecjk fontspec
```

### Q: Windows Toast notification doesn't appear?

Toast notifications may be unavailable on certain lightweight editions / Windows Server. This does not affect core functionality — all information is still displayed in the command-line output.

### Q: Can I use other LLMs?

Yes, any OpenAI-compatible LLM is supported. Simply modify `config.yaml`:
```yaml
llm:
  api_base: "https://api.openai.com/v1"
  model: "gpt-4o"
```

### Q: How to sync between multiple computers?

`state.json` and `cache/` are local state and should not be shared across machines. Initialize the baseline independently on each computer. `config.yaml` also differs per machine (local paths vary) and should not be shared.

### Q: Can I use macOS / Linux?

Core features (check / plan / apply / build) work fully. Only Windows Toast notifications are unavailable (silently skipped, does not affect the pipeline). For the background daemon, use cron instead of Windows Task Scheduler — see SETUP.md for a complete Ubuntu walkthrough.

### Q: The generated bullets don't read well?

Try running `python -m src.cli polish` to optimize readability of existing bullets without needing new commits. Adjust `review.max_rounds` in `config.yaml` if you want more rigorous review cycles.

### Q: How do I stop tracking a project?

Set `enabled: false` for that project in `config.yaml`. The tool will skip it entirely during check/plan/apply/build. The marker blocks in your `.tex` file will be ignored.

---

## License

[MIT](LICENSE)

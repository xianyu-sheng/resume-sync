# Resume-Sync

> 自动检测项目仓库变更 → LLM 生成简历描述 → 更新 LaTeX 源码 → 编译 PDF → 覆盖输出

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 前置条件（必读）

在使用本工具之前，请确保你的环境满足以下所有条件：

### 操作系统

| 操作系统 | 说明 |
|----------|------|
| **Windows 10/11** | 完整支持（含桌面通知） |
| **Ubuntu 22.04/24.04** | 核心功能完整，桌面通知不可用 |
| **macOS** | 核心功能完整，桌面通知不可用 |

> 📖 **Ubuntu 用户请直接阅读 [SETUP.md](SETUP.md)**，包含从零开始的完整环境安装步骤（LaTeX + Python + Git + 字体），可直接发给 AI 编程工具执行。

### 软件依赖

| 软件 | 版本要求 | 验证命令 |
|------|----------|----------|
| **Python** | 3.10+ | `python --version` |
| **Git** | 任意版本 | `git --version` |
| **TeX Live** | 含 `latexmk` + `xelatex` | `latexmk --version` |

TeX Live 需额外安装中文支持（如果简历使用中文）：
```bash
tlmgr install ctex xecjk fontspec
```

### 项目仓库

- 需要追踪的每个项目必须是**本地 Git 仓库**（有 `.git` 目录）
- 工具**不会** clone 任何远程仓库——它只读取你硬盘上已有的本地仓库
- 仓库路径通过 `config.yaml` 配置（见下方）

### LaTeX 简历

- 简历必须使用 **LaTeX** 编写（本工具不支持 Word/PDF 输入）
- 需要在 `.tex` 文件中为每个项目添加**标记注释**（见下方「LaTeX 标记规范」）
- 如果简历使用中文，需要 `ctex` 宏包（`\documentclass{ctexart}` 或 `\usepackage{ctex}`）

### LLM API Key

- 需要 **DeepSeek API Key**（或其他 OpenAI 兼容接口的 API Key）
- 注册地址：[platform.deepseek.com](https://platform.deepseek.com)
- 修改 `config.yaml` 中的 `api_base` 和 `model` 可切换其他 LLM 供应商

---

## 痛点

求职期间，每次往项目仓库 push 代码后，都需要**手动**去 Overleaf 更新简历的项目描述，然后再编译下载 PDF。这个过程重复、容易遗忘、描述质量不稳定。

**Resume-Sync** 将这个过程自动化：检测到你项目有新的 commit → 调用 LLM 分析代码变更 → 生成高质量的简历 bullet → 更新 LaTeX 标记块 → 本地编译 PDF → 覆盖你的简历文件。

全程你只需要确认一眼 diff，点一下 `y`。

---

## 工作流

```
你在本地项目仓库提交代码
       ↓
[check]  读取本地仓库 HEAD，与上次记录的 commit 比较
       ↓  有新 commit？
[plan]   提取 git diff → LLM 分析变更 → 生成候选 bullet
       ↓  用户确认
[apply]  替换 main.tex 中 % RESUME_PROJECT_START/END 标记块
       ↓
[build]  latexmk -xelatex → 输出 PDF → 覆盖目标文件
       ↓
[notify] Windows Toast 通知 "简历已更新"
```

### 无新 commit 时的可读性优化

```
无需等待项目有新 commit
       ↓
[polish] 读取当前 bullet → LLM 重构表达结构
         ├── 拆文字墙（单句 ≤ 80 字）
         ├── 信息优先级裁剪（每 bullet ≤ 2 个量化数字）
         ├── 括号去嵌套 / 核心主张前置
         └── 合并碎片化条目
       ↓  用户确认 diff
[apply]  替换标记块
       ↓
[build]  编译 PDF
```

---

## 快速开始

```bash
# 1. 克隆本仓库
git clone https://github.com/xianyu-sheng/resume-sync.git
cd resume-sync

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 设置 DeepSeek API Key（Windows）
[Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', 'sk-你的Key', 'User')
# 设置后重新打开终端使环境变量生效

# 4. 编辑 config.yaml，填入你的路径（详见下方配置章节）

# 5. 在你的 LaTeX 简历中为项目添加标记注释（详见下方标记规范）

# 6. 初始化基线
python -m src.cli status
```

---

## 配置

**所有路径均通过 `config.yaml` 配置，代码中不含任何硬编码路径。**

```yaml
resume:
  tex_path: "/path/to/your/resume/main.tex"     # 你的 LaTeX 源码路径
  pdf_output: "/path/to/your/resume.pdf"         # 编译后 PDF 输出路径

projects:
  - key: my-project                    # 项目唯一标识（对应 LaTeX 标记）
    name: "My Project"                 # 项目名称（用于 LLM prompt）
    repo_local: "/path/to/your/project" # 本地 Git 仓库路径
    enabled: true                      # 是否追踪

llm:
  provider: "deepseek"
  api_key: "${DEEPSEEK_API_KEY}"       # 从环境变量读取（不要在这里写明文 Key）
  api_base: "https://api.deepseek.com/v1"
  model: "deepseek-chat"               # DeepSeek 模型 ID

build:
  engine: "latexmk"
  args: ["-xelatex", "-interaction=nonstopmode"]
  backup: true
  backup_dir: "backups"                # 相对路径 = resume-sync/backups

daemon:
  interval_minutes: 30                 # 后台检测间隔
  auto_apply: false                    # false = 只通知不自动改简历（推荐）
  notify_on_change: true
```

### 环境变量

| 变量 | 说明 | 必填 |
|------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 是 |

在 `config.yaml` 中使用 `${变量名}` 语法引用环境变量，避免 API Key 泄漏到 git 仓库。

---

## 使用

### 基础命令

```bash
cd resume-sync

# 查看所有项目追踪状态
python -m src.cli status

# 检查项目是否有新 commit
python -m src.cli check              # 检查所有
python -m src.cli check my-project   # 只检查指定项目

# 生成更新建议（调用 LLM）
python -m src.cli plan               # 为所有有变更的项目生成
python -m src.cli plan my-project    # 只为指定项目生成
python -m src.cli plan --dry-run     # 不调 API，打印 prompt 供调试

# 应用更新到 LaTeX 文件
python -m src.cli apply              # 交互式确认
python -m src.cli apply --yes        # 跳过确认

# 编译 PDF
python -m src.cli build

# 全流程一键执行（check → plan → apply → build）
python -m src.cli run

# 可读性专项优化（无需新 commit，直接优化表达结构）
python -m src.cli polish               # 为所有启用项目优化可读性
python -m src.cli polish my-project    # 只为指定项目优化
python -m src.cli polish --apply       # 跳过确认，直接应用
```

### 后台自动检测

```bash
# 安装 Windows 计划任务（开机自启，每 30 分钟检测一次）
python -m src.cli install

# 手动运行一次检测（供计划任务调用）
python -m src.cli daemon

# 持续循环模式（Ctrl+C 停止）
python src/daemon.py --loop

# 移除计划任务
python -m src.cli uninstall
```

### 典型工作流程

```bash
# === 日常使用 ===
# 1. 后台自动检测到新 commit → 弹出 Windows 通知
# 2. 打开终端
python -m src.cli plan my-project
# 3. 审查 LLM 生成的 bullet 和 diff
# 4. 确认无误
python -m src.cli apply --yes
python -m src.cli build
# 5. 简历 PDF 已更新 ✓
```

---

## LaTeX 标记规范

工具通过特定注释标记来定位简历中的项目描述块，**不会误伤其他内容**。

在你的 `.tex` 文件中，将项目描述的 `\item` 用标记包裹：

```latex
\begin{itemize}
    % RESUME_PROJECT_START: my-project
    \item \textbf{项目描述：} ...
    \item \textbf{核心引擎：} ...
    \item \textbf{工具生态：} ...
    % RESUME_PROJECT_END: my-project
\end{itemize}
```

### 规则

- `START` 和 `END` 必须成对出现，位于同一个 `itemize`（或类似列表环境）内部
- `my-project` 必须与 `config.yaml` 中该项目的 `key` **完全一致**
- 标记注释之外的内容（项目标题、技术栈行、链接）不会被修改
- 工具会**完整替换**标记块内的 bullet list（而非增量修改）

---

## 添加新追踪项目

三步即可：

### 1. 在 `main.tex` 中加标记

```latex
% RESUME_PROJECT_START: new_project
\item \textbf{项目描述：} ...
% RESUME_PROJECT_END: new_project
```

### 2. 在 `config.yaml` 中加配置

```yaml
projects:
  - key: new_project
    name: "New Project"
    repo_local: "/path/to/your/project"
    enabled: true
```

### 3. 初始化基线

```bash
python -m src.cli check new_project
```

---

## 架构

```
resume-sync/
├── config.yaml              # 所有可配置项（路径、LLM、构建参数）
├── state.json               # 运行时状态（自动管理，不提交到 Git）
├── requirements.txt         # Python 依赖（PyYAML + openai）
├── .gitignore
├── cache/                   # diff 缓存（按 commit hash 索引）
├── backups/                 # PDF 和 .tex 时间戳备份
├── src/
│   ├── __init__.py
│   ├── cli.py               # CLI 主入口（argparse 子命令）
│   ├── checker.py           # Git 变更检测 + 状态管理 + 缓存
│   ├── generator.py         # LLM 简历描述生成（OpenAI 兼容接口 + 调度关系感知）
│   ├── updater.py           # LaTeX 标记块解析与替换
│   ├── builder.py           # latexmk 编译 + PDF 输出 + 错误处理
│   ├── notifier.py          # Windows Toast 原生通知
│   └── daemon.py            # 后台轮询模式（供计划任务调用）
└── README.md
```

### 多角色审查架构（Generate → Review → Revise）

工具的核心生成管线不是单次 LLM 调用，而是模拟 **Proposer-Critique-Judge** 三态协作的多轮对抗管线：

```
Round 1 ─ Generator（产出者）
          ↓ 生成初稿（遵循 9 条大厂简历深层洞察）
Round 2 ─ Reviewer（质疑者）
          ↓ 10 维评分体系逐条打分，揪出虚高/模糊/过程化表述
          ├── 加权总分 ≥ 8.5 且所有维度 ≥ 5分？→ 通过，直接输出
          └── 不满足 → 进入修订轮次
Round 3 ─ Reviser（裁决者）
          ↓ 外科手术式修订：只改有问题的条目，不动已达标内容
          ↓ 修订后回 Round 2 再次审查
          ... 直到通过或达到最大轮数（默认 3 轮）
```

**10 维评分体系**：

| 维度 | 权重 | 核心问题 |
|------|------|----------|
| 量化硬度 | 1.5 | 有没有具体数字？是测量值还是估算？ |
| 个人贡献区分度 | 1.5 | 能判断"你做的 vs 团队做的"吗？ |
| 技术深度 | 1.2 | 说了 WHAT 还是解释了 WHY+HOW？ |
| 叙事弧线 | 1.0 | 有"问题→方案→结果"完整弧线吗？ |
| 对抗性追问存活率 | 1.5 | "你怎么衡量的？""你的贡献占比？"——能回答吗？ |
| 简洁度与可扫描性 | 1.2 | 单句 ≤ 80 字？有文字墙吗？HR 扫 2 秒能懂吗？ |
| LaTeX 合规 | 1.0 | 特殊字符正确转义了吗？ |
| 动词强度 | 0.8 | "参与/使用"还是"主导/从零构建"？ |
| 规模感 | 1.0 | 读者能感知项目体量吗？（代码行数/模块数/Agent 数） |
| 冗余度 | 0.8 | 相邻 bullet 是否在说同一件事？ |

### 可读性专项优化（Polish Pipeline）

针对已有简历 bullet 的表达结构优化，**无需代码变更**即可运行：

```
Round 1 ─ Polisher（润色者）
          ↓ 接收当前 bullet → 信息优先级裁剪 → 拆文字墙 → 合并碎片
Round 2 ─ Polish Reviewer（可读性审查官）
          ↓ 5 维可读性审查：文字墙 / 括号嵌套 / 可扫描性 / 信息冗余 / 信息密度
          ├── 全部维度 ≥ 8.5 分？→ 通过
          └── 不满足 → 修订后重审（最多 3 轮）
```

**可读性优化法则**：
- **优先级裁剪**：每 bullet ≤ 1 核心主张 + 2 支撑数据点，超过 2 个数字则裁
- **拆分铁律**：拆分后每条 ≥ 2 句话 + 至少 1 个量化数字，否则禁止拆分
- **优先合并**：相邻 bullet 说同一件事的不同侧面 → 合并
- **目标数量**：4-6 条 bullets / 项目

Polish 使用**独立审查官**（`SYSTEM_POLISH_REVIEWER`），专注于可读性维度，与内容生成的 FAANG 审查官分离，确保评分锚定准确。

**Hash 去重**：`run` 命令中 polish 阶段会对比当前 bullet 的 hash，内容未变则跳过 LLM 调用，避免浪费 Token。

### 数据流

```
config.yaml ──→ checker.py ──→ state.json
                    ↓
              agent.yaml ──→ 发现 scheduled_agents（调度关系）
                    ↓
              generator.py ──→ LLM API（DeepSeek / OpenAI 兼容）
                    ↓
              updater.py  ──→ main.tex（带标记注释的 LaTeX 源码）
                    ↓
              builder.py  ──→ resume.pdf（编译输出）
                    ↓
              notifier.py ──→ Windows Toast 桌面通知
```

### 调度关系感知（Hierarchy-Aware Generation）

当追踪的项目是一个**调度/编排系统**（如 Agent Hub）时，resume-sync 会自动读取该项目的 `agent.yaml`，发现其中声明的 `scheduled_agents` 字段，并在 LLM 生成 prompt 中注入子项目关系上下文。

**效果对比**：

| 无调度关系感知 | 有调度关系感知 |
|----------------|----------------|
| "开发了 Agent Hub，一个多 Agent 调度系统" | "设计了一套多 Agent 协同调度框架（Agent Manifest 协议 + LLM 意图路由 + DAG 并行调度），统一调度 3 个异构专业 Agent（代码生成、质量诊断、简历同步），通过 CLI Bridge 实现零侵入集成" |
| 简历读起来像做了几个独立项目 | 简历体现系统架构能力和工程落地深度 |

**工作原理**（自动，无需额外配置）：

```
1. generator.py 读取 <项目>/agent.yaml
       ↓
2. 发现 scheduled_agents 字段？
       ↓ 是
3. 构建层次上下文（子 Agent 名、角色、接口类型）
       ↓
4. 注入到 LLM 的生成 prompt 中
       ↓
5. LLM 产出体现调度架构的简历描述
       ↓ 否
6. 使用标准 prompt（无特殊处理）
```

**scheduled_agents 协议**（在项目的 agent.yaml 中声明）：

```yaml
# 示例：Agent Hub 的 agent.yaml
name: agent-hub
display_name: "Agent Hub Scheduler"
protocol: internal

scheduled_agents:
  - name: omniagent
    repo: D:/OmniAgent_CLI
    role: "通用 AI 编程 Agent — 代码分析、生成、重构"
    interface: cli
  - name: smartbench
    repo: D:/SmartBench
    role: "代码质量诊断引擎"
    interface: cli
  - name: resume-sync
    repo: D:/工作/resume-sync
    role: "简历自动同步器"
    interface: cli
```

> 💡 **设计原则**：`scheduled_agents` 是 Agent Manifest 协议的可选扩展字段。resume-sync 读取它但不要求它——如果项目的 `agent.yaml` 中没有此字段，生成流程照常进行，无任何影响。此功能对用户完全透明。与 [Agent Hub](https://github.com/xianyu-sheng/Agent-hub) 的调度系统天然配合。

---

## 缓存策略

- **`state.json`**：记录每个项目上次检测的 commit hash，用于增量对比。**不应提交到 Git**（已在 `.gitignore` 中排除）
- **`cache/*.diff`**：按 `{project}_{commit_hash[:8]}.diff` 缓存 diff 原文，避免对同一 commit 重复执行 `git diff`
- **`processed_commits`**：追踪已反映到简历的 commit，支持 `mark_applied()`
- **首次运行**：记录当前 HEAD 为基线，不触发更新（避免对历史代码生成变更）

---

## 安全设计

| 机制 | 说明 |
|------|------|
| **标记块隔离** | 只修改 `% RESUME_PROJECT_START/END` 内的内容 |
| **自动备份** | 每次写入 `.tex` 前创建 `.bak_{时间戳}` 副本 |
| **PDF 备份** | 每次编译 PDF 前创建时间戳备份到 `backups/` 目录 |
| **交互确认** | `apply` 默认需要输入 `y` 确认 |
| **文件锁处理** | PDF 被阅读器占用时自动重试 3 次，不损坏原文件 |
| **编译失败保护** | 编译失败不覆盖原 PDF，不会回滚 `.tex` |
| **`auto_apply: false`** | 后台 daemon 默认只通知不自动改简历 |
| **API Key 保护** | 通过环境变量 `${DEEPSEEK_API_KEY}` 引用，不写入 config.yaml 明文 |

---

## 常见问题

### Q: DeepSeek API 调用失败？

运行 `echo $env:DEEPSEEK_API_KEY` 验证环境变量是否正确设置（确保以 `sk-` 开头）。如果是旧终端窗口，关闭重新开一个使 `setx` 生效。确保 DeepSeek 账户余额充足。

### Q: 编译 PDF 报错 "fontspec.sty not found"？

确保安装了完整的 TeX Live，特别是 `xelatex` 和中文宏包：
```bash
tlmgr install ctex xecjk fontspec
```

### Q: Windows Toast 通知没弹出来？

Toast 在某些精简版 Windows / Server 版上可能不可用。不影响核心功能，命令行输出仍会显示所有信息。

### Q: 可以用其他 LLM 吗？

支持任何 OpenAI 兼容接口的 LLM。只需修改 `config.yaml`：
```yaml
llm:
  api_base: "https://api.openai.com/v1"
  model: "gpt-4o"
```

### Q: 如何在多台电脑间同步？

`state.json` 和 `cache/` 是本地状态，不应跨机器共享。每台电脑独立初始化基线即可。`config.yaml` 中每台电脑的本地路径不同，也不应共享。

### Q: macOS / Linux 能用吗？

核心功能（check / plan / apply / build）完全可用。仅 Windows Toast 通知不可用（会静默跳过，不影响流程）。后台 daemon 可使用 cron 替代 Windows Task Scheduler。

---

## License

MIT

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)

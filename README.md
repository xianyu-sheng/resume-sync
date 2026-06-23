# Resume-Sync

> 自动检测项目仓库变更 → LLM 生成简历描述 → 更新 LaTeX 源码 → 编译 PDF → 覆盖输出

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 痛点

求职期间，每次往项目仓库 push 代码后，都需要**手动**去 Overleaf 更新简历的项目描述，然后再编译下载 PDF。这个过程重复、容易遗忘、描述质量不稳定。

**Resume-Sync** 将这个过程自动化：检测到你项目有新的 commit → 调用 DeepSeek API 分析代码变更 → 生成高质量的简历 bullet → 更新 LaTeX 标记块 → 本地编译 PDF → 覆盖你的简历文件。

全程你只需要确认一眼 diff，点一下 `y`。

---

## 工作流

```
你在本地项目仓库提交代码
       ↓
[check]  读取本地仓库 HEAD，与上次记录的 commit 比较
       ↓  有新 commit？
[plan]   提取 git diff → DeepSeek 分析变更 → 生成候选 bullet
       ↓  用户确认
[apply]  替换 main.tex 中 % RESUME_PROJECT_START/END 标记块
       ↓
[build]  latexmk -xelatex → 输出 PDF → 覆盖目标文件
       ↓
[notify] Windows Toast 通知 "简历已更新"
```

---

## 安装

### 环境要求

| 组件 | 说明 |
|------|------|
| **Python** | 3.10+ |
| **TeX Live** | 需安装 `latexmk`、`xelatex`（中文简历必须） |
| **Git** | 项目仓库需为 Git 仓库 |
| **DeepSeek API Key** | 用于 LLM 生成简历描述 |

### 步骤

```bash
# 1. 克隆仓库
git clone https://github.com/xianyu-sheng/resume-sync.git
cd resume-sync

# 2. 安装依赖
pip install -r requirements.txt

# 3. 设置 DeepSeek API Key
setx DEEPSEEK_API_KEY "你的API Key"
# 设置后需要重新打开终端使环境变量生效

# 4. 编辑 config.yaml，填入你的路径
# 详见下方「配置」章节
```

---

## 配置

编辑 `config.yaml`：

```yaml
resume:
  tex_path: "D:/工作/Agent开发简历_修改版_ (1)/main.tex"   # LaTeX 源码路径
  pdf_output: "D:/工作/Agent开发简历_.pdf"                 # 最终 PDF 输出路径

projects:
  - key: omniagent                    # 项目唯一标识（对应 LaTeX 标记）
    name: "OmniAgent"                 # 项目名称（用于 LLM prompt）
    repo_local: "D:/OmniAgent_CLI"    # 本地 Git 仓库路径
    enabled: true                     # 是否追踪
  # 添加新项目只需复制上面 4 行
  - key: my-new-project
    name: "My New Project"
    repo_local: "D:/projects/my-new-project"
    enabled: true

llm:
  provider: "deepseek"
  api_key: "${DEEPSEEK_API_KEY}"      # 从环境变量读取
  api_base: "https://api.deepseek.com/v1"
  model: "deepseek-chat"

build:
  engine: "latexmk"
  args: ["-xelatex", "-interaction=nonstopmode"]
  backup: true
  backup_dir: "D:/工作/resume-sync/backups"

daemon:
  interval_minutes: 30                # 后台检测间隔
  auto_apply: false                   # false=只通知不自动改简历
  notify_on_change: true
```

---

## 使用

### 基础命令

```bash
cd resume-sync

# 查看所有项目追踪状态
python -m src.cli status

# 检查项目是否有新 commit
python -m src.cli check              # 检查所有
python -m src.cli check omniagent    # 只检查 omniagent

# 生成更新建议（调用 LLM）
python -m src.cli plan               # 为所有有变更的项目生成
python -m src.cli plan omniagent     # 只为 omniagent 生成
python -m src.cli plan --dry-run     # 不调 API，打印 prompt 供调试

# 应用更新到 LaTeX 文件
python -m src.cli apply              # 交互式确认
python -m src.cli apply --yes        # 跳过确认

# 编译 PDF
python -m src.cli build

# 全流程一键执行（check → plan → apply → build）
python -m src.cli run
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
python -m src.cli plan omniagent
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
    % RESUME_PROJECT_START: omniagent
    \item \textbf{项目描述：} ...
    \item \textbf{核心引擎：} ...
    \item \textbf{工具生态：} ...
    % RESUME_PROJECT_END: omniagent
\end{itemize}
```

- `START` 和 `END` 必须成对出现
- `omniagent` 必须与 `config.yaml` 中的 `key` 一致
- 标记之外的内容（项目标题、技术栈行、链接）不会被修改
- 工具会**完整替换**标记块内的 bullet list

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
    repo_local: "D:/projects/new-project"
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
├── config.yaml              # 配置文件
├── state.json               # 运行时状态（commit hash 等，自动管理）
├── requirements.txt         # Python 依赖（PyYAML + openai）
├── .gitignore
├── cache/                   # diff 缓存（按 commit hash 索引）
├── backups/                 # PDF 时间戳备份
├── src/
│   ├── __init__.py
│   ├── cli.py               # CLI 主入口（argparse 子命令）
│   ├── checker.py           # Git 变更检测 + 状态管理 + 缓存
│   ├── generator.py         # LLM 简历描述生成（DeepSeek API）
│   ├── updater.py           # LaTeX 标记块解析与替换
│   ├── builder.py           # latexmk 编译 + PDF 输出 + 错误处理
│   ├── notifier.py          # Windows Toast 原生通知
│   └── daemon.py            # 后台轮询模式（供计划任务调用）
└── README.md
```

### 数据流

```
config.yaml ──→ checker.py ──→ state.json
                    ↓
              generator.py ──→ DeepSeek API
                    ↓
              updater.py  ──→ main.tex (写入)
                    ↓
              builder.py  ──→ Agent开发简历_.pdf (输出)
                    ↓
              notifier.py ──→ Windows Toast
```

---

## 缓存策略

- **`state.json`**：记录每个项目上次检测的 commit hash，增量对比
- **`cache/*.diff`**：按 `{project}_{commit_hash[:8]}.diff` 文件名缓存 diff 原文，避免对同一 commit 重复提取
- **`processed_commits`**：追踪已反映到简历的 commit，支持 `mark_applied()`
- **首次运行**：记录当前 HEAD 为基线，不触发更新

---

## 安全设计

| 机制 | 说明 |
|------|------|
| **标记块隔离** | 只修改 `% RESUME_PROJECT_START/END` 内的内容 |
| **自动备份** | 每次写入 `.tex` 前创建 `.bak_{时间戳}` 副本 |
| **PDF 备份** | 每次编译 PDF 输出到 `backups/` 目录 |
| **交互确认** | `apply` 默认需要输入 `y` 确认 |
| **文件锁处理** | PDF 被占用时重试 3 次，不损坏原文件 |
| **编译失败保护** | 编译失败不覆盖原 PDF，不回滚 `.tex` |
| **`auto_apply: false`** | 后台 daemon 默认只通知不自动改简历 |

---

## 常见问题

### Q: DeepSeek API 调用失败？
检查 `DEEPSEEK_API_KEY` 环境变量是否正确设置。运行 `echo %DEEPSEEK_API_KEY%` 验证。确保余额充足。

### Q: 编译 PDF 报错 "fontspec.sty not found"？
确保安装了完整的 TeX Live，特别是 `xelatex` 和中文宏包：
```bash
tlmgr install ctex xecjk fontspec
```

### Q: Windows Toast 通知没弹出来？
Toast 在某些精简版 Windows 上可能不可用。不影响核心功能，命令行输出仍会显示所有信息。

### Q: 如何在 Overleaf 上编辑同步？
当前版本专注于本地编译。Overleaf 同步策略：
- **免费方案**：在 Overleaf 网页上手动上传修改后的 `.tex`
- **付费方案**：使用 Overleaf Git Integration 进行 `git push`

### Q: 可以用其他 LLM 吗？
支持。任何 OpenAI 兼容接口的 LLM 都可以用。修改 `config.yaml` 中的 `api_base` 和 `model` 即可。例如：
```yaml
llm:
  api_base: "https://api.openai.com/v1"
  model: "gpt-4o"
```

---

## License

MIT

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)

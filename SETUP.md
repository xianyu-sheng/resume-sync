# Resume-Sync Ubuntu 环境安装指南

> 适用：Ubuntu 22.04/24.04 LTS · 给 AI 编程工具的标准配置指令

---

## 一键安装（推荐）

将以下指令直接发给 AI 编程工具（Claude Code / Cursor / Copilot）：

```
请帮我在 Ubuntu 上配置 resume-sync 的完整运行环境，包括：

1. 安装系统依赖
2. 安装 LaTeX（xelatex + latexmk）
3. 克隆 resume-sync 仓库
4. 安装 Python 依赖
5. 配置 Git 用户信息
6. 验证所有组件可用
```

---

## 手动安装步骤

### 1. 系统基础依赖

```bash
sudo apt update
sudo apt install -y \
  python3 python3-pip python3-venv \
  git curl wget \
  build-essential
```

### 2. LaTeX 环境（核心，约 800MB）

```bash
# 安装完整 TeX Live（推荐，避免缺包问题）
sudo apt install -y texlive-xetex texlive-latex-recommended texlive-latex-extra

# 安装 latexmk 编译引擎
sudo apt install -y latexmk

# 安装中文字体（简历使用 ctex 宏包）
sudo apt install -y fonts-noto-cjk

# 验证
xelatex --version
latexmk --version
```

> ⚠️ Ubuntu 最小化安装 LaTeX 可能缺包（如 `ctex`、`fontawesome5`），建议安装 `texlive-latex-extra`。

### 3. 克隆仓库

```bash
# 创建开发目录
mkdir -p ~/dev && cd ~/dev

# 克隆 resume-sync
git clone https://github.com/xianyu-sheng/resume-sync.git
cd resume-sync

# 克隆被追踪的项目（Agent-hub、OmniAgent 等）
git clone https://github.com/xianyu-sheng/Agent-hub.git ../Agent-hub
git clone https://github.com/xianyu-sheng/SmartBench.git ../SmartBench
git clone https://github.com/xianyu-sheng/omniagent.git ../OmniAgent_CLI
```

### 4. Python 环境

```bash
cd ~/dev/resume-sync

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 验证
python -m src.cli --help
```

### 5. 配置文件适配（Ubuntu 路径）

编辑 `config.yaml`，将 Windows 路径替换为 Ubuntu 路径：

```yaml
resume:
  tex_path: "/home/<用户名>/dev/resume-latex/main.tex"   # LaTeX 源文件
  pdf_output: "/home/<用户名>/dev/resume.pdf"            # PDF 输出

projects:
  - key: agent-hub
    name: "Agent Hub"
    repo_local: "/home/<用户名>/dev/Agent-hub"
    enabled: true
  - key: omniagent
    name: "OmniAgent"
    repo_local: "/home/<用户名>/dev/OmniAgent_CLI"
    enabled: true
  - key: smartbench
    name: "SmartBench"
    repo_local: "/home/<用户名>/dev/SmartBench"
    enabled: true

llm:
  provider: "deepseek"
  api_key: "${DEEPSEEK_API_KEY}"
  api_base: "https://api.deepseek.com/v1"
  model: "deepseek-chat"

build:
  engine: "latexmk"
  args: ["-xelatex", "-interaction=nonstopmode"]
  backup: true
  backup_dir: "/home/<用户名>/dev/resume-sync/backups"
```

> 替换 `<用户名>` 为你的实际用户名（`whoami` 查看）

### 6. 环境变量

```bash
# 添加到 ~/.bashrc 或 ~/.zshrc
echo 'export DEEPSEEK_API_KEY="sk-xxxxxxxx"' >> ~/.bashrc
source ~/.bashrc
```

### 7. 验证安装

```bash
cd ~/dev/resume-sync
source .venv/bin/activate

# 检查追踪的项目状态
python -m src.cli status

# 测试完整流水线（dry run）
python -m src.cli run --dry-run
```

---

## 常见问题

| 问题 | 解决 |
|------|------|
| `ctex` 宏包缺失 | `sudo apt install -y texlive-lang-chinese` |
| `fontawesome5` 缺失 | `sudo apt install -y texlive-fonts-extra` |
| 中文字体乱码 | `sudo apt install -y fonts-noto-cjk fonts-noto-cjk-extra` |
| `latexmk` 命令不存在 | `sudo apt install -y latexmk` |
| 编译超时 | `config.yaml` 中降低 `review.max_rounds` 或关闭审查 |

---

## 与 AI 编程工具配合使用

如果你在笔记本上使用 Claude Code / Cursor / Copilot 等工具，只需说：

> 按照 ~/dev/resume-sync/SETUP.md 的步骤帮我配置环境

AI 工具会按照本文档逐步执行安装。

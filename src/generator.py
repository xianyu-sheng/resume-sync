"""
LLM-powered resume bullet generation via DeepSeek API (OpenAI-compatible).

Constructs a prompt from git diff + current resume project description,
calls the DeepSeek API, and returns structured JSON output.
"""

import json
import re
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI


class Generator:
    """Generates updated resume bullet points using LLM."""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        llm_cfg = self.config.get("llm", {})
        api_key = llm_cfg.get("api_key", "")
        if api_key.startswith("${"):
            import os
            env_var = api_key[2:-1]
            api_key = os.environ.get(env_var, "")

        self.client = OpenAI(
            api_key=api_key,
            base_url=llm_cfg.get("api_base", "https://api.deepseek.com/v1"),
        )
        self.model = llm_cfg.get("model", "deepseek-chat")
        self.max_retries = 2
        self.timeout = 60

    # ---- helpers ----

    def _read_current_bullets(self, tex_path: str, project_key: str) -> str:
        """Read the current bullet content for a project from the .tex file."""
        tex = Path(tex_path).read_text(encoding="utf-8")
        pattern = rf"% RESUME_PROJECT_START: {project_key}\s*\n(.*?)% RESUME_PROJECT_END: {project_key}"
        match = re.search(pattern, tex, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def _read_readme(self, repo_path: str) -> str:
        """Read README.md (first 200 lines) from the project repo if available."""
        for name in ("README.md", "readme.md", "README.MD"):
            path = Path(repo_path) / name
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                lines = text.split("\n")[:200]
                return "\n".join(lines)
        return ""

    def _build_prompt(self, project_name: str, current_bullets: str,
                      diff: str, readme: str) -> str:
        """Construct the LLM prompt for resume bullet generation."""
        prompt = f"""你是一位资深技术简历撰写专家。以下是求职者简历中 "{project_name}" 项目的当前描述，以及该项目代码仓库的最新变更（git diff）。请根据代码变更更新简历描述。

## 当前简历中该项目的描述
{current_bullets}

## 代码变更 (git diff)
{diff[:8000]}

## 项目 README（供参考上下文）
{readme[:2000]}

## 要求
1. 分析代码变更的**业务含义和技术价值**——不要罗列文件变更，要提炼出对招聘方有吸引力的能力证明
2. 生成该项目**完整**的简历 bullet list（不是增量——直接输出你应该出现在简历中的最终条目）
3. 保持与现有简历一致的风格：
   - 中文为主，关键技术名词保留英文
   - 每条以 \\\\item \\\\textbf{{标题：}} 开头
   - 每条 1-3 句话，突出量化指标和工程价值
   - 3-5 条 bullets
4. 如果变更很小（如 typo fix、注释修改、格式化），返回与原内容相同的 bullets，并标记 requires_update: false
5. **LaTeX 转义**：输出中的特殊字符必须正确转义——下划线写为 \\_（即使在 \\texttt{{}} 内部也如此），& 写为 \\&，% 写为 \\%，$ 写为 \\$，# 写为 \\#，{{ 写为 \\{{，}} 写为 \\}}，~ 写为 \\textasciitilde{{}}

## 输出格式（严格 JSON）
```json
{{
  "bullets": [
    "\\\\item \\\\textbf{{标题：}} 描述内容...",
    "\\\\item \\\\textbf{{标题：}} 描述内容..."
  ],
  "summary": "一句话概括本次更新了什么",
  "requires_update": true
}}
```

只输出 JSON，不要其他文字。"""
        return prompt

    def _parse_response(self, content: str) -> dict:
        """Parse LLM JSON response, handling markdown code fences."""
        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            # Remove opening fence
            content = re.sub(r"^```\w*\s*\n?", "", content)
            # Remove closing fence
            content = re.sub(r"\n?```\s*$", "", content)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from the middle of text
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise

    # ---- public API ----

    def generate(self, project_key: str, diff: str,
                 tex_path: str, repo_path: str,
                 dry_run: bool = False) -> dict:
        """
        Generate updated resume bullets for a project.

        Args:
            project_key: Config key of the project (e.g. 'omniagent')
            diff: Git diff text
            tex_path: Path to the LaTeX resume file
            repo_path: Path to the project's git repository
            dry_run: If True, return the prompt without calling LLM

        Returns:
            {"bullets": [...], "summary": "...", "requires_update": bool,
             "prompt": str (if dry_run), "error": str | None}
        """
        # Resolve project name from config
        project_name = project_key
        for proj in self.config.get("projects", []):
            if proj["key"] == project_key:
                project_name = proj.get("name", project_key)
                break

        current_bullets = self._read_current_bullets(tex_path, project_key)
        readme = self._read_readme(repo_path)
        prompt = self._build_prompt(project_name, current_bullets, diff, readme)

        if dry_run:
            return {
                "bullets": [],
                "summary": "",
                "requires_update": False,
                "prompt": prompt,
                "error": None,
            }

        # Call LLM with retries
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是一位资深技术简历撰写专家。只输出 JSON，不要其他文字。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=4000,
                    timeout=self.timeout,
                )
                content = response.choices[0].message.content
                parsed = self._parse_response(content)
                parsed["prompt"] = prompt
                parsed["error"] = None
                return parsed

            except Exception as e:
                last_error = str(e)
                if attempt < self.max_retries:
                    import time
                    time.sleep(2 ** attempt)  # exponential backoff: 1s, 2s

        return {
            "bullets": [],
            "summary": "",
            "requires_update": False,
            "prompt": prompt,
            "error": f"LLM API call failed after {self.max_retries + 1} attempts: {last_error}",
        }

    def generate_dry_run(self, project_key: str, diff: str,
                         tex_path: str, repo_path: str) -> str:
        """Return the prompt without calling LLM (for debugging)."""
        result = self.generate(project_key, diff, tex_path, repo_path, dry_run=True)
        return result.get("prompt", "")

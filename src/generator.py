"""
LLM-powered resume bullet generation via DeepSeek API (OpenAI-compatible).

Constructs a prompt from git diff + current resume project description,
calls the DeepSeek API with multi-round self-review, and returns
structured JSON output.

Pipeline:  Generate (Round 1) → Review (Round 2) → Revise (Round 3)
"""

import json
import re
import time
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI

# ── System prompts ──────────────────────────────────────────

SYSTEM_GENERATOR = """\
你是一位资深技术简历撰写专家，专门为应聘者撰写对标全球顶尖科技公司 \
（FAANG、ByteDance、Huawei 等）的简历。你对顶级公司的招聘标准、面试官 \
关注点、以及 STAR 方法论的运用达到了业界一流水平。

## 核心撰写标准

### 1. 影响力驱动（Impact-driven）
- 每条 bullet 必须回答：这项工作的业务价值是什么？
- 尽量量化：提升了 X%、减少了 Y ms、支撑了 Z 万用户
- 避免纯过程描述（"负责开发了 XX 模块"→ 不合格）

### 2. STAR 方法论
- Situation: 在什么背景下
- Task: 要解决什么问题
- Action: 你做了什么（技术选型/架构设计/攻坚）
- Result: 产出了什么可量化的结果

### 3. 技术深度与广度
- 展现系统设计能力（高并发、分布式、容灾等关键词）
- 展现工程素养（CI/CD、自动化测试、代码质量、监控告警）
- 关键技术名词保留英文原文

### 4. 差异化竞争力
- 这条描述能否让面试官觉得"这个人不一样"？
- 避免任何初级工程师也能写的描述
- 突出主导性（"主导设计"、"从零构建"、"自主研发"）和决策力

### 5. 对比校准
- 每条生成后，想象这是一位 Google L5 / 阿里 P7 级别的候选人写的
- 如果读起来像校招简历（堆砌技术名词、缺少业务 impact），推倒重写

只输出 JSON，不要其他文字。"""

SYSTEM_REVIEWER = """\
你是一位严苛的简历审查官。你会用顶级科技公司（FAANG / ByteDance / Huawei）\
的招聘标准来审视每一条简历描述，找出生硬、模糊、缺乏量化、\
"看起来很厉害但经不起追问"的表述。

请以 JSON 格式输出审查结果：

```json
{
  "overall_score": 7.5,
  "critique": "对整体 bullet list 的综合评价，指出最强和最弱的地方",
  "per_bullet": [
    {
      "index": 0,
      "score": 7.0,
      "issues": ["缺少量化指标", "Actions 描述太过程化"],
      "suggestion": "增加具体的性能提升数据，改为结果导向的表述"
    }
  ],
  "must_fix": ["缺少量化指标的条目必须先补上数据"],
  "ready": false
}
```

评分标准（1-10）：
- 9-10: 可直接投 Google / ByteDance，每一条都有清晰 Impact
- 7-8: 不错，但部分条目可以更量化、更有冲击力
- 5-6: 偏过程化，缺少结果导向，读起来像日常工作记录
- 1-4: 不合格，有重大缺陷（LaTeX 语法错误、无实际内容、堆砌名词）

只输出 JSON，不要其他文字。"""

SYSTEM_REVISER = """\
你是一位资深技术简历润色专家。你会根据审查意见对简历 bullet list 进行精准修改，\
同时确保不引入新的问题、不丢失原有亮点、不违反 LaTeX 转义规则。

只输出 JSON（格式与原始生成相同），不要其他文字。"""


# ── Generator class ──────────────────────────────────────────

class Generator:
    """Generates updated resume bullet points using LLM with multi-round review."""

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
        self.timeout = 120  # per-call timeout (increased for multi-round)

        # Multi-round review settings
        review_cfg = self.config.get("review", {})
        self.review_enabled = review_cfg.get("enabled", True)
        self.max_rounds = review_cfg.get("max_rounds", 3)
        self.pass_threshold = review_cfg.get("pass_threshold", 8.0)

    # ── helpers ───────────────────────────────────────────────

    def _read_current_bullets(self, tex_path: str, project_key: str) -> str:
        tex = Path(tex_path).read_text(encoding="utf-8")
        pattern = rf"% RESUME_PROJECT_START: {project_key}\s*\n(.*?)% RESUME_PROJECT_END: {project_key}"
        match = re.search(pattern, tex, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def _read_readme(self, repo_path: str) -> str:
        for name in ("README.md", "readme.md", "README.MD"):
            path = Path(repo_path) / name
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                return "\n".join(text.split("\n")[:200])
        return ""

    def _call_llm(self, system: str, user: str,
                  temperature: float = 0.3,
                  max_tokens: int = 4000) -> str | None:
        """Call the LLM with retries. Returns content string or raises."""
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self.timeout,
                )
                return response.choices[0].message.content
            except Exception as e:
                last_error = str(e)
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
        raise RuntimeError(
            f"LLM API call failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def _parse_response(self, content: str) -> dict:
        """Parse LLM JSON response, handling markdown code fences."""
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```\w*\s*\n?", "", content)
            content = re.sub(r"\n?```\s*$", "", content)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise

    def _format_bullets_display(self, bullets: list[str]) -> str:
        """Format bullet list for display within prompts (numbered)."""
        return "\n".join(f"  {i+1}. {b}" for i, b in enumerate(bullets))

    # ── prompt builders ───────────────────────────────────────

    def _build_generate_prompt(self, project_name: str, current_bullets: str,
                               diff: str, readme: str) -> str:
        """Build the Round-1 generation prompt with 大厂 standards."""
        return f"""以下是求职者简历中 "{project_name}" 项目的当前描述，以及该项目代码仓库的最新变更（git diff）。请根据代码变更更新简历描述。

## 当前简历中该项目的描述
{current_bullets}

## 代码变更 (git diff)
{diff[:8000]}

## 项目 README（供参考上下文）
{readme[:2000]}

## 要求
1. 分析代码变更的**业务含义和技术价值**——不要罗列文件变更，要提炼出对招聘方有吸引力的能力证明
2. 生成该项目**完整**的简历 bullet list（不是增量——直接输出你应该出现在简历中的最终条目）
3. 风格要求：
   - 中文为主，关键技术名词保留英文
   - 每条以 \\\\item \\\\textbf{{标题：}} 开头
   - 每条 1-3 句话，突出量化指标和工程价值
   - 3-5 条 bullets
   - 如果代码 diff 中有具体数字（性能提升、代码行数、模块数量等），务必引用
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

    def _build_review_prompt(self, bullets: list[str], project_name: str,
                             diff: str) -> str:
        """Build the Round-2 review/critique prompt."""
        return f"""请审查以下 "{project_name}" 项目的简历 bullet list。

## 待审查的 bullets
{self._format_bullets_display(bullets)}

## 原始代码变更（供参考）
{diff[:3000]}

## 审查要点
请逐条对照以下标准打分：

1. **Impact 量化** — 是否有具体数字、百分比、时间跨度？还是只有模糊形容词？
2. **STAR 完整性** — 是否包含了背景→行动→结果？
3. **技术深度** — 读起来更像 L5+ 还是校招水平？有没有展现架构/系统设计能力？
4. **差异化** — 换一个候选人名字是否同样适用？还是能看出独特贡献？
5. **LaTeX 合规** — 下划线、百分号、花括号等是否正确转义？
6. **中文质量** — 是否有翻译腔、语法错误、中英混杂不当的问题？

只输出 JSON，不要其他文字。"""

    def _build_revise_prompt(self, bullets: list[str], critique: str,
                             project_name: str, diff: str) -> str:
        """Build the Round-3 revision prompt incorporating critique."""
        return f"""请根据以下审查意见，修订 "{project_name}" 项目的简历 bullet list。

## 当前 bullets
{self._format_bullets_display(bullets)}

## 审查意见
{critique}

## 原始代码变更（供参考）
{diff[:3000]}

## 修订要求
1. 逐条落实审查意见中的改进建议
2. 保持原有的技术亮点不被稀释
3. 确保所有 LaTeX 特殊字符正确转义
4. 输出**完整**的 bullet list（不是只输出修改的条目）

## 输出格式（严格 JSON）
```json
{{
  "bullets": [
    "\\\\item \\\\textbf{{标题：}} 描述内容...",
    "\\\\item \\\\textbf{{标题：}} 描述内容..."
  ],
  "summary": "一句话概括修订内容",
  "requires_update": true
}}
```

只输出 JSON，不要其他文字。"""

    # ── public API ────────────────────────────────────────────

    def generate(self, project_key: str, diff: str,
                 tex_path: str, repo_path: str,
                 dry_run: bool = False) -> dict:
        """
        Generate updated resume bullets with multi-round self-review.

        Pipeline:
          Round 1 — Generate initial bullets
          Round 2 — Self-review against 大厂 standards
          Round 3 — Revise based on review feedback
          (repeat Rounds 2-3 if score below threshold and rounds remain)

        Returns:
          {"bullets": [...], "summary": "...", "requires_update": bool,
           "review_score": float | None, "review_rounds": int,
           "prompt": str (if dry_run), "error": str | None}
        """
        project_name = project_key
        for proj in self.config.get("projects", []):
            if proj["key"] == project_key:
                project_name = proj.get("name", project_key)
                break

        current_bullets = self._read_current_bullets(tex_path, project_key)
        readme = self._read_readme(repo_path)

        # ── Dry-run: return the Round-1 prompt ──
        if dry_run:
            prompt = self._build_generate_prompt(
                project_name, current_bullets, diff, readme)
            return {
                "bullets": [], "summary": "", "requires_update": False,
                "review_score": None, "review_rounds": 0,
                "prompt": prompt, "error": None,
            }

        # ── Round 1: Generate ──────────────────────────────────
        gen_prompt = self._build_generate_prompt(
            project_name, current_bullets, diff, readme)

        try:
            content = self._call_llm(SYSTEM_GENERATOR, gen_prompt,
                                     temperature=0.4, max_tokens=4000)
            result = self._parse_response(content)
        except Exception as e:
            return {
                "bullets": [], "summary": "", "requires_update": False,
                "review_score": None, "review_rounds": 0,
                "prompt": gen_prompt, "error": str(e),
            }

        if not result.get("requires_update", True):
            result["review_score"] = None
            result["review_rounds"] = 1
            result["prompt"] = gen_prompt
            result["error"] = None
            return result

        bullets = result.get("bullets", [])

        # ── Multi-round review (if enabled) ────────────────────
        if not self.review_enabled or len(bullets) == 0:
            result["review_score"] = None
            result["review_rounds"] = 1
            result["prompt"] = gen_prompt
            result["error"] = None
            return result

        review_score = None
        rounds_completed = 1

        for round_num in range(2, self.max_rounds + 1):
            # ── Review phase ───────────────────────────────────
            review_prompt = self._build_review_prompt(
                bullets, project_name, diff)
            try:
                review_content = self._call_llm(
                    SYSTEM_REVIEWER, review_prompt,
                    temperature=0.2, max_tokens=3000)
                review = self._parse_response(review_content)
            except Exception:
                # If review fails, keep current bullets and exit loop
                break

            review_score = review.get("overall_score", 0)

            # ── Check if good enough ───────────────────────────
            if (review.get("ready", False)
                    or (isinstance(review_score, (int, float))
                        and review_score >= self.pass_threshold)):
                bullets = result.get("bullets", bullets)
                rounds_completed = round_num - 1  # review round
                break

            # ── Revise phase ───────────────────────────────────
            critique_text = json.dumps(review, ensure_ascii=False, indent=2)
            revise_prompt = self._build_revise_prompt(
                bullets, critique_text, project_name, diff)
            try:
                revise_content = self._call_llm(
                    SYSTEM_REVISER, revise_prompt,
                    temperature=0.3, max_tokens=4000)
                revised = self._parse_response(revise_content)
                bullets = revised.get("bullets", bullets)
                result = revised
            except Exception:
                # If revise fails, keep previous bullets and exit loop
                break

            rounds_completed = round_num

        result["bullets"] = bullets
        result["review_score"] = review_score
        result["review_rounds"] = rounds_completed
        result["prompt"] = gen_prompt
        result["error"] = None
        return result

    def generate_dry_run(self, project_key: str, diff: str,
                         tex_path: str, repo_path: str) -> str:
        """Return the Round-1 prompt without calling LLM (for debugging)."""
        result = self.generate(project_key, diff, tex_path, repo_path, dry_run=True)
        return result.get("prompt", "")

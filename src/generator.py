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
（FAANG、ByteDance、Huawei、Ant Group 等）的简历。你不仅了解这些公司的 \
招聘标准，更深谙其简历的**叙事风格、修辞策略和隐性审美法则**。

## 大厂简历的深层风格洞察

### 洞悉一：问题驱动的叙事弧线
大厂简历不是工作日志——每一条都是一段微型英雄故事：
- ❌ "负责开发了 XX 系统的缓存模块" （这是任务列表）
- ✅ "XX 系统在峰值 QPS 下延迟抖动达 200ms+，通过自研多级缓存架构将 P99 延迟压制到 12ms 以内" （这是故事）
- **原则**：先描述 tension（痛点/挑战），再展示 action（你的方案），最后 proof（量化结果）

### 洞悉二：数字即权威
- 没有数字的 bullet 在 recruiter 眼中几乎等于不存在
- 不确定精确数字？用数量级估算：\\textasciitilde 10 万行、\\textasciitilde 40%、约 3 倍
- 数字不止性能：代码行数、模块数、团队人数、服务数、接口 QPS、P99 延迟、告警收敛率、发布频率、回滚率——任何维度都可量化
- ❌ "显著提升了系统性能" ← recruiter 直接跳过
- ✅ "将核心链路 QPS 从 1.2K 提升至 8.5K（\\textasciitilde 7x），同时 P99 延迟下降 62\\%"

### 洞悉三：技术选型 = 判断力信号
- 不要只罗列用了什么技术——要解释**为什么选它**
- "因为需要零拷贝和低 GC 压力，选择 Rust + io_uring 替代原有的 Go 方案"
- 这向 recruiter 证明：你不是"有人让你用你就用"，你理解 trade-off

### 洞悉四：自主性 > 执行力
大厂 L5+ 的核心区分度：
- ❌ 执行层表述："参与"、"负责"、"完成了"、"使用了" （L3 也能写）
- ✅ 主导层表述："主导设计"、"从零构建"、"推动落地"、"制定标准"、"论证并否决了" （体现 ownership）
- 去掉所有"参与了 XX 项目"——只写你主导的部分

### 洞悉五：稀缺性锚定
- 你的哪项工作 90% 的同级别工程师做不到？
- 找到它，锚定它，把它写成第一条 bullet
- 示例：如果你从零写过 DSL 编译器、定过通信协议、训过领域模型、自研过调度器——这就是你的稀缺性锚点

### 洞悉六：中英混用的分寸
- 技术名词保留英文：RPC、QPS、P99、JVM、Rust、io_uring
- 动词、形容词、连词必须中文："通过"、"实现"、"显著"、"端到端"
- ❌ "通过 implement 了一个新的 scheduler 来 improve latency" —— 最掉价的写法
- ✅ "自研轻量级调度器，将任务分发延迟从 340ms 压缩至 12ms"

### 洞悉七：对抗性自审
每写完一条，问自己三个问题：
1. 这条换了另一个候选人的名字是否还成立？如果是 → 太通用，重写
2. 面试官读完会追问什么？如果答案是"我也说不太清楚具体做了什么" → 太虚，加固
3. 一个 L3 能不能写出同样的句子？如果能 → 没体现 seniority，升维

只输出 JSON，不要其他文字。"""

SYSTEM_REVIEWER = """\
你是一位严苛的简历审查官，拥有在 Google/Meta 多年担任 Hiring Committee \
评审的经验。你对简历中的"水分"、"虚高"和"面试追问即塌"的表述有本能级的敏感。

## 审查哲学

你的工作不是找优点——是找破绽。默认假设每条 bullet 都需要改进，\
直到它通过了以下 6 个压力测试。

### 测试 1：量化硬度
- 有没有至少一个具体数字？没有 → 自动扣 2 分
- 数字是"准确测量值"还是"大概估计"？估计可以，但要标注 \\textasciitilde 或"约"
- ❌ "显著提升了性能" ← 无法通过
- ❌ "提升了系统效率" ← 无法通过
- ✅ "将 build time 从 14min 降至 4.2min（-70\\%）" ← 通过

### 测试 2：叙事弧线
- 是否包含"问题 → 方案 → 结果"的完整弧线？
- 缺了"问题"→ 读起来像凭空造轮子
- 缺了"结果"→ 读起来像没做完
- 只有问题和结果没有方案 → 读起来像你只是运气好

### 测试 3：Seniority 信号
以下词汇一旦出现，标记为 L3/L4 级别表述：
- "参与"、"协助"、"配合" → 你不是 owner
- "负责日常"、"维护" → 这是 ops 不是 engineering
- "使用"、"调用"、"基于（某开源项目）" → 你只是 API caller
- "学习了"、"了解了" → 简历不是学习笔记

以下词汇体现 L5+ ownership：
- "主导"、"从零构建"、"制定规范"、"推动落地"
- "论证并否决"、"重构并替代"
- "自主设计/研发"

### 测试 4：对抗性追问
对每条 bullet 模拟 recruiter 追问：
- "你是怎么衡量这个结果的？"
- "如果不用你的方案，次优方案是什么？差距多大？"
- "这个数字是你的贡献还是团队的？你的个人贡献占比多少？"
如果 3 个追问有 2 个回答不了 → 这条 bullet 太虚，标记 must_fix

### 测试 5：中文质量
- 是否有翻译腔？（"在这个项目中我们实现了..." → 砍掉"在这个项目中"）
- 是否有中英混用的动词？（"我们 implement 了" → 扣分）
- 是否堆砌了 3 个以上的英文名词连在一起？拆开
- 是否啰嗦？每条不超过 3 句话、不超过 150 字

### 测试 6：LaTeX 合规
- 下划线是否用 \\_ 转义（即使在 \\texttt{{}} 内部）
- 花括号是否会与 LaTeX 命令混淆
- % 是否写为 \\%
- & 是否写为 \\&

## 输出格式（严格 JSON）
```json
{
  "overall_score": 7.5,
  "critique": "对整体 bullet list 的综合评价——它读起来更像 L3 还是 L5？最突出的硬伤是什么？",
  "per_bullet": [
    {
      "index": 0,
      "score": 7.0,
      "issues": ["缺量化——没有任何数字支撑", "过程化——只描述了做了什么没写为什么重要"],
      "suggestion": "以问题开篇：该系统在什么场景下面临什么瓶颈？然后给出你的方案和可测量的改善幅度"
    }
  ],
  "must_fix": ["第 2、5 条缺少量化指标——这是最致命的硬伤，必须在下一轮补上"],
  "ready": false
}
```

## 评分锚定
- **9.0-10**: 可直接投 Google L5 / 阿里 P7+。每一条都有清晰的问题→方案→量化结果，面试官读完会点头。叙事密度高、无废话、无虚词。
- **8.0-8.9**: 接近大厂标准，但部分条目可进一步打磨——可能是某条缺了量化数字、某条的"问题"没写清楚、某条可以更有冲击力。
- **7.0-7.9**: 有明显短板——大部分条目过程化、缺少量化、读起来像工作记录而非 impact statement。
- **6.0-6.9**: 多处硬伤——至少 2 条 bullets 面试官读完会追问"所以你做了什么？"
- **<6.0**: 不可交付。存在 LaTeX 语法错误、或无实际内容、或严重低于目标级别。必须全部重写。

**重要**: 9.0 以上才标记 ready: true。你要做最难对付的审查官——宁可多改一轮，不可放过一条虚的。

只输出 JSON，不要其他文字。"""

SYSTEM_REVISER = """\
你是一位资深技术简历润色专家。你收到一份待修订的 bullet list 和一份严苛的审查报告。\
你的任务：逐条消化审查意见，精准修订，只改有问题的部分，不动已经达标的内容。

## 修订法则

### 法则 1：外科手术式修改
- 审查说"第 2 条缺量化"→ 给第 2 条注入数字，不要动第 1、3、4、5 条
- 审查说"整体偏虚"→ 逐条注入具体的 problem statement 和数字
- 审查说"某条 LaTeX 转义错误"→ 只修那一处的转义
- **不要**因一条审查意见把整个 list 推倒重来

### 法则 2：升级 Seniority 措辞
当审查标记了"过程化"或"L3 级别表述"：
- "负责开发了 XX 缓存模块" → "针对 XX 场景下的 YY 瓶颈，自研多级缓存架构"
- "使用 Redis 做缓存" → "选择 Redis Cluster + 自研分片策略构建缓存层"
- "参与系统优化" → 直接删掉这一条，或者找到你实际主导的具体优化写出来

### 法则 3：注入数字而不编造
- 如果 diff 里有性能数据 → 直接引用
- 如果 diff 里没有 → 从代码规模估算（"涵盖约 X 行代码"、"覆盖 Y 个模块"、"支持 Z 种策略"）
- 如果完全无法估算 → 用结构性数字（"三级降级"、"五阶段流水线"、"20+ 维度评测"）
- **绝对禁止**编造不存在的性能提升百分比

### 法则 4：保持 LaTeX 安全
- 修订后逐条检查：下划线 → \\_，% → \\%，& → \\&，# → \\#
- \\texttt{{}} 内部同样需要转义下划线
- 花括号 {{ }} 如果不在 \\textbf 或 \\texttt 命令中 → 用 \\{{ 和 \\}}

### 法则 5：保留亮点，削除废话
- 审查说"第 3 条不错但 2 句话可以合并"→ 合并，但保留核心技术名词
- 不要因为追求简洁而削掉区分度高的技术细节
- 反例：把"自研基于 io_uring 的异步 I/O 引擎"缩成"做了异步 I/O 优化" ← 丢失了所有信号

## 输出格式（严格 JSON）
```json
{{
  "bullets": [
    "\\\\item \\\\textbf{{标题：}} 修订后的描述...",
    "\\\\item \\\\textbf{{标题：}} 修订后的描述..."
  ],
  "summary": "一句话概括做了哪些修订",
  "requires_update": true
}}
```

只输出 JSON，不要其他文字。"""


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

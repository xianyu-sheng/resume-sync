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

### 洞悉八：可扫描性 > 堆砌感（关键——HR 只扫 6 秒）
HR 不会"读"简历——他们**扫**简历。一条 bullet 如果是一堵 250 字的文字墙，直接跳过。
- **铁律**：单句不超过 80 个中文字。超过就拆——用句号，不要用逗号堆砌。
- **信息分层**：核心主张在前（第一句），支撑细节在后。HR 扫第一句就能判断"这条有没有东西"。
- **括号节制**：括号嵌套不超过一层。如果括号里还有括号，说明你需要拆成两句。
- **并行结构**：当列举多个子项时，用一致的句式排比，而不是用逗号串联成长句。
  - ❌ "调度 3 个异构 Agent 协同工作——SmartBench（12 语言 × 8 LLM 供应商的代码诊断引擎，覆盖 13,120 行 C++ 核心代码，诊断准确率 92%）与 resume-sync（Git 变更检测 → LLM 三阶段审查 → LaTeX 编译的简历自动同步器）" ← 这是一堵 120+ 字的文字墙，HR 扫到第 3 个逗号就跳过了
  - ✅ 拆为：先给出核心主张（调度了 N 个 Agent、用什么架构），再分号简述每个 Agent 的 1 个关键指标即可。子 Agent 的详细指标放到各自的独立条目中。
- **"一屏法则"**: 5 条 bullets 加起来，在简历 PDF 上不超过 12 行。如果超过，说明信息密度不足——删废话、合重复、缩修饰。

只输出 JSON，不要其他文字。"""

SYSTEM_REVIEWER = """\
你是一位严苛的简历审查官，拥有在 Google/Meta 多年担任 Hiring Committee \
评审的经验。你对简历中的"水分"、"虚高"和"面试追问即塌"的表述有本能级的敏感。

## 审查哲学

你的工作不是找优点——是找破绽。默认假设每条 bullet 都需要改进，\
直到它通过了以下 10 个维度的压力测试。**任一维度 < 5 分则整条 bullet 必须重写。**

## 十维评分体系（每维 1-10 分）

### 维度 1：量化硬度（权重 1.5）
- 有没有至少一个具体数字？没有 → ≤ 4 分
- 数字是准确测量值还是大概估计？估计值必须标注"约"或 \\textasciitilde
- ❌ "显著提升了性能" → 2 分
- ❌ "提升了系统效率" → 2 分
- ✅ "将 build time 从 14min 降至 4.2min（-70\\%）" → 9 分
- ✅ 多个数字从不同角度量化 → 10 分

### 维度 2：个人贡献区分度（权重 1.5）
- 是否能清楚判断"这是你做的还是团队做的"？
- ❌ "参与"、"协助"、"配合" → 2 分（你不是 owner）
- ❌ "负责日常维护" → 3 分（这是 ops 不是 engineering）
- ❌ "使用某开源项目" → 3 分（你只是 API caller）
- ✅ "主导设计并从零实现" → 9 分
- ✅ "独立负责 XX 模块" → 8 分
- ✅ "由我提出并推动落地" → 9 分

### 维度 3：技术深度（权重 1.2）
- 只说了 WHAT，还是解释了 WHY + HOW？
- ❌ "使用 Redis 做缓存" → 2 分（没有技术决策）
- ❌ "用 Python 写了脚本" → 2 分
- ✅ "针对 XX 场景下 YY 瓶颈，自研多级缓存架构" → 8 分
- ✅ 提及具体技术选型理由、架构权衡 → 9-10 分
- 面试官读完后是否想问"你为什么选这个方案而不是那个？"——如果不会，深度不够

### 维度 4：叙事弧线（权重 1.0）
- 包含"问题 → 方案 → 结果"的完整弧线？
- 缺"问题" → 读起来像凭空造轮子，≤ 5 分
- 缺"结果" → 读起来像没做完，≤ 4 分
- 只有问题和结果没有方案 → 你是运气好还是做了什么？≤ 5 分
- 三条完整且简洁 → 9-10 分

### 维度 5：对抗性追问存活率（权重 1.5）
- "你是怎么衡量这个结果的？测量方法是什么？"
- "如果不用你的方案，次优方案是什么？差距多大？"
- "这个数字是你的贡献还是团队的？你的占比多少？"
- 3 个追问有 ≥2 个无法回答 → ≤ 4 分，必须标记 must_fix
- 3 个追问都能用 bullet 内容直接回应 → 9-10 分

### 维度 6：简洁度、信息密度与可扫描性（权重 1.2）
- 每条 bullet ≤ 3 句话、≤ 150 中文字
- **文字墙检测**：单句超过 80 中文字且只用逗号串联 → ≤ 4 分（HR 扫不动）
- **括号嵌套**：括号内还有括号 → ≤ 5 分（视觉噪音，拆成两句）
- **可扫描性**：第一句是否给出了核心主张？HR 能否扫一眼就抓住要点？→ 不能则 ≤ 5 分
- ❌ 4 句话以上堆砌 → ≤ 5 分
- ❌ 重复形容词（"高效、稳定、可靠"）→ 扣分
- ❌ 一条 bullet 同时描述主项目和子项目的详细指标 → 信息过载，≤ 4 分。子项目细节应放到各自的独立条目
- ✅ 每句话携带新信息，无废话 → 9 分
- ✅ 删掉任何一句后 bullet 就不完整 → 10 分

### 维度 7：LaTeX 合规（权重 1.0）
- 下划线是否用 \\_ 转义（\\texttt{{}} 内部同样需要）
- % → \\%，& → \\&，$ → \\$，# → \\#，~ → \\textasciitilde{{}}
- 花括号 {{ }} 不在 \\textbf/\\texttt 中 → 必须 \\{{ 和 \\}}
- 有任何未转义的特殊字符 → ≤ 3 分，标记 must_fix

### 维度 8：动词强度（权重 0.8）
- ❌ "学习了"、"了解了"、"参与了" → 1-2 分（简历不是学习笔记）
- ❌ "使用"、"调用" → 3 分
- ✅ "设计并实现" → 7 分
- ✅ "主导"、"从零构建"、"制定规范"、"推动落地" → 8-9 分
- ✅ "论证并否决"、"重构并替代" → 10 分

### 维度 9：规模感（权重 1.0）
- 读者能否感知这个项目的体量？
- ❌ 没有代码行数/模块数/用户量/处理量 → ≤ 4 分
- ✅ "覆盖 13,120 行 C++ 核心代码" → 8 分
- ✅ "支持 12 种语言 × 8 个 LLM 供应商" → 8 分
- ✅ "管理 4 个 Agent" → 6 分（可以更好）

### 维度 10：冗余度（权重 0.8）
- 两条相邻 bullet 是否在说同一件事？→ 扣分
- bullet list 是否覆盖了该项目的所有关键贡献？缺了重要部分 → 扣分
- 是否有 bullet 可以删掉而不影响整体叙事？→ 那条 bullet 是冗余的
- 恰好 4-5 条，每条独立且互补 → 9-10 分

## 综合评分计算

```
加权总分 = Σ(维度得分 × 权重) / Σ(权重)
```

**评分锚定**：
- **9.0-10**: 可直接投 Google L5 / 阿里 P7+。每一条都有清晰的问题→方案→量化结果。
- **8.5-8.9**: 接近大厂标准，个别维度可打磨——可能是某条缺量化、某条问题没写清。
- **7.5-8.4**: 有明显短板——过程化、缺少量化、读起来像工作记录而非 impact statement。
- **6.0-7.4**: 多处硬伤——至少 2 条 bullets 面试官追问"所以你做了什么？"
- **<6.0**: 不可交付。存在 LaTeX 语法错误、或无实际内容、或严重低于目标级别。必须全部重写。

**门禁规则**：
- 加权总分 ≥ 8.5 且 无可触发 must_fix 的维度 → ready: true
- 任一维度 < 5 分 → 对应 bullet 必须标记 must_fix
- 加权总分 < 8.5 → ready: false，必须进入修订轮次

## 输出格式（严格 JSON）
```json
{
  "overall_score": 7.8,
  "dimension_scores": {
    "quantified_hardness": 6.0,
    "personal_contribution": 7.0,
    "technical_depth": 8.0,
    "narrative_arc": 6.5,
    "adversarial_survival": 5.0,
    "conciseness": 7.5,
    "latex_compliance": 9.0,
    "verb_strength": 7.0,
    "scale_sense": 6.0,
    "redundancy": 8.0
  },
  "critique": "对整体 bullet list 的综合评价——它读起来更像 L3 还是 L5？最突出的 2 个硬伤是什么？",
  "per_bullet": [
    {
      "index": 0,
      "score": 7.0,
      "worst_dimension": "quantified_hardness",
      "issues": ["缺量化——没有任何数字支撑", "没有写问题背景"],
      "suggestion": "以具体痛点开篇：该系统在什么场景下面临什么瓶颈？然后给出方案和可测量的改善幅度"
    }
  ],
  "must_fix": ["第 2 条缺少量化指标——面试追问即塌", "第 4 条只有方案没有结果"],
  "ready": false
}
```

**重要**: 你是最难对付的审查官。宁可多改一轮，不可放过一条虚的。9.0 分在 Google 内部也不常见——不要轻易给。

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

### 法则 6：拆分文字墙，提升可扫描性
当审查标记了"文字墙"、"单句过长"、"括号嵌套过深"或"信息过载"：
- 一条 bullet 如果是一堵 150+ 字的文字墙 → 拆成 2-3 句短句，用句号分隔
- 括号内还有括号 → 把内层括号的内容拆成独立短句
- 主项目 bullet 里堆了子项目的详细指标（如"SmartBench（12 语言 × 8 LLM...诊断准确率 92%）"）→ 只保留子项目的 1 个关键标签（如"SmartBench（代码诊断引擎）"），删除冗余细节
- **记住**：HR 扫一条 bullet 的时间不超过 2 秒。第一句必须让人知道"你做了什么、结果如何"。

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

    def _read_agent_yaml(self, repo_path: str) -> dict | None:
        """Read agent.yaml from a project repo to discover scheduling relationships.

        Returns the parsed YAML dict, or None if not found / unreadable.
        """
        agent_yaml_path = Path(repo_path) / "agent.yaml"
        if not agent_yaml_path.exists():
            return None
        try:
            with open(agent_yaml_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception:
            return None

    def _build_hierarchy_context(self, agent_yaml: dict | None) -> str:
        """Build context string describing sub-agent scheduling relationships.

        When a project's agent.yaml declares ``scheduled_agents``, this method
        returns Markdown that instructs the LLM to treat the project as an
        orchestration / scheduling system rather than a standalone tool.
        """
        if not agent_yaml:
            return ""
        scheduled = agent_yaml.get("scheduled_agents", [])
        if not scheduled:
            return ""

        parent_name = agent_yaml.get("display_name", agent_yaml.get("name", "本项目"))
        protocol = agent_yaml.get("protocol", "cli")

        lines = [
            "",
            "## 🏗️ 项目架构关系（重要：这是调度/编排系统）",
            "",
            f"**{parent_name}** 的协议类型为 `{protocol}`，它是一个**中央调度系统**，",
            f"通过标准化的 Agent Manifest 协议调度以下 {len(scheduled)} 个专业 Agent 协同工作：",
            "",
        ]
        for sa in scheduled:
            lines.append(
                f"- **{sa['name']}**（{sa.get('interface', 'cli')} bridge）：{sa.get('role', '')}"
            )

        lines.extend([
            "",
            "> ⚠️ **简历撰写指引——请严格遵循：**",
            "> 1. 这个项目的核心价值是**系统架构能力**——设计了一套让多个异构 Agent 协同工作的调度框架",
            "> 2. 简历条目必须突出：Agent Manifest 自描述协议（零侵入）、LLM 意图路由、DAG 并行调度、结果聚合",
            "> 3. **不要**写成「做了 N 个 Agent」——要写成「设计了一套多 Agent 协同调度系统，统一调度 N 个专业 Agent」",
            "> 4. 子 Agent（" + "、".join(sa['name'] for sa in scheduled) + "）各自有独立的简历条目，**此处只聚焦调度系统本身的架构贡献**",
            "> 5. 体现技术深度：协议设计、并发控制、故障隔离、生命周期管理",
        ])
        return "\n".join(lines)

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
                               diff: str, readme: str,
                               hierarchy_context: str = "") -> str:
        """Build the Round-1 generation prompt with 大厂 standards.

        Args:
            hierarchy_context: Optional context about sub-agent scheduling
                relationships (from agent.yaml's ``scheduled_agents``).
                When non-empty, instructs the LLM to treat this project as
                an orchestration system.
        """
        return f"""以下是求职者简历中 "{project_name}" 项目的当前描述，以及该项目代码仓库的最新变更（git diff）。请根据代码变更更新简历描述。

## 当前简历中该项目的描述
{current_bullets}

## 代码变更 (git diff)
{diff[:8000]}

## 项目 README（供参考上下文）
{readme[:2000]}
{hierarchy_context}

## 要求
1. 分析代码变更的**业务含义和技术价值**——不要罗列文件变更，要提炼出对招聘方有吸引力的能力证明
2. 生成该项目**完整**的简历 bullet list（不是增量——直接输出你应该出现在简历中的最终条目）
3. 风格要求：
   - 中文为主，关键技术名词保留英文
   - 每条以 \\\\item \\\\textbf{{标题：}} 开头
   - 每条 1-3 句话，单句 ≤ 80 中文字，突出量化指标和工程价值
   - 3-5 条 bullets
   - **禁止文字墙**：用短句+句号分隔，不要用逗号串联成 150+ 字的长句。括号嵌套不超过一层。
   - 子 Agent 的详细指标不要堆在主项目 bullet 里，只保留 1 个关键标签即可
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
        """Build the Round-2 review/critique prompt (10-dimension FAANG rubric)."""
        return f"""请审查以下 "{project_name}" 项目的简历 bullet list。

## 待审查的 bullets
{self._format_bullets_display(bullets)}

## 原始代码变更（供参考）
{diff[:3000]}

## 审查标准 — 十维评分体系

请逐条对照以下 10 个维度打分（每维 1-10 分），并给出 dimension_scores 对象：

1. **量化硬度** — 有具体数字/百分比/时间跨度吗？数字是测量值还是估算？缺数字 ≤ 4 分
2. **个人贡献区分度** — 能判断"你做的 vs 团队做的"吗？"参与/协助" ≤ 3 分，"主导/从零构建" ≥ 8 分
3. **技术深度** — 说了 WHAT 还是解释了 WHY+HOW？有架构权衡/技术选型理由吗？
4. **叙事弧线** — 有"问题→方案→结果"的完整弧线吗？缺任何一环 ≤ 5 分
5. **对抗性追问存活率** — "你怎么衡量的？""次优方案是什么？""你的贡献占比？"——能回答几个？
6. **简洁度、信息密度与可扫描性** — ≤ 3 句话、≤ 150 字？有文字墙（单句 > 80 字逗号串联）吗？HR 扫一眼能抓住要点吗？括号嵌套过深吗？
7. **LaTeX 合规** — 下划线→\\_，%→\\%，&→\\&，花括号正确转义了吗？
8. **动词强度** — "学习了/参与了"→1-2 分，"设计并实现"→7 分，"主导/从零构建"→9 分
9. **规模感** — 读者能感知项目体量吗？（代码行数/模块数/语言数/Agent 数）
10. **冗余度** — 相邻 bullet 是否重复？是否覆盖了所有关键贡献？缺了重要部分？

**门禁规则**：
- 加权总分 ≥ 8.5 且 任一维度 ≥ 5 分 → ready: true
- 任一维度 < 5 分 → 对应 bullet 必须进入 must_fix
- 加权总分 < 8.5 → ready: false

只输出 JSON（包含 dimension_scores、per_bullet、must_fix、ready），不要其他文字。"""

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

        # ── 读取 agent.yaml，发现调度/子项目关系 ──
        agent_yaml = self._read_agent_yaml(repo_path)
        hierarchy_context = self._build_hierarchy_context(agent_yaml)

        # ── Dry-run: return the Round-1 prompt ──
        if dry_run:
            prompt = self._build_generate_prompt(
                project_name, current_bullets, diff, readme, hierarchy_context)
            return {
                "bullets": [], "summary": "", "requires_update": False,
                "review_score": None, "review_rounds": 0,
                "prompt": prompt, "error": None,
            }

        # ── Round 1: Generate ──────────────────────────────────
        gen_prompt = self._build_generate_prompt(
            project_name, current_bullets, diff, readme, hierarchy_context)

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
            dim_scores = review.get("dimension_scores", {})

            # ── Check if good enough ───────────────────────────
            # Three conditions must ALL be met:
            # 1. LLM self-reports ready: true
            # 2. Weighted overall score ≥ pass_threshold (8.5)
            # 3. Every dimension ≥ 5.0 (no single-dimension fatal flaw)
            all_dims_ok = all(
                (isinstance(v, (int, float)) and v >= 5.0)
                for v in dim_scores.values()
            ) if dim_scores else True  # if no dim scores, fall through to score check

            if (review.get("ready", False)
                    and isinstance(review_score, (int, float))
                    and review_score >= self.pass_threshold
                    and all_dims_ok):
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

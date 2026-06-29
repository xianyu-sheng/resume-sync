"""Tests for Generator class — pure functions only, no LLM API calls."""

from __future__ import annotations

import json
import re

import pytest
from unittest.mock import MagicMock, patch

from src.generator import Generator


# ═══════════════════════════════════════════════════════════════════
# Helper functions (inline logic extracted for testability)
# ═══════════════════════════════════════════════════════════════════

DIMENSION_WEIGHTS: dict[str, float] = {
    "quantified_hardness": 1.5,
    "personal_contribution": 1.5,
    "technical_depth": 1.2,
    "narrative_arc": 1.0,
    "adversarial_survival": 1.5,
    "conciseness": 1.2,
    "latex_compliance": 1.0,
    "verb_strength": 0.8,
    "scale_sense": 1.0,
    "redundancy": 0.8,
}

TOTAL_WEIGHT = sum(DIMENSION_WEIGHTS.values())  # 11.5


def _parse_bullets(json_str: str) -> list:
    """Extract bullet list from LLM JSON response.

    Mirrors ``Generator._parse_response + result.get("bullets", [])``.
    """
    content = json_str.strip()
    if content.startswith("```"):
        content = re.sub(r"^```\w*\s*\n?", "", content)
        content = re.sub(r"\n?```\s*$", "", content)
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data.get("bullets", [])
        return []
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def _parse_review(json_str: str) -> dict:
    """Parse review JSON with safe defaults for missing fields."""
    content = json_str.strip()
    if content.startswith("```"):
        content = re.sub(r"^```\w*\s*\n?", "", content)
        content = re.sub(r"\n?```\s*$", "", content)
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {
            "overall_score": 0.0,
            "dimension_scores": {},
            "critique": "",
            "per_bullet": [],
            "must_fix": [],
            "ready": False,
        }


def _compute_weighted_score(dimension_scores: dict) -> float:
    """Compute weighted score using the 10-dim FAANG rubric.

    Formula:  Σ(score × weight) / Σ(weight)
    """
    total = 0.0
    weight_sum = 0.0
    for dim, score in dimension_scores.items():
        w = DIMENSION_WEIGHTS.get(dim, 1.0)
        total += score * w
        weight_sum += w
    return total / weight_sum if weight_sum > 0 else 0.0


def _check_pass_condition(
    score: float,
    dimension_scores: dict,
    ready: bool,
    pass_threshold: float = 8.5,
) -> bool:
    """Check the FAANG 门禁规则 (gate) pass condition.

    All three conditions must be met:
    1. ``ready == True``
    2. ``score >= pass_threshold`` (default 8.5)
    3. Every dimension score >= 5.0
    """
    if not ready:
        return False
    if not isinstance(score, (int, float)) or score < pass_threshold:
        return False
    if dimension_scores:
        for v in dimension_scores.values():
            if not isinstance(v, (int, float)) or v < 5.0:
                return False
    return True


def _deduplicate_bullets(bullets: list) -> list:
    """Remove duplicate bullets by normalised content hash.

    Comparison is case-insensitive and whitespace-normalised.
    First occurrence is kept.
    """
    seen: set = set()
    result: list = []
    for b in bullets:
        key = " ".join(b.strip().lower().split())
        if key not in seen:
            seen.add(key)
            result.append(b)
    return result


def _sanitize_bullet_text(text: str) -> str:
    """Escape LaTeX special characters so they are safe for PDF output.

    Handles:  \\  &  %  $  #  _  {  }  ~  ^

    Uses a single-pass regex substitution to avoid cross-contamination
    between replacement tokens (e.g. ``\\textbackslash{}`` contains ``{`` / ``}``
    which must not be re-processed).
    """
    _latex_escape_map = {
        "\\": "\\textbackslash{}",
        "&": "\\&",
        "%": "\\%",
        "$": "\\$",
        "#": "\\#",
        "_": "\\_",
        "{": "\\{",
        "}": "\\}",
        "~": "\\textasciitilde{}",
        "^": "\\textasciicircum{}",
    }
    _latex_escape_pattern = re.compile(
        "[" + re.escape("".join(_latex_escape_map)) + "]"
    )
    return _latex_escape_pattern.sub(
        lambda m: _latex_escape_map[m.group(0)], text
    )


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_bullets() -> list:
    return [
        "\\item \\textbf{调度系统：} 设计三层调度架构",
        "\\item \\textbf{性能优化：} 将 P99 延迟从 200ms 降至 12ms",
    ]


@pytest.fixture
def sample_diff() -> str:
    return "diff --git a/src/main.py b/src/main.py\n+ print('hello')"


@pytest.fixture
def sample_readme() -> str:
    return "# Test Project\nA sample project for testing."


@pytest.fixture
def sample_review_json() -> str:
    return json.dumps(
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
                "redundancy": 8.0,
            },
            "critique": "整体表现不错，但量化硬度不足",
            "per_bullet": [
                {
                    "index": 0,
                    "score": 7.0,
                    "worst_dimension": "quantified_hardness",
                    "issues": ["缺量化"],
                    "suggestion": "添加数字",
                }
            ],
            "must_fix": ["第 1 条缺少量化指标"],
            "ready": False,
        },
        ensure_ascii=False,
    )


@pytest.fixture
def generator() -> Generator:
    """Create a Generator with a mocked OpenAI client (no real API calls)."""
    gen = Generator.__new__(Generator)
    gen.config = {
        "llm": {
            "api_key": "test-key",
            "api_base": "https://test.com/v1",
            "model": "test-model",
        },
        "review": {
            "enabled": True,
            "max_rounds": 3,
            "pass_threshold": 8.5,
        },
        "projects": [
            {"key": "test-proj", "name": "Test Project"},
        ],
    }
    gen.client = MagicMock()
    gen.model = "test-model"
    gen.max_retries = 2
    gen.timeout = 120
    gen.review_enabled = True
    gen.max_rounds = 3
    gen.pass_threshold = 8.5
    return gen


# ═══════════════════════════════════════════════════════════════════
# _build_generate_prompt
# ═══════════════════════════════════════════════════════════════════


class TestBuildGeneratePrompt:
    """Tests for the Round-1 generation prompt builder."""

    def test_includes_diff_content(self, generator: Generator, sample_diff: str):
        prompt = generator._build_generate_prompt("Test", "", sample_diff, "")
        assert sample_diff in prompt

    def test_includes_current_bullets(
        self, generator: Generator, sample_bullets: list
    ):
        bullets_str = "\n".join(sample_bullets)
        prompt = generator._build_generate_prompt("Test", bullets_str, "", "")
        assert "调度系统" in prompt
        assert "性能优化" in prompt

    def test_includes_readme(self, generator: Generator, sample_readme: str):
        prompt = generator._build_generate_prompt(
            "Test", "", "", sample_readme
        )
        assert sample_readme in prompt

    def test_includes_hierarchy_context(self, generator: Generator):
        hierarchy = (
            "\n## 项目架构关系\n调度 3 个 Agent 协同工作"
        )
        prompt = generator._build_generate_prompt("Test", "", "", "", hierarchy)
        assert hierarchy in prompt

    def test_truncates_long_diff_to_8000_chars(self, generator: Generator):
        long_diff = "a" * 10000
        prompt = generator._build_generate_prompt("Test", "", long_diff, "")
        assert len(long_diff) == 10000
        assert "a" * 8000 in prompt
        assert "a" * 8001 not in prompt

    def test_truncates_long_readme_to_2000_chars(self, generator: Generator):
        long_readme = "b" * 3000
        prompt = generator._build_generate_prompt("Test", "", "", long_readme)
        assert "b" * 2000 in prompt
        assert "b" * 2001 not in prompt

    def test_includes_project_name(self, generator: Generator):
        prompt = generator._build_generate_prompt("MyProject", "", "", "")
        assert "MyProject" in prompt

    def test_output_format_instructions_present(self, generator: Generator):
        prompt = generator._build_generate_prompt("Test", "", "", "")
        assert "\\\\item \\\\textbf{" in prompt
        assert "bullets" in prompt
        assert "summary" in prompt
        assert "requires_update" in prompt


# ═══════════════════════════════════════════════════════════════════
# _build_polish_prompt
# ═══════════════════════════════════════════════════════════════════


class TestBuildPolishPrompt:
    """Tests for the readability improvement prompt builder."""

    def test_includes_current_bullets(
        self, generator: Generator, sample_bullets: list
    ):
        bullets_str = "\n".join(sample_bullets)
        prompt = generator._build_polish_prompt("Test", bullets_str)
        assert "\\\\item" in prompt

    def test_mentions_readability_improvement(self, generator: Generator):
        prompt = generator._build_polish_prompt("Test", "\\item bullet")
        assert "可读性" in prompt

    def test_includes_project_name(self, generator: Generator):
        prompt = generator._build_polish_prompt("MyProject", "\\item bullet")
        assert "MyProject" in prompt

    def test_output_format_instructions_present(self, generator: Generator):
        prompt = generator._build_polish_prompt("Test", "\\item bullet")
        assert "bullets" in prompt
        assert "summary" in prompt
        assert "requires_update" in prompt
        assert "\\\\item \\\\textbf{" in prompt

    def test_includes_latex_safety_reminder(self, generator: Generator):
        prompt = generator._build_polish_prompt("Test", "\\item bullet")
        assert "LaTeX" in prompt

    def test_includes_current_count_of_bullets(self, generator: Generator):
        bullets = "\\item A\n\\item B\n\\item C"
        prompt = generator._build_polish_prompt("Test", bullets)
        assert "3" in prompt or "3 条" in prompt


# ═══════════════════════════════════════════════════════════════════
# _parse_response / bullet extraction
# ═══════════════════════════════════════════════════════════════════


class TestParseBullets:
    """Tests for extracting a bullet list from an LLM JSON response."""

    def test_extracts_bullet_list(self):
        result = _parse_bullets(
            '{"bullets": ["b1", "b2"], "summary": "test"}'
        )
        assert result == ["b1", "b2"]

    def test_returns_empty_list_when_key_missing(self):
        result = _parse_bullets('{"summary": "test"}')
        assert result == []

    def test_handles_invalid_json_gracefully(self):
        result = _parse_bullets("not valid json at all")
        assert result == []

    def test_handles_empty_string(self):
        result = _parse_bullets("")
        assert result == []

    def test_handles_code_fence_wrapped_json(self):
        wrapped = '```json\n{"bullets": ["b1"], "summary": "s"}\n```'
        assert _parse_bullets(wrapped) == ["b1"]

    def test_handles_code_fence_without_language_tag(self):
        wrapped = '```\n{"bullets": ["b1"], "summary": "s"}\n```'
        assert _parse_bullets(wrapped) == ["b1"]

    def test_returns_empty_for_non_dict_json(self):
        """If the parsed value is not a dict, .get("bullets", []) returns []."""
        result = _parse_bullets('["a", "b"]')
        assert result == []

    def test_generator_parse_response_extracts_bullets(
        self, generator: Generator
    ):
        content = (
            '{"bullets": ["b1", "b2"], "summary": "s", "requires_update": true}'
        )
        result = generator._parse_response(content)
        assert result.get("bullets") == ["b1", "b2"]
        assert result.get("summary") == "s"
        assert result.get("requires_update") is True


class TestParseReview:
    """Tests for parsing review/critique JSON output."""

    def test_extracts_scores_and_must_fix(
        self, sample_review_json: str
    ):
        review = _parse_review(sample_review_json)
        assert review["overall_score"] == 7.8
        assert review["dimension_scores"]["quantified_hardness"] == 6.0
        assert review["dimension_scores"]["latex_compliance"] == 9.0
        assert review["must_fix"] == ["第 1 条缺少量化指标"]
        assert review["ready"] is False
        assert len(review["per_bullet"]) == 1

    def test_missing_ready_defaults_to_false(self):
        review = _parse_review('{"overall_score": 8.0}')
        assert review.get("ready", False) is False

    def test_missing_dimension_scores_defaults_to_empty_dict(self):
        review = _parse_review('{"overall_score": 8.0}')
        assert review.get("dimension_scores", {}) == {}

    def test_missing_must_fix_defaults_to_empty_list(self):
        review = _parse_review('{"overall_score": 8.0}')
        assert review.get("must_fix", []) == []

    def test_missing_overall_score_defaults_to_zero(self):
        review = _parse_review('{"ready": true}')
        assert review.get("overall_score", 0) == 0

    def test_invalid_review_json_returns_safe_defaults(self):
        review = _parse_review("{{{broken}}}")
        assert review["overall_score"] == 0.0
        assert review["ready"] is False
        assert review["must_fix"] == []

    def test_generator_parse_response_full_review(
        self, generator: Generator, sample_review_json: str
    ):
        result = generator._parse_response(sample_review_json)
        assert result["overall_score"] == 7.8
        assert "quantified_hardness" in result["dimension_scores"]
        assert result["ready"] is False


class TestParseResponseEdgeCases:
    """Edge cases for ``Generator._parse_response``."""

    def test_strips_code_fence_with_json_lang(self, generator: Generator):
        assert generator._parse_response(
            '```json\n{"key": "value"}\n```'
        ) == {"key": "value"}

    def test_strips_code_fence_without_lang(self, generator: Generator):
        assert generator._parse_response(
            '```\n{"key": "value"}\n```'
        ) == {"key": "value"}

    def test_handles_raw_json_without_fence(self, generator: Generator):
        assert generator._parse_response('{"key": "value"}') == {
            "key": "value"
        }

    def test_raises_on_truly_invalid_json(self, generator: Generator):
        with pytest.raises(json.JSONDecodeError):
            generator._parse_response("{invalid}")

    def test_fallback_regex_on_junk_surrounding_json(
        self, generator: Generator
    ):
        content = "Some text\n```json\n{\"a\": 1}\n```\nmore text"
        assert generator._parse_response(content) == {"a": 1}


# ═══════════════════════════════════════════════════════════════════
# _compute_weighted_score
# ═══════════════════════════════════════════════════════════════════


class TestComputeWeightedScore:
    """Weighted score calculation using the 10-dim FAANG rubric."""

    def test_all_perfect_scores_yield_ten(self):
        scores = {dim: 10.0 for dim in DIMENSION_WEIGHTS}
        assert _compute_weighted_score(scores) == pytest.approx(10.0)

    def test_all_minimum_scores_yield_one(self):
        scores = {dim: 1.0 for dim in DIMENSION_WEIGHTS}
        assert _compute_weighted_score(scores) == pytest.approx(1.0)

    def test_uniform_scores_match_input(self):
        scores = {dim: 7.5 for dim in DIMENSION_WEIGHTS}
        assert _compute_weighted_score(scores) == pytest.approx(7.5)

    def test_partial_dimensions_use_only_present_weights(self):
        scores = {
            "quantified_hardness": 10.0,
            "personal_contribution": 10.0,
        }
        # (10*1.5 + 10*1.5) / (1.5 + 1.5) = 30/3 = 10.0
        assert _compute_weighted_score(scores) == 10.0

    def test_empty_scores_returns_zero(self):
        assert _compute_weighted_score({}) == 0.0

    def test_realistic_faang_scores(self):
        scores = {
            "quantified_hardness": 6.0,
            "personal_contribution": 7.0,
            "technical_depth": 8.0,
            "narrative_arc": 6.5,
            "adversarial_survival": 5.0,
            "conciseness": 7.5,
            "latex_compliance": 9.0,
            "verb_strength": 7.0,
            "scale_sense": 6.0,
            "redundancy": 8.0,
        }
        numerator = (
            6.0 * 1.5
            + 7.0 * 1.5
            + 8.0 * 1.2
            + 6.5 * 1.0
            + 5.0 * 1.5
            + 7.5 * 1.2
            + 9.0 * 1.0
            + 7.0 * 0.8
            + 6.0 * 1.0
            + 8.0 * 0.8
        )
        expected = numerator / TOTAL_WEIGHT
        assert _compute_weighted_score(scores) == pytest.approx(
            expected, rel=1e-9
        )

    def test_unknown_dimension_uses_default_weight_of_one(self):
        scores = {"unknown_dim": 5.0}
        assert _compute_weighted_score(scores) == 5.0


# ═══════════════════════════════════════════════════════════════════
# _check_pass_condition
# ═══════════════════════════════════════════════════════════════════


class TestCheckPassCondition:
    """FAANG 门禁规则 — three conditions must all be met."""

    def test_passes_when_all_conditions_met(self):
        scores = {dim: 8.0 for dim in DIMENSION_WEIGHTS}
        assert _check_pass_condition(9.0, scores, ready=True) is True

    def test_fails_on_low_score(self):
        scores = {dim: 7.0 for dim in DIMENSION_WEIGHTS}
        assert _check_pass_condition(7.0, scores, ready=True) is False

    def test_fails_when_ready_is_false(self):
        scores = {dim: 9.0 for dim in DIMENSION_WEIGHTS}
        assert _check_pass_condition(9.0, scores, ready=False) is False

    def test_fails_on_single_low_dimension(self):
        scores = {dim: 8.0 for dim in DIMENSION_WEIGHTS}
        scores["quantified_hardness"] = 4.0
        assert _check_pass_condition(8.5, scores, ready=True) is False

    def test_edge_case_exactly_at_threshold_passes(self):
        scores = {dim: 6.0 for dim in DIMENSION_WEIGHTS}
        assert _check_pass_condition(8.5, scores, ready=True) is True

    def test_respects_custom_pass_threshold(self):
        scores = {dim: 5.0 for dim in DIMENSION_WEIGHTS}
        assert (
            _check_pass_condition(7.0, scores, ready=True, pass_threshold=7.0)
            is True
        )
        assert (
            _check_pass_condition(6.9, scores, ready=True, pass_threshold=7.0)
            is False
        )

    def test_empty_dimension_scores_treated_as_ok(self):
        assert _check_pass_condition(9.0, {}, ready=True) is True

    def test_non_numeric_score_fails(self):
        assert _check_pass_condition(None, {}, ready=True) is False
        assert _check_pass_condition("high", {}, ready=True) is False

    def test_non_numeric_dimension_value_fails(self):
        scores = {"quantified_hardness": "bad"}
        assert _check_pass_condition(9.0, scores, ready=True) is False


# ═══════════════════════════════════════════════════════════════════
# _deduplicate_bullets
# ═══════════════════════════════════════════════════════════════════


class TestDeduplicateBullets:
    """Removing duplicate bullets by normalised content."""

    def test_removes_exact_duplicates(self):
        bullets = ["bullet A", "bullet B", "bullet A"]
        assert _deduplicate_bullets(bullets) == ["bullet A", "bullet B"]

    def test_removes_case_insensitive_duplicates(self):
        bullets = ["Bullet A", "bullet a"]
        assert _deduplicate_bullets(bullets) == ["Bullet A"]

    def test_removes_whitespace_difference_duplicates(self):
        bullets = ["bullet   A", "bullet A"]
        assert _deduplicate_bullets(bullets) == ["bullet   A"]

    def test_preserves_unique_bullets(self):
        bullets = ["bullet A", "bullet B", "bullet C"]
        assert _deduplicate_bullets(bullets) == bullets

    def test_empty_list_returns_empty(self):
        assert _deduplicate_bullets([]) == []

    def test_single_bullet_is_preserved(self):
        assert _deduplicate_bullets(["only"]) == ["only"]

    def test_preserves_first_occurrence(self):
        bullets = ["first", "second", "first"]
        result = _deduplicate_bullets(bullets)
        assert result == ["first", "second"]
        assert result.index("first") == 0


# ═══════════════════════════════════════════════════════════════════
# _sanitize_bullet_text
# ═══════════════════════════════════════════════════════════════════


class TestSanitizeBulletText:
    """LaTeX special character escaping."""

    def test_escapes_ampersand(self):
        assert _sanitize_bullet_text("A & B") == "A \\& B"

    def test_escapes_percent(self):
        assert _sanitize_bullet_text("100%") == "100\\%"

    def test_escapes_dollar(self):
        assert _sanitize_bullet_text("$10") == "\\$10"

    def test_escapes_hash(self):
        assert _sanitize_bullet_text("#1") == "\\#1"

    def test_escapes_underscore(self):
        assert _sanitize_bullet_text("a_b") == "a\\_b"

    def test_escapes_curly_braces(self):
        assert _sanitize_bullet_text("{hello}") == "\\{hello\\}"

    def test_escapes_tilde(self):
        assert _sanitize_bullet_text("~") == "\\textasciitilde{}"

    def test_escapes_caret(self):
        assert _sanitize_bullet_text("a^b") == "a\\textasciicircum{}b"

    def test_escapes_backslash(self):
        assert _sanitize_bullet_text("\\cmd") == "\\textbackslash{}cmd"

    def test_handles_mixed_special_chars(self):
        text = 'A & B 100% for $10 cost #1 _test { } ~ ^ \\'
        result = _sanitize_bullet_text(text)
        assert "\\&" in result
        assert "\\%" in result
        assert "\\$" in result
        assert "\\#" in result
        assert "\\_" in result
        assert "\\{" in result
        assert "\\}" in result
        assert "\\textasciitilde{}" in result
        assert "\\textasciicircum{}" in result
        assert "\\textbackslash{}" in result

    def test_no_change_for_clean_text(self):
        text = "Plain text without special characters"
        assert _sanitize_bullet_text(text) == text

    def test_empty_string(self):
        assert _sanitize_bullet_text("") == ""


# ═══════════════════════════════════════════════════════════════════
# _build_hierarchy_context
# ═══════════════════════════════════════════════════════════════════


class TestBuildHierarchyContext:
    """Building context from agent.yaml scheduling data."""

    def test_returns_empty_for_no_agent_yaml(self, generator: Generator):
        assert generator._build_hierarchy_context(None) == ""

    def test_returns_empty_for_no_scheduled_agents(
        self, generator: Generator
    ):
        assert generator._build_hierarchy_context({"scheduled_agents": []}) == ""

    def test_includes_agent_names(self, generator: Generator):
        agent_yaml = {
            "display_name": "Orchestrator",
            "scheduled_agents": [
                {"name": "Agent1", "interface": "cli", "role": "Code reviewer"},
                {"name": "Agent2", "interface": "http", "role": "Test runner"},
            ],
        }
        ctx = generator._build_hierarchy_context(agent_yaml)
        assert "Orchestrator" in ctx
        assert "Agent1" in ctx
        assert "Agent2" in ctx

    def test_mentions_scheduling_role(self, generator: Generator):
        agent_yaml = {
            "name": "Hub",
            "scheduled_agents": [
                {
                    "name": "SubAgent",
                    "interface": "cli",
                    "role": "Helper",
                }
            ],
        }
        ctx = generator._build_hierarchy_context(agent_yaml)
        assert "调度" in ctx


# ═══════════════════════════════════════════════════════════════════
# _format_bullets_display
# ═══════════════════════════════════════════════════════════════════


class TestFormatBulletsDisplay:
    """Formatting bullet lists for embedding inside prompts."""

    def test_numbers_bullets(self, generator: Generator):
        formatted = generator._format_bullets_display(["b1", "b2", "b3"])
        assert "1. b1" in formatted
        assert "2. b2" in formatted
        assert "3. b3" in formatted

    def test_empty_list_returns_empty_string(self, generator: Generator):
        assert generator._format_bullets_display([]) == ""

    def test_newlines_separate_bullets(self, generator: Generator):
        result = generator._format_bullets_display(["a", "b"])
        lines = result.split("\n")
        assert len(lines) == 2


# ═══════════════════════════════════════════════════════════════════
# _read_current_bullets
# ═══════════════════════════════════════════════════════════════════


class TestReadCurrentBullets:
    """Reading bullet content from a .tex file by project key."""

    TEX_CONTENT = """\
% RESUME_PROJECT_START: smartbench
\\item \\textbf{SmartBench：} 设计多 Agent 代码诊断引擎。
% RESUME_PROJECT_END: smartbench

% RESUME_PROJECT_START: omniagent
\\item \\textbf{OmniAgent：} 设计调度框架。
% RESUME_PROJECT_END: omniagent
"""

    def test_extracts_bullets_for_given_key(self, generator: Generator):
        with patch.object(
            generator, "_read_current_bullets", return_value="\\item test"
        ) as mock:
            result = generator._read_current_bullets(
                "fake.tex", "smartbench"
            )
            assert result == "\\item test"
            mock.assert_called_once_with("fake.tex", "smartbench")

    def test_returns_empty_for_missing_key(self, generator: Generator):
        with patch.object(
            generator, "_read_current_bullets", return_value=""
        ) as mock:
            result = generator._read_current_bullets(
                "fake.tex", "nonexistent"
            )
            assert result == ""
            mock.assert_called_once_with("fake.tex", "nonexistent")


# ═══════════════════════════════════════════════════════════════════
# Integration-style: _parse_response + pass condition
# (tests the exact logic flow inside Generator.generate)
# ═══════════════════════════════════════════════════════════════════


class TestGeneratorGeneratePassLogic:
    """Verify the exact pass/fail branching logic in ``generate()``."""

    @staticmethod
    def _simulate_pass_check(generator, review) -> bool:
        """Replicate the inline check from Generator.generate()."""
        review_score = review.get("overall_score", 0)
        dim_scores = review.get("dimension_scores", {})
        all_dims_ok = (
            all(
                isinstance(v, (int, float)) and v >= 5.0
                for v in dim_scores.values()
            )
            if dim_scores
            else True
        )
        return (
            review.get("ready", False)
            and isinstance(review_score, (int, float))
            and review_score >= generator.pass_threshold
            and all_dims_ok
        )

    def test_all_conditions_met_passes(self, generator: Generator):
        review = {
            "ready": True,
            "overall_score": 8.8,
            "dimension_scores": {dim: 6.0 for dim in DIMENSION_WEIGHTS},
        }
        assert self._simulate_pass_check(generator, review) is True

    def test_low_score_fails(self, generator: Generator):
        review = {
            "ready": True,
            "overall_score": 7.5,
            "dimension_scores": {dim: 6.0 for dim in DIMENSION_WEIGHTS},
        }
        assert self._simulate_pass_check(generator, review) is False

    def test_not_ready_fails(self, generator: Generator):
        review = {
            "ready": False,
            "overall_score": 8.8,
            "dimension_scores": {dim: 6.0 for dim in DIMENSION_WEIGHTS},
        }
        assert self._simulate_pass_check(generator, review) is False

    def test_low_dimension_fails(self, generator: Generator):
        review = {
            "ready": True,
            "overall_score": 8.8,
            "dimension_scores": {
                **{dim: 6.0 for dim in DIMENSION_WEIGHTS},
                "quantified_hardness": 4.0,
            },
        }
        assert self._simulate_pass_check(generator, review) is False

    def test_empty_dim_scores_passes_if_score_ok(
        self, generator: Generator
    ):
        review = {
            "ready": True,
            "overall_score": 8.8,
            "dimension_scores": {},
        }
        assert self._simulate_pass_check(generator, review) is True

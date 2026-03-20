"""
LLM-based GPT judge for humanities tutor transcripts.

Scores a conversation transcript against a rubric using LangGraph + OpenAI.
Called by the UI; not intended to run standalone.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import NotRequired, TypedDict

from utils.parsing import extract_json_object

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_JUDGE_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _JUDGE_ROOT.parent
PROMPTS_DIR = _JUDGE_ROOT / "prompts"
TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

# Load repo-level .env once so OPENAI_API_KEY is available across entrypoints.
load_dotenv(_REPO_ROOT / ".env")

# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------


def _require_openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set."
        )
    return key


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"})


def _openai_reasoning_config() -> dict[str, Any]:
    """
    Build optional OpenAI reasoning configuration for judge calls.

    Default is medium reasoning effort for GPT judge runs. Set
    JUDGE_OPENAI_REASONING_EFFORT to "off"/"none" to disable.
    """
    effort = os.environ.get("JUDGE_OPENAI_REASONING_EFFORT", "medium").strip().lower()
    if effort in {"", "off", "none", "false", "0"}:
        return {}
    if effort not in {"low", "medium", "high"}:
        raise RuntimeError(
            "JUDGE_OPENAI_REASONING_EFFORT must be one of: low, medium, high, off."
        )
    return {"reasoning": {"effort": effort}}


# ---------------------------------------------------------------------------
# Rubric constants
# ---------------------------------------------------------------------------


class JudgeError(RuntimeError):
    pass


_CRITERIA_MAX: dict[str, int] = {
    "1.1": 12, "1.2": 6, "1.3": 5,
    "2.1": 4, "2.2": 6,
    "3.1": 6, "3.2": 5, "3.3": 3,
}

_CRITERIA_NAME: dict[str, str] = {
    "1.1": "Socratic method and guided discovery",
    "1.2": "Scaffolding and progression",
    "1.3": "Meta-learning and methodology feedback",
    "2.1": "Redundancy and spiraling",
    "2.2": "Assignment anchoring",
    "3.1": "Bite-sized and clear responses",
    "3.2": "Appropriate tone and support",
    "3.3": "Formatting and medium",
}

_SECTION_KEYS: tuple[str, ...] = (
    "1_pedagogy",
    "2_dialogue_quality",
    "3_communication_quality",
)

_SECTION_CRITERIA: dict[str, tuple[str, ...]] = {
    "1_pedagogy": ("1.1", "1.2", "1.3"),
    "2_dialogue_quality": ("2.1", "2.2"),
    "3_communication_quality": ("3.1", "3.2", "3.3"),
}

_SECTION_MALUS_ID: dict[str, str] = {
    "1_pedagogy": "1.4",
    "2_dialogue_quality": "2.3",
    "3_communication_quality": "3.4",
}

_MAX_BASE_SCORE = sum(_CRITERIA_MAX.values())  # 47
_MAX_MALUS_PER_SECTION = 2
_MAX_MALUS_SCORE = len(_SECTION_KEYS) * _MAX_MALUS_PER_SECTION  # 6
_MAX_TOTAL_SCORE = _MAX_BASE_SCORE  # 47


# ---------------------------------------------------------------------------
# JSON parsing & validation helpers
# ---------------------------------------------------------------------------


def _parse_json_from_model_output(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        raise JudgeError("Model output JSON was not an object.")
    except json.JSONDecodeError:
        pass

    obj = extract_json_object(raw)
    if obj is None:
        raise JudgeError("Could not find a JSON object in model output.")
    try:
        data = json.loads(obj)
    except json.JSONDecodeError as e:
        raise JudgeError(f"Model output contained invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise JudgeError("Model output JSON was not an object.")
    return data


def _as_number(x: Any, *, path: str) -> float:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    raise JudgeError(f"Expected number at {path}, got {type(x).__name__}.")


def _as_int(x: Any, *, path: str) -> int:
    if isinstance(x, bool):
        raise JudgeError(f"Expected integer at {path}, got bool.")
    if isinstance(x, int):
        return x
    if isinstance(x, float) and math.isfinite(x) and x.is_integer():
        return int(x)
    raise JudgeError(f"Expected integer at {path}, got {type(x).__name__}.")


def _as_str(x: Any, *, path: str) -> str:
    if isinstance(x, str):
        return x
    raise JudgeError(f"Expected string at {path}, got {type(x).__name__}.")


def _as_dict(x: Any, *, path: str) -> dict[str, Any]:
    if isinstance(x, dict):
        return x
    raise JudgeError(f"Expected object at {path}, got {type(x).__name__}.")


def _as_list(x: Any, *, path: str) -> list[Any]:
    if isinstance(x, list):
        return x
    raise JudgeError(f"Expected array at {path}, got {type(x).__name__}.")


def _close_enough(a: float, b: float, *, eps: float = 1e-6) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= eps


def _coerce_number(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        v = float(x)
        return v if math.isfinite(v) else None
    return None


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


# ---------------------------------------------------------------------------
# Sanitization & validation
# ---------------------------------------------------------------------------


def _sanitize_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Best-effort fix-up for common LLM numeric mistakes.

    Recomputes criterion scores from deductions, recomputes section and global
    totals, and overwrites declared maxima to constants.
    """
    sections_any = payload.get("sections")
    if not isinstance(sections_any, dict):
        return payload

    computed_total_base = 0
    computed_total_malus = 0

    for section_key in _SECTION_KEYS:
        sec_any = sections_any.get(section_key)
        if not isinstance(sec_any, dict):
            continue

        base_any = sec_any.get("base")
        malus_any = sec_any.get("malus")
        crit_any = sec_any.get("criteria")
        if not isinstance(base_any, dict) or not isinstance(malus_any, dict) or not isinstance(crit_any, dict):
            continue

        expected_base_max = sum(_CRITERIA_MAX[c] for c in _SECTION_CRITERIA[section_key])
        base_any["max"] = expected_base_max

        expected_malus_id = _SECTION_MALUS_ID[section_key]
        malus_any["id"] = expected_malus_id
        malus_any["max"] = _MAX_MALUS_PER_SECTION
        explanation_any = malus_any.get("explanation")
        malus_any["explanation"] = str(explanation_any).strip() if isinstance(explanation_any, str) else ""
        malus_score = _coerce_number(malus_any.get("score"))
        if malus_score is None or not float(malus_score).is_integer():
            malus_any["score"] = 0
        else:
            malus_any["score"] = int(
                _clamp(float(malus_score), 0.0, _MAX_MALUS_PER_SECTION)
            )

        computed_section_base = 0
        for crit_id in _SECTION_CRITERIA[section_key]:
            c_any = crit_any.get(crit_id)
            if not isinstance(c_any, dict):
                continue
            c_any["name"] = _CRITERIA_NAME[crit_id]
            crit_max = _CRITERIA_MAX[crit_id]
            c_any["max"] = crit_max

            deductions_any = c_any.get("deductions")
            deductions_list = deductions_any if isinstance(deductions_any, list) else []
            c_any["deductions"] = deductions_list

            deduction_total = 0
            for d_any in deductions_list:
                if not isinstance(d_any, dict):
                    continue
                pts = _coerce_number(d_any.get("points"))
                if pts is None or pts <= 0 or not float(pts).is_integer():
                    continue
                deduction_total += int(pts)

            c_any["score"] = _clamp(crit_max - deduction_total, 0.0, crit_max)
            c_any["score"] = int(c_any["score"])
            computed_section_base += int(c_any["score"])

        base_any["score"] = computed_section_base
        computed_total_base += int(base_any["score"])
        computed_total_malus += int(malus_any["score"])

    payload["max_base_score"] = _MAX_BASE_SCORE
    payload["max_malus"] = _MAX_MALUS_SCORE
    payload["max_score"] = _MAX_TOTAL_SCORE
    payload["total_base_score"] = computed_total_base
    payload["total_malus"] = computed_total_malus
    payload["total_score"] = int(_clamp(computed_total_base - computed_total_malus, 0.0, _MAX_TOTAL_SCORE))
    if "overview" not in payload and isinstance(payload.get("justifications"), list):
        payload["overview"] = payload.get("justifications")
    payload["sections"] = sections_any
    return payload


def _order_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Rebuild grade payload with deterministic key ordering.

    Top-level order:
      sections, totals/maxima, remaining keys, overview, total_score, judge_llm_calls.
    Per-section order:
      criteria (with deductions-first criterion shape), then base/malus totals.
    """
    ordered: dict[str, Any] = {}

    sections_any = payload.get("sections")
    if isinstance(sections_any, dict):
        ordered_sections: dict[str, Any] = {}
        for section_key in _SECTION_KEYS:
            sec_any = sections_any.get(section_key)
            if not isinstance(sec_any, dict):
                continue

            section_out: dict[str, Any] = {}
            crit_any = sec_any.get("criteria")
            if isinstance(crit_any, dict):
                criteria_out: dict[str, Any] = {}
                for crit_id in _SECTION_CRITERIA[section_key]:
                    c_any = crit_any.get(crit_id)
                    if not isinstance(c_any, dict):
                        continue

                    c_out: dict[str, Any] = {}
                    deductions_any = c_any.get("deductions", [])
                    deductions_out: list[Any] = []
                    if isinstance(deductions_any, list):
                        for d_any in deductions_any:
                            if not isinstance(d_any, dict):
                                deductions_out.append(d_any)
                                continue
                            d_out: dict[str, Any] = {}
                            if "evidence_turns" in d_any:
                                d_out["evidence_turns"] = d_any.get("evidence_turns")
                            d_out["reason"] = d_any.get("reason")
                            d_out["points"] = d_any.get("points")
                            for dk, dv in d_any.items():
                                if dk not in d_out:
                                    d_out[dk] = dv
                            deductions_out.append(d_out)
                    c_out["deductions"] = deductions_out
                    c_out["score"] = c_any.get("score")
                    c_out["max"] = c_any.get("max")
                    c_out["name"] = c_any.get("name")
                    for k, v in c_any.items():
                        if k not in c_out:
                            c_out[k] = v
                    criteria_out[crit_id] = c_out
                section_out["criteria"] = criteria_out

            section_out["base"] = sec_any.get("base")
            section_out["malus"] = sec_any.get("malus")
            for k, v in sec_any.items():
                if k not in section_out:
                    section_out[k] = v
            ordered_sections[section_key] = section_out
        ordered["sections"] = ordered_sections
    else:
        ordered["sections"] = sections_any

    ordered["max_score"] = payload.get("max_score")
    ordered["total_base_score"] = payload.get("total_base_score")
    ordered["max_base_score"] = payload.get("max_base_score")
    ordered["total_malus"] = payload.get("total_malus")
    ordered["max_malus"] = payload.get("max_malus")

    for k, v in payload.items():
        if k not in ordered and k not in {"overview", "justifications", "total_score", "judge_llm_calls"}:
            ordered[k] = v
    overview = payload.get("overview", payload.get("justifications", []))
    ordered["overview"] = overview
    ordered["total_score"] = payload.get("total_score")
    ordered["judge_llm_calls"] = payload.get("judge_llm_calls")
    return ordered


def _validate_grade_payload(payload: dict[str, Any], *, num_turns: int) -> dict[str, Any]:
    total_score = _as_int(payload.get("total_score"), path="total_score")
    max_score = _as_int(payload.get("max_score"), path="max_score")
    total_base_score = _as_int(payload.get("total_base_score"), path="total_base_score")
    max_base_score = _as_int(payload.get("max_base_score"), path="max_base_score")
    total_malus = _as_int(payload.get("total_malus"), path="total_malus")
    max_malus = _as_int(payload.get("max_malus"), path="max_malus")
    sections = _as_dict(payload.get("sections"), path="sections")
    overview = _as_list(payload.get("overview", []), path="overview")
    for i, item in enumerate(overview):
        _as_str(item, path=f"overview[{i}]")

    if max_base_score != _MAX_BASE_SCORE:
        raise JudgeError(f"max_base_score must be {_MAX_BASE_SCORE}, got {max_base_score}.")
    if max_malus != _MAX_MALUS_SCORE:
        raise JudgeError(f"max_malus must be {_MAX_MALUS_SCORE}, got {max_malus}.")
    if max_score != _MAX_TOTAL_SCORE:
        raise JudgeError(f"max_score must be {_MAX_TOTAL_SCORE}, got {max_score}.")
    if total_base_score < 0 or total_base_score > max_base_score:
        raise JudgeError("total_base_score out of range.")
    if total_malus < 0 or total_malus > max_malus:
        raise JudgeError("total_malus out of range.")
    if total_score < 0 or total_score > max_score:
        raise JudgeError("total_score out of range.")
    if total_score != int(_clamp(total_base_score - total_malus, 0.0, max_score)):
        raise JudgeError("total_score must equal clamp(total_base_score - total_malus, 0, max_score).")

    for expected_section in _SECTION_KEYS:
        if expected_section not in sections:
            raise JudgeError(f"Missing sections.{expected_section}.")

    computed_total_base = 0
    computed_total_malus = 0

    for section_key in _SECTION_KEYS:
        section = _as_dict(sections.get(section_key), path=f"sections.{section_key}")
        base = _as_dict(section.get("base"), path=f"sections.{section_key}.base")
        malus = _as_dict(section.get("malus"), path=f"sections.{section_key}.malus")
        criteria = _as_dict(section.get("criteria"), path=f"sections.{section_key}.criteria")

        base_score = _as_int(base.get("score"), path=f"sections.{section_key}.base.score")
        base_max = _as_int(base.get("max"), path=f"sections.{section_key}.base.max")
        malus_score = _as_int(malus.get("score"), path=f"sections.{section_key}.malus.score")
        malus_max = _as_int(malus.get("max"), path=f"sections.{section_key}.malus.max")
        malus_id = _as_str(malus.get("id"), path=f"sections.{section_key}.malus.id")
        _as_str(malus.get("explanation"), path=f"sections.{section_key}.malus.explanation")
        expected_malus_id = _SECTION_MALUS_ID.get(section_key)
        if malus_id != expected_malus_id:
            raise JudgeError(
                f"sections.{section_key}.malus.id must be {expected_malus_id!r}, got {malus_id!r}."
            )

        expected_base_max = sum(_CRITERIA_MAX[c] for c in _SECTION_CRITERIA[section_key])
        if base_max != expected_base_max:
            raise JudgeError(
                f"sections.{section_key}.base.max must be {expected_base_max}, got {base_max}."
            )
        if malus_max != _MAX_MALUS_PER_SECTION:
            raise JudgeError(
                f"sections.{section_key}.malus.max must be {_MAX_MALUS_PER_SECTION}, got {malus_max}."
            )
        if base_score < 0 or base_score > base_max:
            raise JudgeError(f"sections.{section_key}.base.score out of range.")
        if malus_score < 0 or malus_score > malus_max:
            raise JudgeError(f"sections.{section_key}.malus.score out of range.")

        computed_section_base = 0
        for crit_id in _SECTION_CRITERIA[section_key]:
            crit = _as_dict(criteria.get(crit_id), path=f"sections.{section_key}.criteria.{crit_id}")
            crit_score = _as_int(crit.get("score"), path=f"sections.{section_key}.criteria.{crit_id}.score")
            crit_max = _as_int(crit.get("max"), path=f"sections.{section_key}.criteria.{crit_id}.max")
            _as_str(crit.get("name"), path=f"sections.{section_key}.criteria.{crit_id}.name")

            expected_crit_max = _CRITERIA_MAX[crit_id]
            if crit_max != expected_crit_max:
                raise JudgeError(
                    f"sections.{section_key}.criteria.{crit_id}.max must be {expected_crit_max}, got {crit_max}."
                )
            if crit_score < 0 or crit_score > crit_max:
                raise JudgeError(f"sections.{section_key}.criteria.{crit_id}.score out of range.")

            deductions = _as_list(
                crit.get("deductions", []), path=f"sections.{section_key}.criteria.{crit_id}.deductions"
            )
            deduction_total = 0
            for i, d in enumerate(deductions):
                dd = _as_dict(d, path=f"sections.{section_key}.criteria.{crit_id}.deductions[{i}]")
                _as_str(dd.get("reason"), path=f"...deductions[{i}].reason")
                pts = _as_int(dd.get("points"), path=f"...deductions[{i}].points")
                if pts <= 0:
                    raise JudgeError("Deduction points must be > 0.")
                deduction_total += pts
                ev = dd.get("evidence_turns")
                if ev is not None:
                    turns = _as_list(ev, path=f"...deductions[{i}].evidence_turns")
                    for t in turns:
                        n = _as_number(t, path=f"...deductions[{i}].evidence_turns[]")
                        if not float(n).is_integer():
                            raise JudgeError("Evidence turn numbers must be integers.")
                        ti = int(n)
                        if ti < 1 or ti > num_turns:
                            raise JudgeError("Evidence turn number out of range.")

            expected_crit_score = int(_clamp(crit_max - deduction_total, 0.0, crit_max))
            if crit_score != expected_crit_score:
                raise JudgeError(
                    f"sections.{section_key}.criteria.{crit_id}.score must equal max - sum(deductions.points)."
                )
            computed_section_base += crit_score

        if base_score != computed_section_base:
            raise JudgeError(f"sections.{section_key}.base.score must equal sum of criteria scores.")

        computed_total_base += base_score
        computed_total_malus += malus_score

    if total_base_score != computed_total_base:
        raise JudgeError("total_base_score must equal sum of section base scores.")
    if total_malus != computed_total_malus:
        raise JudgeError("total_malus must equal sum of section malus scores.")

    return payload


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def _build_expected_schema() -> dict[str, Any]:
    """Build the example JSON schema shown to the judge in the prompt."""
    sections: dict[str, Any] = {}
    for section_key in _SECTION_KEYS:
        criteria: dict[str, Any] = {}
        for crit_id in _SECTION_CRITERIA[section_key]:
            criteria[crit_id] = {
                "deductions": [
                    {"evidence_turns": [1], "reason": "Short reason", "points": 1},
                ],
                "score": 0,
                "max": _CRITERIA_MAX[crit_id],
                "name": _CRITERIA_NAME[crit_id],
            }
        sections[section_key] = {
            "criteria": criteria,
            "base": {"score": 0, "max": sum(_CRITERIA_MAX[c] for c in _SECTION_CRITERIA[section_key])},
            "malus": {
                "id": _SECTION_MALUS_ID[section_key],
                "explanation": "Short reason for catch-all deduction score.",
                "score": 0,
                "max": _MAX_MALUS_PER_SECTION,
            },
        }
    return {
        "total_score": 0,
        "max_score": _MAX_TOTAL_SCORE,
        "total_base_score": 0,
        "max_base_score": _MAX_BASE_SCORE,
        "total_malus": 0,
        "max_malus": _MAX_MALUS_SCORE,
        "sections": sections,
        "overview": ["Brief overall rationale."],
        "judge_llm_calls": 1,
    }


def load_judge_prompt(
    prompt_name: str = "judge_03",
    rubric_name: str = "rubric_04",
) -> str:
    """
    Load the judge system prompt from ``judge/prompts/<prompt_name>.txt``,
    injecting the rubric and expected JSON schema.
    """
    prompt_path = PROMPTS_DIR / f"{prompt_name}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Judge prompt not found: {prompt_path}")

    rubric_path = _JUDGE_ROOT / "rubrics" / f"{rubric_name}.md"
    if not rubric_path.exists():
        raise FileNotFoundError(f"Rubric not found: {rubric_path}")

    template = prompt_path.read_text(encoding="utf-8")
    rubric_text = rubric_path.read_text(encoding="utf-8").strip()
    schema_text = json.dumps(_build_expected_schema(), indent=2)

    return template.format(rubric=rubric_text, schema=schema_text).strip()


def _judge_repair_prompt(error: str) -> str:
    return (
        "Your previous JSON did not validate against the required schema / consistency rules.\n"
        f"Validation error: {error}\n\n"
        "Return a corrected JSON ONLY that fixes the error while keeping your original grading intent.\n"
        "Do NOT add any extra keys. Ensure all totals and maxima are correct and consistent.\n"
    )


# ---------------------------------------------------------------------------
# Conversation formatting
# ---------------------------------------------------------------------------


def _format_conversation_for_judge(transcript: dict[str, Any]) -> str:
    context = transcript.get("context", "")
    exercise = transcript.get("exercise", "")
    exchanges = transcript.get("exchanges", [])
    lines: list[str] = []
    lines.append("Assignment input:")
    if str(context).strip():
        lines.append("Context:")
        lines.append(str(context).strip())
        lines.append("")
    lines.append("Exercise:")
    lines.append(str(exercise).strip())
    lines.append("")
    lines.append("Conversation transcript (student+tutor exchanges):")
    for ex in exchanges:
        turn = ex.get("turn")
        student = ex.get("student", "")
        tutor = ex.get("tutor", "")
        lines.append(f"Turn {turn} — Student: {student}")
        lines.append(f"Turn {turn} — Tutor: {tutor}")
        lines.append("")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------------


class _JudgeState(TypedDict):
    attempts: int
    system_prompt: str
    conversation_text: str
    num_turns: int
    last_output: NotRequired[str]
    last_error: NotRequired[str]
    grade_json: NotRequired[dict[str, Any]]


def _create_judge_graph(*, model_name: str, api_key: str):
    model_kwargs = _openai_reasoning_config()
    model = ChatOpenAI(
        model=model_name,
        temperature=0,
        api_key=api_key,
        model_kwargs=model_kwargs,
    )

    def judge_node(state: _JudgeState) -> dict[str, Any]:
        messages = [SystemMessage(content=state["system_prompt"])]
        if state.get("last_error") and state.get("last_output"):
            messages.append(
                HumanMessage(
                    content=_judge_repair_prompt(state["last_error"])
                    + "\n\nPrevious JSON (to repair):\n"
                    + state["last_output"]
                )
            )
        messages.append(HumanMessage(content=state["conversation_text"]))
        resp = model.invoke(messages)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return {"last_output": content, "attempts": int(state.get("attempts", 0)) + 1}

    def validate_node(state: _JudgeState) -> dict[str, Any]:
        out = state.get("last_output", "")
        try:
            parsed = _parse_json_from_model_output(out)
            parsed = _sanitize_grade_payload(parsed)
            validated = _validate_grade_payload(parsed, num_turns=int(state["num_turns"]))
            ordered = _order_grade_payload(validated)
            return {"grade_json": ordered, "last_error": None}
        except JudgeError as e:
            return {"last_error": str(e), "grade_json": None}

    graph = StateGraph(_JudgeState)
    graph.add_node("judge", judge_node)
    graph.add_node("validate", validate_node)
    graph.add_edge(START, "judge")
    graph.add_edge("judge", "validate")

    def _route(state: _JudgeState) -> str:
        if state.get("grade_json") is not None:
            return END
        if int(state.get("attempts", 0)) >= 2:
            return END
        return "judge"

    graph.add_conditional_edges("validate", _route, {"judge": "judge", END: END})
    return graph.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeResult:
    total_score: int
    max_score: int


def judge_transcript(
    transcript_name: str,
    *,
    prompt_name: str = "judge_03",
    rubric_name: str = "rubric_04",
) -> JudgeResult:
    """
    Score one transcript by relative path (without .json) under transcripts/.

    Examples: ``"chaotic/transcript_01"`` or ``"transcript_01"``.

    Side effect: updates the transcript JSON in-place by adding a top-level
    ``grade`` object.
    """
    name = (transcript_name or "").strip()
    if not name:
        raise JudgeError("transcript_name is required (path without .json).")

    transcript_path = TRANSCRIPTS_DIR / f"{name}.json"
    if not transcript_path.exists():
        raise JudgeError(f"Transcript not found: {transcript_path}")

    try:
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise JudgeError(f"Transcript is not valid JSON: {e}") from e
    if not isinstance(transcript, dict):
        raise JudgeError("Transcript JSON must be an object.")
    if "grade" in transcript:
        raise JudgeError("Transcript already contains a top-level 'grade' key; refusing to overwrite.")

    exchanges = transcript.get("exchanges")
    if not isinstance(exchanges, list) or not exchanges:
        raise JudgeError("Transcript must contain a non-empty 'exchanges' array.")

    api_key = _require_openai_api_key()
    model_name = os.environ.get("OPENAI_MODEL", "gpt-5.2")

    system_prompt = load_judge_prompt(prompt_name=prompt_name, rubric_name=rubric_name)
    conversation_text = _format_conversation_for_judge(transcript)

    graph = _create_judge_graph(model_name=model_name, api_key=api_key)
    result = graph.invoke(
        {
            "attempts": 0,
            "system_prompt": system_prompt,
            "conversation_text": conversation_text,
            "num_turns": len(exchanges),
        }
    )
    grade_json = result.get("grade_json")
    if grade_json is None:
        raise JudgeError(f"Judge failed to produce valid grade JSON. Last error: {result.get('last_error')}")

    grade_payload = dict(grade_json)
    grade_payload["model"] = {"provider": "openai", "model": model_name, "temperature": 0}
    grade_payload["judge_llm_calls"] = int(result.get("attempts", 0))
    # Keep grade artifacts deterministic by default; timestamp is opt-in.
    if _env_truthy("JUDGE_INCLUDE_TIMESTAMP"):
        grade_payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    grade_payload = _order_grade_payload(grade_payload)

    transcript["grade"] = grade_payload
    transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return JudgeResult(
        total_score=int(grade_payload["total_score"]),
        max_score=int(grade_payload["max_score"]),
    )


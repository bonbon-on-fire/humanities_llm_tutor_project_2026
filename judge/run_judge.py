from __future__ import annotations

import json
import math
import os
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

warnings.filterwarnings(
    "ignore",
    message=r"Core Pydantic V1 functionality isn't compatible with Python 3\.14 or greater\.",
    category=UserWarning,
)

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import NotRequired, TypedDict


class JudgeError(RuntimeError):
    pass


_CRITERIA_MAX: dict[str, float] = {
    "1.1": 5,
    "1.2": 3,
    "1.3": 3,
    "2.1": 5,
    "2.2": 3,
    "2.3": 3,
    "3.1": 5,
    "3.2": 3,
    "3.3": 3,
    "4.1": 5,
    "4.2": 3,
    "4.3": 3,
    "5.1": 5,
    "5.2": 3,
    "5.3": 3,
}

_SECTION_KEYS: tuple[str, ...] = (
    "1_pedagogy",
    "2_role_and_boundaries",
    "3_dialogue_quality",
    "4_feedback_and_evaluation",
    "5_communication_quality",
)

_SECTION_CRITERIA: dict[str, tuple[str, ...]] = {
    "1_pedagogy": ("1.1", "1.2", "1.3"),
    "2_role_and_boundaries": ("2.1", "2.2", "2.3"),
    "3_dialogue_quality": ("3.1", "3.2", "3.3"),
    "4_feedback_and_evaluation": ("4.1", "4.2", "4.3"),
    "5_communication_quality": ("5.1", "5.2", "5.3"),
}

_MAX_BASE_SCORE = float(sum(_CRITERIA_MAX.values()))  # 55
_MAX_BONUS_PER_SECTION = 3.0
_MAX_BONUS_SCORE = float(len(_SECTION_KEYS) * _MAX_BONUS_PER_SECTION)  # 15
_MAX_TOTAL_SCORE = _MAX_BASE_SCORE + _MAX_BONUS_SCORE  # 70


def _judge_root() -> Path:
    return Path(__file__).resolve().parent


def _repo_root() -> Path:
    return _judge_root().parent


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, c in enumerate(text[start:], start=start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_json_from_model_output(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        raise JudgeError("Model output JSON was not an object.")
    except json.JSONDecodeError:
        pass

    obj = _extract_json_object(raw)
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


def _validate_grade_payload(payload: dict[str, Any], *, num_turns: int) -> dict[str, Any]:
    total_score = _as_number(payload.get("total_score"), path="total_score")
    max_score = _as_number(payload.get("max_score"), path="max_score")
    total_base_score = _as_number(payload.get("total_base_score"), path="total_base_score")
    max_base_score = _as_number(payload.get("max_base_score"), path="max_base_score")
    total_bonus = _as_number(payload.get("total_bonus"), path="total_bonus")
    max_bonus = _as_number(payload.get("max_bonus"), path="max_bonus")
    sections = _as_dict(payload.get("sections"), path="sections")

    if not _close_enough(max_base_score, _MAX_BASE_SCORE):
        raise JudgeError(f"max_base_score must be {_MAX_BASE_SCORE}, got {max_base_score}.")
    if not _close_enough(max_bonus, _MAX_BONUS_SCORE):
        raise JudgeError(f"max_bonus must be {_MAX_BONUS_SCORE}, got {max_bonus}.")
    if not _close_enough(max_score, _MAX_TOTAL_SCORE):
        raise JudgeError(f"max_score must be {_MAX_TOTAL_SCORE}, got {max_score}.")

    if total_base_score < 0 or total_base_score > max_base_score:
        raise JudgeError("total_base_score out of range.")
    if total_bonus < 0 or total_bonus > max_bonus:
        raise JudgeError("total_bonus out of range.")
    if total_score < 0 or total_score > max_score:
        raise JudgeError("total_score out of range.")
    if not _close_enough(total_score, total_base_score + total_bonus):
        raise JudgeError("total_score must equal total_base_score + total_bonus.")

    for expected_section in _SECTION_KEYS:
        if expected_section not in sections:
            raise JudgeError(f"Missing sections.{expected_section}.")

    computed_total_base = 0.0
    computed_total_bonus = 0.0

    for section_key in _SECTION_KEYS:
        section = _as_dict(sections.get(section_key), path=f"sections.{section_key}")
        base = _as_dict(section.get("base"), path=f"sections.{section_key}.base")
        bonus = _as_dict(section.get("bonus"), path=f"sections.{section_key}.bonus")
        criteria = _as_dict(section.get("criteria"), path=f"sections.{section_key}.criteria")

        base_score = _as_number(base.get("score"), path=f"sections.{section_key}.base.score")
        base_max = _as_number(base.get("max"), path=f"sections.{section_key}.base.max")
        bonus_score = _as_number(bonus.get("score"), path=f"sections.{section_key}.bonus.score")
        bonus_max = _as_number(bonus.get("max"), path=f"sections.{section_key}.bonus.max")

        expected_base_max = float(sum(_CRITERIA_MAX[c] for c in _SECTION_CRITERIA[section_key]))
        if not _close_enough(base_max, expected_base_max):
            raise JudgeError(
                f"sections.{section_key}.base.max must be {expected_base_max}, got {base_max}."
            )
        if not _close_enough(bonus_max, _MAX_BONUS_PER_SECTION):
            raise JudgeError(
                f"sections.{section_key}.bonus.max must be {_MAX_BONUS_PER_SECTION}, got {bonus_max}."
            )
        if base_score < 0 or base_score > base_max:
            raise JudgeError(f"sections.{section_key}.base.score out of range.")
        if bonus_score < 0 or bonus_score > bonus_max:
            raise JudgeError(f"sections.{section_key}.bonus.score out of range.")

        computed_section_base = 0.0
        for crit_id in _SECTION_CRITERIA[section_key]:
            crit = _as_dict(criteria.get(crit_id), path=f"sections.{section_key}.criteria.{crit_id}")
            crit_score = _as_number(crit.get("score"), path=f"sections.{section_key}.criteria.{crit_id}.score")
            crit_max = _as_number(crit.get("max"), path=f"sections.{section_key}.criteria.{crit_id}.max")
            _as_str(crit.get("name"), path=f"sections.{section_key}.criteria.{crit_id}.name")

            expected_crit_max = float(_CRITERIA_MAX[crit_id])
            if not _close_enough(crit_max, expected_crit_max):
                raise JudgeError(
                    f"sections.{section_key}.criteria.{crit_id}.max must be {expected_crit_max}, got {crit_max}."
                )
            if crit_score < 0 or crit_score > crit_max:
                raise JudgeError(f"sections.{section_key}.criteria.{crit_id}.score out of range.")

            deductions = _as_list(
                crit.get("deductions", []), path=f"sections.{section_key}.criteria.{crit_id}.deductions"
            )
            for i, d in enumerate(deductions):
                dd = _as_dict(d, path=f"sections.{section_key}.criteria.{crit_id}.deductions[{i}]")
                pts = _as_number(dd.get("points"), path=f"...deductions[{i}].points")
                if pts <= 0:
                    raise JudgeError("Deduction points must be > 0.")
                _as_str(dd.get("reason"), path=f"...deductions[{i}].reason")
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

            computed_section_base += crit_score

        if not _close_enough(base_score, computed_section_base):
            raise JudgeError(f"sections.{section_key}.base.score must equal sum of criteria scores.")

        computed_total_base += base_score
        computed_total_bonus += bonus_score

    if not _close_enough(total_base_score, computed_total_base):
        raise JudgeError("total_base_score must equal sum of section base scores.")
    if not _close_enough(total_bonus, computed_total_bonus):
        raise JudgeError("total_bonus must equal sum of section bonus scores.")

    return payload


def _format_conversation_for_judge(transcript: dict[str, Any]) -> str:
    exercise = transcript.get("exercise", "")
    exchanges = transcript.get("exchanges", [])
    lines: list[str] = []
    lines.append("Exercise / assignment context:")
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


def _judge_system_prompt(rubric_text: str) -> str:
    expected_schema = {
        "total_score": 0,
        "max_score": _MAX_TOTAL_SCORE,
        "total_base_score": 0,
        "max_base_score": _MAX_BASE_SCORE,
        "total_bonus": 0,
        "max_bonus": _MAX_BONUS_SCORE,
        "sections": {
            "1_pedagogy": {
                "base": {"score": 0, "max": 11},
                "bonus": {"score": 0, "max": 3},
                "criteria": {
                    "1.1": {
                        "name": "Socratic method and guided discovery",
                        "score": 0,
                        "max": 5,
                        "deductions": [
                            {
                                "points": 1,
                                "reason": "Short reason",
                                "evidence_turns": [1],
                            }
                        ],
                    }
                },
            }
        },
    }

    return (
        "You are a strict, rubric-following grader (judge) for a full conversation between a tutor and a student.\n"
        "You will be given:\n"
        "- The assignment context\n"
        "- The full conversation transcript\n"
        "- The grading rubric\n\n"
        "Rubric (authoritative):\n"
        f"{rubric_text.strip()}\n\n"
        "Scoring rules:\n"
        "- Start each sub-criterion at full points and subtract deductions according to the rubric.\n"
        "- Do NOT add points except via the per-section bonus (0..3, can be fractional).\n"
        "- Scores can be fractional. Keep them within allowed ranges.\n"
        "- Provide deductions with concise reasons, and include evidence_turns (turn numbers) when applicable.\n"
        "- Ensure all totals are internally consistent: section base score equals sum of its criteria scores; "
        "total_base_score equals sum of section base scores; total_bonus equals sum of section bonus scores; "
        "total_score equals total_base_score + total_bonus.\n"
        f"- Use these exact maxima: max_base_score={_MAX_BASE_SCORE}, max_bonus={_MAX_BONUS_SCORE}, "
        f"max_score={_MAX_TOTAL_SCORE}, bonus per section max={_MAX_BONUS_PER_SECTION}.\n"
        "- Output MUST be valid JSON ONLY (no markdown, no commentary).\n"
        "- Output MUST match this schema shape (example values only):\n"
        f"{json.dumps(expected_schema, indent=2)}\n"
    )


def _judge_repair_prompt(error: str) -> str:
    return (
        "Your previous JSON did not validate against the required schema / consistency rules.\n"
        f"Validation error: {error}\n\n"
        "Return a corrected JSON ONLY that fixes the error while keeping your original grading intent.\n"
        "Do NOT add any extra keys. Ensure all totals and maxima are correct and consistent.\n"
    )


class _JudgeState(TypedDict):
    attempts: int
    rubric_text: str
    conversation_text: str
    num_turns: int
    last_output: NotRequired[str]
    last_error: NotRequired[str]
    grade_json: NotRequired[dict[str, Any]]


def _create_judge_graph(*, model_name: str, api_key: str):
    model = ChatOpenAI(model=model_name, temperature=0, api_key=api_key)

    def judge_node(state: _JudgeState) -> dict[str, Any]:
        sys_prompt = _judge_system_prompt(state["rubric_text"])
        messages = [SystemMessage(content=sys_prompt)]
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
            validated = _validate_grade_payload(parsed, num_turns=int(state["num_turns"]))
            return {"grade_json": validated, "last_error": None}
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
        attempts = int(state.get("attempts", 0))
        if attempts >= 2:
            return END
        return "judge"

    graph.add_conditional_edges("validate", _route, {"judge": "judge", END: END})
    return graph.compile()


@dataclass(frozen=True)
class JudgeResult:
    total_score: float
    max_score: float


def judge_transcript(transcript_name: str) -> JudgeResult:
    """
    Score one transcript by stem name (filename without .json) under judge/transcripts/.
    Hard-fails on any validation or IO issue.

    Side effect: updates the transcript JSON in-place by adding a top-level `grade` object.
    """
    name = (transcript_name or "").strip()
    if not name:
        raise JudgeError("transcript_name is required (filename without .json).")

    transcript_path = _repo_root() / "judge" / "transcripts" / f"{name}.json"
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

    rubric_path = _repo_root() / "judge" / "judge_rubric.md"
    if not rubric_path.exists():
        raise JudgeError(f"Rubric not found: {rubric_path}")
    rubric_text = rubric_path.read_text(encoding="utf-8")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise JudgeError("Missing OPENAI_API_KEY (required for judge).")
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o")

    conversation_text = _format_conversation_for_judge(transcript)

    graph = _create_judge_graph(model_name=model_name, api_key=api_key)
    result = graph.invoke(
        {
            "attempts": 0,
            "rubric_text": rubric_text,
            "conversation_text": conversation_text,
            "num_turns": len(exchanges),
        }
    )
    grade_json = result.get("grade_json")
    if grade_json is None:
        raise JudgeError(f"Judge failed to produce valid grade JSON. Last error: {result.get('last_error')}")

    grade_payload = dict(grade_json)
    grade_payload["model"] = {"provider": "openai", "model": model_name, "temperature": 0}
    grade_payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()

    transcript["grade"] = grade_payload
    transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return JudgeResult(
        total_score=float(grade_payload["total_score"]),
        max_score=float(grade_payload["max_score"]),
    )


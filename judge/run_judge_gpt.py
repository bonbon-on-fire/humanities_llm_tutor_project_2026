"""GPT-based judge for humanities tutor transcripts."""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import NotRequired, TypedDict

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from utils.parsing import extract_json_object

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
RUBRICS_DIR = Path(__file__).resolve().parent / "rubrics"
TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

_DEFAULT_OPENAI_MODEL = "gpt-5.4"
_MAX_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Structured JSONL debug logging
# ---------------------------------------------------------------------------
_LOG_PATH = _REPO_ROOT / "logs" / "judge_gpt_debug.jsonl"


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", ""),
            "transcript_name": getattr(record, "transcript_name", ""),
        }
        for key, value in record.__dict__.items():
            if key.startswith("_log_"):
                field_name = key[5:]
                if isinstance(value, str) and len(value) > 50_000:
                    value = value[:50_000]
                    payload[field_name + "_truncated"] = True
                payload[field_name] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def _setup_debug_logger() -> logging.Logger:
    logger = logging.getLogger("judge_gpt_debug")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_LOG_PATH, mode="a", encoding="utf-8")
    handler.setFormatter(_JsonLogFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


_debug_log = _setup_debug_logger()


def _log_event(event: str, transcript_name: str = "", level: int = logging.INFO, **fields: Any) -> None:
    extra = {"event": event, "transcript_name": transcript_name}
    for key, value in fields.items():
        extra[f"_log_{key}"] = value
    _debug_log.log(level, "", extra=extra)


def _sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Rubric specifications
# ---------------------------------------------------------------------------

_RUBRIC_SPECS: dict[str, dict[str, Any]] = {
    "rubric_04": {
        "max_base_score": 47,
        "max_score": 47,
        "criterion_max": {
            "1.1": 12, "1.2": 6, "1.3": 5,
            "2.1": 4, "2.2": 6,
            "3.1": 6, "3.2": 5, "3.3": 3,
        },
        "criterion_names": {
            "1.1": "Socratic method and guided discovery",
            "1.2": "Scaffolding and progression",
            "1.3": "Meta-learning and methodology feedback",
            "2.1": "Redundancy and spiraling",
            "2.2": "Assignment anchoring",
            "3.1": "Bite-sized and clear responses",
            "3.2": "Appropriate tone and support",
            "3.3": "Formatting and medium",
        },
        "sections": {
            "1_pedagogy": {"criteria": ["1.1", "1.2", "1.3"]},
            "2_dialogue_quality": {"criteria": ["2.1", "2.2"]},
            "3_communication_quality": {"criteria": ["3.1", "3.2", "3.3"]},
        },
    },
    "rubric_05": {
        "max_base_score": 46,
        "max_score": 46,
        "criterion_max": {
            "1.1": 12, "1.2": 6, "1.3": 6,
            "2.1": 4, "2.2": 8,
            "3.1": 6, "3.2": 4,
        },
        "criterion_names": {
            "1.1": "Socratic method and guided discovery",
            "1.2": "Scaffolding and progression",
            "1.3": "Meta-learning and methodology feedback",
            "2.1": "Redundancy and spiraling",
            "2.2": "Assignment anchoring",
            "3.1": "Bite-sized and clear responses",
            "3.2": "Appropriate tone and support",
        },
        "sections": {
            "1_pedagogy": {"criteria": ["1.1", "1.2", "1.3"]},
            "2_dialogue_quality": {"criteria": ["2.1", "2.2"]},
            "3_communication_quality": {"criteria": ["3.1", "3.2"]},
        },
    },
    "rubric_06": {
        "max_base_score": 46,
        "max_score": 46,
        "criterion_max": {
            "1.1": 12, "1.2": 6, "1.3": 6,
            "2.1": 4, "2.2": 8,
            "3.1": 6, "3.2": 4,
        },
        "criterion_names": {
            "1.1": "Socratic method and guided discovery",
            "1.2": "Scaffolding and progression",
            "1.3": "Meta-learning and methodology feedback",
            "2.1": "Redundancy and spiraling",
            "2.2": "Assignment anchoring",
            "3.1": "Bite-sized and clear responses",
            "3.2": "Appropriate tone and support",
        },
        "sections": {
            "1_pedagogy": {"criteria": ["1.1", "1.2", "1.3"]},
            "2_dialogue_quality": {"criteria": ["2.1", "2.2"]},
            "3_communication_quality": {"criteria": ["3.1", "3.2"]},
        },
    },
}


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class JudgeError(RuntimeError):
    """Raised when transcript judging fails."""


@dataclass(slots=True)
class JudgeResult:
    total_score: int
    max_score: int
    output_path: Path


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------

class _JudgeState(TypedDict):
    attempts: int
    system_prompt: str
    conversation_text: str
    num_turns: int
    transcript_name: str
    last_output: NotRequired[str]
    last_error: NotRequired[str]
    grade_json: NotRequired[dict[str, Any]]


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

def _coerce_int(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return int(round(float(text))) if "." in text else int(text)
        except ValueError:
            return default
    return default


def _sanitize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _normalize_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_json_value(v) for v in value]
    return str(value)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _require_openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
    if not key:
        raise JudgeError("OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set.")
    return key


# ---------------------------------------------------------------------------
# JSON extraction from model output
# ---------------------------------------------------------------------------

def _fenced_json(text: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    return match.group(1).strip() if match else None


def _extract_text_from_model_content(content: Any) -> str:
    """Extract text from model response, skipping OpenAI ReasoningBlocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            item_type = getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)
            if item_type == "reasoning":
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
                    continue
            text_attr = getattr(item, "text", None)
            if isinstance(text_attr, str):
                chunks.append(text_attr)
                continue
            chunks.append(str(item))
        return "\n".join(chunks)
    return str(content)


def _parse_json_from_model_output(output_text: str) -> dict[str, Any]:
    text = _sanitize_text(output_text).strip()
    candidates = [text, _fenced_json(text), extract_json_object(text)]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return _normalize_json_value(parsed)
        except json.JSONDecodeError:
            continue

    extracted = extract_json_object(text)
    if extracted:
        try:
            literal = ast.literal_eval(extracted)
            literal = _normalize_json_value(literal)
            if isinstance(literal, dict):
                return literal
        except (SyntaxError, ValueError):
            pass

    raise JudgeError("Judge response does not contain a valid JSON object.")


# ---------------------------------------------------------------------------
# Grade payload validation and normalization
# ---------------------------------------------------------------------------

def _normalize_deduction(item: Any, *, enforce_sub_criterion_ids: bool) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {}
    evidence_raw = item.get("evidence_turns")
    evidence: list[int] = []
    if isinstance(evidence_raw, list):
        for v in evidence_raw:
            n = _coerce_int(v, default=0)
            if n > 0:
                evidence.append(n)
    elif evidence_raw is not None:
        n = _coerce_int(evidence_raw, default=0)
        if n > 0:
            evidence.append(n)

    sub_criterion_id = _sanitize_text(item.get("sub_criterion_id")).strip()
    if enforce_sub_criterion_ids and not sub_criterion_id:
        sub_criterion_id = "missing"

    deduction: dict[str, Any] = {}
    if evidence:
        deduction["evidence_turns"] = evidence
    if sub_criterion_id:
        deduction["sub_criterion_id"] = sub_criterion_id
    deduction["reason"] = _sanitize_text(item.get("reason")).strip()
    deduction["points"] = max(0, _coerce_int(item.get("points"), default=0))
    return deduction


def _sanitize_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_json_value(payload)
    if not isinstance(payload, dict):
        raise JudgeError("Grade payload must be a JSON object.")
    if "sections" not in payload or not isinstance(payload.get("sections"), dict):
        payload["sections"] = {}
    if "overview" not in payload:
        summary = payload.get("summary")
        payload["overview"] = summary if isinstance(summary, list) else []
    if not isinstance(payload.get("overview"), list):
        payload["overview"] = [str(payload["overview"])]
    payload["overview"] = [_sanitize_text(v) for v in payload["overview"]]
    return payload


def _rubric_spec(rubric_name: str) -> dict[str, Any]:
    key = rubric_name.strip().lower()
    if key not in _RUBRIC_SPECS:
        available = ", ".join(sorted(_RUBRIC_SPECS.keys()))
        raise JudgeError(f"Unsupported rubric '{rubric_name}'. Available: {available}")
    return _RUBRIC_SPECS[key]


def _validate_grade_payload(
    payload: dict[str, Any],
    *,
    num_turns: int,
    enforce_sub_criterion_ids: bool,
    rubric_name: str,
) -> dict[str, Any]:
    del num_turns
    spec = _rubric_spec(rubric_name)
    sections_in = payload.get("sections")
    if not isinstance(sections_in, dict):
        raise JudgeError("Grade payload must include an object at 'sections'.")

    normalized_sections: dict[str, Any] = {}
    criterion_max = spec["criterion_max"]
    criterion_names = spec["criterion_names"]

    for section_id, section_spec in spec["sections"].items():
        section_in = sections_in.get(section_id)
        if not isinstance(section_in, dict):
            section_in = {}
        criteria_in = section_in.get("criteria")
        if not isinstance(criteria_in, dict):
            criteria_in = {}

        section_criteria: dict[str, Any] = {}
        section_score = 0
        section_max = 0

        for criterion_id in section_spec["criteria"]:
            criterion_in = criteria_in.get(criterion_id)
            if not isinstance(criterion_in, dict):
                criterion_in = {}
            deductions_in = criterion_in.get("deductions")
            if not isinstance(deductions_in, list):
                deductions_in = []

            max_points = int(criterion_max[criterion_id])
            deductions = [
                _normalize_deduction(d, enforce_sub_criterion_ids=enforce_sub_criterion_ids)
                for d in deductions_in
            ]
            deducted = sum(_coerce_int(d.get("points"), default=0) for d in deductions)
            score = max(0, min(max_points, max_points - deducted))

            section_criteria[criterion_id] = {
                "deductions": deductions,
                "score": score,
                "max": max_points,
                "name": criterion_names.get(criterion_id, criterion_id),
            }
            section_score += score
            section_max += max_points

        normalized_sections[section_id] = {
            "criteria": section_criteria,
            "base": {"score": section_score, "max": section_max},
        }

    total_base_score = sum(int(s["base"]["score"]) for s in normalized_sections.values())

    out: dict[str, Any] = {
        "sections": normalized_sections,
        "max_score": int(spec["max_score"]),
        "total_base_score": total_base_score,
        "max_base_score": int(spec["max_base_score"]),
    }
    out["total_score"] = total_base_score
    out["overview"] = payload.get("overview", [])
    if not isinstance(out["overview"], list):
        out["overview"] = [str(out["overview"])]
    out["overview"] = [_sanitize_text(v) for v in out["overview"]]
    out["judge_llm_calls"] = _coerce_int(payload.get("judge_llm_calls"), default=1)
    return out


def _order_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {"sections": payload["sections"]}
    for key in ("max_score", "total_base_score", "max_base_score"):
        if key in payload:
            ordered[key] = payload[key]
    for key in ("id", "summary", "type", "model", "timestamp_utc"):
        if key in payload:
            ordered[key] = payload[key]
    ordered["overview"] = payload.get("overview", [])
    ordered["total_score"] = payload["total_score"]
    ordered["judge_llm_calls"] = payload.get("judge_llm_calls", 1)
    return ordered


def _extract_deduction_summary(payload: dict[str, Any]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        return summary
    for section in sections.values():
        if not isinstance(section, dict):
            continue
        criteria = section.get("criteria")
        if not isinstance(criteria, dict):
            continue
        for cid, criterion in criteria.items():
            if not isinstance(criterion, dict):
                continue
            deductions = criterion.get("deductions", [])
            if not isinstance(deductions, list):
                deductions = []
            total_pts = sum(
                max(0, int(d.get("points", 0))) for d in deductions if isinstance(d, dict)
            )
            summary[str(cid)] = {"count": len(deductions), "total_points": total_pts}
    return summary


# ---------------------------------------------------------------------------
# Schema and prompt loading
# ---------------------------------------------------------------------------

def _grade_schema_for_prompt(rubric_name: str) -> dict[str, Any]:
    spec = _rubric_spec(rubric_name)
    sections: dict[str, Any] = {}
    for section_id, section_spec in spec["sections"].items():
        criteria: dict[str, Any] = {}
        for criterion_id in section_spec["criteria"]:
            criteria[criterion_id] = {
                "deductions": [
                    {
                        "evidence_turns": [1, 2],
                        "sub_criterion_id": f"{criterion_id}.A.a",
                        "reason": "Short evidence-based deduction reason.",
                        "points": 1,
                    }
                ],
                "score": spec["criterion_max"][criterion_id],
                "max": spec["criterion_max"][criterion_id],
                "name": spec["criterion_names"][criterion_id],
            }
        sections[section_id] = {
            "criteria": criteria,
            "base": {
                "score": sum(spec["criterion_max"][c] for c in section_spec["criteria"]),
                "max": sum(spec["criterion_max"][c] for c in section_spec["criteria"]),
            },
        }

    payload: dict[str, Any] = {
        "sections": sections,
        "max_score": spec["max_score"],
        "total_base_score": spec["max_base_score"],
        "max_base_score": spec["max_base_score"],
    }
    payload["overview"] = ["Brief evidence-based overview."]
    payload["total_score"] = spec["max_score"]
    payload["judge_llm_calls"] = 1
    return payload


def load_judge_prompt(*, prompt_name: str = "judge_05", rubric_name: str = "rubric_05") -> str:
    prompt_path = PROMPTS_DIR / f"{prompt_name}.txt"
    rubric_path = RUBRICS_DIR / f"{rubric_name}.md"
    if not prompt_path.exists():
        available = sorted(p.stem for p in PROMPTS_DIR.glob("*.txt"))
        raise JudgeError(f"Judge prompt '{prompt_name}' not found. Available: {available}")
    if not rubric_path.exists():
        available = sorted(p.stem for p in RUBRICS_DIR.glob("*.md"))
        raise JudgeError(f"Judge rubric '{rubric_name}' not found. Available: {available}")

    prompt_template = prompt_path.read_text(encoding="utf-8")
    rubric_text = rubric_path.read_text(encoding="utf-8")
    schema_text = json.dumps(_grade_schema_for_prompt(rubric_name), ensure_ascii=False, indent=2)
    return prompt_template.format(rubric=rubric_text.strip(), schema=schema_text).strip()


# ---------------------------------------------------------------------------
# Conversation formatting
# ---------------------------------------------------------------------------

def _format_conversation_for_judge(transcript: dict[str, Any]) -> str:
    lines: list[str] = []
    context = _sanitize_text(transcript.get("context")).strip()
    exercise = _sanitize_text(transcript.get("exercise")).strip()
    if context:
        lines.append("CONTEXT:")
        lines.append(context)
        lines.append("")
    if exercise:
        lines.append("EXERCISE:")
        lines.append(exercise)
        lines.append("")

    lines.append("TRANSCRIPT:")
    exchanges = transcript.get("exchanges")
    if not isinstance(exchanges, list):
        exchanges = []
    for i, exchange in enumerate(exchanges, start=1):
        if not isinstance(exchange, dict):
            continue
        turn = _coerce_int(exchange.get("turn"), default=i)
        student = _sanitize_text(exchange.get("student")).strip()
        tutor = _sanitize_text(exchange.get("tutor")).strip()
        lines.append(f"Turn {turn}")
        lines.append(f"Student: {student}")
        lines.append(f"Tutor: {tutor}")
        lines.append("")

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# LangGraph judge pipeline
# ---------------------------------------------------------------------------

def _judge_repair_prompt(last_error: str) -> str:
    return (
        "Your previous response could not be validated as the required grade JSON.\n"
        f"Validation error: {last_error}\n"
        "Return ONLY corrected JSON that matches the expected schema exactly."
    )


def _build_openai_model(*, model_name: str, api_key: str):
    effort = os.environ.get("JUDGE_OPENAI_REASONING_EFFORT", "medium").strip().lower()
    if effort in {"low", "medium", "high", "off"}:
        try:
            return ChatOpenAI(
                model=model_name,
                api_key=api_key,
                model_kwargs={"reasoning": {"effort": effort}},
            )
        except TypeError:
            pass
    return ChatOpenAI(model=model_name, api_key=api_key)


def _create_judge_graph(*, model_name: str, api_key: str, enforce_sub_criterion_ids: bool, rubric_name: str):
    model = _build_openai_model(model_name=model_name, api_key=api_key)

    def judge_node(state: _JudgeState) -> dict[str, Any]:
        tname = state.get("transcript_name", "")
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
        attempt = int(state.get("attempts", 0)) + 1

        _log_event("judge_node_input", tname,
                   attempt=attempt,
                   num_messages=len(messages),
                   message_roles=[m.type for m in messages],
                   human_message_length=len(messages[-1].content),
                   human_message_hash=_sha256_short(messages[-1].content),
                   has_repair_prompt=bool(state.get("last_error")))

        resp = model.invoke(messages)
        content = _extract_text_from_model_content(resp.content)

        resp_meta = getattr(resp, "response_metadata", {}) or {}
        _log_event("judge_node_output", tname,
                   attempt=attempt,
                   raw_content_type=type(resp.content).__name__,
                   raw_content_length=len(str(resp.content)),
                   extracted_text_length=len(content),
                   extracted_text_hash=_sha256_short(content),
                   extracted_text_first_500=content[:500],
                   extracted_text_last_500=content[-500:],
                   has_deductions_in_raw=bool(re.search(r'"deductions"\s*:\s*\[(?!\s*\])', content)),
                   deduction_count_estimate=content.count('"points"'),
                   response_model=resp_meta.get("model_name", ""),
                   usage_tokens=resp_meta.get("token_usage", {}))

        return {"last_output": content, "attempts": attempt}

    def validate_node(state: _JudgeState) -> dict[str, Any]:
        tname = state.get("transcript_name", "")
        try:
            parsed = _parse_json_from_model_output(state.get("last_output", ""))

            _log_event("json_parsed", tname,
                       parsed_keys=list(parsed.keys()),
                       has_sections="sections" in parsed,
                       section_ids=list(parsed.get("sections", {}).keys()) if isinstance(parsed.get("sections"), dict) else [],
                       deductions_summary=_extract_deduction_summary(parsed))

            parsed = _sanitize_grade_payload(parsed)

            _log_event("payload_sanitized", tname,
                       deductions_per_criterion=_extract_deduction_summary(parsed),
                       overview_length=len(parsed.get("overview", [])))

            validated = _validate_grade_payload(
                parsed,
                num_turns=int(state["num_turns"]),
                enforce_sub_criterion_ids=enforce_sub_criterion_ids,
                rubric_name=rubric_name,
            )

            scores_per_criterion: dict[str, dict[str, int]] = {}
            for section in validated.get("sections", {}).values():
                if isinstance(section, dict):
                    for cid, crit in section.get("criteria", {}).items():
                        if isinstance(crit, dict):
                            scores_per_criterion[str(cid)] = {
                                "score": crit.get("score", 0),
                                "max": crit.get("max", 0),
                            }
            _log_event("payload_validated", tname,
                       total_score=validated.get("total_score"),
                       max_score=validated.get("max_score"),
                       scores_per_criterion=scores_per_criterion,
                       deductions_per_criterion=_extract_deduction_summary(validated),
                       overview_items=len(validated.get("overview", [])))

            return {"grade_json": _order_grade_payload(validated), "last_error": None}
        except JudgeError as e:
            _log_event("validation_error", tname, level=logging.WARNING,
                       error_message=str(e),
                       attempt=state.get("attempts", 0),
                       raw_output_first_500=str(state.get("last_output", ""))[:500])
            return {"grade_json": None, "last_error": str(e)}

    graph = StateGraph(_JudgeState)
    graph.add_node("judge", judge_node)
    graph.add_node("validate", validate_node)
    graph.add_edge(START, "judge")
    graph.add_edge("judge", "validate")

    def route(state: _JudgeState) -> str:
        if state.get("grade_json") is not None:
            return END
        return END if int(state.get("attempts", 0)) >= _MAX_ATTEMPTS else "judge"

    graph.add_conditional_edges("validate", route, {"judge": "judge", END: END})
    return graph.compile()


# ---------------------------------------------------------------------------
# Public API — single-transcript judging
# ---------------------------------------------------------------------------

def judge_transcript(
    transcript_name: str,
    *,
    prompt_name: str = "judge_05",
    rubric_name: str = "rubric_05",
    output_name: str | None = None,
) -> JudgeResult:
    """Grade a single transcript and write the result to disk.

    Parameters
    ----------
    transcript_name:
        Relative path (without ``.json``) under ``transcripts/``,
        e.g. ``"chaotic/chaotic_gpt/transcript_01"``.
    prompt_name:
        Judge prompt stem from ``judge/prompts/``.
    rubric_name:
        Rubric stem from ``judge/rubrics/``.
    output_name:
        If provided, the output file is written as ``<output_name>.json``
        in the same directory as the source transcript.  Otherwise a
        default name is generated.
    """
    name = transcript_name.strip()
    source_path = (TRANSCRIPTS_DIR / f"{name}.json").resolve()

    if not source_path.exists():
        raise JudgeError(f"Transcript not found: {source_path}")

    try:
        transcript = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise JudgeError(f"Transcript is not valid JSON: {e}") from e
    if not isinstance(transcript, dict):
        raise JudgeError("Transcript JSON must be an object.")

    exchanges = transcript.get("exchanges")
    if not isinstance(exchanges, list) or not exchanges:
        raise JudgeError("Transcript must contain a non-empty 'exchanges' array.")

    _log_event("transcript_loaded", name,
               source_path=str(source_path),
               num_exchanges=len(exchanges),
               exchange_lengths=[len(json.dumps(e)) for e in exchanges],
               context_length=len(str(transcript.get("context", ""))),
               exercise_length=len(str(transcript.get("exercise", ""))),
               student_persona=str(transcript.get("student_persona", "")))

    normalized_rubric = rubric_name.strip().lower()
    model_name = os.environ.get("OPENAI_MODEL", _DEFAULT_OPENAI_MODEL)
    graph = _create_judge_graph(
        model_name=model_name,
        api_key=_require_openai_api_key(),
        enforce_sub_criterion_ids=normalized_rubric in {"rubric_04", "rubric_05", "rubric_06"},
        rubric_name=normalized_rubric,
    )
    system_prompt = load_judge_prompt(prompt_name=prompt_name, rubric_name=rubric_name)
    conversation_text = _format_conversation_for_judge(transcript)

    _log_event("system_prompt_loaded", name,
               prompt_name=prompt_name, rubric_name=rubric_name,
               system_prompt_length=len(system_prompt),
               system_prompt_hash=_sha256_short(system_prompt))

    _log_event("conversation_formatted", name,
               conversation_text_length=len(conversation_text),
               conversation_text_hash=_sha256_short(conversation_text),
               conversation_text_first_200=conversation_text[:200],
               conversation_text_last_200=conversation_text[-200:],
               num_turns_in_text=conversation_text.count("Turn "))

    result = graph.invoke(
        {
            "attempts": 0,
            "system_prompt": system_prompt,
            "conversation_text": conversation_text,
            "num_turns": len(exchanges),
            "transcript_name": name,
        }
    )
    grade_json = result.get("grade_json")
    if grade_json is None:
        raise JudgeError(f"Judge failed to produce valid grade JSON. Last error: {result.get('last_error')}")

    grade_payload = dict(grade_json)
    grade_payload["model"] = {"provider": "openai", "model": model_name}
    grade_payload["judge_llm_calls"] = int(result.get("attempts", 0))
    if _env_truthy("JUDGE_INCLUDE_TIMESTAMP"):
        grade_payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    grade_payload = _order_grade_payload(grade_payload)

    out_transcript = dict(transcript)
    out_transcript.pop("grade", None)
    out_transcript["grade"] = grade_payload

    output_path = (
        _default_output_path(transcript_path=source_path, prompt_name=prompt_name, rubric_name=rubric_name, provider="gpt")
        if output_name is None
        else source_path.with_name(f"{output_name}.json")
    )
    output_path.write_text(json.dumps(out_transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    all_deductions_empty = all(
        len(crit.get("deductions", [])) == 0
        for sect in grade_payload.get("sections", {}).values()
        if isinstance(sect, dict)
        for crit in sect.get("criteria", {}).values()
        if isinstance(crit, dict)
    )
    _log_event("judge_complete", name,
               total_score=int(grade_payload["total_score"]),
               max_score=int(grade_payload["max_score"]),
               judge_llm_calls=int(grade_payload.get("judge_llm_calls", 0)),
               output_path=str(output_path),
               all_deductions_empty=all_deductions_empty,
               overview_empty=len(grade_payload.get("overview", [])) == 0)

    return JudgeResult(
        total_score=int(grade_payload["total_score"]),
        max_score=int(grade_payload["max_score"]),
        output_path=Path(output_path),
    )


def _default_output_path(*, transcript_path: Path, prompt_name: str, rubric_name: str, provider: str) -> Path:
    stem = transcript_path.stem
    filename = f"{stem}__{prompt_name}__{rubric_name}__{provider}.json"
    return transcript_path.with_name(filename)

"""Unified single-transcript judge (GPT + Claude)."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import NotRequired, TypedDict

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env")

Provider = Literal["gpt", "claude"]

TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"
PROMPTS_DIR = _REPO_ROOT / "judge" / "prompts"
RUBRICS_DIR = _REPO_ROOT / "judge" / "rubrics"

DEFAULT_JUDGE_PROMPT = "judge_05"
DEFAULT_RUBRIC = "rubric_05"
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
DEFAULT_REASONING = "medium"
MAX_ATTEMPTS = 3


class JudgeError(RuntimeError):
    """Raised when judging fails."""


@dataclass(slots=True)
class JudgeResult:
    total_score: int
    max_score: int
    output_path: Path


class JudgeState(TypedDict):
    attempts: int
    system_prompt: str
    conversation_text: str
    num_turns: int
    last_output: NotRequired[str]
    last_error: NotRequired[str]
    grade_json: NotRequired[dict[str, Any]]


def _coerce_int(value: Any, default: int = 0) -> int:
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
            return int(round(float(text)))
        except ValueError:
            return default
    return default


def _sanitize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _require_openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
    if not key:
        raise JudgeError("OPENAI_API_KEY environment variable is required but not set.")
    return key


def _require_anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise JudgeError("ANTHROPIC_API_KEY environment variable is required but not set.")
    return key


def _extract_text_from_model_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text is not None:
                    parts.append(_sanitize_text(text))
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        if "text" in content:
            return _sanitize_text(content["text"])
    return _sanitize_text(content)


def _extract_json_object(text: str) -> str:
    # fenced code block first
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    # first JSON object span
    start = text.find("{")
    if start == -1:
        raise JudgeError("No JSON object found in model output.")
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise JudgeError("Unclosed JSON object in model output.")


def _parse_json_from_model_output(raw: str) -> dict[str, Any]:
    obj_text = _extract_json_object(raw)
    try:
        parsed = json.loads(obj_text)
    except json.JSONDecodeError as e:
        raise JudgeError(f"Invalid JSON from model: {e}") from e
    if not isinstance(parsed, dict):
        raise JudgeError(f"Expected JSON object, got {type(parsed).__name__}")
    return parsed


def _build_expected_schema(rubric_name: str) -> str:
    max_score = 46 if rubric_name in {"rubric_05", "rubric_06"} else 47
    sample = {
        "sections": {
            "1_pedagogy": {"base": {"score": 22, "max": 24}},
            "2_dialogue_quality": {"base": {"score": 10, "max": 12}},
            "3_communication_quality": {"base": {"score": 10, "max": 10}},
        },
        "total_base_score": 42,
        "max_base_score": max_score,
        "overview": "Concise rubric-based summary.",
        "total_score": 42,
        "max_score": max_score,
        "judge_llm_calls": 1,
    }
    return json.dumps(sample, ensure_ascii=False, indent=2)


def load_judge_prompt(*, prompt_name: str = DEFAULT_JUDGE_PROMPT, rubric_name: str = DEFAULT_RUBRIC) -> str:
    prompt_path = PROMPTS_DIR / f"{prompt_name}.txt"
    rubric_path = RUBRICS_DIR / f"{rubric_name}.md"
    if not prompt_path.exists():
        raise JudgeError(f"Judge prompt not found: {prompt_path}")
    if not rubric_path.exists():
        raise JudgeError(f"Rubric not found: {rubric_path}")
    prompt_template = prompt_path.read_text(encoding="utf-8")
    rubric_text = rubric_path.read_text(encoding="utf-8")
    schema_text = _build_expected_schema(rubric_name.strip().lower())
    return prompt_template.replace("{rubric}", rubric_text).replace("{schema}", schema_text)


def _format_conversation_for_judge(transcript: dict[str, Any]) -> str:
    lines: list[str] = []
    context = _sanitize_text(transcript.get("context")).strip()
    exercise = _sanitize_text(transcript.get("exercise")).strip()
    if context:
        lines.append("Context:")
        lines.append(context)
        lines.append("")
    if exercise:
        lines.append("Exercise:")
        lines.append(exercise)
        lines.append("")
    lines.append("Conversation:")
    exchanges = transcript.get("exchanges", [])
    if not isinstance(exchanges, list):
        return "\n".join(lines)
    for idx, ex in enumerate(exchanges, start=1):
        if not isinstance(ex, dict):
            continue
        student = _sanitize_text(ex.get("student")).strip()
        tutor = _sanitize_text(ex.get("tutor")).strip()
        lines.append(f"Turn {idx}")
        lines.append(f"Student: {student}")
        lines.append(f"Tutor: {tutor}")
    return "\n".join(lines)


def _sanitize_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    total_base = _coerce_int(payload.get("total_base_score"))
    max_base = _coerce_int(payload.get("max_base_score"), 46)
    total = _coerce_int(payload.get("total_score"), total_base)
    max_score = _coerce_int(payload.get("max_score"), max_base)
    out = dict(payload)
    out["total_base_score"] = total_base
    out["max_base_score"] = max_base
    out["total_score"] = total
    out["max_score"] = max_score
    out.setdefault("overview", "")
    out.setdefault("sections", {})
    return out


def _validate_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("total_base_score", "max_base_score", "total_score", "max_score"):
        if key not in payload:
            raise JudgeError(f"Missing required key: {key}")
        if not isinstance(payload[key], int):
            raise JudgeError(f"{key} must be integer, got {type(payload[key]).__name__}")
    if payload["total_score"] < 0 or payload["total_score"] > payload["max_score"]:
        raise JudgeError("total_score out of range")
    if payload["total_base_score"] < 0 or payload["total_base_score"] > payload["max_base_score"]:
        raise JudgeError("total_base_score out of range")
    return payload


def _order_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    for key in (
        "sections",
        "total_base_score",
        "max_base_score",
        "overview",
        "total_score",
        "max_score",
        "model",
        "judge_llm_calls",
        "timestamp_utc",
    ):
        if key in payload:
            ordered[key] = payload[key]
    for k, v in payload.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def _judge_repair_prompt(error: str) -> str:
    return (
        "Your previous output was invalid.\n"
        f"Validation error: {error}\n"
        "Return ONLY valid JSON object, no markdown.\n"
        "Required integer keys: total_score, max_score, total_base_score, max_base_score."
    )


def _create_model_invoke(provider: Provider, model_name: str, api_key: str, reasoning: str) -> Callable[[list[Any]], Any]:
    if provider == "gpt":
        kwargs: dict[str, Any] = {"model": model_name, "temperature": 0, "api_key": api_key}
        if reasoning in {"low", "medium", "high"}:
            kwargs["reasoning"] = {"effort": reasoning}
        model = ChatOpenAI(**kwargs)
        return model.invoke
    model = ChatAnthropic(model=model_name, temperature=0, api_key=api_key)
    return model.invoke


def _create_judge_graph(*, invoke_model: Callable[[list[Any]], Any]) -> Any:
    def judge_node(state: JudgeState) -> dict[str, Any]:
        messages = [SystemMessage(content=state["system_prompt"])]
        if state.get("last_error") and state.get("last_output"):
            messages.append(
                HumanMessage(
                    content=_judge_repair_prompt(_sanitize_text(state["last_error"]))
                    + "\n\nPrevious JSON:\n"
                    + _sanitize_text(state["last_output"])
                )
            )
        messages.append(HumanMessage(content=state["conversation_text"]))
        resp = invoke_model(messages)
        return {
            "last_output": _extract_text_from_model_content(getattr(resp, "content", resp)),
            "attempts": int(state.get("attempts", 0)) + 1,
        }

    def validate_node(state: JudgeState) -> dict[str, Any]:
        try:
            parsed = _parse_json_from_model_output(_sanitize_text(state.get("last_output", "")))
            sanitized = _sanitize_grade_payload(parsed)
            validated = _validate_grade_payload(sanitized)
            return {"grade_json": _order_grade_payload(validated), "last_error": None}
        except JudgeError as e:
            return {"grade_json": None, "last_error": str(e)}

    def route(state: JudgeState) -> str:
        if state.get("grade_json") is not None:
            return END
        return END if int(state.get("attempts", 0)) >= MAX_ATTEMPTS else "judge"

    graph = StateGraph(JudgeState)
    graph.add_node("judge", judge_node)
    graph.add_node("validate", validate_node)
    graph.add_edge(START, "judge")
    graph.add_edge("judge", "validate")
    graph.add_conditional_edges("validate", route, {"judge": "judge", END: END})
    return graph.compile()


def _judge_transcript(
    transcript_name: str,
    *,
    provider: Provider,
    prompt_name: str,
    rubric_name: str,
    output_name: str | None,
) -> JudgeResult:
    transcript_path = TRANSCRIPTS_DIR / f"{transcript_name}.json"
    if not transcript_path.exists():
        raise JudgeError(f"Transcript not found: {transcript_path}")
    try:
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise JudgeError(f"Invalid transcript JSON: {transcript_path}: {e}") from e
    if not isinstance(transcript, dict):
        raise JudgeError("Transcript JSON must be an object.")
    exchanges = transcript.get("exchanges")
    if not isinstance(exchanges, list) or not exchanges:
        raise JudgeError("Transcript must contain non-empty 'exchanges' list.")

    if provider == "gpt":
        model_name = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        api_key = _require_openai_api_key()
        reasoning = os.environ.get("JUDGE_OPENAI_REASONING_EFFORT", DEFAULT_REASONING).strip().lower() or DEFAULT_REASONING
    else:
        model_name = os.environ.get("ANTHROPIC_MODEL", DEFAULT_CLAUDE_MODEL)
        api_key = _require_anthropic_api_key()
        reasoning = "off"

    invoke_model = _create_model_invoke(provider, model_name, api_key, reasoning)
    graph = _create_judge_graph(invoke_model=invoke_model)

    system_prompt = load_judge_prompt(prompt_name=prompt_name, rubric_name=rubric_name)
    conversation_text = _format_conversation_for_judge(transcript)
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
    if provider == "gpt":
        grade_payload["model"] = {
            "provider": "openai",
            "model": model_name,
            "temperature": 0,
            "reasoning_effort": reasoning,
        }
    else:
        grade_payload["model"] = {"provider": "anthropic", "model": model_name, "temperature": 0}
    grade_payload["judge_llm_calls"] = int(result.get("attempts", 0))
    if _env_truthy("JUDGE_INCLUDE_TIMESTAMP"):
        grade_payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    grade_payload = _order_grade_payload(grade_payload)

    out_doc = dict(transcript)
    out_doc.pop("grade", None)
    out_doc["grade"] = grade_payload
    if output_name is None:
        out_name = transcript_path.name
    else:
        out_name = f"{output_name}.json"
    output_path = transcript_path.with_name(out_name)
    output_path.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return JudgeResult(
        total_score=int(grade_payload["total_score"]),
        max_score=int(grade_payload["max_score"]),
        output_path=output_path,
    )


def judge_transcript_gpt(
    transcript_name: str,
    *,
    prompt_name: str = DEFAULT_JUDGE_PROMPT,
    rubric_name: str = DEFAULT_RUBRIC,
    output_name: str | None = None,
) -> JudgeResult:
    return _judge_transcript(
        transcript_name,
        provider="gpt",
        prompt_name=prompt_name,
        rubric_name=rubric_name,
        output_name=output_name,
    )


def judge_transcript_claude(
    transcript_name: str,
    *,
    prompt_name: str = DEFAULT_JUDGE_PROMPT,
    rubric_name: str = DEFAULT_RUBRIC,
    output_name: str | None = None,
) -> JudgeResult:
    return _judge_transcript(
        transcript_name,
        provider="claude",
        prompt_name=prompt_name,
        rubric_name=rubric_name,
        output_name=output_name,
    )


def judge_transcript(
    transcript_name: str,
    *,
    provider: Provider = "gpt",
    prompt_name: str = DEFAULT_JUDGE_PROMPT,
    rubric_name: str = DEFAULT_RUBRIC,
    output_name: str | None = None,
) -> JudgeResult:
    return _judge_transcript(
        transcript_name,
        provider=provider,
        prompt_name=prompt_name,
        rubric_name=rubric_name,
        output_name=output_name,
    )


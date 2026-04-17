"""
Continue a raw transcript from a chosen pivot turn with a (possibly different) tutor prompt.

History keeps full student+tutor exchanges for turns ``1 .. X-1``. For turn ``X`` only the
student line from the file is kept; the tutor replies first (regenerated), then
``additional_turns`` full student+tutor exchanges run for turns ``X+1`` onward.

Student uses OpenAI (same stack as ``run_student``); tutor provider is selectable (gpt/claude).

Used by ``ui.run_ui_raw_mini`` and usable standalone via ``python -m tutor.run_tutor_mini``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage  # pyright: ignore[reportMissingImports]

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env")

from students.run_student import (  # noqa: E402
    build_graph as build_student_graph,
    get_next_student_message,
)
from tutor.run_tutor import (  # noqa: E402
    create_tutor_graph,
    get_tutor_reply,
    load_system_prompt,
    parse_tutor_response,
)

_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"
_TUTOR_GREETING = "Hi. What would you like to work on today?"
_TUTOR_CALL_MAX_RETRIES = 2

_RAW_SUBDIR_BY_PERSONA_TYPE: dict[str, str] = {
    "chaotic": "chaotic_raw",
    "chitchat": "chitchat_raw",
    "clueless": "clueless_raw",
    "cooperative": "cooperative_raw",
}


def _is_retryable_openai_payload_error(error: Exception) -> bool:
    text = str(error).lower()
    return "badrequesterror" in text and "could not parse the json body" in text


@dataclass(frozen=True)
class MiniContinuationParams:
    """Parameters for continuing a raw transcript."""

    persona_type: str
    source_transcript_stem: str
    resume_from_turn: int
    additional_turns: int
    tutor_prompt: str
    tutor_provider: str


def mini_output_dir(persona_type: str) -> Path:
    """Directory for mini continuation outputs: transcripts/<type>/<type>_mini/."""
    return _TRANSCRIPTS_DIR / persona_type / f"{persona_type}_mini"


def raw_transcript_dir(persona_type: str) -> Path:
    """Directory for raw transcripts for a persona type."""
    sub = _RAW_SUBDIR_BY_PERSONA_TYPE.get(persona_type)
    if not sub:
        raise ValueError(
            f"Unsupported persona type '{persona_type}'. "
            f"Supported: {', '.join(sorted(_RAW_SUBDIR_BY_PERSONA_TYPE))}"
        )
    return _TRANSCRIPTS_DIR / persona_type / sub


def list_raw_transcript_stems(persona_type: str) -> list[str]:
    """Sorted transcript stems (e.g. transcript_01) under the persona raw folder."""
    directory = raw_transcript_dir(persona_type)
    if not directory.exists():
        return []
    stems: list[str] = []
    for path in sorted(directory.glob("transcript_*.json")):
        stems.append(path.stem)
    return stems


def load_raw_transcript(persona_type: str, transcript_stem: str) -> dict[str, Any]:
    """Load and parse a raw JSON transcript; path is transcripts/<type>/<type>_raw/<stem>.json."""
    path = raw_transcript_dir(persona_type) / f"{transcript_stem}.json"
    if not path.exists():
        raise FileNotFoundError(f"Raw transcript not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _exchange_to_tutor_ai_message(exchange: dict[str, Any]) -> AIMessage:
    """Rebuild tutor AIMessage JSON as stored in-graph from a transcript exchange dict."""
    reasoning = (exchange.get("pedagogical_reasoning") or "").strip()
    answer = (exchange.get("tutor") or "").strip()
    if not reasoning:
        reasoning = "Replayed from transcript (no pedagogical reasoning stored)."
    payload = {
        "pedagogical-reasoning": reasoning,
        "Student-facing-answer": answer,
    }
    return AIMessage(content=json.dumps(payload, ensure_ascii=False))


def build_histories_through_turn(
    exchanges: list[dict[str, Any]],
    *,
    through_turn_inclusive: int,
) -> tuple[list, list]:
    """
    Rebuild (tutor_messages, student_messages) after completing *through_turn_inclusive*.

    Option A: turns ``1 .. through_turn_inclusive`` are fully in history; next step is
    student turn ``through_turn_inclusive + 1``.
    """
    if through_turn_inclusive < 1:
        raise ValueError("through_turn_inclusive must be >= 1")
    by_turn: dict[int, dict[str, Any]] = {}
    for ex in exchanges:
        t = ex.get("turn")
        if isinstance(t, int):
            by_turn[t] = ex
    max_turn = max(by_turn.keys()) if by_turn else 0
    if through_turn_inclusive > max_turn:
        raise ValueError(
            f"through_turn_inclusive={through_turn_inclusive} exceeds last turn in transcript ({max_turn})"
        )

    tutor_messages: list = []
    student_messages: list = [HumanMessage(content=_TUTOR_GREETING)]

    for turn in range(1, through_turn_inclusive + 1):
        ex = by_turn.get(turn)
        if ex is None:
            raise ValueError(f"Transcript missing exchange for turn {turn}")
        student_text = ex.get("student")
        if not isinstance(student_text, str):
            student_text = str(student_text)
        tutor_messages.append(HumanMessage(content=student_text))
        tutor_messages.append(_exchange_to_tutor_ai_message(ex))

        student_messages.append(AIMessage(content=student_text))
        tutor_face = ex.get("tutor")
        if not isinstance(tutor_face, str):
            tutor_face = str(tutor_face)
        student_messages.append(HumanMessage(content=tutor_face))

    return tutor_messages, student_messages


def build_histories_resume_pivot(
    exchanges: list[dict[str, Any]],
    *,
    pivot_turn: int,
) -> tuple[list, list, str]:
    """
    Rebuild histories so turns ``1 .. pivot_turn-1`` are complete; turn ``pivot_turn`` has
    only the student message (tutor not yet in state).

    Returns ``(tutor_messages, student_messages, student_text_for_pivot)``.
    """
    if pivot_turn < 1:
        raise ValueError("pivot_turn must be >= 1")
    by_turn: dict[int, dict[str, Any]] = {}
    for ex in exchanges:
        t = ex.get("turn")
        if isinstance(t, int):
            by_turn[t] = ex
    max_turn = max(by_turn.keys()) if by_turn else 0
    if pivot_turn > max_turn:
        raise ValueError(
            f"resume_from_turn={pivot_turn} exceeds last turn in transcript ({max_turn})"
        )

    if pivot_turn == 1:
        tutor_messages: list = []
        student_messages: list = [HumanMessage(content=_TUTOR_GREETING)]
    else:
        tutor_messages, student_messages = build_histories_through_turn(
            exchanges, through_turn_inclusive=pivot_turn - 1
        )

    ex_pivot = by_turn[pivot_turn]
    student_text = ex_pivot.get("student")
    if not isinstance(student_text, str):
        student_text = str(student_text)

    tutor_messages.append(HumanMessage(content=student_text))
    student_messages.append(AIMessage(content=student_text))
    return tutor_messages, student_messages, student_text


def _next_transcript_number(output_dir: Path) -> str:
    used_numbers: set[int] = set()
    if output_dir.exists():
        for path in output_dir.glob("transcript_*.json"):
            match = re.match(r"^transcript_(\d+)\.json$", path.name)
            if match:
                used_numbers.add(int(match.group(1)))
    next_num = 1
    while next_num in used_numbers:
        next_num += 1
    return f"{next_num:02d}"


def continue_from_transcript(
    data: dict[str, Any],
    *,
    resume_from_turn: int,
    additional_turns: int,
    tutor_prompt: str,
    tutor_provider: str,
    source_path: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    """
    Keep turns ``1 .. resume_from_turn-1`` unchanged; at turn ``resume_from_turn`` keep only
    the saved student line, regenerate the tutor reply first, then run *additional_turns*
    full student+tutor exchanges for turns ``resume_from_turn+1`` onward.

    Returns ``(payload_dict, output_path_written)``.
    """
    if additional_turns < 0:
        raise ValueError("additional_turns must be >= 0")

    exchanges_raw = data.get("exchanges")
    if not isinstance(exchanges_raw, list):
        raise ValueError("Transcript missing 'exchanges' list")
    exchanges: list[dict[str, Any]] = [e for e in exchanges_raw if isinstance(e, dict)]

    student_persona = data.get("student_persona")
    if not isinstance(student_persona, str) or not student_persona.strip():
        raise ValueError("Transcript missing 'student_persona'")

    assignment_text = data.get("exercise")
    if not isinstance(assignment_text, str):
        assignment_text = str(assignment_text or "")

    context_text = data.get("context")
    if not isinstance(context_text, str):
        context_text = str(context_text or "")

    course = data.get("course")
    exercise_number = data.get("exercise_number")
    if not isinstance(course, str):
        course = str(course or "")
    if not isinstance(exercise_number, str):
        exercise_number = str(exercise_number or "")

    tutor_messages, student_messages, student_text_pivot = build_histories_resume_pivot(
        exchanges, pivot_turn=resume_from_turn
    )

    total_planned_turns = resume_from_turn + additional_turns
    system_prompt = load_system_prompt(tutor_prompt, assignment_override=assignment_text)
    tutor_graph = create_tutor_graph(system_prompt, provider=tutor_provider)
    student_graph = build_student_graph(prompt_name=student_persona)

    new_exchanges: list[dict[str, object]] = []

    def _one_tutor_reply(turn_index: int) -> tuple[str, str]:
        nonlocal tutor_messages, tutor_graph
        tutor_error: Exception | None = None
        tutor_text_local = ""
        for attempt in range(1, _TUTOR_CALL_MAX_RETRIES + 2):
            try:
                tutor_messages, tutor_text_local = get_tutor_reply(
                    tutor_messages, graph=tutor_graph
                )
                tutor_error = None
                break
            except Exception as error:  # noqa: BLE001
                tutor_error = error
                if _is_retryable_openai_payload_error(error) and attempt < _TUTOR_CALL_MAX_RETRIES + 1:
                    tutor_graph = create_tutor_graph(system_prompt, provider=tutor_provider)
                    print(
                        "[Warn] transient tutor API payload error; "
                        f"retrying turn={turn_index} attempt={attempt}/{_TUTOR_CALL_MAX_RETRIES + 1}"
                    )
                    continue
                break
        if tutor_error is not None:
            raise RuntimeError(
                f"Tutor call failed (turn={turn_index}, persona={student_persona}). "
                f"Last error: {tutor_error}"
            ) from tutor_error

        reasoning = ""
        last_msg = tutor_messages[-1] if tutor_messages else None
        if isinstance(last_msg, AIMessage):
            raw_content = (
                last_msg.content
                if isinstance(last_msg.content, str)
                else str(last_msg.content)
            )
            parsed_reasoning, _ = parse_tutor_response(raw_content)
            reasoning = (
                parsed_reasoning.strip()
                if isinstance(parsed_reasoning, str) and parsed_reasoning.strip()
                else ""
            )
        return tutor_text_local, reasoning

    # Regenerate tutor for pivot turn X (student line unchanged from file).
    tutor_text_x, tutor_reasoning_x = _one_tutor_reply(resume_from_turn)
    student_messages.append(HumanMessage(content=tutor_text_x))
    new_exchanges.append(
        {
            "turn": resume_from_turn,
            "student": student_text_pivot,
            "tutor": tutor_text_x,
            "pedagogical_reasoning": tutor_reasoning_x,
        }
    )

    for offset in range(additional_turns):
        turn_index = resume_from_turn + 1 + offset
        student_message = get_next_student_message(
            student_messages,
            assignment=assignment_text,
            turn_size=total_planned_turns,
            graph=student_graph,
        )
        student_text = (
            student_message.content
            if isinstance(student_message.content, str)
            else str(student_message.content)
        )

        tutor_messages.append(HumanMessage(content=student_text))
        tutor_text, tutor_reasoning = _one_tutor_reply(turn_index)

        student_messages.append(student_message)
        student_messages.append(HumanMessage(content=tutor_text))
        new_exchanges.append(
            {
                "turn": turn_index,
                "student": student_text,
                "tutor": tutor_text,
                "pedagogical_reasoning": tutor_reasoning,
            }
        )

    by_turn_merge: dict[int, dict] = {}
    for ex in exchanges:
        t = ex.get("turn")
        if isinstance(t, int):
            by_turn_merge[t] = ex
    prefix_list = [
        by_turn_merge[t]
        for t in sorted(by_turn_merge.keys())
        if t < resume_from_turn
    ]
    merged = prefix_list + new_exchanges

    persona_type = student_persona.rsplit("_", 1)[0] if "_" in student_persona else ""
    if not persona_type:
        raise ValueError(f"Could not infer persona_type from student_persona={student_persona!r}")

    out_dir = mini_output_dir(persona_type)
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript_num = _next_transcript_number(out_dir)
    transcript_name = f"transcript_{transcript_num}"
    out_path = out_dir / f"{transcript_name}.json"

    source_rel: str | None = None
    if source_path is not None:
        try:
            source_rel = source_path.relative_to(_REPO_ROOT).as_posix()
        except ValueError:
            source_rel = source_path.as_posix()

    payload: dict[str, Any] = {
        "tutor_provider": tutor_provider,
        "tutor_prompt": tutor_prompt,
        "student_persona": student_persona,
        "student_provider": "gpt",
        "course": course,
        "exercise_number": exercise_number,
        "turn_size": total_planned_turns,
        "context": context_text,
        "exercise": assignment_text,
        "turns": len(merged),
        "exchanges": merged,
        "mini_continuation": {
            "source_transcript": source_rel,
            "source_stem": source_path.stem if source_path else None,
            "resume_from_turn": resume_from_turn,
            "additional_turns": additional_turns,
            "original_tutor_prompt": data.get("tutor_prompt"),
            "original_tutor_provider": data.get("tutor_provider"),
        },
    }

    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload, out_path


def run_mini(params: MiniContinuationParams) -> Path:
    """Load raw transcript by stem, continue, write to *_mini/; return output path."""
    path = raw_transcript_dir(params.persona_type) / f"{params.source_transcript_stem}.json"
    data = load_raw_transcript(params.persona_type, params.source_transcript_stem)
    sp = data.get("student_persona")
    if isinstance(sp, str) and sp.strip():
        exp = f"{params.persona_type}_"
        if not sp.startswith(exp):
            raise ValueError(
                f"Transcript student_persona={sp!r} does not match --persona-type={params.persona_type!r} "
                f"(expected prefix {exp!r})."
            )
    _, out_path = continue_from_transcript(
        data,
        resume_from_turn=params.resume_from_turn,
        additional_turns=params.additional_turns,
        tutor_prompt=params.tutor_prompt,
        tutor_provider=params.tutor_provider,
        source_path=path,
    )
    return out_path


def _require_openai_for_student() -> None:
    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")):
        raise RuntimeError(
            "OPENAI_API_KEY (or OPENAI_KEY) is required for the student model."
        )


def _require_tutor_key(provider: str) -> None:
    if provider == "gpt":
        if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")):
            raise RuntimeError("OPENAI_API_KEY (or OPENAI_KEY) is required for GPT tutor.")
    elif provider == "claude":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is required for Claude tutor.")
    else:
        raise ValueError(f"Unknown tutor provider: {provider}")


def _discover_tutor_prompts() -> list[str]:
    prompts_dir = _REPO_ROOT / "tutor" / "prompts"
    if not prompts_dir.exists():
        return []
    return sorted(p.stem for p in prompts_dir.glob("*.txt"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Continue a raw transcript from a pivot turn: keep full exchanges before that "
            "turn, keep only the student line on the pivot turn, regenerate the tutor there first, "
            "then append additional student+tutor exchanges."
        )
    )
    parser.add_argument(
        "--persona-type",
        required=True,
        choices=sorted(_RAW_SUBDIR_BY_PERSONA_TYPE.keys()),
        help="Persona folder under transcripts/ (e.g. chaotic).",
    )
    parser.add_argument(
        "--transcript",
        required=True,
        help="Transcript stem in raw folder (e.g. transcript_01).",
    )
    parser.add_argument(
        "--resume-from-turn",
        type=int,
        required=True,
        help=(
            "Pivot turn X: keep full exchanges for turns 1..X-1; keep only the student message "
            "for turn X; regenerate the tutor for turn X first, then continue."
        ),
    )
    parser.add_argument(
        "--additional-turns",
        type=int,
        required=True,
        help="Number of new full student+tutor exchanges after the regenerated turn X (0 allowed).",
    )
    parser.add_argument(
        "--tutor-prompt",
        required=True,
        help="Tutor prompt stem (tutor/prompts/<name>.txt).",
    )
    parser.add_argument(
        "--tutor-provider",
        choices=["gpt", "claude"],
        required=True,
        help="LLM provider for tutor turns during continuation.",
    )
    args = parser.parse_args(argv)

    try:
        _require_openai_for_student()
        _require_tutor_key(args.tutor_provider)
    except RuntimeError as e:
        print(str(e))
        return 1

    available = set(_discover_tutor_prompts())
    if args.tutor_prompt not in available:
        print(f"Unknown tutor prompt {args.tutor_prompt!r}. Available: {sorted(available)}")
        return 1

    params = MiniContinuationParams(
        persona_type=args.persona_type,
        source_transcript_stem=args.transcript.removesuffix(".json"),
        resume_from_turn=args.resume_from_turn,
        additional_turns=args.additional_turns,
        tutor_prompt=args.tutor_prompt,
        tutor_provider=args.tutor_provider,
    )

    try:
        out = run_mini(params)
        print(f"[Mini] Saved {out.relative_to(_REPO_ROOT)}")
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(str(e))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

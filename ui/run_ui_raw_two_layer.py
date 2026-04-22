"""
Interactive runner that generates raw transcripts using the two-layer tutor.

Each turn goes through a verifier before the reply reaches the student.
If the verifier rejects, the tutor retries once with the feedback injected.
The exchange records a ``verifier`` field with the outcome.

Output folder: transcripts/{persona_type}/{persona_type}_two_layer_raw/

Run with interactive CLI:
    python -m ui.run_ui_raw_two_layer

Or run with command-line arguments:
    python -m ui.run_ui_raw_two_layer --provider gpt --tutor tutor_05 --rubric rubric_05 --personas clueless_01 --course philosophy --exercise 01 --turn-size 10 --trials 2
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage  # pyright: ignore[reportMissingImports]

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env")

from students.run_student import build_graph as build_student_graph  # noqa: E402
from students.run_student import get_next_student_message, list_personas  # noqa: E402
from tutor.run_tutor import load_system_prompt, parse_tutor_response  # noqa: E402
from tutor.run_tutor_two_layer import (  # noqa: E402
    create_two_layer_graph,
    discover_rubrics,
    get_tutor_reply_two_layer,
    load_rubric,
)
from ui.cli_utils import (  # noqa: E402
    confirm_proceed,
    group_personas_by_type,
    parse_persona_type_and_version,
    prompt_integer,
    prompt_numbered_selection,
    prompt_single_selection,
)

_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

_TUTOR_GREETING = "Hi. What would you like to work on today?"
_TWO_LAYER_SUBDIR = "{persona_type}_two_layer_raw"
_SUPPORTED_PERSONA_TYPES = {"chaotic", "cooperative", "clueless"}
_TUTOR_CALL_MAX_RETRIES = 2
PARALLEL_WORKERS = 6
_SAVE_LOCK = threading.Lock()

DEFAULT_TUTOR_PROMPTS: list[str] = ["tutor_05"]
DEFAULT_RUBRIC: str = "rubric_05"
DEFAULT_STUDENT_PERSONAS: list[str] = ["clueless_01"]
DEFAULT_COURSE_EXERCISES: list[tuple[str, str]] = [("philosophy", "01")]
DEFAULT_TURN_SIZE: int = 10
DEFAULT_TRIALS: int = 2


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunConfig:
    tutor_prompt: str
    rubric_name: str
    persona_type: str
    persona_version: str
    course: str
    exercise_number: str
    turn_size: int
    provider: str = "gpt"

    @property
    def student_persona(self) -> str:
        return f"{self.persona_type}_{self.persona_version}"


@dataclass(frozen=True)
class BundleConfig:
    provider: str
    tutor_prompts: list[str]
    rubric_name: str
    student_personas: list[str]
    course_exercises: list[tuple[str, str]]
    turn_size: int
    trials: int


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _discover_tutor_prompts() -> list[str]:
    if not _TUTOR_PROMPTS_DIR.exists():
        return []
    return sorted(p.stem for p in _TUTOR_PROMPTS_DIR.glob("*.txt"))


def _discover_courses() -> list[str]:
    if not _CURRICULUM_DIR.exists():
        return []
    return sorted(p.name for p in _CURRICULUM_DIR.iterdir() if p.is_dir())


def _discover_exercises(course: str) -> list[str]:
    course_dir = _CURRICULUM_DIR / course
    if not course_dir.exists():
        return []
    nums: list[str] = []
    for path in sorted(course_dir.glob("exercise_*.txt")):
        m = re.match(r"^exercise_(\d{2})\.txt$", path.name)
        if m:
            nums.append(m.group(1))
    return nums


# ---------------------------------------------------------------------------
# Assignment loading
# ---------------------------------------------------------------------------


def _load_course_context(course: str) -> str:
    return (_CURRICULUM_DIR / course / "course.txt").read_text(encoding="utf-8").strip()


def _build_assignment_text(course: str, exercise_number: str, turn_size: int) -> str:
    course_text = _load_course_context(course)
    exercise_text = (
        _CURRICULUM_DIR / course / f"exercise_{exercise_number}.txt"
    ).read_text(encoding="utf-8").strip()
    return (
        "Course context:\n"
        f"{course_text}\n\n"
        "Exercise:\n"
        f"{exercise_text}\n\n"
        "Run configuration:\n"
        f"- Planned conversation length: {turn_size} student+tutor exchanges."
    )


# ---------------------------------------------------------------------------
# Transcript numbering + saving
# ---------------------------------------------------------------------------


def _next_transcript_number(output_dir: Path) -> str:
    used: set[int] = set()
    if output_dir.exists():
        for p in output_dir.glob("transcript_*.json"):
            m = re.match(r"^transcript_(\d+)\.json$", p.name)
            if m:
                used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return f"{n:04d}"


def _save_transcript(
    config: RunConfig,
    context_text: str,
    assignment_text: str,
    exchanges: list[dict],
) -> tuple[str, Path]:
    subdir = _TWO_LAYER_SUBDIR.format(persona_type=config.persona_type)
    output_dir = _TRANSCRIPTS_DIR / config.persona_type / subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    with _SAVE_LOCK:
        num = _next_transcript_number(output_dir)
        name = f"transcript_{num}"
        path = output_dir / f"{name}.json"
        payload = {
            "tutor_provider": config.provider,
            "tutor_prompt": config.tutor_prompt,
            "verifier_rubric": config.rubric_name,
            "student_persona": config.student_persona,
            "course": config.course,
            "exercise_number": config.exercise_number,
            "turn_size": config.turn_size,
            "context": context_text,
            "exercise": assignment_text,
            "turns": len(exchanges),
            "exchanges": exchanges,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return name, path


# ---------------------------------------------------------------------------
# Conversation runner
# ---------------------------------------------------------------------------


def _is_retryable_openai_payload_error(error: Exception) -> bool:
    text = str(error).lower()
    return "badrequesterror" in text and "could not parse the json body" in text


def _run_conversation(config: RunConfig, assignment_text: str) -> list[dict]:
    """Run a full multi-turn two-layer conversation. Returns exchange dicts."""
    system_prompt = load_system_prompt(config.tutor_prompt, assignment_override=assignment_text)
    rubric_text = load_rubric(config.rubric_name)
    two_layer_graph = create_two_layer_graph(system_prompt, rubric_text, provider=config.provider)
    student_graph = build_student_graph(prompt_name=config.student_persona)

    exchanges: list[dict] = []
    tutor_messages: list = []
    student_messages: list = [HumanMessage(content=_TUTOR_GREETING)]

    for turn_index in range(config.turn_size):
        student_message = get_next_student_message(
            student_messages,
            assignment=assignment_text,
            turn_size=config.turn_size,
            graph=student_graph,
        )
        student_text = (
            student_message.content
            if isinstance(student_message.content, str)
            else str(student_message.content)
        )

        tutor_messages.append(HumanMessage(content=student_text))

        tutor_error: Exception | None = None
        tutor_text = ""
        verifier_info: dict = {"retried": False, "feedback": None}

        for attempt in range(1, _TUTOR_CALL_MAX_RETRIES + 2):
            try:
                tutor_messages, tutor_text, verifier_info = get_tutor_reply_two_layer(
                    tutor_messages,
                    graph=two_layer_graph,
                )
                tutor_error = None
                break
            except Exception as error:  # noqa: BLE001
                tutor_error = error
                if _is_retryable_openai_payload_error(error) and attempt < _TUTOR_CALL_MAX_RETRIES + 1:
                    print(
                        "[Warn] transient API payload error; "
                        f"retrying turn={turn_index + 1} attempt={attempt}/{_TUTOR_CALL_MAX_RETRIES + 1}"
                    )
                    continue
                break

        if tutor_error is not None:
            raise RuntimeError(
                f"Tutor call failed (turn={turn_index + 1}, persona={config.student_persona}). "
                f"Last error: {tutor_error}"
            ) from tutor_error

        # Extract pedagogical reasoning from the final AIMessage.
        tutor_reasoning = ""
        last_msg = tutor_messages[-1] if tutor_messages else None
        if isinstance(last_msg, AIMessage):
            raw = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
            parsed_reasoning, _ = parse_tutor_response(raw)
            tutor_reasoning = (
                parsed_reasoning.strip()
                if isinstance(parsed_reasoning, str) and parsed_reasoning.strip()
                else ""
            )

        student_messages.append(student_message)
        student_messages.append(HumanMessage(content=tutor_text))

        exchange: dict = {
            "turn": turn_index + 1,
            "student": student_text,
            "tutor": tutor_text,
            "pedagogical_reasoning": tutor_reasoning,
            "verifier": verifier_info,
        }
        exchanges.append(exchange)

    return exchanges


# ---------------------------------------------------------------------------
# API key guards
# ---------------------------------------------------------------------------


def _require_openai_api_key() -> None:
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY"):
        return
    raise RuntimeError("OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set.")


def _require_anthropic_api_key() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    raise RuntimeError("ANTHROPIC_API_KEY environment variable is required but not set.")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_bundle_config(config: BundleConfig) -> None:
    if config.provider == "claude":
        _require_anthropic_api_key()
    else:
        _require_openai_api_key()
    if config.turn_size <= 0:
        raise ValueError("Turn size must be a positive integer.")
    if config.trials <= 0:
        raise ValueError("Trials must be a positive integer.")
    if not config.tutor_prompts:
        raise ValueError("Must select at least one tutor prompt.")
    if not config.student_personas:
        raise ValueError("Must select at least one student persona.")
    if not config.course_exercises:
        raise ValueError("Must select at least one course/exercise combination.")

    available_prompts = set(_discover_tutor_prompts())
    available_rubrics = set(discover_rubrics())
    available_personas = set(list_personas())
    available_courses = set(_discover_courses())

    for prompt in config.tutor_prompts:
        if prompt not in available_prompts:
            raise ValueError(f"Unknown tutor prompt: {prompt}")
    if config.rubric_name not in available_rubrics:
        raise ValueError(f"Unknown rubric: {config.rubric_name}")
    for persona in config.student_personas:
        if persona not in available_personas:
            raise ValueError(f"Unknown student persona: {persona}")
        persona_type, _ = parse_persona_type_and_version(persona)
        if persona_type not in _SUPPORTED_PERSONA_TYPES:
            raise ValueError(
                f"Persona type '{persona_type}' is not supported. "
                f"Supported: {', '.join(sorted(_SUPPORTED_PERSONA_TYPES))}"
            )
    for course, exercise_num in config.course_exercises:
        if course not in available_courses:
            raise ValueError(f"Unknown course: {course}")
        if exercise_num not in _discover_exercises(course):
            raise ValueError(f"Unknown exercise '{exercise_num}' for course '{course}'")


# ---------------------------------------------------------------------------
# Interactive config
# ---------------------------------------------------------------------------


def _get_interactive_config() -> BundleConfig:
    print("=== Two-Layer Tutor — Raw Transcript Generation ===\n")

    provider = prompt_single_selection("Tutor + verifier provider", ["gpt", "claude"], required=True)

    available_prompts = _discover_tutor_prompts()
    selected_prompts = prompt_numbered_selection(
        "Tutor prompts", available_prompts, allow_empty=True, empty_means_all=True
    )

    available_rubrics = discover_rubrics()
    if not available_rubrics:
        raise RuntimeError("No rubrics found in judge/rubrics/")
    rubric_name = prompt_single_selection("Verifier rubric", available_rubrics, required=True)

    available_personas = list_personas()
    selected_personas = prompt_numbered_selection(
        "Student personas", available_personas, allow_empty=True, empty_means_all=True
    )

    available_courses = _discover_courses()
    if not available_courses:
        raise RuntimeError("No courses found in curriculum/")
    course_exercises: list[tuple[str, str]] = []
    for course in available_courses:
        for ex in _discover_exercises(course):
            course_exercises.append((course, ex))

    labels = [f"{c}/exercise_{e}" for c, e in course_exercises]
    selected_labels = prompt_numbered_selection(
        "Course/exercise combinations", labels, allow_empty=True, empty_means_all=True
    )
    selected_course_exercises = [
        course_exercises[labels.index(label)] for label in selected_labels
    ]

    turn_size = prompt_integer(
        "Turn size (student+tutor exchanges per conversation)", min_value=1, max_value=50
    ) or DEFAULT_TURN_SIZE
    trials = prompt_integer(
        "Number of trials per configuration", min_value=1, max_value=100
    ) or DEFAULT_TRIALS

    return BundleConfig(
        provider=provider,
        tutor_prompts=selected_prompts,
        rubric_name=rubric_name,
        student_personas=selected_personas,
        course_exercises=selected_course_exercises,
        turn_size=turn_size,
        trials=trials,
    )


# ---------------------------------------------------------------------------
# CLI args
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate raw transcripts using the two-layer tutor (with verifier)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m ui.run_ui_raw_two_layer
  python -m ui.run_ui_raw_two_layer --provider gpt --tutor tutor_05 --rubric rubric_05 --personas clueless_01 --course philosophy --exercise 01 --turn-size 10 --trials 2
        """,
    )
    parser.add_argument("--provider", choices=["gpt", "claude"], default="gpt")
    parser.add_argument("--tutor", nargs="+", help="Tutor prompt names")
    parser.add_argument("--rubric", help="Verifier rubric stem (from judge/rubrics/rubric_*.md)")
    parser.add_argument("--personas", nargs="+", help="Student persona names")
    parser.add_argument("--course", help="Course name")
    parser.add_argument("--exercise", nargs="+", help="Exercise numbers (e.g. 01 02)")
    parser.add_argument("--turn-size", type=int, default=DEFAULT_TURN_SIZE)
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    return parser.parse_args()


def _get_config_from_args(args: argparse.Namespace) -> BundleConfig:
    tutor_prompts = args.tutor or DEFAULT_TUTOR_PROMPTS
    rubric_name = args.rubric or DEFAULT_RUBRIC
    student_personas = args.personas or DEFAULT_STUDENT_PERSONAS
    course_exercises = (
        [(args.course, ex) for ex in args.exercise]
        if args.course and args.exercise
        else DEFAULT_COURSE_EXERCISES
    )
    return BundleConfig(
        provider=args.provider,
        tutor_prompts=tutor_prompts,
        rubric_name=rubric_name,
        student_personas=student_personas,
        course_exercises=course_exercises,
        turn_size=args.turn_size,
        trials=args.trials,
    )


# ---------------------------------------------------------------------------
# Bundle execution
# ---------------------------------------------------------------------------


def _iter_runs(bundle_config: BundleConfig):
    for tutor_prompt in bundle_config.tutor_prompts:
        for persona_name in bundle_config.student_personas:
            persona_type, persona_version = parse_persona_type_and_version(persona_name)
            for course, exercise_number in bundle_config.course_exercises:
                for trial in range(1, bundle_config.trials + 1):
                    yield RunConfig(
                        tutor_prompt=tutor_prompt,
                        rubric_name=bundle_config.rubric_name,
                        persona_type=persona_type,
                        persona_version=persona_version,
                        course=course,
                        exercise_number=exercise_number,
                        turn_size=bundle_config.turn_size,
                        provider=bundle_config.provider,
                    ), trial


def _run_bundle(bundle_config: BundleConfig) -> int:
    try:
        _validate_bundle_config(bundle_config)
    except (RuntimeError, ValueError) as error:
        print(f"Configuration error: {error}")
        return 1

    persona_groups = group_personas_by_type(bundle_config.student_personas)
    total = (
        len(bundle_config.tutor_prompts)
        * len(bundle_config.student_personas)
        * len(bundle_config.course_exercises)
        * bundle_config.trials
    )

    summary_lines = [
        f"Will generate {total} two-layer transcripts:",
        f"  • Provider (tutor + verifier): {bundle_config.provider.upper()}",
        f"  • Tutor prompt(s): {', '.join(bundle_config.tutor_prompts)}",
        f"  • Verifier rubric: {bundle_config.rubric_name}",
        f"  • {len(bundle_config.student_personas)} persona(s) across {len(persona_groups)} type(s)",
    ]
    for ptype, personas in persona_groups.items():
        summary_lines.append(f"    - {ptype}: {', '.join(personas)}")
    summary_lines.extend([
        f"  • Course/exercise: {', '.join(f'{c}/{e}' for c, e in bundle_config.course_exercises)}",
        f"  • {bundle_config.turn_size} turns per conversation",
        f"  • {bundle_config.trials} trial(s) per configuration",
        f"  • Output: transcripts/{{persona_type}}/{{persona_type}}_two_layer_raw/",
    ])

    if not confirm_proceed("\n".join(summary_lines)):
        print("Cancelled.")
        return 0

    runs = list(_iter_runs(bundle_config))
    print(
        f"[Two-Layer] Running {len(runs)} conversations  "
        f"parallel={PARALLEL_WORKERS}  provider={bundle_config.provider.upper()}"
    )

    failed = 0

    def _run_one(config: RunConfig, trial: int) -> dict:
        assignment_text = _build_assignment_text(config.course, config.exercise_number, config.turn_size)
        context_text = _load_course_context(config.course)
        try:
            exchanges = _run_conversation(config, assignment_text)
        except RuntimeError as error:
            return {"ok": False, "trial": trial, "config": config, "reason": str(error)}
        _, path = _save_transcript(config, context_text, assignment_text, exchanges)
        retried_turns = sum(1 for ex in exchanges if ex.get("verifier", {}).get("retried"))
        return {"ok": True, "trial": trial, "config": config, "path": path, "retried_turns": retried_turns}

    try:
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
            futures = {pool.submit(_run_one, config, trial): (config, trial) for config, trial in runs}
            completed = 0
            for future in as_completed(futures):
                completed += 1
                result = future.result()
                config = result["config"]
                trial = int(result["trial"])
                if result["ok"]:
                    path = Path(result["path"])
                    retried = result["retried_turns"]
                    print(
                        f"[Two-Layer] [{completed}/{len(runs)}]  "
                        f"trial={trial}  tutor={config.tutor_prompt}  "
                        f"persona={config.student_persona}  "
                        f"course={config.course}  exercise={config.exercise_number}  "
                        f"verifier_retries={retried}/{config.turn_size}  "
                        f"saved={path.relative_to(_REPO_ROOT)}"
                    )
                else:
                    failed += 1
                    print(
                        f"[Two-Layer] [{completed}/{len(runs)}]  FAILED  "
                        f"trial={trial}  persona={config.student_persona}  "
                        f"reason={result['reason']}"
                    )
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except FileNotFoundError as error:
        print(f"Missing curriculum file: {error.filename}")
        return 1

    if failed:
        print(f"[Two-Layer] Done with {failed} failed run(s).")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    args = _parse_args()
    use_interactive = not any([args.tutor, args.personas, args.course, args.exercise, args.rubric])
    try:
        bundle_config = _get_interactive_config() if use_interactive else _get_config_from_args(args)
        return _run_bundle(bundle_config)
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}")
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

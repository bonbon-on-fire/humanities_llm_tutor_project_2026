from __future__ import annotations

import importlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.messages import HumanMessage

from tutor.run_tutor import get_tutor_reply


_STUDENT_TYPES: tuple[str, ...] = ("chaotic", "chitchat", "clueless")
_EXERCISE_RE = re.compile(r"^exercise_(\d{2})\.txt$")
_STUDENT_DIR_RE = re.compile(r"^student_(\d{2})$")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _prompt_text(prompt: str) -> str:
    return input(prompt).strip()


def _normalize_two_digit_number(text: str) -> str | None:
    s = (text or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{1,2}", s) is None:
        return None
    n = int(s)
    if n <= 0 or n > 99:
        return None
    return f"{n:02d}"


def _discover_exercise_numbers(exercises_dir: Path) -> list[str]:
    numbers: set[str] = set()
    if not exercises_dir.exists():
        return []
    for p in exercises_dir.iterdir():
        if not p.is_file():
            continue
        m = _EXERCISE_RE.match(p.name)
        if m:
            numbers.add(m.group(1))
    return sorted(numbers)


def _discover_student_versions(student_type_dir: Path) -> list[str]:
    versions: set[str] = set()
    if not student_type_dir.exists():
        return []
    for p in student_type_dir.iterdir():
        if not p.is_dir():
            continue
        m = _STUDENT_DIR_RE.match(p.name)
        if m:
            versions.add(m.group(1))
    return sorted(versions)


def _format_available_numbers(nums: list[str]) -> str:
    if not nums:
        return "(none)"
    if len(nums) == 1:
        return nums[0]
    # If contiguous, show as range.
    ints = [int(x) for x in nums]
    if ints == list(range(ints[0], ints[0] + len(ints))):
        return f"{nums[0]}..{nums[-1]}"
    return ", ".join(nums)


def _prompt_exercise(exercises_dir: Path) -> Path:
    available = _discover_exercise_numbers(exercises_dir)
    if not available:
        raise RuntimeError(f"No exercise_*.txt files found under: {exercises_dir}")

    while True:
        raw = _prompt_text(f"Exercise number ({_format_available_numbers(available)}): ")
        choice = _normalize_two_digit_number(raw)
        if choice is None:
            print("Please enter a number like 01, 02, ...")
            continue
        path = exercises_dir / f"exercise_{choice}.txt"
        if not path.exists():
            print(f"exercise_{choice}.txt not found. Available: {', '.join(available)}")
            continue
        return path


def _prompt_student_type() -> str:
    while True:
        raw = _prompt_text(f"Student type ({', '.join(_STUDENT_TYPES)}): ").lower()
        if raw in _STUDENT_TYPES:
            return raw
        print(f"Please enter one of: {', '.join(_STUDENT_TYPES)}")


def _prompt_student_version(student_type_dir: Path, student_type: str) -> str:
    available = _discover_student_versions(student_type_dir)
    if not available:
        raise RuntimeError(f"No student_## folders found under: {student_type_dir}")
    while True:
        raw = _prompt_text(f"Student version ({_format_available_numbers(available)}) for {student_type}: ")
        choice = _normalize_two_digit_number(raw)
        if choice is None:
            print("Please enter a number like 01, 02, ...")
            continue
        folder = student_type_dir / f"student_{choice}"
        if not folder.exists():
            print(f"student_{choice} not found. Available: {', '.join(available)}")
            continue
        return choice


def _prompt_turns() -> int:
    while True:
        raw = _prompt_text("Turns (number of student+tutor exchanges): ")
        if re.fullmatch(r"\d+", raw or "") is None:
            print("Please enter a positive integer.")
            continue
        n = int(raw)
        if n <= 0:
            print("Please enter a positive integer.")
            continue
        return n


_INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\\\|?*]+')
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_transcript_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = _WHITESPACE_RE.sub("_", s)
    s = _INVALID_FILENAME_CHARS_RE.sub("_", s)
    s = s.strip(" ._")
    if not s.endswith(".json"):
        s += ".json"
    return s


def _prompt_transcript_path(transcripts_dir: Path) -> Path:
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    while True:
        raw = _prompt_text("Name transcript (will be saved under judge/transcripts): ")
        normalized = _normalize_transcript_name(raw)
        if normalized == ".json":
            print("Please enter a non-empty name.")
            continue
        path = transcripts_dir / normalized
        if path.exists():
            print("A transcript with that name already exists. Please choose a different name.")
            continue
        return path


def _student_module_path(student_type: str, version: str) -> str:
    # students/<type>_student/student_##/bot.py is a proper Python package.
    return f"students.{student_type}_student.student_{version}.bot"


@dataclass(frozen=True)
class _StudentBotApi:
    build_graph: object
    get_next_student_message: object


def _load_student_bot(student_type: str, version: str) -> _StudentBotApi:
    mod = importlib.import_module(_student_module_path(student_type, version))
    build_graph = getattr(mod, "build_graph", None)
    get_next_student_message = getattr(mod, "get_next_student_message", None)
    if build_graph is None or get_next_student_message is None:
        raise RuntimeError(
            f"Student bot module missing expected API (build_graph/get_next_student_message): {mod.__name__}"
        )
    return _StudentBotApi(build_graph=build_graph, get_next_student_message=get_next_student_message)


def _check_required_env() -> None:
    # Student bots accept OPENAI_KEY or OPENAI_API_KEY.
    if not (os.environ.get("OPENAI_KEY") or os.environ.get("OPENAI_API_KEY")):
        raise RuntimeError("Missing OPENAI_KEY / OPENAI_API_KEY (required for student bot).")
    # Tutor requires OPENAI_API_KEY specifically.
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Missing OPENAI_API_KEY (required for tutor).")


def main() -> int:
    root = _repo_root()
    exercises_dir = root / "tutor" / "exercises"
    transcripts_dir = root / "judge" / "transcripts"

    try:
        _check_required_env()
    except RuntimeError as e:
        print(str(e))
        return 1

    try:
        exercise_path = _prompt_exercise(exercises_dir)
        student_type = _prompt_student_type()
        student_type_dir = root / "students" / f"{student_type}_student"
        version = _prompt_student_version(student_type_dir, student_type)
        turns = _prompt_turns()
    except KeyboardInterrupt:
        print("\nCancelled. Exiting without saving.")
        return 130

    exercise_text = exercise_path.read_text(encoding="utf-8").strip()
    student_api = _load_student_bot(student_type, version)
    student_graph = student_api.build_graph()

    tutor_greeting = "Hi. What would you like to work on today?"
    print()
    print(
        f"[Config] exercise={exercise_path.name} (used as context for student and tutor) "
        f"student={student_type} version=student_{version} turns={turns}"
    )
    print("[Tutor]", tutor_greeting, "\n")

    transcript: list[dict[str, object]] = []
    tutor_messages: list = []
    student_messages_for_bot: list = [HumanMessage(content=tutor_greeting)]

    try:
        for turn_idx in range(turns):
            # Exercise is passed as context so the student bot can reference the assignment.
            student_msg = student_api.get_next_student_message(
                student_messages_for_bot,
                exercise=exercise_text,
                graph=student_graph,
            )
            student_content = getattr(student_msg, "content", "")
            student_text = student_content if isinstance(student_content, str) else str(student_content)
            print("[Student]", student_text, "\n")

            tutor_messages.append(HumanMessage(content=student_text))
            tutor_messages, tutor_text = get_tutor_reply(
                tutor_messages,
                assignment_override=exercise_text or None,
            )
            print("[Tutor]", tutor_text, "\n")

            student_messages_for_bot.append(student_msg)
            student_messages_for_bot.append(HumanMessage(content=tutor_text))

            transcript.append({"turn": turn_idx + 1, "student": student_text, "tutor": tutor_text})

        # Build output with exercise as context for the judge.
        transcript_payload = {
            "exercise": exercise_text,
            "exercise_file": exercise_path.name,
            "student_type": student_type,
            "student_version": version,
            "exchanges": transcript,
        }
    except KeyboardInterrupt:
        print("\nCancelled. Exiting without saving.")
        return 130

    try:
        out_path = _prompt_transcript_path(transcripts_dir)
    except KeyboardInterrupt:
        print("\nCancelled. Exiting without saving.")
        return 130

    out_path.write_text(json.dumps(transcript_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved transcript to: {out_path}")
    return 0


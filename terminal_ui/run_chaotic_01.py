"""
Run a fixed tutor-vs-student scenario in terminal:
- Tutor prompt: tutor_01
- Student persona: chaotic_01
- Course: philosophy
- Exercise: exercise_01
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from langchain_core.messages import HumanMessage

from students.run_student import build_graph as build_student_graph
from students.run_student import get_next_student_message
from tutor.run_tutor import create_tutor_graph, get_tutor_reply, load_system_prompt

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"


def _require_openai_api_key() -> None:
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY"):
        return
    raise RuntimeError(
        "OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set."
    )


def _load_assignment_text(turn_size: int) -> str:
    course_path = _CURRICULUM_DIR / "philosophy" / "course.txt"
    exercise_path = _CURRICULUM_DIR / "philosophy" / "exercise_01.txt"
    course_text = course_path.read_text(encoding="utf-8").strip()
    exercise_text = exercise_path.read_text(encoding="utf-8").strip()
    return (
        "Course context:\n"
        f"{course_text}\n\n"
        "Exercise:\n"
        f"{exercise_text}\n\n"
        "Run configuration:\n"
        f"- Planned conversation length: {turn_size} student+tutor exchanges."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run chaotic_01 vs tutor on philosophy exercise_01."
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=4,
        help="Number of student+tutor exchanges (default: 4).",
    )
    args = parser.parse_args()

    if args.turns <= 0:
        print("Turns must be a positive integer.")
        return 1

    try:
        _require_openai_api_key()
        assignment_text = _load_assignment_text(args.turns)
    except FileNotFoundError as e:
        print(f"Missing curriculum file: {e.filename}")
        return 1
    except RuntimeError as e:
        print(str(e))
        return 1

    system_prompt = load_system_prompt("tutor_01", assignment_override=assignment_text)
    tutor_graph = create_tutor_graph(system_prompt)
    student_graph = build_student_graph(prompt_name="chaotic_01")

    print("[Config] tutor=tutor_01  persona=chaotic_01  course=philosophy  exercise=01")
    print(f"[Config] turns={args.turns}\n")

    tutor_greeting = "Hi. What would you like to work on today?"
    print(f"[Tutor] {tutor_greeting}\n")

    tutor_messages: list = []
    student_messages: list = [HumanMessage(content=tutor_greeting)]

    for _ in range(args.turns):
        student_msg = get_next_student_message(
            student_messages,
            assignment=assignment_text,
            turn_size=args.turns,
            graph=student_graph,
        )
        student_text = (
            student_msg.content
            if isinstance(student_msg.content, str)
            else str(student_msg.content)
        )
        print(f"[Student] {student_text}\n")

        tutor_messages.append(HumanMessage(content=student_text))
        tutor_messages, tutor_text = get_tutor_reply(tutor_messages, graph=tutor_graph)
        print(f"[Tutor] {tutor_text}\n")

        student_messages.append(student_msg)
        student_messages.append(HumanMessage(content=tutor_text))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

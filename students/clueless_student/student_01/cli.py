"""
CLI to run a conversation with the clueless student bot.

Modes:
- Interactive: you play the tutor (type each tutor message; bot replies as student).
- Mock tutor: a scripted tutor replies with good "helping lost student" behavior (diagnostic then short reply).
- --tutor: use the real tutor bot; tutor output is the student's input.

Usage (from project root):
  python -m student_personas.clueless_student.student_01.cli
  python -m student_personas.clueless_student.student_01.cli --mock-tutor
  python -m student_personas.clueless_student.student_01.cli --tutor --exercise "..."
  python -m student_personas.clueless_student.student_01.cli --prompt student_01_prompt_02 --tutor
  python -m student_personas.clueless_student.student_01.cli --max-turns 20

Requires OPENAI_KEY (or OPENAI_API_KEY) for the student bot. For --tutor also set OPENAI_API_KEY.
"""

import argparse
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Allow running as __main__ or as module from project root.
if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    __package__ = "student_personas.clueless_student.student_01"

from langchain_core.messages import AIMessage, HumanMessage

from .bot import build_graph, get_next_student_message

_STUDENT_DIR = Path(__file__).resolve().parent


def _prompt_path_from_name(prompt_name: str) -> Path:
    """Resolve e.g. student_01_prompt_02 to prompts/student_01_prompt_02.txt."""
    name = prompt_name.strip()
    if not name:
        raise ValueError("Prompt name must be non-empty.")
    if not name.endswith(".txt"):
        name = name + ".txt"
    p = _STUDENT_DIR / "prompts" / name
    if not p.exists():
        raise FileNotFoundError(f"Prompt file not found: {p}")
    return p


def _mock_tutor_reply(turn_index: int, last_student_content: str) -> str:
    """Scripted mock tutor: good 'helping lost student' behavior—diagnostic question first, then short reply + check."""
    if turn_index == 0:
        return (
            "Hi. I'm your tutor for this assignment. I'm here to help you work through it step by step. "
            "What would you like to work on first?"
        )
    # Alternate: odd turns = one diagnostic question; even turns = short reply + check for understanding.
    if turn_index % 2 == 1:
        return (
            "To help you without overwhelming you—what part is unclear? "
            "The main question we're trying to answer, or a specific concept?"
        )
    return (
        "Here's one way to think about it: start by stating the problem in your own words. "
        "Does that help? What would you try first?"
    )


def run_interactive(max_turns: int, exercise: str, prompt_path: Path | None = None) -> None:
    """Run conversation loop: user types tutor messages, bot replies as student."""
    persona = None
    if prompt_path is not None:
        from .bot import load_persona
        persona = load_persona(path=prompt_path)
    graph = build_graph(persona=persona)
    messages: list = []
    print("Clueless student bot (student_01). You play the tutor. Type 'quit' to exit.\n")
    if exercise:
        print("[Exercise context is set and visible to the student.]\n")

    for turn in range(max_turns):
        if not messages:
            prompt = "Tutor message (or 'quit'): "
        else:
            prompt = "Tutor reply (or 'quit'): "
        try:
            tutor_text = input(prompt).strip()
        except EOFError:
            break
        if not tutor_text or tutor_text.lower() == "quit":
            print("Exiting.")
            break
        messages.append(HumanMessage(content=tutor_text))
        student_msg = get_next_student_message(messages, exercise=exercise or None, graph=graph)
        messages.append(student_msg)
        assert isinstance(student_msg, AIMessage)
        print("\n[Student]", student_msg.content, "\n")
    else:
        print(f"Reached max turns ({max_turns}). Exiting.")


def run_mock_tutor(max_turns: int, exercise: str, prompt_path: Path | None = None) -> None:
    """Run conversation loop with a scripted mock tutor (good 'helping lost student' behavior)."""
    persona = None
    if prompt_path is not None:
        from .bot import load_persona
        persona = load_persona(path=prompt_path)
    graph = build_graph(persona=persona)
    messages: list = []
    print("Clueless student bot (student_01) with mock tutor. Student may speak first or after tutor.\n")
    if exercise:
        print("[Exercise context is set and visible to the student.]\n")

    # First message: mock tutor greets.
    tutor_msg = _mock_tutor_reply(0, "")
    messages.append(HumanMessage(content=tutor_msg))
    print("[Tutor]", tutor_msg, "\n")

    for turn in range(max_turns - 1):
        student_msg = get_next_student_message(messages, exercise=exercise or None, graph=graph)
        messages.append(student_msg)
        assert isinstance(student_msg, AIMessage)
        print("[Student]", student_msg.content, "\n")
        tutor_msg = _mock_tutor_reply(turn + 1, student_msg.content)
        messages.append(HumanMessage(content=tutor_msg))
        print("[Tutor]", tutor_msg, "\n")
    print("Mock tutor run finished.")


def run_tutor_mode(max_turns: int, exercise: str, prompt_path: Path | None = None) -> None:
    """Run conversation loop: real tutor bot vs student bot. Tutor output is student's input."""
    import os
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY not set. The tutor requires it. Set it in .env or the environment.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        from tutor.run_tutor import get_tutor_reply
    except ImportError as e:
        print(
            "Tutor module not found. Run from project root so 'tutor' package is importable.",
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    persona = None
    if prompt_path is not None:
        from .bot import load_persona
        persona = load_persona(path=prompt_path)
    student_graph = build_graph(persona=persona)
    tutor_messages: list = []
    tutor_greeting = "Hi. What would you like to work on today?"
    student_messages_for_bot = [HumanMessage(content=tutor_greeting)]

    print("Tutor vs Student (clueless_student_01). Tutor output is the student's input.\n")
    if exercise:
        print("[Exercise context is set for both tutor and student.]\n")
    print("[Tutor]", tutor_greeting, "\n")

    for turn in range(max_turns):
        student_msg = get_next_student_message(
            student_messages_for_bot,
            exercise=exercise or None,
            graph=student_graph,
        )
        assert isinstance(student_msg, AIMessage)
        student_text = student_msg.content if isinstance(student_msg.content, str) else str(student_msg.content)
        print("[Student]", student_text, "\n")

        tutor_messages.append(HumanMessage(content=student_text))
        assignment_override = exercise if exercise else None
        tutor_messages, tutor_text = get_tutor_reply(
            tutor_messages,
            assignment_override=assignment_override or None,
        )
        print("[Tutor]", tutor_text, "\n")

        student_messages_for_bot.append(student_msg)
        student_messages_for_bot.append(HumanMessage(content=tutor_text))

    print("Max turns reached. Done.")


def _load_exercise(args: argparse.Namespace) -> str:
    """Load exercise string from --exercise-file or --exercise."""
    if getattr(args, "exercise_file", None):
        path = Path(args.exercise_file)
        if not path.exists():
            raise FileNotFoundError(f"Exercise file not found: {path}")
        return path.read_text(encoding="utf-8").strip()
    return (getattr(args, "exercise", None) or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run clueless student bot (student_01). Interactive = you play tutor; mock = scripted tutor (good 'helping lost student' behavior)."
    )
    parser.add_argument(
        "--mock-tutor",
        action="store_true",
        help="Use a scripted mock tutor instead of typing tutor messages.",
    )
    parser.add_argument(
        "--tutor",
        action="store_true",
        help="Use the real tutor bot; tutor output is the student's input.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=20,
        metavar="N",
        help="Maximum number of exchanges (default 20).",
    )
    parser.add_argument(
        "--exercise",
        type=str,
        default="",
        metavar="TEXT",
        help="Exercise/assignment text the student is working on (visible to the student bot).",
    )
    parser.add_argument(
        "--exercise-file",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a file containing the exercise text (overrides --exercise if set).",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        metavar="NAME",
        help="Prompt file name (e.g. student_01_prompt_02). File: prompts/<NAME>.txt.",
    )
    args = parser.parse_args()
    try:
        exercise = _load_exercise(args)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    prompt_path = None
    if getattr(args, "prompt", None):
        try:
            prompt_path = _prompt_path_from_name(args.prompt)
        except (ValueError, FileNotFoundError) as e:
            print(e, file=sys.stderr)
            return 1
    if args.tutor:
        run_tutor_mode(max_turns=args.max_turns, exercise=exercise, prompt_path=prompt_path)
    elif args.mock_tutor:
        run_mock_tutor(max_turns=args.max_turns, exercise=exercise, prompt_path=prompt_path)
    else:
        run_interactive(max_turns=args.max_turns, exercise=exercise, prompt_path=prompt_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

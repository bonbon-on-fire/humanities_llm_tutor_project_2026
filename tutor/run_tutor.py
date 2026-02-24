"""
Terminal-based Humanities LLM Tutor using LangGraph and OpenAI.

Loads OPENAI_API_KEY from the environment or from a .env file in the project root
(the parent of this tutor folder).
Optional: TUTOR_DEBUG=1 to show pedagogical reasoning; ASSIGNMENT to override assignment text.
"""

import json
import operator
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import Annotated, TypedDict

# Load .env from project root (parent of tutor folder) so OPENAI_API_KEY is set
_load_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_load_env_path)


# ---------------------------------------------------------------------------
# Prompt and config
# ---------------------------------------------------------------------------

def _tutor_root() -> Path:
    """Root of the tutor package (this folder)."""
    return Path(__file__).resolve().parent


def load_system_prompt(assignment_override: str | None = None) -> str:
    path = _tutor_root() / "prompts" / "tutor_prompt_01.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if assignment_override is not None:
        text = re.sub(
            r"<Assignment>.*?</Assignment>",
            f"<Assignment>\n{assignment_override.strip()}\n</Assignment>",
            text,
            flags=re.DOTALL,
        )
    return text.strip()


# ---------------------------------------------------------------------------
# LangGraph state and model
# ---------------------------------------------------------------------------

class TutorState(TypedDict):
    messages: Annotated[list, operator.add]


def _create_tutor_graph(system_prompt: str):
    model = ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", "gpt-5.2"),
        api_key=os.environ.get("OPENAI_API_KEY"),
    )

    def tutor_node(state: TutorState) -> dict:
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = model.invoke(messages)
        return {"messages": [response]}

    graph = StateGraph(TutorState)
    graph.add_node("tutor", tutor_node)
    graph.add_edge(START, "tutor")
    graph.add_edge("tutor", END)
    return graph.compile()


def _extract_json_object(text: str) -> str | None:
    """Find first { and return substring with balanced braces."""
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


def _parse_tutor_response(content: str) -> tuple[str | None, str | None]:
    """Extract pedagogical-reasoning and Student-facing-answer from JSON in content."""
    text = content.strip()
    # Try parsing whole content as JSON
    try:
        data = json.loads(text)
        return (
            data.get("pedagogical-reasoning"),
            data.get("Student-facing-answer"),
        )
    except json.JSONDecodeError:
        pass
    # Try ```json ... ``` block
    code = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if code:
        try:
            data = json.loads(code.group(1).strip())
            return (
                data.get("pedagogical-reasoning"),
                data.get("Student-facing-answer"),
            )
        except json.JSONDecodeError:
            pass
    # Find balanced-brace JSON object
    obj = _extract_json_object(text)
    if obj:
        try:
            data = json.loads(obj)
            return (
                data.get("pedagogical-reasoning"),
                data.get("Student-facing-answer"),
            )
        except json.JSONDecodeError:
            pass
    return None, None


def _print_tutor_reply(ai_message: AIMessage, show_reasoning: bool) -> None:
    content = ai_message.content if isinstance(ai_message.content, str) else str(ai_message.content)
    reasoning, answer = _parse_tutor_response(content)
    if answer is not None:
        if show_reasoning and reasoning:
            print("\n[Reasoning]", reasoning, "\n", sep="\n")
        print(answer)
    else:
        print(content)


def get_tutor_reply(
    messages: list,
    assignment_override: str | None = None,
    *,
    graph=None,
    show_reasoning: bool = False,
) -> tuple[list, str]:
    """
    Invoke the tutor with the given conversation (list of HumanMessage, AIMessage).
    Returns (updated_messages, student_facing_answer_text).
    Use this to drive the tutor from another script (e.g. student bot CLI).
    """
    if graph is None:
        system_prompt = load_system_prompt(assignment_override)
        graph = _create_tutor_graph(system_prompt)
    result = graph.invoke({"messages": messages})
    out_messages = result["messages"]
    last = out_messages[-1] if out_messages else None
    if isinstance(last, AIMessage):
        content = last.content if isinstance(last.content, str) else str(last.content)
        _, student_facing = _parse_tutor_response(content)
        text = student_facing if student_facing is not None else content
    else:
        text = ""
    return out_messages, text


# ---------------------------------------------------------------------------
# Terminal REPL
# ---------------------------------------------------------------------------

def main() -> None:
    # .env is loaded at import time; ensure key is present
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY not set. Add it to the environment or to the project's .env file.",
            file=sys.stderr,
        )
        sys.exit(1)

    assignment_override = os.environ.get("ASSIGNMENT")
    system_prompt = load_system_prompt(assignment_override)
    show_reasoning = os.environ.get("TUTOR_DEBUG", "").strip().lower() in ("1", "true", "yes")

    graph = _create_tutor_graph(system_prompt)
    messages: list = []

    print("Humanities Tutor (terminal). Type your message and press Enter. Ctrl+C or 'exit' to quit.\n")

    while True:
        try:
            line = input("You: ").strip()
        except EOFError:
            break
        if not line:
            continue
        if line.lower() in ("exit", "quit", "q"):
            print("Goodbye.")
            break

        messages.append(HumanMessage(content=line))
        result = graph.invoke({"messages": messages})
        messages = result["messages"]
        last = messages[-1] if messages else None
        if isinstance(last, AIMessage):
            print("\nTutor:", end=" ")
            _print_tutor_reply(last, show_reasoning)
        print()


if __name__ == "__main__":
    main()

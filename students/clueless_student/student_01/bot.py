"""
Clueless student bot (student_01): LLM-based agent that simulates a lost/confused student
attacking the "helping lost student" failure. Uses LangGraph; prompt loaded from prompts/student_01_prompt_01.txt.

Uses OPENAI_KEY from the environment (or .env) for the LLM; falls back to OPENAI_API_KEY.
"""

import os
import warnings
from pathlib import Path
from typing import Annotated, Sequence

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

warnings.filterwarnings(
    "ignore",
    message=r"Core Pydantic V1 functionality isn't compatible with Python 3\.14 or greater\.",
    category=UserWarning,
)

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict

# -----------------------------------------------------------------------------
# API key (OPENAI_KEY from .env, else OPENAI_API_KEY)
# -----------------------------------------------------------------------------


def _get_openai_api_key() -> str | None:
    """API key for OpenAI: OPENAI_KEY first, then OPENAI_API_KEY."""
    return os.environ.get("OPENAI_KEY") or os.environ.get("OPENAI_API_KEY")


# -----------------------------------------------------------------------------
# Prompt (student_01_prompt_01.txt)
# -----------------------------------------------------------------------------

DEFAULT_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "student_01_prompt_01.txt"


def load_persona(path: Path | None = None) -> str:
    """Load student prompt from prompts/student_01_prompt_01.txt (or the given path)."""
    p = path or DEFAULT_PROMPT_PATH
    if not p.exists():
        raise FileNotFoundError(f"Prompt file not found: {p}")
    return p.read_text(encoding="utf-8").strip()


# -----------------------------------------------------------------------------
# State and graph
# -----------------------------------------------------------------------------


class StudentBotState(TypedDict):
    """State for the student bot: conversation history and optional exercise text."""

    messages: Annotated[list[BaseMessage], add_messages]
    exercise: NotRequired[str]  # Assignment/exercise the student is working on with the tutor


def _last_message_is_tutor(state: StudentBotState) -> bool:
    """True if the last message in state is from the tutor (human)."""
    messages = state.get("messages") or []
    if not messages:
        return False
    return isinstance(messages[-1], HumanMessage)


def _build_student_agent_node(persona: str, model: ChatOpenAI):
    """Build the node that generates the next student message from conversation state."""

    def student_agent(state: StudentBotState) -> dict:
        messages = state.get("messages") or []
        if not messages:
            return {"messages": [AIMessage(content="[Student has nothing to respond to yet.]")]}
        if not _last_message_is_tutor(state):
            # Last message was from student; don't add another (shouldn't happen in normal flow).
            return {}

        # Model sees: system = persona (+ exercise if provided), chat = conversation (tutor=user, student=assistant).
        system_content = persona
        exercise = (state.get("exercise") or "").strip()
        if exercise:
            system_content += "\n\n---\n\nCurrent exercise (assignment) you are working on with the tutor:\n\n" + exercise
        system = SystemMessage(content=system_content)
        chat_messages = [system] + list(messages)
        response = model.invoke(chat_messages)
        if not isinstance(response, BaseMessage):
            response = AIMessage(content=str(response))
        return {"messages": [response]}

    return student_agent


def build_graph(*, model: ChatOpenAI | None = None, persona: str | None = None):
    """
    Build and compile the LangGraph for the clueless student bot.

    - model: Chat model (default: ChatOpenAI with temperature > 0 for variety).
    - persona: Persona/prompt text (default: loaded from prompts/student_01_prompt_01.txt).
    """
    if model is None:
        api_key = _get_openai_api_key()
        model = ChatOpenAI(
            model=os.environ.get("OPENAI_MODEL", "gpt-5.2"),
            temperature=0.7,
            api_key=api_key,
        )
    if persona is None:
        persona = load_persona()

    node_fn = _build_student_agent_node(persona, model)
    builder = StateGraph(StudentBotState)
    builder.add_node("student_agent", node_fn)
    builder.add_edge(START, "student_agent")
    builder.add_edge("student_agent", END)
    return builder.compile()


def get_next_student_message(
    messages: Sequence[BaseMessage],
    *,
    exercise: str | None = None,
    graph=None,
    model: ChatOpenAI | None = None,
    persona: str | None = None,
) -> BaseMessage:
    """
    Given the current conversation (tutor + student messages), return the next
    student message. The last message in `messages` must be from the tutor (HumanMessage).

    exercise: Optional string describing the assignment/exercise the student is working on
    with the tutor; the student will see this and can reference it when expressing confusion.

    If `graph` is provided, use it; otherwise build one with optional `model` and `persona`.
    """
    if graph is None:
        graph = build_graph(model=model, persona=persona)
    payload: dict = {"messages": list(messages)}
    if exercise is not None:
        payload["exercise"] = exercise.strip()
    result = graph.invoke(payload)
    out_messages = result.get("messages") or []
    if not out_messages:
        return AIMessage(content="[No response generated.]")
    return out_messages[-1]

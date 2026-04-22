"""
Two-layer tutor engine.

Bottom layer: the standard tutor (run_tutor.py).
Top layer: a rubric-aware verifier that reviews the draft reply before it reaches
the student. If the verifier rejects, it sends plain-language feedback to the bottom
layer which regenerates once. The draft is never committed to conversation history —
only the final reply is appended.

Cap: one retry per turn. If the verifier rejects after the retry, the revised reply
is sent regardless.

Public API
----------
    load_rubric(rubric_name)
    create_two_layer_graph(system_prompt, rubric_text, *, provider)
    get_tutor_reply_two_layer(messages, *, graph) -> (updated_messages, student_text, verifier_info)

    verifier_info = {"retried": bool, "feedback": str | None}
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env")

from tutor.run_tutor import (  # noqa: E402
    create_tutor_graph,
    get_tutor_reply,
    parse_tutor_response,
)
from utils.parsing import extract_json_object  # noqa: E402

RUBRICS_DIR = _REPO_ROOT / "judge" / "rubrics"
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"

_REVIEWER_NOTE_TEMPLATE = (
    "\n\n[Reviewer note — not visible to student]\n"
    "Your previous response had an issue: {feedback}\n"
    "Please revise your response."
)


# ---------------------------------------------------------------------------
# Rubric loading
# ---------------------------------------------------------------------------


def discover_rubrics() -> list[str]:
    """Return available rubric stems from judge/rubrics/."""
    if not RUBRICS_DIR.exists():
        return []
    return sorted(p.stem for p in RUBRICS_DIR.glob("rubric_*.md"))


def load_rubric(rubric_name: str) -> str:
    """Load rubric text from judge/rubrics/<rubric_name>.md."""
    path = RUBRICS_DIR / f"{rubric_name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Rubric '{rubric_name}' not found at {path}.\n"
            f"Available: {discover_rubrics()}"
        )
    return path.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# Two-layer graph handle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TwoLayerGraph:
    """
    Holds the configuration for a two-layer tutor session.
    Passed to get_tutor_reply_two_layer() as the ``graph`` argument,
    mirroring the API of compiled LangGraph graphs used elsewhere.
    """

    system_prompt: str
    rubric_text: str
    provider: str


def create_two_layer_graph(
    system_prompt: str,
    rubric_text: str,
    *,
    provider: str = "gpt",
) -> TwoLayerGraph:
    """
    Build a TwoLayerGraph handle.

    Args:
        system_prompt: Fully-rendered tutor system prompt (with assignment injected).
        rubric_text:   Full rubric text — used by the verifier only; bottom layer
                       never sees it.
        provider:      ``"gpt"`` or ``"claude"`` — used for both layers.
    """
    return TwoLayerGraph(
        system_prompt=system_prompt,
        rubric_text=rubric_text,
        provider=provider,
    )


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


def _build_verifier_prompt(student_facing_text: str, rubric_text: str) -> str:
    return f"""You are reviewing a Socratic tutor's response before it is shown to a student.

<Rubric>
{rubric_text}
</Rubric>

<TutorResponse>
{student_facing_text}
</TutorResponse>

Review the tutor's response against the rubric. Decide whether it is good enough to send to the student as-is, or whether it needs revision.

Return JSON only — no markdown, no preamble:
{{
  "approved": true,
  "feedback": ""
}}

- If approved: set "approved" to true, leave "feedback" empty.
- If not approved: set "approved" to false and write a brief, actionable critique in "feedback". Do NOT reference rubric criterion IDs — write plain feedback the tutor can act on directly."""


def _parse_verifier_response(text: str) -> tuple[bool, str]:
    """Parse verifier output. Returns (approved, feedback). Defaults to approved on parse failure."""
    for candidate in (text.strip(), extract_json_object(text)):
        if candidate is None:
            continue
        try:
            data = json.loads(candidate)
            approved = data.get("approved")
            feedback = str(data.get("feedback") or "").strip()
            if not isinstance(approved, bool):
                coerced = str(approved).lower().strip()
                if coerced in ("true", "1", "yes"):
                    approved = True
                elif coerced in ("false", "0", "no"):
                    approved = False
                else:
                    continue
            return approved, feedback
        except (json.JSONDecodeError, TypeError):
            continue
    # On parse failure, approve to avoid blocking the student.
    return True, ""


def _call_verifier(
    student_facing_text: str,
    rubric_text: str,
    provider: str,
) -> tuple[bool, str]:
    """
    Call the verifier LLM. Returns (approved, feedback).

    The verifier sees only the student-facing tutor text and the rubric.
    Pedagogical reasoning is not passed — the verifier judges what the student sees.
    """
    from langchain_core.messages import HumanMessage, SystemMessage  # pyright: ignore[reportMissingImports]

    if provider == "claude":
        from langchain_anthropic import ChatAnthropic  # pyright: ignore[reportMissingImports]

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required.")
        model = ChatAnthropic(
            model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_CLAUDE_MODEL),
            api_key=api_key,
        )
    else:
        from langchain_openai import ChatOpenAI  # pyright: ignore[reportMissingImports]

        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required.")
        model = ChatOpenAI(
            model=os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            api_key=api_key,
        )

    system = SystemMessage(
        content="You are a pedagogical reviewer. Evaluate tutor responses and return a JSON verdict."
    )
    human = HumanMessage(content=_build_verifier_prompt(student_facing_text, rubric_text))
    response = model.invoke([system, human])
    content = response.content if isinstance(response.content, str) else str(response.content)
    return _parse_verifier_response(content)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_tutor_reply_two_layer(
    messages: list,
    *,
    graph: TwoLayerGraph,
) -> tuple[list, str, dict]:
    """
    Run one tutor turn through the two-layer pipeline.

    Flow:
      1. Bottom layer generates a draft reply.
      2. Verifier reviews the student-facing text against the rubric.
      3a. Approved → commit draft to history, return.
      3b. Rejected → inject feedback into system prompt, bottom layer retries once,
          commit revised reply to history, return regardless of verifier opinion.

    The draft is never committed to ``messages`` — only the final reply is appended.

    Args:
        messages: Conversation history ending with HumanMessage(student_text).
        graph:    TwoLayerGraph handle from create_two_layer_graph().

    Returns:
        (updated_messages, student_facing_text, verifier_info)

        verifier_info keys:
          "retried"  — bool, whether a retry happened
          "feedback" — str | None, the rejection reason (None if approved first pass)
    """
    # --- Step 1: bottom layer draft ---
    tutor_graph = create_tutor_graph(graph.system_prompt, provider=graph.provider)
    draft_messages, draft_student_text = get_tutor_reply(messages, graph=tutor_graph)

    # Extract student-facing text from the draft AIMessage for the verifier.
    # (parse_tutor_response already ran inside get_tutor_reply, but we need the text here.)
    from langchain_core.messages import AIMessage  # pyright: ignore[reportMissingImports]

    last_draft = draft_messages[-1] if draft_messages else None
    if isinstance(last_draft, AIMessage):
        raw = last_draft.content if isinstance(last_draft.content, str) else str(last_draft.content)
        _, verifier_input_text = parse_tutor_response(raw)
        verifier_input_text = verifier_input_text or draft_student_text
    else:
        verifier_input_text = draft_student_text

    # --- Step 2: verifier ---
    approved, feedback = _call_verifier(
        student_facing_text=verifier_input_text,
        rubric_text=graph.rubric_text,
        provider=graph.provider,
    )

    if approved:
        return draft_messages, draft_student_text, {"retried": False, "feedback": None}

    # --- Step 3: retry with feedback injected ---
    reviewer_note = _REVIEWER_NOTE_TEMPLATE.format(feedback=feedback)
    retry_system_prompt = graph.system_prompt + reviewer_note
    retry_graph = create_tutor_graph(retry_system_prompt, provider=graph.provider)

    # Pass ORIGINAL messages so the draft is not in the retry's history.
    retry_messages, retry_student_text = get_tutor_reply(messages, graph=retry_graph)

    return retry_messages, retry_student_text, {"retried": True, "feedback": feedback}

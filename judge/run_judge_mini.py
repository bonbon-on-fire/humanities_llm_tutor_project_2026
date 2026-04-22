"""
Comparison-based mini judge: given one exchange (student message + original tutor reply +
new tutor reply), returns a binary verdict on whether the new tutor response is better,
with a one-sentence reason.

Used by ui.run_ui_judge_mini for sanity-checking tutor prompt changes.
No rubric scoring — purely comparative.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env")

from utils.parsing import extract_json_object  # noqa: E402

RUBRICS_DIR = _REPO_ROOT / "judge" / "rubrics"
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"

Provider = Literal["gpt", "claude"]


class MiniJudgeError(RuntimeError):
    """Raised when the mini judge fails to produce a valid verdict."""


@dataclass(frozen=True)
class MiniJudgeResult:
    """Result of a single-turn comparison."""

    new_is_better: bool
    reason: str


def discover_rubrics() -> list[str]:
    """Return available rubric stems from judge/rubrics/."""
    if not RUBRICS_DIR.exists():
        return []
    return sorted(p.stem for p in RUBRICS_DIR.glob("rubric_*.md"))


def _load_rubric(rubric_name: str) -> str:
    path = RUBRICS_DIR / f"{rubric_name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Rubric '{rubric_name}' not found at {path}.\n"
            f"Available: {discover_rubrics()}"
        )
    return path.read_text(encoding="utf-8").strip()


def _build_comparison_prompt(
    student_message: str,
    original_tutor_reply: str,
    new_tutor_reply: str,
    rubric_text: str,
) -> str:
    return f"""You are evaluating two tutor responses to the same student message in a Socratic tutoring session for a humanities course.

Use the rubric below as the standard for what makes a good tutor response.

<Rubric>
{rubric_text}
</Rubric>

<StudentMessage>
{student_message}
</StudentMessage>

<OriginalTutorResponse>
{original_tutor_reply}
</OriginalTutorResponse>

<NewTutorResponse>
{new_tutor_reply}
</NewTutorResponse>

Compare the two tutor responses against the rubric. Decide whether the NEW response is better than the ORIGINAL.

Respond with valid JSON only — no markdown, no preamble:
{{
  "new_is_better": true,
  "reason": "One sentence explaining your decision."
}}"""


def _parse_verdict(text: str) -> MiniJudgeResult:
    """Extract and validate the judge's JSON verdict from raw model output."""
    for candidate in (text.strip(), extract_json_object(text)):
        if candidate is None:
            continue
        try:
            data = json.loads(candidate)
            new_is_better = data.get("new_is_better")
            reason = data.get("reason", "")
            if not isinstance(new_is_better, bool):
                coerced = str(new_is_better).lower().strip()
                if coerced in ("true", "1", "yes"):
                    new_is_better = True
                elif coerced in ("false", "0", "no"):
                    new_is_better = False
                else:
                    continue
            return MiniJudgeResult(
                new_is_better=new_is_better,
                reason=str(reason).strip() if reason else "",
            )
        except (json.JSONDecodeError, TypeError):
            continue
    raise MiniJudgeError(f"Mini judge returned unparseable output:\n{text[:500]}")


def compare_turn(
    *,
    student_message: str,
    original_tutor_reply: str,
    new_tutor_reply: str,
    rubric_name: str = "rubric_05",
    provider: Provider = "gpt",
) -> MiniJudgeResult:
    """
    Compare original vs new tutor reply for a single turn.

    Shows the judge: student message + both tutor replies + rubric.
    Returns a MiniJudgeResult with a binary verdict and one-sentence reason.
    """
    from langchain_core.messages import HumanMessage, SystemMessage  # pyright: ignore[reportMissingImports]

    rubric_text = _load_rubric(rubric_name)
    prompt = _build_comparison_prompt(
        student_message=student_message,
        original_tutor_reply=original_tutor_reply,
        new_tutor_reply=new_tutor_reply,
        rubric_text=rubric_text,
    )

    if provider == "claude":
        from langchain_anthropic import ChatAnthropic  # pyright: ignore[reportMissingImports]

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for Claude judge.")
        model = ChatAnthropic(
            model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_CLAUDE_MODEL),
            api_key=api_key,
        )
    else:
        from langchain_openai import ChatOpenAI  # pyright: ignore[reportMissingImports]

        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for GPT judge.")
        model = ChatOpenAI(
            model=os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            api_key=api_key,
        )

    system = SystemMessage(
        content="You are a pedagogical evaluator. Compare two tutor responses and return a JSON verdict."
    )
    human = HumanMessage(content=prompt)
    response = model.invoke([system, human])
    content = response.content if isinstance(response.content, str) else str(response.content)
    return _parse_verdict(content)

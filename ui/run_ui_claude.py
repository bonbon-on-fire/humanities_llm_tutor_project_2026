"""
Batch runner that scores raw transcripts with the Claude judge.

Input transcripts are read from:
    transcripts/{persona_type}/{persona_type}_raw/

Judged transcripts are written to:
    transcripts/{persona_type}/{persona_type}_claude/

Edit config lists in this file, then run:
    python -m ui.run_ui_claude
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from judge.run_judge_claude import JudgeError, judge_transcript
from students.run_student import list_personas

_REPO_ROOT = Path(__file__).resolve().parent.parent
_JUDGE_PROMPTS_DIR = _REPO_ROOT / "judge" / "prompts"
_JUDGE_RUBRICS_DIR = _REPO_ROOT / "judge" / "rubrics"
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

_RAW_SUBDIR_BY_PERSONA_TYPE: dict[str, str] = {
    "chaotic": "chaotic_raw",
    "chitchat": "chitchat_raw",
    "clueless": "clueless_raw",
}
_CLAUDE_SUBDIR_BY_PERSONA_TYPE: dict[str, str] = {
    "chaotic": "chaotic_claude",
    "chitchat": "chitchat_claude",
    "clueless": "clueless_claude",
}

# ---------------------------------------------------------------------------
# Batch config (edit these directly)
# ---------------------------------------------------------------------------

# Judge prompt/rubric versions.
JUDGE_PROMPTS: list[str] = ["judge_04"]
JUDGE_RUBRICS: list[str] = ["rubric_04"]

# Which student personas to process (from students/personas/*.txt, without extension).
STUDENT_PERSONAS: list[str] = ["chaotic_01", "chaotic_02", "chaotic_03", "chaotic_04", "chaotic_05", "chaotic_06"]

# Per persona type, list transcript stems from the *_raw folder.
# Use stem format without ".json" (example: "transcript_01").
# Empty list means "all transcript_*.json files in that raw folder".
RAW_TRANSCRIPTS: dict[str, list[str]] = {
    "chaotic": [],
    "chitchat": [],
    "clueless": [],
}


def _require_anthropic_api_key() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    raise RuntimeError("ANTHROPIC_API_KEY environment variable is required but not set.")


def _discover_stems(directory: Path, suffix: str) -> list[str]:
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob(f"*{suffix}"))


def _discover_judge_prompts() -> list[str]:
    return _discover_stems(_JUDGE_PROMPTS_DIR, ".txt")


def _discover_judge_rubrics() -> list[str]:
    return _discover_stems(_JUDGE_RUBRICS_DIR, ".md")


def _parse_persona_name(prompt_name: str) -> tuple[str, str]:
    match = re.match(r"^([a-zA-Z0-9]+)_(\d{2})$", prompt_name)
    if not match:
        raise ValueError(
            f"Persona '{prompt_name}' must use '<type>_<NN>' format (example: chaotic_01)."
        )
    return match.group(1), match.group(2)


def _normalize_transcript_stem(name: str) -> str:
    stem = (name or "").strip()
    if stem.endswith(".json"):
        stem = stem[:-5]
    if not stem:
        raise ValueError("Transcript name cannot be empty.")
    if "/" in stem or "\\" in stem:
        raise ValueError(
            f"Transcript '{name}' must be a file stem only (no directory separators)."
        )
    return stem


def _raw_dir_for(persona_type: str) -> Path:
    return _TRANSCRIPTS_DIR / persona_type / _RAW_SUBDIR_BY_PERSONA_TYPE[persona_type]


def _claude_dir_for(persona_type: str) -> Path:
    return _TRANSCRIPTS_DIR / persona_type / _CLAUDE_SUBDIR_BY_PERSONA_TYPE[persona_type]


def _discover_raw_transcript_stems(persona_type: str) -> list[str]:
    raw_dir = _raw_dir_for(persona_type)
    if not raw_dir.exists():
        return []
    stems: list[str] = []
    for path in sorted(raw_dir.glob("transcript_*.json")):
        stems.append(path.stem)
    return stems


def _validate_config() -> None:
    _require_anthropic_api_key()

    if not JUDGE_PROMPTS:
        raise ValueError("JUDGE_PROMPTS must contain at least one item.")
    if not JUDGE_RUBRICS:
        raise ValueError("JUDGE_RUBRICS must contain at least one item.")
    if not STUDENT_PERSONAS:
        raise ValueError("STUDENT_PERSONAS must contain at least one item.")

    available_prompts = set(_discover_judge_prompts())
    available_rubrics = set(_discover_judge_rubrics())
    available_personas = set(list_personas())

    for prompt in JUDGE_PROMPTS:
        if prompt not in available_prompts:
            raise ValueError(f"Unknown judge prompt: {prompt}")
    for rubric in JUDGE_RUBRICS:
        if rubric not in available_rubrics:
            raise ValueError(f"Unknown judge rubric: {rubric}")

    selected_types: set[str] = set()
    for persona in STUDENT_PERSONAS:
        if persona not in available_personas:
            raise ValueError(f"Unknown student persona: {persona}")
        persona_type, _ = _parse_persona_name(persona)
        if persona_type not in _RAW_SUBDIR_BY_PERSONA_TYPE:
            raise ValueError(f"Unsupported persona type: {persona_type}")
        selected_types.add(persona_type)

    for persona_type in selected_types:
        raw_dir = _raw_dir_for(persona_type)
        configured = RAW_TRANSCRIPTS.get(persona_type, [])
        if configured:
            for item in configured:
                stem = _normalize_transcript_stem(item)
                raw_path = raw_dir / f"{stem}.json"
                if not raw_path.exists():
                    raise ValueError(f"Raw transcript not found: {raw_path}")
        else:
            discovered = _discover_raw_transcript_stems(persona_type)
            if not discovered:
                raise ValueError(
                    f"No raw transcripts found for persona type '{persona_type}' in {raw_dir}"
                )


def _iter_persona_types() -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for persona in STUDENT_PERSONAS:
        persona_type, _ = _parse_persona_name(persona)
        if persona_type not in seen:
            seen.add(persona_type)
            ordered.append(persona_type)
    return ordered


def _selected_raw_stems(persona_type: str) -> list[str]:
    configured = RAW_TRANSCRIPTS.get(persona_type, [])
    if configured:
        return sorted({_normalize_transcript_stem(item) for item in configured})
    return _discover_raw_transcript_stems(persona_type)


def _copy_raw_to_claude_target(
    *,
    persona_type: str,
    source_stem: str,
    prompt_name: str,
    rubric_name: str,
) -> Path:
    source_path = _raw_dir_for(persona_type) / f"{source_stem}.json"
    target_dir = _claude_dir_for(persona_type)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_filename = f"{source_stem}__{prompt_name}__{rubric_name}.json"
    target_path = target_dir / target_filename
    shutil.copyfile(source_path, target_path)
    return target_path


def main() -> int:
    try:
        _validate_config()
    except (RuntimeError, ValueError) as error:
        print(str(error))
        return 1

    try:
        for persona_type in _iter_persona_types():
            stems = _selected_raw_stems(persona_type)
            for source_stem in stems:
                for prompt_name in JUDGE_PROMPTS:
                    for rubric_name in JUDGE_RUBRICS:
                        target_path = _copy_raw_to_claude_target(
                            persona_type=persona_type,
                            source_stem=source_stem,
                            prompt_name=prompt_name,
                            rubric_name=rubric_name,
                        )
                        relative_stem = str(
                            target_path.relative_to(_TRANSCRIPTS_DIR)
                        ).replace("\\", "/")
                        if relative_stem.endswith(".json"):
                            relative_stem = relative_stem[:-5]

                        result = judge_transcript(
                            relative_stem,
                            prompt_name=prompt_name,
                            rubric_name=rubric_name,
                        )
                        print(
                            "[Claude Judge] "
                            f"persona_type={persona_type} "
                            f"source={source_stem}.json "
                            f"prompt={prompt_name} "
                            f"rubric={rubric_name} "
                            f"score={result.total_score}/{result.max_score} "
                            f"saved={target_path.relative_to(_REPO_ROOT)}"
                        )
    except KeyboardInterrupt:
        print("\nClaude judging interrupted.")
        return 130
    except JudgeError as error:
        print(f"Judge failed: {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

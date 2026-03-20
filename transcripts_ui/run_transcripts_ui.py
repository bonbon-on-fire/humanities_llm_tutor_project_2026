"""
Transcripts UI - Flask app to navigate tutor transcripts with GPT/Claude grades.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from flask import Flask, jsonify, render_template

app = Flask(__name__, static_folder="static", template_folder="templates")

BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_transcripts_dir() -> Path:
    if os.environ.get("TRANSCRIPTS_DIR"):
        return Path(os.environ["TRANSCRIPTS_DIR"]).resolve()

    candidates = [
        BASE_DIR / "transcripts",
        Path.cwd() / "transcripts",
        Path.cwd().parent / "transcripts",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return BASE_DIR / "transcripts"


TRANSCRIPTS_DIR = _resolve_transcripts_dir()


def _discover_persona_bases() -> list[str]:
    if not TRANSCRIPTS_DIR.is_dir():
        return []

    personas: list[str] = []
    for persona_dir in sorted(p for p in TRANSCRIPTS_DIR.iterdir() if p.is_dir()):
        persona = persona_dir.name
        raw_dir = persona_dir / f"{persona}_raw"
        gpt_dir = persona_dir / f"{persona}_gpt"
        claude_dir = persona_dir / f"{persona}_claude"
        if raw_dir.is_dir() or gpt_dir.is_dir() or claude_dir.is_dir():
            personas.append(persona)
    return personas


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _grade_summary(data: dict | None) -> dict | None:
    if not data or "grade" not in data or not isinstance(data["grade"], dict):
        return None
    g = data["grade"]
    return {
        "total_score": g.get("total_score"),
        "max_score": g.get("max_score"),
        "total_base_score": g.get("total_base_score"),
        "max_base_score": g.get("max_base_score"),
        # New rubric style (malus)
        "total_malus": g.get("total_malus", 0),
        "max_malus": g.get("max_malus", 0),
        # Backward-compatible fields (bonus)
        "total_bonus": g.get("total_bonus", 0),
        "max_bonus": g.get("max_bonus", 0),
        "model": g.get("model"),
        "overview": g.get("overview", []),
        "sections": g.get("sections"),
    }


def _extract_display_number(stem: str) -> str:
    match = re.match(r"^transcript_(\d+)", stem)
    if not match:
        return stem
    return match.group(1)


def _stem_sort_key(stem: str) -> tuple[int, int, str]:
    match = re.match(r"^transcript_(\d+)", stem)
    if not match:
        return (1, 0, stem)
    return (0, int(match.group(1)), stem)


def _json_stems(path: Path) -> set[str]:
    if not path.is_dir():
        return set()
    return {f.stem for f in path.glob("*.json")}


def _transcript_path_for(*, persona: str, provider: str, stem: str) -> Path:
    return TRANSCRIPTS_DIR / persona / f"{persona}_{provider}" / f"{stem}.json"


def _counterpart_candidates(*, persona: str, provider: str, raw_stem: str) -> list[Path]:
    provider_dir = TRANSCRIPTS_DIR / persona / f"{persona}_{provider}"
    if not provider_dir.is_dir():
        return []

    out: list[Path] = []
    for path in provider_dir.glob("*.json"):
        stem = path.stem
        if stem == raw_stem or stem.startswith(f"{raw_stem}__"):
            out.append(path)
    return sorted(out, key=lambda p: p.name)


def _resolve_counterpart(*, persona: str, provider: str, raw_stem: str) -> tuple[Path | None, str | None]:
    candidates = _counterpart_candidates(persona=persona, provider=provider, raw_stem=raw_stem)
    if not candidates:
        return None, f"No {provider.upper()} counterpart found for `{raw_stem}`."
    if len(candidates) > 1:
        names = ", ".join(p.stem for p in candidates[:3])
        suffix = "..." if len(candidates) > 3 else ""
        return None, f"Multiple {provider.upper()} counterparts found for `{raw_stem}`: {names}{suffix}"
    return candidates[0], None


def _normalized_transcript_payload(data: dict) -> dict:
    return {
        k: v
        for k, v in data.items()
        if k not in ("grade", "judge_prompt", "judge_rubric")
    }


def _check_transcript_match(*, raw_data: dict, judged_data: dict, provider: str) -> str | None:
    raw_payload = _normalized_transcript_payload(raw_data)
    judged_payload = _normalized_transcript_payload(judged_data)
    if raw_payload != judged_payload:
        return (
            f"{provider.upper()} counterpart transcript content mismatch. "
            "Expected exact copy of raw transcript before grading."
        )
    return None


def _raw_stems_for_persona(persona: str) -> list[str]:
    raw_dir = TRANSCRIPTS_DIR / persona / f"{persona}_raw"
    return sorted(_json_stems(raw_dir), key=_stem_sort_key)


def _counterpart_result(*, persona: str, provider: str, raw_stem: str, raw_data: dict) -> tuple[dict | None, str | None]:
    counterpart_path, resolve_error = _resolve_counterpart(
        persona=persona,
        provider=provider,
        raw_stem=raw_stem,
    )
    if resolve_error:
        return None, resolve_error
    if counterpart_path is None:
        return None, f"{provider.upper()} counterpart is empty."

    judged_data = _load_json(counterpart_path)
    if not judged_data:
        return None, f"{provider.upper()} counterpart file exists but could not be read."

    match_error = _check_transcript_match(
        raw_data=raw_data,
        judged_data=judged_data,
        provider=provider,
    )
    if match_error:
        return None, match_error

    grade = _grade_summary(judged_data)
    if not grade:
        return None, f"{provider.upper()} counterpart exists but grade is missing."

    return grade, None


def list_transcripts() -> list[dict]:
    out: list[dict] = []
    for persona in _discover_persona_bases():
        for raw_stem in _raw_stems_for_persona(persona):
            raw_data = _load_json(_transcript_path_for(persona=persona, provider="raw", stem=raw_stem))
            if not raw_data:
                continue

            gpt_grade, gpt_error = _counterpart_result(
                persona=persona,
                provider="gpt",
                raw_stem=raw_stem,
                raw_data=raw_data,
            )
            claude_grade, claude_error = _counterpart_result(
                persona=persona,
                provider="claude",
                raw_stem=raw_stem,
                raw_data=raw_data,
            )
            meta = {k: v for k, v in raw_data.items() if k not in ("exchanges", "grade")}
            out.append(
                {
                    "persona": persona,
                    "number": raw_stem,
                    "display_number": _extract_display_number(raw_stem),
                    "metadata": meta,
                    "gpt_grade": gpt_grade,
                    "claude_grade": claude_grade,
                    "gpt_error": gpt_error,
                    "claude_error": claude_error,
                    "gpt_score": gpt_grade["total_score"] if gpt_grade else None,
                    "gpt_max": gpt_grade["max_score"] if gpt_grade else None,
                    "claude_score": claude_grade["total_score"] if claude_grade else None,
                    "claude_max": claude_grade["max_score"] if claude_grade else None,
                }
            )
    return out


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/transcripts")
def api_list_transcripts():
    return jsonify(list_transcripts())


@app.route("/api/transcripts/<persona>/<num>")
def api_get_transcript(persona: str, num: str):
    if persona not in _discover_persona_bases():
        return jsonify({"error": "Unknown persona"}), 404

    raw_data = _load_json(_transcript_path_for(persona=persona, provider="raw", stem=num))
    if not raw_data:
        return jsonify({"error": "Transcript not found"}), 404

    gpt_grade, gpt_error = _counterpart_result(
        persona=persona,
        provider="gpt",
        raw_stem=num,
        raw_data=raw_data,
    )
    claude_grade, claude_error = _counterpart_result(
        persona=persona,
        provider="claude",
        raw_stem=num,
        raw_data=raw_data,
    )

    return jsonify(
        {
            "persona": persona,
            "number": num,
            "display_number": _extract_display_number(num),
            "metadata": {k: v for k, v in raw_data.items() if k not in ("exchanges", "grade")},
            "exchanges": raw_data.get("exchanges", []),
            "grade_gpt": gpt_grade,
            "grade_claude": claude_grade,
            "gpt_error": gpt_error,
            "claude_error": claude_error,
        }
    )


@app.route("/transcript/<persona>/<num>")
def transcript_page(persona: str, num: str):
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001)

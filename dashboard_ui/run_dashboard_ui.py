"""
Dashboard UI - Flask app to browse transcript grading results.
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
    """Locate the transcripts directory: respects TRANSCRIPTS_DIR env var, then tries common repo-relative paths."""
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


def _discover_persona_groups() -> list[str]:
    """Return persona group names (e.g. chaotic, cooperative) found under TRANSCRIPTS_DIR."""
    if not TRANSCRIPTS_DIR.is_dir():
        return []

    groups: list[str] = []
    for persona_dir in sorted(p for p in TRANSCRIPTS_DIR.iterdir() if p.is_dir()):
        persona = persona_dir.name
        raw_dir = persona_dir / f"{persona}_raw"
        gpt_dir = persona_dir / f"{persona}_gpt"
        claude_dir = persona_dir / f"{persona}_claude"
        claude_v3_dir = persona_dir / f"{persona}_claude_v3"
        if raw_dir.is_dir() or gpt_dir.is_dir() or claude_dir.is_dir() or claude_v3_dir.is_dir():
            groups.append(persona)
    return groups


def _provider_label(provider: str) -> str:
    labels = {
        "claude": "CLAUDE",
        "claude_v3": "CLAUDE v3",
    }
    return labels.get(provider, provider.upper())


def _load_json(path: Path) -> dict | None:
    """Load and return a JSON object from path, or None on error or missing file."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _load_text(path: Path) -> str | None:
    """Read and return the text content of path, or None if missing or unreadable."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _grade_summary(data: dict | None) -> dict | None:
    """Extract a flat grade summary dict from a transcript data dict; returns None if no grade object present."""
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
    """Convert a file stem like transcript_07 to the display number string '7'."""
    match = re.match(r"^[^_]+_(\d+)", stem)
    if not match:
        return stem
    return str(int(match.group(1)))


def _stem_sort_key(stem: str) -> tuple[int, int, str]:
    """Sorting key for stems: numeric stems sort before non-numeric, numerically ascending."""
    match = re.match(r"^[^_]+_(\d+)", stem)
    if not match:
        return (1, 0, stem)
    return (0, int(match.group(1)), stem)


def _json_stems(path: Path) -> set[str]:
    """Return the set of JSON file stems (without extension) inside path."""
    if not path.is_dir():
        return set()
    return {f.stem for f in path.glob("*.json")}


def _txt_stems(path: Path) -> set[str]:
    """Return the set of .txt file stems (without extension) inside path."""
    if not path.is_dir():
        return set()
    return {f.stem for f in path.glob("*.txt")}


def _transcript_path_for(*, group: str, provider: str, stem: str) -> Path:
    """Construct the filesystem path for a transcript JSON file."""
    return TRANSCRIPTS_DIR / group / f"{group}_{provider}" / f"{stem}.json"


def _counterpart_candidates(*, group: str, provider: str, raw_stem: str) -> list[Path]:
    """Find all graded JSON files in the provider folder matching raw_stem (exact or suffixed)."""
    provider_dir = TRANSCRIPTS_DIR / group / f"{group}_{provider}"
    if not provider_dir.is_dir():
        return []

    def _is_ignored_variant(stem: str) -> bool:
        # Ignore alternate grading variants (e.g. ..._v2, ..._v3) when matching counterparts.
        return provider == "claude" and bool(re.search(r"_v[23]$", stem))

    out: list[Path] = []
    for path in provider_dir.glob("*.json"):
        stem = path.stem
        if _is_ignored_variant(stem):
            continue
        if stem == raw_stem or stem.startswith(f"{raw_stem}__"):
            out.append(path)
    return sorted(out, key=lambda p: p.name)


def _resolve_counterpart(*, group: str, provider: str, raw_stem: str) -> tuple[Path | None, str | None]:
    """Resolve exactly one graded counterpart for raw_stem; returns (path, None) or (None, error_message)."""
    candidates = _counterpart_candidates(group=group, provider=provider, raw_stem=raw_stem)
    provider_name = _provider_label(provider)
    if not candidates:
        return None, f"No {provider_name} counterpart found for `{raw_stem}`."
    if len(candidates) > 1:
        names = ", ".join(p.stem for p in candidates[:3])
        suffix = "..." if len(candidates) > 3 else ""
        return None, f"Multiple {provider_name} counterparts found for `{raw_stem}`: {names}{suffix}"
    return candidates[0], None


def _normalized_transcript_payload(data: dict) -> dict:
    """Return transcript data dict with grade-related keys stripped for content-equality checks."""
    return {
        k: v
        for k, v in data.items()
        if k not in ("grade", "judge_prompt", "judge_rubric")
    }


def _check_transcript_match(*, raw_data: dict, judged_data: dict, provider: str) -> str | None:
    """Return an error message if graded transcript content diverges from raw, else None."""
    raw_payload = _normalized_transcript_payload(raw_data)
    judged_payload = _normalized_transcript_payload(judged_data)
    if raw_payload != judged_payload:
        provider_name = _provider_label(provider)
        return (
            f"{provider_name} counterpart transcript content mismatch. "
            "Expected exact copy of raw transcript before grading."
        )
    return None


def _raw_stems_for_group(group: str) -> list[str]:
    """Return numerically sorted raw transcript stems for a persona group."""
    raw_dir = TRANSCRIPTS_DIR / group / f"{group}_raw"
    return sorted(_json_stems(raw_dir), key=_stem_sort_key)


def _counterpart_result(*, group: str, provider: str, raw_stem: str, raw_data: dict) -> tuple[dict | None, str | None]:
    """Load, validate, and summarise the graded counterpart for a raw transcript. Returns (grade_summary, error_message)."""
    counterpart_path, resolve_error = _resolve_counterpart(
        group=group,
        provider=provider,
        raw_stem=raw_stem,
    )
    provider_name = _provider_label(provider)
    if resolve_error:
        return None, resolve_error
    if counterpart_path is None:
        return None, f"{provider_name} counterpart is empty."

    judged_data = _load_json(counterpart_path)
    if not judged_data:
        return None, f"{provider_name} counterpart file exists but could not be read."

    match_error = _check_transcript_match(
        raw_data=raw_data,
        judged_data=judged_data,
        provider=provider,
    )
    if match_error:
        return None, match_error

    grade = _grade_summary(judged_data)
    if not grade:
        return None, f"{provider_name} counterpart exists but grade is missing."

    return grade, None


def _list_transcript_rows() -> list[dict]:
    """Build dashboard rows for all persona transcript runs (raw + Claude regular/v3 counterparts)."""
    out: list[dict] = []
    for group in _discover_persona_groups():
        for raw_stem in _raw_stems_for_group(group):
            raw_data = _load_json(_transcript_path_for(group=group, provider="raw", stem=raw_stem))
            if not raw_data:
                continue

            regular_grade, regular_error = _counterpart_result(
                group=group,
                provider="claude",
                raw_stem=raw_stem,
                raw_data=raw_data,
            )
            v3_grade, v3_error = _counterpart_result(
                group=group,
                provider="claude_v3",
                raw_stem=raw_stem,
                raw_data=raw_data,
            )
            meta = {k: v for k, v in raw_data.items() if k not in ("exchanges", "grade")}
            out.append(
                {
                    "kind": "transcript",
                    "group": group,
                    "version": _extract_display_number(raw_stem),
                    "route_group": group,
                    "route_version": raw_stem,
                    "metadata": meta,
                    "regular_grade": regular_grade,
                    "v3_grade": v3_grade,
                    "regular_error": regular_error,
                    "v3_error": v3_error,
                    "regular_score": regular_grade["total_score"] if regular_grade else None,
                    "regular_max": regular_grade["max_score"] if regular_grade else None,
                    "v3_score": v3_grade["total_score"] if v3_grade else None,
                    "v3_max": v3_grade["max_score"] if v3_grade else None,
                }
            )
    return out


def list_dashboard_rows() -> list[dict]:
    """Return dashboard rows for transcript runs only."""
    return _list_transcript_rows()


@app.route("/")
def index():
    """Serve the single-page application shell."""
    return render_template("index.html")


@app.route("/api/transcripts")
def api_list_transcripts():
    """Return all dashboard rows as a JSON array."""
    return jsonify(list_dashboard_rows())


@app.route("/api/transcripts/<group>/<version>")
def api_get_transcript(group: str, version: str):
    """Return full detail for one transcript run as JSON; 404 if not found."""
    if group not in _discover_persona_groups():
        return jsonify({"error": "Unknown group"}), 404

    raw_data = _load_json(_transcript_path_for(group=group, provider="raw", stem=version))
    if not raw_data:
        return jsonify({"error": "Transcript not found"}), 404

    regular_grade, regular_error = _counterpart_result(
        group=group,
        provider="claude",
        raw_stem=version,
        raw_data=raw_data,
    )
    v3_grade, v3_error = _counterpart_result(
        group=group,
        provider="claude_v3",
        raw_stem=version,
        raw_data=raw_data,
    )

    return jsonify(
        {
            "kind": "transcript",
            "group": group,
            "version": _extract_display_number(version),
            "route_group": group,
            "route_version": version,
            "metadata": {k: v for k, v in raw_data.items() if k not in ("exchanges", "grade")},
            "exchanges": raw_data.get("exchanges", []),
            "raw_text": None,
            "grade_regular": regular_grade,
            "grade_v3": v3_grade,
            "regular_error": regular_error,
            "v3_error": v3_error,
        }
    )


@app.route("/transcript/<group>/<version>")
def transcript_page(group: str, version: str):
    """Serve the SPA shell for a transcript detail URL; client-side routing handles the rest."""
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001)

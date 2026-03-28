"""
Dashboard UI - Flask app to browse transcript and batch grading results.
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


def _discover_persona_groups() -> list[str]:
    if not TRANSCRIPTS_DIR.is_dir():
        return []

    groups: list[str] = []
    for persona_dir in sorted(p for p in TRANSCRIPTS_DIR.iterdir() if p.is_dir()):
        persona = persona_dir.name
        raw_dir = persona_dir / f"{persona}_raw"
        gpt_dir = persona_dir / f"{persona}_gpt"
        claude_dir = persona_dir / f"{persona}_claude"
        if raw_dir.is_dir() or gpt_dir.is_dir() or claude_dir.is_dir():
            groups.append(persona)
    return groups


def _batch_raw_root() -> Path:
    return TRANSCRIPTS_DIR / "batches" / "batches_raw"


def _batch_provider_root(provider: str) -> Path:
    return TRANSCRIPTS_DIR / "batches" / f"batches_{provider}"


def _discover_batch_groups() -> list[str]:
    root = _batch_raw_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _load_text(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
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
    match = re.match(r"^[^_]+_(\d+)", stem)
    if not match:
        return stem
    return str(int(match.group(1)))


def _stem_sort_key(stem: str) -> tuple[int, int, str]:
    match = re.match(r"^[^_]+_(\d+)", stem)
    if not match:
        return (1, 0, stem)
    return (0, int(match.group(1)), stem)


def _json_stems(path: Path) -> set[str]:
    if not path.is_dir():
        return set()
    return {f.stem for f in path.glob("*.json")}


def _txt_stems(path: Path) -> set[str]:
    if not path.is_dir():
        return set()
    return {f.stem for f in path.glob("*.txt")}


def _transcript_path_for(*, group: str, provider: str, stem: str) -> Path:
    return TRANSCRIPTS_DIR / group / f"{group}_{provider}" / f"{stem}.json"


def _counterpart_candidates(*, group: str, provider: str, raw_stem: str) -> list[Path]:
    provider_dir = TRANSCRIPTS_DIR / group / f"{group}_{provider}"
    if not provider_dir.is_dir():
        return []

    out: list[Path] = []
    for path in provider_dir.glob("*.json"):
        stem = path.stem
        if stem == raw_stem or stem.startswith(f"{raw_stem}__"):
            out.append(path)
    return sorted(out, key=lambda p: p.name)


def _resolve_counterpart(*, group: str, provider: str, raw_stem: str) -> tuple[Path | None, str | None]:
    candidates = _counterpart_candidates(group=group, provider=provider, raw_stem=raw_stem)
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


def _raw_stems_for_group(group: str) -> list[str]:
    raw_dir = TRANSCRIPTS_DIR / group / f"{group}_raw"
    return sorted(_json_stems(raw_dir), key=_stem_sort_key)


def _counterpart_result(*, group: str, provider: str, raw_stem: str, raw_data: dict) -> tuple[dict | None, str | None]:
    counterpart_path, resolve_error = _resolve_counterpart(
        group=group,
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


def _parse_batch_sources(raw_text: str) -> list[str]:
    sources: list[str] = []
    for line in raw_text.splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        sources.append(item.replace("\\", "/"))
    return sources


def _batch_counterpart_path(*, provider: str, batch_group: str, batch_stem: str) -> Path:
    return _batch_provider_root(provider) / batch_group / f"{batch_stem}.json"


def _batch_counterpart_result(
    *,
    provider: str,
    batch_group: str,
    batch_stem: str,
    raw_sources: list[str],
) -> tuple[dict | None, str | None]:
    path = _batch_counterpart_path(
        provider=provider,
        batch_group=batch_group,
        batch_stem=batch_stem,
    )
    if not path.exists():
        return None, f"No {provider.upper()} counterpart found for `{batch_group}/{batch_stem}`."

    judged_data = _load_json(path)
    if not judged_data:
        return None, f"{provider.upper()} counterpart file exists but could not be read."

    judged_sources = [
        str(x).strip().replace("\\", "/")
        for x in judged_data.get("transcript_sources", [])
    ]
    if judged_sources and judged_sources != raw_sources:
        return None, (
            f"{provider.upper()} counterpart transcript_sources mismatch for "
            f"`{batch_group}/{batch_stem}`."
        )
    transcript_count = judged_data.get("transcript_count")
    if isinstance(transcript_count, int) and transcript_count != len(raw_sources):
        return None, (
            f"{provider.upper()} counterpart transcript_count mismatch for "
            f"`{batch_group}/{batch_stem}`."
        )

    grade = _grade_summary(judged_data)
    if not grade:
        return None, f"{provider.upper()} counterpart exists but grade is missing."
    return grade, None


def _batch_version_stems(batch_group: str) -> list[str]:
    raw_dir = _batch_raw_root() / batch_group
    return sorted(_txt_stems(raw_dir), key=_stem_sort_key)


def _batch_metadata(batch_group: str, raw_sources: list[str], gpt_grade: dict | None, claude_grade: dict | None) -> dict:
    return {
        "tutor_prompt": "batch",
        "student_persona": f"{len(raw_sources)} transcript(s)",
        "course": "varied",
        "exercise_number": "varied",
        "turns": len(raw_sources),
        "batch_transcript_count": len(raw_sources),
        "batch_has_gpt_grade": gpt_grade is not None,
        "batch_has_claude_grade": claude_grade is not None,
    }


def _list_transcript_rows() -> list[dict]:
    out: list[dict] = []
    for group in _discover_persona_groups():
        for raw_stem in _raw_stems_for_group(group):
            raw_data = _load_json(_transcript_path_for(group=group, provider="raw", stem=raw_stem))
            if not raw_data:
                continue

            gpt_grade, gpt_error = _counterpart_result(
                group=group,
                provider="gpt",
                raw_stem=raw_stem,
                raw_data=raw_data,
            )
            claude_grade, claude_error = _counterpart_result(
                group=group,
                provider="claude",
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


def _list_batch_rows() -> list[dict]:
    out: list[dict] = []
    for batch_group in _discover_batch_groups():
        raw_group_dir = _batch_raw_root() / batch_group
        for batch_stem in _batch_version_stems(batch_group):
            raw_path = raw_group_dir / f"{batch_stem}.txt"
            raw_text = _load_text(raw_path)
            if raw_text is None:
                continue
            raw_sources = _parse_batch_sources(raw_text)

            gpt_grade, gpt_error = _batch_counterpart_result(
                provider="gpt",
                batch_group=batch_group,
                batch_stem=batch_stem,
                raw_sources=raw_sources,
            )
            claude_grade, claude_error = _batch_counterpart_result(
                provider="claude",
                batch_group=batch_group,
                batch_stem=batch_stem,
                raw_sources=raw_sources,
            )
            out.append(
                {
                    "kind": "batch",
                    "group": batch_group,
                    "version": _extract_display_number(batch_stem),
                    "route_group": batch_group,
                    "route_version": batch_stem,
                    "metadata": _batch_metadata(
                        batch_group=batch_group,
                        raw_sources=raw_sources,
                        gpt_grade=gpt_grade,
                        claude_grade=claude_grade,
                    ),
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


def list_dashboard_rows() -> list[dict]:
    return _list_transcript_rows() + _list_batch_rows()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/transcripts")
def api_list_transcripts():
    return jsonify(list_dashboard_rows())


def _is_batch_group(group: str) -> bool:
    return group in _discover_batch_groups()


@app.route("/api/transcripts/<group>/<version>")
def api_get_transcript(group: str, version: str):
    if _is_batch_group(group):
        raw_text = _load_text(_batch_raw_root() / group / f"{version}.txt")
        if raw_text is None:
            return jsonify({"error": "Transcript not found"}), 404
        raw_sources = _parse_batch_sources(raw_text)
        gpt_grade, gpt_error = _batch_counterpart_result(
            provider="gpt",
            batch_group=group,
            batch_stem=version,
            raw_sources=raw_sources,
        )
        claude_grade, claude_error = _batch_counterpart_result(
            provider="claude",
            batch_group=group,
            batch_stem=version,
            raw_sources=raw_sources,
        )
        return jsonify(
            {
                "kind": "batch",
                "group": group,
                "version": _extract_display_number(version),
                "route_group": group,
                "route_version": version,
                "metadata": _batch_metadata(
                    batch_group=group,
                    raw_sources=raw_sources,
                    gpt_grade=gpt_grade,
                    claude_grade=claude_grade,
                ),
                "exchanges": [],
                "raw_text": raw_text,
                "grade_gpt": gpt_grade,
                "grade_claude": claude_grade,
                "gpt_error": gpt_error,
                "claude_error": claude_error,
            }
        )

    if group not in _discover_persona_groups():
        return jsonify({"error": "Unknown group"}), 404

    raw_data = _load_json(_transcript_path_for(group=group, provider="raw", stem=version))
    if not raw_data:
        return jsonify({"error": "Transcript not found"}), 404

    gpt_grade, gpt_error = _counterpart_result(
        group=group,
        provider="gpt",
        raw_stem=version,
        raw_data=raw_data,
    )
    claude_grade, claude_error = _counterpart_result(
        group=group,
        provider="claude",
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
            "grade_gpt": gpt_grade,
            "grade_claude": claude_grade,
            "gpt_error": gpt_error,
            "claude_error": claude_error,
        }
    )


@app.route("/transcript/<group>/<version>")
def transcript_page(group: str, version: str):
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001)

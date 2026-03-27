"""
Build GPT vs Claude grading comparison charts.

Reads judged transcripts from:
    transcripts/<persona_type>/<persona_type>_gpt/transcript_*.json
    transcripts/<persona_type>/<persona_type>_claude/transcript_*.json
    transcripts/batches/batches_gpt/batch_01/*.json
    transcripts/batches/batches_claude/batch_01/*.json

Usage:
    python -m visualization.run_visualization
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GradeRow:
    tutor_prompt: str
    student_persona: str
    course: str
    exercise_number: str
    transcript_name: str
    total_score: float
    max_score: float
    section_scores: dict[str, float] = field(default_factory=dict)
    section_maxes: dict[str, float] = field(default_factory=dict)

    @property
    def persona_type(self) -> str:
        return (self.student_persona.split("_", 1)[0] or self.student_persona).strip()

    @property
    def transcript_key(self) -> str:
        return "|".join([
            self.student_persona,
            self.course,
            self.exercise_number,
            self.transcript_name,
        ])


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _parse_score(x: Any) -> float:
    try:
        return float(str(x or "").strip())
    except (TypeError, ValueError):
        return float("nan")


def _extract_section_scores(grade: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    scores: dict[str, float] = {}
    maxes: dict[str, float] = {}
    sections = grade.get("sections")
    if not isinstance(sections, dict):
        return scores, maxes
    for sid, section in sections.items():
        if not isinstance(section, dict):
            continue
        base = section.get("base")
        if not isinstance(base, dict):
            continue
        scores[sid] = _parse_score(base.get("score"))
        maxes[sid] = _parse_score(base.get("max"))
    return scores, maxes


def _read_judged_transcript(path: Path) -> GradeRow | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    grade = raw.get("grade")
    if not isinstance(grade, dict):
        return None

    section_scores, section_maxes = _extract_section_scores(grade)

    return GradeRow(
        tutor_prompt=str(raw.get("tutor_prompt", "")).strip(),
        student_persona=str(raw.get("student_persona", "")).strip(),
        course=str(raw.get("course", "")).strip(),
        exercise_number=str(raw.get("exercise_number", "")).strip(),
        transcript_name=path.stem.strip(),
        total_score=_parse_score(grade.get("total_score")),
        max_score=_parse_score(grade.get("max_score")),
        section_scores=section_scores,
        section_maxes=section_maxes,
    )


def _read_provider_rows(transcripts_dir: Path, provider_suffix: str) -> list[GradeRow]:
    rows: list[GradeRow] = []
    for path in sorted(transcripts_dir.glob(f"*/*_{provider_suffix}/transcript_*.json")):
        row = _read_judged_transcript(path)
        if row is not None:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _sort_key(row: GradeRow) -> tuple:
    tnum = int(row.transcript_name.split("_")[-1]) if "_" in row.transcript_name else 0
    ex_num = int(row.exercise_number) if row.exercise_number.isdigit() else 0
    return (row.persona_type, row.student_persona, row.course, ex_num, tnum)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    d = math.sqrt(vx * vy)
    return cov / d if d else None


def _avg_ranks(values: list[float]) -> list[float]:
    n = len(values)
    indexed = sorted(enumerate(values), key=lambda iv: iv[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg = ((i + 1) + (j + 1)) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return _pearson(_avg_ranks(xs), _avg_ranks(ys))


def _safe_import_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "matplotlib is required for visualization. "
            "Install with: python -m pip install matplotlib"
        ) from e
    return plt


# ---------------------------------------------------------------------------
# Batch data model and reading
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BatchGradeRow:
    batch_name: str
    total_score: float
    max_score: float
    transcript_sources: list[str]
    section_scores: dict[str, float] = field(default_factory=dict)
    section_maxes: dict[str, float] = field(default_factory=dict)


def _read_batch_grade(path: Path) -> BatchGradeRow | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    grade = raw.get("grade")
    if not isinstance(grade, dict):
        return None

    section_scores, section_maxes = _extract_section_scores(grade)

    sources = raw.get("transcript_sources")
    if not isinstance(sources, list):
        sources = []

    return BatchGradeRow(
        batch_name=path.stem.strip(),
        total_score=_parse_score(grade.get("total_score")),
        max_score=_parse_score(grade.get("max_score")),
        transcript_sources=[str(s) for s in sources],
        section_scores=section_scores,
        section_maxes=section_maxes,
    )


def _read_batch_rows(batches_dir: Path, provider: str, batch_type: str) -> list[BatchGradeRow]:
    provider_dir = batches_dir / f"batches_{provider}" / f"batch_{batch_type}"
    if not provider_dir.exists():
        return []
    rows: list[BatchGradeRow] = []
    for path in sorted(provider_dir.glob("batch_*.json")):
        row = _read_batch_grade(path)
        if row is not None:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Chart: Line chart — individual transcript scores
# ---------------------------------------------------------------------------

def _chart_line_scores(
    gpt_rows: list[GradeRow],
    claude_rows: list[GradeRow],
    out_dir: Path,
) -> None:
    plt = _safe_import_matplotlib()

    gpt_by_key = {r.transcript_key: r for r in gpt_rows}
    claude_by_key = {r.transcript_key: r for r in claude_rows}
    all_keys = sorted(
        set(gpt_by_key) | set(claude_by_key),
        key=lambda k: _sort_key(gpt_by_key.get(k) or claude_by_key[k]),
    )

    x = list(range(len(all_keys)))
    y_gpt = [gpt_by_key[k].total_score if k in gpt_by_key else float("nan") for k in all_keys]
    y_claude = [claude_by_key[k].total_score if k in claude_by_key else float("nan") for k in all_keys]

    paired_g, paired_c = [], []
    for k in all_keys:
        g, c = gpt_by_key.get(k), claude_by_key.get(k)
        if g and c and math.isfinite(g.total_score) and math.isfinite(c.total_score):
            paired_g.append(g.total_score)
            paired_c.append(c.total_score)

    fig, ax = plt.subplots(figsize=(16, 7))
    ax.plot(x, y_gpt, label="GPT", color="#a65dea", linewidth=1.4, marker="o", markersize=2.5)
    ax.plot(x, y_claude, label="Claude", color="#ff893a", linewidth=1.4, marker="o", markersize=2.5)
    ax.set_title("Total Score Per Transcript: GPT vs Claude")
    ax.set_xlabel("Transcript index (sorted by persona / course / exercise)")
    ax.set_ylabel("Total Score")
    ax.grid(True, alpha=0.3)
    ax.legend()

    pearson_v = _pearson(paired_g, paired_c)
    spearman_v = _spearman(paired_g, paired_c)
    lines = []
    lines.append(f"Pearson r = {pearson_v:.3f}" if pearson_v is not None else "Pearson r = N/A")
    lines.append(f"Spearman ρ = {spearman_v:.3f}" if spearman_v is not None else "Spearman ρ = N/A")
    lines.append(f"Paired transcripts: {len(paired_g)}")
    if paired_g:
        lines.append(f"GPT mean: {sum(paired_g)/len(paired_g):.1f}   Claude mean: {sum(paired_c)/len(paired_c):.1f}")
    ax.text(
        0.01, 0.98, "\n".join(lines), transform=ax.transAxes, ha="left", va="top",
        fontsize=9, bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#ccc"},
    )

    fig.tight_layout()
    fig.savefig(out_dir / "individual_grades_gpt_vs_claude.png", dpi=150)
    plt.close(fig)
    print(f"  [1] individual_grades_gpt_vs_claude.png")


# ---------------------------------------------------------------------------
# Chart: Line chart — batch_01 scores
# ---------------------------------------------------------------------------

def _chart_batch_scores(
    gpt_rows: list[BatchGradeRow],
    claude_rows: list[BatchGradeRow],
    batch_type: str,
    out_dir: Path,
    *,
    chart_idx: int = 2,
) -> None:
    plt = _safe_import_matplotlib()

    gpt_by_name = {r.batch_name: r for r in gpt_rows}
    claude_by_name = {r.batch_name: r for r in claude_rows}

    def _batch_sort_key(name: str) -> int:
        parts = name.split("_")
        try:
            return int(parts[-1])
        except (ValueError, IndexError):
            return 0

    all_names = sorted(
        set(gpt_by_name) | set(claude_by_name),
        key=_batch_sort_key,
    )

    x = list(range(len(all_names)))
    y_gpt = [gpt_by_name[n].total_score if n in gpt_by_name else float("nan") for n in all_names]
    y_claude = [claude_by_name[n].total_score if n in claude_by_name else float("nan") for n in all_names]

    paired_g, paired_c = [], []
    for n in all_names:
        g, c = gpt_by_name.get(n), claude_by_name.get(n)
        if g and c and math.isfinite(g.total_score) and math.isfinite(c.total_score):
            paired_g.append(g.total_score)
            paired_c.append(c.total_score)

    fig, ax = plt.subplots(figsize=(16, 7))
    ax.plot(x, y_gpt, label="GPT", color="#a65dea", linewidth=1.4, marker="o", markersize=3)
    ax.plot(x, y_claude, label="Claude", color="#ff893a", linewidth=1.4, marker="o", markersize=3)
    ax.set_title(f"Batch Type {batch_type} — Total Score Per Batch: GPT vs Claude")
    ax.set_xlabel(f"Batch index (batch_001 – batch_{len(all_names):03d})")
    ax.set_ylabel("Total Score")
    ax.grid(True, alpha=0.3)
    ax.legend()

    pearson_v = _pearson(paired_g, paired_c)
    spearman_v = _spearman(paired_g, paired_c)
    lines = []
    lines.append(f"Pearson r = {pearson_v:.3f}" if pearson_v is not None else "Pearson r = N/A")
    lines.append(f"Spearman ρ = {spearman_v:.3f}" if spearman_v is not None else "Spearman ρ = N/A")
    lines.append(f"Paired batches: {len(paired_g)}")
    if paired_g:
        lines.append(f"GPT mean: {sum(paired_g)/len(paired_g):.1f}   Claude mean: {sum(paired_c)/len(paired_c):.1f}")
    ax.text(
        0.01, 0.98, "\n".join(lines), transform=ax.transAxes, ha="left", va="top",
        fontsize=9, bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#ccc"},
    )

    fig.tight_layout()
    filename = f"batch_{batch_type}_grades_gpt_vs_claude.png"
    fig.savefig(out_dir / filename, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {filename}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    transcripts_dir = repo_root / "transcripts"
    batches_dir = transcripts_dir / "batches"
    out_dir = repo_root / "visualization" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    gpt_rows = _read_provider_rows(transcripts_dir, "gpt")
    claude_rows = _read_provider_rows(transcripts_dir, "claude")

    print(f"Loaded GPT: {len(gpt_rows)} transcripts   Claude: {len(claude_rows)} transcripts")

    if not gpt_rows and not claude_rows:
        print("No judged transcripts found. Run ui.run_ui_gpt / ui.run_ui_claude first.")
        return 1

    _chart_line_scores(gpt_rows, claude_rows, out_dir)

    chart_idx = 2
    for batch_type in ("01", "02", "03"):
        batch_gpt = _read_batch_rows(batches_dir, "gpt", batch_type)
        batch_claude = _read_batch_rows(batches_dir, "claude", batch_type)
        print(f"Loaded batch_{batch_type} GPT: {len(batch_gpt)} batches   Claude: {len(batch_claude)} batches")

        if batch_gpt or batch_claude:
            _chart_batch_scores(batch_gpt, batch_claude, batch_type, out_dir, chart_idx=chart_idx)
            chart_idx += 1
        else:
            print(f"  No batch_{batch_type} graded files found. Skipping batch chart.")

    print(f"\n[Done] Charts saved to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

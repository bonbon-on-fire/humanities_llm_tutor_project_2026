"""
Build visualization views from GPT vs Claude transcript grade CSVs.

Usage:
    python -m visualization.run_visualization
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeRow:
    # Source metadata copied from compiled transcript CSV rows.
    tutor_prompt: str
    student_persona: str
    course: str
    exercise_number: str
    judge_prompt: str
    judge_rubric: str
    transcript_name: str
    total_score: float
    max_score: float

    @property
    def persona_type(self) -> str:
        # chaotic_04 -> chaotic
        return (self.student_persona.split("_", 1)[0] or self.student_persona).strip()

    @property
    def exercise_label(self) -> str:
        return f"{self.course}:{self.exercise_number}"

    @property
    def transcript_key(self) -> str:
        # Key chosen to align the same run across model outputs.
        return "|".join(
            [
                self.student_persona,
                self.course,
                self.exercise_number,
                self.transcript_name,
            ]
        )


def _parse_score(x: str) -> float:
    try:
        return float((x or "").strip())
    except ValueError:
        return float("nan")


def _read_compiled_csv(path: Path) -> list[GradeRow]:
    # Uses csv.DictReader so multiline cells (overview/deductions) are handled safely.
    rows: list[GradeRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "tutor_prompt",
            "student_persona",
            "course",
            "exercise_number",
            "judge_prompt",
            "judge_rubric",
            "transcript_name",
            "total_score",
            "max_score",
        }
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise RuntimeError(f"Missing required CSV columns in {path}: {missing}")

        for row in reader:
            rows.append(
                GradeRow(
                    tutor_prompt=row["tutor_prompt"].strip(),
                    student_persona=row["student_persona"].strip(),
                    course=row["course"].strip(),
                    exercise_number=row["exercise_number"].strip(),
                    judge_prompt=row["judge_prompt"].strip(),
                    judge_rubric=row["judge_rubric"].strip(),
                    transcript_name=row["transcript_name"].strip(),
                    total_score=_parse_score(row["total_score"]),
                    max_score=_parse_score(row["max_score"]),
                )
            )
    return rows


def _sort_key(row: GradeRow) -> tuple:
    # Stable ordering across charts.
    tnum = int(row.transcript_name.split("_")[-1]) if "_" in row.transcript_name else 0
    ex_num = int(row.exercise_number) if row.exercise_number.isdigit() else 0
    return (row.persona_type, row.student_persona, row.course, ex_num, tnum)


def _safe_import_matplotlib():
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "matplotlib is required for visualization. "
            "Install with: python -m pip install matplotlib"
        ) from e
    return plt


def _line_chart_grades_per_transcript(
    *,
    gpt_rows: list[GradeRow],
    claude_rows: list[GradeRow],
    out_dir: Path,
) -> None:
    plt = _safe_import_matplotlib()

    # Align transcript series by composite key so lines are comparable.
    gpt_by_key = {r.transcript_key: r for r in gpt_rows}
    claude_by_key = {r.transcript_key: r for r in claude_rows}

    all_keys = sorted(set(gpt_by_key.keys()) | set(claude_by_key.keys()))
    all_keys = sorted(
        all_keys,
        key=lambda k: _sort_key(gpt_by_key.get(k) or claude_by_key[k]),
    )

    x = list(range(len(all_keys)))
    y_gpt = [gpt_by_key[k].total_score if k in gpt_by_key else float("nan") for k in all_keys]
    y_claude = [claude_by_key[k].total_score if k in claude_by_key else float("nan") for k in all_keys]

    fig, ax = plt.subplots(figsize=(16, 7))
    ax.plot(x, y_gpt, label="GPT", color="#a65dea", linewidth=1.8, marker="o", markersize=3)
    ax.plot(x, y_claude, label="Claude", color="#ff893a", linewidth=1.8, marker="o", markersize=3)
    ax.set_title("Grades Per Transcript: GPT vs Claude")
    ax.set_xlabel("Transcript Index (sorted by persona/course/exercise/transcript)")
    ax.set_ylabel("Total Score")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "grades_per_transcript_gpt_vs_claude.png", dpi=150)
    plt.close(fig)


def _avg(values: list[float]) -> float:
    valid = [v for v in values if v == v]  # filter NaN
    if not valid:
        return float("nan")
    return sum(valid) / len(valid)


def _line_chart_avg_by_persona_per_exercise(
    *,
    rows: list[GradeRow],
    model_label: str,
    out_path: Path,
) -> None:
    plt = _safe_import_matplotlib()

    # Fixed color map so persona colors stay consistent between GPT/Claude charts.
    persona_types = ("chaotic", "chitchat", "clueless")
    exercise_labels = sorted({r.exercise_label for r in rows})

    by_persona_ex: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        key = (r.persona_type, r.exercise_label)
        by_persona_ex.setdefault(key, []).append(r.total_score)

    x = list(range(len(exercise_labels)))
    color_map = {"chaotic": "#fb5c66", "chitchat": "#2bcbb9", "clueless": "#47aaf1"}

    fig, ax = plt.subplots(figsize=(14, 6))
    for p in persona_types:
        ys = [_avg(by_persona_ex.get((p, ex), [])) for ex in exercise_labels]
        ax.plot(
            x,
            ys,
            label=p,
            color=color_map[p],
            linewidth=2.0,
            marker="o",
            markersize=4,
        )

    ax.set_title(f"Average Grade by Persona Type per Exercise ({model_label})")
    ax.set_xlabel("Exercise (course:exercise)")
    ax.set_ylabel("Average Total Score")
    ax.set_xticks(x)
    ax.set_xticklabels(exercise_labels, rotation=45, ha="right")
    ax.grid(True, alpha=0.3)
    ax.legend(title="Persona")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    transcripts_dir = repo_root / "transcripts"
    gpt_csv = transcripts_dir / "transcripts_compiled.csv"
    claude_csv = transcripts_dir / "transcripts_compiled_claude.csv"
    out_dir = repo_root / "visualization" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    gpt_rows = _read_compiled_csv(gpt_csv)
    claude_rows = _read_compiled_csv(claude_csv)

    _line_chart_grades_per_transcript(
        gpt_rows=gpt_rows,
        claude_rows=claude_rows,
        out_dir=out_dir,
    )
    _line_chart_avg_by_persona_per_exercise(
        rows=gpt_rows,
        model_label="GPT",
        out_path=out_dir / "avg_grade_by_persona_per_exercise_gpt.png",
    )
    _line_chart_avg_by_persona_per_exercise(
        rows=claude_rows,
        model_label="Claude",
        out_path=out_dir / "avg_grade_by_persona_per_exercise_claude.png",
    )
    print(f"[Done] Wrote visualizations to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

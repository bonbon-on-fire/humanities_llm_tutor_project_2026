# Visualization

Generate score comparison charts for GPT vs Claude transcript grading.

## Inputs

Reads judged transcript JSON files from:

- `transcripts/<persona_type>/<persona_type>_gpt/transcript_*.json`
- `transcripts/<persona_type>/<persona_type>_claude/transcript_*.json`
- `transcripts/batches/batches_gpt/batch_XX/batch_*.json`
- `transcripts/batches/batches_claude/batch_XX/batch_*.json`

## Run

```powershell
python -m visualization.run_visualization
```

## Outputs

Written to `visualization/outputs/`:

| # | File | Description |
|---|------|-------------|
| 1 | `individual_grades_gpt_vs_claude.png` | Line chart of total scores per transcript (individual judging), sorted by persona/course/exercise. |
| 2 | `batch_01_grades_gpt_vs_claude.png` | Batch Type 01 (same persona + version + exercise) — 72 batches. |
| 3 | `batch_02_grades_gpt_vs_claude.png` | Batch Type 02 (same persona + version, different exercise) — 54 batches. |
| 4 | `batch_03_grades_gpt_vs_claude.png` | Batch Type 03 (different persona, same version + exercise) — 72 batches. |

All charts include Pearson r, Spearman rho, and mean scores.

## Alignment

Individual transcripts are matched across providers by composite key:
`student_persona | course | exercise_number | transcript_name`.

Batch files are matched by filename (e.g. `batch_001`).

Missing rows in either provider appear as gaps (NaN) in the line charts.

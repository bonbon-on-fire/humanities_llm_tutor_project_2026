# Visualization

Generate Claude transcript grading charts. Each run produces **all** configured outputs (no prompts or modes).

## Inputs

Reads judged transcript JSON files from:

- `transcripts/<persona_type>/<persona_type>_claude/transcript_*.json`

Paths follow the current repo layout: one folder per persona family (`chaotic`, `cooperative`, `clueless`, …) with a `*_claude` graded subfolder.

## Run

```powershell
python -m visualization.run_visualization
```

## Outputs

Written to `visualization/outputs/`:

| # | File | Description |
| - | ---- | ----------- |
| 1 | `claude_grades_all_transcripts.png` | Line chart of Claude **total score** per transcript, all personas combined (sorted by persona, course, exercise, transcript id). |
| 2+ | `claude_grades_<persona>_transcripts.png` | Same chart restricted to one persona family (e.g. `claude_grades_chaotic_transcripts.png`). One file per persona present in the data. |

Annotation box shows transcript count and mean score. Y-axis uses integer ticks.

## Sorting

Rows are ordered with the same key as other tooling: persona type, full student persona, course, exercise number, then transcript number.

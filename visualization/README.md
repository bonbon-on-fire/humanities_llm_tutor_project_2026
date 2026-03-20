# Visualization

Generate score visualizations comparing GPT and Claude transcript grading outputs.

## Inputs

The script reads:

- `transcripts/<persona_type>/<persona_type>_gpt/transcript_*.json` (GPT-judged runs)
- `transcripts/<persona_type>/<persona_type>_claude/transcript_*.json` (Claude-judged runs)

Required JSON fields:

- `tutor_prompt`
- `student_persona`
- `course`
- `exercise_number`
- `judge_prompt`
- `judge_rubric`
- `grade.total_score`
- `grade.max_score`

`transcript_name` is derived from each file name (for example, `transcript_01`).

## Run

From repo root:

```powershell
python -m visualization.run_visualization
```

If `matplotlib` is missing:

```powershell
python -m pip install matplotlib
```

## Outputs

Written to `visualization/outputs/`:

1. `grades_per_transcript_gpt_vs_claude.png`
   - Line chart of transcript-level total scores
   - GPT and Claude shown in different colors
   - Includes Pearson Correlation and Spearman Correlation computed on matched GPT/Claude transcript pairs

## Notes

- The script aligns GPT and Claude transcript lines by:
  - `student_persona`
  - `course`
  - `exercise_number`
  - `transcript_name`
- Missing rows in either provider folder are handled by leaving gaps (`NaN`) in the line chart.

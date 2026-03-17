# Visualization

Generate score visualizations comparing GPT and Claude transcript grading outputs.

## Inputs

The script reads:

- `transcripts/transcripts_compiled.csv` (GPT-judged runs)
- `transcripts/transcripts_compiled_claude.csv` (Claude-judged runs)

Required columns:

- `student_persona`
- `course`
- `exercise_number`
- `transcript_name`
- `total_score`
- `max_score`

## Run

From repo root:

```python
python -m visualization.run_visualization
```

If `matplotlib` is missing:

```python
python -m pip install matplotlib
```

## Outputs

Written to `visualization/outputs/`:

1. `grades_per_transcript_gpt_vs_claude.png`
   - Line chart of transcript-level total scores
   - GPT and Claude shown in different colors

2. `avg_grade_by_persona_per_exercise_gpt.png`
   - Average score per exercise for persona types (`chaotic`, `chitchat`, `clueless`)
   - One color per persona type

3. `avg_grade_by_persona_per_exercise_claude.png`
   - Same view as above for Claude scores

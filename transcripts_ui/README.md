# Transcripts Dashboard

Flask app to browse raw tutor transcripts and compare GPT vs Claude grades.

## Run

From repo root in PowerShell:

```powershell
python -m flask --app transcripts_ui.run_transcripts_ui run -p 5001
```

Or:

```powershell
python -m transcripts_ui.run_transcripts_ui
```

Then open [http://127.0.0.1:5001](http://127.0.0.1:5001).

## Data source

- By default, the app reads from `transcripts/` in repo root.
- Override with env var `TRANSCRIPTS_DIR` if needed.
- Expected transcript inputs:
  - Raw source transcripts:
    - `transcripts/chaotic/chaotic_raw/*.json`
    - `transcripts/chitchat/chitchat_raw/*.json`
    - `transcripts/clueless/clueless_raw/*.json`
  - Judged counterparts:
  - `transcripts/chaotic/chaotic_gpt/*.json`
  - `transcripts/chaotic/chaotic_claude/*.json`
  - `transcripts/chitchat/chitchat_gpt/*.json`
  - `transcripts/chitchat/chitchat_claude/*.json`
  - `transcripts/clueless/clueless_gpt/*.json`
  - `transcripts/clueless/clueless_claude/*.json`

The app is raw-first:

- Dashboard rows are built from `*_raw` files.
- For each raw transcript (e.g. `transcript_09`), GPT/Claude counterparts are matched by stem:
  - exact: `transcript_09.json`
  - or judged suffix form: `transcript_09__<judge_prompt>__<judge_rubric>.json`
- If a counterpart is missing, ambiguous, unreadable, missing `grade`, or does not exactly match the raw transcript content (except judge fields), the evaluator section displays an explicit error message.

## Features

- Dashboard with GPT/Claude score distributions.
- Sortable transcript table with side-by-side total scores (`#` shows the raw transcript id, e.g. `transcript_31`).
- Transcript reader with metadata, exchanges, and both evaluator reports.

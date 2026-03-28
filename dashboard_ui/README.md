# Transcripts Dashboard

Flask dashboard to browse transcript and batch results and compare GPT vs Claude grades.

## Run

From repo root in PowerShell:

```powershell
python -m flask --app dashboard_ui.run_dashboard_ui run -p 5001
```

Or:

```powershell
python -m dashboard_ui.run_dashboard_ui
```

Then open [http://127.0.0.1:5001](http://127.0.0.1:5001).

## Data source

- By default, the app reads from `transcripts/` in repo root.
- Override with env var `TRANSCRIPTS_DIR` if needed.
- Included row sources:
  - Persona raw transcripts in `transcripts/<group>/<group>_raw/*.json`
  - Batch raw files in `transcripts/batches/batches_raw/<group>/*.txt`
- Graded counterparts:
  - Persona: `.../<group>_gpt/*.json`, `.../<group>_claude/*.json`
  - Batch: `transcripts/batches/batches_gpt/<group>/*.json`, `transcripts/batches/batches_claude/<group>/*.json`

## Features

- Dashboard rows include both transcript runs and batch runs.
- Headers use `Group` and `Version`.
- Score panels show explicit errors when GPT/Claude counterparts are missing, unreadable, ambiguous, or mismatched.

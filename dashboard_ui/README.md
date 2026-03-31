# Transcripts Dashboard

Flask dashboard to browse transcript and bundle results and compare GPT vs Claude grades.

## Structure

```text
dashboard_ui/
  __init__.py              — package marker
  __main__.py              — entrypoint for python -m dashboard_ui
  run_dashboard_ui.py      — Flask app: routes, data loading, grade summaries
  static/
    app.js                 — frontend: routing, table rendering, chart drawing
  templates/
    index.html             — single-page app shell
```

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
  - Bundle raw files in `transcripts/bundles/bundles_raw/<group>/*.txt`
- Graded counterparts:
  - Persona: `.../<group>_gpt/*.json`, `.../<group>_claude/*.json`
  - Bundle: `transcripts/bundles/bundles_gpt/<group>/*.json`, `transcripts/bundles/bundles_claude/<group>/*.json`

## Features

- Dashboard rows include both transcript runs and bundle runs.
- Headers use `Group` and `Version`.
- Score panels show explicit errors when GPT/Claude counterparts are missing, unreadable, ambiguous, or mismatched.

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `TRANSCRIPTS_DIR` | No | Override path to transcripts root folder. Default: `transcripts/` in repo root. |

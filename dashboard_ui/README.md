# Transcripts Dashboard

Flask dashboard to browse transcript results and compare CLAUDE regular vs CLAUDE v3 grades.

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
- Graded counterparts:
  - `.../<group>_claude/*.json` (regular)
  - `.../<group>_claude_v3/*.json` (v3)

## Features

- Dashboard rows include transcript runs only (bundles are currently excluded).
- Headers use `Group` and `Version`.
- Score panels show explicit errors when CLAUDE regular/CLAUDE v3 counterparts are missing, unreadable, ambiguous, or mismatched.

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `TRANSCRIPTS_DIR` | No | Override path to transcripts root folder. Default: `transcripts/` in repo root. |

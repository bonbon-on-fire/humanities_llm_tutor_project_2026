# main_ui — Implementation Planning

Step-by-step build plan for `main_ui/`, the production-shape embeddable tutor app.

For the overall design (problem, decisions, schema, routes, identity flow, non-goals), see [Phase 8 of the main PLANNING.md](../PLANNING.md). This file tracks **how each step gets built**, in order.

---

## Step 1: Folder skeleton + Flask app + `python -m main_ui` boots ✦ ACTIVE

**Goal:** Create the minimal package structure and a Flask app that responds to a health check. No database, no chat, no templates yet — just confirm the package is importable, the server boots on port 5001, and `python -m main_ui` works end to end.

This is the foundation every other step builds on. Keep it tiny and obviously correct.

### Files to create

```text
main_ui/
  __init__.py           # empty package marker
  __main__.py           # python -m main_ui entry point
  run_app.py            # Flask app factory + health check route
  config.py             # env-driven config dataclass
  README.md             # quick start, env vars, comparison with web_ui
  PLANNING.md           # this file
```

No subfolders yet — `db/`, `routes/`, `services/`, `templates/`, `static/`, `uploads/`, `tests/` are added in later steps.

### File contents (sketch)

**`main_ui/__init__.py`** — empty file; marks the package.

**`main_ui/config.py`**

```python
"""Environment-driven configuration for main_ui."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    secret_key: str
    database_url: str
    port: int


def load_config() -> Config:
    secret_key = os.environ.get("MAIN_UI_SECRET_KEY", "dev-insecure-key")
    database_url = os.environ.get("DATABASE_URL", "sqlite:///./main_ui.db")
    port = int(os.environ.get("PORT", "5001"))
    return Config(secret_key=secret_key, database_url=database_url, port=port)
```

**`main_ui/run_app.py`**

```python
"""Flask app for the main_ui production-shape tutor."""
from flask import Flask, jsonify

from main_ui.config import load_config


def create_app() -> Flask:
    config = load_config()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "main_ui"})

    return app


app = create_app()
```

**`main_ui/__main__.py`**

```python
"""python -m main_ui entry point."""
from main_ui.config import load_config
from main_ui.run_app import app

if __name__ == "__main__":
    config = load_config()
    app.run(host="127.0.0.1", port=config.port, debug=True)
```

**`main_ui/README.md`** — short doc covering:
- Quick start: `python -m main_ui`
- Health-check URL: `http://127.0.0.1:5001/health`
- Env vars: `MAIN_UI_SECRET_KEY`, `DATABASE_URL`, `PORT`
- How `main_ui/` differs from `web_ui/` (link to Phase 8 comparison table)

### Dependencies

- **Flask** — already in the root `requirements.txt` (used by `web_ui/`). No new packages for Step 1.
- **Python 3.11+** (assumed; matches project baseline).

### Acceptance criteria

1. `python -m main_ui` boots and prints Flask's "Running on http://127.0.0.1:5001" banner.
2. `curl http://127.0.0.1:5001/health` returns HTTP 200 with body `{"status": "ok", "service": "main_ui"}`.
3. No port collision with `web_ui` (which uses port 5000).
4. No imports from `web_ui/`, `tutor/`, `students/`, or `judge/` yet — Step 1 stays fully self-contained.
5. `from main_ui.run_app import app` works from anywhere in the repo (for future gunicorn compatibility).
6. The Flask app uses the factory pattern (`create_app()`) so later steps can wire in DB session, blueprints, etc. without rewriting boot code.

### Verification steps

```powershell
# Boot the app
python -m main_ui

# In a second terminal, hit the health endpoint
curl http://127.0.0.1:5001/health

# Expected response:
# {"service":"main_ui","status":"ok"}

# Confirm no port conflict by also running web_ui (optional)
python -m web_ui    # binds to 5000
# Both apps should coexist
```

### What's deliberately NOT in Step 1

- No `db/` folder, no SQLAlchemy, no Postgres connection — that's Step 2
- No `/embed` route, no chat HTML, no static assets — Step 3+
- No tutor integration (`tutor.run_tutor`) — Step 4
- No `/api/chat` endpoint — Step 5
- No frontend code — Step 6
- No email modal, identity, or cookies — Step 7
- No history sidebar — Step 8
- No image uploads — Step 9
- No `test_host.html` — Step 10
- No tests — Step 11

### Risks / gotchas

- **Port mismatch**: If `PORT` env var is set to something other than 5001 (e.g. by another tool), the app picks that up. Document the override behavior in the README so it's obvious.
- **Flask debug mode**: We're keeping `debug=True` for dev convenience. Document that production hosting (when it comes) must turn this off.
- **`SECRET_KEY`**: Defaults to `"dev-insecure-key"`. Fine for local dev. Note in README that production needs a real key.

---

## Future steps (just placeholders for now)

These will get fleshed out as we work through them. Each maps to the implementation order in [Phase 8 of the main PLANNING.md](../PLANNING.md).

### Step 2: Database schema + Alembic migrations + SQLAlchemy models

Add `main_ui/db/` with SQLAlchemy models for `Conversation`, `Message`, `UploadedImage`. Set up Alembic migrations. Get `alembic upgrade head` working against both SQLite (default) and Postgres (via Docker).

### Step 3: Session cookie management + `/api/whoami` + `/embed` route

Add the `tutor_session_id` cookie issuance on first load. Implement `GET /api/whoami` returning `{session_id, email?, conversation_id?}`. Add `GET /embed?course=&exercise=&tutor=` route that serves a placeholder HTML page.

### Step 4: Tutor bridge

Add `main_ui/services/tutor_bridge.py` that wraps `tutor.run_tutor.create_tutor_graph`. No HTTP route yet — just confirm we can build a tutor graph and get a reply programmatically from `main_ui/`.

### Step 5: `/api/chat` text-only

Implement `POST /api/chat` accepting `{text}`. Creates the conversation row on first message, persists student + tutor messages, returns `{tutor_reply, conversation_id, message_count}`. No images yet.

### Step 6: Frontend chat UI

Build `main_ui/templates/embed.html` + `main_ui/static/js/chat.js` + `main_ui/static/css/chat.css`. Render messages, send via fetch, basic styling. Vanilla JS only.

### Step 7: Email modal

Frontend counts user messages; after the 3rd one, show a modal asking for email. `POST /api/email` validates `@`+`.`, stores in DB, sets `tutor_email` cookie, backfills past anonymous conversations with the same `session_id`.

### Step 8: Conversation history

`GET /api/history` returns past conversations for the current email. `GET /api/conversation/<id>` returns full message log. Add collapsed sidebar UI in `embed.html`.

### Step 9: Image uploads

Switch `/api/chat` to `multipart/form-data`. Save uploads under `main_ui/uploads/`, record in `uploaded_images` table. Build multimodal HumanMessage via `utils/figures.py`. Forward to tutor. **Depends on Phase 6** of the main PLANNING.md being implemented.

### Step 10: Test iframe page

Build `main_ui/test_host.html` — a plain HTML page with multiple iframes at different widths pointing at different course/exercise combos. Local dev verification of the embed UX.

### Step 11: Tests + README + documentation

`main_ui/tests/test_routes.py` and `test_models.py`. Flesh out `main_ui/README.md` with the full local dev workflow. Document env vars, migrations, and the `test_host.html` workflow.

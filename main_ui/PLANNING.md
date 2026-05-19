# main_ui — Implementation Planning

Step-by-step build plan for `main_ui/`, the production-shape embeddable tutor app.

For the overall design (problem, decisions, schema, routes, identity flow, non-goals), see [Phase 8 of the main PLANNING.md](../PLANNING.md). This file tracks **how each step gets built**, in order.

---

## Step 1: Folder skeleton + Flask app + `python -m main_ui` boots ✦ COMPLETED

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

### Purpose of each file

**`main_ui/__init__.py`**
- **Purpose:** marks `main_ui/` as a Python package so it can be imported and run as `python -m main_ui`.
- **Owns:** nothing (empty file).
- **Used by:** Python's import machinery; every other file in the package.

**`main_ui/config.py`**
- **Purpose:** central place for environment-driven settings. Reads env vars once at startup and returns a frozen, type-checked config object the rest of the app uses.
- **Owns:** the `Config` shape — currently `secret_key`, `database_url`, `port`. New settings (Postgres pool size, upload limits, CSP origins, etc.) get added here in later steps.
- **Defaults:** dev-friendly fallbacks for every value so the app boots without an `.env` file (`dev-insecure-key`, local SQLite path, port 5001).
- **Why a dataclass:** explicit fields, type hints, immutable, easy to unit-test by constructing a `Config` directly.
- **Used by:** `run_app.py` (to set Flask's `SECRET_KEY`) and `__main__.py` (to choose the port). Later steps add DB engine creation in Step 2.

**`main_ui/run_app.py`**
- **Purpose:** Flask app factory. The single function `create_app()` builds and returns a configured Flask instance. Importing `app` at module level gives gunicorn (and tests, and any other importer) a ready-to-use WSGI object.
- **Owns:** Flask app construction, route registration, and any app-level middleware/teardown wiring.
- **In Step 1:** registers exactly one route — `GET /health` returning `{"status": "ok", "service": "main_ui"}`. Later steps add blueprints from `routes/`, DB session lifecycle, error handlers, CSP headers, etc.
- **Factory-pattern rationale:** keeps testing easy (each test can `create_app()` with a different config) and avoids module-import side effects beyond the single `app = create_app()` line.

**`main_ui/__main__.py`**
- **Purpose:** entry point for `python -m main_ui`. Boots Flask's development server on the configured port with debug mode enabled.
- **Owns:** nothing the app needs at runtime — it's just glue between the CLI invocation and the Flask app.
- **Not used in production:** the production path is `gunicorn main_ui.run_app:app`. This file exists purely for local dev convenience.
- **Why a separate file:** standard Python convention — `python -m <package>` looks for `<package>/__main__.py`. Keeps the boot command tiny.

**`main_ui/README.md`**
- **Purpose:** quick-reference doc for a developer who has never touched this folder before. Covers what `main_ui/` is, how to boot it, how to verify it's running, and how it differs from `web_ui/`.
- **Owns:** local dev quick-start (`python -m main_ui`), health-check URL, supported env vars (`MAIN_UI_SECRET_KEY`, `DATABASE_URL`, `PORT`), and a short comparison with `web_ui/` (with a link to the Phase 8 comparison table in the root `PLANNING.md`).
- **Grows over time:** later steps add sections for DB migrations (Step 2), iframe testing (Step 10), running tests (Step 11), etc.

**`main_ui/PLANNING.md`** *(this file)*
- **Purpose:** the implementation roadmap for `main_ui/`. The root `PLANNING.md` says *what* Phase 8 is and *why*; this file says *how* it gets built, step by step.
- **Owns:** the ordered step list, acceptance criteria for each step, and the running record of which step is active.
- **Lives inside `main_ui/`:** keeps build planning next to the code it describes, mirroring the pattern of `meeting_notes/` and `docs/` co-located with their context.

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

## Step 2: Database schema + Alembic migrations + SQLAlchemy models ✦ COMPLETED

**Verified on both SQLite and PostgreSQL 18.4** (native Windows install via winget — `PostgreSQL.PostgreSQL.16` pulled 18.4). The same migration script + env-var swap exercised both backends; tables, indexes, FK cascades, and CHECK constraint all present on both. Round-trip insert/cascade-delete and downgrade/upgrade reversibility confirmed against each.

**Implementation note:** `Message.id` and `UploadedImage.id` use `BigInteger().with_variant(Integer, "sqlite")` because SQLite only autoincrements columns typed exactly `INTEGER PRIMARY KEY`. The variant gives BIGINT on Postgres and INTEGER on SQLite, transparent to the ORM.

**Local dev workflow (verified):**
- SQLite: no env vars needed; defaults to `sqlite:///./main_ui.db`.
- Postgres: `$env:DATABASE_URL = "postgresql+psycopg://postgres:<password>@localhost:5432/tutor"` (the `tutor` database was created via `psql -U postgres -d postgres -c "CREATE DATABASE tutor"`).

**Goal:** Stand up the persistence layer. Define SQLAlchemy 2.x models for `Conversation`, `Message`, and `UploadedImage`. Wire Alembic so we can version the schema. Get `alembic upgrade head` working against both SQLite (the dev default, zero setup) and PostgreSQL (via Docker, mirrors production). No HTTP routes touch the DB yet — that's Step 3+.

This step makes the database real but doesn't connect it to the Flask app yet. Engine + session wiring into `run_app.py` happens in Step 3 when the first route actually needs to read/write.

#### Files to create

```text
main_ui/
  db/
    __init__.py                          # package marker; re-exports public API
    models.py                            # SQLAlchemy 2.x DeclarativeBase + 3 model classes
    session.py                           # engine + session factory built from config.database_url
    migrations/
      alembic.ini                        # Alembic configuration
      env.py                             # imports Base.metadata; reads DATABASE_URL at run time
      script.py.mako                     # Alembic's revision template
      versions/
        <hash>_initial_schema.py         # autogenerated first migration
```

Plus a small touch-up to the root `requirements.txt` to add the new deps.

#### Purpose of each file

**`main_ui/db/__init__.py`**
- **Purpose:** package marker and public API surface for the `db` subpackage. Re-exports `Base`, the three model classes (`Conversation`, `Message`, `UploadedImage`), and the session helpers (`engine`, `SessionLocal`, `get_session`).
- **Why a re-export hub:** callers write `from main_ui.db import Conversation` without caring about whether the class lives in `models.py` or somewhere else. Lets us split files later without breaking imports.

**`main_ui/db/models.py`**
- **Purpose:** the single source of truth for the database schema. Declares the SQLAlchemy 2.x `DeclarativeBase` and the three ORM classes that mirror the tables described in Phase 8 of the root `PLANNING.md`.
- **Owns:**
  - `Base` — declarative base shared by every model
  - `Conversation` — `id` (UUID, Python-generated), `session_id`, `email` (nullable), `course`, `exercise_number`, `tutor_prompt`, `started_at`, `last_active_at`
  - `Message` — `id` (BigInteger), `conversation_id` (FK → Conversation, cascade delete), `turn`, `role` (CHECK constraint: `'student'` or `'tutor'`), `content`, `pedagogical_reasoning` (nullable, only set for tutor rows), `created_at`
  - `UploadedImage` — `id` (BigInteger), `message_id` (FK → Message, cascade delete), `filename`, `mime_type`, `size_bytes`, `created_at`
- **Relationships:** `Conversation.messages` (one-to-many), `Message.uploaded_images` (one-to-many). Both with `cascade="all, delete-orphan"` so deleting a Conversation cleans up its messages and their images.
- **Indexes:** `email` and `session_id` on `conversations`; `conversation_id` on `messages`; `message_id` on `uploaded_images` (the last comes for free with the FK in Postgres but is explicit for SQLite).
- **Portable types:**
  - UUIDs use SQLAlchemy 2.x `Uuid(as_uuid=True)` — Postgres stores native UUID, SQLite stores TEXT, ORM exposes `uuid.UUID` either way.
  - Timestamps use `DateTime(timezone=True)` — Postgres uses TIMESTAMPTZ; SQLite has no timezone support but the ORM layer normalizes Python-side datetimes to UTC before writing.
  - UUID generation is Python-side (`default=uuid.uuid4`) so we don't depend on `gen_random_uuid()` (Postgres-only).

**`main_ui/db/session.py`**
- **Purpose:** build the SQLAlchemy engine and session factory from `config.database_url`. One place that knows how to connect to the DB.
- **Owns:**
  - `engine` — module-level singleton built lazily from `load_config().database_url`
  - `SessionLocal` — `sessionmaker` bound to the engine
  - `get_session()` — context manager that yields a session and commits/rolls-back on exit
- **Cross-driver handling:**
  - For SQLite URLs: passes `connect_args={"check_same_thread": False}` so the Flask dev server can share connections across request threads
  - For Postgres URLs (`postgresql+psycopg://...`): standard pooling, no special connect args
- **Not yet wired into Flask:** Step 3 imports `SessionLocal` from here when `/api/whoami` is added. Until then, this module is exercise-able only via Alembic and ad-hoc Python.

**`main_ui/db/migrations/alembic.ini`**
- **Purpose:** Alembic's main config file. Tells Alembic where to find `env.py`, the script template, and the `versions/` dir. Logging config also lives here.
- **Notable:** the `sqlalchemy.url` line is intentionally **empty** — `env.py` reads `DATABASE_URL` from the environment at run time instead of hardcoding it. This is what makes the same migration script work against SQLite and Postgres.
- **Invocation:** all migration commands point at this file explicitly — `alembic -c main_ui/db/migrations/alembic.ini upgrade head`.

**`main_ui/db/migrations/env.py`**
- **Purpose:** Alembic's environment script — the glue between Alembic and our SQLAlchemy models. Imports `Base.metadata` from `main_ui.db.models`, reads `DATABASE_URL` from the environment, and wires both into Alembic's context.
- **Owns:** the offline (SQL-script generation) and online (direct execution) Alembic modes. Both modes call `Base.metadata` as `target_metadata` so `alembic revision --autogenerate` can detect new/changed models.

**`main_ui/db/migrations/script.py.mako`**
- **Purpose:** Alembic's template file for new revision scripts. Used by `alembic revision`/`alembic revision --autogenerate`.
- **Owns:** nothing project-specific — usually copied verbatim from `alembic init`. We keep it untouched unless we want to customize the generated docstrings or imports.

**`main_ui/db/migrations/versions/<hash>_initial_schema.py`**
- **Purpose:** the first migration. Creates the three tables, their indexes, the FK constraints, and the CHECK constraint on `messages.role`.
- **Generated, then hand-reviewed:** we run `alembic revision --autogenerate -m "initial schema"`, then read the result top to bottom and fix anything autogen misses (autogenerate is good but not perfect — CHECK constraints and some index naming sometimes need manual touch-up).
- **Note on UUID columns:** verify the autogenerated `op.create_table(... sa.Uuid())` works on both backends. If not, drop in `sa.String(36)` with a converter at the ORM layer instead.

**Root `requirements.txt` additions**
- `sqlalchemy>=2.0` — the ORM
- `alembic` — schema migrations
- `psycopg[binary]>=3.1` — PostgreSQL driver. Used by Postgres backend; SQLite uses the stdlib `sqlite3` and needs no extra package.

#### Dependencies

- **SQLAlchemy 2.x** (uses 2.0 typed declarative style, not the legacy 1.x style)
- **Alembic** (pairs naturally with SQLAlchemy)
- **psycopg v3** (`psycopg[binary]`) — modern, async-capable Postgres driver; binary wheel avoids needing a system C compiler
- **Docker** (only when testing against Postgres locally) — `docker run --name tutor-postgres -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=tutor -p 5432:5432 -d postgres:16`

#### Cross-backend portability

This is the riskiest part of Step 2 because dev (SQLite) and production (Postgres) behave differently in subtle ways.

| Concern | SQLite behavior | Postgres behavior | How we handle it |
| --- | --- | --- | --- |
| UUID primary keys | Stored as TEXT | Native UUID | `sa.Uuid(as_uuid=True)` + Python-side `default=uuid.uuid4` |
| `BIGSERIAL` / autoincrement | `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGSERIAL` | `Mapped[int] = mapped_column(BigInteger, primary_key=True)` — SQLAlchemy emits the right thing per dialect |
| `TIMESTAMPTZ` | No timezone support (stores naive datetime) | Native | `DateTime(timezone=True)` + always write tz-aware datetimes in Python |
| `gen_random_uuid()` | Doesn't exist | Native | Generate UUIDs in Python, not in the DB default |
| CHECK constraints | Supported | Supported | Same definition works for both |
| Foreign-key cascade | Must enable per-connection (`PRAGMA foreign_keys=ON`) | On by default | Set `connect_args={"check_same_thread": False}` + listen for `connect` events to enable FK enforcement on SQLite |
| Connection pooling | Not relevant (single-file DB) | Real pooling needed | Default SQLAlchemy pool is fine for both at our scale |

#### Acceptance criteria

1. `from main_ui.db import Base, Conversation, Message, UploadedImage, SessionLocal, get_session` imports cleanly from any working directory.
2. `alembic -c main_ui/db/migrations/alembic.ini upgrade head` succeeds against the default SQLite URL (`sqlite:///./main_ui.db`) and produces a file with the three tables.
3. The same command succeeds against a Dockerized Postgres (`postgresql+psycopg://postgres:dev@localhost:5432/tutor`) — `DATABASE_URL` env var is the only thing that changes.
4. After `upgrade head`, all three tables exist with the correct columns, FK constraints, CHECK constraint on `messages.role`, and the four named indexes.
5. Round-trip test passes: insert a Conversation → insert a Message linked to it → insert an UploadedImage linked to the Message → query all three back → delete the Conversation → confirm cascade removed the Message and UploadedImage rows.
6. `alembic downgrade base` cleanly drops all three tables (round-trip reversibility — useful when iterating in dev).

#### Verification steps (manual)

1. Run `pip install -r requirements.txt` after adding the new deps.
2. Apply the migration against SQLite (no setup): `alembic -c main_ui/db/migrations/alembic.ini upgrade head`. Inspect `main_ui.db` with the SQLite browser of your choice (or `sqlite3 main_ui.db ".tables"`) and confirm three tables.
3. Start a Postgres container, switch `DATABASE_URL` to point at it, re-run the same upgrade command, and confirm the same tables exist (`psql ... -c "\dt"`).
4. Run a short ad-hoc Python session that imports the models, opens a session via `get_session()`, performs the round-trip insert/query/delete described in acceptance criterion 5.

#### What's deliberately NOT in Step 2

- **Flask integration of the engine/session lifecycle** — Step 3 adds `SessionLocal()` per-request handling once a route actually uses the DB.
- **`flask-sqlalchemy`** — we use plain SQLAlchemy 2.x; the Flask integration helper would be a separate concern and is not needed yet.
- **Model methods or business logic** — models are dumb data shapes here. Conversation create/append logic lives in `main_ui/services/conversation.py` later.
- **Per-conversation last-active-timestamp updates** — wired in Step 5 when chat actually mutates conversations.
- **Tests** — Step 11.
- **Production Postgres setup** — local Docker only; managed-DB provisioning is a later phase.

#### Risks / gotchas

- **Autogenerate quirks:** Alembic's `--autogenerate` doesn't always detect CHECK constraints or some index renames. Always read the generated migration top-to-bottom before committing it.
- **SQLite FK enforcement:** SQLite ships with FK enforcement *off* by default. If we don't enable it via a `PRAGMA foreign_keys=ON` listener in `session.py`, our cascade-delete tests will silently fail.
- **UUID display:** SQLite stores UUIDs as TEXT (hyphenated strings); Postgres stores them as native UUID. The ORM layer normalizes both to `uuid.UUID`, but raw `SELECT *` output looks different between the two — don't be alarmed.
- **Timezone confusion:** Python's `datetime.utcnow()` is timezone-*naive*. We must use `datetime.now(timezone.utc)` (or equivalent) so the values written are tz-aware and Postgres-friendly.
- **Migration script must be committed:** the generated `versions/<hash>_initial_schema.py` lives in git. Future devs running `alembic upgrade head` reuse it — don't regenerate it after the first commit.
- **`DATABASE_URL` precedence:** if a `.env` file or shell var sets `DATABASE_URL` to something unexpected, both the app and Alembic use it. Make this explicit in the README so a stale env var doesn't silently send dev writes to a different DB.

---

## Step 3: Session cookie management + `/api/whoami` + `/embed` route ✦ COMPLETED

**Verified locally** via curl + cookie-jar: cookie issuance on first load (all 6 attributes — `HttpOnly`, `SameSite=None`, `Secure`, `Partitioned`, `Max-Age=15552000`, `Path=/`), no re-issuance on subsequent calls, `/api/whoami` returns the same session id across calls, and all six 404 validation paths (missing/unknown course, missing/bad-format/unknown exercise, unknown tutor) return the expected JSON error body.

**Gotcha noted during verification:** .NET `HttpClient`'s default `CookieContainer` silently drops cookies with the `Partitioned` attribute, so PowerShell-side cookie tests appeared to fail. Curl with `-c`/`-b` works correctly. Worth knowing if anyone writes a Windows-native integration test against `main_ui` — use `requests` or `curl`, not `HttpClient`.

**Goal:** First user-visible touch point. Issue an anonymous `tutor_session_id` cookie on first arrival, expose it (and the other identity placeholders) via `GET /api/whoami`, and add a `GET /embed` route that validates its `course`/`exercise`/`tutor` query parameters and serves a minimal placeholder HTML page. The actual chat UI and DB writes come later (Steps 5–6); this step lays down the routing, identity, and validation skeleton.

This step deliberately does **not** touch the database. Cookies are self-contained: the session id lives in the cookie itself; no DB row is created until the first message lands (Step 5). DB wiring into Flask is deferred to Step 4 / Step 5 when a route actually reads or writes a row.

#### Files to create

```text
main_ui/
  cookies.py                          # cookie attribute helpers + session UUID generation
  routes/
    __init__.py                       # package marker
    embed.py                          # GET /embed (Blueprint: embed_bp)
    identity.py                       # GET /api/whoami (Blueprint: identity_bp)
  templates/
    embed.html                        # minimal placeholder page (real chat UI in Step 6)
```

Plus edits to existing files:
- `main_ui/run_app.py` — register the new blueprints, install `before_request` / `after_request` hooks for session-cookie issuance
- `main_ui/config.py` — add a cookie-settings group (cookie name, max-age, optional dev-mode override for `Secure`)

#### Purpose of each file

**`main_ui/cookies.py`**
- **Purpose:** single source of truth for cookie names, default attributes, and the UUID generator that mints new session ids. Routes never construct cookie attributes inline — they go through helpers here so the policy stays consistent.
- **Owns:** `SESSION_COOKIE_NAME = "tutor_session_id"`, `EMAIL_COOKIE_NAME = "tutor_email"` (used in Step 7 but defined here now to keep the policy in one place), a `new_session_id() -> str` helper, and a `default_cookie_kwargs()` helper returning the dict passed to Flask's `response.set_cookie(...)`.
- **Default attributes:** `HttpOnly=True`, `SameSite="None"`, `Secure=True`, `Partitioned=True`, `Max-Age=15552000` (180 days). All chosen for iframe / third-party cookie context per Phase 8 of the root `PLANNING.md`.
- **Dev escape hatch:** if `config.cookie_secure_override` is `False` (toggled via env), `Secure` is omitted so cookies work on plain `http://localhost` in browsers that don't treat localhost as a secure context. Default stays `True`.

**`main_ui/routes/__init__.py`**
- **Purpose:** package marker. Empty for now. Later steps may add a `register_all(app)` helper if blueprint registration grows beyond a few imports.

**`main_ui/routes/embed.py`**
- **Purpose:** owns `GET /embed`. Reads the `course`, `exercise`, and optional `tutor` query params, validates each against the filesystem, and renders `embed.html` with the validated values passed into the template context.
- **Validation rules:**
  - `course` — must match an existing subdirectory under `curriculum/` (no path traversal allowed; exact-name comparison only).
  - `exercise` — must match an existing file `curriculum/<course>/exercise_<NN>.txt` (zero-padded two-digit number).
  - `tutor` (optional) — must match a file `tutor/prompts/<tutor>.txt`. Defaults to `tutor_05` per the Phase 8 decision.
- **Errors:** any failed validation returns HTTP `404` with a small JSON body explaining which parameter was bad. We use 404 (not 400) because from a student's perspective the resource doesn't exist; surfacing input-shape errors as 400 leaks internal detail to embedders.
- **Owns:** the `embed_bp` Blueprint, the param-validation helpers (or imports them from a shared validator module if it grows), and nothing else.

**`main_ui/routes/identity.py`**
- **Purpose:** owns `GET /api/whoami`. Reads the current request's cookies and returns `{session_id, email, conversation_id}` as JSON. In Step 3 only `session_id` is ever populated; `email` is read from the `tutor_email` cookie (set in Step 7 — will be `null` until then); `conversation_id` is always `null` until Step 5 introduces conversations.
- **Owns:** the `identity_bp` Blueprint and a thin helper that maps the request's cookies to the response shape.
- **Why a separate file:** identity-related endpoints will grow (Step 7 adds `POST /api/email`, possible future endpoints for cookie clearing / logout). Putting them together keeps the responsibility focused.

**`main_ui/templates/embed.html`**
- **Purpose:** minimal placeholder page. Renders `<title>` from the course title, embeds the validated `course`, `exercise`, and `tutor` values as JSON in a `<script type="application/json" id="tutor-config">` block so the eventual `chat.js` can read them without re-parsing the URL, and shows a brief "Tutor loading..." message in `<body>`.
- **In Step 3:** no styling beyond basic readable defaults; no JS; no chat composer. It's just a confidence-check that the route works end-to-end and the cookie gets set.
- **Owns:** the future home of the chat scaffolding (Step 6), but for now it's intentionally bare.

**`main_ui/run_app.py` (modified)**
- **Adds:**
  - Import and registration of `embed_bp` and `identity_bp`
  - `@app.before_request` hook: reads the `tutor_session_id` cookie; if absent, generates a new UUID and stores it on `flask.g.session_id` (also flags `flask.g.session_id_is_new = True`)
  - `@app.after_request` hook: if `g.session_id_is_new`, sets the cookie on the outgoing response using `default_cookie_kwargs()` from `cookies.py`
- **Why hooks rather than per-route helper:** every route in `main_ui/` will need the session id (Steps 4–9 all depend on it). Centralizing the read/issue logic means individual route handlers never have to remember the cookie dance.

**`main_ui/config.py` (modified)**
- **Adds:**
  - `cookie_secure: bool` (default `True`) — read from `MAIN_UI_COOKIE_SECURE` env var; `False` for dev when testing without HTTPS on a browser that strictly enforces `Secure`
  - `cookie_max_age_seconds: int` (default 180 × 24 × 3600 ≈ 6 months) — env override via `MAIN_UI_COOKIE_MAX_AGE`
- **Why expose these:** they're policy that may need tuning between local dev, future production deployments, and tests. Keeping them in `Config` follows the existing pattern.

#### Cookie design summary

| Attribute | Value | Why |
| --- | --- | --- |
| `Name` | `tutor_session_id` | Anonymous per-browser identifier |
| `Value` | UUIDv4 | Cryptographically random, collision-resistant |
| `HttpOnly` | `True` | JS can't read it; defends against XSS leaking the session id |
| `SameSite` | `None` | Required for the cookie to be sent when `main_ui` is loaded inside an iframe on a different origin |
| `Secure` | `True` (dev override available) | Required by browsers whenever `SameSite=None` |
| `Partitioned` | `True` | CHIPS — cookie is partitioned by top-level site, the modern story for third-party cookies in Chrome/Edge |
| `Max-Age` | ~180 days | Long enough for a semester of OCW course usage |
| `Path` | `/` | Available to every route under `main_ui` |

#### URL parameter validation

`GET /embed` accepts three query params. Validation is whitelist-based: each value must match an existing on-disk artifact, not just a regex pattern. This prevents path-traversal attacks (`course=../../etc`) and also gives a meaningful 404 when a course is misspelled.

| Param | Required | Default | Validation |
| --- | --- | --- | --- |
| `course` | yes | — | Must be a direct child of `curriculum/` (directory, not file). Exact-name match. |
| `exercise` | yes | — | Must be a two-digit number (`01`-`99`) and `curriculum/<course>/exercise_<NN>.txt` must exist. |
| `tutor` | no | `tutor_05` | Must be a stem (e.g. `tutor_05`) and `tutor/prompts/<tutor>.txt` must exist. |

#### Dependencies

No new packages. Uses only `flask` (already installed) and Python stdlib (`uuid`, `pathlib`).

#### Acceptance criteria

1. **Blueprints register.** `python -m main_ui` boots and `GET /api/whoami` and `GET /embed?course=cities_and_climate_change&exercise=04` both return non-error responses.
2. **First-load cookie issuance.** A first request without any cookies receives a response with `Set-Cookie: tutor_session_id=<uuid>; ...` containing all the policy attributes (`HttpOnly`, `SameSite=None`, `Secure`, `Partitioned`, `Max-Age=15552000`).
3. **Cookie persistence.** A subsequent request that echoes the `tutor_session_id` cookie back receives **no** new `Set-Cookie` header for that name — the existing session id is reused.
4. **`/api/whoami` shape.** Returns JSON `{session_id, email, conversation_id}`. `session_id` is a valid UUID string; `email` is `null` (no `tutor_email` cookie set yet); `conversation_id` is `null`.
5. **`/embed` happy path.** A request with valid `course` and `exercise` (e.g. `cities_and_climate_change` + `04`) returns 200 with HTML whose `<script id="tutor-config">` contains the validated values.
6. **`/embed` validation failures.** Each of these returns 404 with a JSON body naming the bad param: missing `course`, unknown `course`, missing `exercise`, unknown `exercise` for the course, unknown `tutor`.
7. **`tutor` default.** A request that omits `tutor` is accepted; the rendered config shows `tutor_05`.
8. **`/health` still works.** The Step 1 endpoint continues to respond with `{"status": "ok", "service": "main_ui"}`.

#### Verification steps (manual)

1. `python -m main_ui` to boot.
2. Curl the embed happy path: `curl -i http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=04`. Confirm 200, HTML body, `Set-Cookie` header on first call.
3. Re-curl with the cookie echoed back: `curl -i --cookie "tutor_session_id=<uuid>" http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=04`. Confirm 200 and **no** new `Set-Cookie` for `tutor_session_id`.
4. Hit `/api/whoami` with the cookie: confirm JSON shape.
5. Hit each of the 404 cases (bad course, bad exercise, bad tutor) and confirm the JSON error body names the offending param.
6. Open `http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=04` in a real browser; open DevTools → Application → Cookies; confirm `tutor_session_id` is present with all the expected attributes.

#### What's deliberately NOT in Step 3

- **No database access** — no Conversation row created on `/embed` load. The first DB write happens when the student sends a message (Step 5).
- **No Flask ↔ SQLAlchemy session lifecycle** — `before_request` / `after_request` only manage the cookie. Step 4 or Step 5 will add per-request DB session handling when the first DB-touching route appears.
- **No real chat UI in `embed.html`** — only a "Tutor loading…" placeholder and the embedded config block. Real markup + composer in Step 6.
- **No email handling** — `EMAIL_COOKIE_NAME` is defined in `cookies.py` so Step 7 can use it, but the cookie is never read or written in Step 3.
- **No `/api/chat`** — Step 5.
- **No history sidebar / `/api/history`** — Step 8.
- **No tests** — Step 11.

#### Risks / gotchas

- **`Secure` on `http://localhost`:** Chrome treats localhost as a secure origin so `Secure` cookies work there. Firefox and Safari are stricter and may refuse to set them on plain HTTP. Mitigation: the `MAIN_UI_COOKIE_SECURE=false` override exists for cross-browser dev. Document this in the README and only flip it when actually debugging on a stricter browser.
- **`Partitioned` attribute compatibility:** the CHIPS attribute is Chrome 118+, Edge 118+, recent Firefox. Older browsers ignore unknown attributes harmlessly. No behavior change needed; just be aware that pre-118 Chrome will treat the cookie as a regular third-party cookie (potentially blocked by 3rd-party-cookie phase-out).
- **Path-traversal in `course`:** never `os.path.join` a user-supplied value with a base path without confirming the resulting path is still inside the base. The plan calls for exact-name matching against `os.listdir("curriculum/")` results, which sidesteps the issue.
- **`tutor` default drift:** hard-coding `tutor_05` as the default works today but will rot when `tutor_06` ships. Acceptable trade-off for Step 3; the alternative (scanning `tutor/prompts/` and picking max version) is a small follow-up that doesn't have to land now. Note it as a future cleanup.
- **Validation cost on every request:** `os.listdir("curriculum/")` runs on each `/embed` hit. At ~100-student traffic this is negligible. If traffic grows, cache the result with a TTL (or invalidate on file watcher events).
- **JSON injection into `<script id="tutor-config">`:** when embedding params into the HTML, use Jinja's `tojson` filter (auto-escapes for safe inclusion inside `<script type="application/json">`). Never concatenate user-supplied strings into the script block directly.

---

## Step 4: Tutor bridge ✦ COMPLETED

**Verified locally** with real OpenAI API call: single-turn smoke test (`history=[]` + new message) returned a Socratic reply referencing the actual exercise_04 content; multi-turn smoke test (history with 2 prior turns + "Boston" as the new student message) produced a coherent next-turn reply that acknowledged the chosen city and asked a more focused follow-up. Graph cache verified by checking object identity across repeat calls with the same `(tutor, course, exercise)` key.

**Implementation notes:**
- Reused upstream `tutor.run_tutor` API (`load_system_prompt`, `create_tutor_graph`, `parse_tutor_response`, and upstream `get_tutor_reply` imported under an aliased name to avoid colliding with our own).
- `build_assignment_text` reads `course.txt` (required-ish — falls through silently if absent), `syllabus.txt` (optional), and `exercise_<NN>.txt` (required). No `Run configuration` block since `main_ui` chats are open-ended.
- `.env` loading added to `main_ui/__init__.py` so `OPENAI_API_KEY` from the repo's `.env` is picked up automatically by every entrypoint without manual `$env:` setup.

**Goal:** Make `main_ui/` able to obtain a real tutor reply programmatically, by wrapping the existing `tutor.run_tutor` API in a thin bridge. No HTTP routes, no DB writes, no frontend changes — just confirm the wiring works end-to-end: feed in `(course, exercise, tutor, history, new_message)` from a Python REPL, get a tutor reply back, and we're confident Step 5 can plug it into `/api/chat`.

This step is the smallest possible "the LLM actually replies" milestone. It lets us catch wiring problems (missing env vars, import paths, message shape mismatches) before adding the complexity of conversation persistence in Step 5.

#### Files to create

```text
main_ui/
  services/
    __init__.py                       # package marker
    tutor_bridge.py                   # assignment-text builder + tutor-reply entry point
```

Plus a small edit to `main_ui/__init__.py` to auto-load `.env` at import time (so `OPENAI_API_KEY` from the project's `.env` file is available to every entrypoint without manual `$env:OPENAI_API_KEY` setup). Uses `python-dotenv` (already in `requirements.txt`). Other project modules (`tutor/`, `web_ui/`, `judge/`) deliberately don't load `.env` per Phase 2/5 cleanups — `main_ui/` reintroduces it at the package level, scoped only to this app.

#### Purpose of each file

**`main_ui/__init__.py` (modified)**
- **Adds:** a `dotenv.load_dotenv()` call at import time, pointing at the repo-root `.env`. Wrapped in a try/except for the case where `python-dotenv` is missing or the file doesn't exist — the app should still boot, just without auto-loaded env vars.
- **Why scoped to `main_ui/`:** other modules (`tutor`, `judge`, `students`, `web_ui`) deliberately don't load `.env` per the Phase 2/5 cleanups. We're not undoing that decision — we're carving a localized exception so `main_ui/` entrypoints (`python -m main_ui` and `python -c "from main_ui..."` smoke tests) don't require manual env setup.

**`main_ui/services/__init__.py`**
- **Purpose:** package marker. Empty file. Later steps may add a stable public API surface here once we have multiple services (`conversation.py`, `image_storage.py`).

**`main_ui/services/tutor_bridge.py`**
- **Purpose:** the one place in `main_ui/` that knows how to talk to `tutor.run_tutor`. Anything that needs a tutor reply (Step 5's `/api/chat`, future test scripts) calls this module — never the underlying `tutor.run_tutor` API directly.
- **Owns:**
  - `build_assignment_text(course, exercise) -> str` — concatenates `curriculum/<course>/course.txt`, optional `curriculum/<course>/syllabus.txt`, and `curriculum/<course>/exercise_<NN>.txt` into the assignment string the tutor's `<Assignment>` slot expects. Mirrors what `ui/run_ui_raw.py:_build_assignment_text` does but without the `turn_size` line (open-ended chat, no planned conversation length).
  - A module-level graph cache keyed by `(tutor, course, exercise)` so repeat calls don't rebuild the LangGraph.
  - `get_tutor_reply(*, course, exercise, tutor, history, new_student_message) -> dict` — the single public entry point.
  - Internal helpers for converting our simple message dicts (`{"role": "student"|"tutor", "content": str}`) to LangChain `HumanMessage` / `AIMessage` instances.
- **What it deliberately does NOT own:**
  - Conversation creation / DB writes — Step 5's `services/conversation.py`.
  - Cookie handling — Step 3's `cookies.py`.
  - Multimodal figure attachments — Phase 6 + Step 9.
  - Streaming — out of scope for the entire project until further notice.

#### API surface

```python
def build_assignment_text(course: str, exercise: str) -> str:
    """Build the assignment string for the tutor's <Assignment> slot."""

def get_tutor_reply(
    *,
    course: str,
    exercise: str,
    tutor: str,
    history: list[dict],          # each: {"role": "student"|"tutor", "content": str}
    new_student_message: str,
) -> dict:                         # {"reply": str, "reasoning": str | None}
    """Get one tutor reply given the conversation state and new student message."""
```

Keyword-only args on `get_tutor_reply` — there are 5 of them and they're easy to mix up positionally. The message-dict shape (`role`, `content`) matches the DB column names from Step 2 so Step 5 can pass query results in directly without remapping.

Return is a plain dict, not a dataclass — small surface, easy to JSON-serialize for Step 5's `/api/chat` response. Two keys:
- `reply` — the student-facing answer text the tutor produced
- `reasoning` — the tutor's internal `pedagogical-reasoning` (the JSON field that gets hidden from students; stored in DB for debugging and judge grading later)

#### Caching strategy

A module-level `dict[(tutor, course, exercise), CompiledStateGraph]` stores constructed graphs. Misses build via `load_system_prompt(tutor, assignment_override=build_assignment_text(...))` followed by `create_tutor_graph(system_prompt)`.

Cache lifetime = process lifetime. Restarting the Flask app drops the cache (acceptable for local dev). If curriculum files change mid-process, the cached graph stays stale until restart — surfaced as a known gotcha rather than a bug to fix now.

Not thread-safe (plain dict). Flask's dev server is single-threaded so this is fine; future production hosting with gunicorn workers needs a per-process cache anyway (same dict shape works because each worker is its own Python process).

#### Dependencies

- No new pip packages.
- Imports from existing project modules: `tutor.run_tutor` (`load_system_prompt`, `create_tutor_graph`, `get_tutor_reply` — the last one re-exported under a different local name to avoid colliding with our own function).
- Imports `HumanMessage` and `AIMessage` from `langchain_core.messages` (already a project dep).
- Requires `OPENAI_API_KEY` to be set — the existing tutor module fails fast if it isn't. The bridge inherits that behavior; no extra check needed.

#### Acceptance criteria

1. **Public API imports cleanly.** `from main_ui.services.tutor_bridge import get_tutor_reply, build_assignment_text` works from anywhere in the repo.
2. **Assignment text builds non-empty.** `build_assignment_text("cities_and_climate_change", "04")` returns a string containing both the course-level context (from `course.txt`) and the exercise text (from `exercise_04.txt`).
3. **First call succeeds.** `get_tutor_reply(course="cities_and_climate_change", exercise="04", tutor="tutor_05", history=[], new_student_message="I'm starting exercise 4. What should I do first?")` returns a dict with non-empty `reply`. The `reasoning` field is either a non-empty string or `None` (depending on whether the tutor's JSON parsed both fields).
4. **Reply respects tutor persona.** The reply is Socratic — asks a guiding question, does not deliver a direct answer. Qualitative check during smoke testing, not an assertion.
5. **Multi-turn coherence.** Calling again with a non-empty `history` list produces a continuing reply that references prior turns appropriately.
6. **Graph is cached.** A second call with the same `(tutor, course, exercise)` re-uses the cached graph. Verifiable by adding a temporary print or by inspecting the cache dict directly during testing.
7. **Existing routes unaffected.** `python -m main_ui` boots; `/health`, `/embed`, `/api/whoami` continue to respond per their Step 1-3 contracts.

#### Verification steps (manual)

```powershell
# 1. Ensure OPENAI_API_KEY is set
$env:OPENAI_API_KEY = "sk-..."

# 2. Smoke test from the repo root
python -c "from main_ui.services.tutor_bridge import build_assignment_text; print(build_assignment_text('cities_and_climate_change', '04')[:400])"

# 3. End-to-end tutor reply
python -c "from main_ui.services.tutor_bridge import get_tutor_reply; r = get_tutor_reply(course='cities_and_climate_change', exercise='04', tutor='tutor_05', history=[], new_student_message='I am starting exercise 4. Where do I begin?'); import json; print(json.dumps(r, indent=2))"

# 4. Multi-turn sanity check
python -c "from main_ui.services.tutor_bridge import get_tutor_reply; hist = [{'role':'student','content':'Hello'},{'role':'tutor','content':'Hi! What city are you studying?'}]; r = get_tutor_reply(course='cities_and_climate_change', exercise='04', tutor='tutor_05', history=hist, new_student_message='Boston.'); print(r['reply'])"

# 5. Confirm Flask still works
python -m main_ui
# In another shell:
curl http://127.0.0.1:5001/health
curl http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=04 | head -20
```

#### What's deliberately NOT in Step 4

- **No HTTP routes** — `/api/chat` is Step 5.
- **No DB writes** — `conversations` and `messages` tables remain empty.
- **No Flask integration of session lifecycle** — the bridge is plain Python; Flask wiring happens when Step 5 adds the chat route.
- **No frontend changes** — `embed.html` placeholder stays untouched.
- **No streaming** — single request/response per call.
- **No multimodal / figures** — Phase 6 and Step 9 layer those in later.
- **No tests** — Step 11.

#### Risks / gotchas

- **`OPENAI_API_KEY` must be set or the import-time/call-time chain fails.** The existing tutor module fails fast on missing key; the bridge surfaces that error cleanly. Document in the docstring; remind during verification.
- **Cost per smoke-test call.** Every test call is a real LLM call (cents at most, but worth flagging — repeated automated runs add up). No mocking in this step; mocks belong to Step 11 tests.
- **JSON parsing fragility.** The tutor returns a JSON object with `pedagogical-reasoning` and `Student-facing-answer`. `parse_tutor_response` in `tutor.run_tutor` already handles minor malformations. The bridge does NOT add additional repair logic — if the underlying tutor returns garbage, the bridge raises whatever exception the tutor surfaces.
- **Cache staleness on curriculum edits.** Mid-process changes to `curriculum/<course>/exercise_<NN>.txt` won't reach a cached graph. Restart the process to pick up edits, or extend the cache with file-mtime tracking later if it becomes painful.
- **Path resolution for `_REPO_ROOT`.** `main_ui/services/tutor_bridge.py` is three levels deep from the repo root; use `Path(__file__).resolve().parents[2]` (same trick `routes/embed.py` uses).
- **Local name collision with `get_tutor_reply`.** Both `tutor.run_tutor` and our bridge expose a function named `get_tutor_reply`. Import the upstream one as `from tutor.run_tutor import get_tutor_reply as get_tutor_reply_upstream` to avoid shadowing.
- **Concurrency.** Module-level cache dict is not thread-safe. Flask dev server is single-threaded so this is a non-issue. Document and revisit when we hit a multi-process / multi-thread environment.

---

## Future steps (just placeholders for now)

These will get fleshed out as we work through them. Each maps to the implementation order in [Phase 8 of the main PLANNING.md](../PLANNING.md).

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

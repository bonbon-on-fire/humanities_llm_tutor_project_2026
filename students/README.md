# Students

Simulated student bots used to test the tutor. Each persona is a different "attack vector" — it tries to trigger a specific tutor failure mode (e.g. giving away the answer, going off-topic, lecturing instead of diagnosing).

## Structure

```
students/
  __init__.py      — package exports
  run_student.py   — shared LangGraph engine (one file, all personas)
  personas/
    chaotic_01.txt — LLM system prompt
    chaotic_01.md  — human-readable summary of what the persona tests
    ...
```

- **`run_student.py`** — the single bot engine. Select a persona by name (e.g. `"chaotic_01"`); the engine loads the matching `.txt` prompt from `personas/`.
- **`personas/*.txt`** — system prompts sent to the LLM to shape the student's behavior.
- **`personas/*.md`** — short human-readable descriptions (a few sentences explaining what the persona tests and how it behaves).

## Adding a new persona

Create two files in `personas/`:

1. `{name}.txt` — the LLM system prompt
2. `{name}.md` — a few sentences describing the persona for humans

No code changes needed. The bot engine discovers personas automatically.

## Available personas

Each family now has six variants:
- `_01` scripted baseline
- `_02` unscripted baseline
- `_03` strategy-sweep / tester baseline
- `_04` concise clone of `_01`
- `_05` concise clone of `_02`
- `_06` concise clone of `_03`

| Name pattern | Tests |
| ---- | ----- |
| `chaotic_01..06` | Academic integrity and tutor/assistant boundary stress testing |
| `chitchat_01..06` | Role-adherence and off-topic drift stress testing |
| `clueless_01..06` | Lost-student support and diagnosis-first handling stress testing |

Concise variants (`_04`/`_05`/`_06`) enforce realistic chat length:
- one or two brief sentences per turn
- short, natural messages (no long paragraphs)

## Usage

```python
from students.run_student import get_next_student_message

msg = get_next_student_message(
    messages,                    # conversation so far (list of BaseMessage)
    prompt_name="chaotic_04",    # persona to use (concise variant)
    assignment="...",            # optional assignment text
    turn_size=10,                # optional planned student+tutor exchanges
)
```

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.2`). |

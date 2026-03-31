# Students

Simulated student bots used to test the tutor. Each persona is a different "attack vector" — it tries to trigger a specific tutor failure mode (e.g. giving away the answer, going off-topic, lecturing instead of diagnosing).

## Structure

```text
students/
  __init__.py      — package exports
  run_student.py   — shared LangGraph engine (one file, all personas)
  personas/
    chaotic_01.txt — LLM system prompt
    chaotic_01.md  — human-readable summary of what the persona tests
    ...
```

- `run_student.py` is the shared engine for all personas.
- `personas/*.txt` are LLM-facing persona prompts.
- `personas/*.md` are human-readable summaries of persona intent.

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
- `_04` scripted baseline with casual texting/slang style
- `_05` unscripted baseline with casual texting/slang style
- `_06` strategy-sweep baseline with stronger "genz" texting/slang style

| Name pattern | Tests |
| ---- | ----- |
| `chaotic_01..06` | Academic integrity and tutor/assistant boundary stress testing |
| `cooperative_01..06` | Good-student baseline behavior for compliant, non-adversarial tutoring runs |
| `clueless_01..06` | Lost-student support and diagnosis-first handling stress testing |

Texting/slang variants (`_04`/`_05`/`_06`) enforce realistic chat length plus abbreviation-heavy style:
- one or two brief sentences per turn
- short, natural messages (no long paragraphs)
- natural shorthand/slang (for example `idk`, `ngl`, `tbh`, `rn`, `u`, `fr`)

All personas also inherit shared role constraints from the engine (student voice only, no tutor-like framing, concise replies).

## Usage

```python
from students.run_student import get_next_student_message

msg = get_next_student_message(
    messages,                    # conversation so far (list of BaseMessage)
    prompt_name="chaotic_04",    # persona to use (texting/slang variant)
    assignment="...",            # optional assignment text
    turn_size=10,                # optional planned student+tutor exchanges
)
```

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.4`). |

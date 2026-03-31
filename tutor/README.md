# Tutor

LangGraph-based Socratic tutor for MIT OCW humanities courses. The tutor guides students through assignments using guided discovery — it never gives the answer directly.

## Structure

```text
tutor/
  __init__.py          — package exports
  run_tutor.py         — LangGraph engine, system-prompt loading, response parsing
  prompts/
    tutor_01.txt       — baseline system prompt
    tutor_02.txt       — revised system prompt variant
    tutor_03.txt       — latest concise-response variant used in bundle runs
```

- `run_tutor.py` builds the LangGraph, invokes the LLM, and parses structured JSON response fields (pedagogical reasoning + student-facing answer).
- Prompt versions are selected by name (for example `tutor_01`, `tutor_02`, `tutor_03`) and loaded from `tutor/prompts/`.

## How the tutor works

1. The system prompt is loaded from `prompts/<prompt_name>.txt`.
2. If an exercise is provided, the `<Assignment>...</Assignment>` block in the prompt is replaced with the exercise text.
3. The LLM receives the system prompt + conversation history and returns a JSON response:
   ```json
   {
     "pedagogical-reasoning": "internal reasoning about how to respond",
     "Student-facing-answer": "the message shown to the student"
   }
   ```
4. `parse_tutor_response()` extracts both fields. The student-facing answer is returned; reasoning is available for debugging.

## Usage

```python
from tutor import get_tutor_reply, create_tutor_graph, load_system_prompt

# One-shot (builds a new graph each call)
messages, answer_text = get_tutor_reply(
    messages,
    assignment_override="Your exercise text here...",
)

# Reuse graph across multiple turns
prompt = load_system_prompt("tutor_01", assignment_override="...")
graph = create_tutor_graph(prompt)
messages, answer_text = get_tutor_reply(messages, graph=graph)
```

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.4`). |

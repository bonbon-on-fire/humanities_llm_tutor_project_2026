# Chitchat Student 01 — Role-adherence (off-topic) attacker

Persona and LangGraph-based bot that simulates a student trying to get the tutor to **go off-topic** (e.g. declare a break and ask for pizza recommendations, chat about weekend plans). Used to test that the tutor maintains **role adherence**: acknowledges breaks, declines off-topic requests, and reminds the student of its purpose.

## Contents

- **prompts/student_01_prompt_01.txt** — Default student prompt (persona, tactics, tone). Add more files (e.g. `student_01_prompt_02.txt`) for variants and use `--prompt`.
- **bot.py** — LangGraph agent: loads the prompt, uses an LLM to generate the next student message from conversation history.
- **cli.py** — CLI to run a conversation (interactive, mock tutor, or **real tutor**).
- **persona.md** — Optional: human-readable persona spec (same content as the default prompt).

## Setup

From the **project root** (`humanities_llm_tutor_project_2026`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**API keys**

- **Student bot**: `OPENAI_KEY` (or `OPENAI_API_KEY`). Set in `.env` or the environment.
- **Tutor (when using `--tutor`)**: `OPENAI_API_KEY` is required. Set in `.env` or the environment.

Example `.env` in project root:

```
OPENAI_API_KEY=sk-your-key
# Optional if same key: OPENAI_KEY=sk-your-key
```

## Run

All commands from the **project root**:

### Interactive (you play the tutor)

```powershell
python -m student_personas.chitchat_student.student_01.cli
# Type tutor messages; bot replies as student. Type 'quit' to exit.
```

### Real tutor vs student (`--tutor`)

Runs the **tutor bot** (from `tutor/run_tutor.py`) against this student. Tutor output is the student's input each turn.

```powershell
python -m student_personas.chitchat_student.student_01.cli --tutor --max-turns 10
```

With the same assignment for both:

```powershell
python -m student_personas.chitchat_student.student_01.cli --tutor --exercise "When is it morally okay to kill one to save five? ..." --max-turns 10
python -m student_personas.chitchat_student.student_01.cli --tutor --exercise-file path/to/assignment.txt --max-turns 10
```

### Mock tutor (scripted replies, no real tutor)

The mock tutor models **desired role-adherence**: it acknowledges breaks and declines off-topic questions (e.g. pizza, weather), reminding the student of the tutor's purpose.

```powershell
python -m student_personas.chitchat_student.student_01.cli --mock-tutor --max-turns 5
```

### Exercise / assignment context

The student bot can see the exercise text so it can reference it before going off-topic:

```powershell
python -m student_personas.chitchat_student.student_01.cli --exercise "Discuss act vs rule consequentialism in 500 words."
python -m student_personas.chitchat_student.student_01.cli --exercise-file path/to/assignment.txt
```

### Multiple prompt variants (`--prompt`)

Use a different prompt file under `prompts/` (e.g. after adding `student_01_prompt_02.txt`):

```powershell
python -m student_personas.chitchat_student.student_01.cli --prompt student_01_prompt_02 --tutor --max-turns 10
```

### All options

| Option | Description |
|--------|-------------|
| `--tutor` | Use the real tutor bot; tutor output is the student's input. |
| `--mock-tutor` | Use a scripted mock tutor instead of typing or the real tutor. |
| `--max-turns N` | Maximum number of exchanges (default 20). |
| `--exercise "..."` | Exercise/assignment text visible to the student (and to the tutor when using `--tutor`). |
| `--exercise-file PATH` | Load exercise text from a file (overrides `--exercise` if set). |
| `--prompt NAME` | Use `prompts/<NAME>.txt` instead of the default prompt. |

## Using the student bot from code

When driving the tutor yourself (e.g. from another script), use the bot like this:

```python
from langchain_core.messages import HumanMessage, AIMessage
from student_personas.chitchat_student.student_01.bot import build_graph, get_next_student_message

graph = build_graph()
messages = [HumanMessage(content="Hi. What would you like to work on?")]
student_msg = get_next_student_message(messages, exercise="...", graph=graph)
# Append student_msg, send to tutor, get tutor reply, append HumanMessage(tutor_reply), repeat.
```

Optional: `get_next_student_message(..., exercise=exercise, graph=graph)` and `build_graph(persona=...)` / `load_persona(path=...)` for custom prompt or assignment.

## Multiple chitchat-student versions

To add more prompts or a new student (e.g. student_02), mirror the structure under **`student_personas/chitchat_student/`** (e.g. add `student_02/` with its own `bot.py`, `cli.py`, `prompts/`, and use the same run pattern with the appropriate module path).

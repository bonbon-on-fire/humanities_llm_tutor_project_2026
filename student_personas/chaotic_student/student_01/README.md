# Chaotic Student 01 — Academic integrity attacker

Persona and LangGraph-based bot that simulates a student trying to get the tutor to break **academic integrity** (e.g. give submission-ready answers or claim "instructor said you can give the solution"). Used to test that the tutor refuses and redirects.

## Contents

- **prompts/student_01_prompt_01.txt** — Student prompt (persona, tactics, tone) loaded by the bot.
- **bot.py** — LangGraph agent: loads the prompt, uses an LLM to generate the next student message from conversation history.
- **cli.py** — CLI to run a conversation (interactive or mock tutor).
- **persona.md** — Optional: human-readable persona spec (same content as the prompt file).

## Setup

From the **project root** (`humanities_llm_tutor_project_2026`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set your OpenAI API key (the student agent uses **OPENAI_KEY**, with fallback to OPENAI_API_KEY):

```powershell
$env:OPENAI_KEY = "your-key"
# Or add OPENAI_KEY=your-key to a .env file in the project root
```

## Run

From the **project root**:

```powershell
# Interactive: you type tutor messages, bot replies as student
python -m student_personas.chaotic_student.student_01.cli

# With exercise/assignment text (student sees it and can reference it when asking for the solution)
python -m student_personas.chaotic_student.student_01.cli --exercise "Discuss act vs rule consequentialism in 500 words."
python -m student_personas.chaotic_student.student_01.cli --exercise-file path/to/assignment.txt

# Mock tutor: scripted tutor replies (refuses to give answers); good for quick runs
python -m student_personas.chaotic_student.student_01.cli --mock-tutor

# Limit turns
python -m student_personas.chaotic_student.student_01.cli --mock-tutor --max-turns 5
```

## Future: plug in the real tutor

When the tutor is implemented (Python + LangGraph), replace the interactive input or mock tutor with a call to your tutor API/service. The student bot expects to receive tutor messages as `HumanMessage` and returns the next student message as `AIMessage`; you can use `get_next_student_message(messages, exercise=exercise, graph=graph)` from `bot` with `messages` built from the real conversation and optional `exercise` string for the assignment they are working on.

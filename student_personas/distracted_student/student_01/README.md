# Distracted Student 01 — Role-adherence attacker

Persona and LangGraph-based bot that simulates a **distracted student**: takes breaks, asks off-topic questions (e.g. pizza, recommendations, casual chat). Used to test that the tutor **maintains role**—acknowledges breaks, declines off-topic, and reminds the tutor’s purpose (see PLANNING.md §4 “Role adherence” and §5 failure example).

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
# Interactive: you type tutor messages, bot replies as distracted student
python -m student_personas.distracted_student.student_01.cli

# With exercise/assignment text (student can reference it when drifting or returning)
python -m student_personas.distracted_student.student_01.cli --exercise "Discuss act vs rule consequentialism in 500 words."
python -m student_personas.distracted_student.student_01.cli --exercise-file path/to/assignment.txt

# Mock tutor: scripted tutor acknowledges breaks and declines off-topic (desired role-adherence behavior)
python -m student_personas.distracted_student.student_01.cli --mock-tutor

# Against the real tutor (tests whether tutor holds role when student distracts)
python -m student_personas.distracted_student.student_01.cli --tutor --exercise "..."

# Limit turns
python -m student_personas.distracted_student.student_01.cli --mock-tutor --max-turns 5
```

## Relation to PLANNING.md

This persona targets the **role adherence** failure:

- **Failure**: Student says “I’m taking a break” → Tutor says “If you feel like chatting about something unrelated … I’m here.” Student asks “What are good pizza places in Boston?” → Tutor gives recommendations.
- **Desired**: Acknowledge break; pause support; for off-topic (e.g. pizza), gently decline and remind tutor’s purpose.

The distracted_student bot tries to elicit that failure so you can verify the real tutor passes.

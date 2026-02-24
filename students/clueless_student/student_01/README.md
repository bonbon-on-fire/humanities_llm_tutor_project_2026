# Clueless Student — student_01

LLM bot that simulates a **lost/confused student** to test the tutor’s “helping lost student” behavior (see PLANNING.md).

**Goal:** Trigger the failure where the tutor gives a long lecture instead of asking diagnostic questions first and then giving a short, tailored explanation.

## Usage (from project root)

```powershell
python -m student_personas.clueless_student.student_01.cli
python -m student_personas.clueless_student.student_01.cli --mock-tutor
python -m student_personas.clueless_student.student_01.cli --tutor --exercise "Your assignment text here"
```

- **Interactive:** You play the tutor; the bot replies as the clueless student.
- **--mock-tutor:** Scripted tutor uses good “helping lost student” behavior (diagnostic question, then short reply + check).
- **--tutor:** Real tutor from `tutor.run_tutor`; tutor output is the student’s input.

Requires `OPENAI_KEY` or `OPENAI_API_KEY` for the student bot; `OPENAI_API_KEY` for `--tutor`.

## Files

- `persona.md` — Persona description (same content as prompt).
- `prompts/student_01_prompt_01.txt` — Prompt loaded by the bot.
- `bot.py` — LangGraph student agent.
- `cli.py` — Interactive, mock-tutor, and real-tutor modes.

# UI (terminal launcher)

This folder contains a **terminal-based UI** that launches an automated **tutor vs student** conversation run.

## How it works

When you run `python -m ui`, the UI will prompt for:

- **Exercise number**: choose `01..NN`, where `NN` is based on how many `exercise_*.txt` files exist in `tutor/exercises/`.
  - Selection is **strictly mapped**: `01` → `exercise_01.txt`, `02` → `exercise_02.txt`, etc.
- **Student type**: one of `chaotic`, `chitchat`, `clueless`.
- **Student version**: choose `01..NN` based on available `students/<type>_student/student_##/` folders.
  - Example: `01` → `student_01`.
- **Turns**: number of **student+tutor exchanges** to run.

The UI then runs the conversation automatically (no interactive / no mock-tutor mode).

### Exercise as context for student and tutor

The **selected exercise** (the full text of the chosen `exercise_XX.txt` file) is used as context for both sides:

- **Student**: The exercise text is passed into every call to the student bot as `exercise=...`. The student bot includes it in the student’s context (e.g. in the system prompt) so the simulated student can refer to the assignment when replying (e.g. “I don’t get this question” or “which part of the prompt are we doing?”).
- **Tutor**: The same exercise text is passed as `assignment_override` to the tutor so the tutor’s responses are anchored to that assignment.

- **Transcript**: The exercise text and `exercise_file` name are saved in the transcript JSON so the judge has full context when evaluating the run.

## Transcript output

After the conversation ends normally, the UI will prompt for a transcript name and save a JSON file under `judge/transcripts/`.

- **Directory**: `judge/transcripts/`
- **Naming normalization**:
  - Lowercase everything
  - Convert spaces to underscores
  - If the user omits `.json`, append `.json`
  - If the target file already exists, **reprompt** for a new name (no overwrite)
- **On Ctrl+C**: exit **without saving**.

### Transcript JSON schema

Transcripts are saved as a single object so the judge has full context (including the exercise):

```json
{
  "exercise": "Full exercise/assignment text used as context for student and tutor.",
  "exercise_file": "exercise_04.txt",
  "student_type": "chaotic",
  "student_version": "01",
  "exchanges": [
    { "turn": 1, "student": "…", "tutor": "…" },
    { "turn": 2, "student": "…", "tutor": "…" }
  ]
}
```

Notes:
- **exercise** is the full text that was used as context for the student and as the tutor’s assignment.
- **exchanges** are the student+tutor message pairs (the initial tutor greeting is not stored).

## Judge integration

After the transcript is saved, the UI runs the **judge** once on that transcript and:

- Appends a top-level `grade` object to the transcript JSON (see `judge/README.md`)
- Prints the total score as `total_score/max_score`

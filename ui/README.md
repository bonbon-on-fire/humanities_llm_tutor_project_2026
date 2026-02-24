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

## Transcript output

After the conversation ends normally, the UI will prompt for a transcript name and save a JSON file under `judge/transcripts/`.

- **Directory**: `judge/transcripts/`
- **Naming normalization**:
  - Lowercase everything
  - Convert spaces to underscores
  - If the user omits `.json`, append `.json`
  - If the target file already exists, **reprompt** for a new name (no overwrite)
- **On Ctrl+C**: exit **without saving**.

### Transcript JSON schema (one object per exchange)

Transcripts are an array of exchange objects, in order:

```json
[
  { "turn": 1, "student": "…", "tutor": "…" },
  { "turn": 2, "student": "…", "tutor": "…" }
]
```

Notes:
- Only **student + tutor messages** are stored (no metadata).
- The transcript **does not include** the initial tutor greeting used to start the run.

# Terminal UI

Interactive terminal launcher that orchestrates a **tutor vs student** conversation run, then scores it with the judge.

## How to run

```
python -m terminal_ui
```

## Pipeline

The UI prompts for each configuration step, then runs the conversation:

| Step | Prompt | Source |
| ---- | ------ | ------ |
| 0 | Tutor prompt version | Scans `tutor/prompts/*.txt` |
| 1 | Student persona type | `chaotic`, `chitchat`, `clueless` |
| 2 | Student persona version | Scans `students/personas/{type}_*.txt` for version numbers |
| 3 | Course | Scans `curriculum/` subfolder names |
| 4 | Exercise number | Scans `curriculum/{course}/exercise_*.txt` |
| 5 | Number of turns | Positive integer |
| 6 | *Runs conversation* | Tutor and student alternate for N turns |
| 7 | Judge prompt version | Scans `judge/prompts/*.txt` |
| 8 | *Auto-saves transcript + runs judge* | See below |

If there's only one option for a step (e.g. one tutor prompt), it's auto-selected.

## Transcript output

Transcripts are auto-named and saved under `transcripts/{persona_type}/`:

```
transcripts/
  chaotic/
    transcript_01.json
    transcript_02.json
  chitchat/
    transcript_01.json
  ...
```

Numbers auto-increment (next available `transcript_XX`).

### Transcript JSON schema

```json
{
  "tutor_prompt": "tutor_01",
  "student_persona": "chaotic_01",
  "course": "philosophy",
  "exercise_number": "01",
  "exercise": "Full exercise text...",
  "judge_prompt": "judge_01",
  "turns": 10,
  "exchanges": [
    { "turn": 1, "student": "...", "tutor": "..." },
    { "turn": 2, "student": "...", "tutor": "..." }
  ]
}
```

After the judge runs, a `grade` object is appended to the transcript (see `judge/README.md`).

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.2`). |

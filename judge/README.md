# Judge (LLM-based transcript grader)

This folder contains an **LLM-based judge** that scores a saved conversation transcript under `judge/transcripts/` using the rubric in `judge/judge_rubric.md`.

## What it does

- Reads a transcript JSON (produced by the UI) from `judge/transcripts/<name>.json`
- Uses **LangGraph + OpenAI** to apply `judge/judge_rubric.md`
- **Hard-fails** if it cannot produce valid, internally-consistent grade JSON
- Writes a top-level `grade` object back into the transcript file (appended as the last key when serialized)
- Returns `(total_score, max_score)` back to the caller (the UI prints it)

## Environment variables

- **`OPENAI_API_KEY`**: required
- **`OPENAI_MODEL`**: optional (defaults to `gpt-4o`)

## Usage (from Python)

The UI calls the judge automatically after saving a transcript, but you can also invoke it from code:

```python
from judge import judge_transcript

result = judge_transcript("transcript_01")  # filename without .json
print(result.total_score, result.max_score)
```

## Transcript expectations

The judge expects the transcript JSON schema described in `ui/README.md`, with a non-empty `exchanges` array.

The judge will refuse to run if the transcript already contains a top-level `grade` key.

## Grade schema (high level)

The judge writes:

- `grade.total_score` / `grade.max_score` (max is 70)
- A full breakdown by section and sub-criterion under `grade.sections`
- Deductions with reasons and (when possible) `evidence_turns`
- `grade.model` and `grade.timestamp_utc`


# Transcript format for LLM judge evaluation

This document describes how to **store** a full tutor–student conversation so the LLM judge can score it using [grader_rubric.md](grader_rubric.md).

## Purpose

- **Storage**: Persist a complete conversation (assignment + ordered turns) in a single, well-defined structure.
- **Input to judge**: The judge receives the same structure (e.g. as JSON or as a flattened transcript) and applies the rubric to the **whole conversation**.

## Schema

The canonical schema is [transcript_schema.json](transcript_schema.json). Summary:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | No | Unique identifier for the transcript (e.g. UUID). |
| `assignment` | Yes | Object with at least `text` (full problem/assignment). Optional: `courseId`, `courseName`. |
| `turns` | Yes | Array of turns in order. Each turn has `role` (`"student"` or `"tutor"`) and `content` (string). Optional: `timestamp`, `turnIndex`. |
| `metadata` | No | Optional `createdAt`, `sessionId`, `evaluationId`, etc. |

## Example (minimal)

```json
{
  "assignment": {
    "text": "In the trolley case, explain whether and why you would flip the switch. Use act-consequentialist reasoning."
  },
  "turns": [
    { "role": "student", "content": "I don't get what I'm supposed to do." },
    { "role": "tutor", "content": "Start with this: what does the scenario say is in your power to do?" },
    { "role": "student", "content": "I can flip the switch so only one person dies." },
    { "role": "tutor", "content": "Good. So what would an act-consequentialist compare when deciding?" }
  ]
}
```

## Example (with metadata)

```json
{
  "id": "conv-550e8400-e29b-41d4-a716-446655440000",
  "assignment": {
    "text": "In the trolley case, explain whether and why you would flip the switch. Use act-consequentialist reasoning.",
    "courseId": "24.01",
    "courseName": "Introduction to Philosophy"
  },
  "turns": [
    { "role": "student", "content": "I don't get what I'm supposed to do.", "turnIndex": 0 },
    { "role": "tutor", "content": "Start with this: what does the scenario say is in your power to do?", "turnIndex": 1 },
    { "role": "student", "content": "I can flip the switch so only one person dies.", "turnIndex": 2 },
    { "role": "tutor", "content": "Good. So what would an act-consequentialist compare when deciding?", "turnIndex": 3 }
  ],
  "metadata": {
    "createdAt": "2026-02-24T12:00:00Z",
    "sessionId": "sess-abc123"
  }
}
```

## Flattened transcript for the judge

The LLM judge can receive either:

1. **Structured JSON** (the object above), with instructions to consider `assignment.text` and every `turns[].content` in order by `role`.
2. **Flattened text**, for models that work better with plain text. Example format:

```text
## Assignment
In the trolley case, explain whether and why you would flip the switch. Use act-consequentialist reasoning.

## Conversation
[Student]: I don't get what I'm supposed to do.
[Tutor]: Start with this: what does the scenario say is in your power to do?
[Student]: I can flip the switch so only one person dies.
[Tutor]: Good. So what would an act-consequentialist compare when deciding?
```

When implementing the judge pipeline, either:
- pass the JSON and include in the judge prompt that the conversation is in `turns` in order, and the assignment is in `assignment.text`, or
- generate this flattened transcript from the JSON and pass it with the rubric.

## Implementation notes

- **Producing transcripts**: When the chat app or backend stores a conversation, write it in this schema (e.g. on session end or on demand). Validate against `transcript_schema.json` before passing to the judge.
- **Math**: Keep `$...$` and `$$...$$` in `content` as-is so the judge can check formatting (see rubric section 5.3).
- **Encoding**: Use UTF-8 for JSON and flattened text.
- **File naming**: Suggested pattern for files: `transcript_<id>.json` or `transcript_<sessionId>_<createdAt>.json`.

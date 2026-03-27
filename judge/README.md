# Judge

LLM-based grader that scores tutor–student conversation transcripts against a rubric.

Current defaults in code:
- prompt: `judge_05`
- rubric: `rubric_05`

## Structure

```text
judge/
  __init__.py              — package exports
  run_judge_gpt.py         — GPT judge implementation (OpenAI)
  run_judge_claude.py      — Claude judge module (single-transcript scoring API)
  run_judge_batch_gpt.py   — GPT batch judge for bundle experiments
  run_judge_batch_claude.py — Claude batch judge for bundle experiments
  README.md
  prompts/
    judge_01.txt           — baseline prompt template
    judge_02.txt           — structured prompt template
    judge_03.txt           — prior prompt template (context + exercise aware)
    judge_04.txt           — current prompt template (context + exercise aware)
    judge_05.txt           — current prompt template (rubric_05 compatible)
    judge_06.txt           — latest prompt template
  rubrics/
    rubric_01.md           — original rubric profile
    rubric_02.md           — intermediate rubric profile
    rubric_03.md           — prior rubric profile (33 base + 9 bonus = 42 max)
    rubric_04.md           — prior rubric profile (47 base with section malus deductions)
    rubric_05.md           — current rubric profile (46 base points, no malus)
    rubric_06.md           — latest rubric profile
  transcript_batches/
    README.md              — batch system overview and usage
    batch_01.md            — Type 01 batch documentation
    batch_02.md            — Type 02 batch documentation
    batch_03.md            — Type 03 batch documentation
    batch_##_###.txt       — 198 batch files for experiments
```

Transcripts live in the top-level `transcripts/` folder (not inside `judge/`).

## How it works

1. Load prompt from `prompts/<prompt_name>.txt`.
2. Inject rubric text from `rubrics/<rubric_name>.md` and the expected output schema.
3. Read transcript JSON from `transcripts/<relative_stem>.json`.
4. Call model, parse JSON output, sanitize numeric fields, and validate schema.
5. If validation fails, issue one repair attempt.
6. Write `grade` back into the transcript file.

## Usage

### Single Transcript Judging

```python
from judge.run_judge_gpt import judge_transcript

result = judge_transcript("chaotic/chaotic_raw/transcript_01")
print(result.total_score, result.max_score)  # e.g. 41, 46
```

You can also choose specific judge prompt + rubric versions:

```python
result = judge_transcript(
    "chaotic/chaotic_raw/transcript_01",
    prompt_name="judge_05",
    rubric_name="rubric_05",
)
```

Claude example:

```python
from judge.run_judge_claude import judge_transcript

result = judge_transcript("chaotic/chaotic_raw/transcript_01")
print(result.total_score, result.max_score)
```

### Batch Judging (Bundle Experiments)

Judge multiple transcripts together for comparative analysis:

```python
from judge.run_judge_batch_gpt import judge_transcript_batch

# Use a batch file from judge/transcript_batches/
results = judge_transcript_batch(
    "unused_name",
    batch_file_path="judge/transcript_batches/batch_01_001.txt",
    output_name="experiment_1"
)

for i, result in enumerate(results, 1):
    print(f"Transcript {i}: {result.total_score}/{result.max_score}")
```

Claude batch judging:

```python
from judge.run_judge_batch_claude import judge_transcript_batch

results = judge_transcript_batch(
    "unused_name", 
    batch_file_path="judge/transcript_batches/batch_02_001.txt"
)
```

### Batch Experiments

Run complete batch experiments with simple configuration:

```bash
# Edit BATCH_TYPE (1, 2, or 3) in the file, then run:
python run_batch_gpt.py     # GPT experiments
python run_batch_claude.py  # Claude experiments
```

Available batch types in `judge/transcript_batches/`:
- **Type 01**: Same persona + same version + same exercise (72 batches)
- **Type 02**: Same persona + same version + different exercise (54 batches)  
- **Type 03**: Different persona + same version + same exercise (72 batches)

## Rubric summary

- `1. Pedagogy` (`1.1`-`1.3`): `23` max points
- `2. Dialogue quality` (`2.1`-`2.2`): `10` max points
- `3. Communication quality` (`3.1`-`3.3`): `14` max points
- `Base total`: `47` max points

For `rubric_05` (current):
- `1. Pedagogy` (`1.1`-`1.3`): `24` max points
- `2. Dialogue quality` (`2.1`-`2.2`): `12` max points
- `3. Communication quality` (`3.1`-`3.2`): `10` max points
- `Base total`: `46` max points

**Note**: `rubric_05` removed malus deductions. Total score equals base score.

Maximum total score: **46**.

## Output contract (current)

- Scores are whole integers only.
- Top-level key order ends with `total_score`, then `judge_llm_calls`.
- `overview` replaces `justifications` and appears near the end.
- Deductions are ordered as `evidence_turns`, `sub_criterion_id`, `reason`, then `points` (`evidence_turns` optional).
- For `rubric_04`/`rubric_05`, each deduction must include an exact rubric sub-sub ID in `sub_criterion_id` (for example `1.1.A.a`, `2.2.D.a`, `3.2.C.b`).
- For `rubric_05`: No malus deductions. `total_score` equals `total_base_score`.
- Judge input supports both transcript `context` and `exercise`.

### Batch Output

For batch judging, each transcript gets its own graded file with naming:
`{output_name}_batch_{index:02d}__{prompt_name}__{rubric_name}__{provider}.json`

Example: `experiment_1_batch_01__judge_05__rubric_05__gpt.json`

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.2`). |
| `JUDGE_OPENAI_REASONING_EFFORT` | No | OpenAI reasoning effort for GPT judge: `low`, `medium`, `high`, or `off`. Default: `medium`. |
| `JUDGE_INCLUDE_TIMESTAMP` | No | If truthy (`1/true/yes/on`), include `timestamp_utc` in grade output. Default off for deterministic artifacts. |
| `ANTHROPIC_API_KEY` | For Claude judge | Anthropic API key required by Claude judge flow. |
| `ANTHROPIC_MODEL` | No | Model name for Claude judge (default: `claude-sonnet-4-6`). |

## Claude Judge Module

`judge/run_judge_claude.py` now mirrors the GPT judge flow, but uses Anthropic:
- Same transcript input/output contract.
- Same schema validation, sanitization, and retry behavior.
- Uses `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` (default: `claude-sonnet-4-6`).

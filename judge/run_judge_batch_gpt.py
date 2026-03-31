"""GPT batch judge wrapper (unified core)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from judge.run_judge_batch_unified import JudgeError, JudgeResult, judge_transcript_batch_gpt

# ========================================
# BATCH RUNNER CONFIGURATION
# ========================================
BATCH_TYPE = 1  # 1, 2, or 3
RUN_ALL_BATCHES = False  # Set True to run all for BATCH_TYPE
JUDGE_PROMPT = "judge_05"
RUBRIC_NAME = "rubric_05"
# ========================================

_BATCH_TYPE_COUNTS = {1: 72, 2: 54, 3: 72}

judge_transcript_batch = judge_transcript_batch_gpt

__all__ = ["JudgeError", "JudgeResult", "judge_transcript_batch", "run_all_batches_of_type"]


def _resolve_batch_dir() -> Path:
    primary = Path("transcripts/batches/batches_raw")
    fallback = Path("judge/transcript_batches")
    if primary.exists():
        return primary
    if fallback.exists():
        return fallback
    return primary


def run_all_batches_of_type(batch_type: int) -> None:
    count = _BATCH_TYPE_COUNTS.get(batch_type)
    if count is None:
        raise JudgeError(f"Invalid batch type: {batch_type}. Expected 1, 2, or 3.")
    prefix = f"batch_{batch_type:02d}"
    raw_root = _resolve_batch_dir()
    in_dir = raw_root / prefix if (raw_root / prefix).exists() else raw_root
    out_root = Path("transcripts/batches/batches_gpt")
    out_dir = out_root / prefix
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Running GPT batch type {batch_type:02d} ({count} files)")
    failures = 0
    for i in range(1, count + 1):
        batch_file = in_dir / f"batch_{i:03d}.txt"
        if not batch_file.exists():
            batch_file = in_dir / f"{prefix}_{i:03d}.txt"
        out_path = out_dir / f"batch_{i:03d}.json"
        try:
            result = judge_transcript_batch(
                str(batch_file),
                prompt_name=JUDGE_PROMPT,
                rubric_name=RUBRIC_NAME,
                output_path=str(out_path),
            )
            print(f"[{i:03d}/{count}] OK {result.total_score}/{result.max_score} -> {result.output_path.name}")
        except Exception as e:
            failures += 1
            print(f"[{i:03d}/{count}] FAIL {batch_file.name}: {e}")
    print(f"Done. Failures: {failures}")


if __name__ == "__main__":
    if RUN_ALL_BATCHES:
        run_all_batches_of_type(BATCH_TYPE)
    else:
        print("Set RUN_ALL_BATCHES = True to run batch experiments")
        print(f"Current: BATCH_TYPE={BATCH_TYPE}, JUDGE_PROMPT={JUDGE_PROMPT}, RUBRIC_NAME={RUBRIC_NAME}")



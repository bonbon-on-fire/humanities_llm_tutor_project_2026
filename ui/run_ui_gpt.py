"""
Batch runner that grades all raw transcripts using the GPT judge.

Reads from transcripts/{persona}/{persona}_raw/ and writes graded copies
to transcripts/{persona}/{persona}_gpt/.

Usage:
    python -m ui.run_ui_gpt
    python -m ui.run_ui_gpt --prompt judge_06 --rubric rubric_06
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env")

from judge.run_judge_gpt import JudgeError, judge_transcript

TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

# ---------------------------------------------------------------------------
# Parallel workers — change this value to control concurrency.
# ---------------------------------------------------------------------------
PARALLEL_WORKERS = 6


def _require_openai_api_key() -> None:
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY"):
        return
    raise RuntimeError(
        "OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set."
    )


def _discover_raw_transcripts() -> list[Path]:
    """Find all transcript_*.json files inside any *_raw/ subfolder."""
    return sorted(TRANSCRIPTS_DIR.glob("*/*_raw/transcript_*.json"))


def _provider_target_path(raw_path: Path, provider: str) -> Path:
    """Map a raw transcript path to its graded counterpart folder."""
    persona_dir = raw_path.parent.parent
    persona_type = persona_dir.name
    target_dir = persona_dir / f"{persona_type}_{provider}"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / raw_path.name


def _relative_stem(path: Path) -> str:
    """Return the transcript name relative to TRANSCRIPTS_DIR without .json."""
    rel = path.relative_to(TRANSCRIPTS_DIR).as_posix()
    return rel[:-5] if rel.endswith(".json") else rel


def _grade_one(
    raw_path: Path,
    target_path: Path,
    *,
    prompt_name: str,
    rubric_name: str,
) -> dict[str, Any]:
    """Copy a raw transcript to its target path, then grade it in place."""
    if target_path.exists():
        print(
            f"  [WARN] Overwriting existing file: "
            f"{target_path.relative_to(_REPO_ROOT)}"
        )
    shutil.copyfile(raw_path, target_path)

    result = judge_transcript(
        _relative_stem(target_path),
        prompt_name=prompt_name,
        rubric_name=rubric_name,
        output_name=target_path.stem,
    )

    graded = json.loads(result.output_path.read_text(encoding="utf-8"))
    grade = graded.get("grade", {})
    section_scores: list[str] = []
    for sid, section in grade.get("sections", {}).items():
        base = section.get("base", {})
        section_scores.append(f"{sid}={base.get('score', '?')}/{base.get('max', '?')}")

    return {
        "raw_path": raw_path,
        "name": _relative_stem(target_path),
        "score": result.total_score,
        "max_score": result.max_score,
        "output_path": result.output_path,
        "section_scores": "  ".join(section_scores),
    }


_progress_lock = threading.Lock()
_progress_done = 0


def _print_result(info: dict[str, Any], total: int) -> None:
    global _progress_done
    with _progress_lock:
        _progress_done += 1
        n = _progress_done
    print(
        f"[GPT Judge] [{n}/{total}] "
        f"score={info['score']}/{info['max_score']}  "
        f"source={info['raw_path'].relative_to(_REPO_ROOT)}  "
        f"saved={info['output_path'].relative_to(_REPO_ROOT)}"
    )
    print(f"            {info['section_scores']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Grade all raw transcripts with GPT judge into *_gpt folders."
    )
    parser.add_argument(
        "--prompt", default="judge_05",
        help="Judge prompt stem (default: judge_05).",
    )
    parser.add_argument(
        "--rubric", default="rubric_05",
        help="Judge rubric stem (default: rubric_05).",
    )
    args = parser.parse_args(argv)

    try:
        _require_openai_api_key()
    except RuntimeError as error:
        print(str(error))
        return 1

    raw_files = _discover_raw_transcripts()
    if not raw_files:
        print(f"No raw transcripts found under {TRANSCRIPTS_DIR}")
        return 1

    workers = PARALLEL_WORKERS
    print(
        f"[GPT Judge] Grading {len(raw_files)} transcripts  "
        f"prompt={args.prompt}  rubric={args.rubric}  parallel={workers}"
    )

    tasks: list[tuple[Path, Path]] = []
    for raw_path in raw_files:
        target_path = _provider_target_path(raw_path, "gpt")
        tasks.append((raw_path, target_path))

    global _progress_done
    _progress_done = 0
    total = len(tasks)
    all_scores: list[dict[str, Any]] = []
    failed = 0

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _grade_one, raw_path, target_path,
                    prompt_name=args.prompt, rubric_name=args.rubric,
                ): (raw_path, target_path)
                for raw_path, target_path in tasks
            }
            for future in as_completed(futures):
                raw_path, _ = futures[future]
                try:
                    info = future.result()
                    all_scores.append(info)
                    _print_result(info, total)
                except JudgeError as error:
                    failed += 1
                    with _progress_lock:
                        _progress_done += 1
                        n = _progress_done
                    print(
                        f"[GPT Judge] [{n}/{total}] FAILED "
                        f"source={raw_path.relative_to(_REPO_ROOT)}: {error}"
                    )
    except KeyboardInterrupt:
        print("\nGPT judging interrupted.")
        return 130

    scores_only = [s["score"] for s in all_scores]
    mean_score = sum(scores_only) / len(scores_only) if scores_only else 0.0
    print(
        f"\n[GPT Judge] Done. "
        f"graded={len(all_scores)}  failed={failed}  "
        f"mean={mean_score:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

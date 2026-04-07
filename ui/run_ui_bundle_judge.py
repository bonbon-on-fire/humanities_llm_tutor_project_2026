"""
Interactive bundle runner that grades transcript bundles using either GPT or Claude bundle judge.

Reads bundle files from transcripts/bundles/bundles_raw/bundle_XX/ and writes
graded results to transcripts/bundles/bundles_gpt/bundle_XX/ or 
transcripts/bundles/bundles_claude/bundle_XX/.

Run with interactive CLI:
    python -m ui.run_ui_bundle_judge

Or run with command-line arguments:
    python -m ui.run_ui_bundle_judge --provider gpt --bundle-type 01 --prompt judge_05 --rubric rubric_05
"""

from __future__ import annotations

import argparse
import os
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

# Import shared functions from the existing UI judge script
from ui.run_ui_judge import (
    _require_openai_api_key, 
    _require_anthropic_api_key,
    _discover_judge_prompts,
    _discover_judge_rubrics,
)
from ui.cli_utils import (
    confirm_proceed,
    prompt_single_selection,
)

BUNDLES_DIR = _REPO_ROOT / "transcripts" / "bundles"

# ---------------------------------------------------------------------------
# Change these values to control bundle type and concurrency.
# ---------------------------------------------------------------------------
DEFAULT_BUNDLE_TYPE = "03"
PARALLEL_WORKERS = 6


def _discover_bundle_types() -> list[str]:
    """Find all available bundle types (e.g., ['01', '02', '03'])."""
    raw_dir = BUNDLES_DIR / "bundles_raw"
    if not raw_dir.exists():
        return []
    bundle_types = []
    for path in raw_dir.iterdir():
        if path.is_dir() and path.name.startswith("bundle_"):
            bundle_type = path.name[7:]  # Remove "bundle_" prefix
            if bundle_type.isdigit():
                bundle_types.append(bundle_type.zfill(2))
    return sorted(bundle_types)


def _discover_bundle_files(bundle_type: str) -> list[Path]:
    """Find all bundle_*.txt files for the given bundle type."""
    raw_dir = BUNDLES_DIR / "bundles_raw" / f"bundle_{bundle_type}"
    if not raw_dir.exists():
        return []
    return sorted(raw_dir.glob("bundle_*.txt"))


def _output_path_for(bundle_file: Path, bundle_type: str, provider: str) -> Path:
    """Map a raw bundle file to its graded output path based on provider."""
    out_dir = BUNDLES_DIR / f"bundles_{provider}" / f"bundle_{bundle_type}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / bundle_file.with_suffix(".json").name


def _grade_one_bundle(
    bundle_file: Path,
    output_path: Path,
    *,
    provider: str,
    prompt_name: str,
    rubric_name: str,
) -> dict[str, Any]:
    """Grade a single bundle file using the specified provider and return summary info."""
    if output_path.exists():
        print(
            f"  [WARN] Overwriting existing file: "
            f"{output_path.relative_to(_REPO_ROOT)}"
        )

    from judge.run_judge_bundle import judge_transcript_bundle

    result = judge_transcript_bundle(
        str(bundle_file),
        provider=provider,
        prompt_name=prompt_name,
        rubric_name=rubric_name,
        output_path=str(output_path),
    )

    return {
        "bundle_file": bundle_file,
        "score": result.total_score,
        "max_score": result.max_score,
        "output_path": result.output_path,
    }


_progress_lock = threading.Lock()
_progress_done = 0


def _print_result(info: dict[str, Any], total: int, provider: str) -> None:
    """Print a one-line progress and score summary for a completed bundle grading task."""
    global _progress_done
    with _progress_lock:
        _progress_done += 1
        n = _progress_done
    
    provider_label = provider.upper()
    print(
        f"[{provider_label} Bundle Judge] [{n}/{total}] "
        f"score={info['score']}/{info['max_score']}  "
        f"bundle={info['bundle_file'].name}  "
        f"saved={info['output_path'].relative_to(_REPO_ROOT)}"
    )


def _get_interactive_config() -> tuple[str, str, str, str]:
    """Get bundle judge configuration through interactive CLI prompts."""
    print("=== Bundle Transcript Judging Configuration ===")
    
    # Provider selection
    provider = prompt_single_selection(
        "Judge provider",
        ["gpt", "claude"],
        required=True,
    )
    
    # Bundle type selection
    available_bundle_types = _discover_bundle_types()
    if not available_bundle_types:
        raise RuntimeError("No bundle types found in transcripts/bundles/bundles_raw/")
    
    bundle_type = prompt_single_selection(
        "Bundle type",
        available_bundle_types,
        required=True,
    )
    
    # Judge prompt selection
    available_prompts = _discover_judge_prompts()
    if not available_prompts:
        raise RuntimeError("No judge prompts found in judge/prompts/")
    
    prompt_name = prompt_single_selection(
        "Judge prompt",
        available_prompts,
        required=True,
    )
    
    # Judge rubric selection
    available_rubrics = _discover_judge_rubrics()
    if not available_rubrics:
        raise RuntimeError("No judge rubrics found in judge/rubrics/")
    
    rubric_name = prompt_single_selection(
        "Judge rubric",
        available_rubrics,
        required=True,
    )
    
    return provider, bundle_type, prompt_name, rubric_name


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Grade all bundle files of a given type with GPT or Claude bundle judge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (default)
  python -m ui.run_ui_bundle_judge
  
  # Command-line mode
  python -m ui.run_ui_bundle_judge --provider gpt --bundle-type 01 --prompt judge_05 --rubric rubric_05
        """,
    )
    parser.add_argument(
        "--provider", choices=["gpt", "claude"],
        help="Judge provider to use: gpt or claude",
    )
    parser.add_argument(
        "--bundle-type",
        help="Bundle type number (e.g., 01, 02, 03)",
    )
    parser.add_argument(
        "--prompt",
        help="Judge prompt stem (from judge/prompts/judge_*.txt)",
    )
    parser.add_argument(
        "--rubric",
        help="Judge rubric stem (from judge/rubrics/rubric_*.md)",
    )
    
    return parser.parse_args()


def _run_bundle_judging(provider: str, bundle_type: str, prompt_name: str, rubric_name: str) -> int:
    """Run the bundle judging process with the given configuration."""
    # Check API key based on provider
    try:
        if provider == "gpt":
            _require_openai_api_key()
        elif provider == "claude":
            _require_anthropic_api_key()
    except RuntimeError as error:
        print(f"API key error: {error}")
        return 1

    bundle_type = bundle_type.zfill(2)
    bundle_files = _discover_bundle_files(bundle_type)
    if not bundle_files:
        print(
            f"No bundle files found under "
            f"{BUNDLES_DIR / 'bundles_raw' / f'bundle_{bundle_type}'}"
        )
        return 1

    # Show summary and get confirmation
    summary = (
        f"Will grade {len(bundle_files)} bundle files using:\n"
        f"  • Provider: {provider.upper()}\n"
        f"  • Bundle type: {bundle_type}\n"
        f"  • Judge prompt: {prompt_name}\n"
        f"  • Judge rubric: {rubric_name}\n"
        f"  • Parallel workers: {PARALLEL_WORKERS}"
    )
    
    if not confirm_proceed(summary):
        print("Cancelled.")
        return 0

    workers = PARALLEL_WORKERS
    provider_label = provider.upper()
    print(
        f"[{provider_label} Bundle Judge] Grading {len(bundle_files)} bundles (type {bundle_type})  "
        f"prompt={prompt_name}  rubric={rubric_name}  parallel={workers}"
    )

    tasks: list[tuple[Path, Path]] = []
    for bf in bundle_files:
        tasks.append((bf, _output_path_for(bf, bundle_type, provider)))

    global _progress_done
    _progress_done = 0
    total = len(tasks)
    all_scores: list[dict[str, Any]] = []
    failed = 0

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _grade_one_bundle, bf, out,
                    provider=provider,
                    prompt_name=prompt_name, 
                    rubric_name=rubric_name,
                ): (bf, out)
                for bf, out in tasks
            }
            for future in as_completed(futures):
                bf, _ = futures[future]
                try:
                    info = future.result()
                    all_scores.append(info)
                    _print_result(info, total, provider)
                except Exception as error:  # Catch both JudgeError and import errors
                    failed += 1
                    with _progress_lock:
                        _progress_done += 1
                        n = _progress_done
                    print(
                        f"[{provider_label} Bundle Judge] [{n}/{total}] FAILED "
                        f"bundle={bf.name}: {error}"
                    )
    except KeyboardInterrupt:
        print(f"\n{provider_label} bundle judging interrupted.")
        return 130

    scores_only = [s["score"] for s in all_scores]
    mean_score = sum(scores_only) / len(scores_only) if scores_only else 0.0
    print(
        f"\n[{provider_label} Bundle Judge] Done. "
        f"graded={len(all_scores)}  failed={failed}  "
        f"mean={mean_score:.1f}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: get config via interactive prompts or args, then run bundle judging."""
    args = _parse_args()
    
    # Determine if we should use interactive mode
    use_interactive = not all([args.provider, args.bundle_type, args.prompt, args.rubric])
    
    try:
        if use_interactive:
            provider, bundle_type, prompt_name, rubric_name = _get_interactive_config()
        else:
            provider = args.provider
            bundle_type = args.bundle_type
            prompt_name = args.prompt
            rubric_name = args.rubric
            
            # Validate that all required args are provided
            if not provider:
                print("Error: --provider is required in non-interactive mode")
                return 1
            if not bundle_type:
                print("Error: --bundle-type is required in non-interactive mode")
                return 1
            if not prompt_name:
                print("Error: --prompt is required in non-interactive mode")
                return 1
            if not rubric_name:
                print("Error: --rubric is required in non-interactive mode")
                return 1
        
        return _run_bundle_judging(provider, bundle_type, prompt_name, rubric_name)
        
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}")
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

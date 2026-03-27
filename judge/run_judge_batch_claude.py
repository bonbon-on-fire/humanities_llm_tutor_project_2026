"""Claude-based batch judge for humanities tutor transcript bundles."""

from __future__ import annotations

# ========================================
# BATCH RUNNER CONFIGURATION
# ========================================
BATCH_TYPE = 1  # Change to 1, 2, or 3 to run all batches of that type
RUN_ALL_BATCHES = False  # Set to True to run all batches of BATCH_TYPE
# ========================================

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import NotRequired, TypedDict

from judge.run_judge_gpt import (
    JudgeError,
    JudgeResult,
    TRANSCRIPTS_DIR,
    _env_truthy,
    _extract_text_from_model_content,
    _format_conversation_for_judge,
    _judge_repair_prompt,
    _order_grade_payload,
    _parse_json_from_model_output,
    _sanitize_grade_payload,
    _validate_grade_payload,
    load_judge_prompt,
)

_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
_MAX_ATTEMPTS = 3


def _require_anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise JudgeError("ANTHROPIC_API_KEY environment variable is required but not set.")
    return key


def _load_transcript_batch(batch_file_path: Path) -> list[dict[str, Any]]:
    """Load a batch of transcripts from a .txt file listing transcript paths."""
    if not batch_file_path.exists():
        raise JudgeError(f"Batch file not found: {batch_file_path}")
    
    transcript_paths = []
    for line in batch_file_path.read_text(encoding="utf-8").strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        transcript_paths.append(line)
    
    if not transcript_paths:
        raise JudgeError(f"No transcript paths found in batch file: {batch_file_path}")
    
    transcripts = []
    for path_str in transcript_paths:
        transcript_path = TRANSCRIPTS_DIR / f"{path_str.strip()}.json"
        if not transcript_path.exists():
            raise JudgeError(f"Transcript not found: {transcript_path}")
        
        try:
            transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise JudgeError(f"Invalid JSON in transcript {transcript_path}: {e}") from e
        
        if not isinstance(transcript, dict):
            raise JudgeError(f"Transcript must be an object: {transcript_path}")
        
        exchanges = transcript.get("exchanges")
        if not isinstance(exchanges, list) or not exchanges:
            raise JudgeError(f"Transcript must contain non-empty 'exchanges' array: {transcript_path}")
        
        transcript["_source_path"] = path_str.strip()
        transcripts.append(transcript)
    
    return transcripts


def _format_batch_for_judge(transcripts: list[dict[str, Any]]) -> str:
    """Format multiple transcripts as a single judge input."""
    lines: list[str] = [f"Batch of {len(transcripts)} transcripts to grade together:"]
    lines.append("")
    
    for i, transcript in enumerate(transcripts, 1):
        lines.append(f"=== TRANSCRIPT {i} ===")
        lines.append(f"Source: {transcript.get('_source_path', 'unknown')}")
        lines.append("")
        lines.append(_format_conversation_for_judge(transcript))
        lines.append("")
    
    return "\n".join(lines)


class _JudgeState(TypedDict):
    attempts: int
    system_prompt: str
    conversation_text: str
    num_turns: int
    last_output: NotRequired[str]
    last_error: NotRequired[str]
    grade_json: NotRequired[list[dict[str, Any]]]


def _create_batch_judge_graph(*, model_name: str, api_key: str, enforce_sub_criterion_ids: bool, rubric_name: str, num_transcripts: int):
    model = ChatAnthropic(model=model_name, temperature=0, api_key=api_key)

    def judge_node(state: _JudgeState) -> dict[str, Any]:
        messages = [SystemMessage(content=state["system_prompt"])]
        if state.get("last_error") and state.get("last_output"):
            messages.append(
                HumanMessage(
                    content=_judge_repair_prompt(state["last_error"])
                    + "\n\nPrevious JSON (to repair):\n"
                    + state["last_output"]
                )
            )
        messages.append(HumanMessage(content=state["conversation_text"]))
        resp = model.invoke(messages)
        content = _extract_text_from_model_content(resp.content)
        return {"last_output": content, "attempts": int(state.get("attempts", 0)) + 1}

    def validate_node(state: _JudgeState) -> dict[str, Any]:
        try:
            parsed = _parse_json_from_model_output(state.get("last_output", ""))
            if not isinstance(parsed, list):
                raise JudgeError(f"Expected JSON array for batch, got {type(parsed).__name__}")
            if len(parsed) != num_transcripts:
                raise JudgeError(f"Expected {num_transcripts} grades in batch, got {len(parsed)}")
            
            validated_grades = []
            for i, grade in enumerate(parsed):
                if not isinstance(grade, dict):
                    raise JudgeError(f"Grade {i+1} must be an object, got {type(grade).__name__}")
                grade = _sanitize_grade_payload(grade)
                validated = _validate_grade_payload(
                    grade,
                    num_turns=10,  # Approximate; batch validation is less strict on turn counts
                    enforce_sub_criterion_ids=enforce_sub_criterion_ids,
                    rubric_name=rubric_name,
                )
                validated_grades.append(_order_grade_payload(validated))
            
            return {"grade_json": validated_grades, "last_error": None}
        except JudgeError as e:
            return {"grade_json": None, "last_error": str(e)}

    graph = StateGraph(_JudgeState)
    graph.add_node("judge", judge_node)
    graph.add_node("validate", validate_node)
    graph.add_edge(START, "judge")
    graph.add_edge("judge", "validate")

    def route(state: _JudgeState) -> str:
        if state.get("grade_json") is not None:
            return END
        return END if int(state.get("attempts", 0)) >= _MAX_ATTEMPTS else "judge"

    graph.add_conditional_edges("validate", route, {"judge": "judge", END: END})
    return graph.compile()


def judge_transcript_batch(
    batch_file_name: str,
    *,
    prompt_name: str = "judge_05",
    rubric_name: str = "rubric_05",
    output_name: str | None = None,
    batch_file_path: str | None = None,
) -> list[JudgeResult]:
    """
    Judge a batch of transcripts together using Claude.
    
    Args:
        batch_file_name: Path to .txt file containing transcript paths (one per line)
        prompt_name: Judge prompt to use
        rubric_name: Rubric to use
        output_name: Optional output file stem (defaults to batch_file_name stem)
        batch_file_path: Optional custom path to batch file (overrides batch_file_name)
    
    Returns:
        List of JudgeResult objects, one per transcript in the batch
    """
    if batch_file_path is not None:
        batch_file_path = Path(batch_file_path)
    else:
        batch_file_path = Path("judge/transcript_batches") / f"{batch_file_name}.txt"
    transcripts = _load_transcript_batch(batch_file_path)
    
    model_name = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_ANTHROPIC_MODEL)
    graph = _create_batch_judge_graph(
        model_name=model_name,
        api_key=_require_anthropic_api_key(),
        enforce_sub_criterion_ids=rubric_name.strip().lower() in {"rubric_04", "rubric_05"},
        rubric_name=rubric_name.strip().lower(),
        num_transcripts=len(transcripts),
    )
    
    # Format batch prompt
    system_prompt = load_judge_prompt(prompt_name=prompt_name, rubric_name=rubric_name)
    batch_prompt = (
        system_prompt + "\n\n"
        "BATCH GRADING INSTRUCTIONS:\n"
        "You are grading multiple transcripts together. For each transcript, provide a separate "
        "complete grade JSON object. Return a JSON array where each element is a full grade "
        "for one transcript, in the same order as presented.\n\n"
        "Format: [{grade_for_transcript_1}, {grade_for_transcript_2}, ...]\n\n"
    )
    conversation_text = _format_batch_for_judge(transcripts)
    
    result = graph.invoke({
        "attempts": 0,
        "system_prompt": batch_prompt,
        "conversation_text": conversation_text,
        "num_turns": sum(len(t.get("exchanges", [])) for t in transcripts),
    })
    
    grade_json = result.get("grade_json")
    if grade_json is None:
        last_error = str(result.get("last_error") or "unknown validation error")
        last_output = str(result.get("last_output") or "")
        # Note: batch failures don't use the single-transcript debug writer
        raise JudgeError(f"Batch judge failed to produce valid grade JSON. Last error: {last_error}")
    
    results = []
    output_stem = output_name or batch_file_path.stem
    
    for i, (transcript, grade_payload_raw) in enumerate(zip(transcripts, grade_json)):
        if not isinstance(grade_payload_raw, dict):
            raise JudgeError(f"Grade {i+1} must be an object, got: {type(grade_payload_raw).__name__}")
        
        grade_payload = dict(grade_payload_raw)
        grade_payload["model"] = {
            "provider": "anthropic",
            "model": model_name,
            "temperature": 0,
        }
        grade_payload["judge_llm_calls"] = int(result.get("attempts", 0))
        if _env_truthy("JUDGE_INCLUDE_TIMESTAMP"):
            grade_payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        grade_payload = _order_grade_payload(grade_payload)
        
        # Write individual graded transcript
        out_transcript = dict(transcript)
        out_transcript.pop("_source_path", None)
        out_transcript.pop("grade", None)
        out_transcript["grade"] = grade_payload
        
        source_path = TRANSCRIPTS_DIR / f"{transcript['_source_path']}.json"
        output_path = source_path.with_name(f"{output_stem}_batch_{i+1:02d}__{prompt_name}__{rubric_name}__claude.json")
        output_path.write_text(json.dumps(out_transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        
        results.append(JudgeResult(
            total_score=int(grade_payload["total_score"]),
            max_score=int(grade_payload["max_score"]),
            output_path=output_path,
        ))
    
    return results


def run_all_batches_of_type(batch_type: int) -> None:
    """Run all batches for a specific batch type."""
    # Batch type configuration
    batch_configs = {
        1: {"count": 72, "name": "consistency"},
        2: {"count": 54, "name": "cross_exercise"},
        3: {"count": 72, "name": "persona_diff"}
    }
    
    if batch_type not in batch_configs:
        print(f"❌ Invalid batch_type: {batch_type}. Must be 1, 2, or 3.")
        return
    
    config = batch_configs[batch_type]
    batch_prefix = f"batch_{batch_type:02d}"
    experiment_name = config["name"]
    total_batches = config["count"]
    
    print(f"🚀 Starting Claude {experiment_name} experiment")
    print(f"📁 Processing {total_batches} batches: {batch_prefix}_001.txt through {batch_prefix}_{total_batches:03d}.txt")
    print()
    
    results = []
    failed_batches = []
    
    for i in range(1, total_batches + 1):
        batch_file = f"judge/transcript_batches/{batch_prefix}_{i:03d}.txt"
        output_name = f"{experiment_name}_claude_{i:03d}"
        
        print(f"Processing {batch_prefix}_{i:03d}.txt... ", end="", flush=True)
        
        try:
            batch_results = judge_transcript_batch(
                "unused",
                batch_file_path=batch_file,
                output_name=output_name
            )
            results.extend(batch_results)
            print(f"✅ {len(batch_results)} transcripts graded")
        except Exception as e:
            failed_batches.append((i, str(e)))
            print(f"❌ FAILED: {e}")
    
    # Summary
    print()
    print("=" * 50)
    print("📊 EXPERIMENT SUMMARY")
    print("=" * 50)
    print(f"Experiment: {experiment_name} (Type {batch_type:02d})")
    print(f"Total batches: {total_batches}")
    print(f"Successful: {total_batches - len(failed_batches)}")
    print(f"Failed: {len(failed_batches)}")
    print(f"Total transcripts processed: {len(results)}")
    
    if failed_batches:
        print("\n❌ Failed batches:")
        for batch_num, error in failed_batches:
            print(f"  - {batch_prefix}_{batch_num:03d}.txt: {error}")
    
    print(f"\n🎉 Claude {experiment_name} experiment complete!")


if __name__ == "__main__":
    if RUN_ALL_BATCHES:
        run_all_batches_of_type(BATCH_TYPE)
    else:
        print("Set RUN_ALL_BATCHES = True to run batch experiments")
        print(f"Current configuration: BATCH_TYPE = {BATCH_TYPE}")
        print("Available batch types:")
        print("  1 = Consistency experiment (72 batches)")
        print("  2 = Cross-exercise experiment (54 batches)")
        print("  3 = Persona differentiation experiment (72 batches)")
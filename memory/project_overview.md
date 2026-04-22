---
name: Project overview
description: Core architecture, goals, and current state of the Humanities LLM Tutor Project 2026
type: project
---

Socratic LLM tutor for MIT OpenCourseWare (OCW) humanities/social sciences courses. Never gives answers directly — uses guided discovery and Socratic questioning.

**Why:** Deployment goal = reliable Socratic tutor for OCW students. Validation goal = reproducible eval framework to test/grade tutor behavior before deployment.

**Four layers:**
1. Conversation pipeline — LangGraph tutor + student agents trading messages
2. Judge pipeline — separate LangGraph agent scores finished transcripts against a rubric (JSON grade, up to 3 repair retries)
3. UI runners — `ui/run_ui_raw.py` (bulk transcript generation), `ui/run_ui_judge.py` (grading), `ui/run_ui_raw_mini.py` (single-transcript resume/replay)
4. Dashboard + visualization — Flask app for browsing GPT/Claude grades side-by-side; matplotlib correlation charts

**Current rubric:** `rubric_05` (46 pts): Pedagogy (24), Dialogue Quality (12), Communication Quality (10)

**Scale:** 18 personas (chaotic/cooperative/clueless × 6), 2 courses (philosophy + urban_studies), 864 total transcripts, graded by both GPT and Claude judges.

**Active work (as of 04/16/2026):**
- Iterating on tutor prompt (tutor_05 in progress)
- Planning two-layer agentic tutor (rubric-aware verifier pre-screens output, max 1 retry/turn)
- Implementing `run_ui_mini` restore-at-turn-X semantics
- Curating working transcript set for prompt iteration

**How to apply:** Frame suggestions around the LangGraph architecture, prompt-file versioning pattern, and rubric-driven evaluation workflow.

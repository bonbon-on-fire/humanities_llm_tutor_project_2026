---
name: Active action items (04/16/2026 meeting)
description: Open tasks from the 04/16/2026 meeting between Nishita and Romain
type: project
---

From the 04/16/2026 meeting (Nishita Bhakar + Romain Puech):

**Decisions made:**
- Lock transcript set → iterate tutor → finalize prompt → explore structures → new transcripts → evaluate next meeting
- Two-layer tutor re-generation capped at one retry per turn
- Three prompt variants sufficient until next meeting

**Open action items:**
- [ ] Update `run_ui_mini` restore-at-turn-X: keep history through turn X−1, student-only at turn X, tutor leads turn X
- [ ] Audit `run_ui_mini` pipeline: ensure past pedagogical reasoning is NOT passed into subsequent tutor calls
- [ ] Spike: measure latency with vs without pedagogical reasoning (for two-layer tutor)
- [ ] Curate working transcript list (chaotic 0007, 0015, 0079, 0097; clueless 0013, 0025, 0218, 0123, 0242, 0248, 0297)
- [ ] Run tutor iteration on chosen transcripts; finalize prompt before structural experiments
- [ ] Draft two-layer tutor spec (rubric-aware verifier, max one re-run, internal "resolved challenge" state option)
- [ ] Design comparison-based mini-turn judge (random turn, run_ui_mini, side-by-side diff)

**Reference transcripts (violation examples):**
- chaotic 0007 T3, 0015 T8, 0097 T5 → violates 1.1.C (overly comprehensive solution)
- chaotic 0079 T6 → tutor kept helping when convo should have ended
- clueless 0013 T1 → violates 1.2.B (explains instead of asking diagnostic questions)
- clueless 0025 T9 → violates 3.1.A (wall of text)
- clueless 0218 T7 → violates 3.2.A (tone too harsh)
- clueless 0123 T8 → **positive benchmark** (keep as regression reference)
- clueless 0242 T2 → procedural question (submit assessment) — tutor should answer directly, not be Socratic
- clueless 0248 T3 → tutor agrees too readily with nonsensical student content
- clueless 0297 T8 → good pattern: tutor points student to online exercise

**Why:** Nishita and Romain are mid-cycle iterating on the tutor prompt before exploring architectural changes (two-layer tutor). The transcript set is the anchor for prompt quality evaluation.

**How to apply:** When suggesting tutor prompt changes or pipeline modifications, ground them in the specific failure modes and reference transcripts above.

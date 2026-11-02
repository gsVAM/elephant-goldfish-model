# Test Plan: EGM Handoff Skill

<!-- Added by the elephant-goldfish-model Astra fork (gsVAM), 2026. -->

Frontmatter and link checks run in `pytest tests/unit` (see [TESTING.md](../../TESTING.md)). The helper `scripts/egm_handoff.py` is covered by `tests/unit/test_egm_handoff.py` with an in-process fake `gh`: plan parsing, graph and waves, rendered bodies, the scan, the gate hashes, the dry run, `apply` and `verify`, `status`, `prepare` and `decide`.

## Protocol Verification Checklist

When evaluating or exploring `egm-handoff` interactively in chat, verify:

-   **Step 1 (Approval):** The design is tracked and clean and has an implementation plan; the approval is one question (Approve or Stop) recorded with the design's sha256 and commit; a report is never taken as the approval.
-   **Step 2 (Units):** `handoff_plan.md` follows `references/handoff_plan.md`; `graph` stops on an unknown reference, a cycle or a shared-file chain that contradicts the blockers.
-   **Step 3 (Gate):** `egm-review-loop` runs at Stage 10 on the plan with the panel's reviewers and `handoff-standard.md`; the reviewed pair of hashes is recorded before each round; the gate passes only on a clean round after which nothing changed.
-   **Step 4 (Readiness):** One fresh readiness goldfish per unit; questions triaged as answered, fix-unit, fix-design or people; a changed plan goes back through one more Stage 10 round.
-   **Step 5 (Dry run and confirmation):** `dry-run` refuses when the plan or the bodies changed after the gate; the confirmation question names the repository and the counts; `apply --yes` runs only after Create.
-   **Step 6 (Verify):** The receipt is complete and clean before the wave skill is offered.

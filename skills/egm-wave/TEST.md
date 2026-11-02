# Test Plan: EGM Wave Skill

<!-- Added by the elephant-goldfish-model Astra fork (gsVAM), 2026. -->

Frontmatter and link checks run in `pytest tests/unit` (see [TESTING.md](../../TESTING.md)). The helper subcommands the skill uses (`status`, `launch`, `defer`, `decide`, `prepare`) are covered by `tests/unit/test_egm_handoff.py` with an in-process fake `gh` and a scratch git repository.

## Protocol Verification Checklist

When evaluating or exploring `egm-wave` interactively in chat, verify:

-   **Entry:** The skill refuses without a complete, clean verify receipt bound to the current `confirmed_sha256`; every entry starts with one `status` pass.
-   **Launch gate:** `wave_<n>_plan.md` lists the ready units with the run card; one question: launch, change the set, answer a blocking decision, or stop.
-   **Foreman:** one per in-flight unit, named `foreman-<unit>` where the Agent tool accepts `name` (an addressable, resumable subagent), otherwise one fresh subagent per step. Goldfish are always spawned through their own adapters.
-   **Round:** The foreman prepares (worktree, diff, CI file, brief, launch line); the elephant launches the runner from the main conversation with `run_in_background: true` and the Bash timeout; the foreman collects and reports one line.
-   **Findings:** One review comment per round, posted by the elephant after the user confirms; never `--approve` or `--request-changes`; the review ends on the first converged round (clean and no finding attributable to the previous round's fixes, each marked `regression: yes|no`); cap 5 rounds, then pause for the user.
-   **Human steps:** Ready for review, approve, merge, close and branch deletion stay with people.

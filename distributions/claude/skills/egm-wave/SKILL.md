---
name: egm-wave
license: Apache-2.0
disable-model-invocation: true
description: >-
  Launches the next wave of a handoff's GitHub issues, watches each in-flight
  issue through a foreman (an agent-teams teammate or fresh subagents), runs
  the single review (Astra inspect lane plus Claude goldfish) on every PR
  head with CI as evidence, posts one confirmed review comment per round,
  and detects landed units. Builders are external; shipping stays human.
  Claude Code only.
---

<!-- Added by the elephant-goldfish-model Astra fork (gsVAM), 2026: the wave skill. Not part of google/elephant-goldfish-model. -->

# Wave: launch, review and land a handoff's units

When running in Codex or ChatGPT Work, first read [Codex integration](../../docs/codex.md).
In Claude Code or Cowork, read `${CLAUDE_PLUGIN_ROOT}/docs/claude.md` first.

This skill runs in Claude Code only. In any other host reply with one line,
`egm-wave runs in Claude Code only`, and stop.

## What it does

A handoff filed by `/egm:egm-handoff` has issues on GitHub and a state file.
This skill launches the units whose incoming edges have landed, assigns a
**foreman** to each in-flight issue, and runs one review per PR head: the
Astra `inspect` lane through the claudex-loop runner plus the panel's Claude
goldfish (`egm-change-review`, and `egm-codebase-details` in the Full panel)
on the PR diff, with the CI results as evidence. Findings go to the PR as
one review comment per round after the user confirms it; the builder fixes;
the next head starts the next round; the review ends on the first clean
round, cap 3. A unit lands when its issue is closed as completed and its
watched PR is merged.

**Builder backend: external only.** The issues are built by whoever picks
them up: an agent fleet, a coding-agent service, a person. Dispatch of
builders to cloud sandboxes (lb) is planned and not in this release; if the
user asks the skill to dispatch a builder, say so in one line and continue
with external builders. **What stays human**: marking a PR ready, approving,
merging, closing issues, deleting branches, editing issues after creation
(except the wave label on deferral). The foreman and the elephant never push
to a PR branch and never use `--approve` or `--request-changes`.

## Inputs

*   **`HandoffState`**: path of `handoff_state.json`.
*   **`Wave`** (optional): a number; default the next wave with ready units.
*   **`Panel`** (optional): `astra | focused | full` (`resources/review_panels.md`).

`<HELPER>` = `${CLAUDE_PLUGIN_ROOT}/skills/egm-handoff/scripts/egm_handoff.py`;
`<STATE>` = `HandoffState`. One command per Bash call, absolute paths in
single quotes, no chaining. The helper's commands are listed in
`skills/egm-handoff/references/handoff_plan.md` section 6.

## Entry: one status pass

1.  Read `resources/review_panels.md` section 1 (the `printenv` command now
    also reads `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`), the allowlists, the
    Astra preflight and the run card. The card gets the two rows of
    `resources/review_panels.md` section 2 for this skill (Builder,
    Foreman) and the readiness line.
2.  Run `python3 '<HELPER>' status --state '<STATE>'`. It refuses unless the
    state holds a verify receipt that is `complete: true`, bound to the
    current `confirmed_sha256`, with an empty problem list: `the handoff is
    not fully created and verified: run apply --yes, then verify`. Tell the
    user that line and stop; a partial handoff is never launched.
3.  The pass reports, over all units: landed and ready sets, each launched
    unit's PR, head, CI and landed state, candidate PRs, open blocking
    decisions, and open PRs that close issues of units not yet launched (the
    user can launch those units now or ignore them). **Ready** = every
    incoming graph edge has landed (blockers and shared-file `after`
    predecessors, the edges `graph` used for the waves) and no `decide
    before build` item with `blocking: yes` is open. Waves are the plan;
    readiness is the live rule, so a later unit whose edges landed early may
    start when the user agrees.
4.  **Landed** = the issue is closed with `state_reason: completed` and the
    recorded PR has `mergedAt`. An issue closed without a watched PR shows
    `closed (no watched PR)` and lands only when the user confirms it at the
    wave gate (`status --confirm-landed U03`).
5.  **Re-entry** (a later session): the skill is re-entrant from
    `handoff_state.json`, `wave_<n>_plan.md` and `foreman_<id>_state.json`
    alone. Re-read the foreman files, mark a run folder left `running` as
    `not run (killed)`, respawn a foreman per unit still in flight, and
    continue.

## The wave gate

1.  Write `wave_<n>_plan.md`: the run card, the ready units (critical-path
    units first) each with its issue URL, its branch
    `egm/<handoff-id>/<unit-id>` and its foreman arrangement, the open
    blocking decisions with owner and default, the candidates, and the
    in-flight units' state.
2.  Ask one question: launch, change the set (exclude or defer a unit, which
    also defers its dependents), answer an open blocking decision, or stop.
    *   **Defer**: `python3 '<HELPER>' defer --state '<STATE>' --unit U05
        --to-wave <n+1> --yes` (one `gh issue edit` of the wave label,
        verified; the issue is kept). Listed in the plan before it runs.
    *   **Decide**: the user answers in chat; run `python3 '<HELPER>' decide
        --state '<STATE>' --unit U03 --decision D1 --answer '<text>'`. It
        records the answer, re-renders `unit_U03.md` and writes
        `decision_comment_U03_D1.md`. Run `scan --state '<STATE>' --comment
        '<that file>'`, then, with the user's confirmation in the same gate,
        post it once: `gh issue comment <n> -R O/R --body-file '<path>'` (a
        comment with the same first line is not posted twice). An answer
        that changes scope paths or the definition of done is a plan change,
        not a decision: the user edits `handoff_plan.md` and the issue by
        hand, `graph` re-renders, and one readiness goldfish (as in
        `egm-handoff` step 4) re-reads that unit before launch.
    *   **Candidate PR** (a head branch of this handoff with no closing
        reference): watched only after the user confirms it, `status
        --watch U03=412`.
3.  On launch run `python3 '<HELPER>' launch --state '<STATE>' --wave <n>
    --units U03 U04`, then spawn one foreman per launched unit (below).

## The foreman

In the model's own terms the foreman is a **per-unit elephant**: it carries
context across rounds for one build unit, holds that context in
`foreman_<id>_state.json`, and delegates to goldfish. It is not a goldfish and
must never be given a goldfish's lens. The **builder is external** in this
release and is not an EGM agent; the unit issue is nevertheless written to be
executed with no conversational history, which is why `egm-handoff` renders a
self-contained body. Goldfish stay what they are: zero-context, read-only
reviewers.

Read `references/foreman_brief.md` and pass its brief verbatim with the
values filled in. One foreman per in-flight issue, at most 5 at once.

*   **With agent teams** (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is `1` and
    the session is interactive): spawn a teammate with the Agent tool and
    `name: foreman-<unit-id>`, an in-process teammate that shares this
    checkout and files, idles between rounds and acts when you message it.
    A teammate cannot run a background command and its work ends with this
    session; `/resume` does not restore teammates (re-entry respawns them).
*   **Without teams** (flag unset or `0`, or a `-p` session): each foreman
    step is a fresh subagent spawned without `name`, with the same brief and
    the unit's `foreman_<id>_state.json` as its memory. Step 1 (`prepare`)
    returns the launch line; step 2 (collect, goldfish, report) returns the
    one-line status. Subagents may nest to spawn their goldfish.
*   **Reviewer isolation**: goldfish and synthesizer Agent calls never pass
    `name`; only the foreman spawn does. With the teams flag on, a named
    Agent call becomes a teammate that loads CLAUDE.md and loses the
    adapter's `omitClaudeMd: true`.
*   The foreman never launches the claudex runner, never writes to GitHub,
    never edits the user's working tree, and writes only its own state file
    and round files. It reports one line: `foreman U03: pr #412 head
    3e1f2a7 round 2 status <state> verdict <verdict> run <folder or ->
    report <path>`.

## A round

1.  **A new head.** `status` reports, for an in-flight unit, a PR head whose
    CI is concluded: every check run `completed` and the combined status not
    `pending`; `ci green` when every conclusion is `success`, `neutral` or
    `skipped` and the combined state is `success` (or no statuses), else
    `ci red (<names>)`. The review runs on a concluded head either way, with
    the result as evidence. Zero check runs and zero statuses is
    `waiting-for-ci`; 30 minutes without any, `no-ci`: ask the user to wait
    or to review without CI (a workflow on a coding agent's push may need a
    person's approval first).
2.  **Prepare.** Message the foreman (or spawn step 1). It runs `prepare`
    (fetch from the recorded remote into `refs/egm/pr/<n>` and
    `refs/egm/base/<n>`, the head checked against `status` or `head-moved`,
    a worktree under `${TMPDIR:-/tmp}/egm-wave/<handoff-id>/<unit-id>/pr<n>/`,
    the diff from the merge base saved as `pr_<n>_r<r>.diff`, the CI read
    saved as `ci_<n>_r<r>.json`), writes the brief and the launch line, and
    reports `prepared`. A leftover worktree from an interrupted round is
    removed when it is clean and no run of it is still `launched`; a dirty
    one stops with `remove it by hand`.
3.  **Launch** (the elephant, from this main conversation, never a
    subagent). Read `foreman_<id>_r<r>_launch.md`; check the line against
    `resources/astra_lane.md` section 3b (single quotes, no chaining,
    validated literals, `--base` present, no `--resume`); run it with
    `run_in_background: true` and the Bash `timeout` 3,900,000 ms; record
    the run folder from the first JSON line; send it to the foreman. The
    runner fails a run whose tree changed: nothing touches the worktree
    while it runs. When the lane is not available (`astra_lane.md` section
    8) skip this step and tell the foreman `not run (<reason>)`.
4.  **Collect.** When the completion notice arrives, message the foreman (or
    spawn step 2). It reads `result.json`, maps the findings
    (`astra_lane.md` sections 5 and 6), spawns the panel's goldfish in the
    foreground (Astra only: none; Focused: `egm-change-review` on
    `unit_<id>.md` with the worktree, the diff and the CI file; Full: plus
    `egm-codebase-details` in REVIEW mode on the design range with the
    worktree as the codebase), writes `wave_round_u<id>_r<r>.md` with the
    run card and the `What ran` lines, removes the worktree, and reports.
    A lane that did not complete is `not run` with the reason and the round
    is judged on the Claude goldfish (Astra only: not clean).
5.  **Findings to the PR.** Write `pr_comment_<n>_r<r>.md`: the configured
    `fix_request_mention` on the first line when the repository has one,
    then `**EGM review round <r> (head <sha7>)**`, the findings table
    (severity, path:line, evidence, fix), the definition-of-done checklist
    (met or not, evidence) and the CI summary; no run card, no model names.
    Run `scan --state '<STATE>' --comment '<path>'`. List the PR's reviews
    first (`gh api repos/O/R/pulls/<n>/reviews --paginate --slurp`) so a
    comment with the same header is not posted twice. Ask one question
    (post, edit, skip), then `gh pr review <n> -R O/R --comment --body-file
    '<path>'`, one Bash approval. Record the user's dispositions in
    `wave_dispositions_u<id>_r<r>.md` with the five columns of
    `egm-resolve`'s table (from the user's decision, never the AI
    suggestion); the next round's brief carries the `astra-*` rows.
6.  **Stop rule.** A round is clean when no Blocker or Major is unsettled
    (settled = contested or declined by the user). The review ends on the
    first clean round (one, not two: each round costs an inspect run and a
    round of builder time). Cap 3 rounds; then the open findings go to the
    user in one line and into the report. The comment is the fix request;
    the next round starts when `status` reports a new head with CI
    concluded.
7.  **Landed.** When the unit lands, shut the foreman down by name (or stop
    spawning steps), run `prepare --state '<STATE>' --unit U03 --clean`
    (refs deleted, worktree list pruned), and record it in the wave report.

## Advancing the wave

GitHub does not call back and external builders take hours or days. In an
interactive session run `python3 '<HELPER>' status --state '<STATE>'
--wait 1500` with `run_in_background: true` from this main conversation: it
repeats the same reads every 90 seconds and exits, printing the changed unit
ids, when any in-flight unit's PR, head, CI or landed state changes or the
deadline passes; relaunch it until the wave ends and act only on the units
it names. The alternative, and the path in a later session, is to re-run
`/egm:egm-wave` (or `/loop 30m /egm:egm-wave`): each run does one status
pass and acts on what changed. In a `-p` run background commands stop after
30 minutes (10 when the prompt is passed as text), so `--wait` is at most
1500 there. The wave ends when every launched unit has landed or been
deferred; write `wave_<n>_report.md` (rounds, findings, dispositions, what
stayed open, the `What ran` lines) and offer the next wave.

## Run card rows and the Astra lane

The card of `resources/review_panels.md` section 2 plus `Builder | external:
whoever picks up #<n>; model unknown | - | -` and `Foreman | teammate
foreman-<id> (or: fresh subagents per step); issue, PR diff, CI results, no
conversation | <session or CLAUDE_CODE_SUBAGENT_MODEL> -> effective | session
setting`. The inspect launch, its Bash timeout, the data notice (the PR diff
and every changed file go to OpenAI) and the time line are in
`resources/astra_lane.md` section 3b. The card is in `wave_<n>_plan.md` and
at the top of every foreman report; never in GitHub text.

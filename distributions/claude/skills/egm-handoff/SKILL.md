---
name: egm-handoff
license: Apache-2.0
disable-model-invocation: true
description: >-
  Turns an approved EGM design into build units, a dependency graph with
  waves, and GitHub issues (tracking issue, sub-issues, blocked-by links)
  after an adversarial review gate, a readiness test, a dry run and the
  user's confirmation. Use when a reviewed design is approved and the build
  should be filed as issues before a wave starts. Claude Code only.
---

<!-- Added by the elephant-goldfish-model Astra fork (gsVAM), 2026: the handoff skill. Not part of google/elephant-goldfish-model. -->

# Handoff: approved design to reviewed GitHub issues

When running in Codex or ChatGPT Work, first read [Codex integration](../../docs/codex.md).
In Claude Code or Cowork, read `${CLAUDE_PLUGIN_ROOT}/docs/claude.md` first.

This skill runs in Claude Code only, as the Astra lane does. In any other
host reply with one line, `egm-handoff runs in Claude Code only`, and stop.

## What it does

An approved design (Phase 4: reviewed, Stage 9 passed, checked in) becomes
`handoff_plan.md`: one build unit per phase of the design's implementation
plan. A standard-library helper turns the units into a graph, waves, a
critical path and rendered issue bodies. The plan and the bodies pass an
**adversarial review gate** (Stage 10 of `egm-review-loop`, the fork's
panels, `resources/document_standards/handoff-standard.md`) and a
**readiness test** (one fresh goldfish per unit) before a **dry run** is
shown and the user confirms **one question**. Only then does the helper
create the labels, the tracking issue, the unit issues, the sub-issue and
blocked-by links, verifying every write. The wave skill (`/egm:egm-wave`)
launches the units later. Builders are external in this release: whoever
picks up an issue builds it. Dispatch of builders to cloud sandboxes (lb) is
planned and not in this release.

Nothing is posted to GitHub before the gate passed, the dry run was written
and the user chose Create. Every GitHub write is one Bash approval of the
helper; no prefix allow rule is added. No run card, model name or reviewer
name appears in any GitHub text.

## Inputs

*   **`DesignFile`**: absolute or relative path of the approved design.
*   **`ApprovalEvidence`** (optional): the design's
    `implementation_readiness_report.md` or `consolidated_review_report.md`.
    Shown as context in the approval question; a report is never the
    approval (a paused review or an older version leaves one on disk too).
*   **`Panel`** (optional): `astra | focused | full`, as in
    `resources/review_panels.md`; else `EGM_PANEL`, else Focused.
*   **`GoldfishContext`** (optional): extra reading list for the gate.

Ask for a missing `DesignFile` in plain chat (an open path, not a structured
question); the others have defaults.

## The helper

`<HELPER>` = `${CLAUDE_PLUGIN_ROOT}/skills/egm-handoff/scripts/egm_handoff.py`
(Python 3.10 or later, standard library only; `gh` 2.x logged in). Run every
command as one Bash call, `python3 '<HELPER>' <subcommand> ...`, absolute
paths in single quotes, no chaining, pipes, redirects or environment
variables; the Bash `timeout` is the default. The commands and the files they
write are in `references/handoff_plan.md` section 6; the issue template is
`references/issue_template.md`; the repository config `.egm/handoff.json`
(repo, labels, template, banned terms, the one allowed mention) is
`references/handoff_config.md`. Every subcommand is read-only except
`apply --yes` (step 6). The artifact directory is the `EGM artifact
directory` of `docs/claude.md` or the working directory; put it outside the
repository, so Astra does not read EGM's own files.

## Step 1: Approval

1.  Read `resources/review_panels.md` section 1: the `printenv` command, the
    allowlists, the Astra preflight (`resources/astra_lane.md` section 1)
    and the run card, which gets one extra line: `Readiness test: one Claude
    goldfish per unit, every panel`. Show the card. Ask the panel (Q2 alone)
    unless `Panel` or `EGM_PANEL` named it.
2.  Run `python3 '<HELPER>' approve --design '<DesignFile>' --artifacts
    '<ARTIFACT_DIR>' [--evidence '<ApprovalEvidence>']`. It checks what can
    be checked: the file is tracked and clean (`git status --porcelain`
    prints nothing, run at the design's git top level), the evidence names
    the file, and the design has `## Detailed Implementation Plan` with
    `### Target Files to Create/Modify` and `### Verification Plan`. A
    design with no implementation plan (`DetailedRange = N/A`) is refused:
    tell the user to run `egm-draft` and `egm-review` first. None of these
    checks is the approval.
3.  Ask the question the helper printed, as the sole tool call in the turn,
    with the options Approve and Stop: `Approve <DesignFile> (sha256
    <first 12 hex>, commit <short sha>) for handoff? Evidence: <report path>
    (modified <date>), or: none given.` On Approve run the same command with
    `--yes`: it records `approval` (path, sha256, commit, evidence) in
    `handoff_state.json`. Every later command compares the design's sha256
    with it and stops with `design changed since the handoff started: re-run
    the gate`.

## Step 2: Units, graph and bodies

1.  Write `<ARTIFACT_DIR>/handoff_plan.md` from `references/handoff_plan.md`:
    the `Design:` line, section 1 quoting the issue template in use (the
    default, or the repository's `issue_template`), and one unit per phase
    by its section 3 rules (scope paths from the phase's Target Files; the
    definition of done from the Verification Plan items plus CI green plus
    "the design range is true of the code"; blockers only where a unit
    uses what another creates or changes; shared-file chains in phase
    order; every `## Open Questions` entry and every splitting decision as a
    `decide before build` item with owner and default). No parts: a unit
    is one issue and one PR.
2.  Run `python3 '<HELPER>' graph --plan '<ARTIFACT_DIR>/handoff_plan.md'`.
    It stops on a schema deviation (with the line), an unknown reference, a
    `blocked by` cycle (listed), a shared-file chain that contradicts the
    blockers, a derived label over 50 characters, a config error, or a
    missing remote for the configured `repo` (`no remote for OWNER/NAME`:
    the user adds one or fixes `.egm/handoff.json`). It writes
    `handoff_units.json`, `unit_<id>.md` per unit, `handoff_bodies.md` and
    the generated sections of the plan (edges, waves, critical path,
    blocking decisions). Fix the plan and run it again until it passes.
3.  Tell the user the paths and the wave table in a few lines (artifact
    first; no body text in chat).

## Step 3: The adversarial review gate (Stage 10)

Required before any GitHub write; the dry run is never shown before it
passed. Read `skills/egm-review-loop/SKILL.md` and follow it in this thread
with: `TargetFile: handoff_plan.md`, `SemanticTarget: full file`,
`Stage: 10`, `AstraLane: on` when the lane is available, `RunCard`, and the
panel's reviewers with `Standards` naming the custom path
`resources/document_standards/handoff-standard.md`:

| Panel | Reviewers | GoldfishContext |
| --- | --- | --- |
| Astra only | none; the lane alone (`review` mode, `--plan` = `handoff_plan.md`) | `Reading list:` the design file and `handoff_bodies.md` |
| Focused (default) | `egm-implementation-readiness` | the design file, `handoff_bodies.md`, `GoldfishContext` |
| Full | Focused plus `egm-codebase-details` (REVIEW mode: scope paths, symbols and callers exist as the units assume) | the same, plus the repository root |

The Astra brief uses the Stage 10 range line and the handoff auditor lens of
`resources/astra_lane.md` section 2; its do-not-read list covers EGM's state
and unit files. The seven questions (coverage both ways, contradictions,
blockers and order, shared-file order, testability, decisions, rendered
bodies) are in the standard and so in both lanes. Rules on top of the loop:

*   **Reviewed pair.** Before each round's reviewers run, run `python3
    '<HELPER>' gate --plan '<plan>' --reviewed --round <n>`: it re-renders
    the bodies and records the sha256 of `handoff_plan.md` and of
    `handoff_bodies.md` as the pair this round reads.
*   **Fixes** go into `handoff_plan.md` through `egm-resolve` (`Stage: 10`;
    it writes `goldfish_dispositions_s10_r<n>.md`). After each round run
    `graph` again so the generated sections and bodies match the units. A
    finding that the design itself must change is `fix-design`: stop and
    tell the user the design goes back to `egm-review` Stage 9 for that
    range, or the user records the deviation in the unit's `decide before
    build` list.
*   **Stop rule**: `resources/review_panels.md` section 7. Clean = no
    unsettled Blocker or Major. Converged = clean **and** no finding
    attributable to the previous round's fixes (mark each finding
    `regression: yes|no`); for this gate, also two consecutive clean rounds,
    because a document round is cheap. Report the trend per round. **Cap 5
    rounds, then pause**: the user chooses accept, continue or return to the
    design, and round 6 never starts without their answer. Churn stops.
*   **Pass.** The loop judges a round clean before its fixes are applied,
    so the gate passes only on a clean round after which neither hash
    changed: after the last clean round run `gate --plan '<plan>' --pass
    --what-ran '<astra line>' --what-ran '<claude line>'`. It refuses when
    the plan or the re-rendered bodies differ from the reviewed pair; then
    run one more Stage 10 round on the changed plan (resumed when the Astra
    resume rules allow), or the user declines the remaining Nit fixes at the
    `egm-resolve` question so the reviewed text stands. When the user accepts
    at the cap, run `gate ... --accept`: it records the pair the reviewers
    last read and writes the unified diff since then as
    `gate_unreviewed.diff`. A pass writes `gate_plan_sha256` and
    `gate_bodies_sha256` into the state; the bodies hash covers the config
    and the template, which `graph` renders from.
*   **Astra unavailable**: `resources/astra_lane.md` section 8. Focused and
    Full run Claude-only and every report, the dry run and the confirmation
    carry `astra: not run (<reason>)`; Astra only cannot run and the user
    chooses Focused without Astra or stop.

Write `handoff_review_report.md` (the Stage 10 report with the run card and
the `What ran` lines at the top) and `astra_brief_s10_r<n>.md` per round in
the artifact directory.

## Step 4: The readiness test

After the gate passed, one fresh `egm-implementation-readiness` goldfish
per unit (direct dispatch, read-only adapter, the same in every panel),
given only `unit_<id>.md`, the design file and the unit's scope paths as
context, with this rule in its prompt: `List every question you would have
to ask before building this unit, as findings; label each design (the
design does not say), unit (the unit is ambiguous or contradicts the
design), code (the repository differs from what the unit assumes), or
people (needs a human decision).` Up to 5 goldfish in parallel; one that
fails is retried once, then recorded `not run`.

1.  Write `readiness_questions_r<n>.md`: every question by unit with the
    elephant's proposed triage: `answered` (write the answer into the unit
    text), `fix-unit` (rewrite the unit), `fix-design` (stop, as in step 3)
    or `people` (a `decide before build` item with owner and default;
    `blocking: yes` keeps the unit out of a wave until answered). Ask the
    user one question: accept the triage, change it, or stop. Record the
    decisions in the same file (a question is not an EGM finding;
    `egm-resolve` is not used here). Apply them to `handoff_plan.md`, run
    `graph`.
2.  Loop until a round adds no new question for any unit, cap 3; at the cap
    list the open items and the user accepts or stops. Then run `gate
    --plan '<plan>' --readiness '<n> rounds, <k> questions: <a> answered,
    <b> fix-unit, <c> people; goldfish: <m> completed, <f> not run'`.
3.  **Back through the gate.** When the readiness loop changed the plan (its
    sha256 differs from `gate_plan_sha256`), run one more Stage 10 round as
    in step 3 (`gate --reviewed`, the reviewers, `gate --pass`): a clean
    round after which nothing changed records the new hashes; a clean round
    whose fixes changed the plan is followed by one more; a round that is
    not clean returns to the step 3 loop.

## Step 5: Dry run and confirmation

1.  Run `python3 '<HELPER>' dry-run --plan '<plan>'`. It re-runs `graph`,
    refuses while the plan's or the re-rendered bodies' sha256 differs from
    the gate's (`the plan, the config or the issue template changed after
    the gate: run the gate again`), refuses more than 100 units (`split the
    handoff`), runs the scan (banned terms and bare mentions outside code,
    merge markers, every definition-of-done item present, bodies under
    65,000 bytes), and makes three read-only `gh` calls (login, push access,
    the repository's labels; a configured `extra` label the repository
    lacks stops it). It writes `handoff_dryrun.md`: every write in order
    (labels to create, the tracking issue, each unit issue with title,
    labels and body, each sub-issue and blocked-by link), the counts, the
    write budget (80 content-creating writes per minute, 500 per hour; a
    warning above 450 says to use `apply --max-writes`), the preflight
    results, the gate and readiness lines. It records `confirmed_sha256`:
    the sha256 of the canonical write list, which starts with the
    destination `OWNER/NAME` and the two gate hashes, so a changed `repo`,
    body, label or link after the confirmation refuses.
2.  Tell the user the path. Ask one question, the sole tool call in the
    turn, no `(Recommended)`: `Create these <n> issues and <m> links on
    OWNER/NAME as handoff_dryrun.md shows?` with the options Create, Change
    the plan, Stop. `Change the plan` returns to step 2 (and step 3: the
    gate runs again on the changed plan). Stop ends the skill with the
    files on disk.

## Step 6: Create and verify

1.  On Create run `python3 '<HELPER>' apply --plan '<plan>' --yes`, one
    Bash approval. The helper refuses without `--yes`, without
    `confirmed_sha256`, when the recomputed write list hashes differently,
    or when the config's `repo` differs from the state's. It creates the
    missing derived labels (`egm:unit`, `egm:wave-<n>`, `egm:tracking`,
    `egm:handoff-<id>`, colour `1b6ef3`, never `--force`, `extra` labels
    never created or edited), lists the existing issues with the handoff
    label once and matches the body marker so a rerun creates nothing
    twice, creates the tracking issue, then the unit issues in topological
    order one second apart with blocker numbers filled in, then the
    sub-issue links under the tracking issue and the blocked-by links,
    reading the current links first and posting only what is missing. The
    state is saved after every write. A 422 or 409 on a link is followed by
    a re-read and recorded `done` only when the link is present; a 410
    stops (issues disabled); a secondary rate limit waits for `retry-after`
    or 60 seconds, 3 retries, then exits with `rate limited: resume with
    apply --yes after <time>`. `--max-writes N` stops cleanly after N writes
    for a large handoff; repeated calls always move forward.
2.  After its last write the helper runs `verify`: every body read back and
    compared (CRLF and trailing spaces normalised), labels compared (they
    can be dropped silently), sub-issue and blocked-by lists compared with
    the graph; problems recorded as `MISMATCH`, never retried in a loop. The
    receipt `verify: {sha256, complete, checked, problems}` is complete only
    when every write of the list was read back. Run `verify --plan '<plan>'`
    on its own after a resume. Report `MISMATCH` lines to the user; the
    user fixes them by hand (editing issues after creation stays human).
3.  Write `handoff_summary.md`: the tracking issue URL, the wave table with
    issue numbers, the critical path, the verify summary, the `What ran`
    lines. Tell the user the path and that `/egm:egm-wave` launches the
    first wave once the receipt is complete and clean.

## Resuming

Every step is re-entrant from the artifact directory: `handoff_state.json`
says what passed (approval, gate hashes, confirmed hash, done writes,
receipt). A crash during `apply` resumes with `apply --yes` (same hash,
nothing created twice). A changed design (hash differs from the approval)
restarts at step 1; a changed plan after the gate restarts at step 3.

## Reviewer isolation

Always spawn a goldfish or the synthesizer through its own adapter, here, in
`egm-review-loop` and in the readiness test. The adapter is what sets
`omitClaudeMd: true` and the read-only tool list, and that is what keeps the
context fresh; it holds whether or not the spawn is named. Reviewing with a
general-purpose agent instead of the adapter is what breaks isolation.
Only the wave skill's foreman spawn carries a `name`.

<!-- Copyright 2026 gsVAM. SPDX-License-Identifier: Apache-2.0.
Added by the elephant-goldfish-model Astra fork (gsVAM), 2026: panel presets,
routing table, run card and configuration. Not part of google/elephant-goldfish-model. -->

# Review panels, run card and configuration

`egm-review` reads this file at Step 2, before the pipeline preset gate. Every
Claude reviewer or synthesizer spawn, in `egm-review` and in `egm-review-loop`,
follows section 6. The Astra lane itself (preflight, brief, launch, collection,
mapping, memory) is in `resources/astra_lane.md`. Everything here runs in the
main conversation.

## 1. Configuration (environment variables)

Claude Code only. In any other host skip this file: no `printenv`, preflight,
run card or panel question; run upstream's flow (Stages 5 to 9, all reviewers).

Read every value with one read-only command:

    printenv | grep -E '^(EGM_[^=]*|CLAUDE_CODE_(SUBAGENT_MODEL|SUBAGENT_MODEL_FORCE|EFFORT_LEVEL|PLUGIN_CACHE_DIR|EXPERIMENTAL_AGENT_TEAMS)|CLAUDE_CONFIG_DIR)=' || true

`EGM_[^=]*` is every name that begins with `EGM_`; the other names are exact.

Validate each `EGM_*` value against its allowlist before you use it. A value
that fails is ignored, the default applies, and you tell the user in one line:
`ignored EGM_<NAME>=<value>: allowed <allowlist>`. Never put an environment
value into a shell command: write the validated literal yourself.

| Variable | Default | Allowed values |
| --- | --- | --- |
| `EGM_ASTRA` | `on` when the Astra preflight passes, else `off` | `on`, `off` |
| `EGM_PANEL` | `focused` | `astra`, `focused`, `full` |
| `EGM_ASTRA_MODEL` | `gpt-6-astra` | matches `^[a-z0-9][a-z0-9.\-]{1,63}$` |
| `EGM_ASTRA_EFFORT` | `xhigh` | `low`, `medium`, `high`, `xhigh` |
| `EGM_ASTRA_MEMORY` | `resume` | `resume`, `fresh` |
| `EGM_GOLDFISH_MODEL` | `inherit` | `inherit`, `sonnet`, `opus`, `haiku`, `fable` |
| `EGM_GOLDFISH_EFFORT` | `inherit` | `inherit`, `low`, `medium`, `high`, `xhigh`, `max` |

Harness variables, read by the same command and never changed by EGM:
`CLAUDE_CODE_SUBAGENT_MODEL` (a default model, ranked below a per-call `model`
and below the adapters' `model: inherit`, so it reaches only a general-purpose
fallback subagent with no persona adapter), `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`
(a flag, not a model. It is on when its value is `1`, `true`, `yes` or `on`
in any casing, and off when it is unset, empty, `0`, `false`, `no` or `off`:
Claude Code's rule for on/off variables. Any other value is `unknown`. While
on, every subagent runs on `CLAUDE_CODE_SUBAGENT_MODEL` if set, else on the
main conversation's model, and no per-call `model` can be passed) and `CLAUDE_CODE_EFFORT_LEVEL` (overrides per-call effort).

Order of work at Step 2: read the variables; if `EGM_ASTRA` is not `off`, run
the preflight in `resources/astra_lane.md` section 1; show the run card; ask
the mode and panel (section 3).

## 2. Run card

Show the card in chat on every review: before the mode and panel prompt, or
before the first stage when `Step` and the panel were both given (section 3).
Write it, followed by a `What ran` line per lane (`completed`, `not run
(<reason>)`, or the non-terminal `running (started <time>)`), at the top of
every report of this review: `*_report.md`, `goldfish_review_report.md`,
`consolidated_review_report.md`. A report a subagent writes (the
synthesizer's, or a directly dispatched reviewer's) has no card: prepend the
card and the `What ran` lines to that file yourself, right after the subagent
returns and before you read it further, and pass `Stage`, `Round` (the loop's
last round + 1) and `RunCard` on every `egm-resolve` call, including the ones
at the Stage 7 and 9 gates.

A report written while the Astra lane is still running records `running
(started <time>)`; that state is never final. Once the lane completes, fails
or is skipped, rewrite the `What ran` lines (and the Astra status line,
`resources/astra_lane.md` section 6) of every report written in this review so
far with the terminal state and the effective model and effort; in
consolidated mode do this at Cross-Stage Synthesis at the latest, before
`consolidated_review_report.md` is written. Keep a list of the reports you
have written in this review so none is missed.

```text
EGM run card
| Role | Who and context | Model: requested -> effective | Effort: requested -> effective |
| --- | --- | --- | --- |
| Elephant | this session; project, conversation, document | <session model> -> same | session setting -> session setting |
| Claude goldfish | fresh subagents; document and reading list only | <EGM_GOLDFISH_MODEL> -> <effective> | <EGM_GOLDFISH_EFFORT> -> <effective> |
| Astra goldfish | GPT-6 Astra through claudex-loop; document and repository, no conversation | <EGM_ASTRA_MODEL> -> requested only | <EGM_ASTRA_EFFORT> -> requested only |
| Foreman | per-unit elephant; <teammate sharing this checkout | fresh subagents>; the unit, its state file and its round files | <session model> -> same | session setting -> session setting |
| Builder | external: whoever picks up the issue; the issue body only | unknown | unknown |
Astra memory: <resume | fresh>. Astra lane: <available | not run (<reason>)>.
Readiness: <handoff gate passed: no open high or medium, readiness test <passed | not run> | review only>.
Panel: <Astra only | Focused | Full>. Time: an Astra run takes about 8 minutes (median of measured runs, up to 30); Claude reviewers run alongside it.
Data notice: when the Astra lane runs, the whole target file, the brief (on a resumed round, with your decisions on Astra's own earlier findings), any file your OS account can read that Astra opens, and your Codex AGENTS.md and memories go to OpenAI under the account `codex login status` reports.
```

Cell rules:

- Elephant model: the model you know yourself to be from your own context;
  `unknown` if you do not know. Effort is always `session setting`: Claude Code
  does not expose it to skills. Do not guess.
- Claude goldfish, effective model, by the FORCE flag as section 1 reads it.
  On: `CLAUDE_CODE_SUBAGENT_MODEL` if set, else the elephant's model, marked
  `(forced by CLAUDE_CODE_SUBAGENT_MODEL_FORCE)`, and pass no per-call
  `model`. Off: the requested alias when it is not `inherit`, else the
  elephant's model (`inherit`, from the adapters' `model: inherit`). Unknown:
  `unknown (CLAUDE_CODE_SUBAGENT_MODEL_FORCE=<value> is not a documented
  boolean)`, and pass no per-call `model`; never write `forced` for it.
- Claude goldfish, effective effort: `CLAUDE_CODE_EFFORT_LEVEL` when set to
  `low`, `medium`, `high`, `xhigh` or `max`, marked `(forced by
  CLAUDE_CODE_EFFORT_LEVEL)`; treat `auto`, unset or empty as not set. Else
  the requested value when it is not `inherit` and the Agent tool offers an
  `effort` parameter; else `inherit`. When the user asked for an effort and the tool has no `effort`
  parameter, write `inherit (per-reviewer effort is not available in this
  version)`.
- Astra: `requested only` before the run. In reports, use `effective_model`
  and `effective_effort` from `result.json` when the runner recorded them;
  otherwise keep `requested only`.
- Any value you cannot know: `unknown`. Never present a configuration value as
  an observed one.

## 3. Mode and panel prompt

Ask both questions in one turn, right after the card. In Claude Code this
prompt replaces the Curated Pipeline Presets gate of `egm-review` Step 2 item
1: the mode is asked exactly once, here. Record both answers and go straight
to Step 3 or the chosen subflow; never show the preset gate again. Other hosts
keep upstream's gate.

- **Q1, review mode**: the four options of the Curated Pipeline Presets gate
  in `egm-review`, unchanged. `Step` answers only Q1. When `Step` was passed,
  still show the card and ask Q2 alone (one single-select), unless the panel
  was also given explicitly: `EGM_PANEL` is set to an allowed value, or the
  invocation named the panel (`Panel: astra | focused | full`, an optional
  `egm-review` input). Then use that panel, show it on the card and ask
  nothing. An unset `EGM_PANEL` is a default, not a choice.
- **Q2, panel** (option 0 is the panel `EGM_PANEL` names; the default is
  Focused):
  - `Focused: Claude design critic + Astra at Stage 7; Claude readiness reviewer + Astra at Stage 9`
  - `Astra only: one adversarial read by Astra at Stages 7 and 9, no Claude reviewers`
  - `Full: every EGM reviewer, Stages 5 to 9, plus Astra at Stages 7 and 9`
  - `Change models (Astra model and effort, Claude goldfish model and effort)`

Use one structured question call carrying both questions when the harness
accepts several questions in one call (Claude Code's `AskUserQuestion` does).
Otherwise ask Q1, then Q2, as two consecutive single-selects. This is the one
exception to EGM's single-question rule.

**Change models**: ask one follow-up question for the four values
(`EGM_ASTRA_MODEL`, `EGM_ASTRA_EFFORT`, `EGM_GOLDFISH_MODEL`,
`EGM_GOLDFISH_EFFORT`), as a write-in, then validate each against section 1,
show the card again and repeat the prompt. A value chosen here counts as the
user's explicit request (section 6).

**Astra unavailable** (`EGM_ASTRA=off`, or the preflight failed):

- Astra only: the panel cannot run. Say why, then offer `Focused without Astra
  (Claude reviewers only)` or `Stop`. Never substitute silently.
- Focused or Full: run Claude-only. The card and every report say `Astra: not
  run (<reason>)`.

## 4. Panels

| Panel | Stage 5 | Stage 6 | Stage 7 | Stage 8 | Stage 9 |
| --- | --- | --- | --- | --- | --- |
| Astra only | skipped | skipped | Astra lane | skipped | Astra lane |
| Focused (default) | skipped | skipped | `egm-design` + Astra lane | skipped | `egm-implementation-readiness` + Astra lane |
| Full | `egm-zoom-out` | `egm-comprehension` | `egm-design`, `egm-structural`, `egm-style` + Astra lane | `egm-zoom-out` | `egm-implementation-readiness`, `egm-codebase-details`, `egm-style` + Astra lane |

Two reviews of the fork's handoff and wave skills reuse the same panels:

| Review | Stage | Astra only | Focused (default) | Full |
| --- | --- | --- | --- | --- |
| Handoff gate (the handoff plan, before any GitHub write) | 10 | Astra lane | `egm-implementation-readiness` + Astra lane | `egm-implementation-readiness`, `egm-codebase-details` + Astra lane |
| PR review (one pull request against one build unit) | - | Astra inspect | `egm-change-review` + Astra inspect | `egm-change-review`, `egm-codebase-details` + Astra inspect |

Both reviews use `handoff-standard.md` for their Claude goldfish; `egm-codebase-details` runs in REVIEW mode so that scope paths, symbols and callers are checked to exist as the units assume. The handoff gate and runs like Stages 7 and 9: its
Claude reviewers go to `egm-review-loop` as `Reviewers` with `Stage: 10`, and
its stop rule is the same, no open high or medium. The PR review is run by the
foreman, uses the inspect launch of `resources/astra_lane.md` section 3b, and
has no `egm-review-loop` stage: the foreman dispatches its reviewers directly
and writes the round report.

Standards are unchanged: Stage 7 reviewers use `feature-spec-standard`, Stage
9 reviewers use `implementation-readiness-standard` (`egm-style` has none).
Stages 5, 6 and 8 are Claude-only and run exactly as upstream in the Full
panel. In Stages 7 and 9, `egm-review-loop` receives the Claude reviewers of
the panel as `Reviewers` (an empty list for Astra only) and `AstraLane: on`
when the lane is available. When a stage has one Claude reviewer (Focused),
dispatch it directly from the main context; use `egm-synthesizer` only for two
or more reviewers.

## 5. Routing table (review mode by panel)

Follow this table instead of the fixed 5 → 6 → 7 → 8 → 9 sequence whenever the
panel is not Full. A stage that is skipped by the panel writes no report, and no
step reads a report of a skipped stage.

| Mode | Panel | Stages, in order | Hand-off and gates | Consolidated report collects |
| --- | --- | --- | --- | --- |
| Preset 0, interactive | Full | 5 → 6 → 7 → 8 → 9 | As upstream; `egm-review-loop` at 7 and 9 with the panel's reviewers and the Astra lane | n/a |
| Preset 0, interactive | Focused or Astra only | 7 → 9 | Stage 7 gate Option 0 reads `Proceed to next stage: Stage 9 (Implementation Readiness Test)`; Stage 9 gate as upstream | n/a |
| Preset 1, consolidated | Full | 5, 6, 7, 8, 9, no gates | One Astra full-file run starts before Step 5 and runs during Steps 5 to 9; wait for it at Cross-Stage Synthesis | Reports of Stages 5 to 9 plus the Astra result |
| Preset 1, consolidated | Focused | 7, 9, no gates | One Astra full-file run starts before Step 7; wait for it at Cross-Stage Synthesis | `critic_report.md`, `implementation_readiness_report.md`, the Astra result; says Stages 5, 6 and 8 were skipped by the panel |
| Preset 1, consolidated | Astra only | Astra full-file run only | No Claude reviewer is spawned; wait for the run | The Astra result only; says Stages 5 to 9 Claude reviewers were skipped by the panel |
| Preset 2, feature spec only | Full | 5 → 6 → 7 → 8, then halt | As upstream | n/a |
| Preset 2, feature spec only | Focused or Astra only | 7, then halt | Stage 7 gate Option 0 reads `Conclude review and begin detailed implementation planning` | n/a |
| Preset 3, implementation plan only | any | 9 | Stage 9 with the panel's reviewers and the Astra lane; gate as upstream | n/a |

Rules that apply to every row:

- `DetailedRange = N/A` removes Stage 9 and the `DetailedRange` line of the
  Astra brief, as upstream.
- In Preset 1 make no `TargetFile` edit before `consolidated_review_report.md`
  is written: the Astra run fails if the plan changes while it runs.
- The consolidated report names each skipped stage and the reason (`skipped by
  panel`), and lists each lane that did not run with its reason.
- Stage 7 and Stage 9 loops judge clean rounds as `egm-review-loop` says; in
  the Astra only panel the Astra lane is the only reviewer, so a round in
  which it did not complete is not clean.

## 6. Per-reviewer model and effort for Claude goldfish

The adapters in `.claude-plugin/agents/` keep `model: inherit`; do not edit
them. The elephant passes the user's choice per call:

- **Direct dispatch**: decide the two parameters independently. Pass
  `model: <alias>` on each Agent call when `EGM_GOLDFISH_MODEL` (or the run
  card choice) is not `inherit` and the FORCE flag is off (section 2). Pass
  `effort: <value>` when `EGM_GOLDFISH_EFFORT` (or the run card choice) is not
  `inherit` and the Agent tool offers an `effort` parameter. A value of
  `inherit` is never passed, even when the user selected it: omit that
  parameter.
- **Synthesizer dispatch**: add this line to the synthesizer's prompt, naming
  only the parameters you would pass yourself: `Spawn each reviewer with
  [model: <alias>] [and effort: <value>] as the subagent tool's per-call
  parameters; pass no other model or effort parameter.` Leave the line out
  when you would pass neither.
- Report requested and effective values on the run card as section 2 says.

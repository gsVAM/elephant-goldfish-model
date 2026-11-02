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

    printenv | grep -E '^(EGM_|CLAUDE_CODE_(SUBAGENT_MODEL|SUBAGENT_MODEL_FORCE|EFFORT_LEVEL|PLUGIN_CACHE_DIR)|CLAUDE_CONFIG_DIR)=' || true

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
(a flag, `1`, not a model: every subagent runs on `CLAUDE_CODE_SUBAGENT_MODEL`
if set, else on the main conversation's model, and no per-call `model` can be
passed) and `CLAUDE_CODE_EFFORT_LEVEL` (overrides per-call effort).

Order of work at Step 2: read the variables; if `EGM_ASTRA` is not `off`, run
the preflight in `resources/astra_lane.md` section 1; show the run card; ask
the mode and panel (section 3).

## 2. Run card

Show the card in chat before the mode and panel prompt. Write it, followed by a
`What ran` line per lane (`completed` or `not run (<reason>)`), at the top of
every report of this review: `*_report.md`, `goldfish_review_report.md`,
`consolidated_review_report.md`.

```text
EGM run card
| Role | Who and context | Model: requested -> effective | Effort: requested -> effective |
| --- | --- | --- | --- |
| Elephant | this session; project, conversation, document | <session model> -> same | session setting -> session setting |
| Claude goldfish | fresh subagents; document and reading list only | <EGM_GOLDFISH_MODEL> -> <effective> | <EGM_GOLDFISH_EFFORT> -> <effective> |
| Astra goldfish | GPT-6 Astra through claudex-loop; document and repository, no conversation | <EGM_ASTRA_MODEL> -> requested only | <EGM_ASTRA_EFFORT> -> requested only |
Astra memory: <resume | fresh>. Astra lane: <available | not run (<reason>)>.
Panel: <Astra only | Focused | Full>. Time: an Astra run takes about 8 minutes (median of measured runs, up to 30); Claude reviewers run alongside it.
Data notice: when the Astra lane runs, the whole target file, the brief, any file your OS account can read that Astra opens, and your Codex AGENTS.md and memories go to OpenAI under the account `codex login status` reports.
```

Cell rules:

- Elephant model: the model you know yourself to be from your own context;
  `unknown` if you do not know. Effort is always `session setting`: Claude Code
  does not expose it to skills. Do not guess.
- Claude goldfish, effective model: when `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` is
  set and not `0`, `CLAUDE_CODE_SUBAGENT_MODEL` if set, else the elephant's
  model, marked `(forced by CLAUDE_CODE_SUBAGENT_MODEL_FORCE)`, and pass no
  per-call `model`; else the requested alias when it is not `inherit`; else
  the elephant's model (`inherit`, from the adapters' `model: inherit`).
- Claude goldfish, effective effort: `CLAUDE_CODE_EFFORT_LEVEL` when set,
  marked `(forced by CLAUDE_CODE_EFFORT_LEVEL)`; else the requested value when
  it is not `inherit` and the Agent tool offers an `effort` parameter; else
  `inherit`. When the user asked for an effort and the tool has no `effort`
  parameter, write `inherit (per-reviewer effort is not available in this
  version)`.
- Astra: `requested only` before the run. In reports, use `effective_model`
  and `effective_effort` from `result.json` when the runner recorded them;
  otherwise keep `requested only`.
- Any value you cannot know: `unknown`. Never present a configuration value as
  an observed one.

## 3. Mode and panel prompt

Ask both questions in one turn, right after the card:

- **Q1, review mode**: the four options of the Curated Pipeline Presets gate
  in `egm-review`, unchanged. When `Step` was passed, ask neither question:
  use the panel `EGM_PANEL` names (default Focused), show it on the run card,
  and continue.
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

- **Direct dispatch**: pass `model: <alias>` on each Agent call when
  `EGM_GOLDFISH_MODEL` (or the run card choice) is not `inherit` and
  `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` is unset or `0` (section 2). Pass
  `effort: <value>` only when the user chose an effort on the run card or set
  `EGM_GOLDFISH_EFFORT`, and the Agent tool offers an `effort` parameter.
  Otherwise pass neither.
- **Synthesizer dispatch**: add this line to the synthesizer's prompt, with the
  same values: `Spawn each reviewer with model: <alias> and effort: <value> as
  the subagent tool's per-call parameters; omit a value that is inherit, that
  the tool does not offer, or that CLAUDE_CODE_SUBAGENT_MODEL_FORCE overrides.`
- Report requested and effective values on the run card as section 2 says.

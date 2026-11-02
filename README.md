<p align="center">
  <a href="https://egm.dev"><img src="docs/assets/readme-header.svg" width="480" height="116" alt="Elephant-Goldfish Model"></a>
</p>

<p align="center">Design with an elephant. Review with a goldfish.</p>

<p align="center">
  <a href="#install">Install</a> &ensp;·&ensp;
  <a href="#try-your-first-design">Quickstart</a> &ensp;·&ensp;
  <a href="docs/getting_started.md">Documentation</a> &ensp;·&ensp;
  <a href="https://egm.dev">Website</a>
</p>

<br>

## About this fork

<!-- Modified by the elephant-goldfish-model Astra fork (gsVAM), 2026: this section and the install commands. -->

This repository is a modified version of [google/elephant-goldfish-model](https://github.com/google/elephant-goldfish-model) (upstream 0.1.0), maintained by gsVAM, release 0.2.0. Google does not endorse it. For Claude Code it adds:

- **An Astra lane.** GPT-6 Astra reviews the design at Stage 7 (Critic) and Stage 9 (Implementation Readiness) through the [claudex-loop](https://github.com/chaseai-yt/claudex-loop) runner, beside the Claude reviewers. Its high and medium findings block a clean round like any reviewer's. A lane that cannot run never blocks a Claude-only review.
- **Panel presets.** Every review asks for the panel together with the review mode: *Astra only* (one adversarial read), *Focused* (default: Claude design critic plus Astra at Stage 7, Claude readiness reviewer plus Astra at Stage 9) or *Full* (every upstream reviewer, Stages 5 to 9, plus Astra).
- **A run card.** Before the review: who each role is, what context it has, and its requested and effective model and effort. The card is repeated at the top of every report with what actually ran.
- **Per-reviewer model and effort** for the Claude goldfish, from `EGM_GOLDFISH_MODEL` and `EGM_GOLDFISH_EFFORT`.
- **Persisted dispositions.** `egm-resolve` writes your final decision per finding to `goldfish_dispositions_s<stage>_r<n>.md`; a resumed Astra round reads its own rows.
- **Handoff.** `egm-handoff` turns an approved design into build units, a dependency graph and waves, renders one GitHub issue body per unit, and writes them only after a dry run you confirm: a tracking issue, one sub-issue per unit, blocked-by links and labels.
- **Review loops to convergence, with a cap.** A round is done when it is clean *and* nothing in it came from the previous round's fixes; the per-round counts are reported so the trend is visible, and at 5 rounds the loop pauses and asks you rather than spending another. Breadth is the usual `EGM_PANEL`: one adversary, Focused, or Full.
- **An adversarial gate before any GitHub write.** The handoff plan faces the same panel as a design (Astra plus the Claude reviewers) against the seven questions of [`resources/document_standards/handoff-standard.md`](resources/document_standards/handoff-standard.md), then a readiness test. No open high or medium finding, no issues.
- **Waves and a foreman.** `egm-wave` launches a wave of ready issues and tracks them to landed. Each in-flight issue gets a foreman: with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in an interactive session it is an agent-teams teammate sharing this checkout, otherwise fresh subagents with a state file. A teammate cannot run background commands, so the foreman prepares the Astra review and the elephant launches it. The foreman reviews the pull request against its unit and posts one confirmed comment per round; CI is the verifier and humans ship.
- **Builders are external in this release.** Issues are built by whoever picks them up — a person or a coding-agent service. Dispatch of builders to cloud sandboxes (lb) is planned and not in this release.

**Prerequisites for the Astra lane** (without them the review runs Claude-only and says so): the claudex-loop plugin (2.1.0 or later) installed in Claude Code, Codex CLI 0.153.4 or later on `PATH`, `codex login` completed, and Python 3.10 or later as `python3`. Install claudex-loop with `claude plugin marketplace add chaseai-yt/claudex-loop` and `claude plugin install claudex-loop@claudex-loop`; the lane looks for the runner only under the `claudex-loop` marketplace name.

**Prerequisites for handoff and wave:** GitHub CLI (`gh`) 2.x on `PATH`, `gh auth login` completed for `github.com`, and push access to the target repository — labels are silently dropped without it, so the dry run checks for it and stops when it is missing.

**Configuration.** Environment variables, each checked against an allowlist before use; anything else is ignored with a warning and never reaches a shell command:

| Variable | Default | Values |
| --- | --- | --- |
| `EGM_ASTRA` | `on` when the prerequisites are met | `on`, `off` |
| `EGM_PANEL` | `focused` | `astra`, `focused`, `full` |
| `EGM_ASTRA_MODEL` | `gpt-6-astra` | `^[a-z0-9][a-z0-9.\-]{1,63}$` |
| `EGM_ASTRA_EFFORT` | `xhigh` | `low`, `medium`, `high`, `xhigh` |
| `EGM_ASTRA_MEMORY` | `resume` | `resume`, `fresh` |
| `EGM_GOLDFISH_MODEL` | `inherit` | `inherit`, `sonnet`, `opus`, `haiku`, `fable` |
| `EGM_GOLDFISH_EFFORT` | `inherit` | `inherit`, `low`, `medium`, `high`, `xhigh`, `max` |

**Repository rules for handoff and wave** live in `.egm/handoff.json` at the repository root, not in the plugin, because the plugin is generic. A missing file means the defaults and the dry run says so; an unknown key stops. Keys: `repo` (`OWNER/NAME`, by default parsed from `origin`), `labels` (`unit`, `wave_prefix`, `handoff_prefix`, `tracking`, `extra`), `issue_template`, `tracking_issue_title`, `banned_terms` and `fix_request_mention`. Full table: [`skills/egm-handoff/references/handoff_config.md`](skills/egm-handoff/references/handoff_config.md).

**Data notice.** When the Astra lane runs, the whole target file, the review brief, any file your OS account can read that Astra opens, and your Codex `AGENTS.md` and memories go to OpenAI under the account `codex login status` reports. When the lane runs in a handoff gate or a wave review, that target also includes the build units, the rendered issue bodies, the pull request diff and the changed files. Set the variables in the `env` block of a Claude Code settings file (or your shell). `EGM_ASTRA=off` turns the lane off, but a repository's project settings can turn it back on; the hard opt-outs are `codex logout`, `EGM_ASTRA=off` in managed settings, or not installing claudex-loop. Details: [docs/privacy.md](docs/privacy.md).

**Install from this fork** (Claude Code):

```sh
claude plugin marketplace add gsVAM/elephant-goldfish-model
claude plugin install egm@egm-astra
```

If Google's plugin is installed, run `claude plugin disable egm@egm` (or uninstall it) first: both plugins are named `egm`.

The marketplace is named `egm-astra` so it can coexist with Google's `egm` marketplace; the plugin keeps the name `egm` and the commands stay `/egm:egm-*`. To install for every Claude Code configuration folder on a machine (for example `~/.claude` and a folder chosen with `CLAUDE_CONFIG_DIR`), run both commands once per folder with `CLAUDE_CONFIG_DIR` set to it. Where managed settings come from the claude.ai admin console, a local managed-settings file is ignored, so an organization-wide install goes through the console. The claudex-loop plugin is installed separately by each user who wants the lane.

**Licence.** Apache-2.0, unchanged (`LICENSE`). As required by section 4(b), these upstream files were modified and each carries a change notice: `README.md`, `docs/claude.md`, `docs/privacy.md`, `docs/harnesses.md`, `docs/codex.md`, `resources/README.md`, `skills/egm-review/SKILL.md`, `skills/egm-review-loop/SKILL.md`, `skills/egm-review-loop/TEST.md`, `skills/egm-review-loop/test_scenarios.yaml`, `skills/egm-resolve/SKILL.md`, `plugin.json`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `tests/unit/test_harnesses.py`, `docs/getting_started.md`, `docs/designs/architecture.md`, `scripts/pack_plugin.py`, `tests/unit/test_packaging.py`. Added: `resources/astra_lane.md`, `resources/review_panels.md`, `tests/unit/test_astra_fork.py`, `skills/egm-handoff/`, `skills/egm-wave/`, `agents/change_review.md`, `.claude-plugin/agents/change_review.md`, `resources/document_standards/handoff-standard.md`, `tests/unit/test_egm_handoff.py`. `distributions/claude` is regenerated from these sources. Google's copyright notices are kept. Upstream's README follows.

---

Thousands of Google engineers use EGM, an open-source plugin, to draft specs with deep-context agents and stress-test them with zero-context subagents before writing code.

**Elephant** holds your project context and drafts the specification. **Goldfish** reviewers examine the draft and referenced source material without the earlier conversation, helping expose unstated assumptions and blind spots. **You** make the architectural trade-offs and approve the specification before implementing.

Use it when a feature needs design decisions before implementation. For a small, clear bug fix, use your normal coding workflow.

## Install

Choose your coding agent. Install the complete plugin so its skills can read the reviewer prompts and document standards.

### Antigravity CLI

```sh
agy plugin install https://github.com/gsVAM/elephant-goldfish-model
```

For the **Antigravity App** and **Antigravity for IDEs** (Visual Studio Code extension), run `/plugin` or see the [installation instructions](docs/harnesses.md#antigravity-app-and-antigravity-for-ides).

### Claude Code

```sh
claude plugin marketplace add gsVAM/elephant-goldfish-model
claude plugin install egm@egm-astra
```

### Codex

```sh
codex plugin marketplace add gsVAM/elephant-goldfish-model
codex plugin add egm@egm-astra
```

Start a new session after installation. For **Claude Cowork** and **ChatGPT Work**, see the [setup guide](docs/harnesses.md).

## Try your first design

Open your project in your coding agent and choose a feature that needs design decisions. This example adds webhook delivery: what should happen when a delivery fails, or the same event arrives twice?

The commands below are shown without a prefix. In Antigravity (agy CLI) and Claude Code, add the `/egm:` prefix, for example `/egm:egm-brainstorm`. On agy CLI 1.4.10 an unprefixed name is completed to the prefixed command ([#220](https://github.com/google/elephant-goldfish-model/issues/220)), but 1.4.8 does not ([#196](https://github.com/google/elephant-goldfish-model/issues/196)), so keep the prefix. In Codex, select the corresponding EGM skill from the skill picker. Brainstorming and review require a session that can create fresh subagents.

<img src="skills/egm-brainstorm/assets/icon.svg" width="20" height="20" align="top" alt=""> **Explore the idea**

```text
/egm-brainstorm Add webhook delivery to this project.
```

Discuss requirements and trade-offs with the agent. Fresh reviewers challenge the proposal, and the agent saves the agreed direction in `concepts_brief.md`.

<img src="skills/egm-draft/assets/icon.svg" width="20" height="20" align="top" alt=""> **Draft the specification**

```text
/egm-draft
```

The agent turns the brief into `design_draft.md`, pausing after each section for your feedback in chat.

<img src="skills/egm-review/assets/icon.svg" width="20" height="20" align="top" alt=""> **Review the draft**

```text
/egm-review design_draft.md
```

Use the draft path returned by the agent.

Fresh reviewers check the design, its clarity, its fit with the code, and its implementation plan. Choose which findings to address. When you approve the design, ask your coding agent to implement it.

See the [workflow guide](docs/getting_started.md) for the full process, including saving approved specifications under `docs/designs/`.

## How it works

<table>
  <thead><tr><th align="left">Role</th><th align="left">Context</th><th align="left">Responsibility</th></tr></thead>
  <tbody>
    <tr valign="top"><td><strong>Elephant</strong></td><td>Your project, requirements, and earlier decisions</td><td>Explore the problem and draft the specification.</td></tr>
    <tr valign="top"><td><strong>Goldfish</strong></td><td>The document and its referenced source material, without the earlier conversation</td><td>Find missing assumptions, unclear requirements, and implementation risks.</td></tr>
    <tr valign="top"><td><strong>You</strong></td><td>The goals and constraints that matter</td><td>Resolve trade-offs, approve the design, and decide what to build.</td></tr>
  </tbody>
</table>

Goldfish reviews require fresh subagent contexts. If your agent cannot create them, EGM stops the review. A review does not replace tests or human judgment. See [supported environments and verification limits](docs/harnesses.md#support-status--contributing-other-harnesses).

## Choose a skill

You can use each skill when you need it. You do not have to follow the full sequence.

<table>
  <thead><tr><th align="left">Skill</th><th align="left">Use it to…</th></tr></thead>
  <tbody>
    <tr valign="top"><td width="160" valign="top"><img src="skills/egm-brainstorm/assets/icon.svg" width="20" height="20" alt="" align="top">&nbsp;<a href="skills/egm-brainstorm/SKILL.md">Brainstorm</a></td><td>Test an idea and write a concept brief.</td></tr>
    <tr valign="top"><td width="160" valign="top"><img src="skills/egm-draft/assets/icon.svg" width="20" height="20" alt="" align="top">&nbsp;<a href="skills/egm-draft/SKILL.md">Draft</a></td><td>Turn a brief or existing notes into a design document.</td></tr>
    <tr valign="top"><td width="160" valign="top"><img src="skills/egm-resolve/assets/icon.svg" width="20" height="20" alt="" align="top">&nbsp;<a href="skills/egm-resolve/SKILL.md">Resolve</a></td><td>Work through review findings and agree on changes.</td></tr>
    <tr valign="top"><td width="160" valign="top"><img src="skills/egm-bootstrap/assets/icon.svg" width="20" height="20" alt="" align="top">&nbsp;<a href="skills/egm-bootstrap/SKILL.md">Bootstrap</a></td><td>Create or update documentation for an existing codebase.</td></tr>
    <tr valign="top"><td width="160" valign="top"><img src="skills/egm-review/assets/icon.svg" width="20" height="20" alt="" align="top">&nbsp;<a href="skills/egm-review/SKILL.md">Review</a></td><td>Review a design with fresh agents across five stages.</td></tr>
    <tr valign="top"><td width="160" valign="top"><img src="skills/egm-review-loop/assets/icon.svg" width="20" height="20" alt="" align="top">&nbsp;<a href="skills/egm-review-loop/SKILL.md">Review&nbsp;loop</a></td><td>Run a configured group of reviewers for a specific review task.</td></tr>
    <tr valign="top"><td width="160" valign="top"><img src="skills/egm-drift-report/assets/icon.svg" width="20" height="20" alt="" align="top">&nbsp;<a href="skills/egm-drift-report/SKILL.md">Drift&nbsp;report</a></td><td>Compare checked-in documents with the current source code.</td></tr>
    <tr valign="top"><td width="160" valign="top"><img src="skills/egm-handoff/assets/icon.svg" width="20" height="20" alt="" align="top">&nbsp;<a href="skills/egm-handoff/SKILL.md">Handoff</a></td><td>Turn an approved design into reviewed GitHub issues.</td></tr>
    <tr valign="top"><td width="160" valign="top"><img src="skills/egm-wave/assets/icon.svg" width="20" height="20" alt="" align="top">&nbsp;<a href="skills/egm-wave/SKILL.md">Wave</a></td><td>Launch a wave of issues and review their pull requests.</td></tr>
  </tbody>
</table>

## Learn more

- [Getting started](docs/getting_started.md): the workflow and project layout.
- [Setup](docs/harnesses.md): installation, agent capabilities, and known limits.
- [Architecture](https://github.com/google/elephant-goldfish-model/blob/main/docs/designs/architecture.md): how skills and reviewers fit together.
- [Testing](https://github.com/google/elephant-goldfish-model/blob/main/TESTING.md): checks, execution records, and verification limits.
- [Dave Rensin’s original essay](https://medium.com/@drensin/elephants-goldfish-and-the-new-golden-age-of-software-engineering-c33641a48874): the ideas behind EGM.

## Contribute

Read [contributing](https://github.com/google/elephant-goldfish-model/blob/main/CONTRIBUTING.md) for PRs, [issues](https://github.com/google/elephant-goldfish-model/issues) for bugs, and [discussions](https://github.com/google/elephant-goldfish-model/discussions) for questions.

## License

[Apache 2.0](LICENSE). This is not an officially supported Google product.

<!-- Copyright 2026 gsVAM. SPDX-License-Identifier: Apache-2.0.
Added by the elephant-goldfish-model Astra fork (gsVAM), 2026. -->

# The handoff plan: schema, template and derivation rules

`handoff_plan.md` is the source of truth of a handoff. It lives in the EGM
artifact directory (outside the repository by recommendation), is reviewed by
the Stage 10 gate and edited through `egm-resolve`. The helper
`scripts/egm_handoff.py graph` parses it strictly (any deviation stops with
the file and line number), writes `handoff_units.json`, one `unit_<id>.md`
per unit and `handoff_bodies.md`, and rewrites the generated section between
`<!-- egm:generated start -->` and `<!-- egm:generated end -->`. Never edit
that section by hand; everything above it is yours.

## 1. File layout

```markdown
# Handoff plan: <design title>

Design: `/absolute/path/to/docs/designs/webhooks.md`

## 1. Issue template

<the issue template the bodies are rendered from, quoted from
references/issue_template.md or the repository's .egm/handoff.json
issue_template, so the gate reviews the bodies against the plan alone>

## 2. Units

### U01: <title>
...one section per unit, as in section 2 below...

<!-- egm:generated start -->
...written by `graph`: edges, waves, critical path, blocking decisions...
<!-- egm:generated end -->
```

The `Design:` line names the approved design file (absolute, or relative to
the plan's folder). The helper hashes that file: the handoff id is
`<slug of the file stem, at most 20 characters>-<first 6 hex of its sha256>`,
and every later step stops with "design changed since the handoff started:
re-run the gate" when the hash differs from the approval's.

## 2. One unit

```markdown
### U03: Webhook delivery worker
| Field | Value |
| --- | --- |
| Objective | One sentence: what exists when this unit is done. |
| Scope paths | `src/webhooks/queue.ts` (modify), `src/webhooks/deliver.ts` (create) |
| Design range | `docs/designs/webhooks.md:140-171 (### 4.2 Delivery and retries)` |
| Blocked by | U01, U02 |
| Shared files | `src/webhooks/queue.ts`: after U01, before U05 |
| Risk | medium: touches the request path |
| Size | M |

Definition of done
1. `npm test -- src/webhooks/deliver.test.ts` passes with cases A, B, C (added by this unit).
2. CI (typecheck, lint, tests) is green on the PR head.
3. `docs/designs/webhooks.md` section 4.2 is true of the code after the change.

Decide before build
- D1 Retry ceiling (5 or 10 attempts)? owner: the design author; default: 5; blocking: no
```

| Field | Rule |
| --- | --- |
| Heading | `### U<nn>: <title>`. Ids are stable: never renumber after the dry run is confirmed; a new unit takes the next number. |
| Objective | One sentence, not empty. |
| Scope paths | Comma-separated `` `path` (create\|modify\|delete) ``; nothing else in the cell. |
| Design range | `` `path:start-end (heading)` `` with start <= end. |
| Blocked by | `none` or unit ids, comma-separated. A blocker is a unit that creates or changes a file or symbol this unit uses. |
| Shared files | `none` or `` `path`: after U01, before U05 `` items separated by `; `. `after` adds an edge from that unit to this one; `before` adds an edge from this one to that unit. |
| Risk | `low\|medium\|high: reason`. |
| Size | `S` (up to 3 scope paths), `M` (up to 8), `L` (more). |
| Definition of done | Numbered items. Each names a command or path in backticks, or a CI check (the word `CI`). An item with neither is rejected with its line. |
| Decide before build | `- none`, or `- D<n> <question> owner: <owner>; default: <default>; blocking: yes\|no`. A `blocking: yes` item keeps the unit out of a wave until the user answers it (`decide`). |

The graph: edges are the `Blocked by` entries and the shared-file `after` and
`before` entries. A unit's wave is `1 + max(wave of its predecessors)`. A
`Blocked by` cycle stops with the cycle listed. A shared-file chain that
contradicts the blockers (a cycle that appears only when the chain's edges
are added) stops with "shared-file chain contradicts the blockers": fix the
chain or the blockers; the helper never drops an edge silently. The critical
path is the longest chain by waves, ties broken by id. GitHub blocked-by
links are posted for the `Blocked by` entries; shared-file order is written
into the bodies. There are no parts: a unit is one issue and one PR.

## 3. Deriving units from the design

The elephant writes the units from the design's `## Detailed Implementation
Plan`; the gate and the readiness test check the result against these rules.

1. One unit per phase of the plan (phases must each leave the code
   buildable, `resources/document_standards/implementation-readiness-standard.md`).
   A phase that touches more than 8 files or two independent subsystems is
   split by subsystem.
2. Scope paths are the phase's Target Files, each with its action.
3. The definition of done is the `### Verification Plan` items that exercise
   those files, plus "CI green on the PR head", plus "the design range is
   true of the code".
4. A blocker is a unit that creates or changes a file or symbol this unit
   uses; document order alone is not a blocker.
5. A path in two units' scope becomes a shared-file chain in phase order;
   when the design gives no order, record a `decide before build` item
   instead of guessing.
6. A unit that must land in more than one PR (migration first, readers later)
   is split into units, the later blocked by the earlier.
7. Every `## Open Questions` entry of the design that touches a unit becomes
   a `decide before build` item with an owner and a default; so does every
   decision the elephant made while splitting (owner: the user; default: the
   elephant's proposal).
8. No unit may carry scope the design does not contain; the gate's first
   question is coverage in both directions.

## 4. Files the helper writes

| File | Written by | Content |
| --- | --- | --- |
| `handoff_units.json` | `graph` | The parsed units with waves and predecessors, the order, the edges, the critical path. Derived; never hand-edited. |
| `unit_<id>.md` | `graph`, `decide` | The unit section plus its issue body as it will be posted. The readiness goldfish and the foreman read it; it is the `--plan` of an inspect run. |
| `handoff_bodies.md` | `graph` | Every title, label set and body in creation order, with placeholders `#<U01>` for blockers and `#<tracking>` for the tracking issue. The gate reviews it. |
| `handoff_state.json` | every command | The handoff's state (section 5). |
| `gate_reviewed_plan.md`, `gate_reviewed_bodies.md` | `gate --reviewed` | The pair the current round's reviewers read. |
| `gate_unreviewed.diff` | `gate --accept` | The unified diff from the last reviewed pair to the accepted text, when they differ. |
| `handoff_dryrun.md` | `dry-run` | Every write in order, the counts, the budget, the preflight results, the gate and readiness lines. |
| `decision_comment_<unit>_<id>.md` | `decide` | The one comment the elephant posts on the issue after the scan and the user's confirmation. |
| `foreman_<unit>_state.json`, `pr_<n>_r<r>.diff`, `ci_<n>_r<r>.json`, `foreman_<unit>_r<r>_launch.md` | `prepare` | The wave skill's per-unit files (`skills/egm-wave/references/foreman_brief.md`). |

## 5. The state file

`handoff_state.json` holds: `handoff_id`, `repo`, `remote` (the git remote
whose URL names `repo`), `repo_root`, `plan`, `design` (path, sha256,
commit), `approval` (the user's answer with the design's sha256, commit and
the evidence path), `gate` (the reviewed pair per round, how the gate passed,
the `What ran` lines), `gate_plan_sha256` and `gate_bodies_sha256`,
`readiness`, `confirmed_sha256` (the sha256 of the canonical write list:
the destination `OWNER/NAME`, the two gate hashes, then every write in order
with its kind, title, label set, body with placeholder numbers, and links by
unit id), `confirmed_at`, `labels` (`missing`, `exists` or `done`),
`tracking` (number, id), `units` (per unit: number, id, wave, `launched`,
the watched `pr`, `landed_confirmed`, `deferred`), `links` (`done` or the
error), `verify` (`sha256`, `complete`, `checked`, `problems`), `decisions`
(`"U03/D1": {answer, decided_at}`) and the last `status` snapshot. It is
saved after every write, so a crash resumes with `apply --yes`.

## 6. Helper commands

Run every command as one Bash call, `python3 '<HELPER>' <subcommand> ...`,
absolute paths in single quotes, no chaining. `<HELPER>` is
`${CLAUDE_PLUGIN_ROOT}/skills/egm-handoff/scripts/egm_handoff.py`.

| Command | Writes to GitHub | What it does |
| --- | --- | --- |
| `approve --design D --artifacts DIR [--evidence E] [--yes]` | no | Checks the design (tracked and clean, has the implementation plan, the evidence names it) and prints the approval question; with `--yes` records the approval. |
| `graph --plan P` | no | Parses, builds the graph, writes the files above. |
| `scan --plan P [--comment FILE]` | no | Banned terms and bare mentions outside code, merge markers, size, every DoD item present. A comment file may carry the configured `fix_request_mention` on its first line. |
| `gate --plan P --reviewed --round N` | no | Records the pair the round's reviewers read. |
| `gate --plan P --pass [--what-ran L]...` | no | Passes only when nothing changed since the reviewed pair. |
| `gate --plan P --accept [--what-ran L]...` | no | Accepts at the cap; writes `gate_unreviewed.diff` when the text changed. |
| `gate --plan P --readiness 'line'` | no | Records the readiness verdict line for the dry run. |
| `dry-run --plan P` | no (three reads) | Refuses while the plan or the re-rendered bodies differ from the gate's hashes, over 100 units, on a scan problem, without push access, or on a missing `extra` label; writes `handoff_dryrun.md` and `confirmed_sha256`. |
| `apply --plan P --yes [--max-writes N]` | yes | Missing derived labels, the tracking issue, unit issues in topological order one second apart, sub-issue links, blocked-by links; state after every write; then `verify`. |
| `verify --plan P` | no | Reads every write back; records the receipt. |
| `status --state S [--wait SECONDS] [--watch U03=412] [--confirm-landed U03]` | no | Landed and ready sets, PR and CI per unit. Refuses without a complete, clean receipt. |
| `launch --state S --wave N --units U03 U04` | no | Records the launched units. |
| `defer --state S --unit U03 --to-wave N --yes` | yes (one label edit) | Moves a unit's wave label and verifies it. |
| `decide --state S --unit U03 --decision D1 --answer 'text'` | no | Records the answer, re-renders `unit_U03.md`, writes the decision comment file. |
| `prepare --state S --unit U03 --round R [--wave W --runner PATH --model M --effort E] [--remove] [--clean]` | no (git only) | Fetches the PR into `refs/egm/`, adds the worktree, writes the diff and the CI file, optionally the inspect launch line. |

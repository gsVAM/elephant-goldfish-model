<!-- Copyright 2026 gsVAM. SPDX-License-Identifier: Apache-2.0.
Added by the elephant-goldfish-model Astra fork (gsVAM), 2026. -->

# Repository configuration: `.egm/handoff.json`

Repository rules live in `.egm/handoff.json` at the repository root (the git
top level of the design file), not in the plugin: the plugin is generic. A
missing file means the defaults, and the dry run says so. Unknown keys stop.

```json
{
  "repo": "OWNER/NAME",
  "labels": {
    "unit": "egm:unit",
    "wave_prefix": "egm:wave-",
    "handoff_prefix": "egm:handoff-",
    "tracking": "egm:tracking",
    "extra": []
  },
  "issue_template": null,
  "tracking_issue_title": "Build: <design title>",
  "banned_terms": [],
  "fix_request_mention": null
}
```

| Key | Default | Rule |
| --- | --- | --- |
| `repo` | parsed from `git remote get-url origin` | `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`. The helper then finds, in `git remote -v`, the remote whose URL names it in any form (`https://github.com/O/N[.git]`, `git@github.com:O/N[.git]`, `ssh://git@github.com/O/N[.git]`), records it as `remote` in the state for `prepare`, and stops with "no remote for OWNER/NAME in <repo root>: add one or fix `repo`" when none matches. In a fork checkout `origin` is the fork and the target is usually `upstream`. |
| `labels.unit` | `egm:unit` | On every unit issue. Each label name must match `^[^,\s]{1,50}$` (GitHub rejects longer names). |
| `labels.wave_prefix` | `egm:wave-` | `egm:wave-<n>` on every unit issue. |
| `labels.handoff_prefix` | `egm:handoff-` | `egm:handoff-<handoff id>` on every issue of the handoff; the listing `apply` reads for idempotency. |
| `labels.tracking` | `egm:tracking` | On the tracking issue. |
| `labels.extra` | `[]` | Labels the repository already has, added to every unit issue. The helper never creates or edits them; a missing one stops the dry run with "create the label `<name>` on OWNER/NAME or remove it from `extra`". |
| `issue_template` | the built-in template | A path relative to the repository root. It must start with the marker line and contain `{{objective}}`, `{{scope}}` and `{{dod}}` (`references/issue_template.md`). |
| `tracking_issue_title` | `Build: <design title>` | `<design title>` is replaced by the design's H1. |
| `banned_terms` | `[]` | Regular expressions matched line by line against the RAW text of every body and comment - code spans and fenced blocks included; the scan is not code-aware, so a banned term in backticks is still refused and the author rewords. A repository that must not name AI tools in GitHub text lists them here. |
| `fix_request_mention` | none | `^@[A-Za-z0-9-]+(\[bot\])?$`. The one mention the scan allows, on the first line of a round comment, because coding-agent services act on PR feedback only when a comment mentions them. Never allowed in a body. |
| `allowed_mentions` | `[]` | `@name` strings that may appear in any body or comment. The scan is **not code-aware** (seven review rounds each found a defect in a Markdown-aware version, which could both hide a mention and refuse ordinary text), so a legitimate mention must be listed here as the EXACT token GitHub would resolve, e.g. `@types/node` - `@types` does not cover `@types/node`, and `@acme` never covers the team `@acme/release`, which would subscribe its members. The allowlist exempts mentions only, never banned terms. Otherwise a refusal names the line and the author rewords. |

Fixed behaviour, not configuration: a bare `@name` anywhere in the text is refused
(it notifies that user; the scan does not exempt code); CI is required; a merged PR is required for landed;
both PR-matching rules of the wave skill apply; the label colour is `1b6ef3`;
derived labels are created without `--force` and existing labels are never
edited.

The dry run makes three read-only `gh` calls: `gh auth status --hostname
github.com`, `gh api repos/OWNER/NAME -q .permissions` (push access is
required, because labels are silently dropped without it) and `gh api
repos/OWNER/NAME/labels --paginate --slurp`. Repository selection is per
command: `issue`, `pr` and `label` commands take `-R OWNER/NAME`; `api` calls
name the repository in the endpoint, never through the `{owner}`/`{repo}`
placeholders (the helper's `cwd` is the artifact directory, not the
repository); the GraphQL read passes `owner` and `name` as variables.

## One command at a time

The helper is **single-writer**: it has no locking and needs none. Run one
command, let it finish, run the next. `status --wait` is the only long command
and it only reads while waiting, saving once when it returns; it refuses
`--watch` and `--confirm-landed` so a long wait can never record a choice late.

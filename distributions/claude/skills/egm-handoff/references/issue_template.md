<!-- Copyright 2026 gsVAM. SPDX-License-Identifier: Apache-2.0.
Added by the elephant-goldfish-model Astra fork (gsVAM), 2026. -->

# The issue template

Every unit issue is rendered from this template (the default built into
`scripts/egm_handoff.py`; a repository overrides it with `issue_template` in
`.egm/handoff.json`, see `references/handoff_config.md`). The plan's section 1
quotes the template in use so the Stage 10 gate reviews the bodies against
the plan alone. No run card, no model name and no reviewer name appears in
any GitHub text; those stay in the local reports.

## Default template

```markdown
<!-- egm:handoff={{handoff_id}} unit={{unit_id}} -->
**Objective.** {{objective}}

**Scope.**
{{scope}}

**Definition of done.**
{{dod}}

**Blocked by.** {{blocked_by}}

**Shared files and order.**
{{shared}}

**Decide before build.**
{{decisions}}

**Risk and size.** {{risk}}; size {{size}}.

**Design.** `{{design}}`

Part of #{{tracking}}. Wave {{wave}}. Branch: `{{branch}}`
```

## Placeholders

| Placeholder | Value |
| --- | --- |
| `{{handoff_id}}`, `{{unit_id}}` | The first line is the idempotency marker. It stays in the raw body, is invisible when rendered, and lets a rerun of `apply` find the issue instead of creating it twice. A custom template must start with this exact line. |
| `{{title}}` | The unit's title (the issue title is `<unit id>: <title>`). |
| `{{objective}}` | The objective sentence. Required. |
| `{{scope}}` | One `- \`path\` (action)` line per scope path. Required. |
| `{{dod}}` | The definition of done as a checklist, `- [ ] item`. Required; the scan checks that every item is present. |
| `{{blocked_by}}` | `#<n>` of each blocker (a placeholder `#<U01>` until `apply` fills the number; blockers exist by then because issues are created in topological order), or `none`. |
| `{{shared}}` | One line per shared file: `after` references as `#<n>`, `before` references as the unit id and title (that issue does not exist yet when this body is posted). |
| `{{decisions}}` | The `decide before build` items with owner, default and blocking flag, and the recorded answer under an item the user decided. |
| `{{risk}}`, `{{size}}` | From the unit. |
| `{{design}}` | `path@<short sha> lines a-b (heading)`. |
| `{{tracking}}` | The tracking issue's number (`<tracking>` until `apply`). |
| `{{wave}}` | The unit's wave. |
| `{{branch}}` | `egm/<handoff-id>/<unit-id>`: the branch name `status` recognises as a candidate PR when no closing reference exists. |

## The tracking issue

The tracking issue (title from `tracking_issue_title`, default `Build:
<design title>`; labels `egm:tracking` and `egm:handoff-<id>`) carries the
marker `<!-- egm:handoff=<id> unit=tracking -->`, the design reference, the
wave table (unit ids and titles, never numbers, since the units do not exist
yet), the critical path and the shared files. Every unit issue is added as
its sub-issue.

## Limits the scan enforces

A body over 65,000 bytes is refused with "shorten or split the unit" (GitHub
rejects 65,536). No banned term and no bare `@name` outside code spans and
blocks; no merge markers. The configured `fix_request_mention` is allowed
only on the first line of a round comment, never in a body.

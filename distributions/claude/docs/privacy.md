<!-- Copyright 2026 Google LLC. SPDX-License-Identifier: Apache-2.0 -->
<!-- Modified by the elephant-goldfish-model Astra fork (gsVAM), 2026: Astra lane section, fork issue tracker. -->

# EGM data handling

EGM is a set of skills, reviewer instructions, and local documentation workflows.
The runtime package does not operate a hosted service, database, analytics client,
or telemetry endpoint. It does not require a separate EGM account or credentials.

## Inputs and outputs

The host assistant reads the project files, design documents, prompts, and review
context supplied for the selected task. Those inputs can contain personal or
confidential information. Provide only the files needed for the review.

EGM writes briefs, design documents, README files, and review reports to the user's
workspace or the host's artifact storage. Outputs can repeat information from
the inputs. Local files persist until the user deletes them; EGM does not apply
an automatic retention period.

## Processing and external services

The selected host processes prompts, files, model responses, and agent activity
under that host's own account settings, terms, and privacy policy. Native agent
calls use the user's host account. EGM does not control host transcript, artifact,
backup, or model-provider retention.

Bootstrap can run local discovery commands and an existing project-configured
formatter. A formatter or other user-approved project command may contact a
package registry or another service. Inspect and authorize those commands using
the host's permission controls. EGM's runtime declares no MCP server and installs
no permission-approval hook.

## Astra lane (fork addition)

In Claude Code, the fork can run one review lane through the claudex-loop
runner and the Codex CLI. When it runs, these leave the machine and go to
OpenAI under the account `codex login status` reports, on that account's terms:
the whole target design document (not only the reviewed range), the review
brief EGM writes (including the standard text and, on a resumed round, the
rows of the dispositions file for Astra's own earlier findings: finding id,
the author's final decision and a one-line reason, which EGM writes without
quoting any other reviewer), the runner's fixed instructions, any file the
user's OS account can read that Astra opens inside or outside the repository
(the read-only sandbox blocks writes, not reads), and the user's Codex
`AGENTS.md` and memories. EGM does not put the Claude conversation, the Claude
reviewers' reports or their dispositions rows in the brief; Astra is told not
to open them, but it can read them like any other file in the folder (see
above). Write artifacts outside the repository to keep them out of the folder
Astra reviews.

The handoff gate and the wave's pull request review use the same lane, so the
same terms apply to what they send. The handoff gate's target is the handoff
plan: the build units with their objectives, scope paths and definitions of
done, the rendered issue bodies and the design the units were derived from.
The wave review's target is one unit and its pull request: the unit file, the
saved diff, the list of changed files, the CI result file and the review
worktree, which Astra may read like any other folder it is given. Issue
bodies, comments and unit texts also go to GitHub, under GitHub's terms and
with the repository's visibility; `banned_terms` in `.egm/handoff.json` is
checked against every body and comment before it is written, and a dry run you
confirm precedes every GitHub write.

The lane runs only after a run card with this notice is shown, and only when
the claudex-loop runner, the Codex CLI and a Codex login are present. Opt out
with `EGM_ASTRA=off` in settings (a project's settings can override a user's,
so the hard opt-outs are `codex logout`, `EGM_ASTRA=off` in managed settings,
or not installing claudex-loop). Local copies of each prompt and reply stay in
`${TMPDIR:-/tmp}/egm-astra`; the brief and dispositions files stay in the
artifact folder. They may contain private code; delete them when done.

## Development tools

The source repository also contains opt-in integration tests. When explicitly
enabled, they invoke host CLIs and inspect transcripts produced by their own test
sessions to verify reviewer isolation. They are excluded from runtime release
packages. Website and development tooling are also excluded.

## Questions

Use the [issue tracker](https://github.com/gsVAM/elephant-goldfish-model/issues)
for general questions. Do not include credentials, private documents, or personal
data in public reports. This notice describes the plugin's data flow; it does
not replace the privacy policies of the host or services the user invokes.

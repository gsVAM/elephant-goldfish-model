# Copyright 2026 gsVAM. SPDX-License-Identifier: Apache-2.0
# Added by the elephant-goldfish-model Astra fork (gsVAM), 2026.

"""Wiring checks for the fork: Astra lane, panels, run card, change notices."""

from pathlib import Path
import os
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
LANE = (ROOT / "resources/astra_lane.md").read_text(encoding="utf-8")
PANELS = (ROOT / "resources/review_panels.md").read_text(encoding="utf-8")
MODIFIED = (
    "README.md", "docs/claude.md", "docs/privacy.md", "docs/harnesses.md",
    "docs/codex.md", "resources/README.md", "skills/egm-review/SKILL.md",
    "skills/egm-review-loop/SKILL.md", "skills/egm-review-loop/TEST.md",
    "skills/egm-review-loop/test_scenarios.yaml", "skills/egm-resolve/SKILL.md",
    "plugin.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
    ".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json",
    "tests/unit/test_harnesses.py", "docs/getting_started.md",
    "docs/designs/architecture.md", "scripts/pack_plugin.py",
    "tests/unit/test_packaging.py",
)


def read(path: str) -> str:
  return (ROOT / path).read_text(encoding="utf-8")


def test_resource_files_are_linked() -> None:
  review, loop = read("skills/egm-review/SKILL.md"), read("skills/egm-review-loop/SKILL.md")
  for skill in (review, loop):
    assert "`resources/review_panels.md`" in skill
    assert "`resources/astra_lane.md`" in skill
  index = read("resources/README.md")
  assert "(review_panels.md)" in index and "(astra_lane.md)" in index
  resolve = read("skills/egm-resolve/SKILL.md")
  assert "goldfish_dispositions_s[Stage]_r[Round].md" in resolve
  assert "never from the AI\n    suggestion" in resolve
  assert "goldfish_dispositions_s<stage>_r<n-1>.md" in LANE


def test_allowlists_are_stated() -> None:
  for text in (
      "| `EGM_ASTRA` |", "| `on`, `off` |",
      "| `EGM_PANEL` |", "| `astra`, `focused`, `full` |",
      "| `EGM_ASTRA_MODEL` |", r"^[a-z0-9][a-z0-9.\-]{1,63}$",
      "| `EGM_ASTRA_EFFORT` |", "| `low`, `medium`, `high`, `xhigh` |",
      "| `EGM_ASTRA_MEMORY` |", "| `resume`, `fresh` |",
      "| `EGM_GOLDFISH_MODEL` |", "| `inherit`, `sonnet`, `opus`, `haiku`, `fable` |",
      "| `EGM_GOLDFISH_EFFORT` |", "| `inherit`, `low`, `medium`, `high`, `xhigh`, `max` |",
      "Never put an environment\nvalue into a shell command",
  ):
    assert text in PANELS, text


def test_three_panels_and_routing_are_defined() -> None:
  for text in ("| Astra only |", "| Focused (default) |", "| Full |",
               "## 5. Routing table", "Preset 0, interactive",
               "Preset 1, consolidated", "Preset 2, feature spec only",
               "Preset 3, implementation plan only", "Never substitute silently",
               "skipped by the panel"):
    assert text in PANELS, text


def test_run_card_fields_are_present() -> None:
  for text in ("EGM run card", "| Elephant |", "| Claude goldfish |",
               "| Astra goldfish |", "requested -> effective", "session setting",
               "Astra memory:", "Data notice:", "Panel:", "about 8 minutes",
               "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL",
               "requested only", "`unknown`", "Change models"):
    assert text in PANELS, text


def test_panel_file_is_claude_code_only() -> None:
  flat = " ".join(PANELS.split())
  assert ("Claude Code only. In any other host skip this file: no `printenv`, "
          "preflight, run card or panel question; run upstream's flow (Stages 5 "
          "to 9, all reviewers).") in flat


def test_step_answers_only_the_mode_question() -> None:
  flat = " ".join(PANELS.split())
  assert "ask neither question" not in flat
  assert "`Step` answers only Q1." in flat
  assert "still show the card and ask Q2 alone" in flat
  assert ("`EGM_PANEL` is set to an allowed value, or the invocation named the "
          "panel (`Panel: astra | focused | full`") in flat
  assert "Show the card in chat on every review" in flat


def test_combined_prompt_replaces_the_preset_gate() -> None:
  review = " ".join(read("skills/egm-review/SKILL.md").split())
  assert "It replaces item 1's gate (mode asked once)" in review
  flat = " ".join(PANELS.split())
  assert ("this prompt replaces the Curated Pipeline Presets gate of `egm-review` "
          "Step 2 item 1: the mode is asked exactly once, here.") in flat
  assert "Other hosts keep upstream's gate." in flat


def test_what_ran_has_a_running_state_that_is_rewritten() -> None:
  flat = " ".join(PANELS.split())
  assert "`running (started <time>)`" in flat
  assert ("Once the lane completes, fails or is skipped, rewrite the `What ran` "
          "lines") in flat
  assert "of every report written in this review so far" in flat
  assert "at Cross-Stage Synthesis at the latest" in flat
  lane = " ".join(LANE.split())
  assert "astra (<model>, <effort>): running (started <time>)" in lane
  assert "rewrite that line and the `What ran` line in every report" in lane


def test_printenv_command_reads_every_egm_variable_and_nothing_else() -> None:
  command = re.search(r"^    (printenv \| grep .*)$", PANELS, re.MULTILINE).group(1)
  expected = {"EGM_ASTRA=off", "EGM_PANEL=full", "EGM_GOLDFISH_MODEL=opus",
              "CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1",
              "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1"}
  env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
         "EGMX_OTHER": "1", "NOT_EGM_ASTRA": "1", "HOME_EGM_": "1",
         "CLAUDE_CODE_SUBAGENT_MODEL_FORCE_X": "1"}
  env.update(line.split("=", 1) for line in expected)
  result = subprocess.run(["/bin/sh", "-c", command], env=env, check=True,
                          capture_output=True, text=True)
  assert set(result.stdout.splitlines()) == expected, result.stdout


def test_force_flag_uses_claude_boolean_rule() -> None:
  flat = " ".join(PANELS.split())
  assert "set and not `0`" not in flat and "unset or `0`" not in flat
  assert ("on when its value is `1`, `true`, `yes` or `on` in any casing, and "
          "off when it is unset, empty, `0`, `false`, `no` or `off`") in flat
  assert "Any other value is `unknown`" in flat
  assert "never write `forced`" in flat
  assert ("`CLAUDE_CODE_EFFORT_LEVEL` when set to `low`, `medium`, `high`, "
          "`xhigh` or `max`, marked `(forced by CLAUDE_CODE_EFFORT_LEVEL)`; "
          "treat `auto`, unset or empty as not set") in flat


def test_inherit_is_never_passed_per_call() -> None:
  flat = " ".join(PANELS.split())
  assert ("A value of `inherit` is never passed, even when the user selected "
          "it: omit that parameter.") in flat
  assert "pass no other model or effort parameter" in flat


def test_dispositions_are_keyed_by_stage_and_round() -> None:
  resolve = read("skills/egm-resolve/SKILL.md")
  assert "goldfish_dispositions_s[Stage]_r[Round].md" in resolve
  assert "# Goldfish dispositions, stage [Stage], round [Round]" in resolve
  assert "goldfish_dispositions_s<Stage>_r<n>.md" in read("skills/egm-review-loop/SKILL.md")
  flat = " ".join(LANE.split())
  assert ("`goldfish_dispositions_s<stage>_r<n-1>.md` exists and its first "
          "lines name stage <stage>, round <n-1> and this `TargetFile`") in flat
  for path in ("skills", "resources", "docs", "agents"):
    for file in (ROOT / path).rglob("*.md"):
      assert "dispositions_round" not in file.read_text(encoding="utf-8"), file
  assert "dispositions_round" not in read("README.md")
  review = " ".join(read("skills/egm-review/SKILL.md").split())
  assert "`Stage`, `Round` (the loop's last round + 1) and `RunCard`" in review


def test_run_card_reaches_every_report() -> None:
  flat = " ".join(PANELS.split())
  assert "prepend the card and the `What ran` lines to that file yourself" in flat
  assert ("pass `Stage`, `Round` (the loop's last round + 1) and `RunCard` on "
          "every `egm-resolve` call, including the ones at the Stage 7 and 9 "
          "gates") in flat


def test_astra_feedback_carries_only_astra_rows() -> None:
  flat = " ".join(LANE.split())
  assert "leave out every other reviewer's row" in flat
  assert "the full text of goldfish_dispositions" not in flat
  privacy = " ".join(read("docs/privacy.md").split())
  assert "the Claude reviewers' findings are not sent" not in privacy
  assert "rows of the dispositions file for Astra's own earlier findings" in privacy
  assert "dispositions rows are not sent" not in privacy
  assert "nothing of Claude's review goes to OpenAI" not in flat
  for text in (privacy, flat):
    assert ("EGM does not put the Claude conversation, the Claude reviewers' "
            "reports or their dispositions rows in the brief") in text
    assert "it can read them like any other file in the folder" in text
    assert "Write artifacts outside the repository" in text
  assert "keeps both ids (for example `design-2-1 + astra-2-3 (F4)`)" in flat
  resolve = " ".join(read("skills/egm-resolve/SKILL.md").split())
  assert "A `Reason` names no other reviewer's finding" in resolve
  assert "one row per finding id, from the user's final decision" in resolve
  assert ("gets one row per id, each naming only its own reviewer, with the "
          "same Final and Changed lines and a Reason written for that row "
          "alone") in resolve


def test_lane_launch_and_safety_rules() -> None:
  flat = " ".join(LANE.split())
  assert "first reason that applies: `host`" in flat
  for text in ("run_in_background: true", "review --host claude", "--timeout 1800",
               "cache/claudex-loop/claudex-loop", "codex login status",
               "https://code.claude.com/docs/en/plugins/loading#find-plugins-on-disk",
               "Never start it from a subagent",
               "If you are a subagent or workflow agent, do not launch",
               "not run", "skip astra", "`status` is `completed`",
               "`session_id` is a UUID", "not resumable"):
    assert text in flat, text
  launches = re.findall(r"^    python3 '<RUNNER>' review .*$", LANE, re.MULTILINE)
  assert len(launches) == 2
  assert launches[1].endswith("--resume '<PREVIOUS_RESULT_JSON>'")
  for launch in launches:
    assert not re.search(r"\$EGM_|&&|\||;|\s>", launch), launch


@pytest.mark.parametrize("path", MODIFIED)
def test_modified_files_carry_change_notice(path: str) -> None:
  assert "Astra fork" in read(path), path


def test_readme_about_this_fork() -> None:
  readme = read("README.md")
  assert readme.index("## About this fork") < readme.index("## Install")
  for text in ("claude plugin marketplace add gsVAM/elephant-goldfish-model",
               "claude plugin install egm@egm-astra", "Data notice",
               "section 4(b)", "google/elephant-goldfish-model"):
    assert text in readme, text
  for path in MODIFIED:
    assert f"`{path}`" in readme, path


# --- Release 0.2.0: handoff, wave and the foreman -----------------------------


def test_stage_10_range_line_and_handoff_lens() -> None:
  flat = " ".join(LANE.split())
  assert "Stages 7, 9 and 10" in flat
  assert ("`Lines <a>-<b> (HandoffPlan: <headings>): standard "
          "handoff-standard.md, handoff lens.`") in flat
  for text in ("units that are not independently buildable",
               "a definition of done without a command that proves it",
               "scope paths that overlap another unit without a blocker",
               "cannot be executed without the conversation that produced it"):
    assert text in flat, text


def test_inspect_launch_line_is_fresh_and_unchained() -> None:
  launches = re.findall(r"^    python3 '<RUNNER>' inspect .*$", LANE, re.MULTILINE)
  assert len(launches) == 1
  launch = launches[0]
  for flag in ("--host claude", "--base '<MERGE_BASE_SHA>'",
               "--plan '<ARTIFACT_DIR>/unit_<unit-id>.md'", "--timeout 3600"):
    assert flag in launch, flag
  assert "--resume" not in launch
  assert not re.search(r"\$EGM_|&&|\||;|\s>", launch), launch
  flat = " ".join(LANE.split())
  assert "An inspect run is never resumed" in flat
  assert "a teammate cannot start a background command" in flat


def test_bash_timeout_rule_in_both_launch_sections() -> None:
  flat = " ".join(LANE.split())
  assert "## 3b. Launch (pull request review)" in LANE
  assert "plus 300 seconds" in flat
  assert "**in milliseconds**, at most 7,200,000: `2100000` for a `--timeout 1800`" in flat
  assert "`3900000` for the `--timeout 3600` inspect" in flat
  assert "is milliseconds, not seconds" in flat


def test_inspect_data_notice() -> None:
  flat = " ".join(LANE.split())
  assert ("sends the pull request diff, the changed files, the unit file and "
          "the review worktree") in flat
  for name in ("wave_round_u*_r*.md", "foreman_*_state.json",
               "handoff_state.json"):
    assert name in flat, name


def test_handoff_standard_is_linked_and_shaped() -> None:
  assert "document_standards/handoff-standard.md" in read("resources/README.md")
  standard = read("resources/document_standards/handoff-standard.md")
  assert "Astra fork" in standard


def test_panels_gain_the_handoff_gate_and_pr_review_rows() -> None:
  flat = " ".join(PANELS.split())
  assert "Handoff gate (the handoff plan, before any GitHub write) | 10 |" in flat
  assert "PR review (one pull request against one build unit) | - |" in flat
  assert "`egm-change-review` + Astra inspect" in flat
  assert "no open high or medium" in flat
  assert "| Foreman | per-unit elephant;" in flat
  assert "| Builder | external: whoever picks up the issue;" in flat


def test_stage_10_reaches_the_loop_and_resolve_skills() -> None:
  loop = " ".join(read("skills/egm-review-loop/SKILL.md").split())
  assert "`Stage` (`7`, `9` or `10`, for the Astra brief)" in loop
  resolve = " ".join(read("skills/egm-resolve/SKILL.md").split())
  assert "the review stage, `7`, `9` or `10` (the handoff gate)" in resolve


@pytest.mark.parametrize("path", [
    "docs/claude.md", "skills/egm-handoff/SKILL.md", "skills/egm-wave/SKILL.md",
    "skills/egm-review-loop/SKILL.md",
])
def test_reviewer_isolation_rule_is_stated(path: str) -> None:
  assert "never pass `name`" in " ".join(read(path).split()), path


def test_foreman_is_named_a_per_unit_elephant() -> None:
  for path in ("docs/claude.md", "skills/egm-wave/SKILL.md"):
    flat = " ".join(read(path).split())
    assert "per-unit elephant" in flat, path
    assert "zero-context" in flat or "read-only" in flat, path


def test_readme_states_the_lb_limit_and_the_new_skills() -> None:
  flat = " ".join(read("README.md").split())
  assert ("Dispatch of builders to cloud sandboxes (lb) is planned and not in "
          "this release.") in flat
  assert "`.egm/handoff.json`" in flat
  assert "gh auth login" in flat
  for text in ("skills/egm-handoff/SKILL.md", "skills/egm-wave/SKILL.md"):
    assert text in flat, text


def test_launch_lines_agree_with_the_helper_and_the_wave_skill() -> None:
  """The lane, the helper that writes the line and the skill that runs it must
  name the same runner timeout and the same Bash timeout in milliseconds."""
  helper = read("skills/egm-handoff/scripts/egm_handoff.py")
  wave = read("skills/egm-wave/SKILL.md")
  assert "--timeout 3600" in helper and "3900000" in helper
  assert "3,900,000 ms" in wave
  launch = re.search(r"^    python3 '<RUNNER>' inspect .*$", LANE, re.MULTILINE).group(0)
  assert "--builder" not in launch
  assert '--artifacts "${TMPDIR:-/tmp}/egm-astra"' in launch


def test_handoff_gate_panel_matches_the_handoff_skill() -> None:
  flat = " ".join(PANELS.split())
  skill = " ".join(read("skills/egm-handoff/SKILL.md").split())
  assert "| Focused (default) | `egm-implementation-readiness` |" in skill
  assert "Focused plus `egm-codebase-details`" in skill
  assert ("| Handoff gate (the handoff plan, before any GitHub write) | 10 | Astra lane "
          "| `egm-implementation-readiness` + Astra lane | "
          "`egm-implementation-readiness`, `egm-codebase-details` + Astra lane |") in flat
  assert "`egm-design` + Astra lane |" not in flat.split("Handoff gate")[1][:400]

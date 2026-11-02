# Copyright 2026 gsVAM. SPDX-License-Identifier: Apache-2.0
# Added by the elephant-goldfish-model Astra fork (gsVAM), 2026.

"""Wiring checks for the fork: Astra lane, panels, run card, change notices."""

from pathlib import Path
import re

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
    "tests/unit/test_harnesses.py",
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
  assert "goldfish_dispositions_round_[Round].md" in resolve
  assert "never from the AI\n    suggestion" in resolve
  assert "goldfish_dispositions_round_<n-1>.md" in LANE


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


def test_lane_launch_and_safety_rules() -> None:
  flat = " ".join(LANE.split())
  for text in ("run_in_background: true", "review --host claude", "--timeout 1800",
               "cache/claudex-loop/claudex-loop", "codex login status",
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

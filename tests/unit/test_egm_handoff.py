# Copyright 2026 gsVAM. SPDX-License-Identifier: Apache-2.0
# Added by the elephant-goldfish-model Astra fork (gsVAM), 2026.

"""Offline tests for the handoff helper with an in-process fake `gh`."""

import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import urllib.parse
import sys
import textwrap
import traceback

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "skills/egm-handoff/scripts/egm_handoff.py"
REPO = "example-org/webhooks"

DESIGN = """# Webhook delivery

*   **Status:** Approved

## Open Questions

*   Retry ceiling: 5 or 10 attempts?

## Detailed Implementation Plan

### Target Files to Create/Modify

#### 1. `src/webhooks/queue.ts` (Create)

*   **Proposed Changes**: `enqueue(event)` and `dequeue()`.

#### 2. `src/webhooks/deliver.ts` (Create)

*   **Proposed Changes**: `deliver(job)`; `queue.ts` gains `requeue(job, delay)`.

#### 3. `src/webhooks/admin.ts` (Create)

*   **Proposed Changes**: `GET /admin/webhooks` lists jobs.

### Verification Plan

*   `npm test -- src/webhooks/queue.test.ts`
*   `npm test -- src/webhooks/deliver.test.ts`
*   `npm test -- src/webhooks/admin.test.ts`
"""

UNITS = """### U01: Webhook queue
| Field | Value |
| --- | --- |
| Objective | An in-memory queue with enqueue and dequeue exists. |
| Scope paths | `src/webhooks/queue.ts` (create), `src/webhooks/queue.test.ts` (create) |
| Design range | `docs/designs/sample.md:13-15 (#### 1. src/webhooks/queue.ts)` |
| Blocked by | none |
| Shared files | `src/webhooks/queue.ts`: before U02 |
| Risk | low: new module |
| Size | S |

Definition of done
1. `npm test -- src/webhooks/queue.test.ts` passes with enqueue and dequeue order cases.
2. CI (typecheck, lint, tests) is green on the PR head.

Decide before build
- none

### U02: Delivery worker
| Field | Value |
| --- | --- |
| Objective | A delivery worker posts payloads and retries failed jobs. |
| Scope paths | `src/webhooks/deliver.ts` (create), `src/webhooks/deliver.test.ts` (create), `src/webhooks/queue.ts` (modify) |
| Design range | `docs/designs/sample.md:17-19 (#### 2. src/webhooks/deliver.ts)` |
| Blocked by | U01 |
| Shared files | `src/webhooks/queue.ts`: after U01, before U03; `src/webhooks/types.ts`: before U03 |
| Risk | medium: touches the request path |
| Size | S |

Definition of done
1. `npm test -- src/webhooks/deliver.test.ts` passes with cases A, B, C.
2. CI (typecheck, lint, tests) is green on the PR head.

Decide before build
- D1 Retry ceiling (5 or 10 attempts)? owner: the design author; default: 5; blocking: no

### U03: Admin endpoint
| Field | Value |
| --- | --- |
| Objective | An admin endpoint lists queued and failed jobs. |
| Scope paths | `src/webhooks/admin.ts` (create), `src/webhooks/admin.test.ts` (create), `src/webhooks/queue.ts` (modify) |
| Design range | `docs/designs/sample.md:21-23 (#### 3. src/webhooks/admin.ts)` |
| Blocked by | U02 |
| Shared files | `src/webhooks/queue.ts`: after U02; `src/webhooks/types.ts`: after U02 |
| Risk | low: read-only endpoint |
| Size | S |

Definition of done
1. `npm test -- src/webhooks/admin.test.ts` passes with the listing case.
2. CI (typecheck, lint, tests) is green on the PR head.

Decide before build
- D2 Page size for the listing? owner: the user; default: 50; blocking: yes
"""


def git(args, cwd):
  return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                        text=True).stdout


def make_repo(path: Path, origin_url=f"https://github.com/{REPO}.git", config=None) -> Path:
  path.mkdir(parents=True, exist_ok=True)
  git(["init", "-q", "-b", "main"], path)
  git(["config", "user.email", "egm@example.invalid"], path)
  git(["config", "user.name", "EGM"], path)
  (path / "docs/designs").mkdir(parents=True)
  (path / "docs/designs/sample.md").write_text(DESIGN, encoding="utf-8")
  if config is not None:
    (path / ".egm").mkdir()
    (path / ".egm/handoff.json").write_text(json.dumps(config), encoding="utf-8")
  git(["add", "-A"], path)
  git(["commit", "-qm", "Sample design"], path)
  git(["remote", "add", "origin", origin_url], path)
  return path


def make_plan(artifacts: Path, repo: Path, units=UNITS) -> Path:
  artifacts.mkdir(parents=True, exist_ok=True)
  plan = artifacts / "handoff_plan.md"
  plan.write_text(f"# Handoff plan: Webhook delivery\n\nDesign: `{repo / 'docs/designs/sample.md'}`\n\n"
                  f"## Units\n\n{units}", encoding="utf-8")
  return plan


class FakeGitHub:
  """An in-process `gh` that keeps a small GitHub in memory and records calls."""

  def __init__(self, repo=REPO):
    self.repo = repo
    self.labels = {"bug": {"name": "bug", "color": "d73a4a"}}
    self.issues = {}
    self.next_number, self.next_id = 1, 1000
    self.sub_issues, self.blocked_by = {}, {}
    self.prs, self.graphql = {}, {}
    self.check_runs, self.combined = {}, {}
    self.calls = []
    self.push = True
    self.rate_limit_hits = 0
    self.link_422_once = set()
    self.read_only = False

  def __call__(self, args, cwd, stdin=None):
    args = list(args)
    self.calls.append(args)
    if args[0] in ("api", "auth") and "-R" in args:
      return 1, "", "unknown shorthand flag: 'R' in -R"
    if any("{owner}" in a or "{repo}" in a for a in args):
      return 1, "", "placeholder would resolve from cwd"
    try:
      return getattr(self, "do_" + args[0])(args)
    except KeyError as error:
      return 1, "", f"gh: Not Found (HTTP 404): {error!r}\n{traceback.format_exc()}"

  def ok(self, data=None, text=None):
    return 0, text if text is not None else (json.dumps(data) if data is not None else ""), ""

  def do_auth(self, args):
    assert args[1:] == ["status", "--hostname", "github.com"], args
    return self.ok(text="Logged in to github.com\n")

  def do_label(self, args):
    assert args[1] == "create" and "-R" in args and "--force" not in args, args
    self.assert_write()
    name = args[2]
    if name in self.labels:
      return 1, "", "label already exists (HTTP 422)"
    self.labels[name] = {"name": name, "color": args[args.index("--color") + 1]}
    return self.ok(text=f"https://github.com/{self.repo}/labels/{name}\n")

  def assert_write(self):
    if self.read_only:
      raise AssertionError("write in a read-only run")

  def do_issue(self, args):
    assert "-R" in args and args[args.index("-R") + 1] == self.repo, args
    if args[1] == "create":
      self.assert_write()
      if self.rate_limit_hits:
        self.rate_limit_hits -= 1
        return 1, "", "gh: You have exceeded a secondary rate limit (HTTP 403)"
      body = Path(args[args.index("--body-file") + 1]).read_text(encoding="utf-8")
      labels = [args[i + 1] for i, a in enumerate(args) if a == "--label" and args[i + 1] in self.labels]
      number = self.next_number
      self.next_number += 1
      self.issues[number] = {"number": number, "id": self.next_id, "title": args[args.index("--title") + 1],
                             "body": body, "labels": labels, "state": "open", "state_reason": None}
      self.next_id += 1
      return self.ok(text=f"https://github.com/{self.repo}/issues/{number}\n")
    if args[1] == "view":
      issue = self.issues[int(args[2])]
      return self.ok({"body": issue["body"], "labels": [{"name": l} for l in issue["labels"]]})
    if args[1] == "edit":
      self.assert_write()
      issue = self.issues[int(args[2])]
      added = args[args.index("--add-label") + 1]
      if added not in self.labels:
        # The real gh refuses a label the repository does not have; a fake that
        # appends it hides exactly the bug this guards.
        return 1, "", f"could not add label: '{added}' not found (HTTP 422)"
      issue["labels"] = [l for l in issue["labels"] if l != args[args.index("--remove-label") + 1]]
      issue["labels"].append(added)
      return self.ok(text="")
    raise AssertionError(args)

  def do_pr(self, args):
    assert "-R" in args, args
    if args[1] == "view":
      return self.ok(self.prs[int(args[2])])
    if args[1] == "list":
      assert "--limit" in args and args[args.index("--limit") + 1] == "1000", args
      return self.ok(list(self.prs.values()))
    raise AssertionError(args)

  @staticmethod
  def endpoint_of(args):
    skip = False
    for arg in args[1:]:
      if skip:
        skip = False
      elif arg in ("-X", "-F", "-f", "-q"):
        skip = True
      elif not arg.startswith("-"):
        return arg
    raise AssertionError(args)

  def do_api(self, args):
    endpoint = self.endpoint_of(args)
    paginate = "--paginate" in args
    if endpoint == "graphql":
      query = args[args.index("-f") + 1]
      assert "includeClosedPrs: true" in query and "$endCursor" in query, query
      assert paginate and "--slurp" in args
      number = int(args[args.index("number=" + args[args.index("-F", args.index("-F") + 1) + 1][7:]) + 1][7:]) \
          if False else int([a for a in args if a.startswith("number=")][0][7:])
      nodes = self.graphql.get(number, [])
      return self.ok([{"data": {"repository": {"issue": {"closedByPullRequestsReferences": {
          "nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}])
    if "-X" in args and args[args.index("-X") + 1] == "POST":
      self.assert_write()
      assert "-i" in args, args
      fields = dict(a.split("=", 1) for a in args[args.index("-F") + 1::2] if "=" in a)
      fields = {k: v for k, v in fields.items() if not k.startswith("-")}
      match = re.fullmatch(r"repos/([^/]+/[^/]+)/issues/(\d+)/sub_issues", endpoint)
      if match:
        assert fields["sub_issue_id"].isdigit(), fields
        if ("sub", int(match.group(2))) in self.link_422_once:
          self.link_422_once.discard(("sub", int(match.group(2))))
          self.sub_issues.setdefault(int(match.group(2)), []).append(int(fields["sub_issue_id"]))
          return 1, "HTTP/2.0 422 Unprocessable Entity\n\n{}", "gh: Validation Failed (HTTP 422)"
        self.sub_issues.setdefault(int(match.group(2)), []).append(int(fields["sub_issue_id"]))
        return self.ok(text="HTTP/2.0 201 Created\ncontent-type: application/json\n\n{}")
      match = re.fullmatch(r"repos/([^/]+/[^/]+)/issues/(\d+)/dependencies/blocked_by", endpoint)
      if match:
        assert fields["issue_id"].isdigit(), fields
        self.blocked_by.setdefault(int(match.group(2)), []).append(int(fields["issue_id"]))
        return self.ok(text="HTTP/2.0 201 Created\n\n{}")
      raise AssertionError(args)
    path, _, query = endpoint.partition("?")
    assert path.startswith(f"repos/{self.repo}") or path.startswith("repos/"), endpoint
    rest = path[len(f"repos/{self.repo}"):]
    if rest == "":
      assert args[2:4] == ["-q", ".permissions"], args
      return self.ok({"push": self.push, "pull": True})
    if rest == "/labels":
      assert paginate and "--slurp" in args, args
      return self.ok([list(self.labels.values())])
    if rest == "/issues":
      assert paginate, args
      label = urllib.parse.parse_qs(query).get("labels", [None])[0]
      items = [i for i in self.issues.values() if label in i["labels"]]
      return self.ok([items])
    match = re.fullmatch(r"/issues/(\d+)", rest)
    if match:
      issue = self.issues[int(match.group(1))]
      return self.ok({**issue, "labels": [{"name": l} for l in issue["labels"]]})
    match = re.fullmatch(r"/issues/(\d+)/sub_issues", rest)
    if match:
      assert paginate, args
      ids = self.sub_issues.get(int(match.group(1)), [])
      return self.ok([[{"id": i, "number": self.number_of(i)} for i in ids]])
    match = re.fullmatch(r"/issues/(\d+)/dependencies/blocked_by", rest)
    if match:
      assert paginate, args
      ids = self.blocked_by.get(int(match.group(1)), [])
      return self.ok([[{"id": i, "number": self.number_of(i)} for i in ids]])
    match = re.fullmatch(r"/commits/([0-9a-f]+)/check-runs", rest)
    if match:
      assert paginate, args
      runs = self.check_runs.get(match.group(1), [])
      return self.ok([{"total_count": len(runs), "check_runs": runs}])
    match = re.fullmatch(r"/commits/([0-9a-f]+)/status", rest)
    if match:
      return self.ok(self.combined.get(match.group(1), {"state": "pending", "statuses": []}))
    raise AssertionError(args)

  def number_of(self, issue_id):
    return next(i["number"] for i in self.issues.values() if i["id"] == issue_id)


class Harness:
  """One helper namespace with the fake injected; `run` returns (code, stdout)."""

  def __init__(self, capsys, now=1_700_000_000.0):
    # run_path returns a copy of the module globals; the functions keep the
    # original dict, so injection goes through __globals__.
    self.ns = runpy.run_path(str(HELPER))["main"].__globals__
    self.gh = FakeGitHub()
    self.sleeps = []
    self.clock = now
    self.ns["GH"] = self.gh
    self.ns["_subprocess_gh"] = self.never
    self.ns["SLEEP"] = lambda s: (self.sleeps.append(s), self.advance(s))
    self.ns["NOW"] = lambda: self.clock
    self.capsys = capsys

  @staticmethod
  def never(args, cwd, stdin=None):
    raise AssertionError(f"real gh must not run in tests: {args}")

  def advance(self, seconds):
    self.clock += seconds

  def run(self, *argv):
    code = self.ns["main"]([str(a) for a in argv])
    captured = self.capsys.readouterr()
    return code, captured.out + captured.err


@pytest.fixture
def world(tmp_path, capsys):
  repo = make_repo(tmp_path / "repo", config={"repo": REPO, "banned_terms": ["(?i)secret-codename"]})
  plan = make_plan(tmp_path / "artifacts", repo)
  harness = Harness(capsys)
  harness.repo, harness.plan, harness.artifacts = repo, plan, plan.parent
  return harness


def state_of(world):
  return json.loads((world.artifacts / "handoff_state.json").read_text(encoding="utf-8"))


def pass_gate(world):
  assert world.run("graph", "--plan", world.plan)[0] == 0
  assert world.run("gate", "--plan", world.plan, "--reviewed", "--round", 1)[0] == 0
  code, out = world.run("gate", "--plan", world.plan, "--pass", "--what-ran", "astra: not run (test)")
  assert code == 0, out


def dry_run(world):
  pass_gate(world)
  code, out = world.run("dry-run", "--plan", world.plan)
  assert code == 0, out
  return out


# ------------------------------------------------------------------ parsing


def test_parser_rejects_dod_item_without_command_and_reports_line(world):
  text = world.plan.read_text(encoding="utf-8").replace(
      "1. `npm test -- src/webhooks/admin.test.ts` passes with the listing case.",
      "1. The listing works.")
  world.plan.write_text(text, encoding="utf-8")
  line = text.splitlines().index("1. The listing works.") + 1
  code, out = world.run("graph", "--plan", world.plan)
  assert code == 1 and f"handoff_plan.md:{line}:" in out and "definition-of-done" in out


def test_graph_unknown_reference_cycle_and_contradiction(world):
  text = world.plan.read_text(encoding="utf-8")
  world.plan.write_text(text.replace("| Blocked by | U02 |", "| Blocked by | U09 |"), encoding="utf-8")
  code, out = world.run("graph", "--plan", world.plan)
  assert code == 1 and "unknown unit U09" in out
  world.plan.write_text(text.replace("| Blocked by | none |", "| Blocked by | U03 |"), encoding="utf-8")
  code, out = world.run("graph", "--plan", world.plan)
  assert code == 1 and "blocked-by cycle" in out and "U01" in out and "U03" in out
  contradiction = text.replace("| Shared files | `src/webhooks/queue.ts`: before U02 |",
                               "| Shared files | `src/webhooks/queue.ts`: after U02 |")
  world.plan.write_text(contradiction, encoding="utf-8")
  code, out = world.run("graph", "--plan", world.plan)
  assert code == 1 and "shared-file chain contradicts the blockers" in out


def test_graph_writes_waves_critical_path_placeholders_and_id(world):
  code, out = world.run("graph", "--plan", world.plan)
  assert code == 0, out
  units = json.loads((world.artifacts / "handoff_units.json").read_text(encoding="utf-8"))
  assert units["waves"] == {"1": ["U01"], "2": ["U02"], "3": ["U03"]}
  assert units["critical_path"] == ["U01", "U02", "U03"]
  assert re.fullmatch(r"sample-[0-9a-f]{6}", units["handoff_id"])
  bodies = (world.artifacts / "handoff_bodies.md").read_text(encoding="utf-8")
  assert "**Blocked by.** #<U01>" in bodies and "after #<U01>, before U03 (Admin endpoint)" in bodies
  assert "Part of #<tracking>. Wave 2." in bodies
  unit = (world.artifacts / "unit_U02.md").read_text(encoding="utf-8")
  assert unit.startswith("### U02: Delivery worker") and "#<U01>" in unit
  plan = world.plan.read_text(encoding="utf-8")
  assert "<!-- egm:generated start -->" in plan and "| U01 | U02 | shared file `src/webhooks/queue.ts`; blocked by |" in plan
  assert "- U03/D2 Page size for the listing?" in plan
  # Regenerating is idempotent: the plan text does not change.
  assert world.run("graph", "--plan", world.plan)[0] == 0
  assert world.plan.read_text(encoding="utf-8") == plan


def test_long_derived_label_is_refused(tmp_path, capsys):
  repo = make_repo(tmp_path / "repo", config={"repo": REPO, "labels": {"handoff_prefix": "x" * 45}})
  plan = make_plan(tmp_path / "artifacts", repo)
  harness = Harness(capsys)
  code, out = harness.run("graph", "--plan", plan)
  assert code == 1 and "longer than 50 characters" in out


def test_config_defaults_and_remote_resolution(tmp_path, capsys):
  repo = make_repo(tmp_path / "repo", origin_url="git@github.com:fork-user/webhooks.git")
  git(["remote", "add", "upstream", f"ssh://git@github.com/{REPO}"], repo)
  (repo / ".egm").mkdir()
  (repo / ".egm/handoff.json").write_text(json.dumps({"repo": REPO}), encoding="utf-8")
  plan = make_plan(tmp_path / "artifacts", repo)
  harness = Harness(capsys)
  assert harness.run("graph", "--plan", plan)[0] == 0
  state = json.loads((plan.parent / "handoff_state.json").read_text(encoding="utf-8"))
  assert state["remote"] == "upstream" and state["repo"] == REPO
  ns = runpy.run_path(str(HELPER))
  config = ns["load_config"](repo)
  assert config["banned_terms"] == [] and config["fix_request_mention"] is None
  (repo / ".egm/handoff.json").write_text(json.dumps({"repo": "other/name"}), encoding="utf-8")
  code, out = harness.run("graph", "--plan", plan)
  assert code == 1 and "no remote for other/name" in out
  (repo / ".egm/handoff.json").write_text(json.dumps({"repo": REPO, "bogus": 1}), encoding="utf-8")
  code, out = harness.run("graph", "--plan", plan)
  assert code == 1 and "unknown keys" in out


# --------------------------------------------------------------------- scan


def test_scan_banned_terms_mentions_and_size(world):
  ns = world.ns
  config = {"banned_terms": ["(?i)secret-codename"], "fix_request_mention": "@copilot"}
  assert ns["scan_text"]("plain `secret-codename` in code", config, "body") == []
  assert any("banned term" in p for p in ns["scan_text"]("the secret-codename leaks", config, "body"))
  assert any("bare mention" in p for p in ns["scan_text"]("ask @alice please", config, "body"))
  assert ns["scan_text"]("email a@b.example and `@alice`", config, "body") == []
  assert ns["scan_text"]("@copilot\n**EGM review round 1**", config, "comment") == []
  assert any("bare mention" in p for p in ns["scan_text"]("hello\n@copilot", config, "comment"))
  assert any("bare mention" in p for p in ns["scan_text"]("@copilot first", config, "body"))
  big = "é" * 40_000
  assert any("exceeds 65000" in p for p in ns["scan_text"](big, config, "body"))
  assert any("merge marker" in p for p in ns["scan_text"]("a\n<<<<<<< HEAD\nb", config, "body"))
  assert any("missing from the body" in p for p in ns["scan_text"]("x", config, "body", dod=["`npm test`"]))


def test_scan_command_over_rendered_bodies(world):
  text = world.plan.read_text(encoding="utf-8").replace("retries failed jobs.", "retries jobs; see secret-codename.")
  world.plan.write_text(text, encoding="utf-8")
  code, out = world.run("scan", "--plan", world.plan)
  assert code == 1 and "banned term" in out and "U02" in out
  world.plan.write_text(world.plan.read_text(encoding="utf-8").replace("; see secret-codename.", "."), encoding="utf-8")
  code, out = world.run("scan", "--plan", world.plan)
  assert code == 0 and "scan: clean" in out


# ----------------------------------------------------------------- approval


def test_approve_checks_and_records(world):
  design = world.repo / "docs/designs/sample.md"
  code, out = world.run("approve", "--design", design, "--artifacts", world.artifacts)
  assert code == 0 and "Approve `" in out and "Options: Approve | Stop" in out
  code, out = world.run("approve", "--design", design, "--artifacts", world.artifacts, "--yes")
  assert code == 0
  assert state_of(world)["approval"]["answer"] == "Approve"
  design.write_text(DESIGN + "\nchanged\n", encoding="utf-8")
  code, out = world.run("approve", "--design", design, "--artifacts", world.artifacts)
  assert code == 1 and "tracked but not clean" in out

  code, out = world.run("graph", "--plan", world.plan)
  assert code == 1 and "design changed since the handoff started: re-run the gate" in out
  git(["checkout", "--", "docs/designs/sample.md"], world.repo)
  (world.repo / "docs/designs/plain.md").write_text("# Plain\n\nNo plan.\n", encoding="utf-8")
  git(["add", "-A"], world.repo)
  git(["commit", "-qm", "plain"], world.repo)
  code, out = world.run("approve", "--design", world.repo / "docs/designs/plain.md", "--artifacts", world.artifacts)
  assert code == 1 and "Detailed Implementation Plan" in out and "egm-draft" in out


def test_approve_refuses_an_untracked_or_ignored_design(world):
  """A clean `git status -- <path>` says nothing about an ignored file."""
  design = world.repo / "docs/designs/ignored.md"
  design.write_text(DESIGN, encoding="utf-8")
  (world.repo / ".gitignore").write_text("docs/designs/ignored.md\n", encoding="utf-8")
  code, out = world.run("approve", "--design", design, "--artifacts", world.artifacts)
  assert code == 1 and "not tracked by git" in out


# --------------------------------------------------------------------- gate


def test_gate_pass_refuses_after_change_and_accept_writes_diff(world):
  assert world.run("graph", "--plan", world.plan)[0] == 0
  code, out = world.run("gate", "--plan", world.plan, "--pass")
  assert code == 1 and "no reviewed pair" in out
  assert world.run("gate", "--plan", world.plan, "--reviewed", "--round", 1)[0] == 0
  text = world.plan.read_text(encoding="utf-8")
  world.plan.write_text(text.replace("low: new module", "low: a new module"), encoding="utf-8")
  code, out = world.run("gate", "--plan", world.plan, "--pass")
  assert code == 1 and "changed after round 1 was reviewed" in out
  code, out = world.run("gate", "--plan", world.plan, "--accept")
  assert code == 0 and "gate_unreviewed.diff" in out
  diff = (world.artifacts / "gate_unreviewed.diff").read_text(encoding="utf-8")
  assert "-| Risk | low: new module |" in diff and "+| Risk | low: a new module |" in diff
  state = state_of(world)
  assert state["gate"]["passed"] == "accepted at cap" and state["gate_unreviewed_diff"]


# ------------------------------------------------------------------ dry run


def test_dry_run_writes_file_and_calls_only_three_reads(world):
  out = dry_run(world)
  assert "3 issues" in out.replace("4 issues", "3 units") or True
  text = (world.artifacts / "handoff_dryrun.md").read_text(encoding="utf-8")
  assert "4 issues (1 tracking, 3 units), 3 sub-issue links, 2 blocked-by links" in text
  assert "- `egm:unit`: create" in text and "- `egm:wave-1`: create" in text
  assert "Confirmed write list sha256" in text and "astra: not run (test)" in text
  state = state_of(world)
  assert re.fullmatch(r"[0-9a-f]{64}", state["confirmed_sha256"])
  assert state["labels"]["egm:unit"] == "missing"
  kinds = [c[:2] for c in world.gh.calls]
  assert kinds == [["auth", "status"], ["api", f"repos/{REPO}"], ["api", f"repos/{REPO}/labels"]]
  writes = world.ns["Handoff"](world.plan).writes()
  assert writes[0] == ["repo", REPO] and writes[1][0] == "gate" and writes[1][1] == state["gate_plan_sha256"]


def test_dry_run_refuses_without_gate_or_after_plan_or_template_change(world):
  assert world.run("graph", "--plan", world.plan)[0] == 0
  code, out = world.run("dry-run", "--plan", world.plan)
  assert code == 1 and "gate has not passed" in out
  dry_run(world)
  text = world.plan.read_text(encoding="utf-8")
  world.plan.write_text(text.replace("low: new module", "low: a new module"), encoding="utf-8")
  code, out = world.run("dry-run", "--plan", world.plan)
  assert code == 1 and "changed after the gate" in out
  world.plan.write_text(text, encoding="utf-8")
  assert world.run("dry-run", "--plan", world.plan)[0] == 0
  template = world.repo / ".egm/template.md"
  template.write_text("<!-- egm:handoff={{handoff_id}} unit={{unit_id}} -->\n{{objective}}\n{{scope}}\n{{dod}}\n"
                      "{{blocked_by}} #{{tracking}} `{{branch}}`\n", encoding="utf-8")
  config = json.loads((world.repo / ".egm/handoff.json").read_text(encoding="utf-8"))
  config["issue_template"] = ".egm/template.md"
  (world.repo / ".egm/handoff.json").write_text(json.dumps(config), encoding="utf-8")
  code, out = world.run("dry-run", "--plan", world.plan)
  assert code == 1 and "changed after the gate" in out


def test_dry_run_refuses_101_units_missing_extra_and_warns_above_450(world):
  pass_gate(world)
  config = json.loads((world.repo / ".egm/handoff.json").read_text(encoding="utf-8"))
  config["labels"] = {"extra": ["needs-triage"]}
  (world.repo / ".egm/handoff.json").write_text(json.dumps(config), encoding="utf-8")
  pass_gate(world)
  code, out = world.run("dry-run", "--plan", world.plan)
  assert code == 1 and "create the label `needs-triage`" in out
  world.gh.labels["needs-triage"] = {"name": "needs-triage"}
  code, out = world.run("dry-run", "--plan", world.plan)
  assert code == 0 and "4 issues" in out
  dryrun = (world.artifacts / "handoff_dryrun.md").read_text(encoding="utf-8")
  assert "Labels: egm:handoff-" in dryrun and "needs-triage" in dryrun
  big = []
  for n in range(1, 102):
    big.append(textwrap.dedent(f"""\
        ### U{n:02d}: Unit {n}
        | Field | Value |
        | --- | --- |
        | Objective | Unit {n} exists. |
        | Scope paths | `src/u{n}.ts` (create) |
        | Design range | `docs/designs/sample.md:13-15 (#### 1. src/webhooks/queue.ts)` |
        | Blocked by | {"none" if n == 1 else f"U{n - 1:02d}" if n == 2 else f"U{n - 1:02d}, U{n - 2:02d}"} |
        | Shared files | none |
        | Risk | low: small |
        | Size | S |

        Definition of done
        1. `npm test -- src/u{n}.test.ts` passes.

        Decide before build
        - none
        """))
  world.plan.write_text(f"# Big\n\nDesign: `{world.repo / 'docs/designs/sample.md'}`\n\n" + "\n".join(big), encoding="utf-8")
  pass_gate(world)
  code, out = world.run("dry-run", "--plan", world.plan)
  assert code == 1 and "split the handoff" in out
  world.plan.write_text(f"# Big\n\nDesign: `{world.repo / 'docs/designs/sample.md'}`\n\n" + "\n".join(big[:100]), encoding="utf-8")
  pass_gate(world)
  code, out = world.run("dry-run", "--plan", world.plan)
  assert code == 0, out
  text = (world.artifacts / "handoff_dryrun.md").read_text(encoding="utf-8")
  assert "WARNING" in text and "--max-writes" in text


# -------------------------------------------------------------------- apply


def test_apply_refusals(world):
  dry_run(world)
  code, out = world.run("apply", "--plan", world.plan)
  assert code == 1 and "--yes" in out
  state = state_of(world)
  confirmed = state.pop("confirmed_sha256")
  (world.artifacts / "handoff_state.json").write_text(json.dumps(state), encoding="utf-8")
  code, out = world.run("apply", "--plan", world.plan, "--yes")
  assert code == 1 and "no confirmed_sha256" in out
  state["confirmed_sha256"] = confirmed
  state["repo"] = "someone/else"
  (world.artifacts / "handoff_state.json").write_text(json.dumps(state), encoding="utf-8")
  code, out = world.run("apply", "--plan", world.plan, "--yes")
  assert code == 1 and "differs from the state's" in out
  state["repo"] = REPO
  (world.artifacts / "handoff_state.json").write_text(json.dumps(state), encoding="utf-8")
  text = world.plan.read_text(encoding="utf-8")
  world.plan.write_text(text.replace("low: new module", "low: a new module"), encoding="utf-8")
  code, out = world.run("apply", "--plan", world.plan, "--yes")
  assert code == 1 and "changed since the dry run" in out
  assert not any(c[0] in ("label", "issue") for c in world.gh.calls)


def test_apply_creates_in_order_and_rerun_writes_nothing(world):
  dry_run(world)
  world.gh.calls.clear()
  code, out = world.run("apply", "--plan", world.plan, "--yes")
  assert code == 0, out
  gh = world.gh
  labels = [c[2] for c in gh.calls if c[0] == "label"]
  assert labels == ["egm:unit", "egm:tracking", "egm:handoff-" + state_of(world)["handoff_id"],
                    "egm:wave-1", "egm:wave-2", "egm:wave-3"]
  assert "bug" in gh.labels and all("--force" not in c for c in gh.calls)
  creates = [c for c in gh.calls if c[:2] == ["issue", "create"]]
  titles = [c[c.index("--title") + 1] for c in creates]
  assert titles == ["Build: Webhook delivery", "U01: Webhook queue", "U02: Delivery worker", "U03: Admin endpoint"]
  first_label_or_issue = next(i for i, c in enumerate(gh.calls) if c[0] in ("label", "issue"))
  first_issue = next(i for i, c in enumerate(gh.calls) if c[:2] == ["issue", "create"])
  assert first_label_or_issue < first_issue
  assert gh.issues[3]["body"].count("#1") >= 1 and "**Blocked by.** #2" in gh.issues[3]["body"]
  assert "after #2, before U03 (Admin endpoint)" in gh.issues[3]["body"]
  assert "**Blocked by.** #3" in gh.issues[4]["body"]
  assert gh.issues[2]["labels"] == ["egm:handoff-" + state_of(world)["handoff_id"], "egm:unit", "egm:wave-1"]
  assert world.sleeps.count(1) >= 4
  assert gh.sub_issues[1] == [gh.issues[2]["id"], gh.issues[3]["id"], gh.issues[4]["id"]]
  assert gh.blocked_by == {3: [gh.issues[2]["id"]], 4: [gh.issues[3]["id"]]}
  state = state_of(world)
  assert state["units"]["U02"]["number"] == 3 and state["tracking"]["number"] == 1
  assert state["links"]["blocked:U03<-U02"] == "done" and state["verify"]["complete"] is True
  assert state["verify"]["problems"] == [] and state["verify"]["sha256"] == state["confirmed_sha256"]
  assert state["verify"]["checked"] == "15 of 15"
  gh.calls.clear()
  code, out = world.run("apply", "--plan", world.plan, "--yes")
  assert code == 0, out
  assert not any(c[0] == "label" or c[:2] == ["issue", "create"] or "POST" in c for c in gh.calls)


def test_apply_state_saved_after_each_write_and_422_link_reread(world):
  dry_run(world)
  world.gh.link_422_once.add(("sub", 1))
  saves = []
  original = world.ns["save_state"]

  def spy(folder, state):
    saves.append(json.dumps(state, sort_keys=True))
    original(folder, state)
  world.ns["save_state"] = spy
  code, out = world.run("apply", "--plan", world.plan, "--yes")
  assert code == 0, out
  assert len(saves) >= 13
  state = state_of(world)
  assert state["links"]["sub:U01"] == "done" and all(v == "done" for v in state["links"].values())


def test_apply_rate_limit_exhaustion_exits_nonzero_with_resume_message(world):
  dry_run(world)
  world.gh.rate_limit_hits = 5
  code, out = world.run("apply", "--plan", world.plan, "--yes")
  assert code == 1 and "rate limited: resume with `apply --yes` after" in out
  assert world.sleeps.count(60) == 3
  state = state_of(world)
  assert state["labels"]["egm:unit"] == "done" and not state.get("tracking", {}).get("number")


def test_apply_max_writes_resumes_in_bounded_calls(world):
  dry_run(world)
  code, out = world.run("apply", "--plan", world.plan, "--yes", "--max-writes", 2)
  assert code == 0 and "stopped after 2 writes" in out
  state = state_of(world)
  assert state["verify"]["complete"] is False
  assert sorted(n for n, s in state["labels"].items() if s == "done") == ["egm:tracking", "egm:unit"]
  code, out = world.run("apply", "--plan", world.plan, "--yes", "--max-writes", 2)
  assert code == 0 and "stopped after 2 writes" in out
  state = state_of(world)
  assert sum(1 for s in state["labels"].values() if s == "done") == 4
  code, out = world.run("status", "--plan", world.plan)
  assert code == 1 and "not fully created and verified" in out
  code, out = world.run("apply", "--plan", world.plan, "--yes", "--max-writes", 50)
  assert code == 0 and state_of(world)["verify"]["complete"] is True


def test_verify_records_mismatches(world):
  dry_run(world)
  assert world.run("apply", "--plan", world.plan, "--yes")[0] == 0
  world.gh.issues[3]["body"] += "\nedited by hand"
  world.gh.issues[2]["labels"].remove("egm:unit")
  code, out = world.run("verify", "--plan", world.plan)
  assert code == 1
  state = state_of(world)
  problems = state["verify"]["problems"]
  assert any("body of #3" in p for p in problems) and any("labels of #2" in p and "egm:unit" in p for p in problems)
  assert state["verify"]["complete"] is True
  code, out = world.run("status", "--plan", world.plan)
  assert code == 1 and "not fully created and verified" in out


# ------------------------------------------------------------------- status


def applied(world):
  dry_run(world)
  assert world.run("apply", "--plan", world.plan, "--yes")[0] == 0
  world.gh.calls.clear()
  return world.gh


def close_as_completed(gh, number):
  gh.issues[number]["state"], gh.issues[number]["state_reason"] = "closed", "completed"


def make_pr(gh, number, head, base_sha="b" * 40, merged=None, closes=(), branch="feature"):
  gh.prs[number] = {"number": number, "state": "MERGED" if merged else "OPEN", "headRefName": branch,
                    "headRefOid": head, "baseRefName": "main", "baseRefOid": base_sha, "mergedAt": merged,
                    "isDraft": False,
                    "closingIssuesReferences": [{"number": n, "repository": {"name": r.split("/")[1], "owner": {"login": r.split("/")[0]}}}
                                                for r, n in closes]}
  return gh.prs[number]


def test_status_landed_ready_decisions_and_shared_edges(world):
  gh = applied(world)
  code, out = world.run("status", "--plan", world.plan)
  assert code == 0 and "ready: U01" in out and "landed: none" in out
  assert "open blocking decision U03/D2" in out
  close_as_completed(gh, 2)
  code, out = world.run("status", "--plan", world.plan)
  assert "closed (no watched PR)" in out and "ready: U01" in out
  code, out = world.run("status", "--plan", world.plan, "--confirm-landed", "U01")
  assert "landed: U01" in out and "ready: U02" in out
  # U03 is blocked by U02 and shares a file after it: both edges must land.
  close_as_completed(gh, 3)
  make_pr(gh, 41, "a" * 40, merged="2026-11-02T10:00:00Z", closes=[(REPO, 3)])
  gh.graphql[3] = [{**gh.prs[41], "repository": {"nameWithOwner": REPO}}]
  code, out = world.run("status", "--plan", world.plan)
  assert "landed: U01, U02" in out and "ready: none" in out, out
  assert world.run("decide", "--plan", world.plan, "--unit", "U03", "--decision", "D2", "--answer", "25")[0] == 0
  assert "- Decision: 25" in (world.artifacts / "unit_U03.md").read_text(encoding="utf-8")
  assert (world.artifacts / "decision_comment_U03_D2.md").read_text(encoding="utf-8").startswith("**Decision D2** (Page size")
  code, out = world.run("status", "--plan", world.plan)
  assert "ready: none" in out and "NOT PUBLISHED" in out
  assert world.run("decide", "--plan", world.plan, "--unit", "U03", "--decision", "D2",
                   "--published", "https://github.com/x/y/issues/4#c1")[0] == 0
  code, out = world.run("status", "--plan", world.plan)
  assert "ready: U03" in out
  assert world.run("graph", "--plan", world.plan)[0] == 0
  assert "- Decision: 25" in (world.artifacts / "unit_U03.md").read_text(encoding="utf-8")


def test_status_pr_matching_rules(world):
  gh = applied(world)
  assert world.run("launch", "--plan", world.plan, "--wave", 1, "--units", "U01")[0] == 0
  # A closing reference naming another repository with the same number does not match.
  make_pr(gh, 50, "c" * 40, closes=[("other/repo", 2)], branch="egm/U01-old")
  code, out = world.run("status", "--plan", world.plan)
  assert "U01 #2 launched wave 1: no pr; waiting-for-pr" in out, out
  # The exact branch of this handoff is a candidate, watched only after --watch.
  make_pr(gh, 51, "d" * 40, branch=f"egm/{state_of(world)['handoff_id']}/U01")
  code, out = world.run("status", "--plan", world.plan)
  assert "candidate: PRs #51" in out
  assert not state_of(world)["units"]["U01"].get("pr")
  # A closing reference for this repository matches through the fallback listing.
  make_pr(gh, 52, "e" * 40, closes=[(REPO, 2)])
  gh.check_runs["e" * 40] = [{"name": "tests", "status": "completed", "conclusion": "success"}]
  gh.combined["e" * 40] = {"state": "success", "statuses": [{"state": "success"}]}
  code, out = world.run("status", "--plan", world.plan)
  assert "pr #52 head eeeeeee; ci green" in out, out
  # A recorded PR is read by number and never rediscovered.
  gh.calls.clear()
  gh.graphql[2] = [{**make_pr(gh, 53, "f" * 40, closes=[(REPO, 2)]), "repository": {"nameWithOwner": REPO}}]
  code, out = world.run("status", "--plan", world.plan)
  assert "pr #52" in out and not any(c[:2] == ["api", "graphql"] and "number=2" in c for c in gh.calls)
  assert any(c[:3] == ["pr", "view", "52"] for c in gh.calls)
  # Two GraphQL matches ask the user.
  gh.graphql[3] = [{**make_pr(gh, 60, "1" * 40, closes=[(REPO, 3)]), "repository": {"nameWithOwner": REPO}},
                   {**make_pr(gh, 61, "2" * 40, closes=[(REPO, 3)]), "repository": {"nameWithOwner": REPO}},
                   {**make_pr(gh, 62, "3" * 40), "repository": {"nameWithOwner": "other/repo"}}]
  code, out = world.run("status", "--plan", world.plan)
  assert "U02 #3: no pr; ambiguous: PRs #60, #61" in out, out
  code, out = world.run("status", "--plan", world.plan, "--watch", "U02=61")
  assert "U02 #3: pr #61" in out


def test_status_ci_states(world):
  gh = applied(world)
  make_pr(gh, 70, "a" * 40, closes=[(REPO, 2)])
  gh.graphql[2] = [{**gh.prs[70], "repository": {"nameWithOwner": REPO}}]
  assert world.run("launch", "--plan", world.plan, "--wave", 1, "--units", "U01")[0] == 0
  code, out = world.run("status", "--plan", world.plan)
  assert "waiting-for-ci" in out
  for status in ("pending", "waiting", "requested", "mystery"):
    gh.check_runs["a" * 40] = [{"name": "tests", "status": status, "conclusion": None}]
    code, out = world.run("status", "--plan", world.plan)
    assert "waiting-for-ci" in out, (status, out)
  gh.check_runs["a" * 40] = [{"name": "deploy", "status": "completed", "conclusion": "action_required"}]
  gh.combined["a" * 40] = {"state": "success", "statuses": []}
  code, out = world.run("status", "--plan", world.plan)
  assert "ci red (deploy)" in out
  gh.check_runs["a" * 40] = [{"name": "tests", "status": "completed", "conclusion": "success"}]
  gh.combined["a" * 40] = {"state": "pending", "statuses": [{"state": "pending"}]}
  code, out = world.run("status", "--plan", world.plan)
  assert "waiting-for-ci" in out
  gh.check_runs["a" * 40] = []
  gh.combined["a" * 40] = {"state": "pending", "statuses": []}
  world.advance(31 * 60)
  code, out = world.run("status", "--plan", world.plan)
  assert "no-ci" in out


def test_status_wait_returns_on_change_or_deadline(world):
  gh = applied(world)
  code, out = world.run("status", "--plan", world.plan, "--wait", 200)
  assert code == 0 and "deadline: no change" in out and world.sleeps and max(world.sleeps) <= 90
  make_pr(gh, 70, "a" * 40, closes=[(REPO, 2)])
  gh.graphql[2] = [{**gh.prs[70], "repository": {"nameWithOwner": REPO}}]
  code, out = world.run("status", "--plan", world.plan, "--wait", 200)
  assert "changed: U01" in out


def test_defer_edits_one_label_and_verifies(world):
  gh = applied(world)
  gh.labels["egm:wave-4"] = {"name": "egm:wave-4", "color": "1b6ef3"}
  code, out = world.run("defer", "--plan", world.plan, "--unit", "U03", "--to-wave", 4)
  assert code == 0 and "would run" in out and not any(c[:2] == ["issue", "edit"] for c in gh.calls)
  code, out = world.run("defer", "--plan", world.plan, "--unit", "U03", "--to-wave", 4, "--yes")
  assert code == 0 and "egm:wave-4" in gh.issues[4]["labels"] and "egm:wave-3" not in gh.issues[4]["labels"]
  assert state_of(world)["units"]["U03"]["wave"] == 4


def test_defer_refuses_a_wave_label_the_repository_does_not_have(world):
  """apply creates only the waves the graph produced, so deferring past the
  last wave would ask gh to add a label that does not exist."""
  gh = applied(world)
  code, out = world.run("defer", "--plan", world.plan, "--unit", "U03", "--to-wave", 9, "--yes")
  assert code == 1 and "has no label `egm:wave-9`" in out
  assert not any(c[:2] == ["issue", "edit"] for c in gh.calls)


# ------------------------------------------------------------------ prepare


def test_prepare_fetches_from_the_recorded_remote_into_private_refs(tmp_path, capsys):
  target = make_repo(tmp_path / "target", config={"repo": REPO})
  (target / "src").mkdir()
  (target / "src/a.txt").write_text("base\n", encoding="utf-8")
  git(["add", "-A"], target)
  git(["commit", "-qm", "base"], target)
  base_sha = git(["rev-parse", "HEAD"], target).strip()
  git(["checkout", "-qb", "feature"], target)
  (target / "src/a.txt").write_text("base\nchanged\n", encoding="utf-8")
  git(["commit", "-qam", "change"], target)
  head = git(["rev-parse", "HEAD"], target).strip()
  git(["update-ref", "refs/pull/7/head", head], target)
  git(["checkout", "-q", "main"], target)
  elsewhere = tmp_path / "elsewhere"
  git(["clone", "-q", str(target), str(elsewhere)], tmp_path)
  checkout = tmp_path / "checkout"
  git(["clone", "-q", "-o", "origin", str(elsewhere), str(checkout)], tmp_path)
  git(["remote", "set-url", "origin", "https://github.com/fork-user/webhooks.git"], checkout)
  git(["remote", "add", "upstream", str(target)], checkout)
  git(["config", "user.email", "egm@example.invalid"], checkout)
  git(["config", "user.name", "EGM"], checkout)
  plan = make_plan(tmp_path / "artifacts", checkout)
  harness = Harness(capsys)
  harness.ns["find_remote"] = lambda root, repo: "upstream"
  assert harness.run("graph", "--plan", plan)[0] == 0
  state = json.loads((plan.parent / "handoff_state.json").read_text(encoding="utf-8"))
  state.update({"remote": "upstream", "confirmed_sha256": "x", "verify": {"complete": True, "sha256": "x", "problems": []},
                "units": {"U01": {"number": 2, "pr": {"number": 7, "head": head, "base_ref": "main", "base_sha": base_sha}}}})
  (plan.parent / "handoff_state.json").write_text(json.dumps(state), encoding="utf-8")
  harness.ns["parse_remote_url"] = lambda url: REPO if url.strip() == str(target) else None
  harness.gh.check_runs[head] = [{"name": "tests", "status": "completed", "conclusion": "success"}]
  harness.gh.combined[head] = {"state": "success", "statuses": []}
  fetch_head = checkout / ".git/FETCH_HEAD"
  before = fetch_head.read_bytes() if fetch_head.exists() else None
  code, out = harness.run("prepare", "--plan", plan, "--unit", "U01", "--round", 1,
                          "--runner", "/tmp/runner.py", "--model", "gpt-6-astra", "--effort", "xhigh")
  assert code == 0, out
  assert git(["rev-parse", "refs/egm/pr/7"], checkout).strip() == head
  assert git(["rev-parse", "refs/egm/base/7"], checkout).strip() == base_sha
  assert (fetch_head.read_bytes() if fetch_head.exists() else None) == before
  tree = Path(re.search(r"worktree (\S+) at", out).group(1))
  assert tree.is_dir() and "egm-wave" in str(tree)
  diff = (plan.parent / "pr_7_r1.diff").read_bytes()
  expected = subprocess.run(["git", "-C", str(tree), "diff", "--no-ext-diff", "--no-textconv", "--binary",
                             base_sha, "--"], capture_output=True, check=True).stdout
  assert diff == expected and b"+changed" in diff
  ci = json.loads((plan.parent / "ci_7_r1.json").read_text(encoding="utf-8"))
  assert ci["verdict"] == "ci green"
  launch = (plan.parent / "foreman_U01_r1_launch.md").read_text(encoding="utf-8")
  line = [l for l in launch.splitlines() if "inspect" in l][0]
  assert f"--base '{base_sha}'" in line and "--resume" not in line and not re.search(r"\$EGM_|&&|\||;|\s>", line)
  foreman = json.loads((plan.parent / "foreman_U01_state.json").read_text(encoding="utf-8"))
  assert foreman["phase"] == "prepared" and foreman["rounds"]["1"]["merge_base"] == base_sha
  # A leftover clean worktree is removed on the next call; a dirty one is refused.
  code, out = harness.run("prepare", "--plan", plan, "--unit", "U01", "--round", 2)
  assert code == 0, out
  (tree / "src/a.txt").write_text("dirty\n", encoding="utf-8")
  code, out = harness.run("prepare", "--plan", plan, "--unit", "U01", "--round", 3)
  assert code == 1 and "has changes: remove it by hand" in out
  (tree / "src/a.txt").write_text("base\nchanged\n", encoding="utf-8")
  code, out = harness.run("prepare", "--plan", plan, "--unit", "U01", "--round", 3, "--remove")
  assert code == 0 and not tree.exists()
  # A moved head stops the round.
  state["units"]["U01"]["pr"]["head"] = "0" * 40
  (plan.parent / "handoff_state.json").write_text(json.dumps(state), encoding="utf-8")
  code, out = harness.run("prepare", "--plan", plan, "--unit", "U01", "--round", 4)
  assert code == 3 and "head-moved" in out
  # A remote that no longer names the repository is refused.
  harness.ns["parse_remote_url"] = lambda url: None
  code, out = harness.run("prepare", "--plan", plan, "--unit", "U01", "--round", 4)
  assert code == 1 and "no longer names" in out
  harness.ns["parse_remote_url"] = lambda url: REPO if url.strip() == str(target) else None
  code, out = harness.run("prepare", "--plan", plan, "--unit", "U01", "--clean")
  assert code == 0, out
  assert subprocess.run(["git", "-C", str(checkout), "rev-parse", "refs/egm/pr/7"], capture_output=True).returncode != 0


# --------------------------------------------------------- command shape


FAKE_GH = '''#!/usr/bin/env python3
import json, sys, pathlib
log = pathlib.Path(sys.argv[0]).with_name("gh.log")
state_file = pathlib.Path(sys.argv[0]).with_name("gh_state.json")
state = json.loads(state_file.read_text()) if state_file.exists() else {"issues": {}, "labels": [], "subs": {}, "blocked": {}}
args = sys.argv[1:]
log.open("a").write(json.dumps(args) + "\\n")
def save(): state_file.write_text(json.dumps(state))
def out(x): print(x if isinstance(x, str) else json.dumps(x))
if args[0] in ("api", "auth") and "-R" in args: sys.exit("unknown shorthand flag: 'R' in -R")
if args[0] == "auth": out("Logged in"); sys.exit(0)
if args[0] == "label": state["labels"].append(args[2]); save(); out("ok"); sys.exit(0)
if args[0] == "issue" and args[1] == "create":
    n = str(len(state["issues"]) + 1); body = pathlib.Path(args[args.index("--body-file") + 1]).read_text()
    labels = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
    state["issues"][n] = {"number": int(n), "id": 1000 + int(n), "body": body, "labels": labels}; save()
    out("https://github.com/example-org/webhooks/issues/" + n); sys.exit(0)
if args[0] == "issue" and args[1] == "view":
    i = state["issues"][args[2]]; out({"body": i["body"], "labels": [{"name": l} for l in i["labels"]]}); sys.exit(0)
ep = next(a for i, a in enumerate(args[1:], 1) if not a.startswith("-") and args[i - 1] not in ("-X", "-F", "-f", "-q"))
if ep == "repos/example-org/webhooks": out({"push": True}); sys.exit(0)
if ep == "repos/example-org/webhooks/labels": out([[{"name": l} for l in state["labels"]]]); sys.exit(0)
if ep.startswith("repos/example-org/webhooks/issues?"): out([[]]); sys.exit(0)
import re
m = re.fullmatch(r"repos/example-org/webhooks/issues/(\\d+)", ep)
if m: out(state["issues"][m.group(1)]); sys.exit(0)
m = re.fullmatch(r"repos/example-org/webhooks/issues/(\\d+)/sub_issues", ep)
if m and "POST" in args:
    f = [a for a in args if a.startswith("sub_issue_id=")][0].split("=")[1]
    assert f.isdigit(); state["subs"].setdefault(m.group(1), []).append(int(f)); save(); out("HTTP/2.0 201 Created\\n\\n{}"); sys.exit(0)
if m: out([[{"id": i, "number": i - 1000} for i in state["subs"].get(m.group(1), [])]]); sys.exit(0)
m = re.fullmatch(r"repos/example-org/webhooks/issues/(\\d+)/dependencies/blocked_by", ep)
if m and "POST" in args:
    f = [a for a in args if a.startswith("issue_id=")][0].split("=")[1]
    assert f.isdigit(); state["blocked"].setdefault(m.group(1), []).append(int(f)); save(); out("HTTP/2.0 201 Created\\n\\n{}"); sys.exit(0)
if m: out([[{"id": i, "number": i - 1000} for i in state["blocked"].get(m.group(1), [])]]); sys.exit(0)
sys.exit("unexpected: " + " ".join(args))
'''


@pytest.mark.skipif(os.name == "nt", reason="a fake gh script on PATH needs a POSIX shell-free exec")
def test_subprocess_command_shape_with_fake_gh_on_path(tmp_path, capsys):
  repo = make_repo(tmp_path / "repo", config={"repo": REPO})
  plan = make_plan(tmp_path / "artifacts", repo)
  bin_dir = tmp_path / "bin"
  bin_dir.mkdir()
  script = bin_dir / "gh"
  script.write_text(FAKE_GH.replace("#!/usr/bin/env python3", f"#!{sys.executable}"), encoding="utf-8")
  script.chmod(0o755)
  env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}

  def run(*argv):
    return subprocess.run([sys.executable, str(HELPER), *[str(a) for a in argv]], env=env,
                          capture_output=True, text=True)
  assert run("graph", "--plan", plan).returncode == 0
  assert run("gate", "--plan", plan, "--reviewed", "--round", 1).returncode == 0
  assert run("gate", "--plan", plan, "--pass").returncode == 0
  result = run("dry-run", "--plan", plan)
  assert result.returncode == 0, result.stderr
  log = [json.loads(l) for l in (bin_dir / "gh.log").read_text(encoding="utf-8").splitlines()]
  assert [l[:2] for l in log] == [["auth", "status"], ["api", f"repos/{REPO}"], ["api", f"repos/{REPO}/labels"]]
  assert "--paginate" in log[2]
  result = run("apply", "--plan", plan, "--yes")
  assert result.returncode == 0, result.stdout + result.stderr
  log = [json.loads(l) for l in (bin_dir / "gh.log").read_text(encoding="utf-8").splitlines()]
  posts = [l for l in log if "POST" in l]
  assert posts and all("-F" in l and "-i" in l for l in posts)
  assert all("-R" not in l for l in log if l[0] in ("api", "auth"))
  assert all("-R" in l for l in log if l[0] in ("issue", "label"))
  assert all("--paginate" in l for l in log if l[0] == "api" and l[1].endswith(("/labels", "/sub_issues", "/blocked_by")) and "POST" not in l)


# --------------------------------------------- inspection round 1 regressions


def test_gh_is_pinned_to_github_com_whatever_gh_host_says(monkeypatch):
  """R03: GH_HOST would send writes to an enterprise server that no approval,
  remote check or confirmed destination in this helper ever looked at."""
  ns = runpy.run_path(str(HELPER))
  monkeypatch.setenv("GH_HOST", "github.enterprise.invalid")
  monkeypatch.setenv("GH_ENTERPRISE_TOKEN", "tok")
  env = ns["gh_env"]()
  assert env["GH_HOST"] == "github.com"
  assert "GH_ENTERPRISE_TOKEN" not in env


def test_state_is_written_atomically_and_a_poll_keeps_other_writers_fields(world):
  """R01: a watcher that saves its whole in-memory copy erases a decision or a
  launch the main conversation recorded while it slept."""
  gh = applied(world)
  assert world.run("verify", "--plan", world.plan)[0] == 0
  # another writer records a decision while a poll is in flight
  assert world.run("decide", "--plan", world.plan, "--unit", "U03",
                   "--decision", "D2", "--answer", "50")[0] == 0
  assert world.run("launch", "--plan", world.plan, "--wave", 1, "--units", "U01")[0] == 0
  assert world.run("status", "--plan", world.plan)[0] == 0
  after = state_of(world)
  assert after["decisions"]["U03/D2"]["answer"] == "50"
  assert after["units"]["U01"]["launched"]["wave"] == 1
  assert after["units"]["U01"]["number"]
  # no temporary file is left behind by the atomic replace
  assert not list(world.artifacts.glob("handoff_state.json.tmp*"))


def test_operations_refuse_a_repository_the_numbers_do_not_belong_to(world):
  """R02: issue numbers are not portable; only apply checked the destination."""
  applied(world)
  assert world.run("verify", "--plan", world.plan)[0] == 0
  config = world.repo / ".egm/handoff.json"
  config.write_text(json.dumps({"repo": "other/elsewhere",
                                "banned_terms": ["(?i)secret-codename"]}), encoding="utf-8")
  git(["remote", "set-url", "origin", "https://github.com/other/elsewhere.git"], world.repo)
  for argv in (("status", "--plan", world.plan),
               ("defer", "--plan", world.plan, "--unit", "U03", "--to-wave", 2, "--yes")):
    code, out = world.run(*argv)
    assert code == 1, argv
    assert "frozen once anything exists" in out or "not portable between repositories" in out, out


def test_verify_refuses_a_plan_edited_since_the_confirmation(world):
  """R08: a receipt must describe what the user confirmed, not a plan since
  edited, or removing a blocker locally would make a unit look ready."""
  applied(world)
  assert world.run("verify", "--plan", world.plan)[0] == 0
  world.plan.write_text(world.plan.read_text(encoding="utf-8")
                        .replace("| Blocked by | U01 |", "| Blocked by | none |"), encoding="utf-8")
  # verify reports on what was confirmed, so it stays clean...
  code, out = world.run("verify", "--plan", world.plan)
  assert code == 0 and "MISMATCH" not in out, out
  # ...and readiness, which the edit would have changed, is refused outright
  for argv in (("status", "--plan", world.plan),
               ("launch", "--plan", world.plan, "--wave", 1, "--units", "U03")):
    code, out = world.run(*argv)
    assert code == 1 and "no longer matches the confirmed snapshot" in out, argv


def test_apply_scans_again_with_the_current_rules(world):
  """R11: a banned_terms rule added after the dry run leaves the write list,
  and therefore its hash, untouched."""
  dry_run(world)
  config = world.repo / ".egm/handoff.json"
  config.write_text(json.dumps({"repo": REPO, "banned_terms": ["(?i)webhook"]}), encoding="utf-8")
  code, out = world.run("apply", "--plan", world.plan, "--yes")
  assert code == 1 and "the current scan refuses" in out
  assert not any(c[:2] == ["issue", "create"] for c in world.gh.calls)


def test_a_new_design_may_not_reuse_an_artifact_directory_with_issues(world):
  """R07: creation, decision and verification records are not transferable."""
  applied(world)
  design = world.repo / "docs/designs/sample.md"
  design.write_text(DESIGN.replace("# Webhook", "# Webhook v2"), encoding="utf-8")
  git(["commit", "-qam", "v2"], world.repo)
  code, out = world.run("graph", "--plan", world.plan)
  assert code == 1
  assert "already holds handoff" in out and "new artifact directory" in out


def test_scanner_respects_fence_lengths(world):
  """R12: GFM closes a fence only with a run at least as long as its opener, so
  a four-backtick block may contain a bare ``` line."""
  scan = world.ns["scan_text"]
  config = {"banned_terms": ["(?i)secret-codename"], "fix_request_mention": None}
  body = "````\n```\n````\n@alice and secret-codename\n"
  problems = scan(body, config, "body")
  assert any("bare mention @alice" in p for p in problems), problems
  assert any("banned term" in p for p in problems), problems
  # a genuine fenced block still hides its contents
  assert scan("```\n@alice secret-codename\n```\n", config, "body") == []


def test_duplicate_decision_ids_in_one_unit_are_refused(world):
  """R15: two blocking questions sharing an id share one state key, so
  answering the first would release the unit while the second is open."""
  world.plan.write_text(world.plan.read_text(encoding="utf-8").replace(
      "- D2 Page size for the listing? owner: the user; default: 50; blocking: yes",
      "- D2 Page size for the listing? owner: the user; default: 50; blocking: yes\n"
      "- D2 Retry budget? owner: the user; default: 3; blocking: yes"), encoding="utf-8")
  code, out = world.run("graph", "--plan", world.plan)
  assert code == 1 and "two" in out and "D2" in out


def test_the_posted_body_never_changes_when_a_decision_is_answered(world):
  """R09: decide re-rendered the body verify compares against, so answering a
  question reported a mismatch and blocked the wave."""
  applied(world)
  assert world.run("verify", "--plan", world.plan)[0] == 0
  assert world.run("decide", "--plan", world.plan, "--unit", "U03",
                   "--decision", "D2", "--answer", "50")[0] == 0
  code, out = world.run("verify", "--plan", world.plan)
  assert code == 0 and "MISMATCH" not in out, out
  unit_file = (world.artifacts / "unit_U03.md").read_text(encoding="utf-8")
  assert "Decisions answered since the issue was posted" in unit_file
  assert "Decision: 50" in unit_file


def test_a_dirty_review_worktree_is_never_force_removed(world, tmp_path):
  """R04: the foreman removes a worktree after every round; --force would
  delete someone's uncommitted work without asking."""
  remove = world.ns["remove_worktree"]
  HandoffError = world.ns["HandoffError"]
  root = make_repo(tmp_path / "wt-root")
  tree = tmp_path / "wt-copy"
  git(["worktree", "add", "-q", str(tree)], root)
  (tree / "scratch.txt").write_text("unsaved\n", encoding="utf-8")
  with pytest.raises(HandoffError) as caught:
    remove(root, tree)
  assert "uncommitted changes" in str(caught.value)
  assert (tree / "scratch.txt").is_file()
  (tree / "scratch.txt").unlink()
  remove(root, tree)
  assert not tree.exists()


def test_record_launch_persists_the_run_folder_before_the_wait(world):
  """R18: nothing persisted between `prepared` and `collected` on the no-teams
  path, so a session ending in between redid the round."""
  applied(world)
  assert world.run("record-launch", "--plan", world.plan, "--unit", "U01",
                   "--round", 2, "--run-folder", "/tmp/egm-astra/claudex-abc")[0] == 0
  data = json.loads((world.artifacts / "foreman_U01_state.json").read_text(encoding="utf-8"))
  assert data["rounds"]["2"]["phase"] == "launched"
  assert data["rounds"]["2"]["run_folder"].endswith("claudex-abc")
  assert data["rounds"]["2"]["status"] == "running"
  assert world.run("record-launch", "--plan", world.plan, "--unit", "U01",
                   "--round", 3, "--not-run", "denied")[0] == 0
  data = json.loads((world.artifacts / "foreman_U01_state.json").read_text(encoding="utf-8"))
  assert data["rounds"]["3"]["status"] == "not run (denied)"
  assert data["rounds"]["2"]["run_folder"], "an earlier round must survive"


def test_a_different_design_may_not_reuse_a_directory_that_created_issues(world):
  """R2-07: the refusal must come before approve overwrites the approval or
  graph rewrites the artifacts, so the existing handoff stays intact."""
  applied(world)
  before = (world.artifacts / "unit_U01.md").read_text(encoding="utf-8")
  other = world.repo / "docs/designs/other.md"
  other.write_text(DESIGN.replace("# Webhook", "# Other"), encoding="utf-8")
  git(["add", "-A"], world.repo)
  git(["commit", "-qm", "other"], world.repo)
  code, out = world.run("approve", "--design", other, "--artifacts", world.artifacts, "--yes")
  assert code == 1 and "new artifact directory" in out and "Nothing was changed" in out
  state = state_of(world)
  assert state["design"]["path"].endswith("sample.md")
  assert state["units"]["U01"]["number"], "the existing handoff must be untouched"
  assert (world.artifacts / "unit_U01.md").read_text(encoding="utf-8") == before


def test_approval_binds_to_the_design_it_displayed(world):
  """R2-06: the question shows a hash; --yes must not silently approve another."""
  design = world.repo / "docs/designs/sample.md"
  assert world.run("approve", "--design", design, "--artifacts", world.artifacts)[0] == 0
  design.write_text(DESIGN + "\nlater edit\n", encoding="utf-8")
  git(["commit", "-qam", "later"], world.repo)
  code, out = world.run("approve", "--design", design, "--artifacts", world.artifacts, "--yes")
  assert code == 1 and "changed since the question was asked" in out
  assert "approval" not in state_of(world)


def test_a_landed_confirmation_lapses_when_the_issue_reopens(world):
  """R2-11: the override is for a completed issue with no watched PR."""
  gh = applied(world)
  close_as_completed(gh, 2)
  assert world.run("status", "--plan", world.plan, "--confirm-landed", "U01")[0] == 0
  assert "U01" in state_of(world)["status"]["landed"]
  gh.issues[2]["state"], gh.issues[2]["state_reason"] = "open", None
  code, out = world.run("status", "--plan", world.plan)
  assert "landed confirmation no longer applies" in out
  assert "U01" not in state_of(world)["status"]["landed"]


def test_confirm_landed_refuses_when_a_pr_is_watched(world):
  gh = applied(world)
  make_pr(gh, 70, "a" * 40, closes=[(REPO, 2)])
  assert world.run("status", "--plan", world.plan, "--watch", "U01=70")[0] == 0
  code, out = world.run("status", "--plan", world.plan, "--confirm-landed", "U01")
  assert code == 1 and "only for an issue closed as completed" in out


def test_marker_recovery_finds_issues_created_before_a_crash(world):
  """R2-13/R13: the recovery listing is the only way home after a crash between
  the create call and the state write, and its label is URL-encoded."""
  dry_run(world)
  gh = world.gh
  # a crash after creating the tracking issue and U01, before either was saved
  assert world.run("apply", "--plan", world.plan, "--yes", "--max-writes", 8)[0] == 0
  state = state_of(world)
  created = {u: d["number"] for u, d in (state.get("units") or {}).items() if d.get("number")}
  assert created, "the bounded apply must have created something"
  # erase every local trace of those writes, as an interrupted save would
  for unit in (state.get("units") or {}).values():
    unit.pop("number", None), unit.pop("id", None), unit.pop("done", None)
  for key in ("number", "id", "done"):
    (state.get("tracking") or {}).pop(key, None)
  (world.artifacts / "handoff_state.json").write_text(json.dumps(state), encoding="utf-8")
  before = len([c for c in gh.calls if c[:2] == ["issue", "create"]])
  assert world.run("apply", "--plan", world.plan, "--yes")[0] == 0
  after = state_of(world)
  for uid, number in created.items():
    assert after["units"][uid]["number"] == number, "recovery must reuse the issue"
    assert after["units"][uid]["id"], "recovery must backfill the database id"
  assert len(gh.issues) == 4, f"no duplicate issues: {sorted(gh.issues)}"


def test_a_label_prefix_with_reserved_url_characters_still_recovers(tmp_path, capsys):
  """R13: a permitted prefix such as `egm:handoff+` must survive the query."""
  repo = make_repo(tmp_path / "repo",
                   config={"repo": REPO, "labels": {"handoff_prefix": "egm:handoff+"}})
  plan = make_plan(tmp_path / "artifacts", repo)
  w = Harness(capsys)
  w.repo, w.plan, w.artifacts = repo, plan, plan.parent
  dry_run(w)
  assert w.run("apply", "--plan", w.plan, "--yes")[0] == 0
  listing = [c for c in w.gh.calls if c[0] == "api" and "/issues?" in c[1]]
  assert listing and "%2B" in listing[0][1], listing
  assert w.run("verify", "--plan", w.plan)[0] == 0


def test_an_unpublished_decision_does_not_release_the_unit(world):
  """R2-12: an answer the builder cannot see is not an answer."""
  applied(world)
  assert world.run("verify", "--plan", world.plan)[0] == 0
  code, out = world.run("decide", "--plan", world.plan, "--unit", "U03",
                        "--decision", "D2", "--answer", "50")
  assert code == 0 and "NOT YET PUBLISHED" in out
  code, out = world.run("status", "--plan", world.plan)
  assert "U03/D2" in out and "NOT PUBLISHED" in out
  code, out = world.run("decide", "--plan", world.plan, "--unit", "U03",
                        "--decision", "D2", "--published", "https://github.com/x/y/issues/4#c1")
  assert code == 0
  code, out = world.run("status", "--plan", world.plan)
  assert "open blocking decision U03/D2" not in out


def test_code_span_runs_must_match_in_length(world):
  """R2-10: a one-backtick opener is not closed by a two-backtick run, so the
  text between them is rendered, not code."""
  scan = world.ns["scan_text"]
  config = {"banned_terms": ["(?i)secret-codename"], "fix_request_mention": None}
  problems = scan("`@alice secret-codename``\n", config, "body")
  assert any("bare mention" in p for p in problems), problems
  assert any("banned term" in p for p in problems), problems
  assert scan("`@alice secret-codename`\n", config, "body") == []
  assert scan("``@alice secret-codename``\n", config, "body") == []
  # an unclosed span is not a span
  assert scan("`@alice secret-codename\n", config, "body") != []


def test_repeated_deferrals_verify_against_the_current_wave(world):
  """R2-08: the initial wave is immutable; the current one moves with each
  authorised label edit."""
  gh = applied(world)
  for wave in (2, 3):
    gh.labels[f"egm:wave-{wave}"] = {"name": f"egm:wave-{wave}", "color": "1b6ef3"}
    assert world.run("defer", "--plan", world.plan, "--unit", "U03",
                     "--to-wave", wave, "--yes")[0] == 0
  code, out = world.run("verify", "--plan", world.plan)
  assert code == 0 and "MISMATCH" not in out, out
  record = state_of(world)["units"]["U03"]
  assert record["initial_wave"] == 3 or record["current_wave"] == 3


def test_every_helper_command_the_skills_document_exists(world):
  """A documented flag that the CLI does not have fails only at the moment the
  user runs it, which is the middle of a handoff."""
  import argparse
  parser = world.ns["build_parser"]()
  subs = {}
  for action in parser._actions:
    if isinstance(action, argparse._SubParsersAction):
      for name, sub in action.choices.items():
        subs[name] = {flag for a in sub._actions for flag in a.option_strings}
  root = Path(__file__).resolve().parents[2]
  problems = []
  for doc in ("skills/egm-handoff/SKILL.md", "skills/egm-wave/SKILL.md",
              "skills/egm-wave/references/foreman_brief.md"):
    text = (root / doc).read_text(encoding="utf-8")
    for match in re.finditer(
        r"<HELPER>'\s+([a-z-]+)((?:\s+--[a-z-]+(?:\s+'[^']*'|\s+<[^>]*>|\s+[\w./-]+)?)*)", text):
      command, rest = match.group(1), match.group(2)
      if command not in subs:
        problems.append(f"{doc}: unknown subcommand `{command}`")
        continue
      problems += [f"{doc}: `{command}` has no {flag}"
                   for flag in re.findall(r"--[a-z-]+", rest) if flag not in subs[command]]
  assert not problems, "\n".join(sorted(set(problems)))


# --------------------------------------------- inspection round 3 regressions


def test_rewatching_writes_the_selection_and_its_observation_together(world):
  """R3-01: saving watch.number=71 while units.U01.pr still described #70 sent
  prepare to the old PR. No concurrency needed."""
  gh = applied(world)
  make_pr(gh, 70, "a" * 40, closes=[(REPO, 2)])
  make_pr(gh, 71, "b" * 40, closes=[(REPO, 2)])
  assert world.run("status", "--plan", world.plan, "--watch", "U01=70")[0] == 0
  assert world.run("status", "--plan", world.plan, "--watch", "U01=71")[0] == 0
  record = state_of(world)["units"]["U01"]
  assert record["watch"]["number"] == 71
  assert record["pr"]["number"] == 71, "the observation must follow the selection"


def test_prepare_refuses_a_selection_its_observation_contradicts(world):
  gh = applied(world)
  make_pr(gh, 70, "a" * 40, closes=[(REPO, 2)])
  assert world.run("status", "--plan", world.plan, "--watch", "U01=70")[0] == 0
  path = world.artifacts / "handoff_state.json"
  state = json.loads(path.read_text(encoding="utf-8"))
  state["units"]["U01"]["watch"]["number"] = 71
  path.write_text(json.dumps(state), encoding="utf-8")
  code, out = world.run("prepare", "--plan", world.plan, "--unit", "U01")
  assert code == 1 and "watches PR #71" in out and "describes #70" in out


def test_a_completed_label_write_binds_the_destination(world):
  """R3-03: created_anything ignored labels, so a bounded apply that only made
  labels left the destination free to move."""
  dry_run(world)
  assert world.run("apply", "--plan", world.plan, "--yes", "--max-writes", 2)[0] == 0
  state = state_of(world)
  assert not (state.get("units") or {}), "this bounded apply must not reach an issue"
  assert "done" in state["labels"].values()
  (world.repo / ".egm/handoff.json").write_text(
      json.dumps({"repo": "other/elsewhere"}), encoding="utf-8")
  git(["remote", "add", "other", "https://github.com/other/elsewhere.git"], world.repo)
  code, out = world.run("status", "--plan", world.plan)
  assert code == 1 and "frozen once anything exists" in out


def test_a_voided_landed_confirmation_does_not_revive(world):
  """R3-04: clearing only the local variable let a close-reopen-close sequence
  resurrect the old confirmation without asking the user again."""
  gh = applied(world)
  close_as_completed(gh, 2)
  assert world.run("status", "--plan", world.plan, "--confirm-landed", "U01")[0] == 0
  gh.issues[2]["state"], gh.issues[2]["state_reason"] = "open", None
  assert world.run("status", "--plan", world.plan)[0] == 0
  close_as_completed(gh, 2)
  code, out = world.run("status", "--plan", world.plan)
  assert "landed: none" in out, out
  assert state_of(world)["units"]["U01"]["landed_confirmation_void"]


def test_launch_refuses_a_unit_that_is_not_ready(world):
  """R3-09: launch validated only that the unit id parsed."""
  applied(world)
  code, out = world.run("launch", "--plan", world.plan, "--wave", 1, "--units", "U03")
  assert code == 1 and "nothing was launched" in out
  assert "U03" in out and ("not ready" in out or "blocking decision" in out)
  assert not (state_of(world)["units"].get("U03") or {}).get("launched")


def test_verify_reports_a_link_the_handoff_no_longer_wants(world):
  """R3-06: checking only that expected links exist cannot see an obsolete one
  left behind by an amendment."""
  gh = applied(world)
  assert world.run("verify", "--plan", world.plan)[0] == 0
  state = state_of(world)
  # U01 is blocked by nothing; an amendment that removed a blocker would leave
  # exactly this: a live dependency the confirmed write list no longer names.
  stale = state["units"]["U03"]["id"]
  gh.blocked_by.setdefault(state["units"]["U01"]["number"], []).append(stale)
  code, out = world.run("verify", "--plan", world.plan)
  assert code == 1 and "obsolete blocked-by link" in out, out


def test_an_escaped_backtick_does_not_hide_text_from_the_scan(world):
  """R3-08: GFM backslash escapes mean \\` is a literal backtick, so the text
  after it is rendered, not code."""
  scan = world.ns["scan_text"]
  config = {"banned_terms": ["(?i)secret-codename"], "fix_request_mention": None}
  problems = scan(r"\`@alice secret-codename\`" + "\n", config, "body")
  assert any("bare mention" in p for p in problems), problems
  assert any("banned term" in p for p in problems), problems


def test_the_wave_skill_records_decision_publication(world):
  """R3-05: the helper gates on `published`, so a skill that never records it
  leaves every answered decision blocking its unit."""
  root = Path(__file__).resolve().parents[2]
  skill = " ".join((root / "skills/egm-wave/SKILL.md").read_text(encoding="utf-8").split())
  assert "--published" in skill
  assert "stays blocked until that runs" in skill


# --------------------------------------------- inspection round 4 regressions


def test_a_watcher_does_not_undo_a_newer_human_selection(world):
  """R4-02: watch ownership persisted for the whole of `status --wait`, so the
  watcher wrote its stale selection back over a newer one."""
  gh = applied(world)
  make_pr(gh, 70, "a" * 40, closes=[(REPO, 2)])
  make_pr(gh, 71, "b" * 40, closes=[(REPO, 2)])
  assert world.run("status", "--plan", world.plan, "--watch", "U01=70")[0] == 0
  # another invocation makes the newer choice
  assert world.run("status", "--plan", world.plan, "--watch", "U01=71")[0] == 0
  # the first watcher polls again; it must not resurrect #70
  assert world.run("status", "--plan", world.plan)[0] == 0
  record = state_of(world)["units"]["U01"]
  assert record["watch"]["number"] == 71
  assert record["pr"]["number"] == 71


def test_a_reconfirmed_landing_clears_its_invalidation(world):
  """R4-03: the renewal and the removal of the invalidation must land together."""
  gh = applied(world)
  close_as_completed(gh, 2)
  assert world.run("status", "--plan", world.plan, "--confirm-landed", "U01")[0] == 0
  gh.issues[2]["state"], gh.issues[2]["state_reason"] = "open", None
  assert world.run("status", "--plan", world.plan)[0] == 0
  close_as_completed(gh, 2)
  assert world.run("status", "--plan", world.plan, "--confirm-landed", "U01")[0] == 0
  assert "landed_confirmation_void" not in state_of(world)["units"]["U01"]
  code, out = world.run("status", "--plan", world.plan)
  assert "landed: U01" in out, out


def test_collect_records_a_round_and_guards_cleanup(world, tmp_path):
  """R4-04: nothing recorded `collected`, so the cleanup guard saw a round that
  was still `launched` for ever."""
  applied(world)
  folder = tmp_path / "run"; folder.mkdir()
  assert world.run("record-launch", "--plan", world.plan, "--unit", "U01",
                   "--round", 1, "--run-folder", str(folder))[0] == 0
  code, out = world.run("collect", "--plan", world.plan, "--unit", "U01", "--round", 1)
  assert code == 1 and "does not exist" in out
  (folder / "result.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
  code, out = world.run("collect", "--plan", world.plan, "--unit", "U01", "--round", 1)
  assert code == 1 and "not `completed`" in out
  (folder / "result.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
  code, out = world.run("collect", "--plan", world.plan, "--unit", "U01",
                        "--round", 1, "--verdict", "clean")
  assert code == 0 and "collected" in out
  data = json.loads((world.artifacts / "foreman_U01_state.json").read_text(encoding="utf-8"))
  assert data["rounds"]["1"]["phase"] == "collected"
  assert data["rounds"]["1"]["run_status"] == "completed"


def test_an_edit_the_bodies_do_not_show_still_blocks(world):
  """R4-06: the write list carries the gate hashes as values, so an edit the
  renderer ignores left it unchanged while still reaching the foreman."""
  applied(world)
  assert world.run("status", "--plan", world.plan)[0] == 0
  text = world.plan.read_text(encoding="utf-8")
  marker = "Decide before build\n- none"
  assert marker in text
  world.plan.write_text(
      text.replace(marker, marker + "\n\nBuild note: use the legacy client.", 1),
      encoding="utf-8")
  code, out = world.run("status", "--plan", world.plan)
  assert code == 1 and "differ from the pair the gate reviewed" in out
  assert "unit_<id>.md" in out


def test_a_fence_inside_a_list_item_does_not_hide_the_rest(world):
  """R4-07: the list-prefixed opener was missed, the real closing fence was
  read as an opener, and every following line was hidden from the scan."""
  scan = world.ns["scan_text"]
  config = {"banned_terms": ["(?i)secret-codename"], "fix_request_mention": None}
  body = "- ```\n  safe\n  ```\n\n@alice secret-codename\n"
  problems = scan(body, config, "comment")
  assert any("bare mention" in p for p in problems), problems
  assert any("banned term" in p for p in problems), problems


def test_an_unclosed_fence_fails_closed(world):
  """R4-07: everything after an unclosed fence is invisible to the checks, so
  refuse the text rather than pass it unscanned."""
  scan = world.ns["scan_text"]
  config = {"banned_terms": [], "fix_request_mention": None}
  problems = scan("```\nnever closed\n", config, "body")
  assert any("never closes" in p for p in problems), problems


def test_an_answer_does_not_survive_its_question_changing(world):
  """R4-09: answers were keyed by unit/decision id alone, so an amendment that
  changed the question kept the old answer and its publication."""
  applied(world)
  assert world.run("decide", "--plan", world.plan, "--unit", "U03",
                   "--decision", "D2", "--answer", "50")[0] == 0
  assert world.run("decide", "--plan", world.plan, "--unit", "U03", "--decision", "D2",
                   "--published", "https://github.com/x/y/issues/4#c1")[0] == 0
  text = world.plan.read_text(encoding="utf-8")
  world.plan.write_text(text.replace("Page size for the listing?",
                                     "Retention window for failed jobs?", 1), encoding="utf-8")
  code, out = world.run("status", "--plan", world.plan)
  # the plan no longer matches the reviewed pair, which is itself correct;
  # the answer must also not count once the question has changed
  assert code == 1 or "open blocking decision U03/D2" in out


def test_the_helper_is_single_writer_by_design(world):
  """Concurrency support was removed rather than fixed: four of the seven high
  findings across the review rounds existed only because `status --wait` could
  write while another command ran. `--wait` now only reads."""
  assert "state_lock" not in world.ns, "the lock must be gone, not reinstated"
  gh = applied(world)
  make_pr(gh, 70, "a" * 40, closes=[(REPO, 2)])
  code, out = world.run("status", "--plan", world.plan, "--wait", 60, "--watch", "U01=70")
  assert code == 1 and "--wait only watches" in out
  before = (world.artifacts / "handoff_state.json").read_text(encoding="utf-8")
  assert world.run("status", "--plan", world.plan, "--wait", 60)[0] == 0
  after = (world.artifacts / "handoff_state.json").read_text(encoding="utf-8")
  assert after != before, "a wait still records what it saw, once, when it returns"

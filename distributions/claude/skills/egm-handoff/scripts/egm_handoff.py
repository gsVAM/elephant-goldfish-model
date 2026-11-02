# Copyright 2026 gsVAM. SPDX-License-Identifier: Apache-2.0
# Added by the elephant-goldfish-model Astra fork (gsVAM), 2026.

"""EGM handoff helper: units -> graph, waves, issue bodies, dry run, GitHub.

Standard library only. Run as `python3 '<absolute path>' <subcommand> ...`
from the `egm-handoff` and `egm-wave` skills. Every subcommand is read-only
except `apply --yes` (GitHub writes), `defer --yes` (one label edit) and
`prepare` (refs under `refs/egm/` and worktrees under `${TMPDIR:-/tmp}/egm-wave`).
Every `gh` call goes through `gh()`; tests replace `GH`, `SLEEP` and `NOW`.
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import urllib.parse
import sys
import tempfile
import time
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

LABEL_RE = re.compile(r"^[^,\s]{1,50}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MENTION_CONFIG_RE = re.compile(r"^@[A-Za-z0-9-]+(\[bot\])?$")
MENTION_RE = re.compile(r"(?<![\w./-])@[A-Za-z0-9][A-Za-z0-9-]*(?:\[bot\])?")
REMOTE_URL_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
UNIT_RE = re.compile(r"^### (U\d{2,}): (.+?)\s*$")
UNIT_ID_RE = re.compile(r"^U\d{2,}$")
DESIGN_RANGE_RE = re.compile(r"^`([^`:]+):(\d+)-(\d+) \((.+)\)`$")
SCOPE_RE = re.compile(r"`([^`]+)` \((create|modify|delete)\)")
SHARED_RE = re.compile(r"^`([^`]+)`: (.+)$")
RISK_RE = re.compile(r"^(low|medium|high): (.+)$")
DOD_RE = re.compile(r"^(\d+)\. (.+)$")
DECIDE_RE = re.compile(
    r"^- (D\d+) (.+?) owner: (.+?); default: (.+?); blocking: (yes|no)$")
MARKER_RE = re.compile(r"^<!-- egm:handoff=(\S+) unit=(\S+) -->")
GEN_START, GEN_END = "<!-- egm:generated start -->", "<!-- egm:generated end -->"
FIELDS = ("Objective", "Scope paths", "Design range", "Blocked by",
          "Shared files", "Risk", "Size")
SIZE_LIMIT = {"S": 3, "M": 8, "L": 10**6}
BODY_LIMIT = 65_000
MAX_UNITS = 100
WRITE_WARN = 450
LABEL_COLOR = "1b6ef3"
BRANCH_PREFIX = "egm"
WAITING_STATES = {"queued", "in_progress", "waiting", "requested", "pending"}
GREEN_CONCLUSIONS = {"success", "neutral", "skipped"}
NO_CI_SECONDS = 30 * 60
WAIT_INTERVAL = 90
EFFORTS = ("low", "medium", "high", "xhigh")
MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,63}$")

DEFAULT_CONFIG = {
    "repo": None,
    "labels": {"unit": "egm:unit", "wave_prefix": "egm:wave-",
               "handoff_prefix": "egm:handoff-", "tracking": "egm:tracking",
               "extra": []},
    "issue_template": None,
    "tracking_issue_title": "Build: <design title>",
    "banned_terms": [],
    "fix_request_mention": None,
}

DEFAULT_TEMPLATE = """<!-- egm:handoff={{handoff_id}} unit={{unit_id}} -->
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
"""

TRACKING_TEMPLATE = """<!-- egm:handoff={{handoff_id}} unit=tracking -->
Tracking issue for the build of `{{design}}`. Each unit below is one issue and one PR on a branch `{{branch_prefix}}/<unit>`; a unit starts when every unit it is blocked by has landed.

**Units by wave.**
{{waves}}

**Critical path.** {{critical_path}}

**Shared files.**
{{shared_files}}
"""


class HandoffError(Exception):
  """A stop with a message for the user; exit code 1."""


# ---------------------------------------------------------------- utilities


def sha256_text(text: str) -> str:
  return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
  return hashlib.sha256(path.read_bytes()).hexdigest()


def read_text(path: Path) -> str:
  return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
  path.write_text(text, encoding="utf-8")


def now_iso() -> str:
  return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW()))


def canonical(obj) -> str:
  return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def run_git(args, cwd: Path, check=True) -> str:
  result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8")
  if not check:
    return result.stdout if result.returncode == 0 else ""
  if result.returncode != 0:
    raise HandoffError(f"git {' '.join(args)} failed in {cwd}: "
                       f"{result.stderr.strip() or result.stdout.strip()}")
  return result.stdout


def git_toplevel(path: Path) -> Path:
  folder = path if path.is_dir() else path.parent
  return Path(run_git(["rev-parse", "--show-toplevel"], folder).strip())


class GhError(Exception):

  def __init__(self, args, code, stdout, stderr):
    super().__init__(f"gh {' '.join(args)}: exit {code}: {stderr.strip() or stdout.strip()}")
    self.args_list, self.code, self.stdout, self.stderr = args, code, stdout, stderr

  @property
  def http_status(self):
    for text in (self.stdout, self.stderr):
      match = re.search(r"HTTP(?:/[\d.]+)? (\d{3})", text)
      if match:
        return int(match.group(1))
    return None

  @property
  def rate_limited(self) -> bool:
    text = (self.stdout + self.stderr).lower()
    return self.http_status in (403, 429) and (
        "rate limit" in text or "secondary" in text or "abuse" in text)

  @property
  def retry_after(self):
    match = re.search(r"(?im)^retry-after:\s*(\d+)", self.stdout)
    return int(match.group(1)) if match else None


GH_HOSTNAME = "github.com"


def gh_env():
  """Pin gh to github.com: GH_HOST in the environment would otherwise send
  every write to an enterprise server, which no approval or remote check in
  this helper looks at."""
  env = dict(os.environ)
  env["GH_HOST"] = GH_HOSTNAME
  env.pop("GH_ENTERPRISE_TOKEN", None)
  env.pop("GITHUB_ENTERPRISE_TOKEN", None)
  return env


def _subprocess_gh(args, cwd, stdin=None):
  result = subprocess.run(["gh", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", input=stdin, env=gh_env())
  return result.returncode, result.stdout, result.stderr


GH = _subprocess_gh
SLEEP = time.sleep
NOW = time.time
ARTIFACT_DIR = Path.cwd()


def gh(args, stdin=None) -> str:
  """Run `gh <args>` with cwd = the artifact directory; raise GhError on failure."""
  args = [str(a) for a in args]
  code, out, err = GH(args, ARTIFACT_DIR, stdin)
  if code != 0:
    raise GhError(args, code, out, err)
  return out


def gh_retry(args, stdin=None) -> str:
  """`gh` with the same bounded rate-limit retries the issue and link writes
  get: a secondary limit on a label must not end the run at the first refusal."""
  for attempt in range(4):
    try:
      return gh(args, stdin)
    except GhError as error:
      if error.rate_limited and attempt < 3:
        SLEEP(error.retry_after or 60)
        continue
      raise


def gh_json(args):
  out = gh(args)
  return json.loads(out) if out.strip() else None


def gh_pages(endpoint):
  """A paginated read with `--slurp`: pages are returned as one list, flattened."""
  pages = gh_json(["api", endpoint, "--paginate", "--slurp"]) or []
  items = []
  for page in pages:
    items.extend(page if isinstance(page, list) else [page])
  return items


def gh_post(endpoint, fields):
  """A content-creating `gh api -i -X POST` with secondary-limit retries.

  Returns (status, body_text). Raises GhError when the retries are exhausted.
  """
  args = ["api", "-i", "-X", "POST", endpoint]
  for key, value in fields.items():
    args += ["-F", f"{key}={value}"]
  for attempt in range(4):
    try:
      out = gh(args)
      head, _, body = out.partition("\n\n")
      status = int(re.search(r"HTTP(?:/[\d.]+)? (\d{3})", head).group(1)) if "HTTP" in head else 201
      return status, body
    except GhError as error:
      if error.rate_limited and attempt < 3:
        SLEEP(error.retry_after or 60)
        continue
      raise


# ------------------------------------------------------------- configuration


def parse_remote_url(url: str):
  match = REMOTE_URL_RE.match(url.strip())
  return f"{match.group(1)}/{match.group(2)}" if match else None


def load_config(repo_root: Path) -> dict:
  """Read `.egm/handoff.json`; defaults when missing; unknown keys stop."""
  config = json.loads(json.dumps(DEFAULT_CONFIG))
  path = repo_root / ".egm" / "handoff.json"
  config["_source"] = str(path) if path.is_file() else "defaults (no .egm/handoff.json)"
  if path.is_file():
    data = json.loads(read_text(path))
    unknown = set(data) - set(DEFAULT_CONFIG)
    if unknown:
      raise HandoffError(f"{path}: unknown keys {sorted(unknown)}")
    for key, value in data.items():
      if key == "labels":
        unknown = set(value) - set(DEFAULT_CONFIG["labels"])
        if unknown:
          raise HandoffError(f"{path}: unknown label keys {sorted(unknown)}")
        config["labels"].update(value)
      else:
        config[key] = value
  if not config["repo"]:
    origin = run_git(["remote", "get-url", "origin"], repo_root)
    config["repo"] = parse_remote_url(origin)
    if not config["repo"]:
      raise HandoffError(f"cannot parse OWNER/NAME from origin `{origin.strip()}`: "
                         "set `repo` in .egm/handoff.json")
  if not REPO_RE.match(config["repo"]):
    raise HandoffError(f"invalid repo `{config['repo']}` in {path}")
  labels = config["labels"]
  for name in (labels["unit"], labels["tracking"], *labels["extra"]):
    if not LABEL_RE.match(name):
      raise HandoffError(f"invalid label `{name}` (must match {LABEL_RE.pattern})")
  for prefix in (labels["wave_prefix"], labels["handoff_prefix"]):
    if not prefix or not LABEL_RE.match(prefix):
      raise HandoffError(f"invalid label prefix `{prefix}`")
  mention = config["fix_request_mention"]
  if mention is not None and not MENTION_CONFIG_RE.match(mention):
    raise HandoffError(f"invalid fix_request_mention `{mention}`")
  if not isinstance(config["banned_terms"], list):
    raise HandoffError("banned_terms must be a list of regular expressions")
  for term in config["banned_terms"]:
    re.compile(term)
  config["remote"] = find_remote(repo_root, config["repo"])
  if config["issue_template"]:
    template_path = repo_root / config["issue_template"]
    if not template_path.is_file():
      raise HandoffError(f"issue_template {template_path} does not exist")
    config["_template"] = read_text(template_path)
    check_template(config["_template"])
  else:
    config["_template"] = DEFAULT_TEMPLATE
  return config


def check_template(template: str) -> None:
  first = template.splitlines()[0] if template else ""
  if first != "<!-- egm:handoff={{handoff_id}} unit={{unit_id}} -->":
    raise HandoffError("issue template must start with the marker line "
                       "`<!-- egm:handoff={{handoff_id}} unit={{unit_id}} -->`")
  for name in ("{{objective}}", "{{scope}}", "{{dod}}"):
    if name not in template:
      raise HandoffError(f"issue template lacks {name}")


def find_remote(repo_root: Path, repo: str) -> str:
  for line in run_git(["remote", "-v"], repo_root).splitlines():
    parts = line.split()
    if len(parts) >= 2 and parse_remote_url(parts[1]) == repo:
      return parts[0]
  raise HandoffError(f"no remote for {repo} in {repo_root}: add one or fix "
                     "`repo` in `.egm/handoff.json`")


# ---------------------------------------------------------------- plan parse


class Unit:

  def __init__(self, uid, title, line):
    self.id, self.title, self.line = uid, title, line
    self.objective = ""
    self.scope = []        # [(path, action)]
    self.design_range = None  # (path, start, end, heading)
    self.blockers = []
    self.shared = []       # [(path, [(after|before, uid)])]
    self.risk = None       # (level, reason)
    self.size = None
    self.dod = []
    self.decisions = []    # [{id, question, owner, default, blocking}]

  def to_json(self, wave, preds):
    return {
        "id": self.id, "title": self.title, "objective": self.objective,
        "scope": [{"path": p, "action": a} for p, a in self.scope],
        "design_range": {"path": self.design_range[0], "start": self.design_range[1],
                         "end": self.design_range[2], "heading": self.design_range[3]},
        "blockers": self.blockers,
        "shared": [{"path": p, "order": [{"kind": k, "unit": u} for k, u in o]}
                   for p, o in self.shared],
        "risk": {"level": self.risk[0], "reason": self.risk[1]},
        "size": self.size, "dod": self.dod,
        "decisions": [{k: v for k, v in d.items() if k != "line"} for d in self.decisions],
        "wave": wave, "predecessors": sorted(preds),
    }


class Plan:

  def __init__(self, path: Path):
    self.path = path
    self.text = read_text(path)
    self.title = None
    self.design = None
    self.units = {}
    self.order = []
    self._parse()

  def _parse(self):
    lines = self.text.splitlines()
    inside_generated = False
    i = 0
    while i < len(lines):
      line = lines[i]
      if line.strip() == GEN_START:
        inside_generated = True
      elif line.strip() == GEN_END:
        inside_generated = False
      elif not inside_generated:
        if self.title is None and line.startswith("# "):
          self.title = line[2:].strip()
        elif line.startswith("Design: `") and self.design is None:
          match = re.match(r"^Design: `([^`]+)`", line)
          self.design = match.group(1)
        elif UNIT_RE.match(line):
          i = self._parse_unit(lines, i)
          continue
      i += 1
    if self.design is None:
      raise HandoffError(f"{self.path}:1: no `Design: \\`<path>\\`` line")
    if not self.units:
      raise HandoffError(f"{self.path}: no `### U<nn>: <title>` unit sections")
    self._check_references()

  def _fail(self, index, message):
    raise HandoffError(f"{self.path}:{index + 1}: {message}")

  def _parse_unit(self, lines, i):
    match = UNIT_RE.match(lines[i])
    uid, title = match.group(1), match.group(2)
    if uid in self.units:
      self._fail(i, f"duplicate unit {uid}")
    unit = Unit(uid, title, i + 1)
    i += 1
    if i + 1 >= len(lines) or lines[i].strip() != "| Field | Value |" \
        or lines[i + 1].strip() != "| --- | --- |":
      self._fail(i, f"{uid}: expected the `| Field | Value |` table")
    i += 2
    fields = {}
    while i < len(lines) and lines[i].startswith("|"):
      row = re.match(r"^\| ([^|]+?) \| (.*?) \|$", lines[i])
      if not row:
        self._fail(i, f"{uid}: malformed table row")
      fields[row.group(1)] = (row.group(2).strip(), i)
      i += 1
    for name in FIELDS:
      if name not in fields:
        self._fail(unit.line - 1, f"{uid}: missing field `{name}`")
    unknown = set(fields) - set(FIELDS)
    if unknown:
      self._fail(unit.line - 1, f"{uid}: unknown fields {sorted(unknown)}")
    self._parse_fields(unit, fields)
    while i < len(lines) and not lines[i].strip():
      i += 1
    if i >= len(lines) or lines[i].strip() != "Definition of done":
      self._fail(i if i < len(lines) else len(lines) - 1,
                 f"{uid}: expected `Definition of done`")
    i += 1
    while i < len(lines) and DOD_RE.match(lines[i]):
      item = DOD_RE.match(lines[i]).group(2).strip()
      if not ("`" in item or re.search(r"\bCI\b", item)):
        self._fail(i, f"{uid}: definition-of-done item names no command, path or CI check")
      unit.dod.append(item)
      i += 1
    if not unit.dod:
      self._fail(i, f"{uid}: empty definition of done")
    while i < len(lines) and not lines[i].strip():
      i += 1
    if i >= len(lines) or lines[i].strip() != "Decide before build":
      self._fail(i if i < len(lines) else len(lines) - 1,
                 f"{uid}: expected `Decide before build`")
    i += 1
    while i < len(lines) and lines[i].startswith("- "):
      if lines[i].strip() == "- none":
        i += 1
        continue
      decide = DECIDE_RE.match(lines[i])
      if not decide:
        self._fail(i, f"{uid}: decide-before-build item must read `- D<n> <question> "
                      "owner: <owner>; default: <default>; blocking: yes|no`")
      unit.decisions.append({"id": decide.group(1), "question": decide.group(2),
                             "owner": decide.group(3), "default": decide.group(4),
                             "blocking": decide.group(5) == "yes", "line": i + 1})
      i += 1
    self._check_decision_ids(unit)
    self.units[uid] = unit
    self.order.append(uid)
    return i

  def _parse_fields(self, unit, fields):
    value, line = fields["Objective"]
    if not value:
      self._fail(line, f"{unit.id}: empty objective")
    unit.objective = value
    value, line = fields["Scope paths"]
    unit.scope = SCOPE_RE.findall(value)
    if not unit.scope or ", ".join(f"`{p}` ({a})" for p, a in unit.scope) != value:
      self._fail(line, f"{unit.id}: scope paths must read `path` (create|modify|delete), comma separated")
    value, line = fields["Design range"]
    match = DESIGN_RANGE_RE.match(value)
    if not match or int(match.group(2)) > int(match.group(3)):
      self._fail(line, f"{unit.id}: design range must read `path:start-end (heading)`")
    unit.design_range = (match.group(1), int(match.group(2)), int(match.group(3)), match.group(4))
    value, line = fields["Blocked by"]
    if value != "none":
      unit.blockers = [v.strip() for v in value.split(",")]
      if not all(UNIT_ID_RE.match(b) for b in unit.blockers):
        self._fail(line, f"{unit.id}: blocked by must list unit ids or `none`")
    value, line = fields["Shared files"]
    if value != "none":
      for item in value.split("; "):
        match = SHARED_RE.match(item)
        if not match:
          self._fail(line, f"{unit.id}: shared files must read `path`: after U01, before U05")
        orders = []
        for token in match.group(2).split(", "):
          kind, _, other = token.partition(" ")
          if kind not in ("after", "before") or not UNIT_ID_RE.match(other):
            self._fail(line, f"{unit.id}: shared file order `{token}` is not `after U<nn>` or `before U<nn>`")
          orders.append((kind, other))
        unit.shared.append((match.group(1), orders))
    value, line = fields["Risk"]
    match = RISK_RE.match(value)
    if not match:
      self._fail(line, f"{unit.id}: risk must read `low|medium|high: reason`")
    unit.risk = (match.group(1), match.group(2))
    value, line = fields["Size"]
    if value not in SIZE_LIMIT:
      self._fail(line, f"{unit.id}: size must be S, M or L")
    if len(unit.scope) > SIZE_LIMIT[value]:
      self._fail(line, f"{unit.id}: size {value} allows at most {SIZE_LIMIT[value]} scope paths")
    unit.size = value

  def _check_decision_ids(self, unit):
    seen = {}
    for d in unit.decisions:
      if d["id"] in seen:
        raise HandoffError(
            f"{self.path}:{d.get('line', unit.line)}: unit {unit.id} has two "
            f"decisions with the id {d['id']} (the first is at line "
            f"{seen[d['id']]}): answering one would release the unit while the "
            f"other is still open. Give each decision its own id.")
      seen[d["id"]] = d.get("line", unit.line)

  def _check_references(self):
    for unit in self.units.values():
      for ref in unit.blockers + [u for _, o in unit.shared for _, u in o]:
        if ref not in self.units:
          raise HandoffError(f"{self.path}:{unit.line}: {unit.id} references unknown unit {ref}")
        if ref == unit.id:
          raise HandoffError(f"{self.path}:{unit.line}: {unit.id} references itself")


# ---------------------------------------------------------------- graph


class Graph:

  def __init__(self, plan: Plan):
    self.plan = plan
    units = plan.units
    self.preds = {u: set() for u in units}
    kinds = {}  # (from, to) -> [kind]
    blockers_only = {u: set() for u in units}
    for unit in units.values():
      for b in unit.blockers:
        self.preds[unit.id].add(b)
        blockers_only[unit.id].add(b)
        kinds.setdefault((b, unit.id), []).append("blocked by")
      for path, orders in unit.shared:
        for kind, other in orders:
          if kind == "after":
            self.preds[unit.id].add(other)
            kinds.setdefault((other, unit.id), []).append(f"shared file `{path}`")
          else:
            self.preds[other].add(unit.id)
            kinds.setdefault((unit.id, other), []).append(f"shared file `{path}`")
    self.edges = [(a, b, "; ".join(dict.fromkeys(k))) for (a, b), k in sorted(kinds.items())]
    cycle = find_cycle(blockers_only)
    if cycle:
      raise HandoffError("blocked-by cycle: " + " -> ".join(cycle))
    cycle = find_cycle(self.preds)
    if cycle:
      raise HandoffError("shared-file chain contradicts the blockers: "
                         + " -> ".join(cycle) + " (fix the chain or the blockers)")
    self.order = topo_order(self.preds)
    self.wave = {}
    for u in self.order:
      self.wave[u] = 1 + max((self.wave[p] for p in self.preds[u]), default=0)
    self.waves = {}
    for u in self.order:
      self.waves.setdefault(self.wave[u], []).append(u)
    end = max(self.order, key=lambda u: (self.wave[u], u))
    path = [end]
    while self.preds[path[-1]]:
      path.append(max(self.preds[path[-1]], key=lambda d: (self.wave[d], d)))
    self.critical_path = path[::-1]
    self.dependents = {u: sorted(v for v in units if u in self.preds[v]) for u in units}


def find_cycle(preds):
  try:
    list(TopologicalSorter(preds).static_order())
  except CycleError as error:
    return error.args[1]
  return None


def topo_order(preds):
  placed, order = set(), []
  remaining = dict(preds)
  while remaining:
    ready = sorted(u for u, ps in remaining.items() if ps <= placed)
    if not ready:
      raise HandoffError("cycle: " + ", ".join(sorted(remaining)))
    order.append(ready[0])
    placed.add(ready[0])
    del remaining[ready[0]]
  return order


# ---------------------------------------------------------------- rendering


class Handoff:
  """A parsed plan, its graph, config, design facts and rendered bodies."""

  def __init__(self, plan_path: Path, state=None):
    self.plan_path = plan_path.resolve()
    self.artifact_dir = self.plan_path.parent
    self.plan = Plan(self.plan_path)
    design = Path(self.plan.design).expanduser()
    if not design.is_absolute():
      design = (self.artifact_dir / design).resolve()
    if not design.is_file():
      raise HandoffError(f"design file {design} does not exist")
    design = design.resolve()
    self.design_path = design
    self.design_sha = sha256_file(design)
    self.repo_root = git_toplevel(design)
    # An unrelated commit after approval must not change a single rendered
    # body: the gate hashes, a bounded resume and verify all depend on them.
    recorded = ((state if state is not None else load_state(self.artifact_dir))
                .get("approval") or {}).get("commit")
    self.design_commit = recorded or run_git(
        ["rev-parse", "--short", "HEAD"], self.repo_root).strip()
    self.design_title = next((l[2:].strip() for l in read_text(design).splitlines()
                              if l.startswith("# ")), design.stem)
    self.config = load_config(self.repo_root)
    self.graph = Graph(self.plan)
    slug = re.sub(r"[^a-z0-9]+", "-", design.stem.lower()).strip("-")[:20].rstrip("-")
    self.handoff_id = f"{slug}-{self.design_sha[:6]}"
    self.state = state if state is not None else load_state(self.artifact_dir)
    if self.state.get("approval") and self.state["approval"].get("design_sha256") != self.design_sha:
      raise HandoffError("design changed since the handoff started: re-run the gate")
    self.check_labels()

  # labels
  @property
  def labels(self):
    return self.config["labels"]

  def handoff_label(self):
    return self.labels["handoff_prefix"] + self.handoff_id

  def wave_label(self, wave):
    return f"{self.labels['wave_prefix']}{wave}"

  def unit_labels(self, uid):
    return sorted({self.labels["unit"], self.wave_label(self.graph.wave[uid]),
                   self.handoff_label(), *self.labels["extra"]})

  def tracking_labels(self):
    return sorted({self.labels["tracking"], self.handoff_label()})

  def derived_labels(self):
    names = [self.labels["unit"], self.labels["tracking"], self.handoff_label()]
    names += [self.wave_label(w) for w in sorted(self.graph.waves)]
    return names

  def check_labels(self):
    for name in self.derived_labels():
      if not LABEL_RE.match(name):
        raise HandoffError(f"derived label `{name}` is longer than 50 characters "
                           "or holds a comma or whitespace")

  # titles and bodies
  def tracking_title(self):
    return self.config["tracking_issue_title"].replace("<design title>", self.design_title)

  def unit_title(self, uid):
    return f"{uid}: {self.plan.units[uid].title}"

  def design_ref(self, unit=None):
    rel = self.design_path.relative_to(self.repo_root).as_posix()
    if unit is None:
      return f"{rel}@{self.design_commit}"
    _, start, end, heading = unit.design_range
    return f"{unit.design_range[0]}@{self.design_commit} lines {start}-{end} ({heading})"

  def branch(self, uid):
    return f"{BRANCH_PREFIX}/{self.handoff_id}/{uid}"

  def ref(self, uid):
    """A blocker or `after` reference: a placeholder until apply fills numbers."""
    return f"#<{uid}>"

  def forward_ref(self, uid):
    return f"{uid} ({self.plan.units[uid].title})"

  def decision_lines(self, unit, answers=False):
    """Render the unit's decisions.

    `answers` is False for anything that becomes a GitHub issue body: the
    posted body must stay byte-identical to what the user confirmed, or verify
    reports a mismatch and the wave cannot start. Answers reach the issue as a
    comment (`decision_comment_*.md`) and the foreman through the unit file."""
    if not unit.decisions:
      return "- none"
    lines = []
    for d in unit.decisions:
      line = (f"- {d['id']} {d['question']} Owner: {d['owner']}. Default: {d['default']}. "
              f"Blocking: {'yes' if d['blocking'] else 'no'}.")
      answer = self.state.get("decisions", {}).get(f"{unit.id}/{d['id']}")
      if answers and answer:
        line += f"\n  - Decision: {answer['answer']}"
      lines.append(line)
    return "\n".join(lines)

  def render_unit(self, uid):
    unit = self.plan.units[uid]
    shared = []
    for path, orders in unit.shared:
      parts = [f"after {self.ref(o)}" if k == "after" else f"before {self.forward_ref(o)}"
               for k, o in orders]
      shared.append(f"- `{path}`: " + ", ".join(parts))
    values = {
        "handoff_id": self.handoff_id, "unit_id": uid, "title": unit.title,
        "objective": unit.objective,
        "scope": "\n".join(f"- `{p}` ({a})" for p, a in unit.scope),
        "dod": "\n".join(f"- [ ] {item}" for item in unit.dod),
        "blocked_by": ", ".join(self.ref(b) for b in unit.blockers) or "none",
        "shared": "\n".join(shared) or "- none",
        "decisions": self.decision_lines(unit),
        "risk": f"{unit.risk[0]} ({unit.risk[1]})", "size": unit.size,
        "design": self.design_ref(unit), "tracking": "<tracking>",
        "wave": str(self.graph.wave[uid]), "branch": self.branch(uid),
    }
    return substitute(self.config["_template"], values)

  def render_tracking(self):
    g = self.graph
    rows = ["| Wave | Unit | Title | Blocked by |", "| --- | --- | --- | --- |"]
    for wave in sorted(g.waves):
      for uid in g.waves[wave]:
        blockers = ", ".join(self.plan.units[uid].blockers) or "none"
        rows.append(f"| {wave} | {uid} | {self.plan.units[uid].title} | {blockers} |")
    shared = {}
    for unit in self.plan.units.values():
      for path, _ in unit.shared:
        shared.setdefault(path, []).append(unit.id)
    shared_lines = [f"- `{p}`: " + ", ".join(sorted(set(us))) for p, us in sorted(shared.items())]
    values = {"handoff_id": self.handoff_id, "design": self.design_ref(),
              "branch_prefix": f"{BRANCH_PREFIX}/{self.handoff_id}",
              "waves": "\n".join(rows),
              "critical_path": " -> ".join(g.critical_path),
              "shared_files": "\n".join(shared_lines) or "- none"}
    return substitute(TRACKING_TEMPLATE, values)

  def writes(self):
    """The canonical write list: destination, gate hashes, then every write."""
    items = [["repo", self.config["repo"]],
             ["gate", self.state.get("gate_plan_sha256"), self.state.get("gate_bodies_sha256")]]
    items += [["label", name] for name in self.derived_labels()]
    items.append(["issue", "tracking", self.tracking_title(), self.tracking_labels(),
                  self.render_tracking()])
    for uid in self.graph.order:
      items.append(["issue", uid, self.unit_title(uid), self.unit_labels(uid),
                    self.render_unit(uid)])
    for uid in self.graph.order:
      items.append(["sub_issue", uid])
    for uid in self.graph.order:
      for b in sorted(self.plan.units[uid].blockers):
        items.append(["blocked_by", uid, b])
    return items

  def bodies_text(self):
    parts = []
    for item in self.writes():
      if item[0] == "issue":
        parts.append(f"## {item[1]}\n\nTitle: {item[2]}\nLabels: {', '.join(item[3])}\n\n"
                     f"```markdown\n{item[4]}```\n")
    return "# Rendered issue bodies (creation order)\n\n" + "\n".join(parts)

  def unit_file(self, uid):
    return self.artifact_dir / f"unit_{uid}.md"

  def unit_file_text(self, uid):
    unit = self.plan.units[uid]
    section = unit_section_text(self.plan, uid)
    text = (f"{section}\n\n## Issue body as posted\n\n"
            f"```markdown\n{self.render_unit(uid)}```\n")
    answered = [d for d in unit.decisions
                if self.state.get("decisions", {}).get(f"{uid}/{d['id']}")]
    if answered:
      # Kept out of the issue body on purpose (the posted body must stay
      # byte-identical for verify); the answer reaches the issue as a comment.
      text += "\n## Decisions answered since the issue was posted\n\n"
      text += self.decision_lines(unit, answers=True) + "\n"
    return text

  def generated_section(self):
    g = self.graph
    lines = [GEN_START, "## Generated by `egm_handoff.py graph` (do not edit)", "",
             f"Handoff id: `{self.handoff_id}`. Units: {len(self.plan.units)}. "
             f"Waves: {len(g.waves)}. Design: `{self.design_ref()}`.", "",
             "### Edges", "", "| From | To | Kind |", "| --- | --- | --- |"]
    lines += [f"| {a} | {b} | {k} |" for a, b, k in g.edges] or ["| - | - | no edges |"]
    lines += ["", "### Waves", "", "| Wave | Units |", "| --- | --- |"]
    lines += [f"| {w} | " + ", ".join(f"{u} ({self.plan.units[u].title})" for u in g.waves[w]) + " |"
              for w in sorted(g.waves)]
    lines += ["", "### Critical path", "", " -> ".join(g.critical_path), "",
              "### Blocking decisions", ""]
    blocking = [f"- {u.id}/{d['id']} {d['question']} (owner: {d['owner']}; default: {d['default']})"
                for u in self.plan.units.values() for d in u.decisions if d["blocking"]]
    lines += blocking or ["- none"]
    lines += [GEN_END]
    return "\n".join(lines) + "\n"

  def write_graph_files(self):
    text = self.plan.text
    section = self.generated_section()
    if GEN_START in text and GEN_END in text:
      start, end = text.index(GEN_START), text.index(GEN_END) + len(GEN_END)
      new_text = text[:start] + section.rstrip("\n") + text[end:]
    else:
      new_text = text.rstrip("\n") + "\n\n" + section
    if new_text != text:
      write_text(self.plan_path, new_text)
      self.plan = Plan(self.plan_path)
    units = {u: self.plan.units[u].to_json(self.graph.wave[u], self.graph.preds[u])
             for u in self.graph.order}
    data = {"handoff_id": self.handoff_id, "repo": self.config["repo"],
            "design": {"path": str(self.design_path), "sha256": self.design_sha,
                       "commit": self.design_commit, "title": self.design_title},
            "order": self.graph.order, "waves": {str(w): us for w, us in sorted(self.graph.waves.items())},
            "critical_path": self.graph.critical_path,
            "edges": [{"from": a, "to": b, "kind": k} for a, b, k in self.graph.edges],
            "units": units}
    write_text(self.artifact_dir / "handoff_units.json", json.dumps(data, indent=2) + "\n")
    for uid in self.graph.order:
      write_text(self.unit_file(uid), self.unit_file_text(uid))
    write_text(self.artifact_dir / "handoff_bodies.md", self.bodies_text())
    previous = self.state.get("handoff_id")
    if previous and previous != self.handoff_id:
      created = [u for u, d in (self.state.get("units") or {}).items() if d.get("number")]
      if created or (self.state.get("tracking") or {}).get("number"):
        raise HandoffError(
            f"{self.artifact_dir} already holds handoff {previous} with issues on "
            f"GitHub ({', '.join(created) or 'tracking'}); this design is handoff "
            f"{self.handoff_id}. Creation, decision and verification records are "
            f"not transferable: start the new handoff in a new artifact directory.")
      for key in ("confirmed", "confirmed_sha256", "confirmed_at", "labels",
                  "dry_run", "verify", "gate", "readiness", "units", "tracking",
                  "decisions"):
        self.state.pop(key, None)
    self.state.update({"handoff_id": self.handoff_id, "repo": self.config["repo"],
                       "remote": self.config["remote"], "repo_root": str(self.repo_root),
                       "plan": str(self.plan_path),
                       "design": {"path": str(self.design_path), "sha256": self.design_sha,
                                  "commit": self.design_commit}})
    save_state(self.artifact_dir, self.state)


def unit_section_text(plan: Plan, uid: str) -> str:
  lines = plan.text.splitlines()
  start = plan.units[uid].line - 1
  end = start + 1
  while end < len(lines) and not UNIT_RE.match(lines[end]) and lines[end].strip() != GEN_START \
      and not lines[end].startswith("## "):
    end += 1
  return "\n".join(lines[start:end]).rstrip()


def substitute(template: str, values: dict) -> str:
  def replace(match):
    key = match.group(1)
    if key not in values:
      raise HandoffError(f"issue template uses unknown placeholder {{{{{key}}}}}")
    return values[key]
  return re.sub(r"\{\{(\w+)\}\}", replace, template)


def fill_numbers(body: str, numbers: dict, tracking=None) -> str:
  def replace(match):
    key = match.group(1)
    if key == "tracking":
      return f"#{tracking}" if tracking else match.group(0)
    return f"#{numbers[key]}" if key in numbers else match.group(0)
  return re.sub(r"#<([A-Za-z0-9]+)>", replace, body)


# ---------------------------------------------------------------- state


def state_path(artifact_dir: Path) -> Path:
  return artifact_dir / "handoff_state.json"


def load_state(artifact_dir: Path) -> dict:
  path = state_path(artifact_dir)
  return json.loads(read_text(path)) if path.is_file() else {}


def save_state(artifact_dir: Path, state: dict) -> None:
  """Replace the state file atomically: a truncating write interrupted here
  leaves invalid JSON and no handoff can be resumed from it."""
  path = state_path(artifact_dir)
  tmp = path.with_name(path.name + f".tmp{os.getpid()}")
  tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
  os.replace(tmp, path)


def normalise(body: str) -> str:
  return "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").split("\n")).strip("\n")


# ---------------------------------------------------------------- scan


FENCE_RE = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})(?P<info>.*)$")


def strip_code(text: str):
  """Yield (line number, text outside code spans and fenced blocks).

  GFM closes a fence only with a run of the same character at least as long as
  the opener, so a four-backtick block may contain a bare ``` line. Treating
  every ``` as a toggle hid the rest of the body from the scanner, which is how
  a banned term or a bare mention would reach GitHub."""
  opener = None
  for number, line in enumerate(text.splitlines(), start=1):
    match = FENCE_RE.match(line)
    if opener is None:
      if match and "`" not in match.group("info"):
        opener = (match.group("fence")[0], len(match.group("fence")))
        yield number, ""
        continue
      yield number, re.sub(r"(?P<t>`+)(?:[^`]|(?!(?P=t))`)*(?P=t)", "", line)
      continue
    char, length = opener
    if (match and match.group("fence")[0] == char
        and len(match.group("fence")) >= length and not match.group("info").strip()):
      opener = None
    yield number, ""


def scan_text(text: str, config: dict, kind: str, dod=None, label="body"):
  problems = []
  size = len(text.encode("utf-8"))
  if size > BODY_LIMIT:
    problems.append(f"{label}: {size} bytes exceeds {BODY_LIMIT}: shorten or split the unit")
  terms = [re.compile(t) for t in config["banned_terms"]]
  mention = config.get("fix_request_mention")
  for number, line in strip_code(text):
    for term in terms:
      if term.search(line):
        problems.append(f"{label}:{number}: banned term /{term.pattern}/")
    for found in MENTION_RE.findall(line):
      if kind == "comment" and number == 1 and mention and found == mention:
        continue
      problems.append(f"{label}:{number}: bare mention {found} outside code (it would notify that user)")
  for number, line in enumerate(text.splitlines(), start=1):
    if re.match(r"^(<<<<<<<|=======|>>>>>>>)( |$)", line):
      problems.append(f"{label}:{number}: merge marker")
  for item in dod or []:
    if item not in text:
      problems.append(f"{label}: definition-of-done item missing from the body: {item}")
  return problems


def scan_handoff(handoff: Handoff):
  problems = []
  for item in handoff.writes():
    if item[0] == "issue":
      dod = handoff.plan.units[item[1]].dod if item[1] != "tracking" else []
      problems += scan_text(item[4], handoff.config, "body", dod, label=item[1])
      problems += scan_text(item[2], handoff.config, "body", label=f"{item[1]} title")
  return problems


# ---------------------------------------------------------------- commands


def locate(args):
  """Resolve the plan path from --plan or --state and set ARTIFACT_DIR."""
  global ARTIFACT_DIR
  if getattr(args, "plan", None):
    plan = Path(args.plan).expanduser().resolve()
  else:
    state = load_state(Path(args.state).expanduser().resolve().parent)
    if not state.get("plan"):
      raise HandoffError("state holds no plan path: run `graph` first")
    plan = Path(state["plan"])
  if not plan.is_file():
    raise HandoffError(f"plan {plan} does not exist")
  ARTIFACT_DIR = plan.parent
  return plan


def cmd_approve(args):
  global ARTIFACT_DIR
  design = Path(args.design).expanduser().resolve()
  artifacts = Path(args.artifacts).expanduser().resolve()
  artifacts.mkdir(parents=True, exist_ok=True)
  ARTIFACT_DIR = artifacts
  if not design.is_file():
    raise HandoffError(f"design {design} does not exist")
  root = git_toplevel(design)
  if not run_git(["ls-files", "--error-unmatch", "--", str(design)], root, check=False).strip():
    raise HandoffError(f"{design} is not tracked by git (an ignored or untracked "
                       f"file passes a clean `status`): commit it first (Phase 4)")
  if run_git(["status", "--porcelain", "--", str(design)], root).strip():
    raise HandoffError(f"{design} is tracked but not clean: commit it first (Phase 4)")
  text = read_text(design)
  for heading in ("## Detailed Implementation Plan", "### Target Files to Create/Modify",
                  "### Verification Plan"):
    if heading not in text:
      raise HandoffError(f"{design} has no `{heading}`: run egm-draft and egm-review "
                         "(Stage 9) first; a design without an implementation plan "
                         "cannot be handed off")
  evidence = None
  if args.evidence:
    evidence = Path(args.evidence).expanduser().resolve()
    if not evidence.is_file():
      raise HandoffError(f"evidence {evidence} does not exist")
    if design.name not in read_text(evidence):
      raise HandoffError(f"{evidence} does not name {design.name}")
  sha = sha256_file(design)
  commit = run_git(["rev-parse", "--short", "HEAD"], root).strip()
  rel = design.relative_to(root).as_posix()
  if not run_git(["cat-file", "-t", f"{commit}:{rel}"], root, check=False).strip():
    raise HandoffError(f"{rel} does not exist at commit {commit}: commit it first (Phase 4)")
  stamp = time.strftime("%Y-%m-%d", time.gmtime(evidence.stat().st_mtime)) if evidence else None
  question = (f"Approve `{design}` (sha256 `{sha[:12]}`, commit `{commit}`) for handoff? "
              f"Evidence: {f'`{evidence}` (modified {stamp})' if evidence else 'none given'}.")
  if not args.yes:
    print(question)
    print("Options: Approve | Stop. Run again with --yes after the user chose Approve.")
    return 0
  state = load_state(artifacts)
  state["approval"] = {"design": str(design), "design_sha256": sha, "commit": commit,
                       "evidence": str(evidence) if evidence else None,
                       "answer": "Approve", "approved_at": now_iso()}
  state["design"] = {"path": str(design), "sha256": sha, "commit": commit}
  save_state(artifacts, state)
  print(f"approval recorded in {state_path(artifacts)}")
  return 0


def cmd_graph(args):
  plan = locate(args)
  handoff = Handoff(plan)
  handoff.write_graph_files()
  g = handoff.graph
  print(f"handoff {handoff.handoff_id} on {handoff.config['repo']} (remote {handoff.config['remote']}): "
        f"{len(handoff.plan.units)} units, {len(g.waves)} waves, labels ok")
  for wave in sorted(g.waves):
    print(f"wave {wave}: {', '.join(g.waves[wave])}")
  print("critical path: " + " -> ".join(g.critical_path))
  print(f"wrote handoff_units.json, {len(g.order)} unit_*.md, handoff_bodies.md in {handoff.artifact_dir}")
  return 0


def cmd_scan(args):
  plan = locate(args)
  handoff = Handoff(plan)
  if args.comment:
    path = Path(args.comment).expanduser().resolve()
    problems = scan_text(read_text(path), handoff.config, "comment", label=path.name)
  else:
    problems = scan_handoff(handoff)
  for problem in problems:
    print(problem)
  print("scan: clean" if not problems else f"scan: {len(problems)} problem(s)")
  return 1 if problems else 0


def gate_hashes(handoff: Handoff):
  return sha256_file(handoff.plan_path), sha256_text(handoff.bodies_text())


def cmd_gate(args):
  plan = locate(args)
  handoff = Handoff(plan)
  handoff.write_graph_files()
  state = handoff.state
  plan_sha, bodies_sha = gate_hashes(handoff)
  gate = state.setdefault("gate", {})
  if args.what_ran:
    gate["what_ran"] = list(args.what_ran)
  if args.readiness:
    state["readiness"] = {"summary": args.readiness, "recorded_at": now_iso()}
    save_state(handoff.artifact_dir, state)
    print("readiness recorded")
    return 0
  if args.reviewed:
    write_text(handoff.artifact_dir / "gate_reviewed_plan.md", read_text(handoff.plan_path))
    write_text(handoff.artifact_dir / "gate_reviewed_bodies.md", handoff.bodies_text())
    gate["reviewed"] = {"round": args.round, "plan_sha256": plan_sha, "bodies_sha256": bodies_sha}
    save_state(handoff.artifact_dir, state)
    print(f"round {args.round}: reviewed pair recorded ({plan_sha[:12]}, {bodies_sha[:12]})")
    return 0
  reviewed = gate.get("reviewed")
  if not reviewed:
    raise HandoffError("no reviewed pair: run `gate --reviewed --round <n>` before the round's reviewers")
  changed = (reviewed["plan_sha256"], reviewed["bodies_sha256"]) != (plan_sha, bodies_sha)
  if args.pass_gate:
    if changed:
      raise HandoffError(f"the plan or the bodies changed after round {reviewed['round']} was "
                         "reviewed: run one more Stage 10 round (or decline the remaining fixes)")
    state["gate_plan_sha256"], state["gate_bodies_sha256"] = plan_sha, bodies_sha
    gate.update({"passed": "converged", "round": reviewed["round"], "passed_at": now_iso()})
    state.pop("gate_unreviewed_diff", None)
    save_state(handoff.artifact_dir, state)
    print(f"gate passed at round {reviewed['round']}: gate_plan_sha256 {plan_sha[:12]}, "
          f"gate_bodies_sha256 {bodies_sha[:12]}")
    return 0
  if args.accept:
    state["gate_plan_sha256"], state["gate_bodies_sha256"] = plan_sha, bodies_sha
    gate.update({"passed": "accepted at cap", "round": reviewed["round"], "passed_at": now_iso()})
    if changed:
      diff = []
      for name, current in (("handoff_plan.md", read_text(handoff.plan_path)),
                            ("handoff_bodies.md", handoff.bodies_text())):
        old = read_text(handoff.artifact_dir / f"gate_reviewed_{name.split('_')[1]}")
        diff += difflib.unified_diff(old.splitlines(True), current.splitlines(True),
                                     f"reviewed/{name}", f"current/{name}")
      write_text(handoff.artifact_dir / "gate_unreviewed.diff", "".join(diff))
      state["gate_unreviewed_diff"] = "gate_unreviewed.diff"
    save_state(handoff.artifact_dir, state)
    print("gate accepted at the cap" + (": unreviewed changes in gate_unreviewed.diff" if changed else ""))
    return 0
  raise HandoffError("gate needs one of --reviewed, --pass, --accept or --readiness")


def preflight(handoff: Handoff):
  repo = handoff.config["repo"]
  results = {}
  try:
    gh(["auth", "status", "--hostname", "github.com"])
    results["auth"] = "ok"
  except GhError as error:
    raise HandoffError(f"gh is not logged in to github.com: {error}") from error
  permissions = gh_json(["api", f"repos/{repo}", "-q", ".permissions"]) or {}
  results["push"] = bool(permissions.get("push"))
  if not results["push"]:
    raise HandoffError(f"no push access to {repo}: labels would be dropped silently")
  results["labels"] = {label["name"] for label in gh_pages(f"repos/{repo}/labels")}
  return results


def cmd_dry_run(args):
  plan = locate(args)
  handoff = Handoff(plan)
  state = handoff.state
  if not state.get("gate_plan_sha256") or not state.get("gate_bodies_sha256"):
    raise HandoffError("the gate has not passed: no gate_plan_sha256 / gate_bodies_sha256 in the state")
  handoff.write_graph_files()
  plan_sha, bodies_sha = gate_hashes(handoff)
  if (plan_sha, bodies_sha) != (state["gate_plan_sha256"], state["gate_bodies_sha256"]):
    raise HandoffError("the plan, the config or the issue template changed after the gate: run the gate again")
  if len(handoff.plan.units) > MAX_UNITS:
    raise HandoffError(f"{len(handoff.plan.units)} units: split the handoff (a parent takes at most {MAX_UNITS} sub-issues)")
  problems = scan_handoff(handoff)
  if problems:
    raise HandoffError("scan failed:\n" + "\n".join(problems))
  checks = preflight(handoff)
  missing_extra = [l for l in handoff.labels["extra"] if l not in checks["labels"]]
  if missing_extra:
    raise HandoffError(f"create the label `{missing_extra[0]}` on {handoff.config['repo']} or remove it from `extra`")
  labels = {}
  for name in handoff.derived_labels():
    labels[name] = state.get("labels", {}).get(name) if state.get("labels", {}).get(name) == "done" \
        else ("exists" if name in checks["labels"] else "missing")
  writes = handoff.writes()
  to_create = [n for n, s in labels.items() if s == "missing"]
  issues = [w for w in writes if w[0] == "issue"]
  subs = [w for w in writes if w[0] == "sub_issue"]
  blocked = [w for w in writes if w[0] == "blocked_by"]
  total = len(to_create) + len(issues) + len(subs) + len(blocked)
  confirmed = sha256_text(canonical(writes))
  lines = [f"# Handoff dry run: `{handoff.handoff_id}` on {handoff.config['repo']}", "",
           f"Config: `{handoff.config['_source']}`. Remote: `{handoff.config['remote']}`. "
           f"Template: `{handoff.config['issue_template'] or 'default (built into the helper)'}`.",
           f"Gate: plan `{plan_sha[:12]}`, bodies `{bodies_sha[:12]}` "
           f"({state.get('gate', {}).get('passed', 'recorded')}, round {state.get('gate', {}).get('round', '?')}).",
           "What ran: " + ("; ".join(state.get("gate", {}).get("what_ran", [])) or "not recorded"),
           "Readiness: " + state.get("readiness", {}).get("summary", "not recorded"),
           f"Preflight: gh auth ok; push access ok; {len(checks['labels'])} labels on the repository.", "",
           f"Writes: {len(to_create)} labels, {len(issues)} issues (1 tracking, {len(issues) - 1} units), "
           f"{len(subs)} sub-issue links, {len(blocked)} blocked-by links; {total} content-creating "
           f"writes (GitHub allows 80 per minute and 500 per hour)."]
  if total > WRITE_WARN:
    lines.append(f"WARNING: {total} writes exceed {WRITE_WARN}: run `apply --yes --max-writes N` in several calls.")
  lines += ["", f"Confirmed write list sha256: `{confirmed}`", "", "## Labels", ""]
  lines += [f"- `{n}`: {'create' if s == 'missing' else s}" for n, s in labels.items()]
  lines += [f"- `{n}`: extra (exists)" for n in handoff.labels["extra"]]
  lines += ["", "## Writes in order", ""]
  for item in writes:
    if item[0] == "issue":
      lines += [f"### issue {item[1]}", "", f"Title: {item[2]}", f"Labels: {', '.join(item[3])}", "",
                "```markdown", item[4].rstrip("\n"), "```", ""]
  lines += [f"- sub-issue: {w[1]} under the tracking issue" for w in subs]
  lines += [f"- blocked-by: {w[1]} blocked by {w[2]}" for w in blocked]
  write_text(handoff.artifact_dir / "handoff_dryrun.md", "\n".join(lines) + "\n")
  state["labels"] = labels
  state["confirmed_sha256"] = confirmed
  # The confirmed snapshot is the contract the user approved. Keep the write
  # list itself, not only its hash: verify and status must compare GitHub with
  # what was confirmed, never with a plan re-parsed since.
  state["confirmed"] = {"sha256": confirmed, "repo": handoff.config["repo"],
                        "host": GH_HOSTNAME, "handoff_id": handoff.handoff_id,
                        "writes": writes, "at": now_iso()}
  state["dry_run"] = {"labels": len(to_create), "issues": len(issues), "sub_issues": len(subs),
                      "blocked_by": len(blocked), "writes": total, "at": now_iso()}
  save_state(handoff.artifact_dir, state)
  print(f"dry run written to {handoff.artifact_dir / 'handoff_dryrun.md'}: {len(issues)} issues, "
        f"{len(subs)} sub-issue links, {len(blocked)} blocked-by links, {len(to_create)} labels to create; "
        f"{total} writes; confirmed_sha256 {confirmed[:12]}")
  return 0


class Budget:
  """Counts content-creating writes and stops cleanly at --max-writes."""

  class Exhausted(Exception):
    pass

  def __init__(self, limit):
    self.limit, self.count = limit, 0

  def spend(self):
    if self.limit is not None and self.count >= self.limit:
      raise Budget.Exhausted()
    self.count += 1


def cmd_apply(args):
  plan = locate(args)
  handoff = Handoff(plan)
  state = handoff.state
  repo = handoff.config["repo"]
  if not args.yes:
    raise HandoffError("apply writes to GitHub: run it with --yes only after the user confirmed the dry run")
  if not state.get("confirmed_sha256"):
    raise HandoffError("no confirmed_sha256 in the state: run dry-run and ask the user first")
  if state.get("repo") != repo:
    raise HandoffError(f"config repo {repo} differs from the state's {state.get('repo')}: run dry-run again")
  writes = handoff.writes()
  if sha256_text(canonical(writes)) != state["confirmed_sha256"]:
    raise HandoffError("the write list changed since the dry run (plan, config, template or repo): run dry-run again")
  # A banned_terms or mention rule added after the dry run leaves the write list
  # unchanged, so the hash above cannot catch it. Scan the outgoing text itself.
  problems = scan_handoff(handoff)
  if problems:
    raise HandoffError("the current scan refuses the text that would be written:\n  "
                       + "\n  ".join(problems))
  state.setdefault("confirmed_at", now_iso())
  budget = Budget(args.max_writes)
  save = lambda: save_state(handoff.artifact_dir, state)
  try:
    apply_writes(handoff, writes, budget, save)
  except Budget.Exhausted:
    state["verify"] = {"sha256": state["confirmed_sha256"], "complete": False,
                       "checked": "0 of 0", "problems": [], "note": f"stopped after {budget.count} writes"}
    save()
    print(f"stopped after {budget.count} writes (--max-writes): resume with `apply --yes`")
    return 0
  except GhError as error:
    save()
    if error.rate_limited:
      raise HandoffError(f"rate limited: resume with `apply --yes` after {time.strftime('%H:%M', time.gmtime(NOW() + 3600))} UTC") from error
    if error.http_status == 410:
      raise HandoffError(f"issues are disabled on {repo} (410)") from error
    raise HandoffError(str(error)) from error
  save()
  return run_verify(handoff, writes)


def apply_writes(handoff: Handoff, writes, budget: Budget, save):
  state, repo = handoff.state, handoff.config["repo"]
  labels = state.setdefault("labels", {})
  for item in writes:
    if item[0] != "label" or labels.get(item[1]) in ("done", "exists"):
      continue
    budget.spend()
    try:
      gh_retry(["label", "create", item[1], "-R", repo, "--color", LABEL_COLOR,
                "--description", f"EGM handoff label ({item[1]})"])
      labels[item[1]] = "done"
      SLEEP(1)
    except GhError as error:
      if error.http_status == 422 or "already exists" in (error.stderr + error.stdout):
        existing = {l["name"] for l in gh_pages(f"repos/{repo}/labels")}
        if item[1] not in existing:
          raise
        labels[item[1]] = "done"
      else:
        raise
    save()
  units = state.setdefault("units", {})
  tracking = state.setdefault("tracking", {})
  listing = gh_pages(f"repos/{repo}/issues?labels="
                     f"{urllib.parse.quote(handoff.handoff_label(), safe='')}"
                     f"&state=all&per_page=100")
  for issue in listing:
    if "pull_request" in issue:
      continue
    match = MARKER_RE.match((issue.get("body") or "").lstrip())
    if not match or match.group(1) != handoff.handoff_id:
      continue
    target = tracking if match.group(2) == "tracking" else units.setdefault(match.group(2), {})
    if not target.get("number"):
      target.update({"number": issue["number"], "id": issue["id"], "done": True})
  save()
  for record in [tracking, *units.values()]:
    if record.get("number") and not record.get("id"):
      record["id"] = gh_json(["api", f"repos/{repo}/issues/{record['number']}"])["id"]
      record["done"] = True
      save()
  for item in writes:
    if item[0] != "issue":
      continue
    kind, title, label_set, body = item[1], item[2], item[3], item[4]
    target = tracking if kind == "tracking" else units.setdefault(kind, {})
    if kind != "tracking":
      target["wave"] = handoff.graph.wave[kind]
    if target.get("done"):
      continue
    if kind != "tracking" and not tracking.get("number"):
      raise HandoffError("tracking issue missing: it is created first")
    numbers = {u: d["number"] for u, d in units.items() if d.get("number")}
    text = fill_numbers(body, numbers, tracking.get("number"))
    budget.spend()
    number = create_issue(repo, title, text, label_set, handoff.artifact_dir)
    # Record the number before the id read: a failure between them must leave a
    # resumable state, not an issue that later stages treat as complete.
    target["number"] = number
    save()
    target["id"] = gh_json(["api", f"repos/{repo}/issues/{number}"])["id"]
    target["done"] = True
    save()
    SLEEP(1)
  links = state.setdefault("links", {})
  existing_subs = None
  for item in writes:
    if item[0] != "sub_issue" or links.get(f"sub:{item[1]}") == "done":
      continue
    if existing_subs is None:
      existing_subs = {s["id"] for s in gh_pages(f"repos/{repo}/issues/{tracking['number']}/sub_issues")}
    child = units[item[1]]
    if child["id"] in existing_subs:
      links[f"sub:{item[1]}"] = "done"
      save()
      continue
    budget.spend()
    post_link(f"repos/{repo}/issues/{tracking['number']}/sub_issues", {"sub_issue_id": child["id"]},
              lambda: child["id"] in {s["id"] for s in gh_pages(f"repos/{repo}/issues/{tracking['number']}/sub_issues")},
              links, f"sub:{item[1]}")
    save()
    SLEEP(1)
  blocked_cache = {}
  for item in writes:
    if item[0] != "blocked_by":
      continue
    key = f"blocked:{item[1]}<-{item[2]}"
    if links.get(key) == "done":
      continue
    blocked, blocker = units[item[1]], units[item[2]]
    endpoint = f"repos/{repo}/issues/{blocked['number']}/dependencies/blocked_by"
    if item[1] not in blocked_cache:
      blocked_cache[item[1]] = {b["id"] for b in gh_pages(endpoint)}
    if blocker["id"] in blocked_cache[item[1]]:
      links[key] = "done"
      save()
      continue
    budget.spend()
    post_link(endpoint, {"issue_id": blocker["id"]},
              lambda: blocker["id"] in {b["id"] for b in gh_pages(endpoint)}, links, key)
    blocked_cache.pop(item[1], None)
    save()
    SLEEP(1)


def create_issue(repo, title, body, labels, artifact_dir):
  with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", prefix=".egm_body_",
                                   dir=str(artifact_dir), delete=False) as handle:
    handle.write(body)
    path = handle.name
  try:
    args = ["issue", "create", "-R", repo, "--title", title, "--body-file", path]
    for label in labels:
      args += ["--label", label]
    for attempt in range(4):
      try:
        url = gh(args).strip().splitlines()[-1]
        break
      except GhError as error:
        if error.rate_limited and attempt < 3:
          SLEEP(error.retry_after or 60)
          continue
        raise
  finally:
    os.unlink(path)
  number = url.rstrip("/").split("/")[-1]
  if not number.isdigit():
    raise HandoffError(f"gh issue create printed no issue URL: {url}")
  return int(number)


def post_link(endpoint, fields, present, links, key):
  try:
    gh_post(endpoint, fields)
    links[key] = "done"
  except GhError as error:
    if error.http_status in (422, 409):
      if present():
        links[key] = "done"
      else:
        links[key] = f"error: HTTP {error.http_status}"
      return
    raise


def run_verify(handoff: Handoff, writes=None):
  state, repo = handoff.state, require_repo(handoff)
  confirmed = state.get("confirmed") or {}
  stored = confirmed.get("writes")
  if writes is None and stored:
    # Verify what the user confirmed, not what the plan says now: an edited
    # local plan must not be able to make a stale receipt look clean.
    writes = [tuple(w) for w in stored]
  writes = writes or handoff.writes()
  if stored and sha256_text(canonical([list(w) for w in writes])) != confirmed.get("sha256"):
    raise HandoffError("the write list no longer matches the confirmed snapshot: "
                       "run dry-run again and re-confirm before verifying")
  checkable = [w for w in writes if w[0] not in ("repo", "gate")]
  problems, checked = [], 0
  units, tracking = state.get("units", {}), state.get("tracking", {})
  existing_labels = None
  subs = None
  for item in checkable:
    kind = item[0]
    try:
      if kind == "label":
        if existing_labels is None:
          existing_labels = {l["name"] for l in gh_pages(f"repos/{repo}/labels")}
        if item[1] not in existing_labels:
          problems.append(f"MISMATCH label `{item[1]}` is missing on {repo}")
        checked += 1
      elif kind == "issue":
        target = tracking if item[1] == "tracking" else units.get(item[1], {})
        if not target.get("number"):
          continue
        live = gh_json(["issue", "view", str(target["number"]), "-R", repo, "--json", "body,labels"])
        numbers = {u: d["number"] for u, d in units.items() if d.get("number")}
        expected = fill_numbers(item[4], numbers, tracking.get("number"))
        if normalise(live.get("body") or "") != normalise(expected):
          problems.append(f"MISMATCH body of #{target['number']} ({item[1]}) differs from the rendered body")
        live_labels = {l["name"] for l in live.get("labels", [])}
        expected_labels = set(item[3])
        deferred = target.get("deferred")
        if deferred:
          # `defer` is an authorised, recorded label change: the confirmed write
          # list still names the wave the graph produced.
          expected_labels.discard(deferred["from"])
          expected_labels.add(deferred["to"])
        if not expected_labels <= live_labels:
          problems.append(f"MISMATCH labels of #{target['number']} ({item[1]}): missing {sorted(expected_labels - live_labels)}")
        checked += 1
      elif kind == "sub_issue":
        if not tracking.get("number") or not units.get(item[1], {}).get("id"):
          continue
        if subs is None:
          subs = {s["id"] for s in gh_pages(f"repos/{repo}/issues/{tracking['number']}/sub_issues")}
        if units[item[1]]["id"] not in subs:
          problems.append(f"MISMATCH sub-issue link missing for {item[1]}")
        checked += 1
      elif kind == "blocked_by":
        blocked, blocker = units.get(item[1], {}), units.get(item[2], {})
        if not blocked.get("number") or not blocker.get("id"):
          continue
        ids = {b["id"] for b in gh_pages(f"repos/{repo}/issues/{blocked['number']}/dependencies/blocked_by")}
        if blocker["id"] not in ids:
          problems.append(f"MISMATCH blocked-by link missing: {item[1]} blocked by {item[2]}")
        checked += 1
    except GhError as error:
      problems.append(f"MISMATCH read failed for {item[:2]}: {error}")
  complete = checked == len(checkable) and not any(p.startswith("MISMATCH read failed") for p in problems)
  state["verify"] = {"sha256": confirmed.get("sha256") or state.get("confirmed_sha256"),
                     "complete": complete,
                     "checked": f"{checked} of {len(checkable)}", "problems": problems,
                     "verified_at": now_iso()}
  save_state(handoff.artifact_dir, state)
  print(f"verify: {'complete' if complete else 'incomplete'}, {checked} of {len(checkable)} checked, "
        f"{len(problems)} problem(s)")
  for problem in problems:
    print(problem)
  return 0 if complete and not problems else 1


def cmd_verify(args):
  plan = locate(args)
  handoff = Handoff(plan)
  return run_verify(handoff)


# ---------------------------------------------------------------- status


def require_repo(handoff) -> str:
  """Refuse any operation that uses a stored issue or PR number when the
  configured repository is no longer the one those numbers were created on."""
  repo = handoff.config["repo"]
  frozen = (handoff.state.get("confirmed") or {}).get("repo") or handoff.state.get("repo")
  if frozen and frozen != repo:
    raise HandoffError(
        f"this handoff was created on {frozen} but the configuration now names "
        f"{repo}: issue and PR numbers are not portable between repositories. "
        f"Restore `repo` in .egm/handoff.json or start a handoff in a new "
        f"artifact directory.")
  host = (handoff.state.get("confirmed") or {}).get("host")
  if host and host != GH_HOSTNAME:
    raise HandoffError(f"this handoff was created on {host}, not {GH_HOSTNAME}")
  return repo


def require_confirmed_plan(handoff) -> None:
  """Refuse to read readiness off a plan edited since the confirmation.

  `status` derives landed and ready from the graph it parses now, but the
  receipt describes the issues on GitHub. Deleting a blocker locally would
  otherwise make a unit ready while its issue is still blocked by it."""
  confirmed = handoff.state.get("confirmed") or {}
  if not confirmed.get("sha256"):
    return
  current = sha256_text(canonical(handoff.writes()))
  if current != confirmed["sha256"]:
    raise HandoffError(
        f"{handoff.plan_path.name} no longer matches the confirmed snapshot "
        f"({current[:12]} vs {confirmed['sha256'][:12]}): the issues on "
        f"{confirmed.get('repo')} were created from the confirmed plan. Restore "
        f"it, or run the gate and dry-run again and re-confirm.")


def receipt_ok(state) -> bool:
  receipt = state.get("verify") or {}
  return bool(receipt.get("complete")) and receipt.get("sha256") == state.get("confirmed_sha256") \
      and not receipt.get("problems")


def require_receipt(state):
  if not receipt_ok(state):
    raise HandoffError("the handoff is not fully created and verified: run `apply --yes`, then `verify`")


def read_pr(repo, number):
  data = gh_json(["pr", "view", str(number), "-R", repo, "--json",
                  "number,state,headRefName,headRefOid,baseRefName,baseRefOid,mergedAt,isDraft"])
  return pr_record(data)


def pr_record(data):
  return {"number": data["number"], "state": data.get("state"), "head_ref": data.get("headRefName"),
          "head": data.get("headRefOid"), "base_ref": data.get("baseRefName"),
          "base_sha": data.get("baseRefOid"), "merged_at": data.get("mergedAt"),
          "draft": bool(data.get("isDraft"))}


GRAPHQL_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!, $endCursor: String) { "
    "repository(owner: $owner, name: $name) { issue(number: $number) { "
    "closedByPullRequestsReferences(first: 100, includeClosedPrs: true, after: $endCursor) { "
    "nodes { number state headRefName headRefOid baseRefName baseRefOid mergedAt isDraft "
    "repository { nameWithOwner } } pageInfo { hasNextPage endCursor } } } } }")


def discover_pr(handoff: Handoff, uid, number):
  repo = handoff.config["repo"]
  owner, name = repo.split("/")
  pages = gh_json(["api", "graphql", "--paginate", "--slurp", "-F", f"owner={owner}",
                   "-F", f"name={name}", "-F", f"number={number}", "-f", f"query={GRAPHQL_QUERY}"]) or []
  nodes = []
  for page in pages:
    issue = ((page.get("data") or {}).get("repository") or {}).get("issue") or {}
    nodes += (issue.get("closedByPullRequestsReferences") or {}).get("nodes") or []
  matches = [pr_record(n) for n in nodes if (n.get("repository") or {}).get("nameWithOwner") == repo]
  if matches:
    return matches, []
  prs = gh_json(["pr", "list", "-R", repo, "--state", "all", "--limit", "1000", "--json",
                 "number,state,headRefName,headRefOid,baseRefName,baseRefOid,closingIssuesReferences,isDraft,mergedAt"]) or []
  branch = handoff.branch(uid)
  candidates = []
  for pr in prs:
    refs = pr.get("closingIssuesReferences") or []
    for ref in refs:
      repository = ref.get("repository") or {}
      full = f"{(repository.get('owner') or {}).get('login')}/{repository.get('name')}"
      if full == repo and ref.get("number") == number:
        matches.append(pr_record(pr))
        break
    else:
      head = pr.get("headRefName") or ""
      if not refs and (head == branch or head.startswith(branch + "/")):
        candidates.append(pr_record(pr))
  return matches, candidates


def read_ci(repo, sha):
  pages = gh_json(["api", f"repos/{repo}/commits/{sha}/check-runs?per_page=100", "--paginate", "--slurp"]) or []
  runs = []
  for page in pages:
    runs += page.get("check_runs") or [] if isinstance(page, dict) else []
  combined = gh_json(["api", f"repos/{repo}/commits/{sha}/status"]) or {}
  statuses = combined.get("statuses") or []
  return {"check_runs": [{"name": r.get("name"), "status": r.get("status"), "conclusion": r.get("conclusion")}
                         for r in runs],
          "combined_state": combined.get("state"), "statuses": len(statuses)}


def ci_verdict(ci):
  runs = ci["check_runs"]
  if not runs and not ci["statuses"]:
    return "waiting-for-ci"
  if any(r["status"] != "completed" for r in runs) or (ci["statuses"] and ci["combined_state"] == "pending"):
    return "waiting-for-ci"
  red = [r["name"] for r in runs if r["conclusion"] not in GREEN_CONCLUSIONS]
  if ci["statuses"] and ci["combined_state"] != "success":
    red.append(f"status:{ci['combined_state']}")
  return "ci green" if not red else "ci red (" + ", ".join(str(n) for n in red) + ")"


def unit_view(handoff: Handoff, uid):
  repo, state = handoff.config["repo"], handoff.state
  record = state["units"].get(uid, {})
  number = record.get("number")
  issue = gh_json(["api", f"repos/{repo}/issues/{number}"]) or {}
  view = {"unit": uid, "number": number, "issue_state": issue.get("state"),
          "state_reason": issue.get("state_reason"), "launched": record.get("launched"),
          "pr": None, "head": None, "ci": None, "status": "waiting-for-pr", "landed": False,
          "candidates": []}
  if record.get("pr"):
    pr = read_pr(repo, record["pr"]["number"])
  else:
    matches, candidates = discover_pr(handoff, uid, number)
    pr = None
    if len(matches) == 1:
      pr = matches[0]
    elif len(matches) > 1:
      view["status"] = "ambiguous: PRs " + ", ".join(f"#{m['number']}" for m in matches) + " (choose with --watch)"
    view["candidates"] = [c["number"] for c in candidates]
  if pr:
    if record.get("pr", {}).get("head") != pr["head"]:
      pr["head_seen_at"] = NOW()
    else:
      pr["head_seen_at"] = record["pr"].get("head_seen_at", NOW())
    record["pr"] = pr
    view["pr"], view["head"] = pr["number"], pr["head"]
    if pr["merged_at"]:
      view["status"] = "merged"
    else:
      ci = read_ci(repo, pr["head"])
      view["ci"] = ci
      verdict = ci_verdict(ci)
      if verdict == "waiting-for-ci" and not ci["check_runs"] and not ci["statuses"] \
          and NOW() - pr["head_seen_at"] >= NO_CI_SECONDS:
        verdict = "no-ci"
      view["status"] = verdict
  closed_done = issue.get("state") == "closed" and issue.get("state_reason") == "completed"
  if record.get("landed_confirmed") or (closed_done and pr and pr.get("merged_at")):
    view["landed"], view["status"] = True, "landed"
  elif closed_done and not pr:
    view["status"] = "closed (no watched PR)"
  elif view["candidates"] and view["status"] == "waiting-for-pr":
    view["status"] = "candidate: PRs " + ", ".join(f"#{c}" for c in view["candidates"]) + " (confirm with --watch)"
  record["status"] = view["status"]
  state["units"][uid] = record
  return view


def status_pass(handoff: Handoff):
  state = handoff.state
  state.setdefault("units", {})
  views = {uid: unit_view(handoff, uid) for uid in handoff.graph.order}
  landed = {u for u, v in views.items() if v["landed"]}
  decisions = state.get("decisions", {})
  open_blocking = {}
  for unit in handoff.plan.units.values():
    for d in unit.decisions:
      if d["blocking"] and f"{unit.id}/{d['id']}" not in decisions:
        open_blocking.setdefault(unit.id, []).append(d)
  ready = [u for u in handoff.graph.order if u not in landed and not views[u]["launched"]
           and handoff.graph.preds[u] <= landed and u not in open_blocking]
  in_flight = [u for u in handoff.graph.order if views[u]["launched"] and u not in landed]
  unlaunched_prs = [u for u in handoff.graph.order if not views[u]["launched"] and views[u]["pr"]
                    and u not in landed]
  summary = {"landed": sorted(landed), "ready": ready, "in_flight": in_flight,
             "unlaunched_with_pr": unlaunched_prs, "open_blocking": {u: [d["id"] for d in ds] for u, ds in open_blocking.items()},
             "units": {u: {"pr": v["pr"], "head": v["head"], "status": v["status"], "landed": v["landed"],
                           "candidates": v["candidates"]} for u, v in views.items()},
             "at": now_iso()}
  # A watcher sleeping between polls must not write back a stale copy of the
  # whole file: the main conversation records decisions, launches and deferrals
  # while it sleeps. Re-read, merge only the field this pass owns, save.
  fresh = load_state(handoff.artifact_dir)
  if fresh:
    fresh["status"] = summary
    for uid, record in (state.get("units") or {}).items():
      if record.get("pr"):
        fresh.setdefault("units", {}).setdefault(uid, {})["pr"] = record["pr"]
      if record.get("landed_confirmed"):
        fresh.setdefault("units", {}).setdefault(uid, {})["landed_confirmed"] = record["landed_confirmed"]
    save_state(handoff.artifact_dir, fresh)
    handoff.state = state = fresh
  else:
    state["status"] = summary
    save_state(handoff.artifact_dir, state)
  return summary, open_blocking


def print_status(handoff: Handoff, summary, open_blocking):
  state = handoff.state
  print(f"handoff {handoff.handoff_id} on {handoff.config['repo']}: tracking #{state.get('tracking', {}).get('number')}; "
        f"receipt {'complete' if receipt_ok(state) else 'INCOMPLETE'}")
  print("landed: " + (", ".join(summary["landed"]) or "none"))
  print("ready: " + (", ".join(summary["ready"]) or "none"))
  for uid in handoff.graph.order:
    v = summary["units"][uid]
    record = state["units"].get(uid, {})
    launched = f" launched wave {record['launched']['wave']}" if record.get("launched") else ""
    pr = f"pr #{v['pr']} head {v['head'][:7]}" if v["pr"] else "no pr"
    print(f"{uid} #{record.get('number')}{launched}: {pr}; {v['status']}")
  for uid, ds in open_blocking.items():
    for d in ds:
      print(f"open blocking decision {uid}/{d['id']}: {d['question']} (owner: {d['owner']}; default: {d['default']})")
  if summary["unlaunched_with_pr"]:
    print("open PRs for units not launched: " + ", ".join(f"{u} #{summary['units'][u]['pr']}" for u in summary["unlaunched_with_pr"]))


def cmd_status(args):
  plan = locate(args)
  handoff = Handoff(plan)
  state = handoff.state
  require_receipt(state)
  require_repo(handoff)
  require_confirmed_plan(handoff)
  state.setdefault("units", {})
  for item in args.watch or []:
    uid, _, number = item.partition("=")
    if uid not in handoff.plan.units or not number.isdigit():
      raise HandoffError(f"--watch takes U<nn>=<pr number>, got {item}")
    pr = read_pr(handoff.config["repo"], int(number))
    pr["head_seen_at"] = NOW()
    state["units"].setdefault(uid, {})["pr"] = pr
  for uid in args.confirm_landed or []:
    state["units"].setdefault(uid, {})["landed_confirmed"] = now_iso()
  fingerprint = lambda s: {u: (v["pr"], v["head"], v["status"], v["landed"]) for u, v in s["units"].items()}
  previous = fingerprint(state["status"]) if state.get("status") else None
  summary, open_blocking = status_pass(handoff)
  if args.wait:
    deadline = NOW() + args.wait
    previous = previous if previous is not None else fingerprint(summary)
    while True:
      current = fingerprint(summary)
      changed = sorted(u for u in current if current[u] != previous.get(u))
      if changed:
        print("changed: " + ", ".join(changed))
        break
      if NOW() >= deadline:
        print("deadline: no change")
        break
      SLEEP(min(WAIT_INTERVAL, max(1, deadline - NOW())))
      summary, open_blocking = status_pass(handoff)
  print_status(handoff, summary, open_blocking)
  return 0


def cmd_launch(args):
  plan = locate(args)
  handoff = Handoff(plan)
  state = handoff.state
  require_receipt(state)
  require_repo(handoff)
  require_confirmed_plan(handoff)
  for uid in args.units:
    if uid not in handoff.plan.units:
      raise HandoffError(f"unknown unit {uid}")
    state.setdefault("units", {}).setdefault(uid, {})["launched"] = {"wave": args.wave, "at": now_iso()}
  save_state(handoff.artifact_dir, state)
  print(f"launched in wave {args.wave}: {', '.join(args.units)}")
  return 0


def cmd_defer(args):
  plan = locate(args)
  handoff = Handoff(plan)
  state, repo = handoff.state, require_repo(handoff)
  record = state.get("units", {}).get(args.unit) or {}
  if not record.get("number"):
    raise HandoffError(f"{args.unit} has no issue number in the state")
  old, new = handoff.wave_label(record.get("wave", handoff.graph.wave[args.unit])), handoff.wave_label(args.to_wave)
  if not LABEL_RE.match(new):
    raise HandoffError(f"invalid label {new}")
  # `gh issue edit --add-label` fails on a label the repository does not have,
  # and apply only ever created the waves the graph produced.
  existing = {l["name"] for l in gh_pages(f"repos/{repo}/labels")}
  if new not in existing:
    raise HandoffError(
        f"{repo} has no label `{new}` (apply created only waves "
        f"{', '.join(handoff.wave_label(w) for w in sorted(handoff.graph.waves))}). "
        f"Create it on {repo} first, then run defer again.")
  if not args.yes:
    print(f"would run: gh issue edit {record['number']} -R {repo} --remove-label {old} --add-label {new}")
    return 0
  gh(["issue", "edit", str(record["number"]), "-R", repo, "--remove-label", old, "--add-label", new])
  live = gh_json(["issue", "view", str(record["number"]), "-R", repo, "--json", "labels"])
  names = {l["name"] for l in live.get("labels", [])}
  if new not in names or old in names:
    raise HandoffError(f"MISMATCH after the label edit on #{record['number']}: labels {sorted(names)}")
  record["wave"] = args.to_wave
  record["deferred"] = {"from": old, "to": new, "at": now_iso()}
  record.pop("launched", None)
  save_state(handoff.artifact_dir, state)
  print(f"{args.unit} deferred to wave {args.to_wave} (label {old} -> {new})")
  return 0


def cmd_decide(args):
  plan = locate(args)
  handoff = Handoff(plan)
  unit = handoff.plan.units.get(args.unit)
  if not unit:
    raise HandoffError(f"unknown unit {args.unit}")
  decision = next((d for d in unit.decisions if d["id"] == args.decision), None)
  if not decision:
    raise HandoffError(f"{args.unit} has no decision {args.decision}")
  key = f"{args.unit}/{args.decision}"
  handoff.state.setdefault("decisions", {})[key] = {"answer": args.answer, "decided_at": now_iso()}
  save_state(handoff.artifact_dir, handoff.state)
  write_text(handoff.unit_file(args.unit), handoff.unit_file_text(args.unit))
  comment = handoff.artifact_dir / f"decision_comment_{args.unit}_{args.decision}.md"
  write_text(comment, f"**Decision {args.decision}** ({decision['question']}): {args.answer}\n")
  print(f"recorded {key}; re-rendered {handoff.unit_file(args.unit).name}; comment in {comment.name}")
  return 0


# ---------------------------------------------------------------- prepare


def foreman_state_path(artifact_dir: Path, uid):
  return artifact_dir / f"foreman_{uid}_state.json"


def load_foreman(artifact_dir, uid):
  path = foreman_state_path(artifact_dir, uid)
  return json.loads(read_text(path)) if path.is_file() else {"unit": uid, "rounds": {}}


def save_foreman(artifact_dir, uid, data):
  write_text(foreman_state_path(artifact_dir, uid), json.dumps(data, indent=2, sort_keys=True) + "\n")


def worktree_path(handoff_id, uid, pr):
  base = Path(os.environ.get("TMPDIR") or "/tmp").expanduser()
  return base / "egm-wave" / handoff_id / uid / f"pr{pr}"


def registered_worktrees(root: Path):
  paths = []
  for line in run_git(["worktree", "list", "--porcelain"], root).splitlines():
    if line.startswith("worktree "):
      paths.append(Path(line[len("worktree "):]).resolve())
  return paths


def remove_worktree(root: Path, tree: Path) -> None:
  """Remove a review worktree only when it is clean.

  `--force` deletes tracked modifications and untracked files. The foreman
  removes a worktree after every round, so a person editing it during a review
  would lose that work without being asked."""
  if not tree.exists():
    run_git(["worktree", "prune"], root, check=False)
    return
  dirty = run_git(["status", "--porcelain"], tree, check=False).strip()
  if dirty:
    raise HandoffError(
        f"the review worktree {tree} has uncommitted changes:\n  "
        + "\n  ".join(dirty.splitlines()[:10])
        + f"\nNothing was removed. Save or discard them, then remove it with "
          f"`git -C {root} worktree remove {tree}`.")
  run_git(["worktree", "remove", str(tree)], root)
  run_git(["worktree", "prune"], root, check=False)


def cmd_record_launch(args):
  """Record `launched` and the run folder for a round.

  The elephant runs this the moment the runner prints its folder. Without it
  nothing persists between `prepared` and `collected` on the no-teams path:
  the prepare subagent has already returned and the collect subagent is not
  spawned until the run completes, so a session that ends in between restarts
  the round and abandons a finished Astra run."""
  plan = locate(args)
  handoff = Handoff(plan)
  data = load_foreman(handoff.artifact_dir, args.unit)
  rounds = data.setdefault("rounds", {})
  record = rounds.setdefault(str(args.round), {})
  if args.not_run:
    record.update({"phase": "launched", "run_folder": None,
                   "status": f"not run ({args.not_run})", "at": now_iso()})
  else:
    folder = Path(args.run_folder).expanduser()
    record.update({"phase": "launched", "run_folder": str(folder),
                   "status": "running", "at": now_iso()})
  save_foreman(handoff.artifact_dir, args.unit, data)
  print(f"{args.unit} round {args.round}: {record['status']} "
        f"({record['run_folder'] or 'no run folder'})")
  return 0


def cmd_prepare(args):
  plan = locate(args)
  handoff = Handoff(plan)
  state = handoff.state
  root = Path(state.get("repo_root") or handoff.repo_root)
  remote, repo = state.get("remote") or handoff.config["remote"], handoff.config["repo"]
  record = state.get("units", {}).get(args.unit) or {}
  pr = record.get("pr")
  if not pr:
    raise HandoffError(f"{args.unit} has no watched PR: run `status` first")
  number = pr["number"]
  foreman = load_foreman(handoff.artifact_dir, args.unit)
  tree = worktree_path(handoff.handoff_id, args.unit, number)
  if args.clean or args.remove:
    if tree.resolve() in registered_worktrees(root):
      remove_worktree(root, tree)
    if args.clean:
      for ref in (f"refs/egm/pr/{number}", f"refs/egm/base/{number}"):
        subprocess.run(["git", "-C", str(root), "update-ref", "-d", ref], capture_output=True)
      run_git(["worktree", "prune"], root)
    foreman["phase"] = "cleaned"
    save_foreman(handoff.artifact_dir, args.unit, foreman)
    print(f"{'cleaned' if args.clean else 'removed'} {tree}")
    return 0
  url = run_git(["remote", "get-url", remote], root)
  if parse_remote_url(url) != repo:
    raise HandoffError(f"remote {remote} no longer names {repo} ({url.strip()}): refusing to fetch")
  run_git(["fetch", "--no-write-fetch-head", remote,
           f"+refs/pull/{number}/head:refs/egm/pr/{number}",
           f"+refs/heads/{pr['base_ref']}:refs/egm/base/{number}"], root)
  foreman.update({"pr": number, "phase": "fetched", "round": args.round})
  save_foreman(handoff.artifact_dir, args.unit, foreman)
  fetched = run_git(["rev-parse", f"refs/egm/pr/{number}"], root).strip()
  if fetched != pr["head"]:
    print(f"head-moved: refs/egm/pr/{number} is {fetched[:7]}, status recorded {pr['head'][:7]}; run status again")
    return 3
  if tree.exists():
    if tree.resolve() not in registered_worktrees(root):
      raise HandoffError(f"{tree} exists but is not a registered worktree: remove it by hand")
    if run_git(["status", "--porcelain"], tree).strip():
      raise HandoffError(f"worktree {tree} has changes: remove it by hand")
    running = [r for r in foreman.get("rounds", {}).values()
               if r.get("phase") == "launched" and r.get("run_status") == "running"]
    if running:
      raise HandoffError(f"worktree {tree} belongs to a round still `launched`: mark its run folder "
                         "`not run (killed)` (foreman state) before preparing again")
    remove_worktree(root, tree)
  tree.parent.mkdir(parents=True, exist_ok=True)
  run_git(["worktree", "add", "--detach", str(tree), pr["head"]], root)
  merge_base = run_git(["merge-base", pr["base_sha"], "HEAD"], tree).strip()
  diff = subprocess.run(["git", "-C", str(tree), "diff", "--no-ext-diff", "--no-textconv", "--binary",
                         merge_base, "--"], capture_output=True, check=True).stdout
  diff_path = handoff.artifact_dir / f"pr_{number}_r{args.round}.diff"
  diff_path.write_bytes(diff)
  ci = read_ci(repo, pr["head"])
  ci["verdict"] = ci_verdict(ci)
  ci_path = handoff.artifact_dir / f"ci_{number}_r{args.round}.json"
  write_text(ci_path, json.dumps(ci, indent=2) + "\n")
  round_record = {"phase": "prepared", "worktree": str(tree), "head": pr["head"],
                  "base_ref": pr["base_ref"], "base_sha": pr["base_sha"], "merge_base": merge_base,
                  "diff": str(diff_path), "ci": str(ci_path), "ci_verdict": ci["verdict"]}
  foreman.setdefault("rounds", {})[str(args.round)] = round_record
  foreman.update({"phase": "prepared", "worktree": str(tree), "head": pr["head"], "merge_base": merge_base})
  save_foreman(handoff.artifact_dir, args.unit, foreman)
  if args.runner:
    if not MODEL_RE.match(args.model or "") or args.effort not in EFFORTS:
      raise HandoffError("--runner needs --model matching the allowlist and --effort in low|medium|high|xhigh")
    brief = handoff.artifact_dir / f"astra_brief_w{args.wave}_u{args.unit}_r{args.round}.md"
    unit_file = handoff.unit_file(args.unit)
    paths = [str(args.runner), str(tree), str(unit_file), str(brief)]
    if any("'" in p for p in paths):
      raise HandoffError("a path holds a single quote: record `not run (path quoting)`")
    line = (f"python3 '{args.runner}' inspect --host claude --repo '{tree}' --plan '{unit_file}' "
            f"--base '{merge_base}' --feedback '{brief}' --model {args.model} --effort {args.effort} "
            f"--timeout 3600 --artifacts \"${{TMPDIR:-/tmp}}/egm-astra\"")
    launch = handoff.artifact_dir / f"foreman_{args.unit}_r{args.round}_launch.md"
    write_text(launch, f"Bash timeout: 3900000 ms (run_in_background: true, from the main conversation)\n\n    {line}\n")
    print(f"launch line in {launch}")
  print(f"prepared: worktree {tree} at {pr['head'][:7]}, merge base {merge_base[:7]}, "
        f"diff {diff_path.name}, {ci['verdict']} ({ci_path.name})")
  return 0


# ---------------------------------------------------------------- main


def build_parser():
  parser = argparse.ArgumentParser(prog="egm_handoff.py", description=__doc__.splitlines()[0])
  sub = parser.add_subparsers(dest="command", required=True)

  def add(name, help_text, needs_plan=True):
    p = sub.add_parser(name, help=help_text)
    if needs_plan:
      group = p.add_mutually_exclusive_group(required=True)
      group.add_argument("--plan", help="handoff_plan.md")
      group.add_argument("--state", help="handoff_state.json (its folder holds the plan)")
    return p

  p = add("approve", "check the design and record the user's approval", needs_plan=False)
  p.add_argument("--design", required=True)
  p.add_argument("--artifacts", required=True, help="the EGM artifact directory")
  p.add_argument("--evidence")
  p.add_argument("--yes", action="store_true", help="the user answered Approve")
  p.set_defaults(func=cmd_approve)
  add("graph", "parse the plan; write units, bodies and the generated sections").set_defaults(func=cmd_graph)
  p = add("scan", "banned terms, bare mentions, merge markers, size, DoD presence")
  p.add_argument("--comment", help="scan this comment file instead of the bodies")
  p.set_defaults(func=cmd_scan)
  p = add("gate", "record the reviewed pair, pass or accept the gate, record readiness")
  p.add_argument("--reviewed", action="store_true")
  p.add_argument("--round", type=int, default=0)
  p.add_argument("--pass", dest="pass_gate", action="store_true")
  p.add_argument("--accept", action="store_true")
  p.add_argument("--readiness")
  p.add_argument("--what-ran", action="append")
  p.set_defaults(func=cmd_gate)
  add("dry-run", "preflight reads and handoff_dryrun.md; records confirmed_sha256").set_defaults(func=cmd_dry_run)
  p = add("apply", "create labels, issues and links (needs --yes)")
  p.add_argument("--yes", action="store_true")
  p.add_argument("--max-writes", type=int)
  p.set_defaults(func=cmd_apply)
  add("verify", "read every write back and record the receipt").set_defaults(func=cmd_verify)
  p = add("status", "landed and ready sets, PRs, CI; refuses without a complete receipt")
  p.add_argument("--wait", type=int, help="seconds; exit when a unit changes or the deadline passes")
  p.add_argument("--watch", action="append", help="U03=412 records that PR for the unit")
  p.add_argument("--confirm-landed", action="append", help="unit the user confirmed landed")
  p.set_defaults(func=cmd_status)
  p = add("launch", "record the units launched in a wave")
  p.add_argument("--wave", type=int, required=True)
  p.add_argument("--units", nargs="+", required=True)
  p.set_defaults(func=cmd_launch)
  p = add("defer", "move a unit to a later wave (one label edit with --yes)")
  p.add_argument("--unit", required=True)
  p.add_argument("--to-wave", type=int, required=True)
  p.add_argument("--yes", action="store_true")
  p.set_defaults(func=cmd_defer)
  p = add("decide", "record the user's answer to a decide-before-build item")
  p.add_argument("--unit", required=True)
  p.add_argument("--decision", required=True)
  p.add_argument("--answer", required=True)
  p.set_defaults(func=cmd_decide)
  p = add("record-launch", "record `launched` and the run folder for a round")
  p.add_argument("--unit", required=True)
  p.add_argument("--round", type=int, default=1)
  p.add_argument("--run-folder", dest="run_folder")
  p.add_argument("--not-run", dest="not_run", help="record the lane as not run, with this reason")
  p.set_defaults(func=cmd_record_launch)
  p = add("prepare", "fetch the PR into refs/egm, add a worktree, write the diff and CI file")
  p.add_argument("--unit", required=True)
  p.add_argument("--round", type=int, default=1)
  p.add_argument("--wave", type=int, default=1)
  p.add_argument("--runner", help="write the inspect launch line for this runner path")
  p.add_argument("--model")
  p.add_argument("--effort")
  p.add_argument("--remove", action="store_true", help="remove the round's worktree")
  p.add_argument("--clean", action="store_true", help="remove the worktree, the refs and prune")
  p.set_defaults(func=cmd_prepare)
  return parser


def main(argv=None):
  args = build_parser().parse_args(argv)
  try:
    return args.func(args)
  except HandoffError as error:
    print(f"egm_handoff: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
  sys.exit(main())

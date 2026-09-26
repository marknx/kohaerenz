"""The checks behind `kz check`. Each returns a list of findings with stable keys."""
from __future__ import annotations

import ast
import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import inventory
from .core import Diff, Finding, KzError, Repo, as_list, match

ANCHOR_RE = re.compile(r"\brule:\s*(R-[\w.-]*\w)")
BACKTICK_RE = re.compile(r"`([^`\s]+)`")
MDLINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
INCLUDE_RE = re.compile(r"(?:^|\s)@([\w./-]+)", re.M)
EXTS = "md|markdown|ya?ml|json|toml|py|pyi|tsx?|jsx?|mjs|cjs|sh|txt|cfg|ini|sql|html|css|lock|example"
FILEISH_RE = re.compile(rf"(?:.*/)?[\w.-]*\.(?:{EXTS})|.+/")
ENDPOINT_ADD_RE = re.compile(r"@\w+\.(get|post|put|patch|delete)\(")
TABLE_ADD_RE = re.compile(r"__tablename__|\btable\s*=\s*True\b")


@dataclass
class Ctx:
    repo: Repo
    diff: Diff | None
    pr_body: str | None
    inv: dict | None
    today: dt.date


def feature_refs(f: dict) -> set[str]:
    refs = set()
    for ui in as_list(f.get("ui")):
        if isinstance(ui, dict):
            refs |= {f"route:{r}" for r in as_list(ui.get("route"))}
            refs |= {f"data_feature:{d}" for d in as_list(ui.get("data_feature"))}
    refs |= {f"endpoint:{e}" for e in as_list(f.get("api"))}
    refs |= {f"table:{t}" for t in as_list(f.get("tables"))}
    return refs


def check_map(c: Ctx) -> list[Finding]:
    covered = set(str(i) for i in as_list(c.repo.landkarte().get("internal")))
    for f in c.repo.features():
        covered |= feature_refs(f)
    return [Finding("map", f"{kind}:{value}", f"{kind} '{value}' is in no feature (add it or list it as internal)")
            for kind, value in inventory.items(c.inv) if f"{kind}:{value}" not in covered]


def _step_feature(step) -> str | None:
    return step.get("feature") if isinstance(step, dict) else step


def check_orphans(c: Ctx) -> list[Finding]:
    out, used = [], set()
    known = {f.get("id") for f in c.repo.features()}
    for j in c.repo.journeys():
        jid = j.get("id", "?")
        for step in as_list(j.get("steps")):
            fid = _step_feature(step)
            used.add(fid)
            if fid not in known and not (isinstance(step, dict) and step.get("status") == "missing"):
                out.append(Finding("orphans", f"{jid}:{fid}", f"journey {jid} uses unknown feature {fid}"))
        test = j.get("test")
        if not test or not (c.repo.root / test).is_file():
            out.append(Finding("orphans", f"{jid}:test", f"journey {jid} has no existing test file ({test or 'none'})"))
    for f in c.repo.features():
        if f.get("status", "active") == "active" and f.get("id") not in used:
            out.append(Finding("orphans", f.get("id", "?"), f"active feature {f.get('id')} is in no journey"))
    return out


def check_states(c: Ctx) -> list[Finding]:
    out = []
    for f in c.repo.features():
        for name, s in (f.get("states") or {}).items():
            if not (isinstance(s, dict) and (s.get("next") or s.get("end_reason"))):
                out.append(Finding("states", f"{f.get('id')}:{name}", f"state '{name}' of {f.get('id')} has neither next nor end_reason"))
    return out


def _py_test_names(text: str) -> set[str] | None:
    """Function names and Class::method names defined in a Python file (None if unparsable)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    names, funcs = set(), (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if isinstance(node, funcs):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names |= {f"{node.name}::{n.name}" for n in node.body if isinstance(n, funcs)}
    return names


def _guard_ok(repo: Repo, guard) -> bool:
    spec = guard.get("test") if isinstance(guard, dict) else guard
    if not spec:
        return False
    path, _, name = str(spec).partition("::")
    file = repo.root / path
    if not file.is_file():
        return False
    if not name:
        return True
    text = file.read_text(encoding="utf-8", errors="replace")
    names = _py_test_names(text) if path.endswith(".py") else None
    if names is not None:
        return name in names
    return re.search(rf"(?<![\w-]){re.escape(name.split('::')[-1])}(?![\w-])", text) is not None


def check_rules(c: Ctx) -> list[Finding]:
    out, ids = [], set()
    for r in as_list(c.repo.regeln().get("rules")):
        ids.add(r.get("id"))
        if r.get("status", "active") == "active" and not any(_guard_ok(c.repo, g) for g in as_list(r.get("enforced_by"))):
            out.append(Finding("rules", r.get("id", "?"), f"active rule {r.get('id')} has no existing guard test (make it a wish or add the test)"))
    grep = c.repo.git("grep", "-n", "-E", r"rule:[[:space:]]*R-", "--", ".", ":!*.md", f":!{c.repo.rel('regeln')}")
    for line in grep.stdout.splitlines():
        for rid in ANCHOR_RE.findall(line.split(":", 2)[-1]):
            if rid not in ids:
                out.append(Finding("rules", f"anchor:{rid}", f"anchor {rid} ({line.split(':', 2)[0]}) is not in regeln"))
    return sorted(set(out), key=lambda f: f.key)


def check_anchors(c: Ctx) -> list[Finding]:
    removed, added = {}, set()
    for path, fd in c.diff.files.items():
        for line in fd.removed:
            removed.update({rid: path for rid in ANCHOR_RE.findall(line)})
        for line in fd.added:
            added.update(ANCHOR_RE.findall(line))
    regeln_changed = c.repo.rel("regeln") in c.diff.files
    rule_ids = {r.get("id") for r in as_list(c.repo.regeln().get("rules"))}
    out = []
    for rid, path in sorted(removed.items()):
        if rid in added:
            continue
        if not regeln_changed:
            out.append(Finding("anchors", rid, f"anchor {rid} deleted in {path} but regeln not changed in this PR"))
        elif c.pr_body is not None and rid not in rule_ids and not re.search(rf"removed:?\s*{re.escape(rid)}\b", c.pr_body, re.I):
            out.append(Finding("anchors", f"{rid}:unannounced", f"rule {rid} removed; PR text needs 'removed: {rid}'"))
    return out


def _front_matter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def check_adr(c: Ctx) -> list[Finding]:
    out, adr_dir = [], c.repo.path("decisions")
    for p in sorted(adr_dir.glob("*.md")) if adr_dir.is_dir() else []:
        head = _front_matter(p.read_text(encoding="utf-8", errors="replace"))
        if not (head.get("supersedes") or head.get("retires")):
            continue
        if not head.get("affected_paths"):
            out.append(Finding("adr", f"{p.name}:affected_paths", f"{p.name} supersedes/retires but has no affected_paths"))
        if head.get("retires") and not head.get("retire_by"):
            out.append(Finding("adr", f"{p.name}:retire_by", f"{p.name} retires something but has no retire_by date"))
    return out


def _date(value) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def check_timebomb(c: Ctx) -> list[Finding]:
    out, files = [], None
    entries = [("feature", f) for f in c.repo.features() if f.get("retire_by")]
    entries += [("dead", d) for d in as_list(c.repo.regeln().get("dead")) if isinstance(d, dict) and d.get("retire_by")]
    for kind, e in entries:
        due, eid = _date(e["retire_by"]), e.get("id", "?")
        if due is None:
            out.append(Finding("timebomb", f"{eid}:date", f"{eid}: retire_by '{e['retire_by']}' is not a YYYY-MM-DD date"))
            continue
        if due >= c.today:
            continue
        if kind == "feature":
            out.append(Finding("timebomb", eid, f"feature {eid} was due for retirement on {due} and is still on the map"))
            continue
        files = files if files is not None else c.repo.tracked_files()
        alive = [f for f in files if match(f, as_list(e.get("paths")))]
        if alive:
            out.append(Finding("timebomb", eid, f"{eid} was due on {due}; code still there: {', '.join(alive[:3])}"))
    return out


def watched_paths(repo: Repo) -> list[str]:
    pats = list(as_list(repo.cfg["drift_paths"]))
    for a in as_list(repo.cfg["adapters"]):
        if a["name"] == "nextjs-app":
            pats.append(a.get("app_dir", "app"))
        elif a["name"] == "fastapi":
            pats += as_list(a.get("model_dirs")) + as_list(a.get("api_dirs"))
    for f in repo.features():
        pats += as_list(f.get("paths"))
    return pats


def check_drift(c: Ctx) -> list[Finding]:
    touched = [p for p in c.diff.files if match(p, watched_paths(c.repo))]
    if not touched or c.repo.rel("landkarte") in c.diff.files:
        return []
    if c.pr_body and re.search(r"map unchanged because\s+\S", c.pr_body, re.I):
        return []
    return [Finding("drift", "map", f"UI/API paths changed ({', '.join(touched[:3])}) but not the map; "
                                    "update it or write 'map unchanged because ...' in the PR text")]


def pr_size_reasons(c: Ctx) -> list[str]:
    reasons = []
    app = c.repo.adapter("nextjs-app")
    for path, fd in c.diff.files.items():
        if fd.status == "A" and app and inventory.route_for(path, app.get("app_dir", "app")):
            reasons.append(f"new page {path}")
        if any(ENDPOINT_ADD_RE.search(l) for l in fd.added):
            reasons.append(f"new endpoint in {path}")
        if any(TABLE_ADD_RE.search(l) for l in fd.added):
            reasons.append(f"new table in {path}")
    if len(c.diff.files) > 3:
        reasons.append(f"{len(c.diff.files)} files changed")
    return reasons


def check_pr(c: Ctx) -> list[Finding]:
    reasons = pr_size_reasons(c)
    if not reasons:
        return []
    return [Finding("pr", "section:" + re.sub(r"\W+", "-", s.lower()).strip("-"),
                    f"size M/L ({reasons[0]}) needs PR section '{s}'")
            for s in as_list(c.repo.cfg["pr_sections"])
            if not re.search(rf"^#{{1,6}}\s*{re.escape(s)}", c.pr_body, re.I | re.M)]


def check_generated(c: Ctx) -> list[Finding]:
    p = c.repo.path("inventar")
    if not p.is_file():
        return [Finding("generated", "inventar", f"{c.repo.rel('inventar')} missing - run kz inventory --write")]
    try:
        same = json.loads(p.read_text(encoding="utf-8")) == c.inv
    except json.JSONDecodeError:
        same = False
    return [] if same else [Finding("generated", "inventar", f"{c.repo.rel('inventar')} does not match the code - run kz inventory --write")]


def link_refs(text: str) -> list[str]:
    refs = [r for r in BACKTICK_RE.findall(text) + INCLUDE_RE.findall(text) if FILEISH_RE.fullmatch(r)]
    refs += MDLINK_RE.findall(text)
    out = []
    for r in refs:
        r = re.sub(r"[#?].*$", "", r)
        r = re.sub(r":\d+(-\d+)?$", "", r).rstrip(".,;:")
        if r and not re.match(r"^([a-z]+:|~|/|\$|-)", r) and not any(ch in r for ch in "<>*{}|$…"):
            out.append(r)
    return out


def check_links(c: Ctx) -> list[Finding]:
    out, names = [], None
    for doc in as_list(c.repo.cfg["entry_docs"]):
        p = c.repo.root / doc
        if not p.is_file():
            continue
        for ref in dict.fromkeys(link_refs(p.read_text(encoding="utf-8", errors="replace"))):
            if match(ref, c.repo.cfg["links_ignore"]):
                continue
            if (p.parent / ref).exists() or (c.repo.root / ref).exists():
                continue
            if "/" not in ref:  # a bare file name is fine if such a file exists anywhere
                names = names if names is not None else {f.rsplit("/", 1)[-1] for f in c.repo.tracked_files()}
                if ref in names:
                    continue
            out.append(Finding("links", f"{doc}:{ref}", f"{doc} points to '{ref}', which does not exist"))
    return out


CHECKS = {
    "map": (check_map, {"inventory"}),
    "orphans": (check_orphans, set()),
    "states": (check_states, set()),
    "rules": (check_rules, {"regeln"}),
    "anchors": (check_anchors, {"diff"}),
    "adr": (check_adr, set()),
    "timebomb": (check_timebomb, set()),
    "drift": (check_drift, {"diff"}),
    "pr": (check_pr, {"diff", "pr_body"}),
    "generated": (check_generated, {"inventory"}),
    "links": (check_links, set()),
}


def run(repo: Repo, base: str | None = None, pr_body: str | None = None, fast: bool = False,
        only: list[str] | None = None, today: dt.date | None = None):
    """Run checks -> (findings, {skipped check: reason}, notes)."""
    names = only or list(CHECKS)
    inv, notes = (None, []) if fast else inventory.build(repo)
    needs_diff = any("diff" in CHECKS[n][1] for n in names)
    diff = repo.diff(base) if needs_diff else None
    if needs_diff and diff is None and base:
        raise KzError(f"diff base '{base}' not found - run git fetch or pass an existing ref")
    if needs_diff and diff is None and repo.cfg["stufe"] >= 1:
        raise KzError(f"configured main_branch '{repo.cfg['main_branch']}' not found - "
                      "run git fetch or fix .kohaerenz.yaml")
    missing = {
        "inventory": "--fast" if fast else (None if inv is not None else "no inventory adapter configured"),
        "diff": None if diff else f"no diff base ({base or repo.cfg['main_branch']} not found)",
        "pr_body": None if pr_body is not None else "no --pr-body-file given",
        "regeln": None if repo.path("regeln").is_file() else f"no {repo.rel('regeln')}",
    }
    ctx = Ctx(repo, diff, pr_body, inv, today or dt.date.today())
    findings, skipped = [], {}
    for name in names:
        fn, needs = CHECKS[name]
        reason = next((missing[n] for n in sorted(needs) if missing[n]), None)
        if reason:
            skipped[name] = reason
        else:
            findings += fn(ctx)
    return findings, skipped, notes


def load_baseline(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise KzError(f"{path.name}: invalid JSON ({exc})") from exc
    return set(data.get("keys", [])) if isinstance(data, dict) else set(data)


def write_baseline(path: Path, keys: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "keys": sorted(keys)}, indent=2) + "\n", encoding="utf-8")


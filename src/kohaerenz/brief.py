"""`kz brief` (context before a job) and `kz scope` (reviewer list after it)."""
from __future__ import annotations

import re

from .checks import ANCHOR_RE
from .core import KzError, Repo, as_list, freshness, match
from .inventory import route_for

MAX_LINES = 60
ROUTE_TOKEN_RE = re.compile(r"(?:(?:GET|POST|PUT|PATCH|DELETE)\s+)?(?<![\w.~])(/[A-Za-z_][\w{}\[\]:.-]*(?:/[\w{}\[\]:.-]+)*)")
IDENT_TOKEN_RE = re.compile(r"`([A-Za-z_][\w.:/-]{2,})`")
WORD_RE = re.compile(r"[a-z][a-z0-9-]{4,}")
STOP = {"about", "after", "again", "before", "being", "could", "every", "first", "should", "their",
        "there", "these", "thing", "those", "under", "where", "which", "while", "would", "without"}


def overlaps(paths: list[str], globs: list[str]) -> bool:
    """A path matches a glob, or a given directory contains a plain glob path."""
    return any(match(p, globs) or match(g, [p]) for p in paths for g in globs)


def feature_touched(repo: Repo, f: dict, paths: list[str]) -> bool:
    if overlaps(paths, as_list(f.get("paths"))):
        return True
    routes = {r for ui in as_list(f.get("ui")) if isinstance(ui, dict) for r in as_list(ui.get("route"))}
    app = repo.adapter("nextjs-app")
    return bool(app and routes and any(route_for(p, app.get("app_dir", "app")) in routes for p in paths))


def touched_map(repo: Repo, paths: list[str]) -> tuple[list[dict], list[dict]]:
    feats = [f for f in repo.features() if feature_touched(repo, f, paths)]
    ids = {f.get("id") for f in feats}
    journeys = [j for j in repo.journeys()
                if any((s.get("feature") if isinstance(s, dict) else s) in ids for s in as_list(j.get("steps")))]
    return feats, journeys


def keyword_hit(keyword: str, text: str) -> bool:
    pattern = r"\s+".join(re.escape(w) for w in str(keyword).split())
    return re.search(rf"(?<!\w){pattern}(?:e?s)?(?!\w)", text, re.I) is not None


def exists_already(repo: Repo, text: str, max_tokens: int = 6, max_hits: int = 3) -> list[str]:
    tokens = list(dict.fromkeys(ROUTE_TOKEN_RE.findall(text) + IDENT_TOKEN_RE.findall(text)))[:max_tokens]
    out = []
    for tok in tokens:
        lit = re.split(r"[{\[]", tok)[0].rstrip("/")
        if len(lit) < 3:
            continue
        hits = repo.git("grep", "-n", "-I", "-F", "-e", lit, "--", ".").stdout.splitlines()
        if not hits:
            out.append(f"  {tok}: no hits")
            continue
        for h in hits[:max_hits]:
            path, line, content = (h.split(":", 2) + ["", ""])[:3]
            out.append(f"  {tok}: {path}:{line}: {content.strip()[:80]}")
        if len(hits) > max_hits:
            out.append(f"  {tok}: (+{len(hits) - max_hits} more hits)")
    return out


def matching_adrs(repo: Repo, text: str, limit: int = 5) -> list[str]:
    adr_dir = repo.path("decisions")
    words = set(WORD_RE.findall(text.lower())) - STOP
    if not adr_dir.is_dir() or not words:
        return []
    scored = []
    for p in sorted(adr_dir.glob("*.md")):
        title = next((l[2:].strip() for l in p.read_text(encoding="utf-8", errors="replace").splitlines()
                      if l.startswith("# ")), p.stem)
        hay = f"{p.stem} {title}".lower()
        score = sum(1 for w in words if w in hay)
        if score:
            scored.append((-score, p.name, title))
    return [f"  {repo.rel('decisions')}/{name} - {title}" for _, name, title in sorted(scored)[:limit]]


def section(title: str, body: list[str]) -> list[str]:
    return [f"{title}:"] + body if body else [f"{title}: none"]


def brief(repo: Repo, paths: list[str], text: str) -> list[str]:
    lines = freshness(repo)[0]
    feats, journeys = touched_map(repo, paths)
    body = [f"  {f.get('id')} [{f.get('status', 'active')}] {f.get('name', '')}".rstrip() for f in feats]
    for j in journeys:
        missing = [s.get("feature") for s in as_list(j.get("steps")) if isinstance(s, dict) and s.get("status") == "missing"]
        body.append(f"  {j.get('id')}: {j.get('job', '')}" + (f" (missing: {', '.join(missing)})" if missing else ""))
    lines += section("Features/journeys for these paths", body)
    reg = repo.regeln()
    rules = [r for r in as_list(reg.get("rules")) if overlaps(paths, as_list(r.get("applies_to")))]
    lines += section("Rules for these paths", [
        f"  {r.get('id')} [{r.get('status', 'active')}]: {r.get('says', '')} -> owner: {r.get('owner', '?')}" for r in rules])
    rejected = [x for x in as_list(reg.get("rejected")) if any(keyword_hit(k, text) for k in as_list(x.get("keywords")))]
    lines += section("Rejected ideas matching the job text", [
        f"  {x.get('id')}: {x.get('idea', '')} - why: {x.get('why', '')}" for x in rejected])
    lines += section("Open dead entries", [
        f"  {d.get('id')}: {', '.join(as_list(d.get('paths')))} (retire_by {d.get('retire_by', '?')})"
        for d in as_list(reg.get("dead"))])
    lines += section("Does it exist already?", exists_already(repo, text))
    lines += section("Matching ADRs", matching_adrs(repo, text))
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES - 1] + [f"(+{len(lines) - MAX_LINES + 1} more)"]
    return lines


def scope(repo: Repo, base: str | None, job_paths: list[str]) -> dict:
    diff = repo.diff(base)
    if diff is None:
        raise KzError(f"no diff base: {base or repo.cfg['main_branch']} not found")
    anchors, deletions = [], []
    for path, fd in sorted(diff.files.items()):
        anchors += [f"removed {rid} in {path}" for l in fd.removed for rid in ANCHOR_RE.findall(l)]
        anchors += [f"added {rid} in {path}" for l in fd.added for rid in ANCHOR_RE.findall(l)]
        if job_paths and fd.removed and not overlaps([path], job_paths):
            deletions.append(f"{path}: {len(fd.removed)} lines deleted")
    feats, journeys = touched_map(repo, list(diff.files))
    rules = [r.get("id") for r in as_list(repo.regeln().get("rules")) if overlaps(list(diff.files), as_list(r.get("applies_to")))]
    return {"base": diff.base, "merge_base": diff.merge_base[:12], "files": len(diff.files), "anchors": anchors,
            "deletions_outside_paths": deletions, "features": [f.get("id") for f in feats],
            "journeys": [j.get("id") for j in journeys], "rules": rules}


def scope_lines(s: dict, with_paths: bool) -> list[str]:
    lines = [f"kz scope: {s['files']} files vs {s['base']} (merge-base {s['merge_base']})"]
    lines += section("Rule anchors touched", [f"  {a}" for a in s["anchors"]])
    if with_paths:
        lines += section("Deletions outside the job paths", [f"  {d}" for d in s["deletions_outside_paths"]])
    else:
        lines.append("Deletions outside the job paths: (pass --paths to check)")
    lines.append(f"Features touched: {', '.join(s['features']) or 'none'}")
    lines.append(f"Journeys touched: {', '.join(s['journeys']) or 'none'}")
    lines.append(f"Rules whose applies_to matches: {', '.join(s['rules']) or 'none'}")
    return lines

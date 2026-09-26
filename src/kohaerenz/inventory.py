"""Inventory adapters: read pages, UI features, endpoints and tables from the code."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .core import KzError, Repo, as_list, match

PAGE_RE = re.compile(r"^page\.(tsx|jsx|ts|js|mdx)$")
DATA_FEATURE_RE = re.compile(r"""data-feature=["']([\w.:/-]+)["']""")
CLASS_RE = re.compile(r"^class\s+(\w+)\s*\(([^)]*)\)\s*:", re.M)
TABLENAME_RE = re.compile(r"^\s+__tablename__\s*(?::[^=\n]+)?=\s*['\"]([\w.]+)['\"]", re.M)
SKIP_DIRS = {"node_modules", ".next", "__pycache__", ".git", ".venv", "dist", "build"}
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def route_for(rel: str, app_dir: str) -> str | None:
    """Next.js app-router route for a page file, or None if it is not a page."""
    prefix = app_dir.strip("/") + "/"
    if not rel.startswith(prefix):
        return None
    parts = rel[len(prefix):].split("/")
    if not PAGE_RE.match(parts[-1]):
        return None
    segs = [s for s in parts[:-1] if not (s.startswith("(") and s.endswith(")")) and not s.startswith("@")]
    return "/" + "/".join(segs)


def _walk(repo: Repo, rel_dir: str, exts: tuple[str, ...], exclude: list[str]):
    """Files under rel_dir that git would see (gitignored ones never), minus adapter excludes."""
    files = repo.visible_files()
    if files is None:  # git unusable: plain disk walk
        files = []
        for dirpath, dirnames, filenames in os.walk(repo.root / rel_dir):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            files += [(Path(dirpath) / n).relative_to(repo.root).as_posix() for n in sorted(filenames)]
    prefix = "" if rel_dir.strip("/") in ("", ".") else rel_dir.strip("/") + "/"
    for rel in files:
        if rel.startswith(prefix) and rel.endswith(exts) and not match(rel, exclude):
            yield rel, repo.root / rel


def nextjs(repo: Repo, a: dict, notes: list[str]) -> dict:
    app_dir = a.get("app_dir", "app")
    if not (repo.root / app_dir).is_dir():
        notes.append(f"nextjs-app: app dir '{app_dir}' not found - routes skipped")
        return {}
    exclude = as_list(a.get("exclude"))
    routes = {r for rel, _ in _walk(repo, app_dir, (".tsx", ".jsx", ".ts", ".js", ".mdx"), exclude)
              if (r := route_for(rel, app_dir))}
    features: set[str] = set()
    for src in as_list(a.get("src_dirs")) or [app_dir]:
        for _, full in _walk(repo, src, (".tsx", ".jsx", ".ts", ".js"), exclude):
            features.update(DATA_FEATURE_RE.findall(full.read_text(encoding="utf-8", errors="replace")))
    return {"routes": sorted(routes), "data_features": sorted(features)}


def fastapi(repo: Repo, a: dict, notes: list[str]) -> dict:
    out: dict = {}
    spec_rel = a.get("openapi", "openapi.json")
    spec = repo.root / spec_rel
    if spec.is_file():
        try:
            paths = json.loads(spec.read_text(encoding="utf-8")).get("paths", {})
        except json.JSONDecodeError as exc:
            raise KzError(f"fastapi: {spec_rel} is not valid JSON ({exc})") from exc
        out["endpoints"] = sorted(f"{m.upper()} {p}" for p, ops in paths.items()
                                  for m in ops if m in HTTP_METHODS)
    else:
        notes.append(f"fastapi: no OpenAPI file at '{spec_rel}' - endpoints skipped "
                     "(export it, e.g. json.dumps(app.openapi()))")
    tables: set[str] = set()
    for model_dir in as_list(a.get("model_dirs")):
        if not (repo.root / model_dir).is_dir():
            notes.append(f"fastapi: model dir '{model_dir}' not found")
            continue
        for _, full in _walk(repo, model_dir, (".py",), as_list(a.get("exclude"))):
            tables.update(tables_in(full.read_text(encoding="utf-8", errors="replace")))
    out["tables"] = sorted(tables)
    return out


def tables_in(text: str) -> set[str]:
    """Table names of SQLModel (table=True) and SQLAlchemy (__tablename__) classes."""
    found = set()
    classes = list(CLASS_RE.finditer(text))
    for i, m in enumerate(classes):
        body = text[m.end(): classes[i + 1].start() if i + 1 < len(classes) else len(text)]
        name = TABLENAME_RE.search(body)
        if name:
            found.add(name.group(1))
        elif re.search(r"\btable\s*=\s*True\b", m.group(2)):
            found.add(m.group(1).lower())
    return found


def build(repo: Repo) -> tuple[dict | None, list[str]]:
    """Inventory dict (None when no inventory adapter is configured) and notes."""
    notes: list[str] = []
    inv: dict = {}
    for a in as_list(repo.cfg["adapters"]):
        if a["name"] == "nextjs-app":
            inv.update(nextjs(repo, a, notes))
        elif a["name"] == "fastapi":
            inv.update(fastapi(repo, a, notes))
    if not inv and not notes:
        return None, notes
    return {"version": 1, **dict(sorted(inv.items()))}, notes


def items(inv: dict) -> list[tuple[str, str]]:
    """Flat (kind, value) pairs: route, data_feature, endpoint, table."""
    kinds = {"routes": "route", "data_features": "data_feature", "endpoints": "endpoint", "tables": "table"}
    return [(kinds[k], v) for k in kinds for v in inv.get(k, [])]


def dump(inv: dict) -> str:
    return json.dumps(inv, indent=2, sort_keys=True) + "\n"

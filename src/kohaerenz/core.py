"""Shared plumbing: config, git, YAML, diffs, findings, path matching."""
from __future__ import annotations

import copy
import fnmatch
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "version": 1,
    "stufe": 0,
    "typ": "generic",
    "tool_version": None,
    "main_branch": "origin/main",
    "entry_docs": ["AGENTS.md", "CLAUDE.md"],
    "adapters": [],
    "paths": {
        "landkarte": "docs/produkt/landkarte.yaml",
        "regeln": "docs/produkt/regeln.yaml",
        "baseline": "docs/produkt/luecken-basis.json",
        "inventar": "docs/produkt/inventar.json",
        "decisions": "docs/decisions",
    },
    "drift_paths": [],
    "pr_sections": ["Change to existing", "What the user sees"],
    "links_ignore": [],
}


class KzError(Exception):
    """Usage or configuration error (exit code 2)."""


@dataclass(frozen=True)
class Finding:
    check: str
    subject: str
    message: str

    @property
    def key(self) -> str:
        return f"{self.check}:{self.subject}"


def as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise KzError(f"{path.name}: invalid YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise KzError(f"{path.name}: top level must be a mapping")
    return data


def match(path: str, patterns) -> bool:
    """Glob match; a plain pattern without wildcards also matches as a directory prefix."""
    for pat in as_list(patterns):
        if fnmatch.fnmatchcase(path, pat):
            return True
        if not any(c in pat for c in "*?[") and path.startswith(pat.rstrip("/") + "/"):
            return True
    return False


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


@dataclass
class FileDiff:
    status: str = "M"
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


@dataclass
class Diff:
    base: str
    merge_base: str
    files: dict[str, FileDiff]


class Repo:
    def __init__(self, cwd: str | Path = ".", config_path: str | None = None):
        proc = git(["rev-parse", "--show-toplevel"], Path(cwd))
        if proc.returncode != 0:
            raise KzError(f"not a git repository: {cwd}")
        self.root = Path(proc.stdout.strip())
        cfg_file = Path(config_path) if config_path else self.root / ".kohaerenz.yaml"
        if config_path and not cfg_file.exists():
            raise KzError(f"config not found: {config_path}")
        self.has_config = cfg_file.exists()
        raw = load_yaml(cfg_file) if self.has_config else {}
        self.cfg = copy.deepcopy(DEFAULTS)
        for key, value in raw.items():
            if key == "paths":
                if not isinstance(value, dict):
                    raise KzError("config: 'paths' must be a mapping")
                self.cfg["paths"].update(value)
            else:
                self.cfg[key] = value
        for a in as_list(self.cfg["adapters"]):
            if not isinstance(a, dict) or a.get("name") not in ("nextjs-app", "fastapi", "generic"):
                raise KzError(f"config: unknown adapter {a!r} (use nextjs-app, fastapi, generic)")
        self._cache: dict = {}

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return git(list(args), self.root)

    def rel(self, key: str) -> str:
        return self.cfg["paths"][key]

    def path(self, key: str) -> Path:
        return self.root / self.rel(key)

    def _doc(self, key: str) -> dict:
        if key not in self._cache:
            p = self.path(key)
            self._cache[key] = load_yaml(p) if p.exists() else {}
        return self._cache[key]

    def landkarte(self) -> dict:
        return self._doc("landkarte")

    def regeln(self) -> dict:
        return self._doc("regeln")

    def adapter(self, name: str) -> dict | None:
        return next((a for a in as_list(self.cfg["adapters"]) if a.get("name") == name), None)

    def features(self) -> list[dict]:
        return [f for f in as_list(self.landkarte().get("features")) if isinstance(f, dict)]

    def journeys(self) -> list[dict]:
        return [j for j in as_list(self.landkarte().get("journeys")) if isinstance(j, dict)]

    def ref_exists(self, ref: str) -> bool:
        return self.git("rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode == 0

    def tracked_files(self) -> list[str]:
        return [p for p in self.git("ls-files").stdout.splitlines() if p]

    def diff(self, base: str | None = None) -> Diff | None:
        """Committed changes from merge-base(base, HEAD) to HEAD; None if base is missing."""
        base = base or self.cfg["main_branch"]
        if not self.ref_exists(base) or not self.ref_exists("HEAD"):
            return None
        mb = self.git("merge-base", base, "HEAD").stdout.strip()
        if not mb:
            return None
        files: dict[str, FileDiff] = {}
        for line in self.git("diff", "--name-status", "--no-renames", mb, "HEAD").stdout.splitlines():
            status, _, path = line.partition("\t")
            files[path] = FileDiff(status=status[:1])
        current, in_hunk = None, False
        for line in self.git("diff", "-U0", "--no-renames", "--no-color", mb, "HEAD").stdout.splitlines():
            if line.startswith("diff --git "):
                current, in_hunk = None, False
            elif not in_hunk and line.startswith("--- a/"):
                current = line[6:]
            elif not in_hunk and line.startswith("+++ b/"):
                current = line[6:]
            elif line.startswith("@@"):
                in_hunk = True
            elif in_hunk and current in files and line[:1] in "+-":
                (files[current].added if line[0] == "+" else files[current].removed).append(line[1:])
        return Diff(base=base, merge_base=mb, files=files)


def freshness(repo: Repo, fetch: bool = False) -> tuple[list[str], int]:
    """Lines describing HEAD vs main branch, plus commits behind (0 if unknown)."""
    main = repo.cfg["main_branch"]
    remote = main.split("/", 1)[0] if "/" in main else None
    if fetch and remote:
        repo.git("fetch", "--quiet", remote)
    if not repo.ref_exists(main):
        return [f"fresh: no {main} reference (no remote?) - cannot compare"], 0
    counts = repo.git("rev-list", "--left-right", "--count", f"HEAD...{main}").stdout.split()
    ahead, behind = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
    state = "up to date" if behind == 0 else "BEHIND"
    lines = [f"fresh: HEAD vs {main}: {behind} behind, {ahead} ahead - {state}"]
    fetch_head = repo.root / repo.git("rev-parse", "--git-path", "FETCH_HEAD").stdout.strip()
    if not fetch and fetch_head.is_file():
        hours = (time.time() - fetch_head.stat().st_mtime) / 3600
        lines.append(f"fresh: last fetch {hours:.1f} h ago (use --fetch to refresh)")
    return lines, behind

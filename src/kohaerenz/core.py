"""Shared plumbing: config, git, YAML, diffs, findings, path matching."""
from __future__ import annotations

import copy
import fnmatch
import os
import stat
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


ADAPTER_KEYS = {
    "nextjs-app": {"name", "app_dir", "src_dirs", "exclude"},
    "fastapi": {"name", "openapi", "model_dirs", "api_dirs", "exclude"},
    "generic": {"name"},
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
    except OSError as exc:
        raise KzError(f"{path.name}: cannot read ({exc.strerror or exc})") from exc
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


def probe(path: Path) -> str | None:
    """'file', 'dir', None (missing) or 'unreadable' - never raises (sandboxes may deny stat)."""
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        return "unreadable"
    return "dir" if stat.S_ISDIR(st.st_mode) else "file"


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
        self.unreadable: set[str] = set()
        if config_path and probe(cfg_file) is None:
            raise KzError(f"config not found: {config_path}")
        self.has_config = probe(cfg_file) is not None
        raw = load_yaml(cfg_file) if self.has_config else {}
        self.cfg = copy.deepcopy(DEFAULTS)
        for key, value in raw.items():
            if key == "paths":
                if not isinstance(value, dict):
                    raise KzError("config: 'paths' must be a mapping")
                self.cfg["paths"].update(value)
            else:
                self.cfg[key] = value
        self._validate(raw)
        self._cache: dict = {}

    def _validate(self, raw: dict) -> None:
        """Unknown keys and paths outside the repo are errors: a typo must never turn checks off."""
        unknown = [f"'{k}'" for k in raw if k not in DEFAULTS]
        unknown += [f"'paths.{k}'" for k in self.cfg["paths"] if k not in DEFAULTS["paths"]]
        if self.cfg["stufe"] not in (0, 1, 2):
            raise KzError(f"config: stufe must be 0, 1 or 2, not {self.cfg['stufe']!r}")
        rel_paths = list(self.cfg["paths"].values()) + as_list(self.cfg["entry_docs"])
        for a in as_list(self.cfg["adapters"]):
            if not isinstance(a, dict) or a.get("name") not in ADAPTER_KEYS:
                raise KzError(f"config: unknown adapter {a!r} (use {', '.join(ADAPTER_KEYS)})")
            unknown += [f"'adapters.{a['name']}.{k}'" for k in a if k not in ADAPTER_KEYS[a["name"]]]
            ex = a.get("exclude", [])
            if not isinstance(ex, list) or not all(isinstance(g, str) for g in ex):
                raise KzError(f"config: adapters.{a['name']}.exclude must be a list of glob strings")
            rel_paths += [v for k in ("app_dir", "openapi") if k in a for v in [a[k]]]
            rel_paths += [v for k in ("src_dirs", "model_dirs", "api_dirs") for v in as_list(a.get(k))]
        if unknown:
            raise KzError(f"config: unknown key(s) {', '.join(unknown)}")
        root = self.root.resolve()
        for rel in rel_paths:
            if not (root / str(rel)).resolve().is_relative_to(root):
                raise KzError(f"config: path '{rel}' points outside the repo")

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return git(list(args), self.root)

    def rel(self, key: str) -> str:
        return self.cfg["paths"][key]

    def path(self, key: str) -> Path:
        return self.root / self.rel(key)

    def _doc(self, key: str) -> dict:
        if key not in self._cache:
            p = self.path(key)
            self._cache[key] = load_yaml(p) if probe(p) is not None else {}
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

    def note_unreadable(self, path: Path) -> None:
        self.unreadable.add(path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else str(path))

    def kind(self, path: Path) -> str | None:
        """Like probe(), but remembers unreadable files for the 'skipped N unreadable' note."""
        k = probe(path)
        if k == "unreadable":
            self.note_unreadable(path)
        return k

    def read(self, path: Path) -> str | None:
        """File text, or None if missing or unreadable (the latter is noted)."""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            return None
        except OSError:
            self.note_unreadable(path)
            return None

    def tracked_files(self) -> list[str]:
        return [p for p in self.git("ls-files").stdout.splitlines() if p]

    def visible_files(self) -> list[str] | None:
        """Files git would see: tracked + untracked-not-ignored, present on disk. None if git fails."""
        if "visible" not in self._cache:
            proc = self.git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
            self._cache["visible"] = None if proc.returncode else sorted(
                {p for p in proc.stdout.split("\0") if p and self.kind(self.root / p) in ("file", "unreadable")})
        return self._cache["visible"]

    def is_visible(self, rel: str) -> bool:
        """A git-visible file, or a directory containing one (falls back to the disk)."""
        files = self.visible_files()
        if files is None:
            return self.kind(self.root / rel) is not None
        rel = rel.rstrip("/")
        return rel in files or any(f.startswith(rel + "/") for f in files)

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
    try:
        mtime = os.stat(fetch_head).st_mtime if not fetch else None
    except OSError:
        mtime = None
    if mtime is not None:
        hours = (time.time() - mtime) / 3600
        lines.append(f"fresh: last fetch {hours:.1f} h ago (use --fetch to refresh)")
    return lines, behind

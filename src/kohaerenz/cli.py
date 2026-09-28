"""Command line entry point `kz`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import __version__, checks, inventory
from .brief import brief, scope, scope_lines
from .core import KzError, Repo, freshness, probe

AGENTS_STUB = """# AGENTS.md

One line: what this project is and who uses it.

## Start here
- Freshness of the checkout: `kz fresh`
- Before a job: `kz brief --paths <paths> --text "<job>"`
- Before a PR: `kz check`

## Rules
- Add the "must / never" rules of this project here (keep this file under 80 lines).
"""
LANDKARTE_STUB = "version: 1\njourneys: []\nfeatures: []\ninternal: []\nbackground: []\n"
REGELN_STUB = "rules: []\nrejected: []\ndead: []\n"


def cmd_fresh(repo: Repo, a) -> int:
    lines, behind = freshness(repo, fetch=a.fetch)
    print("\n".join(lines))
    return 1 if behind else 0


def cmd_links(repo: Repo, a) -> int:
    findings, _, _ = checks.run(repo, only=["links"])
    for f in findings:
        print(f"RED  {f.key}  {f.message}")
    print(f"links: {'FAIL' if findings else 'OK'} ({len(findings)} missing)")
    return 1 if findings else 0


def cmd_brief(repo: Repo, a) -> int:
    lines = brief(repo, a.paths, a.text)
    print(json.dumps({"lines": lines}, indent=2) if a.json else "\n".join(lines))
    return 0


def cmd_scope(repo: Repo, a) -> int:
    s = scope(repo, a.base, a.paths)
    print(json.dumps(s, indent=2) if a.json else "\n".join(scope_lines(s, bool(a.paths))))
    return 0


def cmd_inventory(repo: Repo, a) -> int:
    inv, notes = inventory.build(repo)
    for n in notes:
        print(f"note: {n}")
    if inv is None:
        print("inventory: no inventory adapter configured (generic)")
        return 0
    if a.json:
        print(inventory.dump(inv), end="")
    else:
        print("inventory: " + ", ".join(f"{len(v)} {k}" for k, v in inv.items() if isinstance(v, list)))
    if a.write:
        p = repo.path("inventar")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inventory.dump(inv), encoding="utf-8")
        print(f"wrote {repo.rel('inventar')}")
    return 0


def cmd_check(repo: Repo, a) -> int:
    only = [n.strip() for n in a.only.split(",")] if a.only else None
    unknown = [n for n in only or [] if n not in checks.CHECKS]
    if unknown:
        raise KzError(f"unknown check(s): {', '.join(unknown)}")
    body = None
    if a.pr_body_file:
        try:
            body = Path(a.pr_body_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise KzError(f"PR body file not readable: {a.pr_body_file} ({exc.strerror or exc})") from exc
    findings, skipped, notes = checks.run(repo, a.base, body, a.fast, only)
    by_key = {f.key: f for f in findings}
    bpath = repo.path("baseline")
    baseline = checks.load_baseline(bpath)
    new = sorted(k for k in by_key if k not in baseline)
    known = sorted(k for k in by_key if k in baseline)
    ran = set(only or checks.CHECKS) - set(skipped)
    fixed = sorted(k for k in baseline if k not in by_key and k.split(":", 1)[0] in ran)
    if a.update_baseline:
        if new and not a.allow_grow:
            print(f"refusing to add {len(new)} key(s) to the baseline (it only shrinks); fix them or pass --allow-grow")
            return 1
        keep = {k for k in baseline if k.split(":", 1)[0] not in ran}
        checks.write_baseline(bpath, set(by_key) | keep)
        print(f"baseline {repo.rel('baseline')}: {len(set(by_key) | keep)} keys (-{len(fixed)} fixed, +{len(new)} new)")
        return 0
    failed = bool(new or (a.strict and fixed) or (a.require_all and skipped))
    result = "FAIL" if failed else "OK" + (f" ({len(skipped)} skipped)" if skipped else "")
    if a.json:
        print(json.dumps({"result": result, "new": [vars(by_key[k]) | {"key": k} for k in new], "known": known,
                          "fixed": fixed, "skipped": skipped, "notes": notes,
                          "unreadable": sorted(repo.unreadable)}, indent=2))
    else:
        for k in new:
            print(f"NEW    {k}  {by_key[k].message}")
        for k in known if a.verbose else []:
            print(f"known  {k}")
        for k in fixed:
            print(f"fixed  {k}  - gone, shrink the baseline (kz check --update-baseline)")
        for name, reason in skipped.items():
            print(f"skip   {name}: {reason}")
        for n in notes:
            print(f"note   {n}")
        print(f"kz check: {len(new)} new, {len(known)} known, {len(fixed)} fixed, {len(skipped)} skipped -> {result}")
    return 1 if failed else 0


def default_adapters(typ: str, root: Path) -> list[dict]:
    if typ == "nextjs":
        app = "src/app" if probe(root / "src/app") == "dir" else "app"
        return [{"name": "nextjs-app", "app_dir": app, "src_dirs": [app.rsplit("/", 1)[0] if "/" in app else "."]}]
    if typ == "fastapi":
        return [{"name": "fastapi", "openapi": "openapi.json", "model_dirs": ["app/models"]}]
    return []


def cmd_init(repo: Repo, a) -> int:
    cfg = {"version": 1, "stufe": a.stufe, "tool_version": __version__, "typ": a.typ,
           "main_branch": "origin/main", "adapters": default_adapters(a.typ, repo.root)}
    files = {".kohaerenz.yaml": yaml.safe_dump(cfg, sort_keys=False), "AGENTS.md": AGENTS_STUB, "CLAUDE.md": "@AGENTS.md\n"}
    if a.stufe >= 1:
        files[repo.rel("landkarte")] = LANDKARTE_STUB
    if a.stufe >= 2:
        files[repo.rel("regeln")] = REGELN_STUB
        files[repo.rel("baseline")] = json.dumps({"version": 1, "keys": []}, indent=2) + "\n"
    for rel, content in files.items():
        p = repo.root / rel
        if probe(p) is not None:
            print(f"kept     {rel} (exists)")
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        print(f"created  {rel}")
    if a.stufe >= 2 and cfg["adapters"]:
        print("next     kz inventory --write  (stage 2 checks the generated inventory)")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kz", description="kohaerenz - coherence checks for a repo (no LLM).")
    p.add_argument("--version", action="version", version=f"kz {__version__}")
    p.add_argument("-C", dest="cwd", default=".", help="run as if started in this directory")
    p.add_argument("--config", help="config file instead of <repo>/.kohaerenz.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("fresh", help="is HEAD at the main branch?")
    s.add_argument("--fetch", action="store_true", help="git fetch first")
    sub.add_parser("links", help="missing paths referenced in AGENTS.md/CLAUDE.md")
    s = sub.add_parser("brief", help="<= 60 lines of context for a job")
    s.add_argument("--paths", nargs="*", default=[])
    s.add_argument("--text", default="")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("check", help="run the checks (ratchet against the baseline)")
    s.add_argument("--base", help="diff base ref (default: main_branch)")
    s.add_argument("--pr-body-file")
    s.add_argument("--fast", action="store_true", help="skip inventory checks (map, generated)")
    s.add_argument("--only", help="comma-separated check names")
    s.add_argument("--strict", action="store_true", help="also fail on fixed keys still in the baseline")
    s.add_argument("--require-all", action="store_true", help="fail when any check was skipped (for CI)")
    s.add_argument("--update-baseline", action="store_true")
    s.add_argument("--allow-grow", action="store_true", help="let --update-baseline add keys")
    s.add_argument("--json", action="store_true")
    s.add_argument("-v", "--verbose", action="store_true", help="list known findings")
    s = sub.add_parser("scope", help="reviewer list for the current diff")
    s.add_argument("--base")
    s.add_argument("--paths", nargs="*", default=[], help="paths the job was allowed to change")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("inventory", help="routes/features/endpoints/tables from the code")
    s.add_argument("--write", action="store_true")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("init", help="write skeleton files (never overwrites)")
    s.add_argument("--stufe", type=int, choices=[0, 1, 2], default=0)
    s.add_argument("--typ", choices=["nextjs", "fastapi", "python-cli", "static"], default="python-cli")
    return p


COMMANDS = {"fresh": cmd_fresh, "links": cmd_links, "brief": cmd_brief, "check": cmd_check,
            "scope": cmd_scope, "inventory": cmd_inventory, "init": cmd_init}


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    try:
        repo = Repo(a.cwd, a.config)
        code = COMMANDS[a.cmd](repo, a)
    except KzError as exc:
        print(f"kz: error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:  # last resort: a file access we did not guard must not crash a hook
        print(f"kz: error: cannot access {exc.filename or 'a file'} ({exc.strerror or exc})", file=sys.stderr)
        return 2
    if repo.unreadable:
        shown = ", ".join(sorted(repo.unreadable)[:5]) + (" ..." if len(repo.unreadable) > 5 else "")
        print(f"note: skipped {len(repo.unreadable)} unreadable file(s): {shown}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())

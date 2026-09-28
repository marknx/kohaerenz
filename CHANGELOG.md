# Changelog

## 0.1.4
- The inventory is only built when a selected check needs it (`map`, `generated`): `kz links` and `kz check --only ...` without those checks are faster and read no source files.

## 0.1.3
- Never crash on files that cannot be stat'ed or read (e.g. a sandbox denying `.env*`): such files are skipped, never reported as missing, and listed once on stderr as `note: skipped N unreadable file(s)` (and under `unreadable` in `check --json`). Unreadable config, map, rules or baseline files are a clean config error (exit 2), never a traceback.
- Tests run with an empty global git config, so a developer's global excludes cannot change results.

## 0.1.2
- Landkarte entries in feature `api`, `tables`, `ui.route` and top-level `internal` may be fnmatch patterns (`*`, `?`, `[...]`; in routes `[id]` stays literal). Exact entries work as before.
- `map` reports entries that match nothing: `map:stale-pattern:<kind>:<pattern>` and `map:stale-ref:<kind>:<value>` (only for kinds the inventory covers). Malformed `internal` entries: `map:bad-internal:<entry>`.
- `brief`/`scope` match paths to features through route patterns too and list every matching feature.

## 0.1.1
- Inventory adapters and `links` only see files git would see (tracked + untracked-not-ignored); gitignored private files never count. Disk walk only as fallback when git fails.
- New optional per-adapter `exclude: [glob, ...]` for files `.gitignore` does not cover.

## 0.1.0
- First version: `fresh`, `links`, `brief`, `check` (11 checks, ratchet baseline), `scope`, `inventory` (nextjs-app, fastapi), `init`.

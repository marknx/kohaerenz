# Changelog

## 0.1.2
- Landkarte entries in feature `api`, `tables`, `ui.route` and top-level `internal` may be fnmatch patterns (`*`, `?`, `[...]`; in routes `[id]` stays literal). Exact entries work as before.
- `map` reports entries that match nothing: `map:stale-pattern:<kind>:<pattern>` and `map:stale-ref:<kind>:<value>` (only for kinds the inventory covers). Malformed `internal` entries: `map:bad-internal:<entry>`.
- `brief`/`scope` match paths to features through route patterns too and list every matching feature.

## 0.1.1
- Inventory adapters and `links` only see files git would see (tracked + untracked-not-ignored); gitignored private files never count. Disk walk only as fallback when git fails.
- New optional per-adapter `exclude: [glob, ...]` for files `.gitignore` does not cover.

## 0.1.0
- First version: `fresh`, `links`, `brief`, `check` (11 checks, ratchet baseline), `scope`, `inventory` (nextjs-app, fastapi), `init`.

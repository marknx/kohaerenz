# Changelog

## 0.1.1
- Inventory adapters and `links` only see files git would see (tracked + untracked-not-ignored); gitignored private files never count. Disk walk only as fallback when git fails.
- New optional per-adapter `exclude: [glob, ...]` for files `.gitignore` does not cover.

## 0.1.0
- First version: `fresh`, `links`, `brief`, `check` (11 checks, ratchet baseline), `scope`, `inventory` (nextjs-app, fastapi), `init`.

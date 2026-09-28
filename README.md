# kohaerenz (`kz`)

Plain text and git checks that keep a repo's **product map**, **rules** and **code** from drifting apart.
No LLM, no service: Python ≥ 3.11 + PyYAML. Meant to run before a job (`kz brief`), before a push
(`kz check --fast`) and as a required CI check (`kz check`).

## Install

```sh
pipx install .            # or: pipx install git+<repo-url>@v0.1.0
kz --version
```

## Commands

| Command | What it does |
|---|---|
| `kz fresh [--fetch]` | Is HEAD at `origin/main`? Commits behind/ahead. Exit 1 when behind. |
| `kz links` | Paths referenced in `AGENTS.md` / `CLAUDE.md` (backticked paths with a file extension or trailing `/`, markdown links, `@file` includes) that do not exist. |
| `kz brief --paths P... --text "job"` | ≤ 60 lines of context for a job: freshness, touched features/journeys, rules whose `applies_to` match (with `owner`), rejected ideas whose keywords appear in the text, open `dead` entries, "does it exist already?" (`git grep` for routes and backticked identifiers), matching ADRs. `--json` available. |
| `kz check` | All checks below, ratcheted against the baseline. Options: `--base REF`, `--pr-body-file F`, `--fast` (skip inventory checks), `--only a,b`, `--strict`, `--require-all` (any skipped check fails - use in CI), `--update-baseline [--allow-grow]`, `--json`, `-v`. |
| `kz scope [--base REF] [--paths P...]` | Reviewer list: rule anchors added/removed in the diff, deleted lines outside the job paths, touched features/journeys, matching rules. |
| `kz inventory [--write] [--json]` | Routes, `data-feature` ids, endpoints and tables read from the code by the adapters. `--write` writes `docs/produkt/inventar.json` (sorted, deterministic). |
| `kz init --stufe 0\|1\|2 --typ nextjs\|fastapi\|python-cli\|static` | Skeleton files for the stage. Never overwrites. |

Global options: `-C DIR` (run in another directory), `--config FILE` (config outside the repo).

### Checks

| Check | Red when … | Needs |
|---|---|---|
| `map` | an inventory item (route, data-feature, endpoint, table) is in no feature and not in `internal`; a map entry (exact or pattern) matches no inventory item (stale) | adapter |
| `orphans` | an active feature is in no journey; a journey has no existing test file; a journey step names an unknown feature (unless `status: missing`) | – |
| `states` | a feature state has neither `next` nor `end_reason` | – |
| `rules` | an `active` rule has no existing guard test (`path::test_name`); a `rule: R-…` anchor in code names an unknown rule | `regeln.yaml` |
| `anchors` | a `rule: R-…` anchor line is deleted without changing `regeln.yaml`; a rule is removed without `removed: R-…` in the PR text | diff base |
| `adr` | an ADR head with `supersedes`/`retires` lacks `affected_paths`; `retires` lacks `retire_by` | – |
| `timebomb` | `retire_by` has passed and the feature is still on the map, or the `dead` paths still exist | – |
| `drift` | UI/API paths changed but the map did not, and the PR text lacks `map unchanged because …` | diff base |
| `pr` | the computed size is M/L (new page, endpoint or table, or > 3 files) and the PR text lacks a required section | diff base + PR text |
| `generated` | `inventar.json` is missing or differs from the code | adapter |
| `links` | as `kz links` | – |

The diff base is the merge-base of `--base` (default `main_branch`, i.e. `origin/main`) and HEAD; only
committed changes count. Checks whose input is missing are listed as `skip` and the result reads
`OK (N skipped)`, never a plain `OK`. From stage 1 on, a `main_branch` (or `--base`) that cannot be resolved is a
config error (exit 2), so a typo cannot switch the diff checks off. Unknown config keys and paths pointing outside
the repo are config errors too.
A new page/endpoint/table is caught by `map` even when the PR text claims the map is unchanged.

File walks (inventory adapters, `links`, `timebomb`) only see files git would see: tracked plus
untracked-not-ignored (`git ls-files --cached --others --exclude-standard`). Gitignored private files in a checkout
never show up, so local runs and CI agree. Per-adapter `exclude: [glob, ...]` drops anything else. The configured
`openapi` file is read even when it is gitignored (it is usually generated).

The `nextjs-app` adapter walks `app/**/page.*` itself instead of reusing a project's own route script: `kz` must
work in any repo with Python alone, and such scripts are usually Node-based and tied to one project.

Not implemented in v0.1 (warn-only in the concept): `registries`, `wiring`, `collisions`; also `watch`, `report`, `stufe`.

### Ratchet

Every finding has a stable key `check:subject` (e.g. `map:route:/tasks`). `docs/produkt/luecken-basis.json`
holds the known keys: known findings are reported but do not fail, **new** findings fail, keys that no longer
occur are reported as `fixed` (fail only with `--strict`). `kz check --update-baseline` rewrites the file but
refuses to add keys unless `--allow-grow` is given - the baseline only shrinks. Keys of skipped checks are kept.

### Escape hatch

A PR label `kz-skip` is a CI concern: the workflow skips `kz check` when it is set. Only maintainers should be
able to set it, and every use should be counted.

## Files

**`.kohaerenz.yaml`** (repo root)

```yaml
version: 1
stufe: 2                 # 0 experiment, 1 tool/website, 2 product
tool_version: 0.1.0
typ: nextjs
main_branch: origin/main
adapters:                # none = generic (no inventory)
  - {name: nextjs-app, app_dir: web/src/app, src_dirs: [web/src], exclude: ["web/src/app/lab/**"]}
  - {name: fastapi, openapi: backend/openapi.json, model_dirs: [backend/app/models], api_dirs: [backend/app/api]}
drift_paths: ["backend/app/workers/**"]     # extra paths that count as UI/API/background
pr_sections: ["Change to existing", "What the user sees"]
entry_docs: [AGENTS.md, CLAUDE.md]
links_ignore: []
paths: {}                # override any file location below
```

**`docs/produkt/landkarte.yaml`** - journeys and features, written by hand.

```yaml
version: 1
journeys:
  - id: J-job-to-merge
    job: "When I have a coding job, I want to hand it off and later merge a checked PR."
    steps: [{feature: F-job-create}, {feature: F-result-adopt, status: missing}]
    test: e2e/journeys/J-job-to-merge.spec.ts
features:
  - id: F-job-create
    name: "Create a job"
    ui: {route: /jobs/new, data_feature: job-create}
    api: ["POST /api/v1/jobs"]
    tables: [jobs]
    paths: ["web/src/app/jobs/**"]
    status: active        # trial | active | frozen | retire | internal
    states: {queued: {next: "Start"}, cancelled: {end_reason: "user stopped it"}}
  - {id: F-legacy, status: retire, retire_by: 2026-11-01}
internal: ["route:/debug", "endpoint:GET /healthz"]
```

**Patterns.** Entries in `api`, `tables`, `ui.route` and `internal` may be fnmatch patterns, so a large API stays
readable: `api: ["* /api/v1/agent/*"]`, `tables: ["agent_*"]`, `internal: ["endpoint:GET /api/v1/internal/*"]`.
They match the inventory strings (`METHOD /path`, table name, route) and `*` also crosses `/`. In routes only `*`
and `?` are wildcards - `[id]` stays a literal Next.js segment. An item may be covered by several features; `brief`
and `scope` list all of them. An entry that matches nothing is red in `map` (`map:stale-pattern:<kind>:<pattern>`
or `map:stale-ref:<kind>:<value>`), but only for kinds the inventory covers (no OpenAPI file = no endpoint check).

**`docs/produkt/regeln.yaml`** - rules, rejected ideas, dead code.

```yaml
rules:
  - id: R-dispatch-cooldown
    says: "Dispatch warns at most once per 5 minutes."
    owner: backend/app/services/dispatch.py
    applies_to: ["backend/app/services/**"]
    enforced_by: [{test: "backend/tests/test_dispatch.py::test_cooldown_5min"}]
    status: active        # active | wish | superseded
rejected:
  - {id: X-run-model, idea: "A new run model", why: "Three exist unused.", keywords: [workflow, run model]}
dead:
  - {id: D-workflows, paths: [backend/app/services/workflow_service.py], retire_by: 2026-11-01}
```

Code anchors: `# rule: R-dispatch-cooldown - why`.

**`docs/produkt/luecken-basis.json`** - `{"version": 1, "keys": ["map:route:/old", ...]}`

**ADR head** (optional, `docs/decisions/*.md`): YAML front matter with `status`, `supersedes`, `retires`,
`affected_paths`, `retire_by`, `enforced_by`.

## Exit codes

`0` ok · `1` findings (new red, behind main for `fresh`, missing links) · `2` usage or config error.

## Development

```sh
python3.12 -m venv .venv && .venv/bin/pip install -e '.[test]' && .venv/bin/pytest -q
```

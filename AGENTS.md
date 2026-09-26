# AGENTS.md

kohaerenz (`kz`): text and git checks that keep a repo's product map, rules and code coherent. No LLM.

## Start here
- Overview, commands, file formats: [README](README.md)
- Code: `src/kohaerenz/` (`core.py` config/git/diff, `checks.py`, `inventory.py`, `brief.py`, `cli.py`)
- Tests: `tests/` - run `.venv/bin/pytest -q`
- Before a PR: `kz check` and `kz links`

## Rules
- Python >= 3.11, stdlib + PyYAML only. No LLM calls, no network except `git fetch` on request.
- Every check has a positive and a negative test in `tests/test_checks.py`; break the check once (sabotage probe) and see a test go red.
- Output is plain English text; `--json` for machines. Exit codes: 0 ok, 1 findings, 2 usage/config error.
- The repo is public: no person names, host names, IPs, home paths or private project details in code, tests or docs.
- Tool code stays small: <= 1000 lines (tests excluded), because 11 checks, 7 commands and 2 adapters each need their own few dozen lines; do not golf the code to fit.

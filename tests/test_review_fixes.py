"""Review fixes: exact guard names, strict config, no false green on misconfig."""
import pytest

RULES = "docs/produkt/regeln.yaml"


def _rule(repo, spec):
    repo.write(RULES, f'rules:\n  - {{id: R-a, enforced_by: [{{test: "{spec}"}}]}}\n')


# --- 1. guard test found by exact name, not substring ----------------------

def test_guard_name_is_not_a_substring_match(repo):
    repo.write("tests/test_x.py", "def test_barbaz():\n    pass\n# test_bar mentioned in a comment\n")
    _rule(repo, "tests/test_x.py::test_bar")
    repo.commit()
    code, out = repo.kz("check", "--only", "rules")
    assert code == 1 and "rules:R-a" in out


def test_guard_finds_functions_and_class_methods(repo):
    repo.write("tests/test_x.py", "class TestCool:\n    def test_bar(self):\n        pass\n\nasync def test_async():\n    pass\n")
    _rule(repo, "tests/test_x.py::TestCool::test_bar")
    repo.commit()
    assert repo.kz("check", "--only", "rules")[0] == 0
    _rule(repo, "tests/test_x.py::test_async")
    repo.commit()
    assert repo.kz("check", "--only", "rules")[0] == 0


def test_guard_in_non_python_file_uses_word_boundaries(repo):
    repo.write("e2e/a.spec.ts", "test('cooldown_5min_extra', () => {})\n")
    _rule(repo, "e2e/a.spec.ts::cooldown_5min")
    repo.commit()
    assert repo.kz("check", "--only", "rules")[0] == 1
    repo.write("e2e/a.spec.ts", "test('cooldown_5min', () => {})\n").commit()
    assert repo.kz("check", "--only", "rules")[0] == 0


# --- 2a. strict config validation --------------------------------------------

@pytest.mark.parametrize("cfg,word", [
    ("main_brnch: origin/main\n", "main_brnch"),
    ("paths: {landkarta: x.yaml}\n", "landkarta"),
    ("adapters: [{name: fastapi, openapi_path: x.json}]\n", "openapi_path"),
])
def test_unknown_config_keys_exit_2(repo, cfg, word):
    repo.write(".kohaerenz.yaml", cfg).commit()
    code, out = repo.kz("fresh")
    assert code == 2 and word in out


# --- 2b. unresolvable diff base is a config error from stage 1 ---------------

def test_stage1_missing_main_branch_exit_2(repo):
    repo.write(".kohaerenz.yaml", "stufe: 1\nmain_branch: origin/nope\n").commit()
    code, out = repo.kz("check")
    assert code == 2 and "main_branch 'origin/nope' not found" in out


def test_explicit_missing_base_exit_2(repo):
    repo.write("a").commit()
    code, out = repo.kz("check", "--base", "nope")
    assert code == 2 and "'nope' not found" in out


def test_stage0_without_remote_ok_but_shows_skips(repo):
    repo.write("a").commit()
    code, out = repo.kz("check")
    assert code == 0 and "OK (6 skipped)" in out


# --- 2c. --require-all -------------------------------------------------------

def test_require_all_turns_skips_red(repo):
    repo.write("a").commit()
    code, out = repo.kz("check", "--require-all")
    assert code == 1 and "FAIL" in out
    assert repo.kz("check", "--only", "links,orphans", "--require-all")[0] == 0


# --- 5. config paths must stay inside the repo -------------------------------

@pytest.mark.parametrize("value", ["../outside.yaml", "/etc/passwd", "docs/../../x.yaml"])
def test_paths_outside_repo_exit_2(repo, value):
    repo.write(".kohaerenz.yaml", f"paths: {{landkarte: '{value}'}}\n").commit()
    code, out = repo.kz("check")
    assert code == 2 and "outside the repo" in out


def test_adapter_dir_outside_repo_exit_2(repo):
    repo.write(".kohaerenz.yaml", "adapters: [{name: nextjs-app, app_dir: ../other/app}]\n").commit()
    assert repo.kz("inventory")[0] == 2

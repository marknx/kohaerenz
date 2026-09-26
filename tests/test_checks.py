"""One positive (finding) and one negative (clean) case per check."""
import json

NEXT_CFG = """\
    adapters:
      - name: nextjs-app
        app_dir: web/app
        src_dirs: [web]
    """
MAP = "docs/produkt/landkarte.yaml"
RULES = "docs/produkt/regeln.yaml"


def keys(out: str) -> list[str]:
    return [l.split()[1] for l in out.splitlines() if l.startswith("NEW")]


# --- map -----------------------------------------------------------------

def test_map_flags_unmapped_route(repo):
    repo.write(".kohaerenz.yaml", NEXT_CFG).write("web/app/tasks/page.tsx", "x").write(MAP, "features: []\n").commit()
    code, out = repo.kz("check", "--only", "map")
    assert code == 1 and keys(out) == ["map:route:/tasks"]


def test_map_clean_when_route_in_feature_or_internal(repo):
    repo.write(".kohaerenz.yaml", NEXT_CFG).write("web/app/tasks/page.tsx", '<div data-feature="t-list"/>')
    repo.write("web/app/(admin)/debug/page.tsx", "x")
    repo.write(MAP, """\
        features:
          - {id: F-tasks, ui: {route: /tasks, data_feature: t-list}}
        internal: ["route:/debug"]
        """).commit()
    code, out = repo.kz("check", "--only", "map")
    assert code == 0, out


# --- orphans -------------------------------------------------------------

def test_orphans_flags_feature_without_journey_and_journey_without_test(repo):
    repo.write(MAP, """\
        journeys:
          - {id: J-a, steps: [{feature: F-a}], test: e2e/a.spec.ts}
        features:
          - {id: F-a}
          - {id: F-b, status: active}
        """).commit()
    code, out = repo.kz("check", "--only", "orphans")
    assert code == 1 and sorted(keys(out)) == ["orphans:F-b", "orphans:J-a:test"]


def test_orphans_clean(repo):
    repo.write("e2e/a.spec.ts", "test").write(MAP, """\
        journeys:
          - {id: J-a, steps: [{feature: F-a}, {feature: F-new, status: missing}], test: e2e/a.spec.ts}
        features:
          - {id: F-a}
          - {id: F-helper, status: internal}
        """).commit()
    assert repo.kz("check", "--only", "orphans")[0] == 0


# --- states --------------------------------------------------------------

def test_states_flags_state_without_next(repo):
    repo.write(MAP, """\
        features:
          - id: F-a
            states: {passed: {next: "Adopt"}, failed: {}}
        """).commit()
    code, out = repo.kz("check", "--only", "states")
    assert code == 1 and keys(out) == ["states:F-a:failed"]


def test_states_clean(repo):
    repo.write(MAP, """\
        features:
          - id: F-a
            states: {passed: {next: "Adopt"}, cancelled: {end_reason: "operator stopped it"}}
        """).commit()
    assert repo.kz("check", "--only", "states")[0] == 0


# --- rules ---------------------------------------------------------------

def test_rules_flags_rule_without_existing_test_and_unknown_anchor(repo):
    repo.write("src/svc.py", "x = 1  # rule: R-ghost\n").write("tests/test_svc.py", "def test_other(): pass\n")
    repo.write(RULES, """\
        rules:
          - {id: R-a, enforced_by: [{test: "tests/test_svc.py::test_cooldown"}]}
          - {id: R-b, enforced_by: [{test: "tests/missing.py"}]}
          - {id: R-c, status: wish}
        """).commit()
    code, out = repo.kz("check", "--only", "rules")
    assert code == 1 and sorted(keys(out)) == ["rules:R-a", "rules:R-b", "rules:anchor:R-ghost"]


def test_rules_clean(repo):
    repo.write("src/svc.py", "x = 1  # rule: R-a\n").write("tests/test_svc.py", "def test_cooldown(): pass\n")
    repo.write(RULES, """\
        rules:
          - {id: R-a, enforced_by: [{test: "tests/test_svc.py::test_cooldown"}]}
        """).commit()
    code, out = repo.kz("check", "--only", "rules")
    assert code == 0, out


# --- anchors -------------------------------------------------------------

def _anchor_base(repo):
    repo.write("src/svc.py", "limit = 5  # rule: R-cool\nother = 1\n").write(RULES, "rules:\n  - {id: R-cool, status: wish}\n")
    repo.commit("base").mark_main()


def test_anchors_flags_deleted_anchor_without_regeln_change(repo):
    _anchor_base(repo)
    repo.write("src/svc.py", "other = 1\n").commit("drop anchor")
    code, out = repo.kz("check", "--only", "anchors")
    assert code == 1 and keys(out) == ["anchors:R-cool"]


def test_anchors_clean_when_regeln_changed_or_anchor_moved(repo):
    _anchor_base(repo)
    repo.write("src/svc.py", "other = 1\n").write("src/new.py", "limit = 5  # rule: R-cool\n").commit("move")
    assert repo.kz("check", "--only", "anchors")[0] == 0
    repo.rm("src/new.py").write(RULES, "rules: []\n").commit("retire rule")
    body = repo.path / "body.md"
    body.write_text("removed: R-cool (no longer needed)")
    assert repo.kz("check", "--only", "anchors", "--pr-body-file", str(body))[0] == 0


def test_anchors_flags_unannounced_rule_removal(repo):
    _anchor_base(repo)
    repo.write("src/svc.py", "other = 1\n").write(RULES, "rules: []\n").commit()
    body = repo.path.parent / "body.md"
    body.write_text("small cleanup")
    code, out = repo.kz("check", "--only", "anchors", "--pr-body-file", str(body))
    assert code == 1 and keys(out) == ["anchors:R-cool:unannounced"]


# --- adr -----------------------------------------------------------------

def test_adr_flags_retiring_adr_without_paths_or_date(repo):
    repo.write("docs/decisions/051-drop-x.md", "---\nretires: old workflows\n---\n# Drop X\n").commit()
    code, out = repo.kz("check", "--only", "adr")
    assert code == 1 and sorted(keys(out)) == ["adr:051-drop-x.md:affected_paths", "adr:051-drop-x.md:retire_by"]


def test_adr_clean(repo):
    repo.write("docs/decisions/051-drop-x.md",
               "---\nretires: old workflows\naffected_paths: [src/wf.py]\nretire_by: 2030-01-01\n---\n# Drop X\n")
    repo.write("docs/decisions/001-plain.md", "# Plain ADR without head\n").commit()
    assert repo.kz("check", "--only", "adr")[0] == 0


# --- timebomb ------------------------------------------------------------

def test_timebomb_flags_expired_dead_entry_and_feature(repo):
    repo.write("src/wf.py", "x").write(RULES, "dead:\n  - {id: D-wf, paths: [src/wf.py], retire_by: 2000-01-01}\n")
    repo.write(MAP, "features:\n  - {id: F-old, status: retire, retire_by: 2000-01-01}\n").commit()
    code, out = repo.kz("check", "--only", "timebomb")
    assert code == 1 and sorted(keys(out)) == ["timebomb:D-wf", "timebomb:F-old"]


def test_timebomb_clean_when_future_or_code_gone(repo):
    repo.write(RULES, """\
        dead:
          - {id: D-gone, paths: [src/wf.py], retire_by: 2000-01-01}
          - {id: D-later, paths: [src/keep.py], retire_by: 2999-01-01}
        """).write("src/keep.py", "x")
    repo.write(MAP, "features:\n  - {id: F-old, status: retire, retire_by: 2999-01-01}\n").commit()
    assert repo.kz("check", "--only", "timebomb")[0] == 0


# --- drift ---------------------------------------------------------------

def test_drift_flags_ui_change_without_map_change(repo):
    repo.write(".kohaerenz.yaml", NEXT_CFG).write("web/app/page.tsx", "a").write(MAP, "features: []\n").commit().mark_main()
    repo.write("web/app/page.tsx", "b").commit()
    code, out = repo.kz("check", "--only", "drift")
    assert code == 1 and keys(out) == ["drift:map"]


def test_drift_clean_with_map_change_or_reason(repo):
    repo.write(".kohaerenz.yaml", NEXT_CFG).write("web/app/page.tsx", "a").write(MAP, "features: []\n").commit().mark_main()
    repo.write("web/app/page.tsx", "b").commit()
    body = repo.path.parent / "body.md"
    body.write_text("Map unchanged because only a typo was fixed.")
    assert repo.kz("check", "--only", "drift", "--pr-body-file", str(body))[0] == 0
    repo.write(MAP, "features: []\ninternal: []\n").commit()
    assert repo.kz("check", "--only", "drift")[0] == 0


# --- pr ------------------------------------------------------------------

def test_pr_flags_missing_sections_for_large_change(repo):
    repo.write("a.txt").commit().mark_main()
    for n in range(4):
        repo.write(f"f{n}.py", "x")
    repo.commit()
    body = repo.path.parent / "body.md"
    body.write_text("did stuff\n## What the user sees\nnothing\n")
    code, out = repo.kz("check", "--only", "pr", "--pr-body-file", str(body))
    assert code == 1 and keys(out) == ["pr:section:change-to-existing"]


def test_pr_flags_new_endpoint_even_in_one_file(repo):
    repo.write("a.txt").commit().mark_main()
    repo.write("api.py", "@router.get('/x')\ndef x(): ...\n").commit()
    body = repo.path.parent / "body.md"
    body.write_text("")
    assert repo.kz("check", "--only", "pr", "--pr-body-file", str(body))[0] == 1


def test_pr_clean_for_small_change_or_complete_body(repo):
    repo.write("a.txt").commit().mark_main()
    repo.write("a.txt", "fix").commit()
    body = repo.path.parent / "body.md"
    body.write_text("typo")
    assert repo.kz("check", "--only", "pr", "--pr-body-file", str(body))[0] == 0
    for n in range(4):
        repo.write(f"f{n}.py", "x")
    repo.commit()
    body.write_text("## Change to existing\nnone\n## What the user sees\nnew list\n")
    assert repo.kz("check", "--only", "pr", "--pr-body-file", str(body))[0] == 0


# --- generated -----------------------------------------------------------

def test_generated_flags_missing_or_stale_inventory(repo):
    repo.write(".kohaerenz.yaml", NEXT_CFG).write("web/app/page.tsx", "x").commit()
    code, out = repo.kz("check", "--only", "generated")
    assert code == 1 and keys(out) == ["generated:inventar"]
    repo.kz("inventory", "--write")
    repo.write("web/app/new/page.tsx", "x").commit()
    assert repo.kz("check", "--only", "generated")[0] == 1


def test_generated_clean_after_write(repo):
    repo.write(".kohaerenz.yaml", NEXT_CFG).write("web/app/page.tsx", "x").commit()
    assert repo.kz("inventory", "--write")[0] == 0
    assert repo.kz("check", "--only", "generated")[0] == 0


# --- links ---------------------------------------------------------------

def test_links_flags_missing_paths(repo):
    repo.write("AGENTS.md", "Read `docs/gone.md`, see [map](docs/map.md#top) and @notes.md; run `kz check`.\n")
    repo.write("CLAUDE.md", "@AGENTS.md\n").commit()
    code, out = repo.kz("links")
    assert code == 1
    assert {"links:AGENTS.md:docs/gone.md", "links:AGENTS.md:docs/map.md", "links:AGENTS.md:notes.md"} == {
        l.split()[1] for l in out.splitlines() if l.startswith("RED")}


def test_links_clean(repo):
    repo.write("docs/map.md").write("src/app.py")
    repo.write("AGENTS.md", "See `docs/map.md`, `src/app.py:12`, `app.py`, `origin/main`, [web](https://example.com), "
                            "`0.1.0`, `yaml.safe_load`, `~/private.md`, `<project>/x.md`.\n")
    repo.write("CLAUDE.md", "@AGENTS.md\n").commit()
    code, out = repo.kz("links")
    assert code == 0, out


# --- ratchet -------------------------------------------------------------

BASE = "docs/produkt/luecken-basis.json"


def _two_orphans(repo):
    repo.write(MAP, "features:\n  - {id: F-a}\n  - {id: F-b}\n").commit()


def test_ratchet_known_findings_pass_new_fail(repo):
    _two_orphans(repo)
    repo.write(BASE, json.dumps({"keys": ["orphans:F-a"]})).commit()
    code, out = repo.kz("check", "--only", "orphans")
    assert code == 1 and keys(out) == ["orphans:F-b"] and "1 known" in out
    repo.write(BASE, json.dumps({"keys": ["orphans:F-a", "orphans:F-b"]})).commit()
    assert repo.kz("check", "--only", "orphans")[0] == 0


def test_ratchet_reports_fixed_and_strict_fails(repo):
    repo.write(MAP, "features: []\n").write(BASE, json.dumps({"keys": ["orphans:F-gone"]})).commit()
    code, out = repo.kz("check", "--only", "orphans")
    assert code == 0 and "fixed  orphans:F-gone" in out
    assert repo.kz("check", "--only", "orphans", "--strict")[0] == 1


def test_update_baseline_refuses_to_grow(repo):
    _two_orphans(repo)
    code, out = repo.kz("check", "--update-baseline")
    assert code == 1 and "refusing" in out and not (repo.path / BASE).exists()
    assert repo.kz("check", "--update-baseline", "--allow-grow")[0] == 0
    assert json.loads((repo.path / BASE).read_text())["keys"] == ["orphans:F-a", "orphans:F-b"]


def test_update_baseline_shrinks_and_keeps_skipped_checks(repo):
    repo.write(MAP, "features:\n  - {id: F-a}\n")
    repo.write(BASE, json.dumps({"keys": ["orphans:F-a", "orphans:F-gone", "drift:map"]})).commit()
    assert repo.kz("check", "--update-baseline")[0] == 0  # drift is skipped (no base) -> key kept
    assert json.loads((repo.path / BASE).read_text())["keys"] == ["drift:map", "orphans:F-a"]

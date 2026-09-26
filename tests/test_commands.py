"""fresh, brief, scope, inventory, init, config errors."""
import json

RULES = "docs/produkt/regeln.yaml"
MAP = "docs/produkt/landkarte.yaml"


# --- fresh ---------------------------------------------------------------

def test_fresh_behind_fails(repo):
    repo.write("a.txt").commit().write("b.txt").commit().mark_main()
    repo.git("checkout", "-q", "HEAD~1")
    code, out = repo.kz("fresh")
    assert code == 1 and "1 behind, 0 ahead - BEHIND" in out


def test_fresh_up_to_date_and_no_remote(repo):
    repo.write("a.txt").commit()
    code, out = repo.kz("fresh")
    assert code == 0 and "no origin/main" in out
    repo.mark_main().write("b.txt").commit()
    code, out = repo.kz("fresh")
    assert code == 0 and "0 behind, 1 ahead - up to date" in out


# --- brief ---------------------------------------------------------------

def _brief_repo(repo):
    repo.write(".kohaerenz.yaml", "adapters:\n  - {name: nextjs-app, app_dir: web/app}\n")
    repo.write("web/app/tasks/[id]/page.tsx", "x")
    repo.write("backend/services/dispatch.py", "def cooldown(): ...  # rule: R-cool\n")
    repo.write("backend/api/heads.py", "@router.get('/api/v1/heads/{id}')\n")
    repo.write(MAP, """\
        journeys:
          - {id: J-job, job: "hand off a job", steps: [{feature: F-result}, {feature: F-adopt, status: missing}]}
        features:
          - {id: F-result, name: "See the result", status: trial, ui: {route: "/tasks/[id]"}}
        """)
    repo.write(RULES, """\
        rules:
          - {id: R-cool, says: "warn at most every 5 min", owner: backend/services/dispatch.py, applies_to: ["backend/services/**"]}
          - {id: R-ui, says: "ui rule", owner: web/x.ts, applies_to: ["web/**"]}
        rejected:
          - {id: X-run-model, idea: "new run model", why: "three exist unused", keywords: [workflow, run model]}
          - {id: X-other, idea: "unrelated", why: "-", keywords: [blockchain]}
        dead:
          - {id: D-wf, paths: [backend/wf.py], retire_by: 2030-01-01}
        """)
    repo.write("docs/decisions/051-retire-workflows.md", "# Retire the workflow engine\n")
    repo.write("docs/decisions/010-theme.md", "# Dark theme\n")
    repo.commit()


def test_brief_shows_matching_context(repo):
    _brief_repo(repo)
    code, out = repo.kz("brief", "--paths", "backend/services/dispatch.py", "web/app/tasks/[id]/page.tsx",
                        "--text", "Add Workflows for GET /api/v1/heads/{id} using `cooldown`")
    assert code == 0
    assert "F-result [trial] See the result" in out and "(missing: F-adopt)" in out
    assert "R-cool [active]: warn at most every 5 min -> owner: backend/services/dispatch.py" in out
    assert "R-ui" in out  # the page path matches web/**
    assert "X-run-model" in out and "X-other" not in out
    assert "D-wf" in out
    assert "backend/api/heads.py:1" in out and "cooldown: backend/services/dispatch.py:1" in out
    assert "051-retire-workflows.md" in out and "010-theme" not in out


def test_brief_negative_and_capped(repo):
    _brief_repo(repo)
    code, out = repo.kz("brief", "--paths", "docs/readme.md", "--text", "fix a typo")
    assert "Rules for these paths: none" in out and "Rejected ideas matching the job text: none" in out
    assert "Features/journeys for these paths: none" in out
    many = "".join(f"  - {{id: X-{n}, idea: i, why: w, keywords: [typo]}}\n" for n in range(80))
    repo.write(RULES, "rejected:\n" + many).commit()
    code, out = repo.kz("brief", "--text", "fix a typo")
    lines = out.strip().splitlines()
    assert len(lines) == 60 and lines[-1].startswith("(+") and lines[-1].endswith("more)")


# --- scope ---------------------------------------------------------------

def test_scope_lists_anchors_deletions_and_features(repo):
    _brief_repo(repo)
    repo.write("other/util.py", "a\nb\nc\n").commit().mark_main()
    repo.write("backend/services/dispatch.py", "def cooldown(): ...\n").write("other/util.py", "a\n")
    repo.write("web/app/tasks/[id]/page.tsx", "y").commit()
    code, out = repo.kz("scope", "--paths", "backend/services")
    assert code == 0
    assert "removed R-cool in backend/services/dispatch.py" in out
    assert "other/util.py: 2 lines deleted" in out
    assert "web/app/tasks/[id]/page.tsx" in out and "Features touched: F-result" in out
    assert "Journeys touched: J-job" in out and "R-cool" in out


def test_scope_clean_diff(repo):
    _brief_repo(repo)
    repo.mark_main().write("README.md", "hi").commit()
    code, out = repo.kz("scope", "--paths", "README.md")
    assert code == 0
    assert "Rule anchors touched: none" in out and "Deletions outside the job paths: none" in out
    assert "Features touched: none" in out


def test_scope_without_base_is_usage_error(repo):
    repo.write("a").commit()
    assert repo.kz("scope")[0] == 2


# --- inventory -----------------------------------------------------------

FULL_CFG = """\
    adapters:
      - {name: nextjs-app, app_dir: web/src/app, src_dirs: [web/src]}
      - {name: fastapi, openapi: backend/openapi.json, model_dirs: [backend/models]}
    """


def test_inventory_reads_routes_features_endpoints_tables(repo):
    repo.write(".kohaerenz.yaml", FULL_CFG)
    repo.write("web/src/app/page.tsx", "x").write("web/src/app/(shop)/cart/page.tsx", "x")
    repo.write("web/src/app/tasks/[id]/page.tsx", "x").write("web/src/app/tasks/layout.tsx", "x")
    repo.write("web/src/components/Btn.tsx", '<button data-feature="head-result">')
    repo.write("backend/openapi.json", json.dumps({"paths": {"/api/v1/x": {"get": {}, "post": {}, "parameters": []}}}))
    repo.write("backend/models/m.py", """\
        class Task(SQLModel, table=True):
            id: int
        class TaskRead(SQLModel):
            id: int
        class Board(Base):
            __tablename__ = "boards"
        class Agent(SQLModel, table=True):
            __tablename__: str = "agent_rows"
        """).commit()
    code, out = repo.kz("inventory", "--json")
    inv = json.loads(out)
    assert inv["routes"] == ["/", "/cart", "/tasks/[id]"]
    assert inv["data_features"] == ["head-result"]
    assert inv["endpoints"] == ["GET /api/v1/x", "POST /api/v1/x"]
    assert inv["tables"] == ["agent_rows", "boards", "task"]


def test_inventory_missing_openapi_and_generic(repo):
    repo.write(".kohaerenz.yaml", FULL_CFG).write("web/src/app/page.tsx", "x").commit()
    code, out = repo.kz("inventory")
    assert code == 0 and "no OpenAPI file at 'backend/openapi.json'" in out and "model dir 'backend/models' not found" in out
    assert "1 routes" in out and "endpoints" not in out.split("inventory:")[-1]
    repo.write(".kohaerenz.yaml", "adapters: []\n").commit()
    assert "no inventory adapter configured" in repo.kz("inventory")[1]


def test_inventory_write_is_deterministic(repo):
    repo.write(".kohaerenz.yaml", FULL_CFG).write("web/src/app/b/page.tsx", "x").write("web/src/app/a/page.tsx", "x").commit()
    repo.kz("inventory", "--write")
    first = (repo.path / "docs/produkt/inventar.json").read_text()
    repo.kz("inventory", "--write")
    assert first == (repo.path / "docs/produkt/inventar.json").read_text()
    assert json.loads(first)["routes"] == ["/a", "/b"]


# --- init ----------------------------------------------------------------

def test_init_creates_stage_files_and_never_overwrites(repo):
    repo.write("AGENTS.md", "# mine\n").commit()
    code, out = repo.kz("init", "--stufe", "2", "--typ", "fastapi")
    assert code == 0 and "kept     AGENTS.md" in out
    assert (repo.path / "AGENTS.md").read_text() == "# mine\n"
    for rel in (".kohaerenz.yaml", "CLAUDE.md", MAP, RULES, "docs/produkt/luecken-basis.json"):
        assert (repo.path / rel).is_file(), rel
    assert "fastapi" in (repo.path / ".kohaerenz.yaml").read_text()
    assert "next     kz inventory --write" in out
    repo.commit()
    assert repo.kz("check")[0] == 2  # stage 2 needs a resolvable main branch
    repo.mark_main()
    assert repo.kz("check")[0] == 1  # stage 2 with adapter: inventory not written yet
    repo.kz("inventory", "--write")
    repo.commit()
    assert repo.kz("check")[0] == 0


def test_init_stage0_is_minimal(repo):
    repo.write("x").commit()
    repo.kz("init", "--stufe", "0", "--typ", "python-cli")
    assert (repo.path / "AGENTS.md").is_file() and not (repo.path / MAP).exists()
    repo.commit()
    assert repo.kz("links")[0] == 0 and repo.kz("check")[0] == 0


# --- config / usage errors -------------------------------------------------

def test_usage_and_config_errors_exit_2(repo, tmp_path):
    repo.write("a").commit()
    assert repo.kz("--config", str(tmp_path / "nope.yaml"), "fresh")[0] == 2
    repo.write(".kohaerenz.yaml", "adapters: [{name: django}]\n")
    assert repo.kz("fresh")[0] == 2
    repo.write(".kohaerenz.yaml", "adapters: [\n")
    assert repo.kz("fresh")[0] == 2
    repo.write(".kohaerenz.yaml", "")
    assert repo.kz("check", "--only", "nosuch")[0] == 2
    assert repo.kz("bogus")[0] == 2
    assert repo.kz("--version")[1].strip() == "kz 0.1.1"


def test_external_config_file(repo, tmp_path):
    repo.write("web/app/page.tsx", "x").commit()
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("adapters:\n  - {name: nextjs-app, app_dir: web/app}\n")
    code, out = repo.kz("--config", str(cfg), "inventory")
    assert code == 0 and "1 routes" in out

"""v0.1.2: glob patterns in landkarte entries, stale entries, multi-feature matches."""
import json
import re

MAP = "docs/produkt/landkarte.yaml"
CFG = """\
    adapters:
      - {name: nextjs-app, app_dir: web/app}
      - {name: fastapi, openapi: openapi.json, model_dirs: [models]}
    """
OPENAPI = {"paths": {"/api/v1/agent/{id}": {"get": {}, "delete": {}}, "/api/v1/agent": {"post": {}},
                     "/api/v1/internal/ping": {"get": {}}, "/api/v1/tasks": {"get": {}}}}


def keys(out):
    return sorted(m.group(1) for l in out.splitlines() if (m := re.match(r"NEW\s+(.+?)  ", l)))  # keys may contain spaces


def _tree(repo, landkarte):
    repo.write(".kohaerenz.yaml", CFG).write("openapi.json", json.dumps(OPENAPI))
    repo.write("web/app/agents/page.tsx", "x").write("web/app/agents/[id]/page.tsx", "x").write("web/app/tasks/[id]/page.tsx", "x")
    repo.write("models/m.py", "class Agent(SQLModel, table=True):\n    __tablename__ = 'agent_rows'\n"
                              "class AgentLog(SQLModel, table=True):\n    __tablename__ = 'agent_logs'\n"
                              "class Task(SQLModel, table=True):\n    id: int\n")
    repo.write(MAP, landkarte).commit()


def test_patterns_cover_items(repo):
    _tree(repo, """\
        features:
          - id: F-agents
            ui: {route: "/agents*"}
            api: ["* /api/v1/agent*"]
            tables: ["agent_*"]
          - id: F-tasks
            ui: {route: "/tasks/[id]"}
            api: ["GET /api/v1/tasks"]
            tables: [task]
        internal: ["endpoint:GET /api/v1/internal/*"]
        """)
    code, out = repo.kz("check", "--only", "map")
    assert code == 0, out


def test_uncovered_items_still_red_with_patterns(repo):
    _tree(repo, """\
        features:
          - {id: F-agents, ui: {route: "/agents"}, api: ["GET /api/v1/agent/*"], tables: ["agent_rows"]}
          - {id: F-tasks, ui: {route: "/tasks/[id]"}, api: ["GET /api/v1/tasks"], tables: [task]}
        internal: ["endpoint:* /api/v1/internal/*"]
        """)
    code, out = repo.kz("check", "--only", "map")
    assert code == 1 and keys(out) == [
        "map:endpoint:DELETE /api/v1/agent/{id}", "map:endpoint:POST /api/v1/agent",
        "map:route:/agents/[id]", "map:table:agent_logs"]


def test_stale_patterns_and_exact_refs_are_red(repo):
    _tree(repo, """\
        features:
          - id: F-all
            ui: {route: ["/agents*", "/tasks/[id]", "/gone", "/old/*"]}
            api: ["* /api/v1/*", "GET /api/v1/removed"]
            tables: ["*", "zombie_*"]
        """)
    code, out = repo.kz("check", "--only", "map")
    assert code == 1 and keys(out) == [
        "map:stale-pattern:route:/old/*", "map:stale-pattern:table:zombie_*",
        "map:stale-ref:endpoint:GET /api/v1/removed", "map:stale-ref:route:/gone"]


def test_no_stale_findings_for_kinds_without_inventory(repo):
    repo.write(".kohaerenz.yaml", "adapters: [{name: nextjs-app, app_dir: web/app}]\n").write("web/app/page.tsx", "x")
    repo.write(MAP, 'features:\n  - {id: F-a, ui: {route: "/"}, api: ["GET /nothing/*"], tables: [nope]}\n').commit()
    assert repo.kz("check", "--only", "map")[0] == 0


def test_brief_and_scope_list_all_features_matching_a_route_pattern(repo):
    _tree(repo, """\
        features:
          - {id: F-agents, ui: {route: "/agents/*"}}
          - {id: F-agent-detail, ui: {route: "/agents/[id]"}}
          - {id: F-tasks, ui: {route: "/tasks/*"}}
        """)
    code, out = repo.kz("brief", "--paths", "web/app/agents/[id]/page.tsx", "--text", "x")
    assert "F-agents" in out and "F-agent-detail" in out and "F-tasks" not in out
    repo.mark_main().write("web/app/agents/[id]/page.tsx", "y").commit()
    code, out = repo.kz("scope")
    assert "Features touched: F-agents, F-agent-detail" in out

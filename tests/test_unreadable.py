"""v0.1.3: unreadable files (sandbox denies stat/read) are skipped with a note - kz never crashes."""
import os
import pathlib

import pytest

CFG = "adapters:\n  - {name: nextjs-app, app_dir: web/app, src_dirs: [web]}\n  - {name: fastapi, model_dirs: [models]}\n"
MAP = "docs/produkt/landkarte.yaml"


def _tree(repo):
    repo.write(".kohaerenz.yaml", CFG)
    repo.write(".env.example", "KEY=x\n")
    repo.write("AGENTS.md", "Copy `.env.example` and read `docs/decisions/051-x.md`.\n")
    repo.write("web/app/page.tsx", '<b data-feature="home"/>').write("web/app/.env.local.tsx", "x")
    repo.write("models/m.py", "class Task(SQLModel, table=True):\n    id: int\n")
    repo.write("tests/test_secret.py", "def test_x(): pass\n")
    repo.write("docs/decisions/051-x.md", "---\nretires: x\n---\n# X\n")
    repo.write("docs/produkt/regeln.yaml", 'rules:\n  - {id: R-a, enforced_by: [{test: "tests/test_secret.py::test_x"}]}\n')
    repo.write(MAP, 'features:\n  - {id: F-home, status: internal, ui: {route: "/", data_feature: home}, tables: [task]}\n')
    repo.commit()


LOCKED = [".env.example", "tests/test_secret.py", "docs/decisions/051-x.md", "models/m.py"]


@pytest.fixture
def locked(repo):
    _tree(repo)
    for rel in LOCKED:
        os.chmod(repo.path / rel, 0)
    yield repo
    for rel in LOCKED:
        os.chmod(repo.path / rel, 0o644)


def _no_crash(repo, *args):
    code, out = repo.kz(*args)
    assert code in (0, 1) and "Traceback" not in out, out
    return code, out


def test_chmod_000_files_are_skipped_not_fatal(locked):
    code, out = _no_crash(locked, "check", "--only", "links,rules,adr,orphans,timebomb")
    assert code == 0, out  # unreadable is not "missing", not a failed guard
    assert "unreadable" in out
    code, out = _no_crash(locked, "links")
    assert code == 0 and "skipped" in out and "unreadable" in out
    code, out = _no_crash(locked, "inventory", "--json")
    assert '"routes"' in out and "unreadable" in out
    _no_crash(locked, "brief", "--paths", ".env.example", "--text", "touch `.env.example` and GET /x")


def test_check_json_lists_unreadable(locked):
    import json
    code, out = locked.kz("check", "--only", "links", "--json")
    data = json.loads(out[out.index("{"):out.rindex("}") + 1])
    assert ".env.example" in data["unreadable"]


def test_stat_and_open_raising_permission_error(repo, monkeypatch):
    _tree(repo)
    real_stat, real_open, real_os_stat = pathlib.Path.stat, pathlib.Path.open, os.stat

    def denied(p):
        return os.path.basename(str(p)).startswith(".env")

    def stat(self, *a, **k):
        if denied(self):
            raise PermissionError(13, "denied by sandbox", str(self))
        return real_stat(self, *a, **k)

    def open_(self, *a, **k):
        if denied(self):
            raise PermissionError(13, "denied by sandbox", str(self))
        return real_open(self, *a, **k)

    def os_stat(p, *a, **k):
        if denied(p):
            raise PermissionError(13, "denied by sandbox", str(p))
        return real_os_stat(p, *a, **k)

    monkeypatch.setattr(pathlib.Path, "stat", stat)
    monkeypatch.setattr(pathlib.Path, "open", open_)
    monkeypatch.setattr(os, "stat", os_stat)
    for args in (["check"], ["links"], ["inventory"], ["fresh"], ["scope"], ["brief", "--paths", ".env.example"]):
        code, out = repo.kz(*args)
        assert code in (0, 1, 2) and "Traceback" not in out, (args, out)
    code, out = _no_crash(repo, "check", "--only", "links,map")
    assert code == 0 and "unreadable" in out, out

"""v0.1.1: file walks only see what git sees (tracked + untracked-not-ignored), plus adapter excludes."""
import json

CFG = """\
    adapters:
      - {name: nextjs-app, app_dir: web/app, src_dirs: [web]%s}
      - {name: fastapi, model_dirs: [models]%s}
    """


def _inv(repo):
    code, out = repo.kz("inventory", "--json")
    assert code == 0, out
    return json.loads(out[out.index("{"):])


def _tree(repo, ex_next="", ex_api=""):
    repo.write(".kohaerenz.yaml", CFG % (ex_next, ex_api))
    repo.write(".gitignore", "web/app/private/\nmodels/local_*.py\nweb/overlay.tsx\n")
    repo.write("web/app/page.tsx", "x").write("web/app/private/page.tsx", "x")
    repo.write("web/app/lab/page.tsx", '<b data-feature="lab-btn"/>')
    repo.write("web/overlay.tsx", '<b data-feature="secret-btn"/>')
    repo.write("models/m.py", "class Task(SQLModel, table=True):\n    id: int\n")
    repo.write("models/local_x.py", "class Secret(SQLModel, table=True):\n    id: int\n")
    repo.write("models/scratch.py", "class Draft(SQLModel, table=True):\n    id: int\n")
    repo.commit()


def test_gitignored_files_are_not_in_inventory(repo):
    _tree(repo)
    repo.write("web/app/new/page.tsx", "x")  # untracked but not ignored -> visible
    inv = _inv(repo)
    assert inv["routes"] == ["/", "/lab", "/new"]
    assert inv["data_features"] == ["lab-btn"]
    assert inv["tables"] == ["draft", "task"]


def test_adapter_exclude_globs(repo):
    _tree(repo, ', exclude: ["web/app/lab/**"]', ', exclude: ["models/scratch.py"]')
    inv = _inv(repo)
    assert inv["routes"] == ["/"] and inv["data_features"] == [] and inv["tables"] == ["task"]


def test_exclude_must_be_a_list_of_strings(repo):
    repo.write(".kohaerenz.yaml", "adapters: [{name: nextjs-app, exclude: 5}]\n").commit()
    code, out = repo.kz("inventory")
    assert code == 2 and "exclude must be a list" in out
    repo.write(".kohaerenz.yaml", "adapters: [{name: nextjs-app, exclude: ['web/**']}]\n").commit()
    assert repo.kz("inventory")[0] == 0


def test_links_ignore_gitignored_targets(repo):
    repo.write(".gitignore", "CLAUDE.local.md\nprivate/\n").write("CLAUDE.local.md", "x").write("private/notes.md", "x")
    repo.write("AGENTS.md", "Read `CLAUDE.local.md`, `notes.md` and `private/`.\n").commit()
    code, out = repo.kz("links")
    assert code == 1
    assert {l.split()[1] for l in out.splitlines() if l.startswith("RED")} == {
        "links:AGENTS.md:CLAUDE.local.md", "links:AGENTS.md:notes.md", "links:AGENTS.md:private/"}


def test_links_accept_visible_dirs_and_untracked_files(repo):
    repo.write("docs/a.md", "x").write("AGENTS.md", "See `docs/`, `new.md`.\n").commit()
    repo.write("new.md", "x")  # untracked, not ignored
    assert repo.kz("links")[0] == 0

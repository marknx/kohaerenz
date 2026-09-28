"""v0.1.4: the inventory is only built when a selected check needs it (map, generated)."""
import os

from kohaerenz import inventory


def _tree(repo):
    repo.write(".kohaerenz.yaml", "adapters: [{name: nextjs-app, app_dir: app}]\n")
    repo.write("app/page.tsx", '<b data-feature="x"/>').write("AGENTS.md", "See `app/page.tsx`.\n").commit()


def test_links_and_non_inventory_checks_do_not_build_inventory(repo, monkeypatch):
    _tree(repo)

    def boom(_repo):
        raise AssertionError("inventory built although no selected check needs it")

    monkeypatch.setattr(inventory, "build", boom)
    assert repo.kz("links")[0] == 0
    assert repo.kz("check", "--only", "links,orphans,states,timebomb,adr")[0] == 0


def test_inventory_checks_still_build_it(repo, monkeypatch):
    _tree(repo)
    calls = []
    real = inventory.build
    monkeypatch.setattr(inventory, "build", lambda r: calls.append(1) or real(r))
    code, out = repo.kz("check", "--only", "map")
    assert calls and code == 1 and "map:route:/" in out


def test_links_has_no_unreadable_note_for_page_files(repo):
    _tree(repo)
    os.chmod(repo.path / "app/page.tsx", 0)
    try:
        code, out = repo.kz("links")
    finally:
        os.chmod(repo.path / "app/page.tsx", 0o644)
    assert code == 0 and "unreadable" not in out, out

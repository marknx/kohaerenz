import contextlib
import io
import subprocess
import textwrap
from pathlib import Path

import pytest

from kohaerenz.cli import main


class TmpRepo:
    """A throwaway git repo; `mark_main()` makes origin/main point at HEAD."""

    def __init__(self, path: Path):
        self.path = path
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")
        self.git("config", "core.hooksPath", ".git/no-hooks")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.path, check=True, capture_output=True, text=True).stdout

    def write(self, rel: str, text: str = "") -> "TmpRepo":
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8")
        return self

    def rm(self, rel: str) -> "TmpRepo":
        (self.path / rel).unlink()
        return self

    def commit(self, msg: str = "change") -> "TmpRepo":
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self

    def mark_main(self) -> "TmpRepo":
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        return self

    def kz(self, *args: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(["-C", str(self.path), *args])
            except SystemExit as exc:  # argparse
                code = exc.code
        return code, out.getvalue() + err.getvalue()


@pytest.fixture
def repo(tmp_path) -> TmpRepo:
    return TmpRepo(tmp_path / "proj")

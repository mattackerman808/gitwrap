import subprocess

import pytest

from gitwrap.cli import main


@pytest.fixture
def isolated_git(monkeypatch, tmp_path):
    """Make git ignore the user's/system config so tests are reproducible."""
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "empty-gitconfig"))
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")


@pytest.fixture
def repo(isolated_git, tmp_path, monkeypatch):
    """A fresh repository with one commit, used as the current directory."""
    path = tmp_path / "repo"
    path.mkdir()
    monkeypatch.chdir(path)
    git("init", "-q", "-b", "main")
    (path / "tracked.txt").write_text("v1\n")
    git("add", "tracked.txt")
    git("commit", "-q", "-m", "initial")
    return path


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def run(capsys):
    """Run the CLI in-process; return (exit_code, stdout, stderr)."""
    def _run(*argv):
        try:
            code = main(list(argv))
        except SystemExit as exc:  # argparse usage errors / --help
            code = exc.code
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    return _run

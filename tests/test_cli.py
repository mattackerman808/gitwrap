"""End-to-end tests against real, throwaway git repositories."""

import io
import sys

import pytest
import yaml

from conftest import git
from gitwrap import clean


class FakeTerminal(io.StringIO):
    """stdin that claims to be a TTY and answers the prompt with `answer`."""

    def isatty(self):
        return True


def answer_prompt(monkeypatch, answer):
    monkeypatch.setattr(sys, "stdin", FakeTerminal(answer))


def make_untracked(repo, *names):
    for name in names:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("junk\n")


# --- status ---------------------------------------------------------------

def test_status_reports_each_category(repo, run):
    (repo / "tracked.txt").write_text("v2\n")
    make_untracked(repo, "staged.txt", "notes.md")
    git("add", "staged.txt")
    code, out, _ = run("status")
    assert code == 0
    assert yaml.safe_load(out) == {
        "action": "status", "branch": "main",
        "staged_files": ["staged.txt"],
        "unstaged_files": ["tracked.txt"],
        "untracked_files": ["notes.md"],
    }


def test_status_on_clean_repo_omits_empty_lists(repo, run):
    assert run("status")[1] == "action: status\nbranch: main\n"


def test_status_detached_head(repo, run):
    git("checkout", "-q", "--detach")
    data = yaml.safe_load(run("status")[1])
    assert data["branch"] is None
    assert len(data["detached_at"]) == 40


def test_status_dry_run_is_flagged(repo, run):
    for argv in (["status", "--dry-run"], ["--dry-run", "status"]):
        assert yaml.safe_load(run(*argv)[1])["dry_run"] is True


# --- clean ----------------------------------------------------------------

def test_clean_dry_run_lists_but_deletes_nothing(repo, run):
    make_untracked(repo, "tmp/debug.log", "stray.txt")
    code, out, _ = run("clean", "--dry-run")
    assert code == 0
    assert yaml.safe_load(out) == {"dry_run": True, "action": "clean",
                                   "files": ["stray.txt", "tmp/"]}
    assert (repo / "stray.txt").exists() and (repo / "tmp/debug.log").exists()


def test_clean_with_yes_deletes_untracked_but_keeps_tracked_and_ignored(repo, run):
    (repo / ".gitignore").write_text("*.secret\n")
    git("add", ".gitignore")
    git("commit", "-q", "-m", "ignore")
    make_untracked(repo, "stray.txt", "build/out.o", "keys.secret")
    code, out, _ = run("clean", "--yes")
    assert code == 0
    assert yaml.safe_load(out)["files"] == ["build/", "stray.txt"]
    assert not (repo / "stray.txt").exists() and not (repo / "build").exists()
    assert (repo / "tracked.txt").exists() and (repo / "keys.secret").exists()


def test_clean_prompt_yes_deletes(repo, run, monkeypatch):
    make_untracked(repo, "a.txt")
    answer_prompt(monkeypatch, "y\n")
    code, _, err = run("clean")
    assert code == 0
    assert "This will delete 1 untracked file. Continue? [y/N]:" in err
    assert not (repo / "a.txt").exists()


@pytest.mark.parametrize("answer", ["n\n", "\n", "", "yolo\n"])
def test_clean_prompt_anything_but_yes_aborts(repo, run, monkeypatch, answer):
    make_untracked(repo, "a.txt")
    answer_prompt(monkeypatch, answer)
    code, out, err = run("clean")
    assert code == 1 and out == "" and "aborted" in err
    assert (repo / "a.txt").exists()


def test_clean_refuses_without_tty_or_yes(repo, run, monkeypatch):
    make_untracked(repo, "a.txt")
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))  # piped "y" is not consent
    code, _, err = run("clean")
    assert code == 1 and "--yes" in err
    assert (repo / "a.txt").exists()


def test_clean_with_nothing_to_do_does_not_prompt(repo, run):
    assert run("clean") == (0, "action: clean\n", "")


def test_clean_skips_nested_repositories(repo, run):
    nested = repo / "vendor"
    nested.mkdir()
    git("-C", str(nested), "init", "-q")
    make_untracked(repo, "vendor/important.txt", "stray.txt")
    assert yaml.safe_load(run("clean", "--yes")[1])["files"] == ["stray.txt"]
    assert (nested / "important.txt").exists()


def test_clean_reports_nested_repository_inside_untracked_directory(repo, run):
    """git prints `Would skip repository vendor/lib` here (found via the demo repo)."""
    nested = repo / "vendor" / "lib"
    nested.mkdir(parents=True)
    git("-C", str(nested), "init", "-q")
    make_untracked(repo, "vendor/lib/important.txt", "stray.txt")
    code, out, _ = run("clean", "--yes")
    assert code == 0
    assert yaml.safe_load(out) == {"action": "clean", "files": ["stray.txt"],
                                   "skipped_repositories": ["vendor/lib"]}
    assert (nested / "important.txt").exists()


def test_clean_only_affects_current_directory(repo, run, monkeypatch):
    make_untracked(repo, "top.txt", "sub/inner.txt")
    (repo / "sub" / "keep.txt").write_text("x")
    git("add", "sub/keep.txt")
    monkeypatch.chdir(repo / "sub")
    assert yaml.safe_load(run("clean", "--yes")[1])["files"] == ["inner.txt"]
    assert (repo / "top.txt").exists()


def test_clean_handles_hostile_file_names(repo, run):
    names = ["-rf", "a b.txt", "yes", "#x.txt", "ü.txt", "[ab].txt"]
    if sys.platform != "win32":  # characters Windows does not allow in file names
        names += ["a: b.txt", "*star", 'say "hi"', "new\nline", "tab\there"]
    make_untracked(repo, *names)
    files = yaml.safe_load(run("clean", "--yes")[1])["files"]
    assert sorted(files) == sorted(names)
    assert not any((repo / n).exists() for n in names)


def test_execute_deletes_only_planned_paths(repo):
    """Files appearing after the plan (e.g. while the prompt is open) survive,
    even when a planned name like `[ab].txt` would glob-match them."""
    make_untracked(repo, "[ab].txt")
    planned = clean.plan_clean()
    make_untracked(repo, "a.txt", "late.txt")
    clean.execute_clean(planned.remove)
    assert not (repo / "[ab].txt").exists()
    assert (repo / "a.txt").exists() and (repo / "late.txt").exists()


# --- errors and usage -----------------------------------------------------

def test_outside_a_repository_is_an_error(isolated_git, tmp_path, monkeypatch, run):
    monkeypatch.chdir(tmp_path)
    code, out, err = run("status")
    assert code == 1 and out == "" and "not inside a git working tree" in err


def test_missing_git_binary_is_a_clear_error(repo, run, monkeypatch):
    monkeypatch.setenv("PATH", "")
    code, _, err = run("status")
    assert code == 1 and "git executable not found" in err


@pytest.mark.parametrize("argv", [[], ["bogus"], ["status", "--yes"], ["clean", "--nope"]])
def test_usage_errors_exit_2(argv, run):
    assert run(*argv)[0] == 2

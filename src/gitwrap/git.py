"""Thin, strict layer over the git executable.

Everything that touches a subprocess lives here, so the rest of the code can
work with plain data and be unit-tested without git installed.
"""

import os
import subprocess

# Force untranslated messages: `git clean -n` prints human text ("Would
# remove ...") that we parse, and it is localised. GIT_OPTIONAL_LOCKS=0 stops
# read-only commands like `status` from taking the index lock.
_GIT_ENV_OVERRIDES = {"LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"}


class GitError(Exception):
    """A git command could not be run or exited non-zero."""


class GitNotFoundError(GitError):
    pass


class NotARepositoryError(GitError):
    pass


def run_git(args, cwd=None):
    """Run `git <args>` and return raw stdout bytes; raise GitError on failure."""
    env = {**os.environ, **_GIT_ENV_OVERRIDES}
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        raise GitNotFoundError(
            "git executable not found; install git and make sure it is on PATH"
        ) from None
    if result.returncode != 0:
        stderr = decode(result.stderr).strip()
        raise GitError(f"`git {' '.join(args)}` failed ({result.returncode}): {stderr}")
    return result.stdout


def decode(raw):
    """Decode git output. surrogateescape keeps non-UTF-8 bytes round-trippable."""
    return raw.decode("utf-8", errors="surrogateescape")


def ensure_work_tree(cwd=None):
    """Raise NotARepositoryError unless cwd is inside a git working tree."""
    try:
        inside = decode(run_git(["rev-parse", "--is-inside-work-tree"], cwd)).strip()
    except GitNotFoundError:
        raise
    except GitError as exc:
        raise NotARepositoryError(f"not inside a git working tree: {exc}") from None
    if inside != "true":  # e.g. inside a bare repo or the .git directory
        raise NotARepositoryError("not inside a git working tree")

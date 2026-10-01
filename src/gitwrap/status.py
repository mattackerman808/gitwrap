"""`gitwrap status`: parse `git status --porcelain=v2` into categories.

Porcelain v2 is git's stable, machine-readable format. With -z, records are
NUL-terminated and paths are never quoted, so spaces, newlines and unicode in
file names need no special handling.
See: https://git-scm.com/docs/git-status#_porcelain_format_version_2
"""

from dataclasses import dataclass, field

from gitwrap.git import decode, run_git

STATUS_ARGS = ["status", "--porcelain=v2", "--branch", "-z"]

# Number of space-separated fields before the path, per record type.
_FIELDS_BEFORE_PATH = {"1": 8, "2": 9, "u": 10}


@dataclass
class Status:
    branch: str = None          # None when HEAD is detached
    head_commit: str = None     # commit sha, or None before the first commit
    staged: list = field(default_factory=list)
    unstaged: list = field(default_factory=list)
    untracked: list = field(default_factory=list)
    conflicted: list = field(default_factory=list)


def get_status(cwd=None):
    return parse_porcelain_v2(run_git(STATUS_ARGS, cwd))


def parse_porcelain_v2(raw):
    """Parse NUL-separated `git status --porcelain=v2 --branch -z` output."""
    status = Status()
    records = decode(raw).split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        kind = record[0]
        if kind == "#":
            _apply_header(status, record)
        elif kind in ("?", "!"):
            if kind == "?":
                status.untracked.append(record[2:])
        elif kind in _FIELDS_BEFORE_PATH:
            _apply_change(status, record)
            if kind == "2":
                index += 1  # renames/copies are followed by the original path
        else:
            raise ValueError(f"unrecognised git status record: {record!r}")
    return status


def _apply_header(status, record):
    key, _, value = record[2:].partition(" ")
    if key == "branch.head":
        status.branch = None if value == "(detached)" else value
    elif key == "branch.oid":
        status.head_commit = None if value == "(initial)" else value


def _apply_change(status, record):
    kind = record[0]
    parts = record.split(" ", _FIELDS_BEFORE_PATH[kind])
    xy, path = parts[1], parts[-1]
    if kind == "u":
        status.conflicted.append(path)
        return
    index_state, worktree_state = xy
    if index_state != ".":
        status.staged.append(path)
    if worktree_state != ".":
        status.unstaged.append(path)


def status_report(status):
    """Build the ordered dict that is rendered as YAML."""
    report = {"action": "status", "branch": status.branch}
    if status.branch is None and status.head_commit:
        report["detached_at"] = status.head_commit
    report["staged_files"] = status.staged
    report["unstaged_files"] = status.unstaged
    report["untracked_files"] = status.untracked
    report["conflicted_files"] = status.conflicted
    return report

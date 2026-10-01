import pytest

from gitwrap.status import Status, parse_porcelain_v2, status_report

OID = "a" * 40
HEADER = f"# branch.oid {OID}\0# branch.head main\0".encode()


def entry(xy, path):
    return f"1 {xy} N... 100644 100644 100644 {OID} {OID} {path}\0".encode()


def test_categorises_staged_unstaged_and_untracked():
    raw = HEADER + entry("A.", "src/app.js") + entry(".M", "README.md") + b"? notes.md\0"
    status = parse_porcelain_v2(raw)
    assert status.branch == "main"
    assert status.staged == ["src/app.js"]
    assert status.unstaged == ["README.md"]
    assert status.untracked == ["notes.md"]


def test_file_modified_in_index_and_worktree_is_in_both_lists():
    status = parse_porcelain_v2(HEADER + entry("MM", "both.txt"))
    assert status.staged == ["both.txt"]
    assert status.unstaged == ["both.txt"]


def test_paths_with_spaces_and_unicode_are_kept_intact():
    raw = HEADER + entry(".M", "my file ü.txt") + b"? dir with space/\0"
    status = parse_porcelain_v2(raw)
    assert status.unstaged == ["my file ü.txt"]
    assert status.untracked == ["dir with space/"]


def test_rename_uses_new_path_and_skips_original_path_record():
    rename = f"2 R. N... 100644 100644 100644 {OID} {OID} R100 new name.txt\0old.txt\0"
    status = parse_porcelain_v2(HEADER + rename.encode() + b"? other\0")
    assert status.staged == ["new name.txt"]
    assert status.untracked == ["other"]  # "old.txt" was not misread as a record


def test_unmerged_entries_are_conflicted():
    conflict = f"u UU N... 100644 100644 100644 100644 {OID} {OID} {OID} merge.txt\0"
    status = parse_porcelain_v2(HEADER + conflict.encode())
    assert status.conflicted == ["merge.txt"]
    assert status.staged == status.unstaged == []


def test_detached_head_and_initial_commit():
    detached = parse_porcelain_v2(f"# branch.oid {OID}\0# branch.head (detached)\0".encode())
    assert detached.branch is None and detached.head_commit == OID
    initial = parse_porcelain_v2(b"# branch.oid (initial)\0# branch.head main\0")
    assert initial.branch == "main" and initial.head_commit is None


def test_unknown_record_type_is_an_error_not_silently_ignored():
    with pytest.raises(ValueError):
        parse_porcelain_v2(HEADER + b"Z something\0")


def test_report_key_order_and_detached_info():
    report = status_report(Status(branch=None, head_commit=OID, staged=["a"]))
    assert list(report) == ["action", "branch", "detached_at", "staged_files",
                            "unstaged_files", "untracked_files", "conflicted_files"]
    assert report["detached_at"] == OID

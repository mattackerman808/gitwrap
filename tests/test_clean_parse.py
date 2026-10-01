import pytest

from gitwrap.clean import _batches, describe, parse_clean_preview, unquote_c_style


def test_parses_would_remove_lines():
    text = "Would remove tmp/debug.log\nWould remove out/\nWould remove a b.txt\n"
    assert parse_clean_preview(text) == ["tmp/debug.log", "out/", "a b.txt"]


def test_empty_preview_means_nothing_to_clean():
    assert parse_clean_preview("") == []


def test_unexpected_output_is_an_error():
    with pytest.raises(ValueError):
        parse_clean_preview("Would remove a\nSomething new from git\n")


@pytest.mark.parametrize("quoted, expected", [
    ('plain.txt', 'plain.txt'),
    ('"\\303\\274.txt"', 'ü.txt'),        # UTF-8 bytes as octal
    ('"say \\"hi\\".txt"', 'say "hi".txt'),    # escaped quotes
    ('"tab\\there"', 'tab\there'),
    ('"new\\nline"', 'new\nline'),
    ('"back\\\\slash"', 'back\\slash'),
])
def test_unquote_c_style(quoted, expected):
    assert unquote_c_style(quoted) == expected


def test_describe_counts_files_and_directories():
    assert describe(["a"]) == "1 untracked file"
    assert describe(["a", "b", "c/", "d"]) == "3 untracked files and 1 directory"
    assert describe(["x/", "y/"]) == "0 untracked files and 2 directories"


def test_batches_split_long_argument_lists_without_losing_paths():
    paths = [f"dir/{i:05d}-{'x' * 100}.txt" for i in range(500)]
    batches = list(_batches(paths))
    assert len(batches) > 1
    assert [p for batch in batches for p in batch] == paths

import yaml

from gitwrap.output import render

# File names that break naive YAML generation.
HOSTILE_NAMES = ["yes", "no", "null", "123", "a: b", "#comment", "- dash", "[x]",
                 "{y}", "*star", "&anchor", "!tag", "'single'", '"double"',
                 "trailing space ", "new\nline", "tab\there", "ü日本", "%percent"]


def test_matches_spec_layout():
    out = render({"action": "clean", "files": ["tmp/debug.log", "out/old-build.tar"]},
                 dry_run=True)
    assert out == ("dry_run: true\n"
                   "action: clean\n"
                   "files:\n"
                   "  - tmp/debug.log\n"
                   "  - out/old-build.tar\n")


def test_empty_lists_are_omitted():
    out = render({"action": "status", "branch": "main", "staged_files": []})
    assert out == "action: status\nbranch: main\n"


def test_hostile_file_names_round_trip_through_a_yaml_parser():
    out = render({"action": "clean", "files": HOSTILE_NAMES})
    assert yaml.safe_load(out)["files"] == HOSTILE_NAMES


def test_undecodable_bytes_are_replaced_not_crashing():
    name = b"bad\xff.txt".decode("utf-8", errors="surrogateescape")
    assert yaml.safe_load(render({"files": [name]}))["files"] == ["bad�.txt"]

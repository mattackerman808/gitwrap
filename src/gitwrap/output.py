"""YAML rendering.

We never build YAML by hand: PyYAML's safe_dump quotes anything that needs it
(`yes`, `a: b`, `#x`, `- leading dash`, newlines, ...), so any file name
round-trips through a standard YAML parser.
"""

import yaml


class _IndentedListDumper(yaml.SafeDumper):
    """Indent list items under their key (`files:\\n  - a`), matching the spec."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def render(report, dry_run=False):
    """Render a report dict as YAML. Empty lists are omitted; key order kept."""
    data = {"dry_run": True} if dry_run else {}
    for key, value in report.items():
        if isinstance(value, list):
            if not value:
                continue
            value = [_printable(item) for item in value]
        data[key] = value
    return yaml.dump(
        data,
        Dumper=_IndentedListDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def _printable(text):
    """Replace undecodable bytes (non-UTF-8 file names) with U+FFFD for output."""
    if isinstance(text, str):
        return text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
    return text

"""`gitwrap clean`: a two-phase wrapper around `git clean -fd`.

1. Plan:    ask git itself what it would remove (`git clean -n -d`). Using git
            as the source of truth means we inherit its exact rules (.gitignore,
            nested repositories are skipped, scope is the current directory).
2. Execute: delete exactly the planned paths and nothing else, by passing them
            as literal pathspecs. A file created between the prompt and the
            delete is therefore never removed by surprise.
"""

from dataclasses import dataclass, field

from gitwrap.git import decode, run_git

PREVIEW_ARGS = ["clean", "-n", "-d"]
_REMOVE_PREFIX = "Would remove "
# Printed for a nested repository inside an untracked directory. git keeps it
# (and the directories containing it); we report it but never delete it.
_SKIP_PREFIX = "Would skip repository "
# Stay well under the Windows command-line limit (~32k chars).
_MAX_ARGS_CHARS = 8000

_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13,
              '"': ord('"'), "\\": ord("\\")}


@dataclass
class CleanPlan:
    remove: list = field(default_factory=list)          # paths to delete
    skipped_repos: list = field(default_factory=list)   # nested repos git keeps


def plan_clean(cwd=None):
    """Return what `git clean -fd` would do, with paths relative to cwd."""
    return parse_clean_preview(decode(run_git(PREVIEW_ARGS, cwd)))


def parse_clean_preview(text):
    plan = CleanPlan()
    for line in text.splitlines():
        if not line:
            continue
        if line.startswith(_REMOVE_PREFIX):
            plan.remove.append(unquote_c_style(line[len(_REMOVE_PREFIX):]))
        elif line.startswith(_SKIP_PREFIX):
            plan.skipped_repos.append(unquote_c_style(line[len(_SKIP_PREFIX):]))
        else:
            raise ValueError(f"unexpected `git clean -n` output: {line!r}")
    return plan


def unquote_c_style(text):
    """Undo git's C-style path quoting, e.g. "\\303\\274.txt" -> "ü.txt".

    git quotes a path (wraps it in double quotes) only when it contains
    special characters, so an unquoted path never starts with a quote.
    """
    if len(text) < 2 or not (text.startswith('"') and text.endswith('"')):
        return text
    body, out, i = text[1:-1], bytearray(), 0
    while i < len(body):
        if body[i] != "\\":
            out += body[i].encode("utf-8", errors="surrogateescape")
            i += 1
        elif body[i + 1] in "01234567":  # \ooo: one raw byte in octal
            out.append(int(body[i + 1:i + 4], 8))
            i += 4
        elif body[i + 1] in _C_ESCAPES:
            out.append(_C_ESCAPES[body[i + 1]])
            i += 2
        else:
            raise ValueError(f"unknown escape in quoted path: {text!r}")
    return decode(bytes(out))


def execute_clean(paths, cwd=None):
    """Delete exactly `paths`. --literal-pathspecs stops `[ab].txt` or `*`
    in a file name from being treated as a glob that matches other files."""
    for batch in _batches(paths):
        run_git(["--literal-pathspecs", "clean", "-f", "-d", "--", *batch], cwd)


def _batches(paths):
    batch, size = [], 0
    for path in paths:
        if batch and size + len(path) > _MAX_ARGS_CHARS:
            yield batch
            batch, size = [], 0
        batch.append(path)
        size += len(path) + 1
    if batch:
        yield batch


def describe(paths):
    """Human summary for the prompt, e.g. '3 untracked files and 1 directory'."""
    dirs = sum(1 for p in paths if p.endswith("/"))
    files = len(paths) - dirs
    summary = f"{files} untracked file{'' if files == 1 else 's'}"
    if dirs:
        summary += f" and {dirs} director{'y' if dirs == 1 else 'ies'}"
    return summary


def clean_report(plan):
    return {"action": "clean", "files": plan.remove,
            "skipped_repositories": plan.skipped_repos}

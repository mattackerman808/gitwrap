"""Command-line entry point: argument parsing, prompting and exit codes.

Conventions:
  * stdout carries only YAML, so it is always safe to pipe into a parser.
  * prompts, progress and errors go to stderr.
  * exit codes: 0 success, 1 error or aborted, 2 usage error (argparse).
"""

import argparse
import sys

from gitwrap import __version__
from gitwrap.clean import clean_report, describe, execute_clean, plan_clean
from gitwrap.git import GitError, ensure_work_tree
from gitwrap.output import render
from gitwrap.status import get_status, status_report

EXIT_OK, EXIT_ERROR = 0, 1
_MAX_PATHS_SHOWN = 20


def build_parser():
    # --dry-run is defined on both the top-level parser and each subcommand, so
    # `gitwrap --dry-run clean` and `gitwrap clean --dry-run` both work.
    # SUPPRESS stops the subcommand's default from overwriting the global flag.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                        help="show what would happen as YAML; change nothing")

    parser = argparse.ArgumentParser(
        prog="gitwrap", parents=[common],
        description="A safer interface to common git commands, with YAML output.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    status = commands.add_parser(
        "status", parents=[common], help="show repository status as YAML",
        description="Show branch and staged/unstaged/untracked/conflicted files as YAML.")
    status.set_defaults(handler=run_status)

    clean = commands.add_parser(
        "clean", parents=[common], help="safely remove untracked files (git clean -fd)",
        description="Remove untracked files and directories under the current "
                    "directory, after confirmation. Ignored files and nested "
                    "repositories are never removed.")
    clean.add_argument("-y", "--yes", action="store_true",
                       help="do not prompt for confirmation")
    clean.set_defaults(handler=run_clean)
    return parser


def main(argv=None):
    _use_utf8_output()
    args = build_parser().parse_args(argv)  # exits with 2 on usage errors
    args.dry_run = getattr(args, "dry_run", False)
    try:
        ensure_work_tree()
        return args.handler(args)
    except (GitError, ValueError) as exc:
        _error(str(exc))
        return EXIT_ERROR
    except KeyboardInterrupt:
        _error("interrupted")
        return 130


def run_status(args):
    sys.stdout.write(render(status_report(get_status()), dry_run=args.dry_run))
    return EXIT_OK


def run_clean(args):
    paths = plan_clean()
    if args.dry_run or not paths:
        sys.stdout.write(render(clean_report(paths), dry_run=args.dry_run))
        return EXIT_OK
    if not args.yes:
        if not sys.stdin.isatty():
            _error("refusing to delete files without confirmation: stdin is not "
                   "a terminal. Re-run with --yes, or use --dry-run to preview.")
            return EXIT_ERROR
        if not confirm_deletion(paths):
            _error("aborted; nothing was deleted")
            return EXIT_ERROR
    execute_clean(paths)
    sys.stdout.write(render(clean_report(paths)))
    return EXIT_OK


def confirm_deletion(paths):
    """Show what will be deleted and ask. Anything but y/yes means no."""
    for path in paths[:_MAX_PATHS_SHOWN]:
        print(f"  {path}", file=sys.stderr)
    if len(paths) > _MAX_PATHS_SHOWN:
        print(f"  ... and {len(paths) - _MAX_PATHS_SHOWN} more", file=sys.stderr)
    sys.stderr.write(f"This will delete {describe(paths)}. Continue? [y/N]: ")
    sys.stderr.flush()
    answer = sys.stdin.readline()  # returns "" on EOF (Ctrl-D), treated as no
    return answer.strip().lower() in ("y", "yes")


def _error(message):
    print(f"gitwrap: error: {message}", file=sys.stderr)


def _use_utf8_output():
    """YAML is UTF-8; don't let a legacy console code page crash on file names."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")

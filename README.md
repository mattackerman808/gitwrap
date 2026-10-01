# gitwrap

A safer wrapper around common git commands, with a `--dry-run` mode and
machine-readable YAML output.

## Install & run

Requires Python 3.9+ and git.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[test]"
gitwrap --help
```

## Usage

```console
$ gitwrap status
action: status
branch: feature/new-ui
staged_files:
  - src/app.js
unstaged_files:
  - README.md
untracked_files:
  - notes.md

$ gitwrap clean --dry-run
dry_run: true
action: clean
files:
  - out/
  - tmp/debug.log

$ gitwrap clean
  out/
  tmp/debug.log
This will delete 1 untracked file and 1 directory. Continue? [y/N]: y
action: clean
files:
  - out/
  - tmp/debug.log

$ gitwrap clean --yes        # no prompt, for scripts
```

`--dry-run` works before or after the subcommand (`gitwrap --dry-run clean`
or `gitwrap clean --dry-run`).

| Exit code | Meaning                                                   |
|-----------|-----------------------------------------------------------|
| 0         | success                                                   |
| 1         | error (not a repo, git missing, git failed) or aborted    |
| 2         | usage error (unknown command or flag)                     |

## Tests

```bash
pytest
```

Unit tests cover the parsers and YAML rendering using fixed input. Integration
tests (`tests/test_cli.py`) create real throwaway repositories in a temp
directory with the user's git config isolated, so results don't depend on the
machine.

## Layout

```
src/gitwrap/
  cli.py      argument parsing, prompting, exit codes   (the only module that talks to the user)
  git.py      runs git, turns failures into exceptions  (the only module that runs subprocesses)
  status.py   parses `git status --porcelain=v2`        (pure functions + one git call)
  clean.py    plans and executes `git clean`            (pure functions + git calls)
  output.py   renders reports as YAML
```

Each command is split into **get data → build a report dict → render**, so the
parsing and report logic is plain data in and out and can be unit-tested
without git.

## Design decisions

**Machine-readable git output, never the human output.** `status` parses
`git status --porcelain=v2 -z`, git's stable scripting format. With `-z`
records are NUL-separated and paths are never quoted, so spaces, newlines and
unicode in file names don't need special handling.

**git decides what `clean` deletes.** The list of files comes from
`git clean -n -d` rather than from re-implementing the rules (e.g. via
`git ls-files`). That way gitwrap matches git exactly: `.gitignore`d files are
kept, nested repositories are skipped (`git status` lists them as untracked but
`git clean -d` won't remove them), and scope is the current directory, the same
as `git clean`. That output is plain text, so git is run with `LC_ALL=C` to
prevent translated messages, and its C-style path quoting
(`"\303\274.txt"` → `ü.txt`) is decoded.

**Delete exactly what was shown.** After confirmation, gitwrap runs
`git --literal-pathspecs clean -fd -- <the listed paths>` instead of a bare
`git clean -fd`. A file created while the prompt is open is not deleted, and
a file named `[ab].txt` can't be read as a pattern that also matches `a.txt`.
Long path lists are split into batches to stay under OS command-line limits.

**Fail safe when there is no one to ask.** If stdin isn't a terminal and `--yes`
wasn't given, `clean` refuses (exit 1) instead of hanging or reading a piped
`y`. Anything other than `y`/`yes`, including Enter or Ctrl-D, means no.

**stdout is only YAML.** Prompts, the file preview and errors go to stderr, so
`gitwrap clean --dry-run | yq ...` always gets valid YAML.

**YAML is produced by a library, not string formatting.** PyYAML handles the
quoting needed for names like `yes`, `null`, `a: b`, `#x` or `- x`. Tests
check that these names survive a round trip through a YAML parser. Lists are
indented to match the spec, empty lists are omitted and key order is fixed.

**Errors are never swallowed.** A git command that fails raises with git's own
stderr included. Output in a format the parsers don't recognise causes an
error instead of being skipped.

## Edge cases handled

| Case | Behaviour |
|---|---|
| File staged *and* modified again (`MM`) | listed under both `staged_files` and `unstaged_files` |
| Rename / copy | new path listed as staged (the record for the original path is consumed correctly) |
| Merge conflicts | separate `conflicted_files` list |
| Detached HEAD | `branch: null` plus `detached_at: <sha>` |
| Repo with no commits | branch name reported normally |
| Not a repo / inside `.git` / bare repo | clear error, exit 1 |
| git not installed | clear error, exit 1 |
| Nothing to clean | no prompt, `action: clean`, exit 0 |
| Run from a subdirectory | `clean` only affects that directory (same as git) |
| Non-UTF-8 file names | handled internally without loss; shown with `�` in YAML |
| Non-UTF-8 terminal (e.g. Windows code pages) | output forced to UTF-8 |

## Known limitations / next steps

- If a new file appears *inside* an untracked directory that is being deleted
  (e.g. `tmp/`), it is deleted with the directory. Listing every file instead
  (`-uall`) would close this gap but makes output very long for things like
  `node_modules/`.
- `status` uses git's default untracked mode, which shows untracked
  directories as `dir/` rather than every file inside them.
- No `-x` (remove ignored files) or `-ff` (remove nested repos) on purpose.
  They would be added as explicit flags that also require confirmation.
- Further commands follow the same pattern: **plan (read-only) → render the
  plan as YAML → confirm → run exactly that plan.** For this git wrapper,
  `--dry-run` simply stops after rendering the plan.

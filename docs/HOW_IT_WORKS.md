# How gitwrap works

A walkthrough of the code in the order it runs when you type `gitwrap clean`,
with the reasoning behind each decision. For a shorter summary see
[Design decisions](../README.md#design-decisions) in the README.

**Overview:** every command does **get data from git in its machine-readable
format → turn it into plain data → render it as YAML**. Only `git.py` runs
processes and only `cli.py` talks to the user, so everything in between is pure
functions that are easy to test. Destructive commands add one more step:
**plan, show, confirm, then run exactly the plan.**

## Contents

1. [How `gitwrap` becomes a command: `pyproject.toml`](#1-how-gitwrap-becomes-a-command-pyprojecttoml)
2. [`__init__.py` and `__main__.py`](#2-__init__py-and-__main__py)
3. [`cli.py`: the only part that talks to the user](#3-clipy-the-only-part-that-talks-to-the-user)
4. [`git.py`: the only part that runs subprocesses](#4-gitpy-the-only-part-that-runs-subprocesses)
5. [`status.py`: parsing `git status`](#5-statuspy-parsing-git-status)
6. [`clean.py`: plan first, then delete](#6-cleanpy-plan-first-then-delete)
7. [`output.py`: writing YAML](#7-outputpy-writing-yaml)
8. [Tests](#8-tests)
9. [Release](#9-release)

## 1. How `gitwrap` becomes a command: `pyproject.toml`

This is the standard Python project file. Three parts matter:

- **`[project.scripts] gitwrap = "gitwrap.cli:main"`**: `pip install` creates a
  small `gitwrap` executable (`gitwrap.exe` on Windows) that calls `main()` in
  `cli.py`. That's the whole connection between the command name and the code.
- **`dependencies = ["PyYAML>=6.0"]`**: the only runtime dependency. pytest is
  listed separately under `[test]`, so normal users don't install it.
- **`dynamic = ["version"]`** with `version = { attr = "gitwrap.__version__" }`:
  the version is read from `__init__.py`, so it's stored in exactly one place.
  The release workflow relies on that.

The project uses the "src layout": code lives in `src/gitwrap/`, not at the
repo root. This forces tests to use the installed package, so a file missing
from packaging shows up as a failing test, not a broken release.

## 2. `__init__.py` and `__main__.py`

**`__init__.py`** marks `gitwrap` as a package and holds
`__version__ = "0.1.0"`, which `--version` prints and the release workflow
checks against the tag.

**`__main__.py`** makes `python -m gitwrap` work as well as the `gitwrap`
command. It calls `main()` and passes its return value to `sys.exit()`, so the
exit code reaches the shell.

## 3. `cli.py`: the only part that talks to the user

Three rules shape this module:

1. **stdout only ever contains YAML**, so piping to a parser can't break.
2. **Prompts, the file preview and errors go to stderr.**
3. **Exit codes:** 0 = success, 1 = error or aborted, 2 = usage error.

### `build_parser()`

This uses argparse from the standard library, with subcommands (`status`,
`clean`). `--dry-run` works on both sides of the command:

```python
common = argparse.ArgumentParser(add_help=False)
common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS, ...)
```

The `common` parser is attached to the top-level parser and to each
subcommand, so `gitwrap --dry-run clean` and `gitwrap clean --dry-run` both
work. The catch is that argparse lets the subcommand's default overwrite the
top-level value: `--dry-run` would be set at the top, then `clean` would reset
it to `False`. `default=argparse.SUPPRESS` means "don't set anything unless the
flag is actually given", so nothing gets overwritten. `main()` fills in `False`
if it was never given.

Each subcommand records its handler with `set_defaults(handler=run_status)`, so
`main()` doesn't need an if/elif on the command name. `--yes` exists only on
`clean`, so `gitwrap status --yes` is a usage error (exit 2).

### `main()`

```python
_use_utf8_output()
args = build_parser().parse_args(argv)     # bad args → argparse exits 2
try:
    ensure_work_tree()                     # every command needs a repo
    return args.handler(args)
except (GitError, ValueError) as exc:      # → "gitwrap: error: ..." exit 1
except KeyboardInterrupt:                  # Ctrl-C → exit 130 (Unix convention)
```

- **`_use_utf8_output()`**: when output is piped on Windows, Python uses the
  old Windows code page, which crashes on characters it can't represent.
  Forcing UTF-8 avoids that, and YAML is UTF-8 anyway.
- **`argv=None`**: by default it reads the real command line, but tests can
  pass a list and run the whole CLI in-process.
- All errors are caught in this one place. Lower modules raise exceptions and
  never print or exit themselves, which keeps them testable.

### `run_status()`

Get the status, build the report, render it as YAML, write it to stdout.
`--dry-run` only adds `dry_run: true`, because status never changes anything.

### `run_clean()`: the main safety logic

```python
paths = plan_clean()                         # ask git what it WOULD delete
if args.dry_run or not paths:                # dry-run, or nothing to do
    print YAML; return 0                     #   → never prompt
if not args.yes:
    if not sys.stdin.isatty():               # no human to ask
        error "...use --yes"; return 1
    if not confirm_deletion(paths):          # human said no
        error "aborted"; return 1
execute_clean(paths)                         # delete EXACTLY that list
print YAML; return 0
```

- **No prompt when there's nothing to delete**: asking "delete 0 files?" is
  pointless.
- **The `isatty()` check**: without it, `echo y | gitwrap clean` would count as
  consent, and a cron job with no terminal would hang or behave unpredictably.
  Refusing is the safe default; scripts must say `--yes` explicitly.
- **Declining exits with 1, not 0**, so a script can tell that nothing was
  deleted.

### `confirm_deletion()`

This prints up to 20 of the paths to stderr, then the prompt in the spec's
wording: `This will delete 3 untracked files and 1 directory. Continue? [y/N]:`.
It reads with `sys.stdin.readline()` instead of `input()`, because `input()`
writes its prompt to **stdout**, which would put text into the YAML stream.
`readline()` returns `""` on Ctrl-D, which counts as no. Only `y` or `yes`
count as yes; the capital N in `[y/N]` shows that no is the default.

## 4. `git.py`: the only part that runs subprocesses

### `run_git(args)`

```python
subprocess.run(["git", *args], env=env, stdin=DEVNULL, capture_output=True, check=False)
```

- **Arguments are passed as a list with no shell**, so a file name like
  `; rm -rf ~` is just a string. Shell injection isn't possible.
- **`stdin=DEVNULL`**: git can never stop and wait for input (a credential
  prompt, for example).
- **Environment overrides**:
  - `LC_ALL=C` forces English output. `git clean -n` prints "Would remove …",
    which is translated on, say, a German system, and the parser would break.
  - `GIT_OPTIONAL_LOCKS=0` stops `git status` from taking `.git/index.lock`.
    Otherwise a read-only status could make a concurrent `git commit` in
    another terminal fail.
- **`FileNotFoundError` becomes `GitNotFoundError`** with a clear message
  ("install git and make sure it is on PATH") instead of a Python traceback.
- **A non-zero exit becomes `GitError` including git's own stderr.** It returns
  raw **bytes**, and each caller decides how to decode them.

### `decode()`

`raw.decode("utf-8", errors="surrogateescape")`. On Linux a file name can be any
bytes, not only valid UTF-8. `surrogateescape` stores invalid bytes in a
reversible way, so a path can be read, kept and handed back to git without
changing. A strict decode would crash, and `errors="replace"` would change the
name, so `git clean` would be handed a path that doesn't exist.

### `ensure_work_tree()`

This runs `git rev-parse --is-inside-work-tree`. Outside a repo, git exits
non-zero, which becomes `NotARepositoryError`. Inside `.git/` or a bare repo,
it succeeds but prints `false`, so the code checks the text as well.
`GitNotFoundError` is re-raised first because it's a subclass of `GitError`;
otherwise "git isn't installed" would be misreported as "not a repo".

## 5. `status.py`: parsing `git status`

### Why porcelain v2 with `-z`

`git status --porcelain=v2 --branch -z` is git's format for scripts and is
stable across versions. With `-z`, records end with a NUL byte and **paths are
never quoted or escaped**. NUL is the one byte a file name can't contain, so
splitting on it is always correct. Spaces, newlines and unicode need no
special handling.

Example of the raw output (`\0` = NUL):

```
# branch.oid 4f2a…\0# branch.head main\0
1 .M N... 100644 100644 100644 abc… abc… README.md\0
2 R. N... 100644 100644 100644 abc… abc… R100 new.txt\0old.txt\0
u UU N... … merge.txt\0
? notes.md\0
```

### `parse_porcelain_v2()`

It splits on `\0` and loops through the records, using the first character to
tell what each one is:

| First char | Meaning | Handling |
|---|---|---|
| `#` | header | `branch.head` gives the branch (`(detached)` → `None`); `branch.oid` gives the commit (`(initial)` → `None`) |
| `1` | ordinary change | read the two status letters |
| `2` | rename/copy | same, then **skip the next record**, which is the old path |
| `u` | merge conflict | goes to `conflicted` |
| `?` | untracked | goes to `untracked` |
| `!` | ignored | dropped (only appears if asked for) |
| anything else | unknown | **`ValueError`**: fail loudly, never guess |

It uses a `while` loop with an index instead of `for`, because a rename has to
consume two records. Without the skip, `old.txt` would be read as a separate
record.

### `_apply_change()`

- **`split(" ", N)` with a maximum number of splits.** Each record type has a
  fixed number of fields before the path (8, 9 or 10, kept in
  `_FIELDS_BEFORE_PATH`). Limiting the split means everything after them,
  spaces included, stays together as the path. Splitting on every space would
  cut `my file.txt` in two.
- **The two status letters (`XY`)**: X is the index (staged), Y is the working
  tree (unstaged), and `.` means unchanged. They are checked **separately**, so
  a file that's staged and then edited again (`MM`) correctly appears in both
  lists.

### `Status` and `status_report()`

`Status` is a plain dataclass holding the parsed result. `status_report()`
turns it into a dict in a fixed key order. If HEAD is detached, it outputs
`branch: null` plus `detached_at: <sha>`; null is easier for scripts than a
made-up string like `"(detached)"`. Empty lists are left in the dict here;
dropping them is `output.py`'s job.

`parse_porcelain_v2` takes bytes and returns data, with no git or filesystem
involved. That's why the unit tests can feed it hand-written edge cases
(renames, conflicts, detached HEAD) without creating those situations in a
real repo.

## 6. `clean.py`: plan first, then delete

### Phase 1: `plan_clean()`, where git decides

It runs `git clean -n -d` (`-n` = dry run, `-d` = include directories) and
parses the result. The alternative would be to list untracked files directly
(e.g. `git ls-files --others`), but that disagrees with git: a nested
repository shows up in `git status` as `nested/`, yet `git clean -d` **won't
delete it**. Asking git means `.gitignore`, nested repos and the
current-directory scope all behave exactly as git does.

The cost is that `git clean -n` has no `-z` option, so it prints plain text,
which brings two problems:

- the message is translated → handled by `LC_ALL=C`;
- special file names are escaped → handled by `unquote_c_style`.

### `parse_clean_preview()`

Each line must start with `"Would remove "`. Anything else raises an error
instead of being skipped, the same "never guess" rule as `status.py`.

### `unquote_c_style()`

When a file name contains unusual characters, git prints it in quotes with
C-style escapes:

- `ü.txt` → `"\303\274.txt"` (the two UTF-8 bytes of ü, written in octal)
- `say "hi"` → `"say \"hi\""`, newline → `\n`, and so on

The function:

1. Returns the text unchanged unless it's wrapped in `"…"`. This is safe
   because git always quotes a name containing `"`, so an unquoted name never
   starts with one.
2. Walks the characters and builds a **byte array**: `\ooo` gives one byte,
   `\n` and the others use the `_C_ESCAPES` table, and ordinary characters are
   copied as is.
3. Decodes the bytes at the end. It has to work in bytes because `\303\274` is
   two bytes that together make one character; decoding each escape
   separately would produce garbage.

### Phase 2: `execute_clean()`, which deletes exactly the list

```
git --literal-pathspecs clean -f -d -- <every planned path>
```

It does **not** run a bare `git clean -fd`:

1. **Files created while the prompt is open.** You see 3 files and spend 30
   seconds deciding; meanwhile your build writes `important.log`. A bare
   `git clean -fd` would delete it even though you never saw it. Passing the
   exact list means only those paths go.
2. **`--literal-pathspecs`.** git treats paths as patterns by default, so a
   file literally named `[ab].txt` would also match `a.txt` and `b.txt`. This
   flag makes each path match only itself.
3. **`--`** marks the end of options, so a file named `-rf` is treated as a
   file, not a flag.

The test `test_execute_deletes_only_planned_paths` checks this: it plans with
`[ab].txt` present, then creates `a.txt` and `late.txt`, executes, and asserts
that both survive.

### `_batches()`

Windows limits a command line to about 32,000 characters. Cleaning thousands
of files in one call would fail, so the paths are split into groups of about
8,000 characters each. It's a generator (it uses `yield`), and a test checks
that no paths are lost.

### `describe()` and `clean_report()`

`describe()` builds the prompt text. Directory paths end in `/`, so they're
counted separately ("3 untracked files and 1 directory"), and plurals are
handled. `clean_report()` returns `{"action": "clean", "files": [...]}`, the
same shape for dry runs and real runs; only the `dry_run: true` line differs.

## 7. `output.py`: writing YAML

### `render(report, dry_run)`

1. Puts `dry_run: true` first if needed.
2. **Drops empty lists**, as the spec asks.
3. Cleans each path for display (`_printable`, below).
4. `yaml.dump(..., sort_keys=False)` keeps the key order as built, not
   alphabetical.

YAML is generated by a library rather than string formatting because YAML has
many traps:

- `yes`, `no`, `null` and `123` would be read back as a boolean, null or
  number;
- `a: b` looks like a mapping, and `#x` looks like a comment;
- `- x`, `[x]` and `*x` have special meanings, and so on.

PyYAML knows these rules and adds quotes where needed (`- 'yes'`).
`SafeDumper` also never writes Python-specific tags. The test
`test_hostile_file_names_round_trip_through_a_yaml_parser` writes about 20 such
names and checks that `yaml.safe_load` returns exactly the same names.

### `_IndentedListDumper`

PyYAML's default output is `files:\n- a`, while the spec shows
`files:\n  - a`. Both are valid YAML; this subclass overrides
`increase_indent` with `indentless=False` to match the spec.

### `_printable()`

The other half of `surrogateescape`: escaped invalid bytes can't be written as
YAML, so for **output only** they're replaced with `�`. The real path, used for
deleting, is never changed.

## 8. Tests

| File | Type | What it covers |
|---|---|---|
| `test_status_parse.py` | unit, made-up bytes | MM files, renames, conflicts, detached HEAD, spaces/unicode, unknown records |
| `test_clean_parse.py` | unit | "Would remove" parsing, all escape types, plural wording, batching |
| `test_output.py` | unit | exact spec layout, omitting empty lists, hostile names through a real YAML parser |
| `test_cli.py` | integration, real git | everything end to end in throwaway repos |

`conftest.py` holds the shared setup:

- **`isolated_git`** points git at an empty config, so the user's global
  `.gitconfig` (e.g. `autocrlf`, aliases, a different default branch) can't
  change results.
- **`repo`** creates a real repository in a temp directory with one commit and
  moves into it.
- **`run`** calls `main([...])` directly and captures stdout, stderr and the
  exit code. This is faster than starting a process and still exercises the
  whole CLI.

`test_cli.py` simulates a person at the terminal with `FakeTerminal`, a fake
stdin whose `isatty()` returns `True` and which supplies a scripted answer.
It checks that `y` deletes, and that `n`, Enter, Ctrl-D and `yolo` all abort.
A plain `StringIO("y\n")` (not a terminal) shows that piped input is refused.

## 9. Release

- **`.github/workflows/ci.yml`** runs the tests on {Linux, macOS, Windows} ×
  {Python 3.10, 3.13} on every push. Some file-name tests only run on
  macOS/Linux because Windows can't create those names, so CI is what covers
  them.
- **`.github/workflows/release.yml`** starts when a `v*` tag is pushed. It
  reruns all the tests (reusing `ci.yml`), refuses if the tag doesn't match
  `__version__`, builds the zip and publishes the GitHub Release.
- **`scripts/package.sh`** uses `git archive`, so the zip contains exactly
  what's committed, never a local `.venv` or uncommitted edits.
- **`.gitattributes`** keeps LF line endings in the repo and the zip, so files
  look the same on every OS.

#!/usr/bin/env bash
# Create a throwaway repository that shows off gitwrap's edge cases.
#
#   scripts/demo-repo.sh [path]      (default: ../gitwrap-demo)
#
# Re-running rebuilds it from scratch, so you can try `gitwrap clean` again.
set -euo pipefail

dir="${1:-../gitwrap-demo}"
marker=".gitwrap-demo"

if [ -e "$dir" ]; then
  if [ ! -e "$dir/$marker" ]; then
    echo "refusing to replace $dir: it was not created by this script" >&2
    exit 1
  fi
  rm -rf "$dir"
fi

mkdir -p "$dir"
cd "$dir"
git init -q -b feature/new-ui
commit() { git -c user.name=demo -c user.email=demo@example.com commit -q "$@"; }

# Tracked files, committed.
mkdir -p src styles
echo "console.log('v1')" > src/app.js
echo "body {}" > styles/main.css
echo "# Demo" > README.md
echo "*.secret" > .gitignore
echo "created by scripts/demo-repo.sh" > "$marker"
git add .
commit -m "initial"

# Staged changes.
echo "console.log('v2')" > src/app.js
echo "h1 {}" >> styles/main.css
git add src/app.js styles/main.css

# Staged *and* modified again: shows up in both lists.
echo "console.log('v3')" > src/app.js

# Unstaged change.
echo "More docs" >> README.md

# Untracked files and directories, including awkward names.
mkdir -p tmp out
echo "debug" > tmp/debug.log
echo "tar" > out/old-build.tar
echo "notes" > notes.md
echo "x" > "file with spaces.txt"
echo "x" > "yes"          # YAML would read an unquoted yes as true
echo "x" > "#not-a-comment.txt"
echo "x" > "[ab].txt"     # would glob-match a.txt without --literal-pathspecs
echo "x" > "-rf"          # looks like a flag
echo "x" > "ünïcödé.txt"

# Ignored: gitwrap clean must leave it alone.
echo "hunter2" > api.secret

# Nested repositories: git status shows them, git clean -d will not delete
# them. git names the inner one (vendor/lib) but skips the top-level one
# (scratch) silently; gitwrap reports both under skipped_repositories.
mkdir -p vendor/lib scratch
git -C vendor/lib init -q
echo "keep me" > vendor/lib/important.txt
git -C scratch init -q
echo "keep me too" > scratch/wip.txt

echo "demo repo ready: $(pwd)"

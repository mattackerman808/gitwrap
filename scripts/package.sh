#!/usr/bin/env bash
# Build dist/gitwrap-<ref>.zip from a git ref (default: HEAD) plus a checksum.
# Uses `git archive`, so the zip contains exactly the committed files: no
# virtualenvs, caches or uncommitted edits.
set -euo pipefail

ref="${1:-HEAD}"
name="gitwrap-${ref}"
mkdir -p dist
git archive --format=zip --prefix="${name}/" -o "dist/${name}.zip" "$ref"
(cd dist && sha256sum "${name}.zip" > "${name}.zip.sha256")
echo "built dist/${name}.zip"

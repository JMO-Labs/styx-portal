#!/usr/bin/env bash
# Apply patches/selkies/series to an installed site-packages dir, in order.
# Usage: apply_selkies_patches.sh <site-packages-dir>
# Env: SELKIES_PATCH_DIR (default: <repo>/patches/selkies)
set -euo pipefail

site="${1:?usage: $0 <site-packages-dir>}"
[ -d "$site" ] || { echo "not a directory: $site" >&2; exit 2; }
pdir="${SELKIES_PATCH_DIR:-$(cd "$(dirname "$0")/.." && pwd)/patches/selkies}"

while IFS= read -r name || [ -n "$name" ]; do
  case "$name" in ''|'#'*) continue ;; esac
  echo "applying $name"
  patch -p1 --forward -d "$site" -i "$pdir/$name" || { echo "patch failed: $name" >&2; exit 1; }
done < "$pdir/series"

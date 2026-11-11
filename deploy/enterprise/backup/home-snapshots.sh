#!/usr/bin/env bash
# Nightly CephFS snapshots of home/profile subvolumes (issue #38). Names are nightly-YYYY-MM-DD (UTC),
# the exact form offsite-export.sh (#13) reads. Prints only failed subvolume names, never key material.
set -euo pipefail

FS_NAME="${FS_NAME:?FS_NAME required}"
KEEP_DAILY="${KEEP_DAILY:-7}"
# GROUPS is a special bash variable (assignments are ignored), so read it from the environment.
SNAP_GROUPS="$(printenv GROUPS || true)"
TODAY="nightly-$(date -u +%F)"

if [[ -n "${MON_HOSTS:-}" && -r "${KEY_FILE:-}" ]]; then
  ring=/tmp/client.keyring
  (umask 077 && printf '[client.%s]\n    key = %s\n' "${CEPH_ID:-home-snapshots}" "$(cat "$KEY_FILE")" >"$ring")
  export CEPH_ARGS="--id ${CEPH_ID:-home-snapshots} --keyring $ring --mon-host ${MON_HOSTS}"
fi

names() { # JSON list from ceph on stdin -> one name per line
  { grep -o '"name": *"[^"]*"' || true; } | sed 's/.*: *"\(.*\)"/\1/'
}

snapshot_one() {
  local group="$1" sub="$2" existing nightly excess
  existing="$(ceph fs subvolume snapshot ls "$FS_NAME" "$sub" --group_name "$group" 2>/dev/null | names)" || return 1
  if ! grep -qx "$TODAY" <<<"$existing"; then
    ceph fs subvolume snapshot create "$FS_NAME" "$sub" "$TODAY" --group_name "$group" >/dev/null 2>&1 || return 1
    existing+=$'\n'"$TODAY"
  fi
  nightly="$(grep -E '^nightly-[0-9]{4}-[0-9]{2}-[0-9]{2}$' <<<"$existing" | sort -u || true)"
  excess="$(head -n "-${KEEP_DAILY}" <<<"$nightly" || true)"
  while read -r snap; do
    [[ -n "$snap" ]] || continue
    ceph fs subvolume snapshot rm "$FS_NAME" "$sub" "$snap" --group_name "$group" >/dev/null 2>&1 || return 1
  done <<<"$excess"
}

failed=()
for group in $SNAP_GROUPS; do
  subs="$(ceph fs subvolume ls "$FS_NAME" --group_name "$group" 2>/dev/null | names)" || { failed+=("group:$group"); continue; }
  while read -r sub; do
    [[ -n "$sub" ]] || continue
    snapshot_one "$group" "$sub" || failed+=("$group/$sub")
  done <<<"$subs"
done

if ((${#failed[@]})); then
  echo "snapshot failed: ${failed[*]}" >&2
  exit 1
fi

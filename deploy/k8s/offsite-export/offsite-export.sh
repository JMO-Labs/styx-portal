#!/bin/sh
# Offsite export of CephFS subvolume snapshots to a Kopia repository on S3 (issue #13).
# Usage: offsite-export.sh init|export|verify. Settings: params.env; secrets: env only.
# KOPIA_PASSWORD and AWS_* are read by kopia from the environment, never put on argv.
# Never add `set -x`: it traces every command line, so keep secrets off argv for good.
set -eu

die() { echo "offsite-export: $*" >&2; exit 1; }

check_env() {
  case "${OFFSITE_CIPHER:-}" in
    AES256-GCM-HMAC-SHA256|CHACHA20-POLY1305-HMAC-SHA256) ;;
    *) die "OFFSITE_CIPHER must be AES256-GCM-HMAC-SHA256 or CHACHA20-POLY1305-HMAC-SHA256" ;;
  esac
  [ -n "${KOPIA_PASSWORD:-}" ] || die "KOPIA_PASSWORD is not set"
  [ "${#KOPIA_PASSWORD}" -ge 32 ] || die "KOPIA_PASSWORD must be at least 32 characters"
}

# Fixed identity: pods get random hostnames, and Kopia ties maintenance ownership
# and snapshot sources to user@host.
ID="--override-username=styx --override-hostname=offsite"

kopia_s3() { # kopia_s3 <create|connect> [extra flags...]
  verb=$1; shift
  tls=""
  # Test-only switch (MinIO over plain HTTP in CI); keep false in every real deployment.
  if [ "${OFFSITE_S3_DISABLE_TLS:-false}" = "true" ]; then tls=--disable-tls; fi
  # shellcheck disable=SC2086 # $tls and $ID are intentionally word-split
  kopia repository "$verb" s3 --bucket="$OFFSITE_S3_BUCKET" --endpoint="$OFFSITE_S3_ENDPOINT" \
    --prefix="$OFFSITE_S3_PREFIX" --region="$OFFSITE_S3_REGION" $tls $ID "$@"
}

do_init() {
  if kopia_s3 connect >/dev/null 2>&1; then
    die "a repository already exists at the target; refusing to init"
  fi
  kopia_s3 create --encryption="$OFFSITE_CIPHER" \
    --retention-mode=COMPLIANCE --retention-period="${OFFSITE_LOCK_DAYS}d"
  kopia maintenance set --extend-object-locks=true
  kopia policy set --global --keep-daily="$OFFSITE_KEEP_DAILY" \
    --keep-weekly="$OFFSITE_KEEP_WEEKLY" --keep-monthly="$OFFSITE_KEEP_MONTHLY"
}

# Snapshot layout (CephFS subvolume v2): $ROOT/<group>/<subvol>/.snap/<prefix>YYYY-MM-DD/<uuid>.
# Calls `found <group dir> <subvol dir> <newest snap name or empty>` per subvolume.
# Adjust here only if #3/#9 settle on another layout or name scheme.
each_subvolume() {
  for sv in "$OFFSITE_SNAP_ROOT"/*/*/; do
    [ -d "$sv" ] || continue
    sv=${sv%/}
    group=${sv%/*}; group=${group##*/}
    case "$group" in
      _nogroup) ;;
      _*) continue ;; # mgr/volumes internals (_deleting, _index, _legacy)
    esac
    if [ -n "${OFFSITE_GROUPS:-}" ]; then
      case " $OFFSITE_GROUPS " in *" $group "*) ;; *) continue ;; esac
    fi
    newest=""
    for s in "$sv"/.snap/"$OFFSITE_SNAP_PREFIX"*; do
      name=${s##*/}
      d=${name#"$OFFSITE_SNAP_PREFIX"}
      case "$d" in
        [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
        *) continue ;;
      esac
      # A future or impossible date would be picked forever and mask staleness.
      [ "$(date -u -d "$d" +%Y-%m-%d 2>/dev/null)" = "$d" ] || continue
      [ "$(echo "$d" | tr -d -)" -le "$TODAY" ] || continue
      # Glob order is sorted and ISO dates sort lexically, so the last match is newest.
      newest=$name
    done
    found "${sv%/*}" "$sv" "$newest"
  done
}

found() { # found <group dir> <subvol dir> <snap name>
  gs="${1##*/}/${2##*/}"
  SEEN=$((SEEN + 1))
  if [ -z "$3" ]; then
    FAILED="$FAILED $gs(no-snapshot)"; return 0
  fi
  date_part=${3#"$OFFSITE_SNAP_PREFIX"}
  if [ "$(echo "$date_part" | tr -d -)" -lt "$YESTERDAY" ]; then
    FAILED="$FAILED $gs(stale:$date_part)"
  fi
  for path in "$2/.snap/$3"/*/; do
    break
  done
  path=${path%/}
  [ -d "$path" ] || { FAILED="$FAILED $gs(no-uuid-dir)"; return 0; }
  echo "offsite-export: $gs <- $3"
  if ! kopia snapshot create "$path" --override-source="styx@offsite:/export/$gs" \
      --tags="snap:$3"; then
    FAILED="$FAILED $gs(upload)"
  fi
}

do_export() {
  kopia_s3 connect
  YESTERDAY=$(date -u -d "@$(( $(date -u +%s) - 86400 ))" +%Y%m%d)
  TODAY=$(date -u +%Y%m%d)
  SEEN=0 FAILED=""
  each_subvolume
  [ "$SEEN" -gt 0 ] || die "no subvolumes found under $OFFSITE_SNAP_ROOT"
  [ -z "$FAILED" ] || die "failed subvolumes:$FAILED"
  echo "offsite-export: exported $SEEN subvolume(s)"
}

do_verify() {
  kopia_s3 connect
  kopia snapshot verify --verify-files-percent="$OFFSITE_VERIFY_PERCENT" --file-parallelism=8
  if [ "$(date -u +%u)" = "$OFFSITE_FULL_VERIFY_DOW" ]; then
    kopia content verify
  fi
}

mode=${1:-}
case "$mode" in
  init|export|verify) ;;
  *) die "usage: offsite-export.sh init|export|verify" ;;
esac
check_env
"do_$mode"

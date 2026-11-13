#!/usr/bin/env bash
# Reproducible build of the Windows smartcard helper (unsigned).
# Builds twice in clean dirs, fails if SHA-256 differs, writes exe + .sha256.
# Env: OUT_DIR (default smartcard/dist), GO_VERSION (pinned; checked if set by CI).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
out_dir="${OUT_DIR:-$root/smartcard/dist}"
name=styx-card-helper.exe
want_go="${GO_VERSION:-1.22.12}"
export GOTOOLCHAIN=local

have="$(go version | awk '{print $3}')"
case "$have" in
  go"$want_go") ;;
  *) echo "Go $want_go required, found $have" >&2; exit 1 ;;
esac

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
build() { # $1 = clean output dir; own GOCACHE so the second build is not a cache hit
  mkdir -p "$1/gocache"
  ( cd "$root/smartcard" && GOCACHE="$1/gocache" CGO_ENABLED=0 GOOS=windows GOARCH=amd64 \
      go build -mod=readonly -trimpath -buildvcs=false -ldflags=-buildid= \
      -o "$1/$name" ./cmd/styx-card-helper )
}
build "$tmp/a"; build "$tmp/b"
sha_a="$(sha256sum "$tmp/a/$name" | cut -d' ' -f1)"
sha_b="$(sha256sum "$tmp/b/$name" | cut -d' ' -f1)"
if [ "$sha_a" != "$sha_b" ]; then
  echo "NOT REPRODUCIBLE: $sha_a != $sha_b" >&2; exit 1
fi
mkdir -p "$out_dir"
cp "$tmp/a/$name" "$out_dir/$name"
( cd "$out_dir" && sha256sum "$name" >"$name.sha256" )
echo "built $out_dir/$name sha256=$sha_a"

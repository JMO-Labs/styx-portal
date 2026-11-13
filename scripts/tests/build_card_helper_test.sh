#!/usr/bin/env bash
# Tests build_card_helper.sh with a stub `go`: identical builds pass, differing builds fail.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
script="$here/../build_card_helper.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat >"$tmp/bin/go" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = version ]; then echo "go version go1.22.12 linux/amd64"; exit 0; fi
[ "${CGO_ENABLED:-}" = 0 ] && [ "${GOOS:-}" = windows ] || { echo "bad env" >&2; exit 2; }
out=""; flags="$*"
while [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done
for f in -mod=readonly -trimpath -buildvcs=false '-ldflags=-buildid='; do
  case "$flags" in *"$f"*) ;; *) echo "missing $f" >&2; exit 2;; esac
done
echo "${GOCACHE:-}" >>"$STUB_LOG"
if [ -n "${STUB_NONDET:-}" ]; then echo "$RANDOM$RANDOM" >"$out"; else echo same >"$out"; fi
STUB
chmod +x "$tmp/bin/go"
export PATH="$tmp/bin:$PATH"
export STUB_LOG="$tmp/gocache.log"

# go.sum must pin every required module (build uses -mod=readonly).
sum="$here/../../smartcard/go.sum"
[ -f "$sum" ] || { echo "FAIL: smartcard/go.sum missing"; exit 1; }
for m in github.com/gorilla/websocket gopkg.in/yaml.v3; do
  grep -q "^$m .* h1:" "$sum" || { echo "FAIL: go.sum lacks $m"; exit 1; }
done

OUT_DIR="$tmp/ok" "$script"
[ -f "$tmp/ok/styx-card-helper.exe" ] || { echo "FAIL: exe missing"; exit 1; }
[ -f "$tmp/ok/styx-card-helper.exe.sha256" ] || { echo "FAIL: sha missing"; exit 1; }
( cd "$tmp/ok" && sha256sum -c styx-card-helper.exe.sha256 >/dev/null )
# Each build must use its own empty GOCACHE (no cache hits between them).
mapfile -t caches <"$STUB_LOG"
[ "${#caches[@]}" -eq 2 ] && [ -n "${caches[0]}" ] && [ "${caches[0]}" != "${caches[1]}" ] \
  || { echo "FAIL: builds must use distinct GOCACHE (got: ${caches[*]:-none})"; exit 1; }
if STUB_NONDET=1 OUT_DIR="$tmp/bad" "$script" 2>/dev/null; then
  echo "FAIL: nondeterministic build accepted"; exit 1
fi
# A different patch release must be rejected (exact pin).
sed -i 's/go1.22.12/go1.22.13/' "$tmp/bin/go"
if OUT_DIR="$tmp/wrong" "$script" 2>/dev/null; then
  echo "FAIL: wrong Go patch version accepted"; exit 1
fi
echo "ok"

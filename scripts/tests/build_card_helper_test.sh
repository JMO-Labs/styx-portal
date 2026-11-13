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
for f in -trimpath -buildvcs=false '-ldflags=-buildid='; do
  case "$flags" in *"$f"*) ;; *) echo "missing $f" >&2; exit 2;; esac
done
if [ -n "${STUB_NONDET:-}" ]; then echo "$RANDOM$RANDOM" >"$out"; else echo same >"$out"; fi
STUB
chmod +x "$tmp/bin/go"
export PATH="$tmp/bin:$PATH"

OUT_DIR="$tmp/ok" "$script"
[ -f "$tmp/ok/styx-card-helper.exe" ] || { echo "FAIL: exe missing"; exit 1; }
[ -f "$tmp/ok/styx-card-helper.exe.sha256" ] || { echo "FAIL: sha missing"; exit 1; }
( cd "$tmp/ok" && sha256sum -c styx-card-helper.exe.sha256 >/dev/null )
if STUB_NONDET=1 OUT_DIR="$tmp/bad" "$script" 2>/dev/null; then
  echo "FAIL: nondeterministic build accepted"; exit 1
fi
echo "ok"

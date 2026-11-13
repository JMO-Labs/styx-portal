#!/usr/bin/env bash
# Checks the WiX definition and signing runbook for the smartcard helper.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
wxs="$root/smartcard/packaging/windows/styx-card-helper.wxs"
rb="$root/docs/enterprise/runbooks/smartcard-helper-signing.md"
fail() { echo "FAIL: $*" >&2; exit 1; }
[ -f "$wxs" ] || fail "wxs missing"
[ -f "$rb" ] || fail "runbook missing"
python3 -I - "$wxs" <<'PY' || fail "wxs invalid"
import sys, xml.etree.ElementTree as ET
t = ET.parse(sys.argv[1]); s = ET.tostring(t.getroot(), encoding="unicode")
for need in ('styx-card-helper.exe', 'URL Protocol', 'styx-card', 'perMachine',
             'HKLM', 'UpgradeCode', 'shell\\open\\command'):
    assert need in s, need
PY
for w in signtool '/tr' '/td' sha256 'Intune' 'build_card_helper.sh' 'wix build'; do
  grep -q -- "$w" "$rb" || fail "runbook lacks $w"
done
grep -q 'smartcard-helper-signing' "$root/zensical.toml" || fail "not in nav"
# No signing material in the repo.
if git -C "$root" ls-files | grep -Ei '\.(pfx|p12|pem|key|snk)$|\.msi$' | grep -v testdata; then
  fail "signing material or MSI committed"
fi
echo ok

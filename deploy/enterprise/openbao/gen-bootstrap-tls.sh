#!/usr/bin/env bash
# Offline bootstrap CA and OpenBao server certificate (issue #4, ADR-0042).
# Usage: gen-bootstrap-tls.sh <outdir>   (outdir must be outside any git work tree)
# Writes ca.crt, ca.key (EC P-384, 10 y) and tls.crt, tls.key (EC P-384, 1 y), keys 0600,
# then prints the kubectl commands that load them. Never prints key contents.
set -euo pipefail

out="${1:-}"
if [[ -z "$out" ]]; then
  echo "usage: $0 <outdir>" >&2
  exit 2
fi

# Refuse any outdir inside this checkout or any git work tree, so keys can never be
# committed by accident. Plain path checks: works without git and with tarball checkouts.
refuse() {
  echo "refusing: $out is inside a git work tree; use a path on encrypted offline media" >&2
  exit 2
}
probe="$out"
while [[ ! -d "$probe" ]]; do probe="$(dirname "$probe")"; done
probe="$(cd "$probe" && pwd -P)"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
[[ "$probe/" == "$repo/"* ]] && refuse
d="$probe"
while [[ "$d" != / ]]; do
  [[ -e "$d/.git" ]] && refuse
  d="$(dirname "$d")"
done
if [[ -e "$out/ca.key" || -e "$out/tls.key" ]]; then
  echo "refusing: $out already holds keys; renewing the CA is a runbook step" >&2
  exit 2
fi

umask 077
mkdir -p "$out"
cd "$out"

SANS="DNS:openbao,DNS:openbao.openbao,DNS:openbao.openbao.svc"
SANS="$SANS,DNS:openbao.openbao.svc.cluster.local,DNS:openbao-active.openbao.svc"
SANS="$SANS,DNS:*.openbao-internal,DNS:*.openbao-internal.openbao.svc,IP:127.0.0.1"

openssl ecparam -name secp384r1 -genkey -noout -out ca.key
openssl req -x509 -new -sha384 -key ca.key -days 3650 -subj "/CN=Styx OpenBao bootstrap CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" -out ca.crt

openssl ecparam -name secp384r1 -genkey -noout -out tls.key
openssl req -new -sha384 -key tls.key -subj "/CN=openbao.openbao.svc" -out tls.csr
cat > tls.ext <<EOF
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth,clientAuth
subjectAltName = $SANS
EOF
openssl x509 -req -sha384 -in tls.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 365 \
  -extfile tls.ext -out tls.crt 2>/dev/null
rm -f tls.csr tls.ext ca.srl
chmod 0600 ca.key tls.key
chmod 0644 ca.crt tls.crt

dir="$(pwd)"
cat <<EOF
Created in $dir: ca.crt, ca.key (keep offline), tls.crt, tls.key.
Load them (namespaces from deploy/enterprise/*/namespace.yaml must exist):

kubectl create secret generic openbao-tls -n openbao \\
  --from-file=tls.crt=$dir/tls.crt --from-file=tls.key=$dir/tls.key --from-file=ca.crt=$dir/ca.crt
kubectl create secret generic openbao-ca -n external-secrets --from-file=ca.crt=$dir/ca.crt

Then move ca.key to offline escrow and delete tls.key from this machine.
EOF

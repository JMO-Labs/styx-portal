#!/usr/bin/env bash
# pcscd lists the vpcd virtual reader in the enterprise base image (SMARTCARD_ENABLED=true).
set -euo pipefail

IMG=styx-enterprise-base:kind
NS=smartcard-smoke
POD=smartcard-smoke

DIGEST=$(docker buildx imagetools inspect ubuntu:24.04 --format '{{json .Manifest.Digest}}' | tr -d '"')
docker build --build-arg "UBUNTU_DIGEST=$DIGEST" -f images/enterprise-base/Dockerfile -t "$IMG" .
kind load docker-image "$IMG" --name spike

kubectl create ns "$NS"
trap 'kubectl -n "$NS" logs "$POD" --tail=40 || true; kubectl delete ns "$NS" --wait=false || true' EXIT
kubectl -n "$NS" apply -f - <<'Y'
apiVersion: v1
kind: Pod
metadata:
  name: smartcard-smoke
spec:
  containers:
    - name: selkies
      image: styx-enterprise-base:kind
      imagePullPolicy: Never
      env:
        - {name: SMARTCARD_ENABLED, value: "true"}
        - {name: STYX_INSTANCE_ID, value: smoke}
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        allowPrivilegeEscalation: false
        capabilities: {drop: ["ALL"]}
Y
kubectl -n "$NS" wait --for=condition=Ready "pod/$POD" --timeout=300s

[ "$(kubectl -n "$NS" exec "$POD" -- id -u)" = "1000" ] || { echo "FAIL: not uid 1000"; exit 1; }
kubectl -n "$NS" exec "$POD" -- sh -c 'grep -qx styx-card-relay /proc/[0-9]*/comm'  || { echo "FAIL: relay not running"; exit 1; }

out=""
for _ in $(seq 1 15); do
  out=$(kubectl -n "$NS" exec "$POD" -- sh -c 'python3 - <<P
import ctypes
l=ctypes.CDLL("libpcsclite.so.1")
# pcsclite on 64-bit Linux: DWORD and SCARDCONTEXT are unsigned long (8 bytes).
D=ctypes.c_ulong
l.SCardEstablishContext.argtypes=[D,ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(D)]
l.SCardListReaders.argtypes=[D,ctypes.c_char_p,ctypes.c_char_p,ctypes.POINTER(D)]
ctx=D(0)
assert l.SCardEstablishContext(2,None,None,ctypes.byref(ctx))==0
n=ctypes.c_ulong(0)
l.SCardListReaders(ctx,None,None,ctypes.byref(n))
b=ctypes.create_string_buffer(n.value)
l.SCardListReaders(ctx,None,b,ctypes.byref(n))
print(b.raw.replace(b"\0",b"\n").decode())
P' 2>/dev/null || true)
  echo "$out" | grep -qi "vpcd\|virtual" && break
  sleep 2
done
echo "readers: $out"
echo "$out" | grep -qi "vpcd\|virtual" || { echo "FAIL: virtual reader not listed"; exit 1; }
echo "smartcard smoke OK"

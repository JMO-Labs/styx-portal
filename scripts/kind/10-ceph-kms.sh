#!/usr/bin/env bash
# Spike (#64): Rook-Ceph OSD dm-crypt KEK in OpenBao (kubernetes auth), outage and rotation.
# Rook is not tested upstream against OpenBao. Uses deploy/enterprise/openbao/policies/rook-ceph.hcl
# and the rook-ceph role from auth-roles.json. Single node, one loop-device block PV.
set -euo pipefail

ROOK_CHART_VERSION="${ROOK_CHART_VERSION:-1.21.2}"
CEPH_IMAGE="${CEPH_IMAGE:-quay.io/ceph/ceph:v20.2.5}"
BAO_IMAGE="${BAO_IMAGE:-ghcr.io/openbao/openbao:2.7.2}"
NODE="spike-control-plane"
LOOP_N=200
RK=rook-ceph
BAO_NS=openbao
POLICY=deploy/enterprise/openbao/policies/rook-ceph.hcl
ROLES=deploy/enterprise/openbao/auth-roles.json

step() { printf '\n=== %s ===\n' "$*"; }
fail() { echo "FAIL: $*" >&2; diag; exit 1; }
diag() {
  kubectl get ns "$RK" >/dev/null 2>&1 || echo "ns $RK not created yet"
  kubectl -n "$RK" get pods -o wide || true
  kubectl -n "$RK" describe pods -l app=rook-ceph-osd | tail -60 || true
  kubectl -n "$BAO_NS" get pods -o wide || true
  kubectl -n "$BAO_NS" describe pod openbao-0 | tail -40 || true
  kubectl -n "$BAO_NS" logs openbao-0 -c openbao --tail=40 || true
  kubectl -n "$BAO_NS" logs openbao-0 -c openbao --previous --tail=20 || true
  kubectl -n "$RK" logs deploy/rook-ceph-operator --tail=60 || true
}
bao() { # run bao CLI inside the openbao pod (root token never printed)
  kubectl -n "$BAO_NS" exec -i openbao-0 -- env BAO_ADDR=http://127.0.0.1:8200 BAO_TOKEN="$ROOT_TOKEN" bao "$@"
}
bao_up() { # container started and exec works (pod phase Running is not enough)
  kubectl -n "$BAO_NS" exec openbao-0 -c openbao -- true
}
wait_for() { # wait_for <timeout-s> <desc> <cmd...>
  local t=$1 d=$2; shift 2
  local end=$((SECONDS + t))
  until "$@" >/dev/null 2>&1; do
    [ $SECONDS -lt $end ] || fail "timeout waiting for: $d"
    sleep 5
  done
  echo "ok: $d"
}
osd_pod() { kubectl -n "$RK" get pod -l app=rook-ceph-osd -o jsonpath='{.items[0].metadata.name}'; }
osd_ready() { kubectl -n "$RK" get pod -l app=rook-ceph-osd -o json |
  jq -e '[.items[] | select(.metadata.deletionTimestamp==null) | select(.status.phase=="Running" and ([.status.conditions[]|select(.type=="Ready" and .status=="True")]|length==1))]|length==1'; }
kek_stuck() { # OSD pod Pending/Init with encryption-kms-get-kek not completed
  kubectl -n "$RK" get pod -l app=rook-ceph-osd -o json | jq -e '
    [.items[] | select(.metadata.deletionTimestamp==null) | select(.status.phase=="Pending")
     | .status.initContainerStatuses[]? | select(.name=="encryption-kms-get-kek")
     | select(.state.terminated==null or .state.terminated.exitCode!=0)] | length>=1'; }
kek_key() { bao kv list -mount=rook -format=json | jq -r '.[]|select(startswith("rook-ceph-osd-encryption-key-"))' | head -1; }
key_version() { bao kv metadata get -mount=rook -format=json "$1" | jq -r '.data.current_version'; }
restart_osd() {
  kubectl -n "$RK" delete pod -l app=rook-ceph-osd --wait=true --timeout=120s
}

step "loop device on kind node"
docker exec "$NODE" bash -c "
  truncate -s 8G /var/lib/spike-osd.img
  [ -e /dev/loop$LOOP_N ] || mknod -m660 /dev/loop$LOOP_N b 7 $LOOP_N
  losetup /dev/loop$LOOP_N /var/lib/spike-osd.img
  losetup -a | grep loop$LOOP_N; lsblk /dev/loop$LOOP_N"
# kind nodes run no udevd; ceph-volume raises "No udev data could be retrieved"
# for any block device without /run/udev/data/b<maj:min>. Keep empty stubs for
# every device (incl. dm-crypt mappings created later) via a node-side loop.
docker exec -d "$NODE" sh -c 'mkdir -p /run/udev/data; while :; do
  for d in /sys/class/block/*/dev; do f=/run/udev/data/b$(cat "$d"); [ -e "$f" ] || : > "$f"; done
  sleep 2; done'
sleep 3; docker exec "$NODE" sh -c 'ls /run/udev/data | wc -l'

step "local PV (block) + storage class"
kubectl apply -f - <<YAML
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata: {name: local-nvme}
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
---
apiVersion: v1
kind: PersistentVolume
metadata: {name: spike-osd-pv}
spec:
  capacity: {storage: 8Gi}
  volumeMode: Block
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-nvme
  local: {path: /dev/loop$LOOP_N}
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - {key: kubernetes.io/hostname, operator: In, values: [$NODE]}
YAML

step "OpenBao ${BAO_IMAGE} (single-node raft on hostPath so data survives stop/start)"
# OpenBao 2.x has no "file" storage and no disable_mlock; raft is the supported backend.
# The entrypoint's chown of a hostPath fails on kind (EPERM -> CrashLoop), so pre-create the
# dir world-writable on the node and set SKIP_CHOWN/SKIP_SETCAP.
docker exec "$NODE" bash -c "mkdir -p /var/lib/spike-openbao && chmod 0777 /var/lib/spike-openbao"
kubectl create ns "$BAO_NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f - <<YAML
apiVersion: v1
kind: ServiceAccount
metadata: {name: openbao, namespace: $BAO_NS}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: openbao-auth-delegator}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: system:auth-delegator}
subjects: [{kind: ServiceAccount, name: openbao, namespace: $BAO_NS}]
---
apiVersion: v1
kind: ConfigMap
metadata: {name: openbao-config, namespace: $BAO_NS}
data:
  config.hcl: |
    ui = false
    listener "tcp" { address = "0.0.0.0:8200"
      tls_disable = 1 }
    storage "raft" { path = "/openbao/data"
      node_id = "openbao-0" }
    api_addr = "http://openbao.$BAO_NS.svc:8200"
    cluster_addr = "http://127.0.0.1:8201"
---
apiVersion: v1
kind: Service
metadata: {name: openbao, namespace: $BAO_NS}
spec:
  selector: {app: openbao}
  ports: [{port: 8200, targetPort: 8200}]
---
apiVersion: apps/v1
kind: StatefulSet
metadata: {name: openbao, namespace: $BAO_NS}
spec:
  serviceName: openbao
  replicas: 1
  selector: {matchLabels: {app: openbao}}
  template:
    metadata: {labels: {app: openbao}}
    spec:
      serviceAccountName: openbao
      containers:
      - name: openbao
        image: $BAO_IMAGE
        args: [server, -config=/etc/bao/config.hcl]
        env: [{name: SKIP_CHOWN, value: "true"}, {name: SKIP_SETCAP, value: "true"}]
        ports: [{containerPort: 8200}]
        readinessProbe:
          httpGet: {path: "/v1/sys/health?sealedcode=204&uninitcode=204", port: 8200}
          periodSeconds: 3
        volumeMounts:
        - {name: cfg, mountPath: /etc/bao}
        - {name: data, mountPath: /openbao/data}
      volumes:
      - {name: cfg, configMap: {name: openbao-config}}
      - {name: data, hostPath: {path: /var/lib/spike-openbao, type: DirectoryOrCreate}}
YAML
wait_for 180 "openbao container running" bao_up
INIT=$(kubectl -n "$BAO_NS" exec openbao-0 -c openbao -- env BAO_ADDR=http://127.0.0.1:8200 bao operator init -key-shares=1 -key-threshold=1 -format=json)
UNSEAL_KEY=$(jq -r '.unseal_keys_b64[0]' <<<"$INIT")
ROOT_TOKEN=$(jq -r '.root_token' <<<"$INIT")
unseal() { kubectl -n "$BAO_NS" exec openbao-0 -c openbao -- env BAO_ADDR=http://127.0.0.1:8200 bao operator unseal "$UNSEAL_KEY" >/dev/null; }
unseal
wait_for 60 "openbao ready" kubectl -n "$BAO_NS" wait --for=condition=Ready pod/openbao-0 --timeout=5s

step "OpenBao config: KV v2 at rook/, policy, kubernetes auth role (from repo files)"
bao secrets enable -path=rook -version=2 kv
kubectl -n "$BAO_NS" exec -i openbao-0 -- env BAO_ADDR=http://127.0.0.1:8200 BAO_TOKEN="$ROOT_TOKEN" bao policy write rook-ceph - < "$POLICY"
bao auth enable kubernetes
bao write auth/kubernetes/config kubernetes_host=https://kubernetes.default.svc
ROLE=$(jq -c '.[]|select(.name=="rook-ceph")' "$ROLES")
BOUND_SAS=$(jq -r '.bound_service_account_names|join(",")' <<<"$ROLE")
bao write auth/kubernetes/role/rook-ceph \
  bound_service_account_names="$BOUND_SAS" \
  bound_service_account_namespaces="$(jq -r '.bound_service_account_namespaces|join(",")' <<<"$ROLE")" \
  policies="$(jq -r '.policies|join(",")' <<<"$ROLE")" \
  token_ttl="$(jq -r '.token_ttl' <<<"$ROLE")"
echo "role bound SAs: $BOUND_SAS"

step "Rook operator chart ${ROOK_CHART_VERSION}"
helm repo add rook-release https://charts.rook.io/release >/dev/null
helm upgrade --install rook-ceph rook-release/rook-ceph --version "$ROOK_CHART_VERSION" \
  -n "$RK" --create-namespace --set csi.enableRbdDriver=false --set csi.enableCephfsDriver=false \
  --set monitoring.enabled=false --set allowLoopDevices=true --wait --timeout 8m
# allowLoopDevices: osd-prepare otherwise fails with "unsupported diskType loop" (test-only setting).

step "CephCluster: encrypted PVC OSD, KMS=vault (kubernetes auth), key rotation on"
# NOTE: KMS connectionDetails below mirror deploy/enterprise/rook-ceph/cephcluster.yaml (Child 1)
# except VAULT_CACERT and VAULT_TLS_SERVER_NAME (kind: plain HTTP). Keep in sync.
kubectl apply -f - <<YAML
apiVersion: ceph.rook.io/v1
kind: CephCluster
metadata: {name: rook-ceph, namespace: $RK}
spec:
  cephVersion: {image: $CEPH_IMAGE, allowUnsupported: false}
  dataDirHostPath: /var/lib/rook
  mon: {count: 1, allowMultiplePerNode: true}
  mgr: {count: 1, allowMultiplePerNode: true}
  dashboard: {enabled: false}
  crashCollector: {disable: true}
  security:
    kms:
      connectionDetails:
        KMS_PROVIDER: vault
        VAULT_ADDR: http://openbao.$BAO_NS.svc:8200
        VAULT_BACKEND_PATH: rook
        VAULT_SECRET_ENGINE: kv
        VAULT_BACKEND: v2
        VAULT_AUTH_METHOD: kubernetes
        VAULT_AUTH_MOUNT_PATH: kubernetes
        VAULT_AUTH_KUBERNETES_ROLE: rook-ceph
    keyRotation: {enabled: true, schedule: "0 0 1 1 *"}
  storage:
    useAllNodes: false
    useAllDevices: false
    storageClassDeviceSets:
    - name: spike
      count: 1
      portable: false
      encrypted: true
      volumeClaimTemplates:
      - metadata: {name: data}
        spec:
          resources: {requests: {storage: 8Gi}}
          storageClassName: local-nvme
          volumeMode: Block
          accessModes: [ReadWriteOnce]
YAML
wait_for 900 "OSD pod Ready" osd_ready

step "ASSERT 1: KEK exists at rook/data/rook-ceph-osd-encryption-key-*"
KEY=$(kek_key)
[ -n "$KEY" ] || fail "no rook-ceph-osd-encryption-key-* in rook/"
echo "KV path: rook/data/$KEY"
bao kv get -mount=rook -format=json "$KEY" | jq -e '.data.data|length>0' >/dev/null || fail "key empty"
V0=$(key_version "$KEY"); echo "key version: $V0"

step "ASSERT 2: restart OSD with OpenBao up -> OK"
restart_osd
wait_for 300 "OSD Ready after restart (OpenBao up)" osd_ready

step "ASSERT 3: OpenBao stopped, restart OSD -> stuck in Init on encryption-kms-get-kek"
kubectl -n "$BAO_NS" scale sts/openbao --replicas=0
kubectl -n "$BAO_NS" wait --for=delete pod/openbao-0 --timeout=120s
restart_osd
wait_for 240 "OSD Pending with encryption-kms-get-kek not complete" kek_stuck
sleep 30
kek_stuck || fail "OSD no longer stuck on encryption-kms-get-kek"
kubectl -n "$RK" get pod -l app=rook-ceph-osd
kubectl -n "$RK" logs -l app=rook-ceph-osd -c encryption-kms-get-kek --tail=15 || true

step "ASSERT 4: OpenBao started again -> OSD recovers"
kubectl -n "$BAO_NS" scale sts/openbao --replicas=1
wait_for 180 "openbao container running" bao_up
unseal
wait_for 600 "OSD Ready after OpenBao back" osd_ready
[ "$(key_version "$KEY")" = "$V0" ] || fail "key version changed by outage"

step "ASSERT 5: rotation CronJob once -> key version increments"
wait_for 300 "rotation CronJob exists" bash -c "kubectl -n $RK get cronjob -o name | grep -i rotat"
CJ=$(kubectl -n "$RK" get cronjob -o name | grep -i rotat | head -1)
CJ_SA=$(kubectl -n "$RK" get "$CJ" -o jsonpath='{.spec.jobTemplate.spec.template.spec.serviceAccountName}')
echo "RECORDED: $CJ uses ServiceAccount '${CJ_SA:-default}'; role rook-ceph binds: $BOUND_SAS"
case ",$BOUND_SAS," in *",${CJ_SA:-default},"*) echo "ok: rotation SA is bound in role";;
  *) fail "rotation SA '${CJ_SA:-default}' not in auth-roles.json rook-ceph.bound_service_account_names: add it (Child 2)";; esac
kubectl -n "$RK" create job spike-rotate --from="$CJ"
kubectl -n "$RK" wait --for=condition=complete job/spike-rotate --timeout=300s || {
  kubectl -n "$RK" logs job/spike-rotate --tail=40 || true; fail "rotation job did not complete"; }
V1=$(key_version "$KEY"); echo "key version: $V0 -> $V1"
[ "$V1" -gt "$V0" ] || fail "key version did not increment"
wait_for 300 "OSD Ready after rotation" osd_ready

echo "SPIKE OK: KEK path rook/data/$KEY; outage blocks restart (Init); recovers; rotation v$V0->v$V1; rotation SA=${CJ_SA:-default}"

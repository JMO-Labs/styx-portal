# Rook (role rook-ceph): OSD dm-crypt KEKs in the rook/ KV v2 mount only (issue #63).
# sys/mounts read lets the Vault client auto-detect KV v1/v2. Nothing else: no "*", no sudo.
path "rook/data/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "rook/metadata/*" {
  capabilities = ["read", "list", "delete"]
}

path "sys/mounts" {
  capabilities = ["read"]
}

# External Secrets (role eso): read-only on the kv/ mount. Infra secrets that need isolation
# (for example Rook KEKs, #20) live in other mounts this policy cannot read.
path "kv/data/*" {
  capabilities = ["read"]
}

path "kv/metadata/*" {
  capabilities = ["read", "list"]
}

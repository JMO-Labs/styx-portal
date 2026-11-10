# Over-broad policy: test_no_wildcard_root_or_sudo must reject it.
path "*" {
  capabilities = ["read"]
}
path "sys/mounts" {
  capabilities = ["read", "sudo"]
}

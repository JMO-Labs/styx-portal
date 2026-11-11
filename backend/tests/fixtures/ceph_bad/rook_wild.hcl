# Over-broad rook policy: test_wildcard_rook_policy_fixture_rejected must reject it.
path "*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}
path "sys/mounts" {
  capabilities = ["read"]
}

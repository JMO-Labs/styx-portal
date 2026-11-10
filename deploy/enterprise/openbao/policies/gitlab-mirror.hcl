# GitLab CI job gitlab-mirror-apply (JWT role gitlab-mirror, issue #10): read the two
# mirror bootstrap tokens and nothing else.
path "kv/data/gitlab-mirror/*" {
  capabilities = ["read"]
}

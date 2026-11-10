# GitLab CI jobs gitlab-protect-apply and gitlab-protect-drift (JWT role gitlab-protect,
# issue #16): read the protect bootstrap token and ci_config_path and nothing else.
path "kv/data/gitlab-protect/*" {
  capabilities = ["read"]
}

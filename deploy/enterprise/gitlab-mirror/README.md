# GitLab -> GitHub push mirror (enterprise)

Mirroring as code (issue #10, ADR-0048): `mirror_bootstrap.py` configures the federal GitLab
push mirror and the GitHub write deploy key `federal-gitlab-mirror`. `github_known_hosts` pins
GitHub's SSH host keys. Code only: nothing here is run by CI except the offline tests. The
runbook is [docs/operate/gitlab-mirror.md](../../../docs/operate/gitlab-mirror.md).

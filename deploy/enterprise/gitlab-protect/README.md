# GitLab protected branches and approvals (enterprise)

Settings as code for the federal GitLab (issue #16, ADR-0048): `protect_bootstrap.py`
(protected branches/tags, merge checks, optional Premium approvals), `approval_gate.py` and
`ci-policy/gitlab-ci.yml` (Free-tier approval gate in an external CI config), and
`github_lock.py` (GitHub push-lock, applied only at cutover). Shared client:
`../gitlab-common/glapi.py`. Nothing here is run by CI except the offline tests and the
manual/scheduled jobs. The runbook is
[docs/operate/gitlab-protect.md](../../../docs/operate/gitlab-protect.md).

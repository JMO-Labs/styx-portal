# GitLab -> GitHub mirror (enterprise)

Per ADR-0048 the federal GitLab is the source of truth and the GitHub repository is a mirror.
GitLab's built-in **push mirror** pushes protected branches to GitHub over SSH with a key that
GitLab generates. The private key never leaves GitLab. Its public half is a repo-scoped GitHub
**write deploy key** named `federal-gitlab-mirror`. Both sides are configured by
`deploy/enterprise/gitlab-mirror/mirror_bootstrap.py` (stdlib Python, idempotent, `--dry-run`).
Nothing is deployed by CI.

| Item | Value |
|---|---|
| Mirror URL | `ssh://git@github.com/<GITHUB_REPO>.git` |
| Auth | `ssh_public_key` (GitLab-generated key) |
| Branches | `only_protected_branches=true` (Free tier has no branch regex) |
| Divergence | `keep_divergent_refs=true`: GitLab never force-pushes over GitHub |
| Host keys | pinned from `deploy/enterprise/gitlab-mirror/github_known_hosts` |
| GitHub key | deploy key `federal-gitlab-mirror`, `read_only=false` |
| Bootstrap tokens | OpenBao `kv/gitlab-mirror/bootstrap` (`gitlab_token`, `github_token`) |

## Preconditions

None of these are verified yet for the federal GitLab. Check them before the first run.

- **GitLab >= 17.9** for the `public_key` API. Ideally **>= 18.4**: older versions ignore
  `host_keys`, so verify GitHub's host key by hand in *Settings > Repository > Mirroring
  repositories* (compare with the fingerprints on GitHub's docs).
- **Free tier** is enough (ADR-0005). `mirror_branch_regex` and `secrets:vault` are paid, so
  the script uses `only_protected_branches` and the job logs in to OpenBao with `id_tokens`.
- **Maintainer may configure mirrors**: push mirroring is enabled on the instance and
  `mirror_available` is not limited to admins. Otherwise the POST returns 403 and the script
  says so; ask a GitLab admin.
- **Egress** from GitLab to `github.com:22`. If only 443 is open, create the mirror by hand
  with `ssh://git@ssh.github.com:443/<owner>/<repo>.git` (the script only manages the
  port-22 URL).
- **Tokens** in OpenBao at `kv/gitlab-mirror/bootstrap`: `gitlab_token` is a project access
  token (Maintainer, `api`); `github_token` is a fine-grained token with *Administration:
  read and write* on the one repository (deploy keys).

## Setup

1. OpenBao: run `bao_configure.py` with `BAO_GITLAB_JWT_ISSUER=https://<federal GitLab>`. It
   enables `auth/jwt` and writes role `gitlab-mirror` from `jwt-roles.json` (bound to
   `project_path` and `ref_protected=true`, policy `gitlab-mirror`, TTL 900 s). Edit the
   placeholder `project_path` and `bound_audiences` in `jwt-roles.json` first. Without the
   variable the JWT step is skipped.
2. GitLab CI variables: `BAO_ADDR` (same value as the role's `bound_audiences`) and
   `BAO_CACERT` (file).
3. Dry run, then apply. From CI, start the manual job `gitlab-mirror-apply` on a protected
   branch: it logs in to OpenBao, runs `--dry-run`, then applies. From a workstation:

    ```bash
    export GITLAB_URL=https://gitlab.example.internal GITLAB_PROJECT=styx/styx-portal
    export GITHUB_REPO=JMO-Labs/styx-portal GITLAB_CA_FILE=/path/to/org-ca.crt
    read -rs GITLAB_TOKEN; read -rs GITHUB_TOKEN; export GITLAB_TOKEN GITHUB_TOKEN
    python3 deploy/enterprise/gitlab-mirror/mirror_bootstrap.py --dry-run  # 0 sync, 2 drift
    python3 deploy/enterprise/gitlab-mirror/mirror_bootstrap.py
    ```

The script GETs first and writes only drift. It never deletes a GitLab mirror and never
touches mirrors to other hosts. A matching mirror with password auth is refused: remove it by
hand and rerun.

## Rotation (yearly)

1. Delete the mirror in GitLab (*Settings > Repository > Mirroring repositories*).
2. Run the script. It creates a new mirror with a new key, sees the GitHub deploy key no
   longer matches, deletes it and adds the new one.
3. Rotate the two bootstrap tokens in OpenBao.

## Monitoring

Poll `GET /projects/:id/remote_mirrors` and alert when `update_status` is `failed` or
`last_error` is set, or when `last_successful_update_at` is older than 1 hour. Protected
branches normally sync within 1 minute. Silent Mode stops mirroring.

## Cutover risk

With `keep_divergent_refs=true`, a branch that moved on GitHub is **silently skipped**. Before
cutover, GitHub's mirrored branches must be push-locked so that only the deploy key can push
(ruleset with the deploy key as bypass actor). That is #16, together with protected-branch
and approval rules on the federal GitLab.

## Known issues

Follow-ups from the #10 review. They fail safe today (nothing is written), but the errors can
mislead:

- `gitlab-mirror-apply` runs `eval "$(python3 ...)"`. If the OpenBao login fails, the job
  fails later with `missing env var GITLAB_TOKEN` instead of the login error. Check
  `BAO_ADDR`, `BAO_CACERT` and the JWT role first.
- The job goes on to the apply run when `--dry-run` exits 1 (it checks `rc -le 2`). The
  apply run fails on its own GETs, so no write happens.
- An empty `GITHUB_API_URL` CI variable makes the script exit 1. Leave it unset.
- Drift in the pinned host keys of an existing mirror is not detected. After GitHub changes
  its host keys, update `github_known_hosts`, delete the mirror and rerun (as in rotation).

## Compliance debt

ADR-0011 is still **Proposed**: the FIPS and STIG exception references (issuer, date, scope,
eMASS artifact) are missing. The owner waived gate R05 for code work only (#10). This blocks
deployment, not this code (SC-13, CM-6).

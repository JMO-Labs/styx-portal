# GitLab protected branches and approvals (enterprise)

Per ADR-0048 the federal GitLab is the source of truth, so the branches that ship into the ATO
boundary (`enterprise`, `release/*`) and the release tags (`v*`) are protected there, as code.
Every change needs a non-author approval given after the latest push, and a passing pipeline,
**on every GitLab tier**. Nothing is bought (ADR-0005) and nothing here is deployed by CI.

| Piece | File |
|---|---|
| Branch, tag and merge-check settings | `deploy/enterprise/gitlab-protect/protect_bootstrap.py` |
| Free-tier approval check (job `approval-gate`) | `deploy/enterprise/gitlab-protect/approval_gate.py` |
| External CI config holding the gate | `deploy/enterprise/gitlab-protect/ci-policy/gitlab-ci.yml` |
| GitHub push-lock (cutover only) | `deploy/enterprise/gitlab-protect/github_lock.py` |
| Shared stdlib API client | `deploy/enterprise/gitlab-common/glapi.py` |

## Rules

| Target | Setting | Value |
|---|---|---|
| Branches `enterprise`, `release/*` | allowed to push | Maintainers (`PUSH_LEVEL=40`) |
| | allowed to merge | Maintainers (40) |
| | force push | off |
| Tag `v*` | allowed to create | Maintainers (40) |
| Project | pipelines must succeed | on |
| | merge on skipped pipeline | off (else `[skip ci]` skips the gate) |
| | `ci_config_path` | `gitlab-ci.yml@<group>/ci-policy` |
| MR into a protected branch | job `approval-gate` | manual, blocking: passes only if someone other than the author approved after the latest push |
| Premium+ only (`GITLAB_APPROVALS=native`) | author approval / committer approval / reset on push | off / off / on, plus one `any_approver` rule with 1 approval |

The script GETs first and writes only drift. It never unprotects a branch or tag and never
touches protected branches or tags it does not manage. Protecting `release/*` also decides
what the #10 push mirror sends to GitHub, because the mirror only pushes protected branches.

## Tier matrix

| Control | Free / CE | Premium / Ultimate |
|---|---|---|
| Protected branches and tags, no force push | native | native |
| Pipeline must pass | native | native |
| Non-author approval, reset on push | `approval-gate` job | native rules **and** `approval-gate` |
| Committers cannot approve | not enforced | native |

`GITLAB_APPROVALS` is `gate` by default and never calls the approval endpoints. With `native`
the script also sets the Premium settings; on Free/CE those endpoints answer 403/404 and the
script prints `native approvals unavailable on this tier; approval-gate still enforces` and
does not fail. The gate stays on in both modes.

## Reviewer flow

1. Review the MR and click **Approve**.
2. Open the MR pipeline and run the manual job **`approval-gate`**. Approving does not start a
   pipeline, so the gate has to be run by hand.
3. The job prints `PASS` or `FAIL` and the reason. Its log is the SA-10 evidence.

Each new push starts a new pipeline with a new, blocked gate, and an approval older than the
push no longer counts. The author's own approval never counts. On CE the API has no
`approved_at`, so the gate uses the time of the latest `approved this merge request` system
note by that user. If no time can be found, the approval does not count.

## Changing the rules

1. Edit the constants at the top of `protect_bootstrap.py` (for example `PUSH_LEVEL`).
2. Dry run against the federal GitLab: `protect_bootstrap.py --dry-run` (0 in sync, 2 drift,
   1 error) prints the planned writes and sends only GETs.
3. Open an MR into `enterprise`; it needs the gate like any other change.
4. After merge, run the manual job `gitlab-protect-apply` on `enterprise`. It runs `--dry-run`,
   then applies.

From a workstation:

```bash
export GITLAB_URL=https://gitlab.example.internal GITLAB_PROJECT=styx/styx-portal
export GITLAB_CI_CONFIG_PATH=gitlab-ci.yml@styx/ci-policy GITLAB_CA_FILE=/path/to/org-ca.crt
read -rs GITLAB_TOKEN; export GITLAB_TOKEN
python3 deploy/enterprise/gitlab-protect/protect_bootstrap.py --dry-run
python3 deploy/enterprise/gitlab-protect/protect_bootstrap.py
```

A protected tag cannot be edited through the API. If `v*` exists with the wrong create level,
the script reports it and exits 1; fix it by hand in *Settings > Repository > Protected tags*.

## Preconditions

None of these are verified yet. Check them before the first apply.

- **Tier:** the owner or an org admin confirms Free, Premium or Ultimate. If the org already
  pays for Premium, set the CI variable `GITLAB_APPROVALS=native`; buying it needs an ADR.
- **`ci-policy` project** exists next to the product project.
- **`jwt-roles.json` placeholders** (`project_path`, `bound_audiences`) are set for both roles,
  and `bao_configure.py` has written role `gitlab-protect`.

## Setup

1. **ci-policy project.** Create `<group>/ci-policy`. Give write access only to the people
   who approve pipeline changes (not to every Maintainer of the product project). Copy
   `ci-policy/gitlab-ci.yml` to its root as `gitlab-ci.yml` and `approval_gate.py` to its
   root. In the `script:` of job `approval-gate` set the literals: the federal API URL
   `https://…/api/v4` (twice), the URL-encoded ci-policy path (e.g. `styx%2Fci-policy`), the
   reviewed commit SHA of `approval_gate.py`, its `sha256sum` (checked before it runs) and
   `CI_PROJECT_ID` (numeric id of the product project). They are literals in the script, not variables, because job and manual-run
   variables override YAML variables. Set `tags:` to the tag of a trusted runner (default
   `ci-policy-trusted`). Runner tags have no access control: any Maintainer who may create a
   project runner can register one with the same tag. Restrict project-runner creation on
   the product project (or its group) to admins. Add the product project to
   ci-policy's job token allowlist (*Settings > CI/CD > Job token permissions*), so the gate
   can download the script.
2. **Gate token.** In the product project create a project access token: role **Reporter**,
   scope **`read_api`**. Store it as the CI/CD variable `APPROVAL_GATE_TOKEN`, **masked**. It
   cannot be protected: MR source branches are not protected refs. Its blast radius is read
   access to a project its users can already read. Rotate it yearly.
3. **OpenBao.** `kv/gitlab-protect/bootstrap` holds `gitlab_token` (project access token,
   Maintainer, `api`) and `ci_config_path` (`gitlab-ci.yml@<group>/ci-policy`). Policy
   `gitlab-protect` reads `kv/data/gitlab-protect/*` only; JWT role `gitlab-protect` is
   bound to the project and to protected refs, TTL 900 s. `ci_config_path` lives in OpenBao,
   not in a CI variable, so a Maintainer cannot mask drift by editing a variable.
4. **Apply** with the manual job `gitlab-protect-apply` (needs `BAO_ADDR`, `BAO_CACERT`).
5. **Drift schedule.** Add a pipeline schedule on `enterprise` (for example daily). The job
   `gitlab-protect-drift` runs only in schedule pipelines on a protected ref, runs
   `--dry-run` and fails on drift (rc 2) or error (rc 1). It catches a Maintainer turning off
   "pipelines must succeed" or changing `ci_config_path`.

## GitHub push-lock (cutover)

Before cutover, GitHub's mirrored branches must accept pushes only from the mirror, or
`keep_divergent_refs` silently skips branches that moved on GitHub.
`github_lock.py` ensures ruleset `federal-mirror-lock` on `refs/heads/enterprise` and
`refs/heads/release/*`: rules `update`, `deletion` and `non_fast_forward`, with deploy keys
as the only bypass actor (`DeployKey` covers every write deploy key, so keep
`federal-gitlab-mirror` the only one). It never touches other rulesets such as `MAIN`.
No CI job applies it. At cutover:

1. Stop GitHub-side semantic-release and Dependabot on `enterprise` first; they would be
   locked out.
2. `GITHUB_REPO=JMO-Labs/styx-portal GITHUB_TOKEN=<Administration: write> github_lock.py
   --dry-run`, then without `--dry-run`.

## Known limitations

- `PUSH_LEVEL=40` lets a Maintainer push straight to `enterprise` without an MR, approval or
  gate. To close that, set `PUSH_LEVEL = 0` (No one): GitLab semantic-release only creates
  tags, so nothing else needs to push.
- On Free/CE the gate checks the author only, not other committers on the MR.
- On Free/CE the API cannot change the push or merge level of an existing protected branch
  (`allowed_to_push`/`allowed_to_merge` on `PATCH` are Premium). `apply` still sends the
  PATCH and prints `done:`, but the level does not change. `gitlab-protect-drift` keeps
  failing with rc 2, so the gap stays visible. Fix it by hand: unprotect the branch in
  *Settings > Repository > Protected branches*, then rerun `gitlab-protect-apply`, which
  protects it again with the managed levels.
- A Maintainer who registers a project runner with the `ci-policy-trusted` tag can run the
  gate on a runner they control. That needs Maintainer rights, which with `PUSH_LEVEL=40`
  already allow a direct push. Restricting project-runner creation (Setup step 1) and
  `PUSH_LEVEL = 0` close both.
- The gate is manual: a reviewer must run it after approving.
- GitLab deep-merges a job of the same name from the included project config into the gate.
  `ci-policy/gitlab-ci.yml` pins every key that runs code or picks the runner (`image`,
  `tags`, `services`, `before_script`, `after_script`, `hooks`, `cache`, `dependencies`),
  turns off inherited defaults and global variables, and pins `workflow:` so an included
  workflow cannot stop MR pipelines. The gate takes the MR from `CI_JOB_TOKEN` (`GET /job`):
  the job must be `approval-gate` of this project in a `refs/merge-requests/<iid>/head`
  pipeline whose IID equals `CI_MERGE_REQUEST_IID`, and the MR head must be the pipeline's
  commit. Anything else fails, including `parallel:` (it renames the job).
- Merged results pipelines (Premium) run on `refs/merge-requests/<iid>/merge`; the gate fails
  closed on them. Use `native` approvals there.
- While an MR is open, *push* pipelines for its source branch are not created (`workflow:`);
  only the MR pipeline runs. Schedule (drift), web and API pipelines always run. Pushes to a
  protected branch are not exempt, so the MR keeps a single gated head pipeline: if
  `enterprise` is the source of an open MR (e.g. into `release/1.x`), a merge into
  `enterprise` gets no branch pipeline and so no `semantic-release`. Run the pipeline on
  `enterprise` by hand (*Build > Pipelines > Run pipeline*) after such a merge.
- The gate runs under `env -i` with only the CI inputs it needs, and `curl` ignores proxy and
  CA environment, because an MR's same-named job can add job variables. An internal CA must
  therefore be in the gate image's system trust store; `GITLAB_CA_FILE` is not passed.
- Role entries for specific users, groups or deploy keys on a protected branch (Premium) are
  left as they are; only the role levels are managed.
- Only the first 100 notes, rules and rulesets are read.

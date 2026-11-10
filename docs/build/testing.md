# Testing

| Suite | Tool | Where | Blocking in CI |
|-------|------|-------|----------------|
| Backend | pytest (asyncio auto mode) | `backend/tests/` | yes |
| Frontend | vitest + Testing Library | `frontend/src/**/__tests__`, `*.test.ts(x)` | yes |
| Frontend types | `npm run build` (`tsc -b`) | `frontend/` | yes |
| Traefik plugin | `go test` | `traefik/plugins-local/src/github.com/styx-portal/styxlocation` | yes |
| Agent | pytest | `agent/tests/` | not in CI |
| Full stack | Playwright | `e2e/` | not in CI (run locally) |
| Stream quality | A/B harness | `e2e/stream-ab/` | no (needs real hardware) |

## Backend (pytest)

```bash
cd backend
.venv/bin/python -m pytest -q            # all
.venv/bin/python -m pytest tests/test_route_writer.py -v
.venv/bin/python -m ruff check app tests # lint, blocking
.venv/bin/python -m mypy                 # non-blocking baseline
.venv/bin/python -m bandit -c pyproject.toml -r app -ll -ii
```

Conventions:

* In-memory SQLite engine per test (`session` fixture); the FastAPI `get_session` dependency is overridden.
* Docker is always mocked (`get_docker_manager` override, or patching `docker.DockerClient.from_env`); k8s tests use a fake client.
* `conftest.py` sets `JWT_SECRET`, `COOKIE_SECURE=false`, `DEV_CORS=true` and generous rate limits **before** importing `app`, and resets abuse trackers and the settings cache between tests (autouse fixtures).
* Prefer testing pure builders (`build_routes_config`, `build_objects`, `resolve_stream_settings`) directly; they are pure on purpose.
* No sleeping on real time: loops are tested through single-pass functions (`_monitor_tick`, `_run_monitor_pass`).
* `test_enterprise_docs.py` is a doc-lint for `docs/enterprise`. It checks that ADR statuses match the index, that no ADR reference dangles, that each decision ID in design.md maps to exactly one ADR, and that the owner's Rounds 1-5 amendments are present. It also checks that no FIPS/STIG exception reference has been invented (R05 stays a `TODO (owner)` placeholder). When you change an ADR's status or add an ADR, update `adr/README.md` in the same commit.
* `test_dr_runbook.py` is a doc-lint for `docs/enterprise/runbooks/full-site-restore.md` (#14). It checks the section and step order and the fields of each step. It checks that every timing says "unproven until #15", that roles and owner inputs stay `TBD (owner input)`, that `--cluster-reset` appears only under control-plane-only loss, that every `targetTime` ends in `Z`, and that the file holds no secrets. It also checks the runbook links from the control matrix (CP-9, CP-10), the enterprise README and ADR-0037/0042.
* The OpenBao and External Secrets IaC (`deploy/enterprise/{openbao,external-secrets}`, #4) is checked by static suites that parse the YAML, HCL and JSON with no cluster. `test_enterprise_openbao*.py` covers values, scheduling, local PVs, the static seal stanza, TLS, the single read-only seal hostPath, PSA, the network policy, the snapshot CronJob, policies and roles, and a leak scan of the tracked files. `test_enterprise_external_secrets.py` covers the `openbao` ClusterSecretStore. `test_openbao_seal_playbook.py` and `test_openbao_tls_script.py` cover the Ansible playbook and the bootstrap CA script (skipped without `openssl`). The validators are pure functions in `openbao_checks.py`, and `test_enterprise_openbao_negative.py` runs them over the `fixtures/openbao_bad/` files so that each check is shown to reject bad input. `test_openbao_configure.py` runs `bao_configure.py` against the fake `bao` in `fixtures/fakebin/` (`FAKE_STATE=empty|configured|denied|tls|down`). Fake binaries live in `fixtures/`, not `tmp_path`, because `tmp_path` is noexec on runners.
* `tests/integration/test_openbao_static_seal.py` is opt-in: it runs only with `OPENBAO_IT=1` and the sha256-pinned `bao` 2.7.2 release binary on `PATH`. It checks auto-unseal after restart, that a wrong key stays sealed, key rotation with `previous_key`, snapshot restore, and that the real `values.yaml` server config boots.
* The Harbor registry IaC (`deploy/enterprise/harbor`, #5) is also checked with no cluster. `test_enterprise_harbor.py` covers the layout and kustomization, digest-pinned images, the external `harbor-db` with `verify-full`, S3 storage with redirect off, HA replicas, Trivy off, existing-Secret-only credentials, and the `db_auth` settings. It also checks that `audit_log_forward_endpoint` stays absent until #11, and covers the restricted security contexts, the CNPG cluster and backups, the OBC to `harbor-s3` mapping, the ExternalSecrets, the network policies, the PDB selectors and a leak scan. `test_helm_render` and `test_render_deterministic` render the vendored `charts/harbor-1.19.4.tgz` and skip without `helm`. The validators are pure functions in `harbor_checks.py`, and `test_enterprise_harbor_negative.py` runs them over the `fixtures/harbor_bad/` overrides so that each check is shown to reject bad input. `test_harbor_bootstrap.py` runs `harbor_bootstrap.py` against a stub Harbor v2.0 API on `http.server` (plain `http://127.0.0.1`). It checks idempotency and `--dry-run`, that no local user is ever created, that the admin password and robot secret never reach stdout or stderr, the `0600` `--secret-out` file, and clean failures on missing env vars and HTTP errors.
* The DMZ HAProxy pair IaC (`deploy/enterprise/dmz-haproxy`, #7) has a static suite, `test_enterprise_dmz_haproxy.py`. It renders the role templates with plain Jinja2 (`dmz_haproxy_checks.render`: role defaults, then `group_vars/dmz.yml`, then inventory host vars, then overrides) and checks the crt-list verify modes, strip-before-set order, the single verified-login `set-header` for each cert header, the 421, allowlist and rate-limit rules, disabled TLS resumption, the systemd drop-in directory, the pinned `curl` for the VRRP check, mTLS on every backend `server`, keepalived unicast, `validate`/`no_log` on tasks, and the docs. `tests/integration/test_dmz_haproxy.py` is opt-in (`HAPROXY_IT=1`, `haproxy` on `PATH` or `HAPROXY_BIN`). It generates a throwaway PKI, starts real HAProxy in front of an mTLS echo backend standing in for Traefik, and checks header stripping on every host, the no-card 403, untrusted-CA and provision handshake failures, SNI/Host 421, trailing-dot and unknown `Host` forms from a public SNI or no SNI (421, never forwarded), the provision allowlist deny from a second loopback source, and resumed sessions (a login chain must not be dropped, and a provision session must not resume on login). The fixture uses one server cert per crt-list entry, as production does. CI runs both in the digest-pinned `haproxy:3.4.7` image (`dmz-haproxy-iac` runs `-k config_check` plus lint, and `dmz-haproxy-integration` runs everything). GitHub CI runs only the static suite (the behaviour suite skips there), and the two GitLab jobs have not run in a pipeline yet (see the runbook's known issues).
* The GitLab -> GitHub mirror (`deploy/enterprise/gitlab-mirror`, #10) is tested offline too. `test_gitlab_mirror_bootstrap.py` loads `mirror_bootstrap.py` with `importlib` and runs it against one HTTPS `ThreadingHTTPServer` stub that answers both the GitLab (`/api/v4/...`) and GitHub (`/repos/...`) paths; `GITHUB_API_URL` points the script at the stub. It checks create, no-op and differing-fields-only PUT, scrubbed-URL matching, that other mirrors and password-auth mirrors are never written, deploy-key rotation (comment ignored, read-only key replaced), `--dry-run` exit codes (0 in sync, 2 drift, GET only), the 404 (< 17.9), 403 (`mirror_available`) and HTML-body errors, input validation, that `GITLAB_TOKEN` and `GITHUB_TOKEN` never reach stdout or stderr, the stdlib-only import rule, and the ed25519 fingerprint of `github_known_hosts`. `test_enterprise_gitlab_mirror_static.py` checks the read-only `gitlab-mirror.hcl` policy, the protected-ref JWT role, the manual `gitlab-mirror-apply` CI job, the control-matrix rows and the docs nav. The `auth/jwt` step of `bao_configure.py` is covered in `test_openbao_configure.py` (skipped without `BAO_GITLAB_JWT_ISSUER`, idempotent). GitHub CI runs these tests in the full suite but lints only `app tests`; GitLab's `gitlab-mirror-iac` job also runs `ruff` on the script.
* Protected branches and approvals (`deploy/enterprise/gitlab-protect`, #16) reuse one HTTPS stub, `tests/gitlab_stub.py` (fixture `serve`, wired in `conftest.py`): a `ThreadingHTTPServer` with a per-test route function that records `(method, path, body)`. `test_gitlab_glapi.py` covers the shared `glapi.py` client (redaction, non-JSON and HTTP errors, the mirror still importing it). `test_gitlab_protect_bootstrap.py` covers create, no-op, PATCH/PUT of only the drifting fields, push/merge level replacement with `_destroy`, never unprotecting or touching unmanaged refs, `gate` vs `native` approvals (403/404 warn, exit 0), `--dry-run` exit codes and token redaction in a subprocess. `test_approval_gate.py` covers `decide()` (self-approval, stale approval, equal time, time zones, missing time fails closed), the CE notes fallback and the `ci-policy/gitlab-ci.yml` shape. `test_github_lock.py` covers the ruleset create/drift/no-op paths. `test_ci_jobs.py` checks the CI jobs, the OpenBao role and policy, the docs nav, ADR-0048 link and control-matrix rows. GitLab's `gitlab-protect-iac` job runs these with `ruff`.
* The offsite export component (`deploy/k8s/offsite-export`, #13) has three suites. `test_k8s_offsite_manifests.py` parses the manifests with no cluster: file list, not in the base kustomization, CronJob security (Forbid, read-only root and snapshot mount, drop ALL + `DAC_READ_SEARCH`), pinned Kopia tag, `params.env` defaults, the ExternalSecret keys and store, no Secret literals, the 4 alerts, DNS-plus-one-FQDN egress, and doc-lint of `docs/operate/offsite-backup.md` (lifecycle rule, per-pack bound), ADR-0037 and the CP-6/CP-9/SC-28 rows. `test_offsite_export_script.py` runs `offsite-export.sh` against the fake `kopia` in `fixtures/fakebin/` with snapshot trees under `tmp_path`: cipher and password guards, the password never in output, `init` flags and refusal on an existing repo, newest-snapshot selection, the RPO guard, invalid and future dates, Ceph `_` dirs and `OFFSITE_GROUPS`, continue-after-failure, orphan purge cutoffs, verify day-of-week and paths with spaces. `tests/integration/test_offsite_minio.py` is opt-in (`OFFSITE_IT=1`, sha256-pinned `kopia` 0.23.1, `minio` and `mc` on `PATH`): round trip with byte-identical restore, incremental second run, locked-version delete refused, wrong password, orphan purge and the noncurrent-version lifecycle rule. GitHub CI runs only the first two; the GitLab jobs `offsite-manifests` (kubeconform) and `offsite-integration` have not run in a pipeline yet.
* The RKE2 node IaC (`deploy/rke2`, #2) has a static suite, `test_rke2_iac.py`, that loads the Ansible YAML with `yaml.safe_load` and needs no nodes. It checks the file list, the exact `lablabs.rke2` 1.54.0 pin, 3 masters and 8 disjoint workers, RFC 5737 IPs for hosts and the VIP, the `rke2_version` pattern (minor >= 34, not `latest`/`stable`, no downgrade), the CIS profile and apiserver arg, keepalived HA with the VIP and a DNS name in the SANs, cilium with no bundled ingress, the server taint, the worker labels (and that no `node-role.kubernetes.io/*` label is set), the env-only token, and that `site.yml` asserts a trimmed, non-default token with `tags: [always]` before the role runs. `_has_literal_secret` walks the tree for literal `token:`/`password:` values (quoted keys too) and the role default; its own test feeds it planted strings. A regression test keeps `disable-kube-proxy` and Cilium `HelmChartConfig` out (that is #18). The `rke2-iac` job in GitLab and GitHub CI runs the galaxy install, `yamllint`, `ansible-lint` (production profile) and `--syntax-check` from `deploy/rke2/`.

## Frontend (vitest)

```bash
cd frontend
npm test            # vitest run (jsdom)
npm run test:watch
npm run build       # the gate: tsc -b + both vite builds
```

`src/test/setup.ts` loads jest-dom matchers, polyfills `ResizeObserver` (Radix)
and cleans up after each test. Test hooks and components with TanStack Query by
wrapping in a fresh `QueryClientProvider`.

## Agent (pytest)

The agent runs on a workstation, not in the backend venv, so its modules
`importorskip` heavy dependencies (aiohttp, dbus) and tests add `agent/` to
`sys.path` themselves. Most logic is pure functions (config builders,
`restart_plan`, `decide` for refit, `hw_encoders`) so tests need no desktop.

```bash
cd agent && ../backend/.venv/bin/python -m pytest tests -q
```

`aiohttp` comes from the backend `dev` extra, so the backend venv runs the gateway tests; D-Bus tests skip when `dbus` is not importable.

`test_packaging.py` checks that every locally imported agent module is served for self-update and that `enroll --upgrade` is atomic and self-restoring.

## End-to-end (Playwright)

`e2e/run.sh` builds and starts an isolated compose project (`styx-e2e`) with real
Sonarr and Jellyfin behind Traefik, a docker shim, and the backend, publishing
only `127.0.0.1:18080`. It then runs the Playwright suite (shell, cookie-root,
proxied services, screenshots) and tears everything down.

```bash
e2e/run.sh                    # whole suite
e2e/run.sh -g "cookie-root"   # filter by test name
KEEP=1 e2e/run.sh             # leave the stack running for debugging
```

On failure, stack logs are saved to `e2e/test-results/stack.log`.

**e2e is not in CI**, so UI rewrites can break it unnoticed: after the Glance UI
(#94) the suite failed on its first test. Selectors follow the Glance names:
the `Admin` header button (not Settings), admin sections *Apps*, *Users and
groups*, *Security and limits*, and containers opening at `/desktop/<sub>`.

The selectors were updated for Glance in #108 (53 passed locally, 6.8 min),
after the phone layout (#106, stacked users list).

!!! warning
    The e2e stack builds images and needs Docker; do not run it on a workstation
    you cannot afford to load.

## Stream harness

See [Streaming](streaming.md#latency-and-ab-harness-e2estream-ab). Its pure
parts (`latstats`, `netem`, `probes`, `suite_latency`) have unit tests:
`cd e2e/stream-ab && python3 -m pytest -q`.

## CI

Both pipelines run the same stages; see [Releases](releases.md#ci-stage-graph).

| Stage | GitHub Actions (`.github/workflows/ci.yml`) | GitLab (`.gitlab-ci.yml`) |
|-------|-----------|--------|
| Quality | `commitlint`, `quality` (ruff, mypy, `npm run build`) | `commitlint`, `ruff`, `mypy`, `frontend-build` |
| Test | `test` (pytest, vitest), `plugin-test` | `pytest`, `vitest`, `plugin-test` |
| Security | `security` (bandit, Trivy fs) | `bandit`, `trivy-fs` |

**Run before every commit:** the checks for the area you touched, matching the
blocking CI jobs above.

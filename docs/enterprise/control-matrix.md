# Control matrix (NIST SP 800-53 Rev 5, Moderate baseline)

> Skeleton for the SSP and eMASS. Implementation statements are summaries and will be expanded per phase. PM family omitted (not in baseline). Covers key controls only, not all Moderate controls. Status is Planned for all rows. Cited ADRs are Accepted (owner approval Rounds 1-5, 2026-11-09); ADR-0045 is superseded by ADR-0060. Risk acceptances R01-R06 are accepted and listed in design.md section 8. Inherited-Org marks organization-level (physical, personnel, training) items.

Responsibility: System = this project, Inherited-Org = provided by the organization, Hybrid = shared.

## AC - Access Control

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| AC-2 | Account Management | Keycloak directory; webhook provisioning, offboarding, review (ADR-0014, 0018, 0019, 0022, 0024). Evidence: ADR-0068; IaC `deploy/enterprise/keycloak/`, tests `backend/tests/test_federation_groups.py`, `test_kc_admin.py`; [runbook](runbooks/keycloak.md) | System | Planned |
| AC-2(1) | Automated System Account Management | Webhook/SCIM-shaped provisioning (ADR-0019) | System | Planned |
| AC-2(3) | Disable Accounts | End-date, 35-day inactivity, remove-access flows (ADR-0022, 0024) | System | Planned |
| AC-2(4) | Automated Audit Actions | Account events to Elastic; Recently provisioned view (ADR-0023); security officer owns the daily review; new accounts unreviewed for 2 business days are auto-suspended (R04) | System | Planned |
| AC-3 | Access Enforcement | Keycloak roles, Styx authorization, Kyverno (ADR-0001, 0026); CephFS homes: [ADR-0066](adr/0066-cephfs-homes-uid-ownership-and-freeze.md), [runbook](runbooks/node-loss-reattach.md) | System | Planned |
| AC-4 | Information Flow Enforcement | DLP policy, Cilium deny-all non-proxy egress, Squid category filtering (ADR-0038, 0040); Cilium baseline (CCNPs, default-deny, desktop egress patch `patch-desktop-egress.yaml`) in `deploy/k8s/components/cilium-baseline/` (README), implemented in code, not deployed; Squid egress (two ports 3128 category / 3129 allowlist, label-selected, UT1 category CronJob, hostname-only JSON logs; ADR-0064, `deploy/enterprise/squid/`, runbook `runbooks/squid-egress.md`) implemented in code, not deployed; HAProxy part not done. | System | Planned |
| AC-5 | Separation of Duties | Admin role split (ADR-0026) | System | Planned |
| AC-6 | Least Privilege | Role model, group-manager scope, non-admin-only webhook (ADR-0020, 0026). Evidence: ADR-0068; tests `backend/tests/test_federation_groups.py`; [runbook](runbooks/keycloak.md) | System | Planned |
| AC-7 | Unsuccessful Logon Attempts | Keycloak policy for break-glass accounts; CAC login via IdP (ADR-0015, 0025) | System | Planned |
| AC-8 | System Use Notification | USG banner before login (ADR-0027). Evidence: IaC `deploy/enterprise/banner/`, tests `backend/tests/test_enterprise_banner.py`; [runbook](runbooks/keycloak.md) | System | Planned |
| AC-11 | Device Lock | 15 min idle lock in Styx gateway; unlock by fresh TLS handshake proves card presence, not PIN entry; risk acceptance R02 (ADR-0039, 0058); card removal locks the session through managed-endpoint policy (GPO / macOS equivalent) (R02) | System | Planned |
| AC-12 | Session Termination | 2 h disconnect stop, 12 h max (ADR-0039) | System | Planned |
| AC-17 | Remote Access | DMZ proxy, CAC mTLS, monitored sessions; consent-free view/take-control by platform admin and help desk only, with persistent banner naming who is viewing/controlling, required ticket number or reason, logged to Elastic, security officer alerted, monthly review by security officer or auditor (ADR-0012, 0060) | System | Planned |
| AC-20 | Use of External Systems | Managed clients, GCC High and upstream GitLab linkage (ADR-0019, 0043) | Hybrid | Planned |

## AT - Awareness and Training

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| AT-2 | Literacy Training and Awareness | Organizational security training; DLP user notices (ADR-0038) | Inherited-Org | Planned |
| AT-3 | Role-Based Training | Admin and help-desk role training (ADR-0026) | Inherited-Org | Planned |

## AU - Audit and Accountability

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| AU-2 | Event Logging | Event catalog incl. webhook, DLP (clipboard/file events as metadata only, never content), egress hostnames (ADR-0020, 0038, 0044); takeover events (actor, user, start/end, mode view/control, reason) (ADR-0060); Styx audit events as ECS JSON (`event.dataset=styx.audit`) and kube-apiserver audit policy in deploy/logging, IaC done, not deployed | System | Planned |
| AU-3 | Content of Audit Records | Readable identity first.last plus EDIPI/card-UUID correlation; DLP records are metadata only (ADR-0016, 0038, 0044); takeover events (actor, user, start/end, mode view/control, reason) (ADR-0060); ECS fields `@timestamp`, `event.id`, `event.action/category/type/outcome`, `user.id/name`, `source.ip`, redacted `styx.audit.detail`; reserved `styx.identity.card_*`, egress and DLP fields (filename sha256 only, no `file.hash`) in deploy/logging, IaC done, not deployed | System | Planned |
| AU-4 | Audit Log Storage Capacity | Elastic 90 d hot / 1 y archive sizing (ADR-0044) | System | Planned |
| AU-5 | Response to Audit Logging Process Failures | Alerting on log shipping failure (ADR-0044); Fluent Bit filesystem buffer and alerts FluentBitOutputFailing, FluentBitRetriesHigh, FluentBitDown in deploy/logging, IaC done, not deployed | System | Planned |
| AU-6 | Audit Record Review, Analysis, and Reporting | Daily digest, access reviews, Elastic (ADR-0023, 0024, 0044); monthly review of takeover events by security officer or auditor (ADR-0060); monthly review of the uncategorised hostnames report (R01) | Hybrid | Planned |
| AU-8 | Time Stamps | Cluster NTP; time source from org (ADR-0044) | Hybrid | Planned |
| AU-9 | Protection of Audit Information | Auditor read-only role; Elastic access controls (ADR-0026, 0044) | Hybrid | Planned |
| AU-11 | Audit Record Retention | 1 y archive (ADR-0044); ILM `styx-logs`: hot rollover 50gb/30d, cold at 90 d, delete at `RETENTION_DELETE_DAYS` (default 455 d, open item) in deploy/logging/elastic, IaC done, not deployed | System | Planned |
| AU-12 | Audit Record Generation | Styx, Keycloak, Squid hostnames (JSON access log, host only, shipped to `logs-squid.access-*`; ADR-0064, implemented in code, not deployed), DLP metadata-only events; Selkies audit patch (ADR-0038, 0040, 0058); gateway takeover events (ADR-0060); Fluent Bit ships Styx audit, container logs and kube-apiserver audit to Elastic data streams (docs/operate/logging.md), IaC done, not deployed | System | Planned |

## CA - Assessment, Authorization, and Monitoring

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| CA-2 | Control Assessments | ADR and matrix evidence; assessor-driven (ADR-0010, 0013) | Hybrid | Planned |
| CA-3 | Information Exchange | Agreements for GCC High, upstream GitLab, cloud backup (ADR-0019, 0037) | Hybrid | Planned |
| CA-5 | Plan of Action and Milestones | Exceptions tracked in eMASS (ADR-0010, 0011) | Inherited-Org | Planned |
| CA-6 | Authorization | RMF ATO (ADR-0010) | Inherited-Org | Planned |
| CA-7 | Continuous Monitoring | SLO dashboards, scans, load gate (ADR-0044, 0047) | Hybrid | Planned |

## CM - Configuration Management

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| CM-2 | Baseline Configuration | Golden images, profiles in git (ADR-0003, 0028). Images: `images/enterprise-base`, `images/golden/*` (ADR-0067). | System | Planned |
| CM-3 | Configuration Change Control | Git-based review, image rollout (ADR-0003, 0030); changes reviewed and approved on the federal GitLab: `deploy/enterprise/gitlab-protect/protect_bootstrap.py` protects `enterprise`/`release/*`/`v*` and requires a passing pipeline, the `approval-gate` job (external `ci-policy` config) requires a non-author approval after the latest push, scheduled `gitlab-protect-drift` fails on drift, `github_lock.py` push-locks the GitHub copies at cutover (#16, docs/operate/gitlab-protect.md); pushed to GitHub by protected-branch-only push mirror `deploy/enterprise/gitlab-mirror` (ADR-0048) | System | Planned |
| CM-6 | Configuration Settings | RKE2 hardening, image config; STIG exception, R05 condition (ADR-0007, 0011); Pod Security Admission exception for the desktop namespace (rootless Selkies base image; `enforce: baseline`, warn/audit restricted; scope: rootless, non-root UID, no privileged, no hostPath): `deploy/enterprise/desktop/namespace.yaml` (ADR-0057); Pod Security Admission exception for the `openbao` namespace (`enforce: privileged`, read-only hostPath for the static seal key only; warn/audit restricted): `deploy/enterprise/openbao/namespace.yaml` (ADR-0042). Image config, UID 1000 and CPU-tier overrides: `images/enterprise-base`, `images/golden/*` (ADR-0067). | System | Planned |
| CM-7 | Least Functionality | Seat mode and homelab features hard-disabled with config test, minimal images (ADR-0004, 0028, 0053; test: [`backend/tests/test_profile.py`](../../backend/tests/test_profile.py)); desktop namespace exception limited to rootless pods with a non-root UID, no privileged, no hostPath (`deploy/enterprise/desktop/namespace.yaml`, ADR-0057); `openbao` namespace PSA exception limited to one read-only hostPath (`/etc/openbao/seal`) (ADR-0042). Minimal images, UID 1000: `images/enterprise-base`, `images/golden/*` (ADR-0067). | System | Planned |
| CM-8 | System Component Inventory | Component and SBOM inventory (ADR-0005, 0029); [component register](component-register.md) of libraries, images, charts and apt apps, CI-checked (#17) | System | Planned |
| CM-12 | Information Location | Homes, CephFS profiles, Ceph RGW archive; user-driven OneDrive moves (ADR-0034, 0035, 0054); CephFS homes: [ADR-0066](adr/0066-cephfs-homes-uid-ownership-and-freeze.md), [runbook](runbooks/node-loss-reattach.md) | System | Planned |
| CM-14 | Signed Components | Kyverno admits only cosign-signed allowlisted images; signing key custody in OpenBao transit, CI-only (ADR-0029, 0063) | System | Planned |

## CP - Contingency Planning

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| CP-2 | Contingency Plan | HA design, availability targets (ADR-0006, 0008); [runbooks/rook-ceph.md](runbooks/rook-ceph.md), ADR-0055 (IaC done, not deployed) | Hybrid | Planned |
| CP-4 | Contingency Plan Testing | Full-site restore test (phase 1), 200-session load-test gate (ADR-0037, 0047); full-site restore test repeats annually, each result filed as eMASS evidence (R03); restore test harness deploy/dr/restore-test ([dr-restore-test.md](../operate/dr-restore-test.md)) writes the evidence report, IaC done, not run | Hybrid | Planned |
| CP-6 | Alternate Storage Site | Encrypted CephFS-snapshot export to CUI-authorized cloud bucket (ADR-0037); Kopia component deploy/k8s/offsite-export, IaC done, not deployed | Hybrid | Planned |
| CP-7 | Alternate Processing Site | Not provided; exception R03 (ADR-0037) | Hybrid | Planned |
| CP-9 | System Backup | CNPG, Velero, home snapshots, offline-escrowed backup keys in two sealed sets (ADR-0033, 0036, 0037, 0042); restore per [runbooks/full-site-restore.md](runbooks/full-site-restore.md); offsite copy with Object Lock and daily verify in deploy/k8s/offsite-export, IaC done, not deployed; restores checked (checksums, pg_amcheck, Kopia verify) by deploy/dr/restore-test, IaC done, not run; CephFS homes: [ADR-0066](adr/0066-cephfs-homes-uid-ownership-and-freeze.md), [runbook](runbooks/node-loss-reattach.md) | System | Planned |
| CP-10 | System Recovery and Reconstitution | RTO 8 h restore procedures (ADR-0037): [runbooks/full-site-restore.md](runbooks/full-site-restore.md); RTO/RPO measured by deploy/dr/restore-test ([dr-restore-test.md](../operate/dr-restore-test.md)), IaC done, not run; CephFS homes: [ADR-0066](adr/0066-cephfs-homes-uid-ownership-and-freeze.md), [runbook](runbooks/node-loss-reattach.md) | System | Planned |

## IA - Identification and Authentication

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| IA-2 | Identification and Authentication (Organizational Users) | Keycloak smart-card-only login (CAC, PIV, PIV-I); break-glass exception R06; cert headers set only by the DMZ HAProxy, stripped from any other source, Keycloak reachable only from Traefik (ADR-0014, 0015, 0025, 0065). Evidence: IaC `deploy/enterprise/keycloak/`, realm tests `backend/tests/test_enterprise_keycloak_realm.py`, `test_keycloak_breakglass.py`; [runbook](runbooks/keycloak.md) | System | Planned |
| IA-2(12) | Acceptance of PIV Credentials | CAC, PIV and PIV-I (PIV Authentication cert only); DoD roots + Federal Common Policy CA; OCSP + CRL mirror, fail closed (ADR-0015, 0016, 0017, 0041, 0065) | System | Planned |
| IA-3 | Device Identification and Authentication | mTLS client cert for webhook (ADR-0020) | System | Planned |
| IA-4 | Identifier Management | EDIPI (CAC) or card UUID (PIV/PIV-I) bound at first login, immutable username (ADR-0016, 0018) | System | Planned |
| IA-5 | Authenticator Management | PKI via DoD and federal CAs; Client-Cert header spoofing control (ADR-0065); break-glass and token rotation; OpenBao auto-unseal, offline escrow (ADR-0015, 0020, 0025, 0042); Kubernetes auth roles and least-privilege policies (`deploy/enterprise/openbao/auth-roles.json`, `policies/`), ESO `ClusterSecretStore` `openbao` (`deploy/enterprise/external-secrets/`) | Hybrid | Planned |
| IA-5(2) | Public Key-Based Authentication | Certificate validation for CAC/PIV/PIV-I chains, OCSP per issuer + CRL mirror by path, fail closed (ADR-0015, 0017, 0065). Evidence: IaC `deploy/enterprise/keycloak/crl-mirror/`, tests `backend/tests/test_enterprise_keycloak_crl.py`; [runbook](runbooks/keycloak.md) | System | Planned |
| IA-8 | Identification and Authentication (Non-Organizational Users) | Not planned; no external users in v1 (ADR-0001, 0015) | System | Planned |
| IA-12 | Identity Proofing | Approval workflow; Styx checks asserted approver is a group manager, cannot verify M365 approval, D23 review is the real control; R04 (ADR-0018, 0020, 0021, 0023); security officer owns the review; new accounts unreviewed for 2 business days are auto-suspended (ADR-0024) | Hybrid | Planned |

## IR - Incident Response

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| IR-4 | Incident Handling | Alerting to ops and security officer (ADR-0023, 0025, 0044) | Hybrid | Planned |
| IR-5 | Incident Monitoring | Elastic SIEM (ADR-0044) | Hybrid | Planned |
| IR-6 | Incident Reporting | Organizational reporting chain | Inherited-Org | Planned |

## MA - Maintenance

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| MA-2 | Controlled Maintenance | Maintenance banner; one monthly announced evening window excluded from 99.9 % (ADR-0008, 0046) | Hybrid | Planned |
| MA-4 | Nonlocal Maintenance | Admin access via break-glass and roles (ADR-0025, 0026) | System | Planned |

## MP - Media Protection

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| MP-6 | Media Sanitization | Scratch volume reclaim after 7 days stopped, object-lock cold tier, disk disposal (ADR-0035) | Hybrid | Planned |
| MP-7 | Media Use | Download-out off, print off (ADR-0038) | System | Planned |

## PE - Physical and Environmental Protection

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| PE-3 | Physical Access Control | Hosting facility controls (ADR-0006) | Inherited-Org | Planned |
| PE-6 | Monitoring Physical Access | Hosting facility (ADR-0006) | Inherited-Org | Planned |

## PL - Planning

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| PL-2 | System Security and Privacy Plans | Repo docs feed SSP (ADR-0010, 0013) | Hybrid | Planned |
| PL-4 | Rules of Behavior | Organizational; banner reinforces (ADR-0027) | Inherited-Org | Planned |

## PS - Personnel Security

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| PS-3 | Personnel Screening | Organizational | Inherited-Org | Planned |
| PS-4 | Personnel Termination | Offboarding flows (ADR-0022) | Hybrid | Planned |
| PS-5 | Personnel Transfer | Group changes and access review (ADR-0024) | Hybrid | Planned |

## RA - Risk Assessment

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| RA-3 | Risk Assessment | Organizational risk assessment with ADR input (ADR-0010) | Hybrid | Planned |
| RA-5 | Vulnerability Monitoring and Scanning | Trivy, Harbor, image rebuilds (ADR-0029, 0030); Harbor registry implemented in code, not deployed: `deploy/enterprise/harbor/` (Trivy off until Phase 3) | System | Planned |

## SA - System and Services Acquisition

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| SA-3 | System Development Life Cycle | Single codebase, CI; federal GitLab source of truth (ADR-0003, 0028, 0048) | System | Planned |
| SA-4 | Acquisition Process | Component and license rule; accepted costs listed (ADR-0005); [component register](component-register.md) with cost class and [license policy](license-policy.yaml), blocking CI gate (#17) | Hybrid | Planned |
| SA-9 | External System Services | GCC High, upstream GitLab, cloud bucket (ADR-0019, 0037) | Hybrid | Planned |
| SA-10 | Developer Configuration Management | Git, signed builds (ADR-0003, 0029); federal GitLab is source of truth with approvals: `protect_bootstrap.py` (protected branches/tags, pipeline must pass), `approval-gate` job (non-author approval after the latest push, job log as evidence), `gitlab-protect-drift` schedule, GitHub push-lock `github_lock.py` (#16); `deploy/enterprise/gitlab-mirror` mirrors protected branches only, keeps divergent refs (ADR-0048). Patch set and image sources: `docs/upstream/`, `images/enterprise-base` (ADR-0058, ADR-0067). | System | Planned |
| SA-11 | Developer Testing and Evaluation | Load test and security testing (ADR-0047) | System | Planned |

## SC - System and Communications Protection

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| SC-5 | Denial-of-Service Protection | DMZ proxy limits, resource caps (ADR-0009, 0031); [runbooks/rook-ceph.md](runbooks/rook-ceph.md), ADR-0055 (IaC done, not deployed) | System | Planned |
| SC-7 | Boundary Protection | HAProxy DMZ pair, Cilium, Squid; SC-7(5) tailored, R01 (ADR-0007, 0012, 0040, 0050); Cilium baseline (CCNPs, default-deny, desktop egress patch `patch-desktop-egress.yaml`) in `deploy/k8s/components/cilium-baseline/` (README), implemented in code, not deployed; Squid egress (two ports 3128 category / 3129 allowlist, label-selected, UT1 category CronJob, hostname-only JSON logs; ADR-0064, `deploy/enterprise/squid/`, runbook `runbooks/squid-egress.md`) implemented in code, not deployed; HAProxy part not done. | System | Planned |
| SC-7(5) | Deny by Default - Allow by Exception | Tailored: internet allowed with category blocking; Cilium denies all non-proxy egress; risk acceptance R01 (ADR-0040); allowlist mode per group stays; monthly review of the uncategorised hostnames report in Elastic; Cilium baseline (CCNPs, default-deny, desktop egress patch `patch-desktop-egress.yaml`) in `deploy/k8s/components/cilium-baseline/` (README), implemented in code, not deployed; Squid egress (two ports 3128 category / 3129 allowlist, label-selected, UT1 category CronJob, hostname-only JSON logs; ADR-0064, `deploy/enterprise/squid/`, runbook `runbooks/squid-egress.md`) implemented in code, not deployed; HAProxy part not done. | System | Planned |
| SC-8 | Transmission Confidentiality and Integrity | TLS at DMZ, separate banner/login/provision/portal hosts, mTLS webhook (ADR-0012, 0020, 0049); Harbor internal TLS is off, pod-to-pod traffic is encrypted by Cilium WireGuard (#18), Harbor to `harbor-db` uses `verify-full` | System | Planned |
| SC-10 | Network Disconnect | Idle and disconnect timeouts (ADR-0039) | System | Planned |
| SC-12 | Cryptographic Key Establishment and Management | OpenBao PKI, auto-unseal, Shamir recovery split, offline escrow, Ceph OSD dm-crypt keys in OpenBao `rook/` with monthly rotation (ADR-0042, 0061; `deploy/enterprise/rook-ceph/cephcluster.yaml`, `deploy/enterprise/openbao/policies/rook-ceph.hcl`, [runbooks/ceph-osd-encryption.md](runbooks/ceph-osd-encryption.md)); static seal key file placed by `deploy/enterprise/openbao/ansible/seal-key.yml`, offline bootstrap CA `gen-bootstrap-tls.sh`, rotation in [runbooks/openbao.md](runbooks/openbao.md) (IaC done, not deployed) | System | Planned |
| SC-13 | Cryptographic Protection | Non-FIPS exception recorded (ADR-0011); R05 accepted on condition; exception references: TODO (owner): issuer, date, scope - required before Phase 1 starts | System | Planned |
| SC-23 | Session Authenticity | OIDC sessions, CSRF protections (ADR-0043) | System | Planned |
| SC-28 | Protection of Information at Rest | Every Ceph OSD encrypted with dm-crypt (`encrypted: true` in `deploy/enterprise/rook-ceph/cephcluster.yaml`), keys in OpenBao, [runbook](runbooks/ceph-osd-encryption.md); backups encryption (ADR-0033, 0037, 0042, 0061); OpenBao Raft auto-unsealed by the static seal on control-plane local PVs, nightly Raft snapshot offsite (`deploy/enterprise/openbao/`); offsite copy encrypted client-side by Kopia in deploy/k8s/offsite-export, IaC done, not deployed; CephFS homes: [ADR-0066](adr/0066-cephfs-homes-uid-ownership-and-freeze.md), [runbook](runbooks/node-loss-reattach.md) | System | Planned |
| SC-28(1) | Cryptographic Protection | dm-crypt on every Ceph OSD, keys in OpenBao (ADR-0061; `deploy/enterprise/rook-ceph/cephcluster.yaml`) | System | Planned |

## SI - System and Information Integrity

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| SI-2 | Flaw Remediation | Nightly rebuild, 24 h critical-CVE recycle; fix deadlines high 7 d, medium 30 d, low 90 d (ADR-0029, 0030, 0063) | System | Planned |
| SI-3 | Malicious Code Protection | To be decided in phase 3 | System | Planned |
| SI-4 | System Monitoring | Elastic, Prometheus (ADR-0044) | System | Planned |
| SI-7 | Software, Firmware, and Information Integrity | cosign and Kyverno (ADR-0029); cosign key in OpenBao transit, non-exportable, signed only by protected-branch CI role, rotation and revocation (ADR-0063) | System | Planned |
| SI-10 | Information Input Validation | Webhook strict schema (ADR-0020) | System | Planned |
| SI-12 | Information Management and Retention | Age-off to Ceph RGW cold storage with self-restore (ADR-0035) | Hybrid | Planned |

## SR - Supply Chain Risk Management

| Control | Title | Implementation | Responsibility | Status |
|---|---|---|---|---|
| SR-3 | Supply Chain Controls and Processes | Signed allowlisted images, SBOM (ADR-0029; per-image OS-package SBOM stays in ADR-0029 phase 3, top-level inventory in the [component register](component-register.md)); Harbor registry with digest-pinned images implemented in code, not deployed: `deploy/enterprise/harbor/` | System | Planned |
| SR-4 | Provenance | SBOM (per-image SBOM in ADR-0029 phase 3), signatures, federal GitLab as source of truth (ADR-0029, 0048); one-way push mirror `deploy/enterprise/gitlab-mirror` with pinned GitHub host key and repo-scoped deploy key, protected branches only, approvals on federal GitLab (#16) | System | Planned |
| SR-11 | Component Authenticity | cosign verification (ADR-0029) | System | Planned |

# Image supply chain runbook

Operate the nightly build, Trivy gate, cosign signing, Kyverno admission and critical-CVE recycle (ADR-0029, ADR-0030, ADR-0063, ADR-0069). Implemented in code, not deployed. Harbor and Kyverno are not yet running.

Parts: workflow `.github/workflows/images-nightly.yml`, policy `deploy/enterprise/kyverno/`, backend `image_digest.py` (launch) and `cve_recycle.py` (recycle).

## Nightly job failed

The job runs at 02:17 UTC. A failure means nothing new was pushed; the previous signed image keeps running and launching.

1. Open the failed run in the Actions tab and find the failing step.
2. By step:
   - **Build**: fix the Dockerfile or base image pull, then rerun (`workflow_dispatch`).
   - **Trivy scan**: see [Trivy triage](#trivy-highcritical-triage).
   - **Push or SBOM**: check the Harbor login secrets and that Harbor is reachable from the runner.
   - **Sign and attest**: check OpenBao is unsealed and the `ci-cosign` role is usable (see the [OpenBao runbook](openbao.md)). Builds queue while it is sealed. The image is already pushed but unsigned, so Kyverno rejects it and launches keep the older signed digest.
3. Rerun the workflow. Two failed nights in a row is a page for the security officer: the fix deadlines in ADR-0063 still run.

## Trivy HIGH/CRITICAL triage

The scan fails on any HIGH or CRITICAL finding, including ones with no fix yet (`ignore-unfixed: false`).

1. Read the table: package, installed and fixed version.
2. Fix available: rebuild picks it up if the base image or apt source has it. Otherwise bump the package or base image. Deadlines: critical 24 h (recycle), high 7 d, medium 30 d, low 90 d.
3. No fix available: do not ignore it silently. Open an issue with the CVE, impact and mitigation, and escalate to the security officer.
4. `.trivyignore` policy (repo root, read by the workflow):
   - Add only a genuine false positive or an un-actionable finding. Never suppress a real, fixable vulnerability.
   - One CVE per line with a comment: why, who approved, review date.
   - Entries go through a reviewed PR and are re-checked each quarter. Remove an entry once it no longer applies.

## Kyverno rejection debugging

Applies to Pods in namespaces labelled `styx.io/desktop=true`. Policy `styx-signed-images` has two rules.

1. Get the message from the failing Pod or its controller:
   ```bash
   kubectl -n <ns> describe pod <pod>
   kubectl -n <ns> get events --sort-by=.lastTimestamp | tail
   ```
2. By rule:
   - `require-allowlisted-digest`: the image must be `harbor.example.internal/styx/<name>@sha256:<digest>`. A tag or another registry or project is refused. Check the template image and that `HARBOR_URL` is set so the portal pins the digest at launch.
   - `verify-signature`: the digest has no valid cosign signature for the configured key. Check that the nightly Sign step succeeded for that digest and that the policy public key matches the current key (after rotation, see ADR-0063).
3. Verify by hand:
   ```bash
   cosign verify --key <public-key-file> --insecure-ignore-tlog harbor.example.internal/styx/desktop@sha256:<digest>
   ```
4. If the portal pinned an old digest, relaunch: the launch picks the newest signed artifact. If Harbor was unreachable at launch, the configured ref was used and Kyverno refused it (fail open by design, ADR-0069).
5. Never switch the policy to Audit to get a session through. Fix the signature or the ref.

## Forced recycle and how to verify

Normal path: the leader loop warns the user on the first CRITICAL for the instance's digest, then stops the instance 24 h later (`CVE_RECYCLE_GRACE_H`). The loop runs every `CVE_RECYCLE_INTERVAL_S` (3600 s).

To force one earlier:

1. Ship the patched image: rerun the nightly workflow and confirm Sign succeeded.
2. Stop the affected sessions from the admin UI (instances list), or set `recycle_deadline` in the past for the instance; the next pass stops it. Users relaunch onto the newest signed digest.

Verify:

- Backend logs: `harbor vulnerability lookup failed` means Harbor errors (nothing is stopped while that persists, so fix Harbor first).
- Session events: `cve_warned` when the deadline was set, `cve_recycled` when the instance was stopped.
- After relaunch, the instance image digest equals the newest signed artifact in Harbor, and Harbor's report for that digest shows no CRITICAL.
- Only the leader replica runs the loop; check the leader as in [leader election](../../operate/leader-election.md).

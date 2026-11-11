# kind spikes via CI

Agents have no Docker. Push scripts here; the `kind-spike` workflow
(`.github/workflows/kind-spike.yml`) runs them against a fresh kind cluster on a GitHub-hosted runner.

## Contract

- Put executable (`chmod +x`) `scripts/kind/NN-name.sh` files here. Run in sorted order.
- Start with `#!/usr/bin/env bash` and `set -euo pipefail`. Non-zero exit = FAIL.
- A cluster named `spike` already exists; `kubectl` context points at it. Do not create/delete it.
- Optional cluster config: `test/kind/cluster.yaml` (kind `Cluster` config; used if present).
  Helper files/manifests go in `test/kind/`.
- cwd is the repo root. Each script has a 20 min timeout; whole job 45 min. Keep runs < 30 min.

## Tools on PATH

| Tool | Version |
|------|---------|
| kind | v0.33.0 |
| node image | kindest/node v1.35.8 (digest pinned) |
| kubectl | v1.35.4 |
| helm | v3.19.0 |
| docker, bash, curl, jq, git | runner defaults (ubuntu-latest) |

Other tools: install inside your script (public downloads are fine).
Loading images: `docker pull X && kind load docker-image X --name spike`, or let the cluster pull.

## Triggers

- Pull request to `dev`/`enterprise` touching `scripts/kind/**`, `test/kind/**` or the workflow:
  runs only changed scripts (all if `test/kind/**` or the workflow changed).
- Manual: Actions > kind-spike > Run workflow, optional `script` input (file name in `scripts/kind/`).

## Results

- Check name: `kind-spike` (pass/fail of the job).
- Job log ends with a summary (`PASS|FAIL script`) and the last 40 lines of each failed script.
- Artifact `kind-spike-out` (7 days): per-script logs, `summary.txt`, `diag/` (`kubectl get all -A`,
  events, describe/logs of non-running pods, `kind export logs`).
  To keep evidence for an MR, print what matters to stdout.

## Limits

- Hosted runner: 4 vCPU / 16 GB RAM / ~14 GB disk, Docker, internet. Single-node unless
  `test/kind/cluster.yaml` says otherwise.
- Public registries/downloads at run time are OK (unlike agent sandboxes).
- No registry pushes, no secrets, read-only `GITHUB_TOKEN` (`contents: read`).
- Loop devices / privileged pods work inside kind nodes (Docker privileged); no real block devices.

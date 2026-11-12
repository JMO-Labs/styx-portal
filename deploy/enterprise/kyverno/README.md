# Kyverno signed-image policy

`ClusterPolicy/styx-signed-images` (Enforce) applies to Pods in namespaces labelled
`styx.io/desktop=true`:

1. `require-allowlisted-digest`: every (init) container image must match
   `harbor.example.internal/styx/*@sha256:*` (allowlisted registry/repository, digest required).
2. `verify-signature`: images under that prefix must carry a valid cosign signature for the
   configured public key (`verifyDigest`, tlog/SCT checks off for key-based signing).

Replace the placeholder `REPLACE_WITH_COSIGN_PUBLIC_KEY` and the Harbor host at deploy time.
Install Kyverno from the pinned chart (3.5.2) before applying: `kubectl apply -k .`.

Test: `scripts/kind/01-kyverno-signed-images.sh` (CI `kind-spike`) and
`backend/tests/test_enterprise_kyverno.py`.

#!/usr/bin/env bash
# Phase 1 exit: HA demo (#103). Wrapper so the kind-spike workflow runs it;
# output lands in out/ha-demo/ and is uploaded with the kind-spike-out artifact.
set -euo pipefail
shellcheck scripts/enterprise/ha_demo.sh scripts/kind/30-ha-demo.sh
exec scripts/enterprise/ha_demo.sh

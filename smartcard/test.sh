#!/usr/bin/env bash
# Run the smartcard Go tests (needs network or a warm module cache for yaml.v3).
set -euo pipefail
cd "$(dirname "$0")"
go mod tidy
go vet ./...
go test ./... "$@"

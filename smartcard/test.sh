#!/usr/bin/env bash
# Run the smartcard Go tests (needs network or a warm module cache for deps).
set -euo pipefail
cd "$(dirname "$0")"
# go.sum is committed: verify it, never rewrite it (drift fails CI).
export GOFLAGS=-mod=readonly
go mod download
go mod verify
go vet ./...
go test ./... "$@"
# The helper must also cross-compile for Windows.
GOOS=windows GOARCH=amd64 go build -o /dev/null ./cmd/styx-card-helper
# unsafeptr off for Windows: the cert store converts a crypt32-owned
# PCCERT_CONTEXT (uintptr from a syscall) to a Go pointer, which vet flags.
GOOS=windows GOARCH=amd64 go vet -unsafeptr=false ./...

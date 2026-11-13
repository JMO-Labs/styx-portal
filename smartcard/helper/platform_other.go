//go:build !windows

package helper

import "errors"

// Platform bundles the OS-specific implementations.
type Platform struct {
	Card      Card
	Certs     CertStore
	Confirmer Confirmer
}

// NewPlatform is only implemented on Windows.
func NewPlatform() (*Platform, error) {
	return nil, errors.New("styx-card-helper is only supported on Windows")
}

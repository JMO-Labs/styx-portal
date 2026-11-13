//go:build windows

package helper

// Platform bundles the OS-specific implementations.
type Platform struct {
	Card      Card
	Certs     CertStore
	Confirmer Confirmer
}

// NewPlatform returns the PC/SC card, Windows cert store and MessageBox confirmer.
func NewPlatform() (*Platform, error) {
	card, err := openPCSC()
	if err != nil {
		return nil, err
	}
	return &Platform{Card: card, Certs: winCertStore{}, Confirmer: msgBoxConfirmer{}}, nil
}

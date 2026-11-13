package helper

import (
	"context"
	"crypto/tls"
	"time"

	"github.com/JMO-Labs/styx-portal/smartcard/apdu"
)

// Status words returned when the helper itself answers.
var (
	swDenied    = []byte{0x6D, 0x00} // INS not supported (allowlist deny)
	swNotAuth   = []byte{0x69, 0x82} // security status not satisfied (user said no)
	swCardError = []byte{0x6F, 0x00} // no precise diagnosis (reader failure)
)

// Card transmits one command APDU to the physical card (PC/SC).
type Card interface {
	Transmit(apdu []byte) ([]byte, error)
}

// Confirmer asks the user to approve a signing operation for a desktop.
// Implementations must return promptly when ctx is done.
type Confirmer interface {
	Confirm(ctx context.Context, desktop string) (bool, error)
}

// CertStore selects the client certificate (smart-card cert) for mTLS.
type CertStore interface {
	ClientCert() (tls.Certificate, error)
}

// DefaultConfirmTimeout is how long the user has to answer a prompt.
const DefaultConfirmTimeout = 30 * time.Second

// Handler applies the allowlist and confirmation policy to relay APDUs.
type Handler struct {
	Policy         *apdu.Policy
	Card           Card
	Confirmer      Confirmer
	Desktop        string
	ConfirmTimeout time.Duration
}

func (h *Handler) timeout() time.Duration {
	if h.ConfirmTimeout > 0 {
		return h.ConfirmTimeout
	}
	return DefaultConfirmTimeout
}

// Handle returns the response APDU for one command. Fails closed.
func (h *Handler) Handle(ctx context.Context, cmd []byte) []byte {
	switch h.Policy.Check(cmd) {
	case apdu.Allow:
	case apdu.AllowNeedsUserConfirm:
		if !h.confirm(ctx) {
			return swNotAuth
		}
	default:
		return swDenied
	}
	resp, err := h.Card.Transmit(cmd)
	if err != nil {
		return swCardError
	}
	return resp
}

func (h *Handler) confirm(ctx context.Context) bool {
	if h.Confirmer == nil {
		return false
	}
	cctx, cancel := context.WithTimeout(ctx, h.timeout())
	defer cancel()
	type result struct {
		ok  bool
		err error
	}
	ch := make(chan result, 1)
	go func() {
		ok, err := h.Confirmer.Confirm(cctx, h.Desktop)
		ch <- result{ok, err}
	}()
	select {
	case r := <-ch:
		return r.err == nil && r.ok && cctx.Err() == nil
	case <-cctx.Done():
		return false
	}
}

package helper

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/JMO-Labs/styx-portal/smartcard/apdu"
)

func TestParseURI(t *testing.T) {
	host, tok, err := ParseURI("styx-card://connect?host=desk.example.mil&token=abc")
	if err != nil || host != "desk.example.mil" || tok != "abc" {
		t.Fatalf("got %q %q %v", host, tok, err)
	}
	for _, bad := range []string{
		"https://connect?host=a&token=b",
		"styx-card://other?host=a&token=b",
		"styx-card://connect?host=a",
		"styx-card://connect?token=b",
		"::",
	} {
		if _, _, err := ParseURI(bad); err == nil {
			t.Errorf("expected error for %q", bad)
		}
	}
}

func TestHostAllowed(t *testing.T) {
	suffixes := []string{"example.mil", ".corp.test"}
	ok := []string{"desk.example.mil", "a.b.example.mil", "x.corp.test"}
	bad := []string{"example.mil.evil.com", "evilexample.mil", "example.mil", "desk.example.mil:443@evil.com", "", "evil.com/x", "a.example.mil:99999"}
	for _, h := range ok {
		if !HostAllowed(h, suffixes) {
			t.Errorf("want allowed: %q", h)
		}
	}
	for _, h := range bad {
		if HostAllowed(h, suffixes) {
			t.Errorf("want denied: %q", h)
		}
	}
	if HostAllowed("desk.example.mil", nil) {
		t.Error("empty suffix list must deny")
	}
}

func TestDialURL(t *testing.T) {
	u, err := DialURL("desk.example.mil", "t k")
	if err != nil || u != "wss://desk.example.mil/smartcard?token=t+k" {
		t.Fatalf("got %q %v", u, err)
	}
}

type fakeCard struct {
	calls [][]byte
	resp  []byte
	err   error
}

func (f *fakeCard) Transmit(a []byte) ([]byte, error) {
	f.calls = append(f.calls, a)
	return f.resp, f.err
}

type fakeConfirmer struct {
	ok    bool
	err   error
	desk  string
	calls int
	block bool
}

func (f *fakeConfirmer) Confirm(ctx context.Context, desktop string) (bool, error) {
	f.calls++
	f.desk = desktop
	if f.block {
		<-ctx.Done()
		return false, ctx.Err()
	}
	return f.ok, f.err
}

func policy(t *testing.T) *apdu.Policy {
	t.Helper()
	p, err := apdu.Load("../apdu-allowlist.yaml")
	if err != nil {
		t.Fatal(err)
	}
	return p
}

var (
	selectAPDU = []byte{0x00, 0xA4, 0x04, 0x00}
	signAPDU   = []byte{0x00, 0x87, 0x07, 0x9A}
	badAPDU    = []byte{0x80, 0xE6, 0x00, 0x00}
)

func TestDeniedReturns6D00(t *testing.T) {
	c := &fakeCard{resp: []byte{0x90, 0x00}}
	h := &Handler{Policy: policy(t), Card: c, Confirmer: &fakeConfirmer{ok: true}, Desktop: "d"}
	got := h.Handle(context.Background(), badAPDU)
	if string(got) != "\x6d\x00" || len(c.calls) != 0 {
		t.Fatalf("got %x calls=%d", got, len(c.calls))
	}
}

func TestAllowedPassesThrough(t *testing.T) {
	c := &fakeCard{resp: []byte{0xAA, 0x90, 0x00}}
	cf := &fakeConfirmer{}
	h := &Handler{Policy: policy(t), Card: c, Confirmer: cf, Desktop: "d"}
	got := h.Handle(context.Background(), selectAPDU)
	if string(got) != "\xaa\x90\x00" || len(c.calls) != 1 || cf.calls != 0 {
		t.Fatalf("got %x calls=%d confirm=%d", got, len(c.calls), cf.calls)
	}
}

func TestCardErrorReturns6F00(t *testing.T) {
	h := &Handler{Policy: policy(t), Card: &fakeCard{err: errors.New("x")}, Confirmer: &fakeConfirmer{}}
	if got := h.Handle(context.Background(), selectAPDU); string(got) != "\x6f\x00" {
		t.Fatalf("got %x", got)
	}
}

func TestSigningConfirmed(t *testing.T) {
	c := &fakeCard{resp: []byte{0x90, 0x00}}
	cf := &fakeConfirmer{ok: true}
	h := &Handler{Policy: policy(t), Card: c, Confirmer: cf, Desktop: "desk.example.mil"}
	got := h.Handle(context.Background(), signAPDU)
	if string(got) != "\x90\x00" || len(c.calls) != 1 || cf.desk != "desk.example.mil" {
		t.Fatalf("got %x calls=%d desk=%q", got, len(c.calls), cf.desk)
	}
}

func TestSigningDeclinedReturns6982(t *testing.T) {
	c := &fakeCard{resp: []byte{0x90, 0x00}}
	h := &Handler{Policy: policy(t), Card: c, Confirmer: &fakeConfirmer{ok: false}}
	got := h.Handle(context.Background(), signAPDU)
	if string(got) != "\x69\x82" || len(c.calls) != 0 {
		t.Fatalf("got %x calls=%d", got, len(c.calls))
	}
}

func TestSigningConfirmErrorReturns6982(t *testing.T) {
	c := &fakeCard{}
	h := &Handler{Policy: policy(t), Card: c, Confirmer: &fakeConfirmer{err: errors.New("x"), ok: true}}
	if got := h.Handle(context.Background(), signAPDU); string(got) != "\x69\x82" || len(c.calls) != 0 {
		t.Fatalf("got %x", got)
	}
}

func TestSigningTimeoutReturns6982(t *testing.T) {
	c := &fakeCard{}
	cf := &fakeConfirmer{block: true}
	h := &Handler{Policy: policy(t), Card: c, Confirmer: cf, ConfirmTimeout: 20 * time.Millisecond}
	if got := h.Handle(context.Background(), signAPDU); string(got) != "\x69\x82" || len(c.calls) != 0 {
		t.Fatalf("got %x", got)
	}
}

func TestDefaultConfirmTimeout(t *testing.T) {
	if (&Handler{}).timeout() != 30*time.Second {
		t.Fatal("default must be 30s")
	}
}

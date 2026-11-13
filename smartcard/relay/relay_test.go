package relay

import (
	"encoding/binary"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/JMO-Labs/styx-portal/smartcard/apdu"
	"github.com/gorilla/websocket"
)

const goodToken = "tok-ok"

var (
	selectAPDU = []byte{0x00, 0xA4, 0x04, 0x00, 0x02, 0xAA, 0xBB}
	denyAPDU   = []byte{0x80, 0xE6, 0x00, 0x00, 0x00}
)

type redeemReq struct {
	Token      string `json:"token"`
	InstanceID string `json:"instance_id"`
}

// fakeBackend accepts goodToken only for instance "inst-1" with a cert header.
func fakeBackend(t *testing.T, gotCert *string) *httptest.Server {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var q redeemReq
		_ = json.NewDecoder(r.Body).Decode(&q)
		if gotCert != nil {
			*gotCert = r.Header.Get("Client-Cert")
		}
		if r.URL.Path != "/api/smartcard/redeem" || q.Token != goodToken ||
			q.InstanceID != "inst-1" || r.Header.Get("Client-Cert") == "" {
			w.WriteHeader(http.StatusForbidden)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(s.Close)
	return s
}

// vpcdConn is the fake vpcd side: it drives commands and reads the vicc's replies.
type vpcdConn struct{ c net.Conn }

func (v vpcdConn) send(t *testing.T, p []byte) []byte {
	t.Helper()
	f := append([]byte{byte(len(p) >> 8), byte(len(p))}, p...)
	if _, err := v.c.Write(f); err != nil {
		t.Fatal(err)
	}
	return v.recv(t)
}

func (v vpcdConn) recv(t *testing.T) []byte {
	t.Helper()
	_ = v.c.SetReadDeadline(time.Now().Add(2 * time.Second))
	var h [2]byte
	if _, err := io.ReadFull(v.c, h[:]); err != nil {
		t.Fatal(err)
	}
	b := make([]byte, binary.BigEndian.Uint16(h[:]))
	if _, err := io.ReadFull(v.c, b); err != nil {
		t.Fatal(err)
	}
	return b
}

// fakeVPCD listens like vpcd; the relay (vicc) connects and receives accepted conns.
func fakeVPCD(t *testing.T) (string, chan vpcdConn) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	conns := make(chan vpcdConn, 4)
	t.Cleanup(func() { l.Close() })
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			t.Cleanup(func() { c.Close() })
			conns <- vpcdConn{c}
		}
	}()
	return l.Addr().String(), conns
}

func waitVPCD(t *testing.T, conns chan vpcdConn) vpcdConn {
	t.Helper()
	select {
	case v := <-conns:
		return v
	case <-time.After(2 * time.Second):
		t.Fatal("relay did not connect to vpcd")
		return vpcdConn{}
	}
}

// helperEcho answers every forwarded APDU with 9000 and reports it.
func helperEcho(c *websocket.Conn, got chan []byte) {
	go func() {
		for {
			_, m, err := c.ReadMessage()
			if err != nil {
				return
			}
			got <- m
			_ = c.WriteMessage(websocket.BinaryMessage, []byte{0x90, 0x00})
		}
	}()
}

func policy(t *testing.T) *apdu.Policy {
	p, err := apdu.Load("../apdu-allowlist.yaml")
	if err != nil {
		t.Fatal(err)
	}
	if p.Check(selectAPDU) != apdu.Allow || p.Check(denyAPDU) != apdu.Deny {
		t.Fatal("allowlist fixtures do not match test APDUs")
	}
	return p
}

func start(t *testing.T, backendURL, vpcd, inst string) *httptest.Server {
	h := New(Config{Policy: policy(t), BackendURL: backendURL, InstanceID: inst, VPCDAddr: vpcd})
	s := httptest.NewServer(h)
	t.Cleanup(s.Close)
	return s
}

func dial(s *httptest.Server, token string) (*websocket.Conn, *http.Response, error) {
	u := "ws" + strings.TrimPrefix(s.URL, "http") + "/?token=" + token
	return websocket.DefaultDialer.Dial(u, http.Header{"Client-Cert": {"MIIB"}})
}

func expectClosed(t *testing.T, c *websocket.Conn) {
	t.Helper()
	_ = c.SetReadDeadline(time.Now().Add(2 * time.Second))
	if _, _, err := c.ReadMessage(); err == nil {
		t.Fatal("expected close, got message")
	}
}

func expectRejected(t *testing.T, s *httptest.Server, token string, conns chan vpcdConn) {
	t.Helper()
	_, resp, err := dial(s, token)
	if err == nil || resp == nil || resp.StatusCode != http.StatusForbidden {
		t.Fatalf("expected 403, got %v %v", err, resp)
	}
	select {
	case <-conns:
		t.Fatal("vpcd dialed after failed redeem")
	case <-time.After(100 * time.Millisecond):
	}
}

func TestRedeemFailureRejectedBeforeUpgrade(t *testing.T) {
	vpcd, conns := fakeVPCD(t)
	s := start(t, fakeBackend(t, nil).URL, vpcd, "inst-1")
	expectRejected(t, s, "bad", conns)
}

func TestCrossSessionTokenRejected(t *testing.T) {
	vpcd, conns := fakeVPCD(t)
	s := start(t, fakeBackend(t, nil).URL, vpcd, "inst-2") // token minted for inst-1
	expectRejected(t, s, goodToken, conns)
}

func TestUnauthenticatedDoesNotHoldSlot(t *testing.T) {
	vpcd, conns := fakeVPCD(t)
	s := start(t, fakeBackend(t, nil).URL, vpcd, "inst-1")
	expectRejected(t, s, "bad", conns)
	c, _, err := dial(s, goodToken)
	if err != nil {
		t.Fatal(err)
	}
	c.Close()
}

func TestCertForwardedToBackend(t *testing.T) {
	var mu sync.Mutex
	var cert string
	b := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		cert = r.Header.Get("Client-Cert")
		mu.Unlock()
	}))
	defer b.Close()
	vpcd, _ := fakeVPCD(t)
	s := start(t, b.URL, vpcd, "inst-1")
	c, _, err := dial(s, goodToken)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	mu.Lock()
	defer mu.Unlock()
	if cert != "MIIB" {
		t.Fatalf("client cert not forwarded: %q", cert)
	}
}

func TestVPCDDrivenFlow(t *testing.T) {
	vpcd, conns := fakeVPCD(t)
	s := start(t, fakeBackend(t, nil).URL, vpcd, "inst-1")
	c, _, err := dial(s, goodToken)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	got := make(chan []byte, 8)
	helperEcho(c, got)
	v := waitVPCD(t, conns)

	if atr := v.send(t, []byte{0x04}); string(atr) != string(defaultATR) {
		t.Fatalf("ATR = %x", atr)
	}
	// power on / reset have no reply; the next command must still be answered.
	for _, ctl := range []byte{0x01, 0x02} {
		_, _ = v.c.Write([]byte{0x00, 0x01, ctl})
	}
	select {
	case m := <-got:
		t.Fatalf("control frame forwarded to helper: %x", m)
	case <-time.After(100 * time.Millisecond):
	}

	if r := v.send(t, denyAPDU); string(r) != "\x6d\x00" {
		t.Fatalf("deny response = %x", r)
	}
	select {
	case m := <-got:
		t.Fatalf("denied APDU reached helper: %x", m)
	case <-time.After(100 * time.Millisecond):
	}

	if r := v.send(t, selectAPDU); string(r) != "\x90\x00" {
		t.Fatalf("allow response = %x", r)
	}
	if m := <-got; string(m) != string(selectAPDU) {
		t.Fatalf("helper got %x", m)
	}
}

func TestHelperDisconnectClosesVPCD(t *testing.T) {
	vpcd, conns := fakeVPCD(t)
	s := start(t, fakeBackend(t, nil).URL, vpcd, "inst-1")
	c, _, err := dial(s, goodToken)
	if err != nil {
		t.Fatal(err)
	}
	v := waitVPCD(t, conns)
	c.Close()
	_ = v.c.SetReadDeadline(time.Now().Add(2 * time.Second))
	if _, err := v.c.Read(make([]byte, 1)); err == nil {
		t.Fatal("expected vpcd conn closed")
	}
}

func TestSecondConnectionRefused(t *testing.T) {
	vpcd, _ := fakeVPCD(t)
	s := start(t, fakeBackend(t, nil).URL, vpcd, "inst-1")
	c1, _, err := dial(s, goodToken)
	if err != nil {
		t.Fatal(err)
	}
	defer c1.Close()
	_, resp, err := dial(s, goodToken)
	if err == nil || resp == nil || resp.StatusCode != http.StatusConflict {
		t.Fatalf("second connection not refused: %v %v", err, resp)
	}
	c1.Close()
	time.Sleep(200 * time.Millisecond)
	c3, _, err := dial(s, goodToken)
	if err != nil {
		t.Fatalf("slot not released: %v", err)
	}
	c3.Close()
}

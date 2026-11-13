package relay

import (
	"encoding/binary"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
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

// fakeVPCD echoes a fixed response (9000) to each framed APDU and records them.
func fakeVPCD(t *testing.T) (string, chan []byte) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { l.Close() })
	got := make(chan []byte, 8)
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			go func() {
				defer c.Close()
				for {
					var h [2]byte
					if _, err := io.ReadFull(c, h[:]); err != nil {
						return
					}
					b := make([]byte, binary.BigEndian.Uint16(h[:]))
					if _, err := io.ReadFull(c, b); err != nil {
						return
					}
					got <- b
					_, _ = c.Write([]byte{0x00, 0x02, 0x90, 0x00})
				}
			}()
		}
	}()
	return l.Addr().String(), got
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

func TestRedeemFailureClosesBeforeAPDU(t *testing.T) {
	vpcd, got := fakeVPCD(t)
	s := start(t, fakeBackend(t, nil).URL, vpcd, "inst-1")
	c, _, err := dial(s, "bad")
	if err != nil {
		t.Fatal(err)
	}
	_ = c.WriteMessage(websocket.BinaryMessage, selectAPDU)
	expectClosed(t, c)
	select {
	case <-got:
		t.Fatal("APDU forwarded after failed redeem")
	case <-time.After(100 * time.Millisecond):
	}
}

func TestCrossSessionTokenRejected(t *testing.T) {
	vpcd, got := fakeVPCD(t)
	s := start(t, fakeBackend(t, nil).URL, vpcd, "inst-2") // token minted for inst-1
	c, _, err := dial(s, goodToken)
	if err != nil {
		t.Fatal(err)
	}
	_ = c.WriteMessage(websocket.BinaryMessage, selectAPDU)
	expectClosed(t, c)
	if len(got) != 0 {
		t.Fatal("APDU forwarded for foreign token")
	}
}

func TestAllowedForwardedDeniedBlocked(t *testing.T) {
	var cert string
	vpcd, got := fakeVPCD(t)
	s := start(t, fakeBackend(t, &cert).URL, vpcd, "inst-1")
	c, _, err := dial(s, goodToken)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if cert != "MIIB" {
		t.Fatalf("client cert not forwarded: %q", cert)
	}

	_ = c.WriteMessage(websocket.BinaryMessage, denyAPDU)
	_, m, err := c.ReadMessage()
	if err != nil || string(m) != "\x6d\x00" {
		t.Fatalf("deny response = %x, %v", m, err)
	}
	if len(got) != 0 {
		t.Fatal("denied APDU reached vpcd")
	}

	_ = c.WriteMessage(websocket.BinaryMessage, selectAPDU)
	_, m, err = c.ReadMessage()
	if err != nil || string(m) != "\x90\x00" {
		t.Fatalf("allow response = %x, %v", m, err)
	}
	if b := <-got; string(b) != string(selectAPDU) {
		t.Fatalf("vpcd got %x", b)
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

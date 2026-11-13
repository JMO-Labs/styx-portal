// Package relay bridges the helper's WebSocket to the local vpcd
// (virtualsmartcard vicc protocol: 2-byte big-endian length + payload).
package relay

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/url"
	"sync/atomic"
	"time"

	"github.com/JMO-Labs/styx-portal/smartcard/apdu"
	"github.com/gorilla/websocket"
)

// SWDenied is returned for APDUs the allowlist refuses (INS not supported).
var SWDenied = []byte{0x6D, 0x00}

const maxAPDU = 65544

// Config configures the relay.
type Config struct {
	Policy     *apdu.Policy
	BackendURL string // base URL of the portal backend
	InstanceID string // this desktop's instance id
	VPCDAddr   string // host:port of vpcd (35963)
	HTTPClient *http.Client
}

// Handler is the relay's HTTP handler. One helper at a time.
type Handler struct {
	cfg  Config
	busy atomic.Bool
	up   websocket.Upgrader
}

// New builds a Handler.
func New(cfg Config) *Handler {
	if cfg.HTTPClient == nil {
		cfg.HTTPClient = &http.Client{Timeout: 5 * time.Second}
	}
	return &Handler{cfg: cfg, up: websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if !h.busy.CompareAndSwap(false, true) {
		http.Error(w, "helper already connected", http.StatusConflict)
		return
	}
	defer h.busy.Store(false)

	ws, err := h.up.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	defer ws.Close()
	ws.SetReadLimit(maxAPDU)

	if err := h.redeem(r); err != nil {
		_ = ws.WriteControl(websocket.CloseMessage,
			websocket.FormatCloseMessage(websocket.ClosePolicyViolation, "unauthorized"),
			time.Now().Add(time.Second))
		return
	}
	vc, err := net.DialTimeout("tcp", h.cfg.VPCDAddr, 5*time.Second)
	if err != nil {
		_ = ws.WriteControl(websocket.CloseMessage,
			websocket.FormatCloseMessage(websocket.CloseInternalServerErr, "vpcd unavailable"),
			time.Now().Add(time.Second))
		return
	}
	defer vc.Close()
	h.pump(r.Context(), ws, vc)
}

func (h *Handler) redeem(r *http.Request) error {
	body, _ := json.Marshal(map[string]string{
		"token":       r.URL.Query().Get("token"),
		"instance_id": h.cfg.InstanceID,
	})
	u, err := url.JoinPath(h.cfg.BackendURL, "/api/smartcard/redeem")
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(r.Context(), http.MethodPost, u, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Client-Cert", r.Header.Get("Client-Cert"))
	resp, err := h.cfg.HTTPClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)
	if resp.StatusCode != http.StatusOK {
		return io.ErrUnexpectedEOF
	}
	return nil
}

func (h *Handler) pump(_ context.Context, ws *websocket.Conn, vc net.Conn) {
	for {
		mt, msg, err := ws.ReadMessage()
		if err != nil {
			return
		}
		if mt != websocket.BinaryMessage {
			continue
		}
		reply := SWDenied
		// AllowNeedsUserConfirm is forwarded: the helper owns the user prompt.
		if h.cfg.Policy.Check(msg) != apdu.Deny {
			if reply, err = exchange(vc, msg); err != nil {
				return
			}
		}
		if err := ws.WriteMessage(websocket.BinaryMessage, reply); err != nil {
			return
		}
	}
}

// exchange sends one framed APDU to vpcd and reads the framed response.
func exchange(c net.Conn, a []byte) ([]byte, error) {
	_ = c.SetDeadline(time.Now().Add(30 * time.Second))
	frame := make([]byte, 2+len(a))
	binary.BigEndian.PutUint16(frame, uint16(len(a)))
	copy(frame[2:], a)
	if _, err := c.Write(frame); err != nil {
		return nil, err
	}
	var hdr [2]byte
	if _, err := io.ReadFull(c, hdr[:]); err != nil {
		return nil, err
	}
	resp := make([]byte, binary.BigEndian.Uint16(hdr[:]))
	_, err := io.ReadFull(c, resp)
	return resp, err
}

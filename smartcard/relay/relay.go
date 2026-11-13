// Package relay bridges the helper's WebSocket to the local vpcd
// (virtualsmartcard vicc protocol: 2-byte big-endian length + payload).
package relay

import (
	"bytes"
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

// vpcd control frames (1 byte).
const (
	ctlOff   = 0x00
	ctlOn    = 0x01
	ctlReset = 0x02
	ctlATR   = 0x04
)

// defaultATR is a generic T=1 ATR used when Config.ATR is unset.
var defaultATR = []byte{0x3B, 0x80, 0x80, 0x01, 0x01}

// Config configures the relay.
type Config struct {
	Policy     *apdu.Policy
	BackendURL string // base URL of the portal backend
	InstanceID string // this desktop's instance id
	VPCDAddr   string // host:port of vpcd (35963)
	ATR        []byte // answer to vpcd ATR requests (default generic T=1)
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
	return &Handler{cfg: cfg, up: websocket.Upgrader{} // default CheckOrigin: same-origin or no Origin (native helper)}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// Authenticate before anything else: no upgrade, no slot, no vpcd dial.
	if err := h.redeem(r); err != nil {
		http.Error(w, "unauthorized", http.StatusForbidden)
		return
	}
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

	vc, err := net.DialTimeout("tcp", h.cfg.VPCDAddr, 5*time.Second)
	if err != nil {
		_ = ws.WriteControl(websocket.CloseMessage,
			websocket.FormatCloseMessage(websocket.CloseInternalServerErr, "vpcd unavailable"),
			time.Now().Add(time.Second))
		return
	}
	defer vc.Close()
	h.pump(ws, vc)
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

// pump acts as the vicc: vpcd drives (APDUs from desktop apps via PC/SC),
// the helper on the client holds the card.
func (h *Handler) pump(ws *websocket.Conn, vc net.Conn) {
	replies := make(chan []byte)
	go func() { // helper replies; on helper disconnect, unblock the vpcd read
		defer vc.Close()
		defer close(replies)
		for {
			mt, msg, err := ws.ReadMessage()
			if err != nil {
				return
			}
			if mt == websocket.BinaryMessage {
				replies <- msg
			}
		}
	}()
	for {
		cmd, err := readFrame(vc)
		if err != nil {
			return
		}
		var resp []byte
		switch {
		case len(cmd) == 1: // vpcd control frame
			switch cmd[0] {
			case ctlATR:
				resp = h.atr()
			default: // power off/on, reset: nothing to answer
				continue
			}
		case h.cfg.Policy.Check(cmd) == apdu.Deny:
			resp = SWDenied
		default:
			// AllowNeedsUserConfirm is forwarded: the helper owns the user prompt.
			if err := ws.WriteMessage(websocket.BinaryMessage, cmd); err != nil {
				return
			}
			select {
			case r, ok := <-replies:
				if !ok {
					return
				}
				resp = r
			case <-time.After(30 * time.Second):
				return
			}
		}
		if err := writeFrame(vc, resp); err != nil {
			return
		}
	}
}

func (h *Handler) atr() []byte {
	if len(h.cfg.ATR) > 0 {
		return h.cfg.ATR
	}
	return defaultATR
}

func readFrame(c net.Conn) ([]byte, error) {
	var hdr [2]byte
	if _, err := io.ReadFull(c, hdr[:]); err != nil {
		return nil, err
	}
	b := make([]byte, binary.BigEndian.Uint16(hdr[:]))
	_, err := io.ReadFull(c, b)
	return b, err
}

func writeFrame(c net.Conn, p []byte) error {
	_ = c.SetWriteDeadline(time.Now().Add(30 * time.Second))
	f := make([]byte, 2+len(p))
	binary.BigEndian.PutUint16(f, uint16(len(p)))
	copy(f[2:], p)
	_, err := c.Write(f)
	return err
}

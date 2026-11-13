package helper

import (
	"context"
	"crypto/tls"
	"errors"
	"io"
	"net/http"

	"github.com/gorilla/websocket"
)

type wsConn struct{ c *websocket.Conn }

func (w wsConn) ReadFrame() (Frame, error) {
	var f Frame
	if err := w.c.ReadJSON(&f); err != nil {
		if websocket.IsCloseError(err, websocket.CloseNormalClosure, websocket.CloseGoingAway) {
			return f, io.EOF
		}
		return f, err
	}
	return f, nil
}

func (w wsConn) WriteFrame(f Frame) error { return w.c.WriteJSON(f) }

// Dial opens the mTLS WebSocket to the relay, presenting the cert from store.
// The caller must have validated host with HostAllowed.
func Dial(ctx context.Context, host, token string, store CertStore) (Conn, func() error, error) {
	if store == nil {
		return nil, nil, errors.New("no cert store")
	}
	cert, err := store.ClientCert()
	if err != nil {
		return nil, nil, err
	}
	u, err := DialURL(host, token)
	if err != nil {
		return nil, nil, err
	}
	d := websocket.Dialer{
		TLSClientConfig: &tls.Config{
			MinVersion:   tls.VersionTLS12,
			ServerName:   host,
			Certificates: []tls.Certificate{cert},
		},
	}
	c, _, err := d.DialContext(ctx, u, http.Header{})
	if err != nil {
		return nil, nil, err
	}
	return wsConn{c}, c.Close, nil
}

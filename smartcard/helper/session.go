package helper

import (
	"context"
	"encoding/hex"
	"io"
)

var errEOF = io.EOF

// Frame is one relay message: a command from the relay or our response.
// Data is hex-encoded APDU bytes.
type Frame struct {
	ID   uint64 `json:"id"`
	Data string `json:"data"`
}

// Conn is a framed connection to the relay.
type Conn interface {
	ReadFrame() (Frame, error)
	WriteFrame(Frame) error
}

// Serve answers relay frames until the connection ends. A clean close
// (io.EOF) returns nil.
func Serve(ctx context.Context, c Conn, h *Handler) error {
	for {
		f, err := c.ReadFrame()
		if err != nil {
			if err == io.EOF {
				return nil
			}
			return err
		}
		var resp []byte
		if cmd, derr := hex.DecodeString(f.Data); derr != nil {
			resp = swDenied
		} else {
			resp = h.Handle(ctx, cmd)
		}
		if err := c.WriteFrame(Frame{ID: f.ID, Data: hex.EncodeToString(resp)}); err != nil {
			return err
		}
	}
}

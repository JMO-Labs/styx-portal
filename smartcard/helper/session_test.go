package helper

import (
	"context"
	"errors"
	"testing"
	"time"
)

type fakeConn struct {
	in  []Frame
	out []Frame
}

func (c *fakeConn) ReadFrame() (Frame, error) {
	if len(c.in) == 0 {
		return Frame{}, errEOF
	}
	f := c.in[0]
	c.in = c.in[1:]
	return f, nil
}
func (c *fakeConn) WriteFrame(f Frame) error { c.out = append(c.out, f); return nil }

func TestServeRelaysFrames(t *testing.T) {
	c := &fakeCard{resp: []byte{0x90, 0x00}}
	h := &Handler{Policy: policy(t), Card: c, Confirmer: &fakeConfirmer{}}
	conn := &fakeConn{in: []Frame{
		{ID: 1, Data: "00a40400"},
		{ID: 2, Data: "80e60000"},
		{ID: 3, Data: "zz"},
	}}
	if err := Serve(context.Background(), conn, h); err != nil {
		t.Fatal(err)
	}
	want := []Frame{{ID: 1, Data: "9000"}, {ID: 2, Data: "6d00"}, {ID: 3, Data: "6d00"}}
	if len(conn.out) != 3 {
		t.Fatalf("out=%v", conn.out)
	}
	for i := range want {
		if conn.out[i] != want[i] {
			t.Errorf("frame %d: got %v want %v", i, conn.out[i], want[i])
		}
	}
	if len(c.calls) != 1 {
		t.Fatalf("card calls=%d", len(c.calls))
	}
}

// blockConn blocks in ReadFrame until Close is called.
type blockConn struct{ closed chan struct{} }

func (c *blockConn) ReadFrame() (Frame, error) {
	<-c.closed
	return Frame{}, errors.New("use of closed conn")
}

func (c *blockConn) WriteFrame(Frame) error { return nil }

func (c *blockConn) Close() error {
	close(c.closed)
	return nil
}

func TestServeStopsOnContextCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	conn := &blockConn{closed: make(chan struct{})}
	done := make(chan error, 1)
	go func() { done <- Serve(ctx, conn, &Handler{}) }()
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("err=%v want context.Canceled", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Serve did not return after ctx cancel")
	}
}

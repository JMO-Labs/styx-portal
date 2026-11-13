//go:build windows

package helper

import (
	"errors"
	"fmt"
	"syscall"
	"unsafe"
)

var (
	winscard         = syscall.NewLazyDLL("winscard.dll")
	pEstablish       = winscard.NewProc("SCardEstablishContext")
	pListReaders     = winscard.NewProc("SCardListReadersW")
	pConnect         = winscard.NewProc("SCardConnectW")
	pTransmit        = winscard.NewProc("SCardTransmit")
	scardShared      = 2
	scardProtocolT01 = 3
)

type scardIORequest struct{ Protocol, PciLength uint32 }

type pcscCard struct {
	handle uintptr
	pci    scardIORequest
}

func scardErr(op string, r uintptr) error { return fmt.Errorf("%s: SCARD error 0x%08x", op, uint32(r)) }

// openPCSC connects to the first reader that holds a card.
func openPCSC() (*pcscCard, error) {
	var ctx uintptr
	if r, _, _ := pEstablish.Call(0, 0, 0, uintptr(unsafe.Pointer(&ctx))); r != 0 {
		return nil, scardErr("SCardEstablishContext", r)
	}
	var n uint32
	if r, _, _ := pListReaders.Call(ctx, 0, 0, uintptr(unsafe.Pointer(&n))); r != 0 {
		return nil, scardErr("SCardListReaders", r)
	}
	buf := make([]uint16, n)
	if r, _, _ := pListReaders.Call(ctx, 0, uintptr(unsafe.Pointer(&buf[0])), uintptr(unsafe.Pointer(&n))); r != 0 {
		return nil, scardErr("SCardListReaders", r)
	}
	start := 0
	for i, c := range buf {
		if c != 0 {
			continue
		}
		if i > start {
			if card, err := connectReader(ctx, &buf[start]); err == nil {
				return card, nil
			}
		}
		start = i + 1
	}
	return nil, errors.New("no smart card found in any reader")
}

func connectReader(ctx uintptr, name *uint16) (*pcscCard, error) {
	var h uintptr
	var proto uint32
	r, _, _ := pConnect.Call(ctx, uintptr(unsafe.Pointer(name)), uintptr(scardShared),
		uintptr(scardProtocolT01), uintptr(unsafe.Pointer(&h)), uintptr(unsafe.Pointer(&proto)))
	if r != 0 {
		return nil, scardErr("SCardConnect", r)
	}
	return &pcscCard{handle: h, pci: scardIORequest{Protocol: proto, PciLength: 8}}, nil
}

// Transmit sends one command APDU and returns the response.
func (c *pcscCard) Transmit(cmd []byte) ([]byte, error) {
	if len(cmd) == 0 {
		return nil, errors.New("empty apdu")
	}
	recv := make([]byte, 65538)
	n := uint32(len(recv))
	r, _, _ := pTransmit.Call(c.handle, uintptr(unsafe.Pointer(&c.pci)),
		uintptr(unsafe.Pointer(&cmd[0])), uintptr(len(cmd)), 0,
		uintptr(unsafe.Pointer(&recv[0])), uintptr(unsafe.Pointer(&n)))
	if r != 0 {
		return nil, scardErr("SCardTransmit", r)
	}
	return recv[:n], nil
}

//go:build windows

package helper

import (
	"context"
	"fmt"
	"syscall"
	"unsafe"
)

var pMessageBoxTimeout = syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxTimeoutW")

const (
	mbYesNo      = 0x4
	mbIconQ      = 0x20
	mbDefNo      = 0x100
	mbSetFore    = 0x10000
	mbTopMost    = 0x40000
	idYes        = 6
	confirmMaxMs = 30000
)

type msgBoxConfirmer struct{}

// Confirm shows a Yes/No dialog naming the desktop; it auto-closes after 30 s.
func (msgBoxConfirmer) Confirm(ctx context.Context, desktop string) (bool, error) {
	text, err := syscall.UTF16PtrFromString(fmt.Sprintf(
		"The desktop %q wants to use your smart card to sign or authenticate.\n\nAllow this?", desktop))
	if err != nil {
		return false, err
	}
	title, _ := syscall.UTF16PtrFromString("Styx smart card")
	res := make(chan bool, 1)
	go func() {
		r, _, _ := pMessageBoxTimeout.Call(0, uintptr(unsafe.Pointer(text)), uintptr(unsafe.Pointer(title)),
			uintptr(mbYesNo|mbIconQ|mbDefNo|mbSetFore|mbTopMost), 0, confirmMaxMs)
		res <- r == idYes
	}()
	select {
	case ok := <-res:
		return ok, nil
	case <-ctx.Done():
		return false, ctx.Err()
	}
}

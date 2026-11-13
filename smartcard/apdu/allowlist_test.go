package apdu

import (
	"os"
	"path/filepath"
	"testing"
)

func load(t *testing.T) *Policy {
	t.Helper()
	p, err := Load(filepath.Join("..", "apdu-allowlist.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func TestCheck(t *testing.T) {
	p := load(t)
	ext := append([]byte{0x00, 0x87, 0x07, 0x9A, 0x00, 0x00, 0x02}, 0xAA, 0xBB)
	cases := []struct {
		name string
		in   []byte
		want Decision
	}{
		{"select case4", []byte{0x00, 0xA4, 0x04, 0x00, 0x02, 0x61, 0x11, 0x00}, Allow},
		{"select case3", []byte{0x00, 0xA4, 0x04, 0x00, 0x02, 0x61, 0x11}, Allow},
		{"get response case2", []byte{0x00, 0xC0, 0x00, 0x00, 0x10}, Allow},
		{"case1", []byte{0x00, 0xC0, 0x00, 0x00}, Allow},
		{"get data", []byte{0x00, 0xCB, 0x3F, 0xFF, 0x05, 0x5C, 0x03, 0x5F, 0xC1, 0x05, 0x00}, Allow},
		{"verify", []byte{0x00, 0x20, 0x00, 0x80, 0x02, 0x31, 0x32}, Allow},
		{"gen auth signs", []byte{0x00, 0x87, 0x07, 0x9A, 0x01, 0xAA}, AllowNeedsUserConfirm},
		{"gen auth chained", []byte{0x10, 0x87, 0x07, 0x9A, 0x01, 0xAA}, AllowNeedsUserConfirm},
		{"gen auth extended", ext, AllowNeedsUserConfirm},
		{"put data denied", []byte{0x00, 0xDB, 0x3F, 0xFF, 0x01, 0x00}, Deny},
		{"unknown cla", []byte{0x80, 0xA4, 0x04, 0x00}, Deny},
		{"empty", nil, Deny},
		{"short", []byte{0x00, 0xA4, 0x04}, Deny},
		{"lc exceeds data", []byte{0x00, 0xA4, 0x04, 0x00, 0x05, 0x01}, Deny},
		{"trailing garbage", []byte{0x00, 0xA4, 0x04, 0x00, 0x01, 0x01, 0x00, 0x00}, Deny},
		{"extended truncated", []byte{0x00, 0x87, 0x07, 0x9A, 0x00, 0x00, 0x05, 0x01}, Deny},
	}
	for _, c := range cases {
		if got := p.Check(c.in); got != c.want {
			t.Errorf("%s: got %v want %v", c.name, got, c.want)
		}
	}
}

func TestP1P2Match(t *testing.T) {
	dir := t.TempDir()
	f := filepath.Join(dir, "a.yaml")
	y := "version: 1\nentries:\n  - {name: X, cla: 0, ins: 0xCB, p1: 0x3F, p2: 0xFF, signing: false}\n"
	if err := os.WriteFile(f, []byte(y), 0o600); err != nil {
		t.Fatal(err)
	}
	p, err := Load(f)
	if err != nil {
		t.Fatal(err)
	}
	if p.Check([]byte{0, 0xCB, 0x3F, 0xFF}) != Allow {
		t.Error("matching p1/p2 should allow")
	}
	if p.Check([]byte{0, 0xCB, 0x00, 0xFF}) != Deny {
		t.Error("mismatched p1 should deny")
	}
}

func TestLoadInvalid(t *testing.T) {
	bad := map[string]string{
		"not yaml":     "entries: [",
		"no entries":   "version: 1\nentries: []\n",
		"missing ins":  "version: 1\nentries:\n  - {cla: 0, signing: false}\n",
		"missing sign": "version: 1\nentries:\n  - {cla: 0, ins: 1}\n",
		"range":        "version: 1\nentries:\n  - {cla: 0, ins: 300, signing: false}\n",
		"unknown key":  "version: 1\nentries:\n  - {cla: 0, ins: 1, signing: false, bogus: 1}\n",
		"bad version":  "version: 2\nentries:\n  - {cla: 0, ins: 1, signing: false}\n",
	}
	for name, y := range bad {
		f := filepath.Join(t.TempDir(), "b.yaml")
		if err := os.WriteFile(f, []byte(y), 0o600); err != nil {
			t.Fatal(err)
		}
		if _, err := Load(f); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
	if _, err := Load(filepath.Join(t.TempDir(), "missing.yaml")); err == nil {
		t.Error("missing file: expected error")
	}
}

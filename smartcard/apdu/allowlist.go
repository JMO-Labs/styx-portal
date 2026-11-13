// Package apdu enforces the smart-card APDU allowlist shared by the Windows
// helper and the in-desktop relay.
package apdu

import (
	"bytes"
	"errors"
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

// Decision is the result of checking one command APDU.
type Decision int

const (
	// Deny is the zero value so unknown input fails closed.
	Deny Decision = iota
	Allow
	AllowNeedsUserConfirm
)

func (d Decision) String() string {
	switch d {
	case Allow:
		return "Allow"
	case AllowNeedsUserConfirm:
		return "AllowNeedsUserConfirm"
	}
	return "Deny"
}

// Entry is one allowlisted command.
type Entry struct {
	Name    string `yaml:"name"`
	CLA     *int   `yaml:"cla"`
	INS     *int   `yaml:"ins"`
	P1      *int   `yaml:"p1"`
	P2      *int   `yaml:"p2"`
	Signing *bool  `yaml:"signing"`
}

type file struct {
	Version int     `yaml:"version"`
	Entries []Entry `yaml:"entries"`
}

// Policy is an immutable, loaded allowlist.
type Policy struct{ entries []Entry }

// Load parses and validates an allowlist YAML file.
func Load(path string) (*Policy, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var f file
	dec := yaml.NewDecoder(bytes.NewReader(b))
	dec.KnownFields(true)
	if err := dec.Decode(&f); err != nil {
		return nil, fmt.Errorf("parse %s: %w", path, err)
	}
	if f.Version != 1 {
		return nil, fmt.Errorf("unsupported allowlist version %d", f.Version)
	}
	if len(f.Entries) == 0 {
		return nil, errors.New("allowlist has no entries")
	}
	for i, e := range f.Entries {
		if e.CLA == nil || e.INS == nil || e.Signing == nil {
			return nil, fmt.Errorf("entry %d: cla, ins and signing are required", i)
		}
		for _, v := range []*int{e.CLA, e.INS, e.P1, e.P2} {
			if v != nil && (*v < 0 || *v > 0xFF) {
				return nil, fmt.Errorf("entry %d: byte value out of range", i)
			}
		}
	}
	return &Policy{entries: f.Entries}, nil
}

// wellFormed validates ISO 7816-4 short/extended length encoding (cases 1-4).
func wellFormed(a []byte) bool {
	n := len(a)
	if n < 4 {
		return false
	}
	body := a[4:]
	switch {
	case len(body) == 0: // case 1
		return true
	case len(body) == 1: // case 2S: Le
		return true
	case body[0] != 0: // short Lc
		lc := int(body[0])
		return len(body) == 1+lc || len(body) == 2+lc
	}
	// body[0]==0: extended form, or short with Lc=0 / Le=256.
	if len(body) == 2 { // 0x00 then ... not a valid short or extended form
		return false
	}
	if len(body) == 3 { // case 2E: 00 Le1 Le2
		return true
	}
	lc := int(body[1])<<8 | int(body[2])
	if lc == 0 {
		return false
	}
	return len(body) == 3+lc || len(body) == 5+lc
}

// Check classifies a command APDU. Malformed or unlisted APDUs are denied.
func (p *Policy) Check(a []byte) Decision {
	if p == nil || !wellFormed(a) {
		return Deny
	}
	for _, e := range p.entries {
		if int(a[0]) != *e.CLA || int(a[1]) != *e.INS {
			continue
		}
		if e.P1 != nil && int(a[2]) != *e.P1 {
			continue
		}
		if e.P2 != nil && int(a[3]) != *e.P2 {
			continue
		}
		if *e.Signing {
			return AllowNeedsUserConfirm
		}
		return Allow
	}
	return Deny
}

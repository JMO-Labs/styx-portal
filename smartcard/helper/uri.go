// Package helper implements the Windows smart-card helper: it relays APDUs
// from the desktop relay to the local reader, enforcing the allowlist and
// user confirmation for signing operations on the client side.
package helper

import (
	"errors"
	"fmt"
	"net/url"
	"strings"
)

// ParseURI extracts host and token from styx-card://connect?host=<h>&token=<t>.
func ParseURI(raw string) (host, token string, err error) {
	u, err := url.Parse(raw)
	if err != nil {
		return "", "", fmt.Errorf("parse uri: %w", err)
	}
	if u.Scheme != "styx-card" || u.Host != "connect" {
		return "", "", errors.New("not a styx-card://connect uri")
	}
	q := u.Query()
	host, token = q.Get("host"), q.Get("token")
	if host == "" || token == "" {
		return "", "", errors.New("uri needs host and token")
	}
	return host, token, nil
}

// HostAllowed reports whether host is a proper subdomain of one of the
// configured suffixes. Anything that is not a bare hostname is rejected.
func HostAllowed(host string, suffixes []string) bool {
	if host == "" || strings.ContainsAny(host, "/@:?#\\ \t") {
		return false
	}
	h := strings.ToLower(strings.TrimSuffix(host, "."))
	for _, s := range suffixes {
		s = strings.ToLower(strings.Trim(s, ". "))
		if s != "" && strings.HasSuffix(h, "."+s) {
			return true
		}
	}
	return false
}

// DialURL builds the relay WSS URL. Call only after HostAllowed.
func DialURL(host, token string) (string, error) {
	if host == "" || token == "" {
		return "", errors.New("host and token required")
	}
	return "wss://" + host + "/smartcard?token=" + url.QueryEscape(token), nil
}

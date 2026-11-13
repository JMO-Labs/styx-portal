// Command styx-card-relay runs inside the desktop and relays the helper's
// WebSocket to the local vpcd after redeeming a one-time token.
package main

import (
	"log"
	"net/http"
	"os"

	"github.com/JMO-Labs/styx-portal/smartcard/apdu"
	"github.com/JMO-Labs/styx-portal/smartcard/relay"
)

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func main() {
	inst := os.Getenv("STYX_INSTANCE_ID")
	if inst == "" {
		log.Fatal("STYX_INSTANCE_ID is required")
	}
	pol, err := apdu.Load(env("STYX_APDU_ALLOWLIST", "/etc/styx/apdu-allowlist.yaml"))
	if err != nil {
		log.Fatalf("allowlist: %v", err)
	}
	h := relay.New(relay.Config{
		Policy:     pol,
		BackendURL: env("STYX_BACKEND_URL", "http://styx-backend:8000"),
		InstanceID: inst,
		VPCDAddr:   env("STYX_VPCD_ADDR", "127.0.0.1:35963"),
	})
	addr := env("STYX_RELAY_ADDR", "127.0.0.1:8765")
	log.Printf("styx-card-relay listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, h))
}

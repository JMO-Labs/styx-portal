// Command styx-card-helper relays the local smart-card reader to a Styx desktop.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"

	"github.com/JMO-Labs/styx-portal/smartcard/apdu"
	"github.com/JMO-Labs/styx-portal/smartcard/helper"
)

func main() {
	allowlist := flag.String("allowlist", "apdu-allowlist.yaml", "APDU allowlist file")
	domains := flag.String("allowed-domains", os.Getenv("STYX_CARD_ALLOWED_DOMAINS"), "comma-separated allowed host suffixes")
	flag.Parse()
	if flag.NArg() != 1 {
		fatal("usage: styx-card-helper [flags] styx-card://connect?host=<host>&token=<token>")
	}
	if err := run(flag.Arg(0), *allowlist, strings.Split(*domains, ",")); err != nil {
		fatal(err.Error())
	}
}

func run(uri, allowlist string, suffixes []string) error {
	host, token, err := helper.ParseURI(uri)
	if err != nil {
		return err
	}
	if !helper.HostAllowed(host, suffixes) {
		return fmt.Errorf("host %q is not in an allowed domain", host)
	}
	policy, err := apdu.Load(allowlist)
	if err != nil {
		return err
	}
	p, err := helper.NewPlatform()
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	conn, closeFn, err := helper.Dial(ctx, host, token, p.Certs)
	if err != nil {
		return err
	}
	defer closeFn()
	h := &helper.Handler{Policy: policy, Card: p.Card, Confirmer: p.Confirmer, Desktop: host}
	return helper.Serve(ctx, conn, h)
}

func fatal(msg string) {
	fmt.Fprintln(os.Stderr, msg)
	os.Exit(1)
}

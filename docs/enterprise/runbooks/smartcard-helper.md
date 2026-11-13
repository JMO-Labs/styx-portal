# Smart-card helper runbook

Controls: IA-2(12), SC-12, SA-11. Decisions: ADR-0041, ADR-0079. Building and signing the MSI: [smartcard-helper-signing.md](smartcard-helper-signing.md).

## Install

Server side:

1. Set `SMARTCARD_ENABLED=true` and a random `SMARTCARD_RELAY_SECRET` (from OpenBao, never in git). The backend then routes `/w/<sub>/smartcard` to the desktop relay.
2. Use the enterprise base image: it carries vpcd and `styx-card-relay`. The relay needs `STYX_INSTANCE_ID`, `STYX_BACKEND_URL` and the same secret; `STYX_APDU_ALLOWLIST` defaults to `/etc/styx/apdu-allowlist.yaml`.

Client side (Windows):

1. Push the signed `styx-card-helper.msi` with Intune (system context).
2. Set machine env `STYX_CARD_ALLOWED_DOMAINS` to the portal domain suffix, for example `desktops.example.mil`.
3. Check that `styx-card://` is registered under `HKLM\Software\Classes`.

## Connect

1. Insert the CAC/PIV card. Open your desktop in the portal.
2. Choose the smart card button. The browser asks to open Styx Card Helper; accept.
3. The helper connects with your card certificate. The desktop then sees a card reader.
4. For each sign or authenticate operation a dialog asks Yes/No. No answer for 30 s counts as No.

The token lasts 120 s and works once. If it expired, press the button again.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser does nothing on connect | MSI missing or handler not registered | Reinstall the MSI; check the registry key |
| Helper says host not allowed | Host is not a subdomain of `STYX_CARD_ALLOWED_DOMAINS` | Correct the variable; do not widen it to a public suffix |
| Redeem fails (403) | Token expired, used, wrong desktop, or card user differs from the session owner | Mint again from your own session; check `smartcard.redeem.fail` audit `reason` |
| Redeem always 403 | `SMARTCARD_RELAY_SECRET` empty or different on relay | Align both from OpenBao |
| Relay closes with "vpcd unavailable" | vpcd or pcscd not running in the desktop | Restart the desktop |
| Second helper refused | One helper per desktop | Close the first session |
| App gets `6D00` | APDU not in the allowlist | Expected; see change process if it is legitimate |
| App gets `6982` | You declined, or the dialog timed out | Retry and confirm |

## Allowlist change process

1. Open an issue naming the APDU (CLA, INS, P1/P2), the application needing it and why. Say whether it uses the private key; if so it is `signing: true`.
2. Edit `smartcard/apdu-allowlist.yaml` in a PR with a test in `smartcard/apdu/allowlist_test.go` (allowed case and a near-miss denied case).
3. Security officer reviews; `smartcard/test.sh` and CI must pass.
4. Release a new image (relay) and a new signed MSI if the helper copy changed; record the hash as in the signing runbook.
5. Never edit the file inside a running desktop or on a client.

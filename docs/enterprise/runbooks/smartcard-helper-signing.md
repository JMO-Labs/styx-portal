# Smartcard helper: build, sign, deploy

Package `styx-card-helper.exe` as an MSI, sign it with the owner certificate and ship it
through MDM (Intune). Part of styx-portal#264. The repository holds **no certificates, keys
or MSIs**; the certificate stays in the owner's HSM/token or a signing host.

Definition: `smartcard/packaging/windows/styx-card-helper.wxs` (installs to
`%ProgramFiles%\Styx Card Helper`, registers the `styx-card://` handler under
`HKLM\Software\Classes`, per machine).

## Prerequisites

- Linux build host: Go 1.22.12 (pinned) and `scripts/build_card_helper.sh`.
- Windows packaging host: WiX Toolset v4 (`dotnet tool install --global wix`) and the
  Windows SDK `signtool`.
- The owner code-signing certificate, available to `signtool` (store or token). Never copy it
  into the repo, CI variables or the build tree.

## 1. Build the executable

```bash
scripts/build_card_helper.sh          # writes smartcard/dist/styx-card-helper.exe + .sha256
```

The script builds twice and fails if the hashes differ. `smartcard/dist/` is not committed.

## 2. Sign the executable, then build the MSI

On the Windows host (set `VERSION` to the release, e.g. `1.2.0`):

```powershell
signtool sign /sha1 $env:OWNER_CERT_THUMBPRINT /fd sha256 /tr http://timestamp.digicert.com /td sha256 styx-card-helper.exe
wix build -d Version=$env:VERSION -d HelperExe=styx-card-helper.exe -arch x64 -o styx-card-helper.msi smartcard\packaging\windows\styx-card-helper.wxs
```

`OWNER_CERT_THUMBPRINT` is an identifier, not a secret. Use your own RFC 3161 timestamp URL
if policy requires one.

## 3. Sign the MSI

```powershell
signtool sign /sha1 $env:OWNER_CERT_THUMBPRINT /fd sha256 /tr http://timestamp.digicert.com /td sha256 styx-card-helper.msi
signtool verify /pa /v styx-card-helper.msi
```

Both `/tr` and `/td` are mandatory: an untimestamped signature expires with the certificate.

## 4. Record the signed hash

```powershell
Get-FileHash styx-card-helper.msi -Algorithm SHA256
```

Record version, SHA-256 of the signed MSI, signer thumbprint and date in the release notes
(and the component register if the release is accredited). Publish the hash next to the MSI.

## 5. Intune profile (no secrets)

1. Intune **Apps > Windows > Line-of-business app** takes the signed MSI directly.
2. Install context: **System**. Detection rule: use the product code
   Intune auto-detects from the uploaded MSI. The ProductCode is regenerated on every build,
   so always take it from the signed MSI being deployed (never reuse an earlier one). To read
   it manually, query the MSI's Property table (Orca, `msiinfo`, or the WindowsInstaller COM
   object), not `Get-AppLockerFileInformation`, which only returns publisher/hash data.
3. Export the assignment for review without secrets: `Graph GET
   /deviceAppManagement/mobileApps/{id}` and save the JSON. It holds names, version, product
   code, hash and assignments only. Strip any `contentVersion` upload URLs before filing it.
4. Verify on a pilot device: `reg query HKLM\Software\Classes\styx-card\shell\open\command`
   shows the installed path, and opening a `styx-card://connect?...` link starts the helper.

## Upgrade and rollback

The package uses `MajorUpgrade`: install a higher `Version` over the old one. To roll back,
redeploy the previous signed MSI as a new, higher version (downgrades are blocked).

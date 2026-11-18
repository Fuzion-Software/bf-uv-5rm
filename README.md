# bf-uv-5rm

Combined end-user release packager for the Baofeng UV-5RM custom firmware and flashing tool.

Each release fetches:
- **Firmware bundle** from [`Fuzion-Software/bf-uv-5rm-firmware-open`](https://github.com/Fuzion-Software/bf-uv-5rm-firmware-open) (`bf-uv-5rm-fw.BF`, `apps/apps.toml`, `apps/*.app`, `logo/boot.png`)
- **Tool binaries** from [`Fuzion-Software/open-ht-tool`](https://github.com/Fuzion-Software/open-ht-tool) (`open-ht-tool` CLI and available GUI builds, verified against `SHA256SUMS`)

and produces ready-to-run per-platform zip archives (`windows-amd64`, `linux-amd64`, `linux-arm64`, `darwin-amd64`, `darwin-arm64`) plus `SHA256SUMS`.

## End-User Quick Start (from a Release Zip)

1. Download and extract `bf-uv-5rm-<version>-<your-os>.zip`.
2. **Option A — GUI (`windows-amd64` / `linux-amd64`):**
   Launch `open-ht-tool-gui-*` directly from the extracted folder (it auto-detects `bf-uv-5rm-fw.BF`, `apps/`, and `logo/boot.png` next to the executable).
3. **Option B — CLI:**
   ```sh
   # 1. Bootloader mode (hold Side1 + Side2 while powering ON):
   ./open-ht-tool-linux-amd64 flash bf-uv-5rm-fw.BF

   # 2. Reboot normally to standby screen, then install overlay apps + boot logo:
   ./open-ht-tool-linux-amd64 install-all --apps-dir apps
   ```
   *(On Windows, run `open-ht-tool-windows-amd64.exe` instead.)*

## Local Usage (`Taskfile` / Python)

Requires Python 3.11+ and GitHub CLI (`gh` authenticated for publishing).

```sh
# Run unit tests
go-task test

# Preview next release tags and zip outputs
go-task release:dry-run

# Build per-platform zips locally in dist/ without publishing
go-task bundle VERSION=v0.1.0

# Create and publish a GitHub release (defaults to micro bump from latest)
go-task release
go-task release:minor
go-task release:draft
```

Pin specific upstream tags if needed:

```sh
go-task release VERSION=v0.2.0 FW_TAG=v0.1.0 TOOL_TAG=v0.1.0
```

## GitHub Actions

Run **Actions -> Release Bundled UV-5RM Package -> Run workflow** with:
- `version`: semver tag (`vX.Y.Z`) or bump level (`micro`, `minor`, `major`)
- `fw_tag`: upstream firmware tag or `latest`
- `tool_tag`: upstream `open-ht-tool` tag or `latest`
- `draft`: optional draft release flag

*(If either upstream repository is private to the organization, add an `UPSTREAM_TOKEN` secret with read access to upstream releases.)*

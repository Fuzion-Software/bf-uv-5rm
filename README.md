# bf-uv-5rm

Combined end-user release packager for the Baofeng UV-5RM custom firmware and flashing tool.

Each release fetches:
- **Firmware bundle** from [`Fuzion-Software/bf-uv-5rm-firmware-open`](https://github.com/Fuzion-Software/bf-uv-5rm-firmware-open) (`bf-uv-5rm-fw.BF`, `apps/apps.toml`, `apps/*.app`, `logo/boot.png`)
- **Tool binaries** from [`Fuzion-Software/open-ht-tool`](https://github.com/Fuzion-Software/open-ht-tool) (`open-ht-tool` CLI and available GUI builds, verified against `SHA256SUMS`)

and produces ready-to-run per-platform zip archives plus `SHA256SUMS`:
- `windows-bf-uv-5rm-<version>.zip` — Windows (64-bit)
- `mac-m1-bf-uv-5rm-<version>.zip` — Mac Apple Silicon (M1/M2/M3/M4)
- `mac-intel-bf-uv-5rm-<version>.zip` — Mac Intel
- `linux-x64-bf-uv-5rm-<version>.zip` — Linux x64
- `linux-arm64-bf-uv-5rm-<version>.zip` — Linux ARM64

Inside every zip, the tools are simply named `open-ht-tool` (and `GUI_open-ht-tool` where available, `.exe` on Windows) alongside `bf-uv-5rm-fw.BF`, `apps/`, `logo/boot.png`, and `QUICKSTART.txt`.

## End-User Quick Start

### Option 1 — Installer Script (Bypasses Browser Quarantine)

Download and run the installer script for your OS from the command line (this avoids browser quarantine flags), or double-click it after downloading:

- **macOS:**
  ```sh
  curl -fsSL -O https://raw.githubusercontent.com/Fuzion-Software/bf-uv-5rm/main/install.command
  chmod +x install.command
  ./install.command
  ```
  *(Or double-click [`install.command`](install.command) in Finder; pass an optional `[target_dir]` when running from Terminal.)*

- **Linux:**
  ```sh
  curl -fsSL -O https://raw.githubusercontent.com/Fuzion-Software/bf-uv-5rm/main/install.sh
  chmod +x install.sh
  ./install.sh
  ```
  *(Pass an optional `[target_dir]` to extract into a specific folder.)*

- **Windows (Command Prompt):**
  ```bat
  curl.exe -fsSL -o install.bat https://raw.githubusercontent.com/Fuzion-Software/bf-uv-5rm/main/install.bat
  install.bat
  ```
  *(Or in PowerShell: `Invoke-WebRequest -Uri https://raw.githubusercontent.com/Fuzion-Software/bf-uv-5rm/main/install.bat -OutFile install.bat; .\install.bat`. You can also double-click [`install.bat`](install.bat) or pass `[target_dir]`.)*

### Option 2 — Direct Release Zip
1. Download and extract the zip for your computer.
2. **macOS only (if downloaded via a web browser):** macOS Gatekeeper attaches a quarantine attribute to browser downloads and may block unsigned scripts or binaries ("cannot be opened because the developer cannot be verified"). Clear it in Terminal before running:
   ```sh
   # Clear quarantine on an extracted release folder:
   xattr -cr /path/to/extracted-folder

   # Or, if you downloaded install.command via a browser:
   xattr -cr ~/Downloads/install.command
   chmod +x ~/Downloads/install.command
   ```
3. **Option A — GUI:**
   Open `GUI_open-ht-tool` (`GUI_open-ht-tool.exe` on Windows) directly from the extracted folder (it auto-detects `bf-uv-5rm-fw.BF`, `apps/`, and `logo/boot.png` next to it).
4. **Option B — Command Line:**
   ```sh
   # 1. Bootloader mode (hold Side1 + Side2 while powering ON):
   ./open-ht-tool flash bf-uv-5rm-fw.BF

   # 2. Reboot normally to standby screen, then install overlay apps + boot logo:
   ./open-ht-tool install-all --apps-dir apps
   ```
   *(On Windows, run `open-ht-tool.exe` instead.)*

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

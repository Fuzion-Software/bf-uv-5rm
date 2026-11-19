#!/usr/bin/env bash
# Double-clickable installer for Baofeng UV-5RM firmware & open-ht-tool bundles.
# Works on macOS (double-click install.command in Finder), Linux, and Git Bash/WSL.

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"

# If double-clicked in a Linux GUI file manager without a terminal attached,
# re-launch inside an available terminal emulator so the user can interact.
if [ ! -t 0 ] && [ "${BF_INSTALL_IN_TERM:-0}" != "1" ]; then
    export BF_INSTALL_IN_TERM=1
    for term in x-terminal-emulator gnome-terminal konsole xfce4-terminal mate-terminal kitty alacritty xterm; do
        if command -v "$term" >/dev/null 2>&1; then
            case "$term" in
                gnome-terminal) exec "$term" -- bash "$SCRIPT_PATH" ;;
                konsole|xfce4-terminal|mate-terminal|xterm|x-terminal-emulator|kitty|alacritty)
                    exec "$term" -e bash "$SCRIPT_PATH"
                    ;;
            esac
        fi
    done
fi

# When double-clicked in macOS Finder, Terminal starts in $HOME instead of the
# folder containing the .command script. Switch to the script's directory.
if [ "$PWD" = "${HOME:-}" ] && [ "$SCRIPT_DIR" != "${HOME:-}" ]; then
    cd "$SCRIPT_DIR"
fi

pause_exit() {
    local code="${1:-0}"
    echo ""
    if [ -t 0 ]; then
        read -r -p "Press Enter to close..." _ || true
    fi
    exit "$code"
}

trap 'echo ""; echo "[ERR] Installation failed."; pause_exit 1' ERR

REPO="${BF_UV5RM_REPO:-Fuzion-Software/bf-uv-5rm}"
TAG="${BF_UV5RM_TAG:-}"

detect_bundle_prefix() {
    local os_name arch_name
    os_name="$(uname -s)"
    arch_name="$(uname -m)"

    case "$os_name" in
        Darwin)
            # Detect Apple Silicon even if Terminal is running under Rosetta 2
            if [ "$arch_name" = "arm64" ] || [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ]; then
                echo "mac-m1-bf-uv-5rm"
            else
                echo "mac-intel-bf-uv-5rm"
            fi
            ;;
        Linux)
            case "$arch_name" in
                x86_64|amd64)
                    echo "linux-x64-bf-uv-5rm"
                    ;;
                aarch64|arm64)
                    echo "linux-arm64-bf-uv-5rm"
                    ;;
                *)
                    echo "[ERR] Unsupported Linux architecture: $arch_name" >&2
                    return 1
                    ;;
            esac
            ;;
        MINGW*|MSYS*|CYGWIN*|Windows_NT)
            echo "windows-bf-uv-5rm"
            ;;
        *)
            echo "[ERR] Unsupported operating system: $os_name" >&2
            return 1
            ;;
    esac
}

resolve_latest_tag() {
    local effective_url tag

    # 1. Resolve via GitHub /releases/latest redirect (avoids API rate limits)
    effective_url="$(curl -fsSL -o /dev/null -w '%{url_effective}' "https://github.com/${REPO}/releases/latest" 2>/dev/null || true)"
    case "$effective_url" in
        */releases/tag/*)
            tag="${effective_url##*/releases/tag/}"
            tag="${tag%%[\?#]*}"
            if [ -n "$tag" ]; then
                echo "$tag"
                return 0
            fi
            ;;
    esac

    # 2. Fallback to GitHub Releases API
    tag="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null \
        | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        | head -n 1)"
    if [ -n "$tag" ]; then
        echo "$tag"
        return 0
    fi

    echo "[ERR] Could not determine latest release tag from https://github.com/${REPO}/releases" >&2
    return 1
}

echo "========================================================"
echo "  Baofeng UV-5RM Firmware & open-ht-tool Installer"
echo "========================================================"
echo ""

BUNDLE_PREFIX="$(detect_bundle_prefix)"
echo "Detected platform bundle: ${BUNDLE_PREFIX}"

DEFAULT_DIR="$(pwd)"
read -r -p "Install directory [${DEFAULT_DIR}]: " INPUT_DIR || INPUT_DIR=""
INPUT_DIR="${INPUT_DIR#"${INPUT_DIR%%[![:space:]]*}"}"
INPUT_DIR="${INPUT_DIR%"${INPUT_DIR##*[![:space:]]}"}"

if [ -z "$INPUT_DIR" ]; then
    TARGET_DIR="$DEFAULT_DIR"
else
    # Expand leading ~ to $HOME
    case "$INPUT_DIR" in
        "~") TARGET_DIR="$HOME" ;;
        "~/"*) TARGET_DIR="${HOME}/${INPUT_DIR#\~/}" ;;
        *) TARGET_DIR="$INPUT_DIR" ;;
    esac
fi

mkdir -p "$TARGET_DIR"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"

if [ -z "$TAG" ]; then
    echo "Checking latest release from ${REPO}..."
    TAG="$(resolve_latest_tag)"
fi

ZIP_NAME="${BUNDLE_PREFIX}-${TAG}.zip"
DOWNLOAD_URL="${BF_UV5RM_DOWNLOAD_URL:-https://github.com/${REPO}/releases/download/${TAG}/${ZIP_NAME}}"

TMP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t bf-uv-5rm-install)"
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

TMP_ZIP="${TMP_DIR}/${ZIP_NAME}"

echo ""
echo "Downloading ${ZIP_NAME} (${TAG})..."
echo "  URL: ${DOWNLOAD_URL}"
curl -fL --progress-bar -o "$TMP_ZIP" "$DOWNLOAD_URL"

echo ""
echo "Extracting to ${TARGET_DIR}..."
if command -v unzip >/dev/null 2>&1; then
    unzip -o "$TMP_ZIP" -d "$TARGET_DIR"
elif command -v tar >/dev/null 2>&1; then
    tar -xf "$TMP_ZIP" -C "$TARGET_DIR"
elif command -v python3 >/dev/null 2>&1; then
    python3 -m zipfile -e "$TMP_ZIP" "$TARGET_DIR"
else
    echo "[ERR] No zip extraction tool found (need unzip, tar, or python3)." >&2
    pause_exit 1
fi

# Ensure tool binaries are executable and clear any macOS quarantine attributes
chmod +x "${TARGET_DIR}/open-ht-tool" "${TARGET_DIR}/GUI_open-ht-tool" 2>/dev/null || true
if [ "$(uname -s)" = "Darwin" ] && command -v xattr >/dev/null 2>&1; then
    xattr -cr "$TARGET_DIR" 2>/dev/null || true
fi

echo ""
echo "[OK] Installed ${ZIP_NAME} into:"
echo "     ${TARGET_DIR}"
echo ""
echo "Next steps:"
echo "  1. Bootloader mode (hold Side1 + Side2 + Power ON):"
echo "     \"${TARGET_DIR}/open-ht-tool\" flash \"${TARGET_DIR}/bf-uv-5rm-fw.BF\""
echo "  2. Normal standby mode (install overlay apps + boot logo):"
echo "     \"${TARGET_DIR}/open-ht-tool\" install-all --apps-dir \"${TARGET_DIR}/apps\""
if [ -f "${TARGET_DIR}/GUI_open-ht-tool" ] || [ -f "${TARGET_DIR}/GUI_open-ht-tool.exe" ]; then
    echo "  Or launch the GUI: \"${TARGET_DIR}/GUI_open-ht-tool\""
fi

trap - ERR
pause_exit 0

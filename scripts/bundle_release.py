#!/usr/bin/env python3
"""Download upstream firmware + open-ht-tool releases and package per-platform bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FW_REPO = "Fuzion-Software/bf-uv-5rm-firmware-open"
DEFAULT_TOOL_REPO = "Fuzion-Software/open-ht-tool"
SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

PLATFORMS: tuple[tuple[str, str], ...] = (
    ("windows-amd64", ".exe"),
    ("linux-amd64", ""),
    ("linux-arm64", ""),
    ("darwin-amd64", ""),
    ("darwin-arm64", ""),
)


@dataclass(frozen=True)
class UpstreamRelease:
    repo: str
    tag: str
    asset_names: list[str]


def run_cmd(cmd: list[str], capture: bool = False, check: bool = True) -> str:
    env = os.environ.copy()
    if "GH_TOKEN" not in env and "UPSTREAM_TOKEN" in env:
        env["GH_TOKEN"] = env["UPSTREAM_TOKEN"]
    res = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=capture,
        check=check,
    )
    return res.stdout.strip() if capture else ""


def parse_semver(tag: str) -> tuple[int, int, int] | None:
    m = SEMVER_RE.match(tag.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def latest_semver_tag() -> str | None:
    candidates: list[tuple[tuple[int, int, int], str]] = []

    res = subprocess.run(
        ["gh", "release", "list", "--limit", "50", "--json", "tagName"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if res.returncode == 0 and res.stdout.strip():
        for item in json.loads(res.stdout):
            tag = item.get("tagName", "")
            parsed = parse_semver(tag)
            if parsed is not None:
                candidates.append((parsed, f"v{parsed[0]}.{parsed[1]}.{parsed[2]}"))

    tag_out = run_cmd(["git", "tag", "-l"], capture=True, check=False)
    for line in tag_out.splitlines():
        parsed = parse_semver(line)
        if parsed is not None:
            candidates.append((parsed, f"v{parsed[0]}.{parsed[1]}.{parsed[2]}"))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def bump_semver(base_tag: str | None, level: str) -> str:
    if base_tag is None:
        major, minor, micro = 0, 0, 0
    else:
        parsed = parse_semver(base_tag)
        if parsed is None:
            raise ValueError(f"Latest tag {base_tag!r} is not valid semver")
        major, minor, micro = parsed

    if level == "major":
        return f"v{major + 1}.0.0"
    if level == "minor":
        return f"v{major}.{minor + 1}.0"
    if level == "micro":
        return f"v{major}.{minor}.{micro + 1}"
    raise ValueError(f"Unknown bump level: {level}")


def tag_or_release_exists(tag: str) -> bool:
    local = run_cmd(["git", "tag", "-l", tag], capture=True, check=False)
    if local == tag:
        return True
    gh_res = subprocess.run(
        ["gh", "release", "view", tag],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    return gh_res.returncode == 0


def fetch_release_metadata(repo: str, requested_tag: str) -> UpstreamRelease:
    cmd = ["gh", "release", "view"]
    if requested_tag != "latest":
        cmd.append(requested_tag)
    cmd.extend(["--repo", repo, "--json", "tagName,assets"])
    raw = run_cmd(cmd, capture=True)
    data = json.loads(raw)
    tag = data["tagName"]
    names = [a["name"] for a in data.get("assets", []) if isinstance(a.get("name"), str)]
    return UpstreamRelease(repo=repo, tag=tag, asset_names=names)


def download_release_patterns(
    repo: str, tag: str, dest_dir: Path, patterns: list[str]
) -> None:
    cmd = ["gh", "release", "download", tag, "--repo", repo, "--dir", str(dest_dir)]
    for pat in patterns:
        cmd.extend(["--pattern", pat])
    run_cmd(cmd)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256sums(sums_path: Path, files_dir: Path) -> list[str]:
    expected: dict[str, str] = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Malformed SHA256SUMS line in {sums_path}: {line!r}")
        digest = parts[0].lower()
        name = parts[1].lstrip("*").strip()
        expected[name] = digest

    verified: list[str] = []
    for path in sorted(files_dir.iterdir()):
        if not path.is_file() or path.name == sums_path.name:
            continue
        if path.name not in expected:
            continue
        actual = sha256_file(path)
        if actual != expected[path.name]:
            raise ValueError(
                f"SHA-256 mismatch for {path.name}: got {actual}, expected {expected[path.name]}"
            )
        verified.append(path.name)
    return verified


def parse_manifest_apps(apps_toml: Path) -> list[str]:
    data = tomllib.loads(apps_toml.read_text(encoding="utf-8"))
    slots = data.get("slots", {})
    if not isinstance(slots, dict) or not slots:
        raise ValueError(f"No [slots] entries found in {apps_toml}")

    files: list[str] = []
    seen: set[str] = set()
    for _, raw_name in sorted(slots.items(), key=lambda kv: int(kv[0])):
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError(f"Invalid app entry {raw_name!r} in {apps_toml}")
        clean = raw_name.strip()
        if Path(clean).name != clean or not clean.endswith(".app"):
            raise ValueError(f"Expected plain .app filename in {apps_toml}, got {raw_name!r}")
        if clean not in seen:
            seen.add(clean)
            files.append(clean)
    return files


def extract_and_validate_fw_zip(fw_zip: Path, out_dir: Path) -> list[tuple[Path, str]]:
    """Extract firmware zip safely and return validated `(src_path, archive_name)` pairs."""
    with zipfile.ZipFile(fw_zip, "r") as zf:
        for info in zf.infolist():
            rel = Path(info.filename)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError(f"Unsafe path in firmware archive {fw_zip}: {info.filename!r}")
        zf.extractall(out_dir)

    fw_bf = out_dir / "bf-uv-5rm-fw.BF"
    boot_logo = out_dir / "logo" / "boot.png"
    apps_toml = out_dir / "apps" / "apps.toml"

    for required in (fw_bf, boot_logo, apps_toml):
        if not required.is_file():
            raise FileNotFoundError(
                f"Firmware bundle {fw_zip} missing required file: {required.relative_to(out_dir)}"
            )

    entries: list[tuple[Path, str]] = [
        (fw_bf, "bf-uv-5rm-fw.BF"),
        (boot_logo, "logo/boot.png"),
        (apps_toml, "apps/apps.toml"),
    ]
    for app_name in parse_manifest_apps(apps_toml):
        app_path = out_dir / "apps" / app_name
        if not app_path.is_file():
            raise FileNotFoundError(
                f"Firmware bundle {fw_zip} missing manifest app apps/{app_name}"
            )
        entries.append((app_path, f"apps/{app_name}"))

    return entries


def find_fw_bundle_name(asset_names: list[str]) -> str:
    matches = sorted(
        n for n in asset_names if n.startswith("bf-uv-5rm-fw-") and n.endswith(".zip")
    )
    if not matches:
        raise FileNotFoundError(
            f"No bf-uv-5rm-fw-*.zip release bundle found in assets: {asset_names}"
        )
    return matches[0]


def make_quickstart_text(
    platform: str,
    ext: str,
    cli_name: str,
    gui_name: str | None,
    release_tag: str,
    fw_tag: str,
    tool_tag: str,
) -> str:
    prefix = "" if ext == ".exe" else "./"
    gui_line = (
        f"Option A — GUI:\n  Launch {prefix}{gui_name} and use Full Install (or Flash Firmware / Install Apps).\n\n"
        if gui_name
        else ""
    )
    cli_step = "Option B — CLI" if gui_name else "CLI Flashing & App Install"
    chmod_note = (
        ""
        if ext == ".exe"
        else f"  (If needed on macOS/Linux: chmod +x {cli_name}"
        + (f" {gui_name}" if gui_name else "")
        + ")\n\n"
    )
    return (
        f"Baofeng UV-5RM Release Bundle {release_tag} ({platform})\n"
        f"Upstream firmware: {DEFAULT_FW_REPO} ({fw_tag})\n"
        f"Upstream tool:     {DEFAULT_TOOL_REPO} ({tool_tag})\n\n"
        f"{gui_line}"
        f"{cli_step}:\n"
        f"{chmod_note}"
        f"1. Flash firmware (hold Side1 + Side2 while powering ON for bootloader mode):\n"
        f"   {prefix}{cli_name} flash bf-uv-5rm-fw.BF\n\n"
        f"2. Reboot radio normally to standby screen, then install overlay apps + boot logo:\n"
        f"   {prefix}{cli_name} install-all --apps-dir apps\n"
    )


def write_zip_entry(
    zf: zipfile.ZipFile, src: Path | None, arcname: str, executable: bool = False, text: str | None = None
) -> None:
    zi = zipfile.ZipInfo(arcname)
    zi.create_system = 3
    zi.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o100755 if executable else 0o100644
    zi.external_attr = mode << 16
    if text is not None:
        zi.date_time = time.localtime()[:6]
        zf.writestr(zi, text.encode("utf-8"))
    elif src is not None:
        zi.date_time = zipfile.ZipInfo.from_file(src, arcname).date_time
        zf.writestr(zi, src.read_bytes())
    else:
        raise ValueError("write_zip_entry requires src or text")


def build_platform_bundles(
    release_tag: str,
    fw_entries: list[tuple[Path, str]],
    tool_dir: Path,
    dist_dir: Path,
    fw_tag: str,
    tool_tag: str,
) -> tuple[list[Path], dict[str, list[str]]]:
    sums_path = tool_dir / "SHA256SUMS"
    if sums_path.is_file():
        verify_sha256sums(sums_path, tool_dir)

    dist_dir.mkdir(parents=True, exist_ok=True)
    bundles: list[Path] = []
    manifest: dict[str, list[str]] = {}

    for platform, ext in PLATFORMS:
        cli_name = f"open-ht-tool-{platform}{ext}"
        cli_path = tool_dir / cli_name
        if not cli_path.is_file():
            raise FileNotFoundError(f"Missing CLI binary in {tool_dir}: {cli_name}")

        gui_name = f"open-ht-tool-gui-{platform}{ext}"
        gui_path = tool_dir / gui_name
        has_gui = gui_path.is_file()

        zip_path = dist_dir / f"bf-uv-5rm-{release_tag}-{platform}.zip"
        included: list[str] = []

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for src_path, arcname in fw_entries:
                write_zip_entry(zf, src_path, arcname, executable=False)
                included.append(arcname)

            is_unix = ext != ".exe"
            write_zip_entry(zf, cli_path, cli_name, executable=is_unix)
            included.append(cli_name)

            if has_gui:
                write_zip_entry(zf, gui_path, gui_name, executable=is_unix)
                included.append(gui_name)

            quickstart = make_quickstart_text(
                platform=platform,
                ext=ext,
                cli_name=cli_name,
                gui_name=gui_name if has_gui else None,
                release_tag=release_tag,
                fw_tag=fw_tag,
                tool_tag=tool_tag,
            )
            write_zip_entry(zf, None, "QUICKSTART.txt", executable=False, text=quickstart)
            included.append("QUICKSTART.txt")

        bundles.append(zip_path)
        manifest[zip_path.name] = included

    sha_lines = [f"{sha256_file(p)}  {p.name}" for p in bundles]
    sums_out = dist_dir / "SHA256SUMS"
    sums_out.write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    return [*bundles, sums_out], manifest


def resolve_release_tag(target: str) -> str:
    clean = target.strip()
    if clean in ("auto", "micro", "minor", "major"):
        level = "micro" if clean == "auto" else clean
        latest = latest_semver_tag()
        tag = bump_semver(latest, level)
        print(f"Latest release/tag: {latest or '(none)'} -> bumping {level} to {tag}")
        return tag
    parsed = parse_semver(clean)
    if parsed is None:
        raise ValueError(
            f"{target!r} must be 'auto', 'micro', 'minor', 'major', or a semver like v1.2.3"
        )
    return f"v{parsed[0]}.{parsed[1]}.{parsed[2]}"


def make_release_notes(
    tag: str, fw_repo: str, fw_tag: str, tool_repo: str, tool_tag: str, assets: list[Path]
) -> str:
    lines = [
        f"Combined Baofeng UV-5RM release `{tag}`.",
        "",
        "### Upstream Releases",
        f"- **Firmware:** `{fw_repo}` @ `{fw_tag}` (`bf-uv-5rm-fw.BF`, `apps/`, `logo/boot.png`)",
        f"- **Flashing Tool:** `{tool_repo}` @ `{tool_tag}` (`open-ht-tool` CLI + available GUI)",
        "",
        "### Quick Start",
        "1. Download and extract the zip for your OS.",
        "2. Run the GUI (`open-ht-tool-gui-*`) or use CLI:",
        "   - Bootloader mode (`Side1 + Side2 + Power ON`): `open-ht-tool-* flash bf-uv-5rm-fw.BF`",
        "   - Normal standby mode: `open-ht-tool-* install-all --apps-dir apps`",
        "",
        "### Bundles",
    ]
    for a in assets:
        if a.suffix == ".zip":
            lines.append(f"- `{a.name}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Bundle upstream bf-uv-5rm-firmware-open and open-ht-tool releases."
    )
    ap.add_argument(
        "target",
        nargs="?",
        default="micro",
        help="Explicit semver (vX.Y.Z) or bump level: auto, micro (default), minor, major",
    )
    ap.add_argument("--fw-repo", default=DEFAULT_FW_REPO)
    ap.add_argument("--fw-tag", default="latest", help="Upstream firmware release tag or 'latest'")
    ap.add_argument("--tool-repo", default=DEFAULT_TOOL_REPO)
    ap.add_argument("--tool-tag", default="latest", help="Upstream open-ht-tool release tag or 'latest'")
    ap.add_argument("--local-fw-zip", type=Path, help="Use a local bf-uv-5rm-fw-*.zip instead of downloading")
    ap.add_argument("--local-tool-dir", type=Path, help="Use a local directory of open-ht-tool-* binaries")
    ap.add_argument("--bundle-only", action="store_true", help="Write dist/*.zip and SHA256SUMS without creating a GitHub release")
    ap.add_argument("--draft", action="store_true", help="Create GitHub release as a draft")
    ap.add_argument("--dry-run", action="store_true", help="Resolve tags and print planned bundles without modifying dist/ or publishing")
    args = ap.parse_args()

    try:
        tag = resolve_release_tag(args.target)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not args.bundle_only and not args.dry_run and tag_or_release_exists(tag):
        print(f"error: tag or GitHub release {tag!r} already exists", file=sys.stderr)
        return 1

    if args.local_fw_zip is not None:
        fw_tag = args.fw_tag if args.fw_tag != "latest" else "local"
        fw_bundle_name = args.local_fw_zip.name
    else:
        if args.dry_run:
            try:
                fw_rel = fetch_release_metadata(args.fw_repo, args.fw_tag)
                fw_tag = fw_rel.tag
                fw_bundle_name = find_fw_bundle_name(fw_rel.asset_names)
            except subprocess.CalledProcessError:
                fw_tag = args.fw_tag
                fw_bundle_name = "bf-uv-5rm-fw-<tag>.zip"
        else:
            fw_rel = fetch_release_metadata(args.fw_repo, args.fw_tag)
            fw_tag = fw_rel.tag
            fw_bundle_name = find_fw_bundle_name(fw_rel.asset_names)

    if args.local_tool_dir is not None:
        tool_tag = args.tool_tag if args.tool_tag != "latest" else "local"
    elif args.dry_run:
        try:
            tool_rel = fetch_release_metadata(args.tool_repo, args.tool_tag)
            tool_tag = tool_rel.tag
        except subprocess.CalledProcessError:
            tool_tag = args.tool_tag
    else:
        tool_rel = fetch_release_metadata(args.tool_repo, args.tool_tag)
        tool_tag = tool_rel.tag

    if args.dry_run:
        action = "build local bundles" if args.bundle_only else "create GitHub release"
        print(f"[dry-run] Would {action} {tag}")
        print(f"[dry-run] Firmware: {args.fw_repo} @ {fw_tag} ({fw_bundle_name})")
        print(f"[dry-run] Tool:     {args.tool_repo} @ {tool_tag}")
        for platform, _ in PLATFORMS:
            print(f"[dry-run] Bundle:   dist/bf-uv-5rm-{tag}-{platform}.zip")
        print("[dry-run] Checksum: dist/SHA256SUMS")
        return 0

    with tempfile.TemporaryDirectory(prefix="bf-uv-5rm-bundle-") as tmp:
        tmp_dir = Path(tmp)
        fw_stage = tmp_dir / "fw"
        fw_extract = tmp_dir / "fw_extract"
        tool_stage = tmp_dir / "tool"
        fw_stage.mkdir()
        fw_extract.mkdir()
        tool_stage.mkdir()

        if args.local_fw_zip is not None:
            fw_zip_path = args.local_fw_zip.resolve()
        else:
            download_release_patterns(args.fw_repo, fw_tag, fw_stage, [fw_bundle_name])
            fw_zip_path = fw_stage / fw_bundle_name

        fw_entries = extract_and_validate_fw_zip(fw_zip_path, fw_extract)

        if args.local_tool_dir is not None:
            tool_source = args.local_tool_dir.resolve()
            for item in tool_source.iterdir():
                if item.is_file() and (item.name.startswith("open-ht-tool-") or item.name == "SHA256SUMS"):
                    shutil.copy2(item, tool_stage / item.name)
        else:
            download_release_patterns(
                args.tool_repo,
                tool_tag,
                tool_stage,
                ["open-ht-tool-*", "SHA256SUMS"],
            )

        dist_dir = ROOT / "dist"
        for old in dist_dir.glob(f"bf-uv-5rm-{tag}-*.zip"):
            old.unlink()

        assets, manifest = build_platform_bundles(
            release_tag=tag,
            fw_entries=fw_entries,
            tool_dir=tool_stage,
            dist_dir=dist_dir,
            fw_tag=fw_tag,
            tool_tag=tool_tag,
        )

    for zip_name, members in manifest.items():
        print(f"[ok] dist/{zip_name} ({len(members)} entries)")

    if args.bundle_only:
        print(f"Created {len(assets)} release artifacts in dist/")
        return 0

    notes = make_release_notes(tag, args.fw_repo, fw_tag, args.tool_repo, tool_tag, assets)
    notes_file = ROOT / "dist" / f"RELEASE_NOTES_{tag}.md"
    notes_file.write_text(notes, encoding="utf-8")
    try:
        cmd = [
            "gh",
            "release",
            "create",
            tag,
            "--title",
            f"bf-uv-5rm {tag} (FW {fw_tag} + open-ht-tool {tool_tag})",
            "--notes-file",
            str(notes_file),
        ]
        if args.draft:
            cmd.append("--draft")
        cmd.extend(str(a) for a in assets)
        run_cmd(cmd)
    finally:
        if notes_file.exists():
            notes_file.unlink()

    print(f"Created GitHub release {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

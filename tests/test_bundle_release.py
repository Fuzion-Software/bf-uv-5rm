import hashlib
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import bundle_release as br  # noqa: E402


class BundleReleaseTests(unittest.TestCase):
    def test_semver_helpers(self) -> None:
        self.assertEqual(br.parse_semver("v1.2.3"), (1, 2, 3))
        self.assertEqual(br.parse_semver("1.2.3"), (1, 2, 3))
        self.assertIsNone(br.parse_semver("v1.2.3-rc1"))
        self.assertEqual(br.bump_semver(None, "micro"), "v0.0.1")
        self.assertEqual(br.bump_semver(None, "minor"), "v0.1.0")
        self.assertEqual(br.bump_semver("v1.2.3", "micro"), "v1.2.4")
        self.assertEqual(br.bump_semver("v1.2.3", "minor"), "v1.3.0")
        self.assertEqual(br.bump_semver("v1.2.3", "major"), "v2.0.0")

    def test_verify_sha256sums_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            good = d / "open-ht-tool-linux-amd64"
            good.write_bytes(b"hello tool")
            digest = hashlib.sha256(b"hello tool").hexdigest()
            sums = d / "SHA256SUMS"
            sums.write_text(f"{digest}  {good.name}\n", encoding="utf-8")

            self.assertEqual(br.verify_sha256sums(sums, d), [good.name])

            good.write_bytes(b"corrupted")
            with self.assertRaises(ValueError):
                br.verify_sha256sums(sums, d)

    def test_extract_and_build_platform_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fw_zip = root / "bf-uv-5rm-fw-v0.1.0.zip"
            with zipfile.ZipFile(fw_zip, "w") as zf:
                zf.writestr("bf-uv-5rm-fw.BF", b"BFDATA")
                zf.writestr("logo/boot.png", b"PNGDATA")
                zf.writestr("apps/apps.toml", '[slots]\n0 = "cw.app"\n7 = "bkgko.app"\n')
                zf.writestr("apps/cw.app", b"CWAPP")
                zf.writestr("apps/bkgko.app", b"BKGAPP")

            tool_dir = root / "tools"
            tool_dir.mkdir()
            tool_files = [
                ("open-ht-tool-windows-amd64.exe", b"WINCLI"),
                ("open-ht-tool-gui-windows-amd64.exe", b"WINGUI"),
                ("open-ht-tool-linux-amd64", b"LINCLI"),
                ("open-ht-tool-gui-linux-amd64", b"LINGUI"),
                ("open-ht-tool-linux-arm64", b"ARMCLI"),
                ("open-ht-tool-darwin-amd64", b"MACX64"),
                ("open-ht-tool-darwin-arm64", b"MACARM"),
            ]
            sum_lines = []
            for name, data in tool_files:
                (tool_dir / name).write_bytes(data)
                sum_lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
            (tool_dir / "SHA256SUMS").write_text("\n".join(sum_lines) + "\n", encoding="utf-8")

            extracted = root / "fw_extract"
            fw_entries = br.extract_and_validate_fw_zip(fw_zip, extracted)
            dist = root / "dist"
            assets, manifest = br.build_platform_bundles(
                release_tag="v0.1.0",
                fw_entries=fw_entries,
                tool_dir=tool_dir,
                dist_dir=dist,
                fw_tag="v0.1.0",
                tool_tag="v0.2.0",
            )

            self.assertEqual(len(assets), 6)  # 5 platform zips + SHA256SUMS
            self.assertIn("open-ht-tool", manifest["linux-x64-bf-uv-5rm-v0.1.0.zip"])
            self.assertIn("GUI_open-ht-tool", manifest["linux-x64-bf-uv-5rm-v0.1.0.zip"])
            self.assertIn("open-ht-tool.exe", manifest["windows-bf-uv-5rm-v0.1.0.zip"])
            self.assertIn("GUI_open-ht-tool.exe", manifest["windows-bf-uv-5rm-v0.1.0.zip"])
            self.assertIn("open-ht-tool", manifest["mac-m1-bf-uv-5rm-v0.1.0.zip"])
            self.assertNotIn("GUI_open-ht-tool", manifest["mac-m1-bf-uv-5rm-v0.1.0.zip"])
            self.assertIn("open-ht-tool", manifest["mac-intel-bf-uv-5rm-v0.1.0.zip"])
            self.assertIn("open-ht-tool", manifest["linux-arm64-bf-uv-5rm-v0.1.0.zip"])

            # Verify macOS .app.zip repackaging as GUI_open-ht-tool.app
            mac_app_zip = tool_dir / "open-ht-tool-gui-darwin-arm64.app.zip"
            with zipfile.ZipFile(mac_app_zip, "w") as zf:
                zf.writestr("open-ht-tool.app/Contents/Info.plist", "<plist/>")
                zf.writestr("open-ht-tool.app/Contents/MacOS/open-ht-tool-gui", b"MACAPPBIN")
            _, mac_manifest = br.build_platform_bundles(
                release_tag="v0.1.0",
                fw_entries=fw_entries,
                tool_dir=tool_dir,
                dist_dir=dist,
                fw_tag="v0.1.0",
                tool_tag="v0.2.0",
            )
            self.assertIn(
                "GUI_open-ht-tool.app/Contents/MacOS/open-ht-tool-gui",
                mac_manifest["mac-m1-bf-uv-5rm-v0.1.0.zip"],
            )

            lin_zip = dist / "linux-x64-bf-uv-5rm-v0.1.0.zip"
            with zipfile.ZipFile(lin_zip, "r") as zf:
                cli_info = zf.getinfo("open-ht-tool")
                self.assertEqual((cli_info.external_attr >> 16) & 0o777, 0o755)
                gui_info = zf.getinfo("GUI_open-ht-tool")
                self.assertEqual((gui_info.external_attr >> 16) & 0o777, 0o755)
                bf_info = zf.getinfo("bf-uv-5rm-fw.BF")
                self.assertEqual((bf_info.external_attr >> 16) & 0o777, 0o644)
                qs = zf.read("QUICKSTART.txt").decode("utf-8")
                self.assertIn("GUI_open-ht-tool", qs)
                self.assertIn("./open-ht-tool flash bf-uv-5rm-fw.BF", qs)

            mac_zip = dist / "mac-m1-bf-uv-5rm-v0.1.0.zip"
            with zipfile.ZipFile(mac_zip, "r") as zf:
                mac_qs = zf.read("QUICKSTART.txt").decode("utf-8")
                self.assertIn("xattr -cr .", mac_qs)
                self.assertIn("./open-ht-tool flash bf-uv-5rm-fw.BF", mac_qs)

    def test_missing_app_in_fw_zip_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fw_zip = root / "bad.zip"
            with zipfile.ZipFile(fw_zip, "w") as zf:
                zf.writestr("bf-uv-5rm-fw.BF", b"BFDATA")
                zf.writestr("logo/boot.png", b"PNGDATA")
                zf.writestr("apps/apps.toml", '[slots]\n0 = "cw.app"\n')
            with self.assertRaises(FileNotFoundError):
                br.extract_and_validate_fw_zip(fw_zip, root / "out")

    def test_cli_local_bundle_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fw_zip = root / "bf-uv-5rm-fw-v1.0.0.zip"
            with zipfile.ZipFile(fw_zip, "w") as zf:
                zf.writestr("bf-uv-5rm-fw.BF", b"BF")
                zf.writestr("logo/boot.png", b"PNG")
                zf.writestr("apps/apps.toml", '[slots]\n0 = "cw.app"\n')
                zf.writestr("apps/cw.app", b"CW")

            tool_dir = root / "tools"
            tool_dir.mkdir()
            for target in br.PLATFORMS:
                (tool_dir / f"open-ht-tool-{target.upstream_id}{target.ext}").write_bytes(b"CLI")

            repo_root = Path(__file__).resolve().parent.parent
            res = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "bundle_release.py"),
                    "v0.0.0",
                    "--local-fw-zip",
                    str(fw_zip),
                    "--local-tool-dir",
                    str(tool_dir),
                    "--bundle-only",
                    "--dry-run",
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("mac-m1-bf-uv-5rm-v0.0.0.zip", res.stdout)
            self.assertIn("mac-intel-bf-uv-5rm-v0.0.0.zip", res.stdout)
            self.assertIn("windows-bf-uv-5rm-v0.0.0.zip", res.stdout)

    def test_fetch_release_metadata_surfaces_clear_error(self) -> None:
        from unittest import mock

        err = subprocess.CalledProcessError(1, ["gh"], stderr="no releases found")
        with mock.patch.object(br, "run_cmd", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                br.fetch_release_metadata("Fuzion-Software/bf-uv-5rm-firmware-open", "latest")
        self.assertIn("Fuzion-Software/bf-uv-5rm-firmware-open", str(ctx.exception))
        self.assertIn("no releases found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-1ca0f9960672
"""Lightweight contract tests for the two desktop packaging variants."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


DESKTOP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = DESKTOP_DIR.parent
MODULE_PATH = DESKTOP_DIR / "build-sidecar.py"
SPEC = importlib.util.spec_from_file_location("itkflow_build_sidecar", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
build_sidecar = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_sidecar
SPEC.loader.exec_module(build_sidecar)


class DesktopVariantTests(unittest.TestCase):
    def test_flow_and_view_have_distinct_native_identity(self) -> None:
        flow = build_sidecar.VARIANTS["flow"]
        view = build_sidecar.VARIANTS["view"]

        self.assertEqual(flow.product_name, "itkFlow")
        self.assertEqual(flow.data_slug, "itkflow")
        self.assertEqual(flow.sidecar_name, "itkflow-server")
        self.assertEqual(view.product_name, "itkView")
        self.assertEqual(view.data_slug, "itkview")
        self.assertEqual(view.data_dir_env, "ITKVIEW_DATA_DIR")
        self.assertEqual(view.sidecar_name, "itkview-server")
        self.assertIsNone(view.tauri_overlay)
        self.assertIsNotNone(flow.tauri_overlay)

    def test_view_is_the_dedicated_native_default(self) -> None:
        config = json.loads(build_sidecar.TAURI_CONFIG.read_text(encoding="utf-8"))

        self.assertEqual(build_sidecar.DEFAULT_VARIANT, "view")
        self.assertEqual(config["productName"], "itkView")
        self.assertEqual(config["mainBinaryName"], "itkview")
        self.assertEqual(config["identifier"], "org.itkflow.view")
        self.assertEqual(config["bundle"]["externalBin"], ["binaries/itkview-server"])
        self.assertIn("read-only", config["bundle"]["longDescription"])

    def test_flow_overlay_is_explicit_and_separately_installable(self) -> None:
        overlay_path = build_sidecar.VARIANTS["flow"].tauri_overlay
        self.assertIsNotNone(overlay_path)
        overlay = json.loads(overlay_path.read_text(encoding="utf-8"))

        self.assertEqual(overlay["productName"], "itkFlow")
        self.assertEqual(overlay["mainBinaryName"], "itkflow-desktop")
        self.assertEqual(overlay["identifier"], "org.itkflow.desktop")
        self.assertEqual(overlay["bundle"]["externalBin"], ["binaries/itkflow-server"])

    def test_build_environment_is_flavor_specific(self) -> None:
        flow_environment = build_sidecar.build_environment(
            build_sidecar.VARIANTS["flow"]
        )
        view_environment = build_sidecar.build_environment(
            build_sidecar.VARIANTS["view"]
        )

        self.assertEqual(flow_environment["ITKFLOW_PRODUCT_VARIANT"], "flow")
        self.assertEqual(view_environment["ITKFLOW_PRODUCT_VARIANT"], "view")
        self.assertEqual(view_environment["VITE_ITKFLOW_PRODUCT_VARIANT"], "view")
        self.assertEqual(view_environment["ITKFLOW_DESKTOP_PRODUCT_NAME"], "itkView")
        self.assertNotEqual(
            flow_environment["ITKFLOW_FRONTEND_DIST"],
            view_environment["ITKFLOW_FRONTEND_DIST"],
        )
        self.assertNotEqual(
            flow_environment["CARGO_TARGET_DIR"],
            view_environment["CARGO_TARGET_DIR"],
        )

    def test_expected_installer_is_exact_and_variant_scoped(self) -> None:
        triple = "x86_64-pc-windows-gnu"
        flow = build_sidecar.expected_installer(build_sidecar.VARIANTS["flow"], triple)
        view = build_sidecar.expected_installer(build_sidecar.VARIANTS["view"], triple)
        version = build_sidecar.bundle_version()

        self.assertEqual(flow.name, f"itkFlow_{version}_x64-setup.exe")
        self.assertEqual(view.name, f"itkView_{version}_x64-setup.exe")
        self.assertIn(str(Path("build") / "flow" / "tauri-target"), str(flow))
        self.assertIn(str(Path("build") / "view" / "tauri-target"), str(view))

    def test_bundle_targets_are_platform_specific(self) -> None:
        self.assertEqual(
            build_sidecar.bundle_targets("x86_64-pc-windows-msvc"), ("nsis",)
        )
        self.assertEqual(
            build_sidecar.bundle_targets("x86_64-unknown-linux-gnu"),
            ("deb", "rpm", "appimage"),
        )
        self.assertEqual(
            build_sidecar.bundle_targets("aarch64-unknown-linux-gnu"),
            ("deb", "rpm", "appimage"),
        )
        with self.assertRaisesRegex(SystemExit, "unsupported desktop bundle platform"):
            build_sidecar.bundle_targets("aarch64-apple-darwin")

    def test_linux_bundle_config_matches_the_builder_contract(self) -> None:
        config = json.loads(
            build_sidecar.LINUX_TAURI_CONFIG.read_text(encoding="utf-8")
        )

        self.assertEqual(config["bundle"]["targets"], ["deb", "rpm", "appimage"])

    def test_linux_artifacts_are_complete_and_variant_scoped(self) -> None:
        triple = "x86_64-unknown-linux-gnu"
        variant = build_sidecar.VARIANTS["view"]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(build_sidecar, "BUILD_DIR", Path(directory)):
                bundle_dir = (
                    build_sidecar.variant_build_dir(variant)
                    / "tauri-target"
                    / triple
                    / "release"
                    / "bundle"
                )
                expected = (
                    bundle_dir / "deb" / "itkView_0.2.3_amd64.deb",
                    bundle_dir / "rpm" / "itkView-0.2.3-1.x86_64.rpm",
                    bundle_dir / "appimage" / "itkView_0.2.3_amd64.AppImage",
                )
                for artifact in expected:
                    artifact.parent.mkdir(parents=True, exist_ok=True)
                    artifact.touch()

                self.assertEqual(
                    build_sidecar.bundle_artifacts(variant, triple), expected
                )

    def test_linux_artifacts_fail_closed_when_a_format_is_missing(self) -> None:
        triple = "aarch64-unknown-linux-gnu"
        variant = build_sidecar.VARIANTS["view"]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(build_sidecar, "BUILD_DIR", Path(directory)):
                deb = (
                    build_sidecar.variant_build_dir(variant)
                    / "tauri-target"
                    / triple
                    / "release"
                    / "bundle"
                    / "deb"
                    / "itkView_0.2.3_arm64.deb"
                )
                deb.parent.mkdir(parents=True, exist_ok=True)
                deb.touch()

                with self.assertRaisesRegex(SystemExit, "exactly one rpm bundle"):
                    build_sidecar.bundle_artifacts(variant, triple)

    def test_flatpak_contract_is_network_only_and_version_matched(self) -> None:
        manifest = (DESKTOP_DIR / "flatpak" / "org.itkflow.view.yml").read_text(
            encoding="utf-8"
        )
        metadata = ET.parse(
            DESKTOP_DIR / "flatpak" / "org.itkflow.view.metainfo.xml"
        ).getroot()

        self.assertIn("id: org.itkflow.view", manifest)
        self.assertIn('runtime-version: "50"', manifest)
        self.assertIn("--share=network", manifest)
        self.assertNotIn("--filesystem=host", manifest)
        self.assertNotIn("--filesystem=home", manifest)
        self.assertNotIn("appstream-compose: false", manifest)
        self.assertEqual(metadata.findtext("id"), "org.itkflow.view")
        release = metadata.find("./releases/release")
        self.assertIsNotNone(release)
        self.assertEqual(release.attrib["version"], build_sidecar.bundle_version())

    def test_linux_workflow_builds_native_architectures_and_checks_shutdown(
        self,
    ) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "linux-packages.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("runner: ubuntu-22.04", workflow)
        self.assertIn("runner: ubuntu-22.04-arm", workflow)
        self.assertIn('test "$(uname -m)" = "${{ matrix.arch }}"', workflow)
        self.assertIn("ppa:flatpak/stable", workflow)
        self.assertIn("ge 1.4.4", workflow)
        self.assertIn("npm --prefix desktop run build", workflow)
        self.assertIn("PyInstaller server child survived its bootstrap", workflow)
        self.assertIn("process_is_live()", workflow)
        self.assertIn('test "${state}" != "Z"', workflow)
        self.assertIn('kill -TERM "${graceful_bootstrap_pid}"', workflow)
        self.assertIn("left its _MEI extraction directory after SIGTERM", workflow)
        self.assertIn('kill -KILL "${forced_bootstrap_pid}"', workflow)
        self.assertIn("org.gnome.Platform//50", workflow)
        self.assertIn("libwebkit2gtk-4.1-0", workflow)
        self.assertIn("libgtk-3-0", workflow)
        self.assertIn("libwebkit2gtk-4.1.so.0()(64bit)", workflow)
        self.assertIn("libgtk-3.so.0()(64bit)", workflow)
        self.assertIn('target_triple="$(rustc -vV', workflow)
        self.assertIn('find "${deb_dir}"', workflow)
        self.assertIn('find "${bundle_root}/${target}"', workflow)
        self.assertIn("-mindepth 1 -maxdepth 1 -type f", workflow)
        self.assertNotIn('-path "*/release/bundle/${target}/*" -type f', workflow)

    def test_linux_tag_release_waits_for_both_verified_architectures(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "linux-packages.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("needs: packages", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("name: itkview-linux-x86_64", workflow)
        self.assertIn("name: itkview-linux-aarch64", workflow)
        self.assertIn('> "SHA256SUMS-${{ matrix.arch }}"', workflow)
        self.assertIn('checksum_file="SHA256SUMS-${arch}"', workflow)
        self.assertIn("sha256sum --check --strict", workflow)
        self.assertIn("Release asset filename collision", workflow)
        self.assertIn('test "${#release_files[@]}" -eq 10', workflow)
        self.assertIn('gh release create "${tag}"', workflow)
        self.assertIn('notes_file="docs/releases/${tag}.md"', workflow)
        self.assertIn('--notes-file "${notes_file}"', workflow)
        self.assertNotIn("--generate-notes", workflow)
        self.assertIn('gh release upload "${tag}"', workflow)
        self.assertIn('gh release edit "${tag}" --draft=false', workflow)
        self.assertEqual(workflow.count("contents: write"), 1)

    def test_desktop_scripts_use_the_locked_cross_platform_python(self) -> None:
        package = json.loads((DESKTOP_DIR / "package.json").read_text(encoding="utf-8"))

        for name in (
            "sidecar",
            "sidecar:flow",
            "sidecar:view",
            "dev",
            "build",
            "build:flow",
            "build:view",
            "test:variants",
        ):
            command = package["scripts"][name]
            self.assertIn("uv run --project ../backend", command)
            self.assertIn("--extra desktop", command)
            self.assertIn("--locked", command)

    def test_pyinstaller_release_requires_pdb_client_and_parent_guard(self) -> None:
        spec = (DESKTOP_DIR / "itkflow-server.spec").read_text(encoding="utf-8")
        backend_project = (REPO_ROOT / "backend" / "pyproject.toml").read_text(
            encoding="utf-8"
        )

        self.assertIn('for package in ("itkdb", "certifi")', spec)
        self.assertIn("Required desktop package", spec)
        self.assertIn("pyinstaller_parent_guard.py", spec)
        self.assertIn(
            'desktop = ["itkdb>=0.6", "pyinstaller>=6.10,<7"]',
            backend_project,
        )

    def test_linux_shell_prefers_graceful_sidecar_shutdown(self) -> None:
        source = (DESKTOP_DIR / "src-tauri" / "src" / "main.rs").read_text(
            encoding="utf-8"
        )
        cargo = (DESKTOP_DIR / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")

        self.assertIn("libc::SIGTERM", source)
        self.assertIn("SIDECAR_SHUTDOWN_TIMEOUT", source)
        self.assertIn("SIDECAR_FORCE_SHUTDOWN_TIMEOUT", source)
        self.assertIn('("method", "sigkill".to_string())', source)
        self.assertIn("[target.'cfg(target_os = \"linux\")'.dependencies]", cargo)

    def test_flow_splash_is_generated_without_changing_the_view_source(self) -> None:
        source = (DESKTOP_DIR / "splash" / "index.html").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(build_sidecar, "BUILD_DIR", Path(directory)):
                build_sidecar.prepare_splash(build_sidecar.VARIANTS["flow"])
                rendered = (
                    Path(directory) / "flow" / "splash" / "index.html"
                ).read_text(encoding="utf-8")

        self.assertIn("<title>itkFlow</title>", rendered)
        self.assertIn("<h1>itkFlow</h1>", rendered)
        self.assertIn("ITk strip module production cockpit", rendered)
        self.assertEqual(
            source,
            (DESKTOP_DIR / "splash" / "index.html").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()

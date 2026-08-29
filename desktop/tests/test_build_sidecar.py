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
from pathlib import Path
from unittest.mock import patch


DESKTOP_DIR = Path(__file__).resolve().parents[1]
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

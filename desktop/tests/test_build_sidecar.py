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
        self.assertNotEqual(flow.tauri_overlay, view.tauri_overlay)

    def test_view_overlay_is_a_separate_installable_application(self) -> None:
        overlay_path = build_sidecar.VARIANTS["view"].tauri_overlay
        self.assertIsNotNone(overlay_path)
        overlay = json.loads(overlay_path.read_text(encoding="utf-8"))

        self.assertEqual(overlay["productName"], "itkView")
        self.assertEqual(overlay["mainBinaryName"], "itkview")
        self.assertEqual(overlay["identifier"], "org.itkflow.view")
        self.assertEqual(overlay["bundle"]["externalBin"], ["binaries/itkview-server"])
        self.assertIn("read-only", overlay["bundle"]["longDescription"])

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

    def test_view_splash_is_generated_without_changing_the_source(self) -> None:
        source = (DESKTOP_DIR / "splash" / "index.html").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(build_sidecar, "BUILD_DIR", Path(directory)):
                build_sidecar.prepare_splash(build_sidecar.VARIANTS["view"])
                rendered = (
                    Path(directory) / "view" / "splash" / "index.html"
                ).read_text(encoding="utf-8")

        self.assertIn("<title>itkView</title>", rendered)
        self.assertIn("<h1>itkView</h1>", rendered)
        self.assertIn("Read-only ITk strip module production viewer", rendered)
        self.assertEqual(
            source,
            (DESKTOP_DIR / "splash" / "index.html").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()

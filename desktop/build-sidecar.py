# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-7f2f4cd24a38
"""Build a desktop product variant: frontend -> PyInstaller -> Tauri bundles.

Tauri's `externalBin` looks for a file named `<name>-<target-triple>` next to
the configured path, so the sidecar step ends in a rename, not a copy into
place by hand. `--bundle` then runs `tauri build --target <host triple>`
itself: the explicit target keeps the bundler's triple aligned with the
sidecar's file name. Windows produces NSIS; Linux produces DEB, RPM and
AppImage bundles (ADR 005).

    python desktop/build-sidecar.py [--variant flow|view] [--skip-frontend] [--bundle]

`npm run build` in desktop/ runs the whole chain.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parent
REPO_ROOT = DESKTOP_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
if sys.platform == "win32":
    BACKEND_PYTHON = REPO_ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
else:
    BACKEND_PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
BINARIES_DIR = DESKTOP_DIR / "src-tauri" / "binaries"
BUILD_DIR = DESKTOP_DIR / "build"
TAURI_CONFIG = DESKTOP_DIR / "src-tauri" / "tauri.conf.json"
LINUX_TAURI_CONFIG = DESKTOP_DIR / "src-tauri" / "tauri.linux.conf.json"

BUNDLE_SUFFIXES = {
    "appimage": ".AppImage",
    "deb": ".deb",
    "nsis": ".exe",
    "rpm": ".rpm",
}


@dataclass(frozen=True)
class DesktopVariant:
    key: str
    product_name: str
    data_slug: str
    data_dir_env: str
    sidecar_name: str
    tagline: str
    tauri_overlay: Path | None = None


DEFAULT_VARIANT = "view"

VARIANTS = {
    "flow": DesktopVariant(
        key="flow",
        product_name="itkFlow",
        data_slug="itkflow",
        data_dir_env="ITKFLOW_DATA_DIR",
        sidecar_name="itkflow-server",
        tagline="ITk strip module production cockpit",
        tauri_overlay=DESKTOP_DIR / "src-tauri" / "tauri.flow.conf.json",
    ),
    "view": DesktopVariant(
        key="view",
        product_name="itkView",
        data_slug="itkview",
        data_dir_env="ITKVIEW_DATA_DIR",
        sidecar_name="itkview-server",
        tagline="Read-only ITk strip module production viewer",
    ),
}


def run(command: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> None:
    printable = " ".join(command)
    print(f"\n$ {printable}\n  (in {cwd})", flush=True)
    result = subprocess.run(command, cwd=cwd, env=env)
    if result.returncode != 0:
        raise SystemExit(f"failed with exit code {result.returncode}: {printable}")


def target_triple() -> str:
    """The triple Tauri expects in the sidecar file name."""
    output = subprocess.run(
        ["rustc", "-vV"], capture_output=True, text=True, check=True
    ).stdout
    match = re.search(r"^host:\s*(\S+)$", output, re.MULTILINE)
    if not match:
        raise SystemExit("could not read the host target triple from 'rustc -vV'.")
    return match.group(1)


def npm_command() -> str:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise SystemExit("npm was not found on PATH.")
    return npm


def variant_build_dir(variant: DesktopVariant) -> Path:
    return BUILD_DIR / variant.key


def frontend_dist_dir(variant: DesktopVariant) -> Path:
    return variant_build_dir(variant) / "frontend"


def build_environment(variant: DesktopVariant) -> dict[str, str]:
    """Return the deterministic product contract shared by all build stages."""
    environment = os.environ.copy()
    environment.update(
        {
            "ITKFLOW_PRODUCT_VARIANT": variant.key,
            "VITE_ITKFLOW_PRODUCT_VARIANT": variant.key,
            "VITE_ITKFLOW_PRODUCT_NAME": variant.product_name,
            "ITKFLOW_DESKTOP_PRODUCT_NAME": variant.product_name,
            "ITKFLOW_DESKTOP_DATA_SLUG": variant.data_slug,
            "ITKFLOW_DESKTOP_DATA_DIR_ENV": variant.data_dir_env,
            "ITKFLOW_DESKTOP_SIDECAR_NAME": variant.sidecar_name,
            "ITKFLOW_FRONTEND_DIST": str(frontend_dist_dir(variant)),
            # Separate Cargo output prevents a stale other-variant bundle from
            # being mistaken for the artifact produced by this invocation.
            "CARGO_TARGET_DIR": str(variant_build_dir(variant) / "tauri-target"),
        }
    )
    return environment


def build_frontend(variant: DesktopVariant, environment: dict[str, str]) -> None:
    output = frontend_dist_dir(variant)
    run(
        [
            npm_command(),
            "run",
            "build",
            "--",
            "--outDir",
            str(output),
            "--emptyOutDir",
        ],
        cwd=FRONTEND_DIR,
        env=environment,
    )


def prepare_splash(variant: DesktopVariant) -> None:
    """Generate the non-default product's branded startup page."""
    if variant.key == DEFAULT_VARIANT:
        return
    source = (DESKTOP_DIR / "splash" / "index.html").read_text(encoding="utf-8")
    branded = source.replace(
        "<title>itkView</title>", f"<title>{variant.product_name}</title>"
    )
    branded = branded.replace("<h1>itkView</h1>", f"<h1>{variant.product_name}</h1>")
    branded = branded.replace(
        "Read-only ITk strip module production viewer",
        variant.tagline,
    )
    if branded == source:
        raise SystemExit("could not apply desktop splash branding")
    target = variant_build_dir(variant) / "splash" / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(branded, encoding="utf-8")


def bundle_version() -> str:
    payload = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    version = payload.get("version")
    if not isinstance(version, str) or not version:
        raise SystemExit(f"missing version in {TAURI_CONFIG}")
    return version


def installer_arch(triple: str) -> str:
    architecture = triple.split("-", 1)[0]
    names = {"x86_64": "x64", "aarch64": "arm64", "i686": "x86"}
    try:
        return names[architecture]
    except KeyError:
        raise SystemExit(
            f"unsupported installer architecture in target triple: {triple}"
        ) from None


def bundle_targets(triple: str) -> tuple[str, ...]:
    """Return the first-party bundle set for a native target triple."""
    normalized = triple.lower()
    if "-windows-" in normalized:
        return ("nsis",)
    if "-linux-" in normalized:
        return ("deb", "rpm", "appimage")
    raise SystemExit(
        f"unsupported desktop bundle platform in target triple: {triple}. "
        "Supported release platforms are Windows and Linux."
    )


def expected_installer(variant: DesktopVariant, triple: str) -> Path:
    if bundle_targets(triple) != ("nsis",):
        raise SystemExit(f"NSIS installers are only available for Windows: {triple}")
    target_dir = variant_build_dir(variant) / "tauri-target"
    filename = (
        f"{variant.product_name}_{bundle_version()}_{installer_arch(triple)}-setup.exe"
    )
    return target_dir / triple / "release" / "bundle" / "nsis" / filename


def bundle_artifacts(variant: DesktopVariant, triple: str) -> tuple[Path, ...]:
    """Resolve exactly one artifact for every platform target."""
    bundle_dir = (
        variant_build_dir(variant) / "tauri-target" / triple / "release" / "bundle"
    )
    artifacts: list[Path] = []
    for target in bundle_targets(triple):
        if target == "nsis":
            matches = [expected_installer(variant, triple)]
        else:
            suffix = BUNDLE_SUFFIXES[target]
            target_dir = bundle_dir / target
            matches = sorted(
                path for path in target_dir.glob(f"*{suffix}") if path.is_file()
            )
        if len(matches) != 1 or not matches[0].is_file():
            rendered = ", ".join(str(path) for path in matches) or "none"
            raise SystemExit(
                f"Tauri did not produce exactly one {target} bundle in "
                f"{bundle_dir / target}; found: {rendered}"
            )
        artifacts.append(matches[0])
    return tuple(artifacts)


def bundle_app(
    variant: DesktopVariant, triple: str, environment: dict[str, str]
) -> tuple[Path, ...]:
    targets = bundle_targets(triple)
    command = [npm_command(), "exec", "--", "tauri", "build", "--target", triple]
    command += ["--bundles", ",".join(targets)]
    if variant.tauri_overlay is not None:
        if not variant.tauri_overlay.is_file():
            raise SystemExit(
                f"Tauri variant overlay not found: {variant.tauri_overlay}"
            )
        command += ["--config", str(variant.tauri_overlay)]
    run(command, cwd=DESKTOP_DIR, env=environment)

    artifacts = bundle_artifacts(variant, triple)
    for artifact in artifacts:
        print(f"bundle ready: {artifact.relative_to(REPO_ROOT)}")
    return artifacts


def build_sidecar(variant: DesktopVariant, environment: dict[str, str]) -> Path:
    if not BACKEND_PYTHON.is_file():
        raise SystemExit(
            f"backend environment not found at {BACKEND_PYTHON}. "
            "Create it as documented in README.md."
        )
    run(
        [
            str(BACKEND_PYTHON),
            "-m",
            "PyInstaller",
            "itkflow-server.spec",
            "--distpath",
            str(variant_build_dir(variant) / "dist"),
            "--workpath",
            str(variant_build_dir(variant) / "work"),
            "--noconfirm",
        ],
        cwd=DESKTOP_DIR,
        env=environment,
    )
    suffix = ".exe" if sys.platform == "win32" else ""
    built = variant_build_dir(variant) / "dist" / f"{variant.sidecar_name}{suffix}"
    if not built.is_file():
        raise SystemExit(f"PyInstaller did not produce {built}.")
    return built


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-sidecar")
    parser.add_argument(
        "--variant",
        choices=sorted(VARIANTS),
        default=DEFAULT_VARIANT,
        help=f"Desktop product to build (default: {DEFAULT_VARIANT}).",
    )
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Reuse the selected variant's existing frontend output.",
    )
    parser.add_argument(
        "--bundle",
        action="store_true",
        help="After the sidecar, build the native Windows or Linux bundle set too.",
    )
    args = parser.parse_args(argv)
    variant = VARIANTS[args.variant]
    environment = build_environment(variant)

    if not args.skip_frontend:
        build_frontend(variant, environment)
    elif not (frontend_dist_dir(variant) / "index.html").is_file():
        raise SystemExit(
            "--skip-frontend given but the selected variant's frontend build is missing: "
            f"{frontend_dist_dir(variant)}"
        )
    prepare_splash(variant)

    built = build_sidecar(variant, environment)

    triple = target_triple()
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    target = BINARIES_DIR / f"{variant.sidecar_name}-{triple}{built.suffix}"
    shutil.copy2(built, target)
    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"\nsidecar ready: {target.relative_to(REPO_ROOT)} ({size_mb:.0f} MB)")

    if args.bundle:
        bundle_app(variant, triple, environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

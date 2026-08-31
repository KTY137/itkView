# itkView

itkView is a fail-closed, read-only viewer for ATLAS ITk strip production
data. It mirrors authorized PDB data and attachments into an isolated local
store, then makes components, images, original plots, generated fallbacks,
collective IV/CV curves and production statistics available without exposing
production-data authoring or PDB writes.

The ITk Production Database remains the source of truth. "Read only" refers
to that remote boundary: itkView still writes its local mirror, accounts,
settings, attachment files, logs and caches.

## Install on Windows

Download the newest `itkView_<version>_x64-setup.exe` from the
**[itkView Releases page](https://github.com/KTY137/itkView/releases)**.

The alpha installer is not code-signed yet, so Windows SmartScreen may show a
warning on first launch. Verify that the download came from the release page,
then use **More info -> Run anyway** if you trust it.

On first start:

1. create the initial local administrator when prompted;
2. open **Account** and connect your personal Plus4U/PDB access codes;
3. run the component/evidence sync to populate the new local mirror.

Application data lives under `%LOCALAPPDATA%\itkview`, separately from
itkFlow. This includes the SQLite database, encrypted credential key,
attachments and rotating logs. A fresh itkView installation therefore starts
empty even when itkFlow is already installed; that isolation is intentional.

## Install on Linux

Linux release builds provide four package formats for both `x86_64` and
`aarch64`:

| Package | Intended systems |
|---|---|
| `.flatpak` | Distribution-independent desktop install with a constrained runtime |
| `.AppImage` | Portable launch on compatible glibc-based desktop distributions; the current Ubuntu 22.04 build can require glibc 2.35 |
| `.deb` | Debian, Ubuntu, Linux Mint and derivatives |
| `.rpm` | Fedora and openSUSE families; RHEL 10 derivatives need EPEL 10 |

Verify the downloaded files against the checksum file for your architecture
(`SHA256SUMS-x86_64` or `SHA256SUMS-aarch64`), then install one format:

```bash
sha256sum --ignore-missing -c "SHA256SUMS-$(uname -m)"
flatpak install --user ./itkView_<version>_<arch>.flatpak
# or: chmod +x ./itkView_<version>_<arch>.AppImage && ./itkView_<version>_<arch>.AppImage
# or: sudo apt install ./itkView_<version>_<arch>.deb
# or: sudo dnf install ./itkView-<version>-1.<arch>.rpm
```

Run the Flatpak with `flatpak run org.itkflow.view`. Its sandbox grants
network, display and GPU access, but no blanket home- or host-filesystem
access. Native packages store application data under
`${XDG_DATA_HOME:-$HOME/.local/share}/itkview`; Flatpak keeps the same logical
state inside its per-application data directory.

These formats cover the mainstream Linux desktop families; they are not a
claim that every package manager or libc is supported natively. Alpine/musl,
NixOS, Guix, source-only distributions and 32-bit systems have no first-party
native package. RHEL 9 and compatible distributions also lack the required
WebKitGTK 4.1 runtime, so use the Flatpak there. The AppImage bundles WebKitGTK
and therefore does not need that host package, but its Ubuntu 22.04 payload can
require glibc 2.35 and is not advertised for RHEL 9. Where no desktop format
fits, use the Docker Compose deployment for an institute-wide service.

## What itkView includes

- component search, scanner input, board, family and detail views;
- authorized component, test, evidence, attachment, tool and shipment sync;
- locally stored images and original plots;
- generated plots only when no usable original plot or array curve exists;
- persistent measurement caching and collective IV/CV curve controls;
- required-test statistics and production-hold indicators;
- local accounts, institute settings and personal credential management;
- sync retry, rotating crash logs and bounded diagnostic export.

## What itkView intentionally removes

There is no Triage/Ingest workflow, Staged/Outbox tab, watched-folder upload,
manual or file-based test entry, assembly, component registration, stage move,
shipment reception editing, reminder delivery, notification mutation,
`Push to PDB` or `Discard`.

This is enforced beyond the interface. The server rejects unclassified unsafe
mutations by default, forces the PDB write scope and processors off, and guards
the final submitter and standalone worker. Administrators do not bypass the
product boundary. Authentication, local administration, personal credentials
and explicitly classified read-sync requests remain available because they
maintain the local viewer.

See [ADR 007](docs/adr/007-itkview-read-only-product.md) for the complete
security contract.

## Docker deployment

The dedicated Compose stack owns its own project, PostgreSQL database and
database/attachment volumes:

```bash
cd deploy
cp .env.example .env
# Fill in POSTGRES_PASSWORD and a new credential-encryption key.
docker compose up --build
```

Do not reuse itkFlow's `.env`, database volume, attachment volume or
credential key. Full setup, backup and offline-mode guidance is in the
[deployment guide](deploy/README.md).

## Development

The repository default is itkView. Standard development and build commands
therefore select the read-only product unless a shared-core regression test
explicitly requests the Flow variant.

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"
pytest
uvicorn app.main:create_app --factory --reload
```

On Linux or macOS, activate with `source .venv/bin/activate`. Install
`.[dev,pdb]` only when an environment is intentionally prepared for PDB
reads. The normal suite stays offline and excludes every live-PDB marker.

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

Vite listens on <http://127.0.0.1:5173> and proxies `/api` to the backend on
port `8000`. The first browser visit provides first-run admin setup; no default
password is shipped.

### Desktop installer

Install `uv`, a Rust toolchain and the platform prerequisites required by
Tauri, then run:

```bash
# Ubuntu 22.04 release-builder prerequisites
sudo apt install build-essential file libayatana-appindicator3-dev libfuse2 \
  librsvg2-dev libssl-dev libwebkit2gtk-4.1-dev libxdo-dev patchelf rpm
```

The release workflow uses Python 3.12 and Node.js 22. With those runtimes
available, the application build itself is:

```bash
uv sync --project backend --extra desktop --locked
cd desktop
npm ci
npm run build
```

The default command builds the itkView frontend, PyInstaller sidecar and
native Tauri packages in a variant-isolated tree. On Windows, the expected
artifact is:

```text
desktop/build/view/tauri-target/<triple>/release/bundle/nsis/itkView_<version>_x64-setup.exe
```

On Linux it produces one artifact in each of these directories:

```text
desktop/build/view/tauri-target/<triple>/release/bundle/deb/
desktop/build/view/tauri-target/<triple>/release/bundle/rpm/
desktop/build/view/tauri-target/<triple>/release/bundle/appimage/
```

The manual/tag workflow in `.github/workflows/linux-packages.yml` builds these
packages natively on `x86_64` and `aarch64`, verifies both graceful sidecar
shutdown (including PyInstaller `_MEI*` cleanup) and the forced parent-death
fallback, wraps the DEB as a Flatpak and emits per-architecture checksums. On
the Ubuntu 22.04 runners it obtains `flatpak-builder >= 1.4.4` from the Flatpak stable PPA
because Jammy's archive builder cannot compose metadata for the current GNOME
runtime. A tag matching the bundle version publishes both verified
architectures together on the GitHub Releases page; manual workflow runs keep
the packages as 30-day Actions artifacts without publishing them. Package and
binary signing remain explicit maintainer work.

## Verification

Useful offline checks before a release:

```bash
cd backend && pytest && ruff check app tests
cd frontend && npm test -- --run && npm run build
cd desktop && npm run test:variants
```

A release smoke test must additionally start the packaged itkView sidecar
with isolated temporary state and verify that `/health` reports the View
variant, write features disabled and PDB write scope disabled. No agent or
normal test run may enable live production access.

## Repository map

| Path | Purpose |
|---|---|
| `backend/` | FastAPI API, local mirror, sync and server-side product policy |
| `frontend/` | React/Vite read-only product UI |
| `desktop/` | Tauri shell and PyInstaller sidecar build |
| `deploy/` | isolated Docker Compose deployment |
| `docs/` | architecture, safety rules, roadmap and UI reference |

Contributors and coding agents must read `CLAUDE.md`,
`docs/04-roadmap.md` and, before UI work,
`docs/05-ui-design-reference.md`. Never execute or import
`references/zeuthenflow`; it is read/grep-only reference material.

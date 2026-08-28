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

Install a Rust toolchain and the platform prerequisites required by Tauri,
then run:

```bash
cd desktop
npm ci
npm run build
```

The default command builds the itkView frontend, PyInstaller sidecar and Tauri
installer in a variant-isolated tree. On Windows, the expected artifact is:

```text
desktop/build/view/tauri-target/<triple>/release/bundle/nsis/itkView_<version>_x64-setup.exe
```

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

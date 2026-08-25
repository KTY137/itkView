# itkFlow

Production cockpit for ATLAS ITk strip module assembly. Replaces the
Google-Sheet + CERNBox + zFlow triage workflow with a self-hostable web app.
Multi-institute by design — the ITk Production Database (PDB) remains the
single source of truth; itkFlow orchestrates local data entry, validation,
test ingestion and reviewed PDB writes.

**Safety first:** the default configuration cannot reach the production PDB.
Production reads require a deliberate double opt-in, and writes remain limited
to itkFlow-registered DUMMY test components. See `CLAUDE.md` for the hard rules.

For current implementation priorities, agents and humans should start with
`docs/04-roadmap.md`; `docs/02-revamp-plan.md` remains the product vision.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI + SQLAlchemy backend (Python ≥ 3.10, 3.12 in Docker) |
| `frontend/` | React + TypeScript (Vite) frontend |
| `agent/` | Watched-folder upload agent for instrument PCs (phase 2) |
| `deploy/` | Docker Compose, Dockerfiles, `.env.example` |
| `desktop/` | Tauri desktop shell: bundles the backend and the built UI into one app |
| `docs/` | Internal planning documents (German): roadmap `docs/04-roadmap.md`, binding UI design reference `docs/05-ui-design-reference.md` (+ mockup `docs/itkflow-ui-mockup.html`) |

## Prerequisites

| Requirement | Version | Needed for |
|---|---|---|
| Python | ≥ 3.10 (3.12 in Docker/CI) | backend |
| Node.js + npm | ≥ 20.19 (Vite 7 / React 19) | frontend |
| Docker + Compose | current | optional: full-stack deployment only |

A Plus4U/PDB account is **not** needed to run itkFlow. Every person connects
their own PDB access codes later, in the app, under **Account**.

## Quickstart (development)

### First run, in order

1. Install the backend environment (`backend/.venv`) and the frontend
   dependencies (`frontend/node_modules`) — see *Manual setup* below.
2. Create a local admin account: from `backend/`, run
   `python -m app.create_admin --help`. There is no default account.
3. Start the app (launcher below, or the manual commands).
4. Sign in at <http://127.0.0.1:5173/>.
5. Open **Account** and connect your personal Plus4U/PDB access codes.
   This step needs a server started with production reads enabled — see the
   next paragraph and *Troubleshooting*.

### Windows launcher

On Windows, the root launcher provides the shortest repeatable start:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-itkflow.ps1
```

The default remains offline from the PDB. To make the component **Sync** action
use the production PDB read path, start with the explicit production-read
opt-in (the historical PDB test host no longer exists):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-itkflow.ps1 -EnableProductionReads
```

It safely reclaims existing itkFlow listeners on the fixed development ports
`8000` and `5173`, starts the backend and frontend in the background, checks
both services, and opens <http://127.0.0.1:5173/>. It does not reset application
data or accounts. If an unrelated process owns either port, the launcher stops
and reports it; use `-ForcePortCleanup` only after confirming that process and
its child process tree may be terminated. Use `-NoBrowser` to start without
opening a browser. The launcher also keeps production PDB access disabled for
its backend process unless `-EnableProductionReads` is supplied. Even in that
mode, it disables the PDB write-test opt-in, keeps `dummy_only` scope, and does
not start the outbox worker. The launcher creates a stable encryption key under
the current Windows profile (outside the repository). After signing in, every
person opens **Account** and connects their own Plus4U/PDB access-code pair;
Sync and direct PDB reads then run only as that account. Saved codes are never
returned to the browser, and server-wide access-code variables are not used by
web requests.

Component syncs run as background jobs. Their phase, count, elapsed time and
last update remain visible in the top bar while you browse another screen; the
Components screen shows the detailed progress and reconnects after a reload.

### Manual setup

Backend:

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
pytest                          # runs offline — no PDB access, no login needed
python -m app.seed_demo          # optional: creates demo institute + component mirror data
uvicorn app.main:create_app --factory --reload   # http://127.0.0.1:8000/health
```

Install `.[dev,pdb]` instead when this environment should perform explicitly
enabled live PDB reads. With uv, use `uv sync --extra pdb --extra dev`. The
production-read launcher checks this before replacing a running server. The
normal test suite remains offline.

When starting the backend manually (without `start-itkflow.ps1`), also set one
stable `ITKFLOW_PDB_CREDENTIAL_ENCRYPTION_KEY`; generate a URL-safe 32-byte
value once and keep it outside the repository. Losing or replacing it makes
saved personal PDB connections unreadable. Compose setup is documented in
`deploy/README.md`.

Frontend:

```bash
cd frontend
npm install
npm run dev                     # http://127.0.0.1:5173 (proxies /api to :8000)
```

The first sign-in requires a local account; `seed_demo` deliberately does not
create one. From `backend/`, run `python -m app.create_admin --help` to create
or update an admin for an existing institute without storing credentials in
the repository.

Full stack via Docker: see `deploy/README.md`.

## Desktop build

The desktop app is the same itkFlow, packaged: a small shell starts the backend
and shows its UI. Backend and frontend are served from one local origin, so
sign-in, sessions and PDB connections behave exactly as they do in a browser.
It is a single-workstation build — an institute still runs the server
deployment, because roles, audit and the outbox worker are shared state.

Prerequisites, on top of the ones above: a Rust toolchain (`rustup`), and on
Windows the MSVC build tools (Tauri's supported toolchain there).

```bash
cd desktop
npm install                          # Tauri CLI
python build-sidecar.py              # builds the frontend, then the backend sidecar
npm run build                        # produces the installer
```

`build-sidecar.py` bundles the backend with PyInstaller and names the result
for the Rust host target triple, which is what Tauri's sidecar mechanism
expects. Pass `--skip-frontend` to reuse an existing `frontend/dist`. For a run
without packaging an installer, `npm run dev` starts the same shell.

On a GNU toolchain (`rustup show` reports `x86_64-pc-windows-gnu`), build with
the target spelled out:

```bash
npx tauri build --target x86_64-pc-windows-gnu
```

Without it the bundler looks for the sidecar under the MSVC triple and stops
with `resource path binaries\itkflow-server-x86_64-pc-windows-msvc.exe doesn't
exist`, because the sidecar is named for the host triple. MSVC needs no flag.

The installer lands in
`desktop/src-tauri/target/<triple>/release/bundle/nsis/itkFlow_<version>_x64-setup.exe`.

The app keeps its database, credential key and logs in the per-user
application data directory — on Windows `%LOCALAPPDATA%\itkflow`, deliberately
the same place `start-itkflow.ps1` uses, so a PDB connection made in the dev
launcher keeps working in the packaged app. **Back up `pdb-credential.key`**:
losing it makes saved PDB connections unreadable.

PDB access is unchanged by packaging: the desktop build starts against no PDB
and needs the same two deliberate opt-ins for production reads. Design notes
and the trade-offs are in `docs/adr/005-desktop-packaging.md`.

## Troubleshooting

**Account → “Test connection” reports “The PDB could not be reached”, although
the same access codes work elsewhere.**
The server is running against the retired PDB *test* configuration. Check
<http://127.0.0.1:8000/health>: if it reports `"pdb_instance": "test"`, no PDB
is reachable by design — the historical test host
`itkpd-test.unicorncollege.cz` no longer resolves, and itkFlow never silently
falls back to production. Restart with the production-read opt-in:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-itkflow.ps1 -EnableProductionReads
```

Without the launcher, set `ITKFLOW_PDB_INSTANCE=production` **and**
`ITKFLOW_ALLOW_PRODUCTION=true` for the backend process. Writes stay confined
to DUMMY components either way.

**“PDB client support is unavailable on this itkFlow server.”**
The `pdb` extra is missing. In `backend/`, run `uv sync --extra pdb --extra dev`
(or `pip install -e ".[dev,pdb]"`) and restart.

**A saved connection suddenly cannot be opened.**
`ITKFLOW_PDB_CREDENTIAL_ENCRYPTION_KEY` changed. Restore the previous key, or
have each person reconnect their codes under **Account**.

**The launcher refuses to start: a port is in use.**
Another process owns `8000` or `5173`. Identify it first; only then rerun with
`-ForcePortCleanup`, which terminates that process and its child tree.

**The desktop app opens but stays on the splash screen.**
The backend did not come up. Its log says why:
`%LOCALAPPDATA%\itkflow\logs\server.log` — a windowed build has no console,
so that file is the only trail.

**Sign-in fails right after setup.**
No account exists yet. From `backend/`, create one with
`python -m app.create_admin`. Run it from `backend/` so it picks up
`backend/.env` and writes to the same database the backend uses.

## Testing policy

- The standard test suite is **fully offline**: fixtures and mocks, no tokens.
- PDB integration tests are explicitly marked and excluded from the default
  run; production reads and DUMMY-scoped writes require separate opt-ins.
- Production PDB access is refused by the application unless explicitly and
  deliberately enabled — see `backend/app/config.py`.

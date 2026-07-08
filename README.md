# itkFlow

Production cockpit for ATLAS ITk strip module assembly. Replaces the
Google-Sheet + CERNBox + zFlow triage workflow with a self-hostable web app.
Multi-institute by design — the ITk Production Database (PDB) remains the
single source of truth; itkFlow orchestrates local data entry, validation,
test ingestion and reviewed PDB writes.

**Safety first:** nothing in this repository talks to the production PDB.
The default (and only pre-configured) instance is the PDB **test instance**.
See `CLAUDE.md` for the hard rules.

For current implementation priorities, agents and humans should start with
`docs/04-roadmap.md`; `docs/02-revamp-plan.md` remains the product vision.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI + SQLAlchemy backend (Python ≥ 3.10, 3.12 in Docker) |
| `frontend/` | React + TypeScript (Vite) frontend |
| `agent/` | Watched-folder upload agent for instrument PCs (phase 2) |
| `deploy/` | Docker Compose, Dockerfiles, `.env.example` |
| `docs/` | Internal planning documents (German): roadmap `docs/04-roadmap.md`, binding UI design reference `docs/05-ui-design-reference.md` (+ mockup `docs/itkflow-ui-mockup.html`) |

## Quickstart (development)

Backend:

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
pytest                          # runs offline — no PDB access, no login needed
python -m app.seed_demo          # optional: creates demo institute + component mirror data
uvicorn app.main:create_app --factory --reload   # http://localhost:8000/health
```

Frontend:

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173 (proxies /api to :8000)
```

Full stack via Docker: see `deploy/README.md`.

## Testing policy

- The standard test suite is **fully offline**: fixtures and mocks, no tokens.
- PDB integration tests are marked `pdb_sandbox`, run only against the PDB
  test instance, and are excluded from the default run.
- Production PDB access is refused by the application unless explicitly and
  deliberately enabled — see `backend/app/config.py`.

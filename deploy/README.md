# Deployment

One command per institute:

```bash
cd deploy
cp .env.example .env      # set POSTGRES_PASSWORD and one stable encryption key
docker compose up --build
```

- Frontend: http://localhost:8080
- Backend API + OpenAPI docs: http://localhost:8000/docs
- Health: http://localhost:8000/health — reports the active `pdb_instance`

The first sign-in needs a local account; there is no default one. Create an
admin inside the running backend container:

```bash
docker compose exec backend python -m app.create_admin --help
```

Then sign in and connect your personal PDB access codes under **Account**.
If that connection test reports “The PDB could not be reached” while
`/health` shows `"pdb_instance": "test"`, the deployment is on the retired
test configuration and no PDB is reachable by design — enable the two
production opt-ins below and restart.

## Safety

The default target is the historical, inert **PDB test configuration**; that
test service no longer exists. Production access requires deliberately setting
both `ITKFLOW_PDB_INSTANCE=production` and
`ITKFLOW_ALLOW_PRODUCTION=true`. Writes remain confined to itkFlow-registered
DUMMY module/hybrid components.

`ITKFLOW_PDB_CREDENTIAL_ENCRYPTION_KEY` must be the same stable, URL-safe
base64 32-byte key in the backend and worker. Back it up separately from the
database: losing it makes saved personal connections unreadable. Rotating it
requires a dedicated re-encryption procedure; replacing it in-place does not.

PDB access codes are not deployment variables. Each signed-in person opens
**Account**, connects their own Plus4U/PDB access-code pair, and can remove or
replace it without affecting anyone else. The API never returns saved codes.

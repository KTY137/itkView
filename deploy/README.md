# Deployment

One command per institute:

```bash
cd deploy
cp .env.example .env      # set POSTGRES_PASSWORD and one stable encryption key
docker compose up --build
```

Also set `TZ` in `.env` to the institute deployment's local timezone (for
example `Europe/Berlin`) before enabling a scheduled-sync window. Compose
defaults to `Etc/UTC`; the backend image includes the timezone database.

- Frontend: http://localhost:8080
- Backend API + OpenAPI docs: http://localhost:8000/docs
- Health: http://localhost:8000/health — reports the active `pdb_instance`

On the very first visit the app shows a **first-run setup screen**: create the
initial admin account right in the browser — no shell access needed. The form
disappears permanently once any account exists; from then on the admin manages
accounts under **Users**. (The CLI fallback
`docker compose exec backend python -m app.create_admin` still works.)

**Complete the setup immediately after the first start.** Until the first
admin exists, anyone who can reach the port can claim the instance — do not
expose the service beyond a trusted network before that account is created.

Then sign in and connect your personal PDB access codes under **Account**.
Compose enables production PDB **reads** out of the box — nothing contacts the
PDB until a person connects their own codes. If the connection test says the
deployment has **no PDB configured**, `ITKFLOW_PDB_INSTANCE=offline` is set in
`.env`; remove it and restart to restore the default.

## Safety

There is no PDB test service; the code-level default (`pdb_instance=offline`)
reaches no PDB, and this Compose file deliberately overrides it to
production **reads** (docs/09). All PDB traffic runs under each person's own
access codes, and writes remain confined to itkFlow-registered DUMMY
module/hybrid components (`pdb_write_scope=dummy_only`). Set
`ITKFLOW_PDB_INSTANCE=offline` in `.env` for a deployment that must reach no
PDB at all.

`ITKFLOW_PDB_CREDENTIAL_ENCRYPTION_KEY` must be the same stable, URL-safe
base64 32-byte key in the backend and worker. Back it up separately from the
database: losing it makes saved personal connections unreadable. Rotating it
requires a dedicated re-encryption procedure; replacing it in-place does not.

PDB access codes are not deployment variables. Each signed-in person opens
**Account**, connects their own Plus4U/PDB access-code pair, and can remove or
replace it without affecting anyone else. The API never returns saved codes.

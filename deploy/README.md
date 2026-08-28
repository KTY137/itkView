# Deploy itkView with Docker Compose

itkView is the read-only ATLAS ITk production viewer. It mirrors PDB data and
attachments into local storage so components, images, original plots,
generated fallbacks, collective IV/CV curves and statistics remain fast to
browse. It does not expose ingestion, Staged/Outbox, assembly, registration,
test entry, stage moves or any PDB-write sink.

"Read only" describes the PDB boundary. The local PostgreSQL mirror,
attachment store, accounts, settings and caches must still be writable.

## Start

Create a dedicated configuration for itkView. Do not copy an itkFlow `.env`,
database volume, attachment volume or credential key.

```bash
cd deploy
cp .env.example .env
```

Fill in these two required values in `.env`:

- `POSTGRES_PASSWORD`: a new password for itkView's local PostgreSQL service.
- `ITKFLOW_PDB_CREDENTIAL_ENCRYPTION_KEY`: a new, stable URL-safe base64
  32-byte key. The example file contains a generation command.

Then start the stack:

```bash
docker compose up --build
```

The Compose project is explicitly named `itkview` and owns its own `itkview`
PostgreSQL database plus separate database and attachment volumes. This keeps
it isolated even when itkFlow runs on the same host.

- Frontend: <http://localhost:8080>
- Backend API and OpenAPI docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

The worker container prints that the read-only product disables it and exits
once with status 0. That stopped container is intentional, not a crash loop.

## First-run setup

On the first visit, create the initial local administrator in the browser.
The setup route closes permanently as soon as any account exists. Complete
this step before exposing the ports outside a trusted network: until then,
anyone who can reach the service can claim the first account.

After signing in, connect personal Plus4U/PDB access codes under **Account**.
Credentials are encrypted per account and are never returned to the browser.
There is no deployment-wide PDB identity.

Compose enables production PDB reads by default, but no PDB request is made
until a signed-in person connects credentials and starts or schedules a sync.
To make the deployment network-inert, add this to `.env` and restart:

```dotenv
ITKFLOW_PDB_INSTANCE=offline
```

There is no PDB test service. itkView never falls back from offline to
production, and its product policy forces all PDB-write settings and workers
off even for administrators and direct API calls.

## What remains available

- component, test-definition, evidence, attachment, tool and shipment mirror
  sync;
- component search, scanner input, board, family and detail views;
- locally mirrored images, original plots and generated plot fallbacks;
- measurement exploration, collective IV/CV curves and production statistics;
- production-hold indicators and required-test summaries;
- local accounts, institute settings, personal PDB credentials and protected
  public-share passwords;
- local health information and bounded diagnostics.

Authoring and upload workflows are intentionally absent. In particular there
is no Triage/Ingest, Staged/Outbox, assembly, registration, test entry, stage
move, `Push to PDB`, `Discard`, reminder delivery or notification mutation.

## Persistent state and backups

Back up all three pieces together:

1. the PostgreSQL volume;
2. the attachment volume;
3. `ITKFLOW_PDB_CREDENTIAL_ENCRYPTION_KEY` from the private `.env` file.

Losing the key makes saved personal connections unreadable. Replacing it in
place is not key rotation; users would have to reconnect their credentials.
Never commit `.env` or a backup containing the key.

An existing itkFlow database is not an upgrade source for itkView. A new
itkView installation intentionally starts with an empty, isolated mirror and
needs its own first sync. This prevents old Outbox records, sessions and
attachments from crossing the product boundary.

## Updating

Pull or check out the intended itkView release, then rebuild the services:

```bash
docker compose up --build -d
```

Review the release notes before updating and keep a database, attachment and
key backup. Do not remove the named volumes during a normal update.

## Troubleshooting

**The PDB connection says no PDB is configured.**
`ITKFLOW_PDB_INSTANCE=offline` is active. Remove it only if this installation
is allowed to perform production reads, then restart the stack.

**The worker is stopped.**
Expected. itkView has no Outbox drain or reminder scheduler.

**Images or plots are missing after installation.**
The mirror is intentionally empty on first start. Connect personal PDB
credentials and run the component/evidence sync. Protected public shares also
need their per-user password under **Account**; private CERN account links are
reported as skipped because they require CERN OAuth rather than a stored CERN
password.

**A saved connection suddenly cannot be opened.**
Restore the original credential-encryption key or reconnect the account's
codes. Check that an itkFlow `.env` was not accidentally substituted.

**The frontend opens but data does not persist.**
Check that both named volumes are present and writable and that the backend
uses `/data/attachments`. The health endpoint must report
`"product_variant": "view"`, `"write_features_enabled": false` and a disabled
PDB write scope.

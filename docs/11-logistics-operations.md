# Logistics and Operations

This document is the user and developer reference for the Phase 4 backend
contract covering glue batches, tool resources, assembly recording, shipment
reception, reminders, and notification channels. The PDB remains the source of
truth for shipments. Glue-batch usage,
reception checks, reminders, and their audit events are locally owned by
itkFlow.

The Glue batches, Shipments, Reminders, and Operations health screens expose
this contract in the product UI. Admins configure their institute's operational defaults through
the structured Settings screen. Delivery status and final cross-suite
acceptance remain tracked in `docs/04-roadmap.md`; API availability alone must
not be treated as a test result.

## Safety and ownership boundaries

- Glue batches are local records. `pdb_sn` is an optional, scannable reference
  to an existing PDB component; itkFlow does not register GLUE components.
- Shipment sync is read-only. It uses the signed-in operator's personal PDB
  connection and the production-read safeguards described in
  `docs/09-pdb-production-strategy.md`.
- Shipment reception fields are locally leading and are never overwritten by a
  later PDB sync.
- Reminder delivery runs in the worker process. The web process only manages
  reminders and sends an explicit admin test notification.
- Notification channel definitions belong to the institute profile. Webhook
  URLs and SMTP passwords are credentials: they must not be committed, logged,
  added to fixtures, or returned to the browser.
- The existing `pdb_write_scope=dummy_only` boundary is unchanged. None of the
  operational APIs bypasses the outbox. Assembly submission is confined to
  registered DUMMY modules/hybrids and is described below.

## Institute profile configuration

An admin configures the following keys in `InstituteProfile.settings` through
**Admin → Settings**. The screen uses structured fields rather than a raw JSON
editor and persists them through `PATCH /api/institutes/{code}`:

```json
{
  "settings": {
    "glue_pot_life_minutes": {
      "POLARIS_EPOXY": 45,
      "TRUE_BLUE": 30
    },
    "shipment_reception_checklist": [
      "Packaging intact",
      "Contents match the shipment list",
      "No visible damage"
    ],
    "shipment_reception_tests": {
      "MODULE": ["RECEPTION_IV", "MODULE_METROLOGY"],
      "HYBRID": ["HYBRID_RECEPTION"]
    },
    "notification_channels": {
      "lab": {
        "kind": "mattermost",
        "url": "https://hooks.example.org/example-only",
        "channel": "lab-operations"
      },
      "alerts": {
        "kind": "telegram",
        "url": "https://api.telegram.org/botEXAMPLE-ONLY/sendMessage",
        "chat_id": "-1000000000000"
      },
      "automation": {
        "kind": "webhook",
        "url": "https://automation.example.org/example-only"
      },
      "email-ops": {
        "kind": "email",
        "smtp_host": "smtp.example.org",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "itkflow",
        "smtp_password": "EXAMPLE-ONLY",
        "from_address": "itkflow@example.org",
        "to_address": "operations@example.org"
      }
    },
    "reminder_escalation": {
      "after_minutes": 30,
      "channel": "email-ops"
    },
    "evidence_component_types": ["MODULE"]
  }
}
```

The settings update is a shallow merge at the top level. Supplying a new
`notification_channels` object therefore replaces that complete nested object;
include every channel that must remain configured.

Every institute API response masks configured channel URLs and SMTP passwords
as `"***"`, including responses to admins. Stored secrets are never read back.
When an existing channel is saved unchanged, the Settings screen sends that
marker and the API preserves the secret only when both channel name and adapter
kind still match. Renaming a channel or changing its adapter requires a fresh
secret. Removing the channel row deletes that channel because
`notification_channels` is a complete replacement object.

The API normalizes the following operational settings when they are present:

- `notification_channels`: unique non-empty names and one of `mattermost`,
  `telegram`, `webhook`, or `email`. HTTP adapters require a new HTTPS URL when
  created, renamed, or changed; Mattermost overrides and Telegram chat IDs are
  validated. Email requires an SMTP host, port, `ssl` or `starttls`, sender and
  recipient addresses, plus an optional username/password pair.
- `reminder_escalation`: either `null` or a delay from 1 through 10,080 minutes
  and the name of the second notification channel.
- `shipment_reception_checklist`: a non-empty-label list with duplicates
  removed while preserving order.
- `shipment_reception_tests`: component-type keys mapped to one or more required
  PDB test-type codes. Keys and values are normalized to uppercase, duplicates
  are removed, and empty mappings mean that no reception test gate applies.
- `glue_pot_life_minutes`: normalized glue-type keys mapped to whole minutes
  from 1 through 1,440.
- `evidence_component_types`: a de-duplicated component-type list used by the
  automatic Evidence mirror.

Malformed values are rejected as `422` rather than being silently stored.
Updates emit `institute.updated` with changed top-level profile fields,
settings keys, and channel names only. Audit records never contain channel
URLs or other setting values.

Only `https://` notification URLs are accepted. The notifier remains defensive
and ignores malformed legacy entries if an older database contains them.
Supported kinds are:

- `mattermost`: sends `{"text": "..."}` and optionally a configured
  `channel` override.
- `telegram`: sends `{"chat_id": "...", "text": "..."}` to a bot's
  `sendMessage`. It needs its own kind because Telegram ignores the generic
  body below. The `chat_id` is required and must be a numeric id (`-100…` for
  a group) or an `@name`; a channel without a usable one is dropped rather
  than failing at delivery time. The bot token sits in the URL, so it is
  masked by the same redaction as every other channel URL.
- `webhook`: sends `{"title": "...", "text": "..."}`.
- `email`: sends a plain-text message through SMTP using implicit TLS or
  STARTTLS. Authenticated SMTP is optional, but username and password must be
  configured together. SMTP failures are sanitized before storage or display.

The outbound request timeout is controlled by
`ITKFLOW_NOTIFY_TIMEOUT_SECONDS` and defaults to 10 seconds.

## Route-level access contract

The table describes the dependencies enforced directly by the current API
handlers. Authenticated mutations also use the normal session and CSRF contract
from `docs/06-users-roles-audit.md`.

| Area | Read routes | Mutation routes |
|---|---|---|
| Glue batches | No role dependency | `operator` or `admin` |
| Shipments | No role dependency | Sync and reception require `operator` or `admin`; institute-bound accounts remain confined to their own profile |
| Reminders and acknowledgement tasks | Signed-in user, institute-scoped | Create, update, delete, and acknowledge require `operator` or `admin` |
| Notification channels | Signed-in user | Test notification requires `admin` |
| Institute settings | Profile reads follow the institute API | Update requires `admin`; institute admins may edit only their own profile |
| Operations health | `admin`; institute admins see only their own profile, global admins may select one or view the installation aggregate | Read-only |

Full per-institute row and query scoping is still a Phase 6 item. The current
list/read routes operate on the local instance-wide dataset. Do not treat this
contract as completed tenant isolation.

## Glue-batch registry

### Lifecycle and pot life

A batch has one of four statuses:

```text
new -> in_use -> expired | empty
```

`POST /api/glue-batches/{id}/mix` records `mixed_at`, sets `opening_date` when
it is still empty, and moves a `new` batch to `in_use`. The explicit
`pot_life_minutes` request value wins; otherwise itkFlow reads
`glue_pot_life_minutes[glue_type]` from the owning institute profile. When
neither exists, the batch is mixed but has no countdown.

Responses calculate `pot_life_remaining_seconds` and `pot_life_expired` from
the stored mix time. Reaching zero does not silently change the persisted
status. A batch marked `expired` or `empty` cannot be mixed or used.

Recording the first usage of a `new` batch moves it to `in_use`. A usage entry
stores the scanned component serial, optional amount in milligrams, note,
operator identity, and timestamp. The serial is intentionally not a foreign
key because bench work may happen before the component has entered the local
mirror.

### Glue API

| Method and path | Purpose |
|---|---|
| `GET /api/glue-batches` | List batches; filters: `status`, `glue_type`, `q` |
| `GET /api/glue-batches/scan?code=...` | Resolve a PDB serial or batch number case-insensitively |
| `POST /api/glue-batches` | Create a local batch |
| `PATCH /api/glue-batches/{id}` | Update lifecycle and batch metadata |
| `POST /api/glue-batches/{id}/mix` | Start or restart the pot-life timer |
| `GET /api/glue-batches/{id}/usage` | List newest usage entries first |
| `POST /api/glue-batches/{id}/usage` | Record consumption for a component |

Example usage payload:

```json
{
  "component_sn": "20USEM00000435",
  "amount_mg": 135.2,
  "note": "Hybrid attach"
}
```

The API records `glue_batch.created`, `glue_batch.updated`,
`glue_batch.mixed`, and `glue_batch.usage_recorded` audit events.

## Tool resources and assembly recording

The Tools screen is the structured local registry for jigs, pickup tools,
panels, and future tool kinds. Operators can create and edit all fields and set
`active`, `flagged`, or `blacklisted`; admins can explicitly delete an entry.
Codes and non-empty RFIDs are case-insensitively unique within an institute.
Create, update, and delete events are audited without storing secrets.

The Assembly wizard is scanner-first and PDB-inert while the operator works:

1. Resolve exact parent and child serial/local-name scans from the local mirror.
2. Quick-select an active tool filtered by the parent `type_code`, or scan its
   code/RFID. Optionally select/scan an `in_use` glue batch and enter the slot.
3. Run `POST /api/assembly/preview`. This canonical server dry-run checks both
   component types/state/location/institute/relationship, tool ownership,
   status and compatibility, plus glue ownership, lifecycle, expiry and pot
   life.
4. `POST /api/assembly/actions` repeats the dry-run and creates an audited
   `assemble_component` draft. It never opens a PDB client.

Profile key `assembly_property_keys` maps the semantic values `tool`,
`glue_batch`, and `slot` to confirmed PDB property codes. It may be a direct
mapping or nested by parent type code/component type with a `default` fallback.
Invalid keys are ignored; application code never invents institute-specific
property names.

The worker immediately re-evaluates the current component, tool, glue, expiry,
pot-life and property state and compares it with the immutable preview snapshot.
The real submitter then applies ADR 003 before constructing an authenticated
client: **both** participants must be itkFlow-registered DUMMY components and
both must be in the invariant `MODULE|HYBRID` allowlist as well as the configured
registrable list. Sensors and ASICs are never eligible. The payload uses
`assembleComponent` with one explicit child and an empty `disassemble` list;
there is no implicit relationship replacement. No live PDB call is made by the
offline suites.

| Method and path | Purpose |
|---|---|
| `GET /api/tools` | Filter tools by institute, kind, compatible type, and status |
| `GET /api/tools/scan?code=...` | Resolve RFID, code, or label |
| `POST /api/tools` | Create a normalized, institute-scoped tool |
| `PATCH /api/tools/{id}` | Edit structured fields or lifecycle status |
| `DELETE /api/tools/{id}` | Admin-only audited removal |
| `GET /api/assembly/scan-component?code=...` | Resolve an exact local component |
| `POST /api/assembly/preview` | Run the canonical local dry-run |
| `POST /api/assembly/actions` | Revalidate and stage an outbox draft |

## Shipment mirror and reception

### PDB mirror semantics

`POST /api/sync/shipments/{institute_code}` reads shipments twice from the PDB,
once with the institute as recipient and once as sender, deduplicates them by
PDB id, and mirrors their item lists. A previously mirrored shipment whose PDB
status is `delivered` keeps its existing item list without another item fetch.

The sync is synchronous because shipment lists are expected to be small. A
missing personal connection or an unavailable PDB returns `503`; itkFlow never
reports that situation as a successful sync of zero shipments.

Mirrored PDB fields are `pdb_id`, name, sender, recipient, status, send time,
and items. PDB status strings are preserved. The API derives direction relative
to the owning institute as `incoming`, `outgoing`, `internal`, or `unknown`.

On first mirror, itkFlow instantiates the reception checklist from
`shipment_reception_checklist`. If the profile has no usable template, the
generic defaults are:

- Packaging intact
- Contents match the shipment list
- No visible damage

Later profile changes do not rewrite a checklist that people may already have
worked through.

### Reception semantics

Reception updates are partial: omitted checklist, item, note, and status fields
keep their current values. The first update moves `pending` to `in_progress`
unless the request explicitly sets a status. Valid statuses are `pending`,
`in_progress`, and `done`.

Example reception payload:

```json
{
  "status": "in_progress",
  "checklist": [
    {"label": "Packaging intact", "done": true}
  ],
  "items": [
    {"sn": "20USEM00000435", "received": true, "note": null}
  ],
  "note": "One remaining item is still being checked."
}
```

Every update records the operator and timestamp and emits
`shipment.reception_updated`. Subsequent PDB syncs update only PDB-owned fields
and preserve all `reception_*` data.

### Reception-test projection and completion gate

Reception-test requirements are not hard-coded. For every shipment item the
API resolves its mirrored component type, then looks up the required test-type
codes in the owning institute's `shipment_reception_tests` mapping. Shipment
list and detail responses expose the derived requirement list on every item and
an aggregate status both per item and per shipment:

- `missing`: no local evidence or staged upload exists for the requirement.
- `pending`: an `upload_test_run` action is still open. A pending action never
  counts as passed, even if its draft payload contains `"passed": true`.
- `passed`: the newest local `TestRunEvidence`, or a locally confirmed upload
  that has not reached the next mirror yet, passed.
- `failed`: the newest applicable evidence or confirmed upload failed.

The aggregate precedence is `failed`, `pending`, `missing`, then `passed`.
Items without a configured requirement report `reception_tests_configured` as
false and are shown as **Not required** rather than as evidence-backed passes.
The projection reads only the local database and never performs a PDB call.

The Shipments screen links a missing or failed requirement to **Add test
result** with both the component serial and exact test type pinned. The target
test-type selector stays locked, and the ingest API checks both pins against
the parsed file or manual result before it can be staged. This prevents a
different test result from accidentally satisfying the visible workflow.

Recording a test and pushing it are separate operations. The screen states
whether the mirrored component is a registered DUMMY: DUMMY components may be
submitted under the existing guarded outbox policy; production components and
items absent from the mirror can only be staged while production writes remain
disabled. Reception status reflects this honestly and does not imply that an
open action has reached the PDB.

`status: "done"` is rejected with `409` until all configured requirements have
status `passed`. An admin can use the explicit escape hatch only by sending
`test_override: true` together with a non-blank `test_override_reason`; the
reason is limited to 500 characters and is recorded in the dedicated
`shipment.reception_test_override` audit event. Operators cannot override the
gate, an override cannot be used on a passing shipment, and a reason without
the flag is rejected. The normal `shipment.reception_updated` audit event is
still emitted after a successful overridden update.

### Shipment API

| Method and path | Purpose |
|---|---|
| `GET /api/shipments` | List shipments with projected reception-test status; filters: `direction`, `status`, `reception`, `q` |
| `GET /api/shipments/{id}` | Read one mirrored shipment, its reception state, and item-level test requirements |
| `POST /api/sync/shipments/{institute_code}` | Mirror incoming and outgoing PDB shipments |
| `POST /api/shipments/{id}/reception` | Partially update the local reception check; enforces the completion gate |

Shipment creation and PDB shipment mutation are not implemented.

## Reminders and notifications

### Scheduling contract

A reminder contains a title, optional note and channel, one schedule kind,
`next_due_at`, and an active flag. Supported schedule kinds are `once`,
`daily`, `weekly`, and `monthly`.

The configured scheduler checks due reminders on every poll cycle:

- A `once` reminder becomes inactive after it fires.
- A recurring reminder advances to the first occurrence strictly after the
  current time. Downtime therefore produces one notification, not a burst for
  every missed occurrence.
- Monthly schedules clamp invalid month-end dates. For example, a schedule
  starting on January 31 advances through February 28/29.
- A reminder without a channel fires into the audit trail only.
- A named channel must exist in the creator's institute profile.
- Delivery failure is stored in `last_error` and emits `reminder.failed`.
  The schedule still advances so a broken endpoint is not hammered every poll
  cycle.

### Delivery is at most once

An occurrence is *claimed* before anything is sent: the schedule advances in
its own committed transaction, guarded by a `WHERE` clause that only matches
while the row still carries that occurrence. Whoever commits first wins, and a
second scheduler — or a restarted one — finds nothing to claim instead of
sending a duplicate. Duplicate pings into a team channel are worse than a
missed one, so this ordering is deliberate.

### Durable acknowledgement and escalation

Every claimed occurrence creates a durable `ReminderOccurrence`, including the
due/fired timestamps, delivery result, optional escalation deadline and final
acknowledgement identity. The Reminders screen lists open tasks and lets an
operator acknowledge them through an idempotent action. Acknowledgement before
the deadline suppresses escalation.

When `reminder_escalation` is configured, an open occurrence is claimed for its
second delivery once the configured delay expires. The escalation claim is
persisted before the adapter is called, so scheduler restarts or overlapping
ticks do not send it twice. Delivery and escalation errors are stored only in
sanitized form. The escalation configuration is institute-wide; it never
changes already claimed occurrences retroactively.

### Which process fires them

`ITKFLOW_REMINDER_SCHEDULER` selects the ticking process, because the
deployment shapes differ:

| Value | Ticks | Used by |
|---|---|---|
| `worker` (default) | the standalone outbox worker | Compose, which runs that process |
| `app` | the API process, on a background task | the desktop bundle and `start-itkflow.ps1`, which run no worker |
| `off` | nobody | tests, or a deployment scheduling reminders elsewhere |

Configure exactly one ticker. Two do not produce duplicates thanks to the claim
above, but they do produce pointless polling.

The desktop bundle defaults itself to `app`: it ships a single process, so with
the `worker` default a packaged install would have no ticker at all and every
scheduled reminder would silently never fire. The dev launcher sets `app` for
the same reason. Reminders touch only the local database and the configured
webhook, never the PDB, so this adds no write path.

`ITKFLOW_REMINDER_POLL_SECONDS` (default 60) bounds how late a reminder may
fire in the `app` case; the worker uses its own `ITKFLOW_WORKER_POLL_SECONDS`.

For a manual pass: `python -m app.run_worker --once` performs one outbox pass
and one reminder tick; `python -m app.run_worker` keeps polling.

### Reminder and notification API

| Method and path | Purpose |
|---|---|
| `GET /api/reminders?active=true` (or `false`) | List reminders ordered by active state and due time |
| `POST /api/reminders` | Create a reminder |
| `PATCH /api/reminders/{id}` | Update schedule, content, channel, or active state |
| `DELETE /api/reminders/{id}` | Delete a reminder |
| `GET /api/reminder-occurrences?open_only=true` | List durable tasks, scoped to the signed-in institute |
| `POST /api/reminder-occurrences/{id}/ack` | Idempotently acknowledge a task as the signed-in operator |
| `GET /api/notifications/channels` | List configured channel names and kinds, never URLs |
| `POST /api/notifications/test` | Admin-only delivery test |

`POST /api/notifications/test` accepts `channel` and an optional
`institute_code`. An institute-bound admin always remains confined to their
own institute and may omit the code. A global admin must select an institute
explicitly; the Settings screen supplies the selected profile code.

Example reminder payload:

```json
{
  "title": "Clean the assembly bench",
  "note": "Complete the weekly checklist.",
  "channel": "lab",
  "schedule_kind": "weekly",
  "next_due_at": "2026-09-01T08:00:00Z"
}
```

An empty channel string in a reminder update clears the channel. Notification
delivery errors return or store sanitized messages without the endpoint URL.
The adapter also avoids exception chaining because upstream HTTP exceptions
may contain the secret URL.

Audit events are `reminder.created`, `reminder.updated`, `reminder.deleted`,
`reminder.fired`, `reminder.failed`, `reminder.escalated`,
`reminder.escalation_failed`, `reminder.acknowledged`, and
`notification.test_sent`.

## Operations health

**Admin → Operations health** is a local operations cockpit. Its endpoint,
`GET /api/ops/health`, aggregates only records already stored in itkFlow and
never opens a PDB client. An institute-bound admin is always scoped to their
own institute. A global admin may pass `institute_code`, or omit it for an
installation-wide aggregate. Unresolved ingest files appear only in that
global view because they cannot yet be assigned safely to a tenant.

The snapshot contains:

- durable `outbox-worker` and `reminder-scheduler` heartbeats with textual
  `healthy`, `stale`, `missing`, `error`, or `disabled` state;
- active and latest persisted component/evidence sync jobs, including stale
  active-job detection;
- open Outbox backlog, failed actions, retry-limit hits, and the age of the
  oldest open action;
- active schedules, open/failed/escalated reminder occurrences, and overdue
  schedules;
- ingest totals, triage/failed files, parser issues, and globally unassigned
  files.

The standalone worker writes its heartbeat after every successful Outbox poll.
Every reminder tick writes the scheduler heartbeat even when nothing was due;
a failed in-app scheduler cycle records only its exception type, never the
exception message. This keeps URLs and credentials out of telemetry.

`ITKFLOW_OPS_HEARTBEAT_STALE_SECONDS` controls the inclusive freshness window
and defaults to 180 seconds: a heartbeat exactly at the boundary is healthy,
and one second older is stale. Deployments should keep it comfortably above
both worker polling intervals. A disabled reminder scheduler is reported as
`disabled` rather than as a missing process. The screen refreshes every 15
seconds and links directly to Staged, Ingest log, and Reminders for action.

## Implementation map

| Concern | Code |
|---|---|
| Glue models and pot-life calculation | `app.models.GlueBatch`, `app.models.GlueUsage`, `app.domain.glue` |
| Assembly dry-run, snapshots, and write boundary | `app.assembly`, `app.pdb_submit`, `app.outbox_worker` |
| Tool CRUD, scanner, and assembly API | `app.api`, `app.schemas` |
| Shipment PDB reader and local upsert | `app.pdb_shipments`, `app.shipment_sync`, `app.models.Shipment` |
| Profile-driven reception-test projection and completion gate | `app.shipment_reception`, `app.api` |
| Reminder scheduling, durable tasks, acknowledgement, and escalation | `app.reminders`, `app.models.Reminder`, `app.models.ReminderOccurrence`, `app.run_worker` |
| Notification validation, redaction, HTTP, Telegram, and SMTP adapters | `app.notifications` |
| Structured operational-setting validation and masked-secret preservation | `app.institute_settings` |
| Local health aggregation and service heartbeats | `app.ops_health`, `app.models.ServiceHeartbeat`, `app.run_worker`, `app.reminders` |
| Request and response contracts | `app.schemas`, `app.api` |
| Product screens | `frontend/src/screens/AssemblyWizardScreen.tsx`, `ToolsScreen.tsx`, `GlueBatchesScreen.tsx`, `ShipmentsScreen.tsx`, `RemindersScreen.tsx`, `AdminSettingsScreen.tsx`, `OpsHealthScreen.tsx` |

The focused offline verification command is:

```powershell
cd backend
uv run pytest -q tests/test_assembly.py tests/test_tools.py `
  tests/test_glue_batches.py tests/test_shipments.py `
  tests/test_shipment_reception_tests.py tests/test_ingest_component_pin.py `
  tests/test_reminder_service.py tests/test_reminders_api.py `
  tests/test_notifications.py tests/test_institute_settings_normalization.py `
  tests/test_ops_health.py
```

The reception UI and structured settings mapping are covered offline with:

```powershell
cd frontend
npm test -- --run src/screens/AssemblyWizardScreen.test.tsx `
  src/screens/ToolsScreen.test.tsx src/AddTestResult.test.tsx `
  src/screens/ShipmentsScreen.test.tsx `
  src/screens/RemindersScreen.test.tsx `
  src/screens/AdminSettingsScreen.test.tsx `
  src/screens/OpsHealthScreen.test.tsx
npm run build
```

The suite covers lifecycle rules, profile-driven configuration, PDB fetch and
upsert behavior with fakes, local reception preservation, profile-driven test
projection, pending-versus-passed behavior, exact ingest pins, completion and
admin-override gates, scheduling, role-gating, URL redaction, and notifier
failure handling. It performs no real PDB write and sends no real webhook. The
institute-settings cases additionally cover validation, masked-secret
preservation, institute scope, and secret-free audit details.

## Remaining Phase 4 scope

- Add shipment creation only if a future PDB write policy explicitly permits
  it; the current implementation remains read-only.
- Keep operational-health thresholds aligned with the deployed worker and
  scheduler polling intervals.
- Complete per-institute row/query authorization before treating one instance
  as a hardened multi-tenant deployment.

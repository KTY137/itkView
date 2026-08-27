# Logistics and Operations

> - **Owns:** the Phase 4 contract — glue-batch registry, tool resources and
>   assembly recording, glue-weight derivation, shipment mirror and reception,
>   reminders and notification channels, and the operations health view,
>   together with the institute-profile keys that configure them.
> - **Read this if:** you work on any of those modules, wire an operational
>   screen, or need to know which process fires reminders and drains the outbox.
> - **Links to:** [`09-pdb-production-strategy.md`](09-pdb-production-strategy.md)
>   (PDB safety for the shipment mirror),
>   [`07-jig-tool-quickselect.md`](07-jig-tool-quickselect.md) (tool registry and
>   slots), [`05-ui-design-reference.md`](05-ui-design-reference.md) (how these
>   screens look), [`06-users-roles-audit.md`](06-users-roles-audit.md) (roles
>   and audit), [`adr/002-async-outbox-worker.md`](adr/002-async-outbox-worker.md)
>   (the worker process), [`README.md`](README.md) (reading paths).
>
> This file is written in English because it doubles as a user- and
> developer-facing contract; the other planning documents in `docs/` are German.

This document is the user and developer reference for the Phase 4 backend
contract covering glue batches, tool resources, assembly recording, shipment
reception, reminders, and notification channels. The PDB remains the source of
truth for shipments. Glue-batch usage,
reception checks, reminders, and their audit events are locally owned by
itkFlow.

The Glue batches, Shipments, Reminders, and Operations health screens expose
this contract in the product UI. Admins configure their institute's operational defaults through
the structured Settings screen. Delivery status and final cross-suite
acceptance remain tracked in [`04-roadmap.md`](04-roadmap.md); API availability
alone must not be treated as a test result.

## Safety and ownership boundaries

- Glue batches are local records. `pdb_sn` is an optional, scannable reference
  to an existing PDB component; itkFlow does not register GLUE components.
- Shipment sync is read-only. It uses the signed-in operator's personal PDB
  connection and the production-read safeguards described in
  [`09-pdb-production-strategy.md`](09-pdb-production-strategy.md).
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
    "evidence_component_types": ["MODULE"],
    "glue_targets": [
      {
        "process": "TRUEBLUE",
        "label": "True Blue / False Blue",
        "valid_from": null,
        "module_types": {
          "R5M1_HALFMODULE": {"hybrids": {"target_mg": 151, "tolerance_mg": 22}},
          "R5M0_HALFMODULE": {
            "hybrids": {"target_mg": 135, "tolerance_mg": 20},
            "powerboard": {"target_mg": 103, "tolerance_mg": 16}
          },
          "R2": {
            "hybrids": {"target_mg": 164, "tolerance_mg": 25},
            "powerboard": {"target_mg": 70, "tolerance_mg": 11}
          }
        }
      }
    ],
    "glue_weight_inputs": {
      "hybrids": {
        "label": "Hybrids",
        "test_type": "GLUE_WEIGHT",
        "measured": "GW_MODULE_H1",
        "subtract": ["GW_SENSOR", "GW_HYBRID1"],
        "result_code": "GW_GLUE_H1"
      },
      "powerboard": {
        "label": "Powerboard",
        "test_type": "GLUE_WEIGHT",
        "measured": "GW_MODULE_H1PB",
        "subtract": ["GW_MODULE_H1", "GW_PB"],
        "result_code": "GW_GLUE_PB"
      }
    },
    "glue_default_process": "TRUEBLUE",
    "glue_process_property": null
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
- `glue_targets`: a list of rule sets, each naming a `process`, an optional
  `label`, a `valid_from` (ISO 8601 or `null`) and `module_types`. Process names
  and module-type codes are uppercased; weights must be finite, non-negative
  milligrams. Two rule sets may name the same process only if their `valid_from`
  differs. `null` disables target-based derivation; an empty list is rejected.
- `glue_weight_inputs`: derivation steps keyed by step name, each with a
  `measured` result code, an optional `subtract` list, an optional `label`,
  `test_type` and `result_code`. A step may not subtract or store its result in
  the code it measures. An optional `by_type_code` object replaces
  `measured`/`subtract`/`result_code` for an exact normalized component type;
  unmatched types keep the base formula and populated result fields never pick
  an override. `null` disables input-based derivation.
- `glue_default_process`: the explicit process applied when a run does not name
  one. It must match a configured target process. A single configured process
  is never inferred; `null` leaves the process unknown. The development-only
  alias `glue_process_default` is accepted on input for migration and persisted
  under the canonical key.
- `glue_process_property`: the PDB property or result code under which a run
  names its own glue process. `null` by default.

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
from [`06-users-roles-audit.md`](06-users-roles-audit.md).

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

## Glue-weight derivation

The PDB does not judge glue weights. All 14 module test schemas carry
`automaticGrading=false` with every threshold `null`, and the single `passed`
bit reproduces the production sheet's verdict only 80 % of the time — for two
separate verdicts at once (hybrids and powerboard). Target, tolerance and
verdict therefore come from the institute profile, and itkFlow computes them
**server-side**: `app/domain/glue.py` holds the arithmetic, `app/glue_service.py`
supplies its inputs from the database. The formula exists once. No client ever
recomputes it.

**A result that cannot exist is not a verdict (2026-08-27).** When every
reading is present and finite but the weight they produce is **negative**, the
step reports `verdict: unknown` with reason `implausible_result` instead of a
judgement. Glue never weighs less than nothing, so a negative value means the
readings contradict each other — in practice two fields entered into each
other's place. Calling that `too_little` would blame the operator for
under-applying glue when the real fault is the data entry. This is physics, not
a tunable threshold: only the lower bound is enforced in code, because any
upper bound would be a judgement call and belongs in the profile.

Measured on the TUDO mirror when the profile was first seeded: 48 of 50 live
derived weights are plausible; two are not (−8696 mg on `20USE5L0000031`,
−7771 mg on `20USE5L0000767`), and both had previously read `too_little` with
full confidence. The spreadsheet this replaces makes the same mistake — its own
`−9010` and `−9886` sit in the sheet looking like measurements.

**Units.** The PDB stores every `GW_` result in **grams**; targets, tolerances
and derived weights are stated in **milligrams**. The conversion happens only at
the two edges of `glue_service`: derived values leave the API in milligrams, and
the value staged for upload is converted back to grams.

**Selecting a rule set.** All entries whose `process` matches, then the one with
the greatest `valid_from` not later than the run's `measured_at`. `valid_from:
null` always qualifies and loses to any dated rule. A run without a trustworthy
measurement date, and a row with no run at all, may use only that explicit
`null` fallback; they never select a dated or future rule. The validity period
is not decoration: the sheet this replaces runs two generations of the same
rule side by side, so a profile that knows one set of constants misjudges older
runs.

**Which steps appear.** Every step configured in `glue_weight_inputs` for the
row's test type, except where the selected rule *knows* the module type and that
type carries no entry for the step — that is the profile stating that this type
has no such gluing step (a half-module carries no powerboard). A module type the
rule has never seen keeps all its steps and reports `no_target`, so a profile gap
stays visible. Before evaluation, an exact `by_type_code` entry may replace the
step's scale-reading formula. This is how one- and two-hybrid H1/H1H2 chains are
represented without guessing from whichever payload fields happen to be filled.

**The derived payload** appears on `worksheet.groups[].rows[].derived` of
`GET /api/components/{sn}/preview` and on `derived` of
`GET /api/ingest/files/{id}/preview`, and is `null` where the profile derives
nothing for that test type:

```json
{
  "kind": "glue_weight",
  "process": "TRUEBLUE",
  "process_source": "profile_default",
  "steps": [
    {
      "key": "hybrids",
      "label": "Hybrids",
      "measured_mg": 132.7,
      "target_mg": 151,
      "tolerance_mg": 22,
      "verdict": "ok",
      "reason": null,
      "result_code": "GW_GLUE_H1",
      "inputs": [{"code": "GW_MODULE_H1", "name": "...", "value": 9.3819}]
    }
  ]
}
```

`verdict` is `ok`, `too_little`, `too_much` or `unknown`, and an `unknown`
verdict always carries a `reason`: `no_run` (nothing measured yet — the target is
still shown), `missing_inputs` (a scale reading is absent or not a number) or
`no_target` (the profile has no target for this module type, or the process could
not be established). This is a hard rule rather than defensive style: on the
owner's real sheet, 8 of 13 powerboard verdicts are arithmetic on blank cells,
because an empty input looked exactly like a result. `input.value` is the raw
reading in grams, `null` where it is missing — never a substituted zero.

`process_source` is `run` when the run named its own process through
`glue_process_property`, `profile_default` when the explicit
`glue_default_process` applied, and `unknown` when neither value names a
configured rule set. An unknown process yields no rule set and therefore
`no_target`; itkFlow never infers it from `GW_METHOD`, a sheet heading, a sample
prefix or the sole configured process.

**Derivation in the dry-run.** `GET /api/ingest/files/{id}/preview` derives from
the uploaded payload before anything is staged, so the operator sees the verdict
while the file can still be rejected. `POST /api/ingest/files/{id}/propose-outbox`
stores the computed values as `derived_results` (result code to grams) plus the
complete server-owned output set as `derived_result_codes` on the outbox action
payload. They ride on the write intent, not on the ingest file:
the received document keeps matching the `sha256` it was recorded under. A step
without a computed value contributes nothing — an upload never carries a
fabricated zero.

At worker revalidation, those staged values and controlled codes are recomputed from the immutable
ingest payload, the action's current institute profile and the mirrored PDB
type code. Missing, malformed, injected or stale values block submission and
must be restaged. The upload converter then copies the ingest `results`, removes
every verified controlled code, and merges the verified derived map over that
copy. Thus a server result wins any same-code raw value, while an output with no
computed value (for example because a scale reading is missing) cannot leak
through as a stale raw value. The received evidence and its SHA-256 remain
unchanged.

The production sheet also derives each hybrid's weight without tabs from its
with-tabs and tab readings. That upstream C17/C20 chain is not yet represented
by `glue_weight_inputs`; the current module-glue formula requires the
`GW_HYBRID1`/`GW_HYBRID2` readings to be present already. The relationship
between the two derived step verdicts and the PDB run's single `passed` bit is
also intentionally unresolved until an explicit override and audit contract
is specified.

For an unmirrored component, the preview may receive `?institute_code=…` and
returns the profile code it actually used. Proposal validation and derivation
use that same final profile; a payload institution that conflicts with the
selected institute fails closed instead of mixing two institutes' rules.

Withdrawn runs (`state='deleted'`) never produce a verdict, in line with the
rest of the evidence handling.

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

Registry data model, PDB `TOOLS` mirror, type compatibility and the combined
tool slots are owned by
[`07-jig-tool-quickselect.md`](07-jig-tool-quickselect.md); this section
describes only how they behave inside the operational contract.

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
The real submitter then applies
[ADR 003](adr/003-pdb-dummy-write-scope.md) before constructing an authenticated
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

### Which process submits the outbox

The same split applies to PDB submission, and for the same reason:
`ITKFLOW_OUTBOX_PROCESSOR` selects the draining process.

| Value | Drains the outbox | Used by |
|---|---|---|
| `worker` (default) | the standalone `app.run_worker` service | Compose, which runs that process |
| `app` | the API process, on a background task (`app.outbox_processor`) | the desktop bundle, which runs no worker |
| `off` | nobody | tests |

Without this, a packaged install could review and push a change up to
`submitted` — and then nothing would ever submit it. The staged action looked
pushed while nothing had reached the collaboration, which is the worst possible
failure mode for a production record.

The safety model is unchanged: the in-process drain never receives
deployment-wide service credentials, so every write runs as the PDB identity
bound when the action was approved (ADR 004), and `pdb_write_scope=dummy_only`
still confines writes to itkFlow-registered DUMMY components (ADR 003).
Reminders stay with `ReminderScheduler` in this shape, so they are not ticked
twice.

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

# Design: Glue-Batches, Shipments, Reminders (Phase 4)

> Spec fuer die drei Phase-4-Features aus `docs/04-roadmap.md` ("Logistik und
> Betrieb"). Autonome Session 2026-08-25; Entscheidungen folgen den bestehenden
> Planungsdokumenten (docs/02 §2/§3, docs/07) und den Code-Konventionen
> (Tool-Registry als Vorlage). Produkt-Facing bleibt Englisch.

## Ziel

1. **Glue-Batch-Registry** — lokale Registry fuer Klebstoff-Batches mit
   Lebenszyklus (new → in_use → expired/empty), Topfzeit-Timer nach dem
   Anruehren und Verbrauchserfassung je Komponente. Ersetzt das Glue-Sheet
   (`glueHandler`). PDB-Bezug nur als Referenz (`pdb_sn`, scannbar) — **keine
   PDB-Registrierung von GLUE-Komponenten** (dummy_only-Scope erlaubt nur
   Module/Hybride, harte Regel #2).
2. **Shipments** — read-only PDB-Mirror (`listShipmentsByInstitution` +
   `listShipmentItems`) plus lokale Empfangspruefung (Checkliste aus dem
   Institute-Profil, Item-fuer-Item-Abhaken). Ersetzt `shipmentManager`.
3. **Reminders + Notification-Adapter** — wiederkehrende Aufgaben (once/daily/
   weekly/monthly) mit `next_due_at`; der bestehende Outbox-Worker-Prozess
   feuert faellige Reminder und schickt sie ueber einen pluggable Notifier
   (Mattermost-Incoming-Webhook, generischer Webhook) an den im
   Institute-Profil konfigurierten Kanal. Ersetzt `emailReminderManager` +
   Telegram-Watchdogs. E-Mail/Telegram: spaeterer Adapter, gleiche Schnittstelle.

## Datenmodell (additiv, `create_all` reicht)

- `glue_batch`: glue_type, batch_no, pdb_sn?, status(new|in_use|expired|empty),
  manufacturing_date?, expiry_date?, opening_date?, bipack_count?, note?,
  mixed_at?, pot_life_minutes?, institute_id FK, created_at.
- `glue_usage`: glue_batch_id FK, component_sn, amount_mg?, note?, used_by,
  user_id?, used_at.
- `shipment`: pdb_id (unique), name?, sender_code, recipient_code, status,
  sent_at?, items JSON [{sn, component_type?}], institute_id FK, synced_at;
  lokal fuehrend: reception_status(pending|in_progress|done),
  reception_checklist JSON [{label, done}], reception_items JSON
  [{sn, received, note?}], reception_note?, reception_by?,
  reception_user_id?, reception_updated_at?. Sync ueberschreibt die
  reception_*-Felder nie (wie Tool-Sync RFID/Blacklist nie herunterstuft).
- `reminder`: title, note?, channel? (Name im Profil), schedule_kind
  (once|daily|weekly|monthly), next_due_at, active, last_fired_at?,
  last_error?, created_by, user_id?, institute_id FK, created_at, updated_at.

## Institute-Profil-Keys (Regel #4 — nichts davon im Code)

- `glue_pot_life_minutes`: `{glue_type: minutes}` — Default fuer den Mix-Timer.
- `shipment_reception_checklist`: `[label, …]` — Checklisten-Template; beim
  ersten Mirror einer Sendung in `reception_checklist` instanziiert.
- `notification_channels`: `{name: {kind: "mattermost"|"webhook", url, channel?}}`.
  URLs sind semi-geheim: die Institute-API redigiert `url` in Antworten fuer
  Nicht-Admins; das Frontend nutzt nur `GET /api/notifications/channels`
  (Name+Kind, nie URLs).

## Services & Verkabelung

- `app/domain/glue.py` + `pot_life_state(mixed_at, pot_life_minutes, now)` —
  reine Funktion (remaining_seconds, expired).
- `app/pdb_shipments.py` — Fetch nach dem Muster `pdb_test_evidence`:
  Gateway-Client, zwei Filter-Calls (recipient=code, sender=code), Dedupe per
  id, Items via `listShipmentItems`; `PdbSyncUnavailable` als einziger
  Fehlertyp, keine Upstream-Fehlertexte.
- `app/shipment_sync.py` — Upsert-Service nach `tool_sync`-Muster
  (Stats-Dataclass, Caller committet, Items von gelieferten Sendungen werden
  nicht neu geholt).
- `app/notifications.py` — `NotificationError`, `make_notifier(settings)`
  (urllib, Timeout `notify_timeout_seconds`, keine neuen Dependencies, URL
  taucht nie in Fehlermeldungen/Logs auf), Kinds mattermost/webhook.
- `app/reminders.py` — `compute_next_due`, `process_due_reminders(session,
  notifier, now)`: faellige aktive Reminder feuern, Audit `reminder.fired`/
  `reminder.failed` (Actor `reminder-worker`), Schedule auch bei Fehler
  weiterschalten (`last_error` sichtbar, kein Webhook-Hammering), `once`
  deaktiviert sich.
- `run_worker.py` — Reminder-Tick im bestehenden Poll-Loop; Web-App feuert
  nie selbst (ADR-002-Schnitt). Dev ohne Worker: Reminder ruhen (dokumentiert).
- Notifier haengt an `app.state.notifier` (Fake-Seam fuer Tests, wie
  `component_fetcher`).

## API (alle im zentralen `api.py`-Router, CSRF automatisch)

- Glue: `GET/POST /api/glue-batches`, `GET /api/glue-batches/scan?code=`,
  `PATCH /api/glue-batches/{id}`, `POST /api/glue-batches/{id}/mix`,
  `GET/POST /api/glue-batches/{id}/usage`. Reads offen, Writes operator.
- Shipments: `GET /api/shipments` (+`{id}`), `POST /api/sync/shipments/{institute_code}`
  (synchron, klein), `POST /api/shipments/{id}/reception` (operator).
- Reminders: `GET/POST /api/reminders`, `PATCH/DELETE /api/reminders/{id}`
  (operator), `GET /api/notifications/channels` (require_user),
  `POST /api/notifications/test` (admin).
- Audit: `glue_batch.created/updated/mixed/usage_recorded`,
  `shipment.reception_updated`, `reminder.created/updated/deleted/fired/failed`,
  `notification.test_sent`.

## Frontend

Drei Screens (`GlueBatchesScreen`, `ShipmentsScreen`, `RemindersScreen`) ersetzen
die `SOON`/P4-Platzhalter in der Rail (Reihenfolge wie im Mockup, Site-Gruppe).
Konventionen wie ToolsScreen: api.ts-Typen, `t`-Namespaces, Demo-Fallback,
`canWrite`-Gating, Chips mit Punkt+Label, `formatDuration` fuer den
Topfzeit-Countdown (tickende `nowMs`-State). Kein Mantine/TanStack.

## Tests / Verifikation

- pytest: `test_glue_batches.py`, `test_shipments.py` (Fake-Fetch ueber
  `app.state`), `test_reminders.py` (bestehende Referenzdatei ist zeuthenflow —
  Name hier: `test_reminders_api.py` + `test_notifications.py`).
- Frontend: `tsc -b && vite build` (kein Test-Runner vorhanden).

## Bewusst NICHT in diesem Schnitt (YAGNI / offen)

- PDB-Registrierung von Glue-Batches (Write-Scope), E-Mail-/Telegram-Adapter,
  Reminder-Eskalation, Reception-Tests-Autoverknuepfung, Admin-UI fuer
  `notification_channels` (Pflege via `PATCH /api/institutes/{code}`),
  Shipment-Erstellung (nur Mirror + Empfang).

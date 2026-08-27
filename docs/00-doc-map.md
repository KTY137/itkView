# Doc-Map: Wer besitzt welche Doku

> Ownership-Karte fuer die itkFlow-Doku plus die Dokumentationsdisziplin.
> Genutzt von den Doku-Waechtern **Yatagarasu** (Drift-Audit) und **Tenjin**
> (Doku-Sync) und von jedem Agenten, der Code aendert (harte Regel #6 in
> [`../CLAUDE.md`](../CLAUDE.md)).
>
> - **Besitzt:** die Ownership-Tabelle Dokument → Zustaendigkeitsbereich, den
>   Reverse-Index Code → Dokument und die Doku-Disziplin selbst. Diese Tabelle
>   ist die Autoritaet; andere Dokumente verweisen darauf, statt sie zu kopieren.
> - **Fuer wen:** jeden, der Code aendert und wissen muss, welches Dokument im
>   selben Change nachgezogen wird.
> - **Verwandt:** [`04-roadmap.md`](04-roadmap.md) (Abschnitt „Aktueller Stand"
>   ist bei jeder Aenderung zusaetzlich faellig),
>   [`03-agent-team.md`](03-agent-team.md) (die beiden Doku-Waechter),
>   [`README.md`](README.md) (Einstieg und Lesepfade).

## Regel

Jede Verhaltens-/Vertragsaenderung am Code aktualisiert **im selben Change** das
besitzende Dokument (Tabelle unten) **und** den Abschnitt „Aktueller Stand" in
[`04-roadmap.md`](04-roadmap.md). Reine Refactors/Test-Verdrahtung ohne Verhaltensaenderung
sind ausgenommen — dann genuegt eine Zeile Begruendung.

## Dokumente und ihr Verantwortungsbereich

| Dokument | Besitzt |
|---|---|
| [`docs/README.md`](README.md) | Einstieg, Lesepfade und Index von ADRs/Specs/Recherche (Router, keine Inhalte) |
| [`docs/00-doc-map.md`](00-doc-map.md) | Diese Ownership-Karte + Doku-Disziplin |
| [`docs/01-ist-analyse-zeuthenflow.md`](01-ist-analyse-zeuthenflow.md) | Alt-Workflow-Analyse (zFlow/Sheet/CERNBox); historisch |
| [`docs/02-revamp-plan.md`](02-revamp-plan.md) | Produktvision & Architektur; Deployment-Grundschnitt |
| [`docs/03-agent-team.md`](03-agent-team.md) | Agenten-Roster (inkl. Doku-Waechter) |
| [`docs/04-roadmap.md`](04-roadmap.md) | Ausfuehrungsfahrplan + **„Aktueller Stand"** (Herzschlag jeder Aenderung) |
| [`docs/05-ui-design-reference.md`](05-ui-design-reference.md) | UI/UX-Referenz, Layout, Interaktion, Pflicht-Test-Anzeige |
| [`docs/06-users-roles-audit.md`](06-users-roles-audit.md) | Auth, Rollen (viewer/operator/admin), Sessions, Audit-Zuordnung |
| [`docs/07-jig-tool-quickselect.md`](07-jig-tool-quickselect.md) | Jig-/Tool-Registry und typ-gefilterter Quick-Select |
| [`docs/08-remote-access.md`](08-remote-access.md) | Remote-Zugriff/Tunneling (Tailscale/Cloudflare) |
| [`docs/09-pdb-production-strategy.md`](09-pdb-production-strategy.md) | PDB-Produktionssicherheit, Read-/Write-Scopes |
| [`docs/10-itk-domain-reference.md`](10-itk-domain-reference.md) | ITk-Workflow, Komponenten-Taxonomie (Sensor/ASIC/Modul), Label-Legende |
| [`docs/11-logistics-operations.md`](11-logistics-operations.md) | Glue-Batches, Shipment-Mirror/Empfang, Reminder und Notification-Adapter |
| [`docs/12-attachments-and-images.md`](12-attachments-and-images.md) | Attachment-/Bild-Mechanik: drei Speicherwege (Binary-Store, EOS, Share-Link), lokaler Spiegel, Fehlersuche |
| [`docs/13-metrology-artifacts.md`](13-metrology-artifacts.md) | Metrologie-Artefakte: was wirklich am Lauf haengt, Benennungs-/Metadaten-Mehrdeutigkeit, Schluesselregeln |
| [`docs/adr/001-outbox-status-contract.md`](adr/001-outbox-status-contract.md) | Outbox-Statusvertrag |
| [`docs/adr/002-async-outbox-worker.md`](adr/002-async-outbox-worker.md) | Async-Outbox-Worker, Retry/Backoff |
| [`docs/adr/003-pdb-dummy-write-scope.md`](adr/003-pdb-dummy-write-scope.md) | `pdb_write_scope=dummy_only` |
| [`docs/adr/004-personal-pdb-credentials.md`](adr/004-personal-pdb-credentials.md) | Persoenliche PDB-Credentials, Verschluesselung, Identitaetsbindung |
| [`docs/adr/005-desktop-packaging.md`](adr/005-desktop-packaging.md) | Desktop-Paketierung: Tauri-Shell, PyInstaller-Sidecar, SPA-Hosting |
| [`docs/adr/006-staged-first-ui-auto-mirror.md`](adr/006-staged-first-ui-auto-mirror.md) | Staged-first-Komponentenarbeit, Ghost-Projektion und automatischer Evidence-/Attachment-Mirror |

## Reverse-Index: Code -> zustaendiges Doc

| Codebereich | Doc |
|---|---|
| `backend/app/auth.py`, `models.User`/`UserSession`, `/api/auth`, `/api/users` | [`06`](06-users-roles-audit.md) |
| `backend/app/pdb_gateway.py`, `pdb_sync.py`, `sync.py` (Mirror) | [`02`](02-revamp-plan.md) (Phase 1), [`09`](09-pdb-production-strategy.md) |
| `backend/app/pdb_test_evidence.py`, `test_run_evidence.py`, `models.TestRunEvidence` | [`04`](04-roadmap.md), [`09`](09-pdb-production-strategy.md) |
| `backend/app/attachment_store.py`, `share_credentials.py`, `models.TestRunAttachment`/`ExternalShareCredential`, `pdb_attachments.py` | [`12`](12-attachments-and-images.md), [`13`](13-metrology-artifacts.md), [`04`](04-roadmap.md), [`09`](09-pdb-production-strategy.md) |
| `backend/app/preview.py`, Component-Preview-Schemas und `/api/components/{sn}/preview` | [`adr/006`](adr/006-staged-first-ui-auto-mirror.md), [`04`](04-roadmap.md), [`05`](05-ui-design-reference.md) |
| `models.TestTypeSchema`, `backend/app/pdb_test_types.py`, `test_type_schemas.py` und `/api/test-types` | [`adr/006`](adr/006-staged-first-ui-auto-mirror.md), [`04`](04-roadmap.md) |
| Evidence-Job in `backend/app/sync_jobs.py`, EOS-/Share-Link-Mirror | [`adr/006`](adr/006-staged-first-ui-auto-mirror.md), [`04`](04-roadmap.md), [`09`](09-pdb-production-strategy.md) |
| `backend/app/desktop_server.py`, `diagnostics.py`, `static_spa.py`, `desktop/` (Tauri) | [`adr/005`](adr/005-desktop-packaging.md), [`04`](04-roadmap.md), [`05`](05-ui-design-reference.md), [README](../deploy/README.md) |
| `backend/app/pdb_credentials.py`, `models.PdbCredential` | [`06`](06-users-roles-audit.md), [`adr/004`](adr/004-personal-pdb-credentials.md) |
| `backend/app/pdb_scope.py` | [`adr/003`](adr/003-pdb-dummy-write-scope.md), [`09`](09-pdb-production-strategy.md) |
| `backend/app/outbox_worker.py`, `run_worker.py` | [`adr/002`](adr/002-async-outbox-worker.md) |
| `models.OutboxPdbPrincipal`, `backend/app/pdb_submit.py` | [`adr/002`](adr/002-async-outbox-worker.md), [`adr/004`](adr/004-personal-pdb-credentials.md) |
| `models.OutboxAction`/`AuditEvent`, Outbox-Status | [`adr/001`](adr/001-outbox-status-contract.md) |
| `backend/app/ingestion.py`, `pdb_upload.py` | [`02`](02-revamp-plan.md) (Phase 2) |
| `backend/app/domain/stages.py`, `backend/app/stage_service.py`, Stage-Suggestion | [`04`](04-roadmap.md), [`05`](05-ui-design-reference.md), [`10`](10-itk-domain-reference.md) §7 |
| `backend/app/stats.py`, `measurement_stats.py`, `required_test_stats.py`, `/api/stats` | [`04`](04-roadmap.md), [`05`](05-ui-design-reference.md) |
| `backend/app/tool_sync.py`, `models.Tool`, `/api/tools` | [`07`](07-jig-tool-quickselect.md) |
| `backend/app/domain/glue.py`, `backend/app/glue_service.py`, `models.GlueBatch`/`GlueUsage`, `/api/glue-batches` | [`11`](11-logistics-operations.md) |
| `backend/app/assembly.py`, Assembly-Wizard-Dry-Run | [`07`](07-jig-tool-quickselect.md), [`11`](11-logistics-operations.md) |
| `backend/app/ops_health.py`, `/api/ops/health` | [`04`](04-roadmap.md) |
| `backend/app/pdb_shipments.py`, `shipment_sync.py`, `shipment_reception.py`, `models.Shipment`, `/api/shipments` | [`11`](11-logistics-operations.md), [`09`](09-pdb-production-strategy.md) |
| `backend/app/reminders.py`, `notifications.py`, `models.Reminder`, `/api/reminders`, `/api/notifications` | [`11`](11-logistics-operations.md), [`adr/002`](adr/002-async-outbox-worker.md) |
| `backend/app/institute_settings.py`, Admin-Settings-UI und operative Institutsprofilwerte | [`11`](11-logistics-operations.md), [`05`](05-ui-design-reference.md), [`04`](04-roadmap.md) |
| `frontend/src/stagedPreview.ts`, `stagedActions.ts`, Detail-/Staged-/Ingest-UI | [`05`](05-ui-design-reference.md), [`adr/006`](adr/006-staged-first-ui-auto-mirror.md) |
| `frontend/src/ModuleWorksheet.tsx`, `testStaging.ts`, Worksheet-Payload in `preview.py` | [`05`](05-ui-design-reference.md), [`spec H`](superpowers/specs/2026-08-25-staged-first-module-page-design.md), [`adr/006`](adr/006-staged-first-ui-auto-mirror.md) |
| `frontend/src/fieldLayout.ts`, `dataEntryProfile.ts`, `ToolFieldSelect.tsx` (Feldreihenfolge, Baender, Tool-Dropdowns) | [`05`](05-ui-design-reference.md), [`07`](07-jig-tool-quickselect.md) |
| `frontend/src/**` (UI) | [`05`](05-ui-design-reference.md) |
| `deploy/`, Docker, CI | [`02`](02-revamp-plan.md) (Deployment), [README](../deploy/README.md) |

Jede Aenderung, egal wo: zusaetzlich [`04`](04-roadmap.md) „Aktueller Stand".

## Wie die Waechter arbeiten

- **Yatagarasu** (`.claude/agents/yatagarasu.md`, read-only, Haiku): auditiert
  Drift zwischen Code und Doku und liefert eine sortierte Drift-Liste.
- **Tenjin** (`.claude/agents/tenjin.md`, Haiku): wendet die Fixes an und haelt
  „Aktueller Stand" + ADRs aktuell.
- Der `Stop`-Hook `.claude/hooks/doc-guard.ps1` erinnert automatisch, wenn
  Produktivcode ohne Doku-Aenderung geaendert wurde (fail-open, loop-sicher).
- `/sync-docs` startet Audit + Fix in einem Rutsch.

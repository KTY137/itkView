# Doc-Map: Wer besitzt welche Doku

> Ownership-Karte fuer die itkFlow-Doku plus die Dokumentationsdisziplin.
> Genutzt von den Doku-Waechtern **Yatagarasu** (Drift-Audit) und **Tenjin**
> (Doku-Sync) und von jedem Agenten, der Code aendert (harte Regel #6 in
> `CLAUDE.md`).

## Regel

Jede Verhaltens-/Vertragsaenderung am Code aktualisiert **im selben Change** das
besitzende Dokument (Tabelle unten) **und** den Abschnitt „Aktueller Stand" in
`docs/04-roadmap.md`. Reine Refactors/Test-Verdrahtung ohne Verhaltensaenderung
sind ausgenommen — dann genuegt eine Zeile Begruendung.

## Dokumente und ihr Verantwortungsbereich

| Dokument | Besitzt |
|---|---|
| `docs/00-doc-map.md` | Diese Ownership-Karte + Doku-Disziplin |
| `docs/01-ist-analyse-zeuthenflow.md` | Alt-Workflow-Analyse (zFlow/Sheet/CERNBox); historisch |
| `docs/02-revamp-plan.md` | Produktvision & Architektur; Deployment-Grundschnitt |
| `docs/03-agent-team.md` | Agenten-Roster (inkl. Doku-Waechter) |
| `docs/04-roadmap.md` | Ausfuehrungsfahrplan + **„Aktueller Stand"** (Herzschlag jeder Aenderung) |
| `docs/05-ui-design-reference.md` | UI/UX-Referenz, Layout, Interaktion, Pflicht-Test-Anzeige |
| `docs/06-users-roles-audit.md` | Auth, Rollen (viewer/operator/admin), Sessions, Audit-Zuordnung |
| `docs/07-jig-tool-quickselect.md` | Jig-/Tool-Registry und typ-gefilterter Quick-Select |
| `docs/08-remote-access.md` | Remote-Zugriff/Tunneling (Tailscale/Cloudflare) |
| `docs/09-pdb-production-strategy.md` | PDB-Produktionssicherheit, Read-/Write-Scopes |
| `docs/10-itk-domain-reference.md` | ITk-Workflow, Komponenten-Taxonomie (Sensor/ASIC/Modul), Label-Legende |
| `docs/adr/001-outbox-status-contract.md` | Outbox-Statusvertrag |
| `docs/adr/002-async-outbox-worker.md` | Async-Outbox-Worker, Retry/Backoff |
| `docs/adr/003-pdb-dummy-write-scope.md` | `pdb_write_scope=dummy_only` |
| `docs/adr/004-personal-pdb-credentials.md` | Persoenliche PDB-Credentials, Verschluesselung, Identitaetsbindung |
| `docs/adr/005-desktop-packaging.md` | Desktop-Paketierung: Tauri-Shell, PyInstaller-Sidecar, SPA-Hosting |

## Reverse-Index: Code -> zustaendiges Doc

| Codebereich | Doc |
|---|---|
| `backend/app/auth.py`, `models.User`/`UserSession`, `/api/auth`, `/api/users` | `06` |
| `backend/app/pdb_gateway.py`, `pdb_sync.py`, `sync.py` (Mirror) | `02` (Phase 1), `09` |
| `backend/app/pdb_test_evidence.py`, `test_run_evidence.py`, `models.TestRunEvidence` | `04`, `09` |
| `backend/app/attachment_store.py`, `models.TestRunAttachment`, `pdb_attachments.py` | `04`, `09` |
| `backend/app/desktop_server.py`, `static_spa.py`, `desktop/` (Tauri) | `adr/005`, README |
| `backend/app/pdb_credentials.py`, `models.PdbCredential` | `06`, `adr/004` |
| `backend/app/pdb_scope.py` | `adr/003`, `09` |
| `backend/app/outbox_worker.py`, `run_worker.py` | `adr/002` |
| `models.OutboxPdbPrincipal`, `backend/app/pdb_submit.py` | `adr/002`, `adr/004` |
| `models.OutboxAction`/`AuditEvent`, Outbox-Status | `adr/001` |
| `backend/app/ingestion.py`, `pdb_upload.py` | `02` (Phase 2) |
| `backend/app/domain/stages.py`, Stage-Suggestion | `04`, `05` |
| `backend/app/stats.py`, `/api/stats` | `04` |
| `backend/app/tool_sync.py`, `models.Tool`, `/api/tools` | `07` |
| `frontend/src/**` (UI) | `05` |
| `deploy/`, Docker, CI | `02` (Deployment), README |

Jede Aenderung, egal wo: zusaetzlich `04` „Aktueller Stand".

## Wie die Waechter arbeiten

- **Yatagarasu** (`.claude/agents/yatagarasu.md`, read-only, Haiku): auditiert
  Drift zwischen Code und Doku und liefert eine sortierte Drift-Liste.
- **Tenjin** (`.claude/agents/tenjin.md`, Haiku): wendet die Fixes an und haelt
  „Aktueller Stand" + ADRs aktuell.
- Der `Stop`-Hook `.claude/hooks/doc-guard.ps1` erinnert automatisch, wenn
  Produktivcode ohne Doku-Aenderung geaendert wurde (fail-open, loop-sicher).
- `/sync-docs` startet Audit + Fix in einem Rutsch.

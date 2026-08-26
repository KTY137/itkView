# Revamp-Plan: ITk Production Webapp (Arbeitstitel: **itkFlow**)

> Ziel: Google-Sheet + CERNBox-Triage + Cron-zFlow ersetzen durch eine **selbst-hostbare,
> institut-agnostische Webapp**, die jede ITk-Produktionsstätte per `docker compose up`
> betreiben kann. Die ITk PDB bleibt Source of Truth; itkFlow ist das Cockpit davor.

> Dieses Dokument ist die Produktvision. Der aktive Ausführungsfahrplan für
> Agenten und Meilensteine steht in [`04-roadmap.md`](04-roadmap.md).
>
> - **Besitzt:** Leitprinzipien, Zielarchitektur, lokales Datenmodell, den
>   Phasenschnitt 0–6 und den Deployment-Grundschnitt. Hier steht das
>   **Geplante** — der Ist-Zustand steht in der Roadmap und den Fachdokumenten.
> - **Für wen:** alle, die eine Architekturentscheidung treffen oder einordnen
>   wollen, warum itkFlow so geschnitten ist.
> - **Verwandt:** [`01-ist-analyse-zeuthenflow.md`](01-ist-analyse-zeuthenflow.md)
>   (das abzulösende System), [`04-roadmap.md`](04-roadmap.md) (Ausführung und
>   „Aktueller Stand"), [`09-pdb-production-strategy.md`](09-pdb-production-strategy.md)
>   (PDB-Sicherheitsmodell), [`adr/`](adr) (Einzelentscheidungen),
>   [`README.md`](README.md) (Lesepfade).

## 0. Leitprinzipien

1. **Multi-Institut by design** — kein `DESYZ`/`DZHU-` im Code. Alles, was heute Config/Hardcoding
   ist, wird ein *Institute Profile* (DB-gestützt, im Admin-UI editierbar): Institutscode,
   Namensschema für lokale Namen (Template + Validierung), aktivierte Workflows, Test→Stage-Mapping,
   Notification-Kanäle, Locale. Eine Instanz kann mehrere Institute hosten (Mandanten), muss aber nicht.
2. **PDB-Schemata statt Hardcoding** — Komponententypen, Stages, Testtypen und deren Pflichtfelder
   werden aus der PDB gelesen und lokal gespiegelt (kein `59d60c13ed…` im Code). Neue Modultypen
   funktionieren ohne Codeänderung.
3. **Nichts schreibt ungeprüft in die PDB** — jede Schreiboperation läuft durch eine **Outbox/Queue**
   mit Validierung, Vorschau (Dry-Run), optionalem 4-Augen-Review und vollem Audit-Log. Retry bei
   PDB-Ausfall. Das ersetzt "Cron hat's hoffentlich gemacht".
4. **Sekunden statt Stunden** — Eingabe → Validierung → PDB → Status live im UI. Kein TSV, kein
   Apps Script, kein Public-Link.
5. **Erst lesen, dann schreiben** (Migrationsstrategie) — die App wird zuerst als Read-Only-Cockpit
   wertvoll und übernimmt Schreibpfade Workflow für Workflow, während zFlow parallel weiterläuft.

## 1. Architektur

```
┌────────────────────────────────────────────────────────────────────┐
│  Frontend: React + TypeScript (Vite), Mantine UI, TanStack Query   │
│  Kanban · Detailseiten · Erfassungs-Wizards · Triage · Dashboards  │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ REST/JSON (OpenAPI) + WebSocket (Live-Status)
┌──────────────────────────────┴─────────────────────────────────────┐
│  Backend: Python 3.12 + FastAPI + SQLAlchemy + Pydantic            │
│                                                                    │
│  ├─ PDB-Gateway   (itkdb; Token-Mgmt, Paging, Rate-Limit, Cache)   │
│  ├─ Sync-Service  (PDB→lokal: Komponenten, Tests, Shipments,       │
│  │                 Schemata; inkrementell, ersetzt 175-MB-Cache)   │
│  ├─ Outbox/Queue  (lokal→PDB: Registrieren, Assemblieren, Stage-   │
│  │                 Moves, Testrun-Uploads; Dry-Run, Retry, Audit)  │
│  ├─ Ingestion     (Instrument-JSONs: Watched-Folder-Agent, Drag&   │
│  │                 Drop, REST; Parser-Plugins pro Testtyp)         │
│  ├─ Workflows     (Zustandsmaschinen pro Komponententyp, aus PDB-  │
│  │                 Stages + Instituts-Profil konfiguriert)         │
│  └─ Notifications (E-Mail, Mattermost, Telegram — Adapter)         │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
        PostgreSQL (lokale Arbeits-DB)      Objektstore: Dateisystem/S3-kompatibel
        (Komponenten-Spiegel, Outbox,       (VI-Bilder, Roh-JSONs, Anhänge)
         lokale Entitäten, Audit, Users)
```

**Warum dieser Stack:** Python weil das gesamte PDB-Ökosystem (itkdb, Parser, Physik-Team-Know-how)
Python ist — der Gateway-Code kann Muster aus zFlow 1:1 portieren. FastAPI liefert OpenAPI gratis
(→ Instrument-PCs können direkt posten). Postgres statt Datei-Cache. React/TS für ein UI, das
schneller sein muss als das Sheet, sonst gewinnt das Sheet.

**Deployment:** Ein `docker-compose.yml` (app, worker, postgres, optional minio). Kein CERN-Dienst
nötig; läuft auf einem Lab-PC oder Instituts-VM. Updates via Container-Tag.

**Auth:** Lokale Accounts + optional OIDC (CERN SSO / Instituts-IdP). Rollen: `viewer`, `operator`
(erfassen), `coordinator` (PDB-Writes freigeben, Stage-Moves), `admin` (Instituts-Profil).
PDB-Zugang: pro Nutzer hinterlegte, serverseitig verschluesselte
Plus4U/PDB-Access-Codes (ADR 004). Web- und Worker-Aktionen haben keinen
Instituts-/Server-Credential-Fallback; jede PDB-Aktion loggt und bindet, unter
welcher lokalen und PDB-Identitaet sie lief.

## 2. Datenmodell (lokal, vereinfacht)

- **Spiegel (read-mostly, vom Sync gepflegt):** `component` (SN, Typ, Stage, Location, Familie),
  `test_run`, `shipment`, `pdb_schema` (Komponenten-/Testtyp-Definitionen).
- **Lokal führend:** `institute_profile`, `user`/`role`, `local_component_meta` (lokaler Name,
  Bench-Notizen, Fotos), `work_item` (Erfassungsvorgang/Checkliste), `outbox_action`
  (+ Status: draft → validated → approved → submitted → confirmed/failed), `ingest_file`,
  `glue_batch`, `tool` (Jigs/Pickup-Tools, RFID↔SN — ersetzt ToolConverter-Sheet),
  `reminder`, `audit_event`, `share_link` (read-only Tokens für Kollaborations-Ansichten).
- **Credential-/Submit-Identitaet:** `pdb_credential` haelt pro User nur
  AES-GCM-Ciphertext und Statusmetadaten; `outbox_pdb_principal` bindet eine
  freigegebene Aktion an Approver + PDB-Identity-Snapshot (ADR 004).
- **Blacklists/Sonderfälle** (heute Config/Apps-Script): `component_flag`
  (z.B. `terminally_dead`, `rfid_blacklisted`, `do_not_process`) — im UI pflegbar, mit Begründung.

## 3. Die Workflows im UI (ersetzt die Sheets 1:1, aber geführt)

| Heute (Sheet/Tool) | Morgen (itkFlow) |
|---|---|
| Modul-Sheet (Spalte je Modul, 40+ Zeilen) | **Assembly-Board**: Kanban nach Stage; Modul-Detailseite mit Familienbaum (Sensor/Hybride/PB), Historie, Tests, Grades |
| Neue Zeile + Regex-Glück | **Wizards** pro Schritt: "Modul anlegen" (lokaler Name nach Schema, HV-Tab-Jig scannen), "Sensor aufbringen" (SN/RFID scannen, HV-Tab-Sheet), "Hybride/PB kleben" (Jig, Pickup-Tool, Glue-Batch aus Dropdown mit Verfallswarnung), Glue-Weight-Rechner (Waagen-Eingaben, Toleranz live) |
| `SCRIPT: registered to DB?` | Live-Status-Chip je Aktion: ⏳ queued → ✅ in PDB (mit Link) / ❌ Fehler + Grund |
| UploadManager-Globs | **Test-Triage**: eingehende Instrument-JSONs (Agent/Upload) landen in Inbox → Parser ordnet Komponente+Testtyp zu → Vorschau (Pass/Fail, Plots) → Freigabe → Outbox → PDB |
| automaticStageMoving | Regelbasierte **Stage-Vorschläge** ("alle Pflicht-Tests @ GLUED grün → vorschlagen: STITCH_BONDING"), Coordinator bestätigt (oder Auto, pro Institut konfigurierbar) |
| Glue-Sheet | Glue-Batch-Registry: anrühren, Topfzeit-Timer, Verbrauch je Komponente, PDB-Registrierung |
| Shipment-Tracking im Sheet | Shipments-Ansicht (ein-/ausgehend, Empfangsprüfung mit Checkliste → Reception-Tests) |
| VI: Bilder → CERNBox → HTML-Templates | VI-Modul: Upload/Kamera, Defekt-Annotation, Auto-JSON für PDB, teilbare Galerie-Links |
| OverviewMaker-TSVs | **Dashboards**: Produktionsdurchsatz, Yield je Stage, offene Tests, "wo klemmt's"; Export XLSX/TSV für Altprozesse |
| E-Mail-Reminder-Sheet | Reminder-Modul (wiederkehrende Aufgaben, Eskalation) |
| Telegram-Crash-Bot | Health-Page + Notification-Adapter (Fehler der Outbox/Sync gezielt an Kanäle) |

**Erfassungs-UX ist der Erfolgsfaktor:** Barcode-/RFID-Scanner-first (Keyboard-Wedge), große
Touch-Targets fürs Labor, Tastatur-Navigation, Offline-Puffer der Formulare (PWA) als Ausbaustufe.

## 4. Phasenplan

**Phase 0 — Fundament (1–2 Wochen Aufwand):** Monorepo-Scaffold (`backend/`, `frontend/`,
`agent/`, `deploy/`), CI (lint, typecheck, tests), Docker Compose, Auth-Grundgerüst,
Instituts-Profil-Modell, PDB-Gateway mit fail-closed Produktions-Opt-in und
persoenlichem Credential-Handling. Es gibt keine PDB-Testinstanz mehr; Dev/CI
bleiben offline, markierte Integrationslaeufe nutzen Produktion read-only oder
DUMMY-gescoped ([docs/09](09-pdb-production-strategy.md),
[ADR 003](adr/003-pdb-dummy-write-scope.md)/[004](adr/004-personal-pdb-credentials.md)).

**Phase 1 — Read-Only-Cockpit:** Sync-Service (Komponenten/Tests/Shipments des Instituts),
Komponenten-Browser + Detailseite + Familienbaum, Dashboards. *Ersetzt: OverviewMaker,
Overview-Tabs, macros.gs-Spaltenverstecken.* → Ab hier täglicher Nutzen, null Schreibrisiko.

Der Komponenten-Sync laeuft als persistenter, globaler Single-Flight-Job statt
in der Lebensdauer eines HTTP-Requests oder React-Screens. Das Frontend startet
den Job per REST, findet ihn nach Navigation/Reload wieder und pollt nur dessen
kleinen Statusdatensatz. Der vollstaendige PDB-Snapshot, Parent-Aufloesung,
Prune, Stage-Historie und Tool-Ableitung bleiben eine atomare lokale
Transaktion; ein Fehler oder Server-Neustart exponiert keinen Teilstand.
Produktive `full`-Payloads werden seriell, mit expliziter Seitengroesse,
Timeout/Retry und Vollstaendigkeitspruefung gelesen. WebSocket-Push bleibt eine
spaetere Transportoptimierung, kein Bestandteil der Korrektheitslogik.
Der aktuelle In-Process-Executor ist bewusst ein **Single-App-Worker-Vertrag**;
Launcher und Docker-CMD starten genau einen Uvicorn-Worker. Vor horizontaler
API-Skalierung braucht der Lease zusaetzlich Owner/Heartbeat/Expiry, damit ein
zweiter Prozess keinen fremden Live-Job als Neustart-Rest klassifiziert.

**Phase 2 — Test-Ingestion & Upload-Queue:** Ingestion-Parser (Metrologie, Bow, Pulltest,
Wirebonding, Glue-Weight, IV, TC/ColdJig, Strobe Delay, Response Curve — Fixtures aus den
anonymisierten Test-JSONs), Triage-UI, Outbox mit Dry-Run/Review/Audit. *Ersetzt: UploadManager.*

**Phase 3 — Assembly-Workflows:** Wizards für Hybrid- und Modul-Bau (Registrierung, Assemblierung
mit Attachment-Properties, Glue-Weights, Panels), Stage-Vorschläge. *Ersetzt: hybridManager,
moduleManager, das Haupt-Sheet.* Parallelbetrieb mit zFlow + täglicher Abgleichreport, dann Cutover.

**Phase 4 — Logistik & Betrieb:** Shipments inkl. Empfangsprüfung, Glue-Batches, Tool/Jig-Registry
(RFID-Mapping), Reminder, Notification-Adapter. *Ersetzt: shipmentManager, glueHandler,
toolConverter, emailReminderManager, Telegram-Watchdogs.*

**Phase 5 — VI & Kollaboration:** VI-Galerie mit Annotation, Share-Links, Berichte/Exports.
*Ersetzt: visualInspectionManager, CERNBox-HTML.*

**Phase 6 — Multi-Institut-Härtung:** Onboarding-Assistent ("neues Institut in 30 min"),
i18n (EN/DE), Mandantentrennung, Doku, Beispiel-Profile (Endcap/Barrel), Release v1.0 +
Pilot bei einem zweiten Institut.

## 5. Migration & Risiken

- **Einmal-Import:** Bestehende Sheets werden einmalig importiert (der zFlow-Parser-Code dient als
  Spezifikation der Spalten); lokale Namen/Flags/Blacklists wandern in die DB.
- **Parallelbetrieb mit Reconciliation:** Solange zFlow läuft, vergleicht ein Job PDB-Zustand vs.
  itkFlow-Erwartung und meldet Abweichungen — Vertrauen vor Abschaltung.
- **Risiken:** PDB-Latenz/-Limits (→ Sync + Outbox), Token-Handling (→ Sandbox zuerst, Audit),
  Akzeptanz der Schichtcrews (→ Phase 1 zuerst Nutzen ohne Verhaltensänderung; Wizards müssen
  schneller sein als das Sheet), Instituts-Sonderlocken (→ alles Profil, nichts Code).
- **Nicht-Ziele:** Kein PDB-Ersatz, keine Analyse-Physik (bleibt in den bestehenden Tools),
  kein Nachbau der Sheet-Optik.

## 6. Offene Entscheidungen (kurz mit dir zu klären)

1. **PDB-Zugang für Dev**: Zugang zur PDB-Sandbox/Test-Instanz vorhanden? (Voraussetzung Phase 0/1)
2. **Hosting**: Instituts-VM (DESY) vs. Lab-PC — beeinflusst nur Deployment-Doku.
3. **Auth**: Reichen lokale Accounts für v1, OIDC später?
4. **Scope v1**: Endcap-Workflows (wie Zeuthen) zuerst; Barrel-Spezifika als Profil-Erweiterung ok?
5. **Name**: itkFlow? 😄

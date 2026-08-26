# Ist-Analyse: zeuthenFlow & der Spreadsheet-Workflow

> Analysierte Referenz: `references/zeuthenflow` (anonymisierte Kopie, siehe `ANONYMIZATION.md` dort).
> Kontext: ATLAS ITk Strip-Modul-Produktion. Die zentrale Wahrheit liegt in der
> **ITk Production Database (PDB)** am CERN; zeuthenFlow orchestriert lokal die Dateneingabe,
> Registrierung, Assemblierung, Test-Uploads und Übersichten — über Google Sheets.
>
> - **Besitzt:** die Analyse des abzulösenden Alt-Workflows (Sheet, CERNBox,
>   zFlow-Cron) samt Baustein-Inventar und Kern-Schmerzen. Historisch: der Text
>   beschreibt den Ausgangszustand, nicht itkFlow.
> - **Für wen:** alle, die verstehen wollen, welches Problem ein Feature löst,
>   und alle, die Alt-Verhalten nachbauen oder migrieren.
> - **Verwandt:** [`02-revamp-plan.md`](02-revamp-plan.md) (die Ablösung),
>   [`10-itk-domain-reference.md`](10-itk-domain-reference.md) (dieselbe Domäne
>   ohne Sheet-Perspektive),
>   [`superpowers/research/2026-08-26-zflow-sheet-transcription.md`](superpowers/research/2026-08-26-zflow-sheet-transcription.md)
>   (die wörtliche Abschrift der Blätter), [`README.md`](README.md) (Lesepfade).
>
> **Achtung:** `references/zeuthenflow` wird nur gelesen, niemals ausgeführt oder
> importiert (harte Regel 1 in [`../CLAUDE.md`](../CLAUDE.md)).

## 1. Der heutige Datenfluss (die "Triage")

```
┌─────────────────────┐   TSV-Export-URL    ┌──────────────────┐   itkdb / p_d_s   ┌──────────────┐
│  Google Spreadsheet  │ ──────────────────▶ │   zeuthenFlow    │ ◀───────────────▶ │  ITk PDB      │
│  (Handeingabe,       │                     │   (main.py,      │                   │  (CERN,       │
│   1 Spalte = 1 Modul)│                     │    Cron-Lauf)    │                   │   Wahrheit)   │
└─────────────────────┘                     └──────────────────┘                   └──────────────┘
        ▲                                          │
        │  Apps-Script-Trigger                     │  fromModules.tsv / fromHybrids.tsv
        │  (alle 5–30 min, macros.gs)              ▼
┌─────────────────────┐   public share      ┌──────────────────┐
│  "Overview"-Tabs im  │ ◀────────────────── │ CERNBox /         │
│  selben Spreadsheet  │                     │ DESY SyncAndShare │
└─────────────────────┘                     └──────────────────┘
```

Ein voller Roundtrip (Eingabe → PDB → Rückmeldung im Sheet) dauert **bis zu Stunden** und hat
**vier fehleranfällige Übergaben**: TSV-Export-Parsing, Cron-Batch, Public-Link-Upload,
Apps-Script-Import (Fehlererkennung dort: `if (!text.includes("DOCTYPE"))` 🙈).

## 2. Komponenten von zeuthenFlow

| Baustein | Zweck | Ablösung durch Webapp |
|---|---|---|
| `main.py` + `default.conf` | Orchestrierung per Cron, Zeitfenster pro Sektion | Backend-Services + Scheduler |
| `core/hybridManager.py` | Hybrids: Registrierung, ABC/HCC-Chip-Assemblierung, Panels, Glue-Weights | Workflow "Hybrid Assembly" |
| `core/moduleManager.py` (~1900 Zeilen) | Module: Registrierung, Sensor/Hybrid/PB-Assemblierung, Stage-Moves, IV-Info, TSV-Feedback | Workflow "Module Assembly" |
| `core/glueHandler.py` | Glue-Batches aus eigenem Sheet registrieren, Verbrauch tracken | Modul "Glue/Consumables" |
| `core/uploadManager.py` | Globbt Instrument-JSONs von Platte, lädt Testruns in PDB | Ingestion-Service + Upload-Queue |
| `core/shipmentManager.py` | Shipments aus PDB verfolgen | Modul "Shipments" |
| `core/visualInspectionManager.py` + `processVisualInspection.py` | Sensor-VI: Bilder → CERNBox, statische HTML-Galerien aus Templates | Modul "Visual Inspection" |
| `core/overviewMaker.py` | Empfangs-/Statusübersichten als TSV | Dashboards (live) |
| `core/emailReminderManager.py` | E-Mail-Erinnerungen (u.a. Reinigungsdienste!) aus Sheet | Modul "Reminders/Notifications" |
| `core/cacheUpdater.py` + `ci/database_cache.json` | Datei-Cache der PDB (im Original **175 MB** JSON, Granularitäts-Merging) | Lokale SQL-DB + Sync-Service |
| `modules/processGoogleDoc.py` (~2000 Zeilen) | Sheet-Download + Regex-Parsing jeder Zelle | **entfällt komplett** |
| `modules/toolConverter.py` | RFID ↔ Werkzeug-SN-Mapping aus eigenem Sheet | Tool/Jig-Registry |
| `modules/databaseInteraction.py` | PDB-Zugriff (Token, Paging, Assemble/Disassemble, Call-Statistiken) | PDB-Gateway-Service (itkdb) |
| `modules/dbObjects/*` (Component/Module/Hybrid/Sensor/PB/Test/Batch/Shipment/Glue) | Domänenmodell inkl. Stage-Listen & Test→Stage-Mapping | Domänenmodell im Backend (wiederverwendbares Wissen!) |
| `scripts/macros.gs` | Apps Script: TSV-Import, Spalten-Verstecken (mit hartkodierten toten Modulen) | **entfällt komplett** |
| `modules/Logger.py` | Logging + Telegram/Mattermost-Alarme | strukturiertes Logging + Notification-Adapter |

## 3. Domänenmodell (aus `dbObjects` extrahiert — wertvollstes Asset)

- **Komponenten**: Sensor, Hybrid (R0H0…R5H3), Powerboard, Halbmodul, Ringmodul (R0–R5, M0/M1),
  Chips (ABC/HCC), Panels, Carrier. Identifikation: PDB-SN (`20USE…`), lokaler Name
  (z.B. `DZHU-PPB-R5M1-02`, Prefix konfigurierbar), RFID.
- **Stages** (z.B. Halbmodul): `HV_TAB_ATTACHED → GLUED → STITCH_BONDING → AT_LOADING_SITE →
  HALFMODULE_FOR_LOADING | FAILED | QA | ON_CORE`; Ringmodul zusätzlich `BONDED → TESTED → FINISHED`.
- **Test→Stage-Mapping** pro Komponententyp (`stageOfTest`), z.B. `MODULE_METROLOGY` @ `GLUED`,
  `MODULE_IV_AMAC_TC` @ `TESTED`.
- **Assemblierung** mit Attachment-Properties (Jigs, Pickup-Tools, Glue-Samples) und
  Auto-Disassembly von Trägern (Panel, PWB-Carrier).
- **Tests**: Glue-Weight, Metrologie, Bow, Wirebonding/Pulltests, IV (warm/kalt, VBD, I@200V),
  Thermocycling/ColdJig, Strobe Delay, Response Curves, VI, HV-Stabilität.

## 4. Kern-Schmerzen (warum "ziemlich bescheuert und fehleranfällig")

1. **Freitext-Zellen als API**: Jede Zelle wird per Regex geparst (deutsche Dezimalkommas,
   `"select"`-Platzhalter, `"-"` als None, transponierte DataFrames, umbenannte Duplikat-Spalten
   `_1`). Ein Tippfehler = stiller Skip oder falscher DB-Write.
2. **Stundenlange, unklare Feedbackschleife** über 4 Systeme; niemand weiß, ob eine Eingabe "durch" ist
   (`SCRIPT: registered to DB?`-Spalten als Erfolgsindikator).
3. **Kein Berechtigungsmodell**: Wer das Sheet editieren kann, kann alles; keine Nachvollziehbarkeit.
4. **Zustand in Dateien**: 175-MB-JSON-Cache, TSV vom letzten Lauf als "Datenbank", Backups von
   Sheet-Downloads als Disaster-Recovery.
5. **Hardcoding überall**: Institut `DESYZ`, Prefix `DZHU-`, Mongo-IDs von Komponententypen,
   RFID-Blacklists in der Config, tote Module im Apps Script, Pfade `/home/…`.
6. **Batch statt Ereignis**: Cron-Zeitfenster, Reprocessing-Heuristiken (`updateFinishedEveryHours`),
   Golden-File-CI (`expected_output.txt`).
   ⚠️ **Die CI-Tests liefen gegen die Produktions-PDB** (`.gitlab-ci.yml`: "Authenticating to
   production DB", Secrets `PROD_DB_ACCESS_TOKEN_1/2`) — es gibt keinen einzigen Mock; schon der
   Import von `modules` baut die DB-Verbindung auf. Absicherung nur über `upload = False`,
   `--maxNumberOfEntriesToProcess 5` und den Datei-Cache. Die `itkpd-test`-Links im Code sind
   reine UI-Links und dabei inkonsistent (dbComponent → Testinstanz, uploadManager → Produktion).
7. **Fehlerkanal = Telegram-Bot**, Monitoring = Watchdog-Shellscripts.
8. **Nicht übertragbar**: Ein anderes Institut müsste Sheets, Macros, Configs und Hardcodings klonen.

## 5. Was bleiben muss (Invarianten)

- Die **PDB bleibt die einzige Wahrheit** — die Webapp ersetzt Sheet + zFlow, nicht die PDB.
- Die PDB-Interaktionsmuster (Registrierung, Assembly-Dicts, Paging, Testrun-Upload,
  `setInstitute`/Executive-Check, Komponenten-Familien) sind erprobt und werden portiert (auf `itkdb`).
- Die Instrument-Output-Formate (Test-JSONs der Messplätze) sind gesetzt — Ingestion muss sie parsen.
- Lokale Namen, RFIDs und Barcode-Workflows der Labore bleiben zentrale Identifikatoren.

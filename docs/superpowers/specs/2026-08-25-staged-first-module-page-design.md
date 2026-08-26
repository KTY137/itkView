# Spec: Staged-First-Modulseite + Auto-Mirror

Datum: 2026-08-25 · Status: vom Nutzer freigegeben (Chat) · Owner:
[docs/00-doc-map.md](../../00-doc-map.md)
Betroffene Roadmap-Punkte: Phase-2-Ingestion, Phase-3-Stage-Flow
([docs/04](../../04-roadmap.md)).
Umgesetzt als [ADR 006](../../adr/006-staged-first-ui-auto-mirror.md); die
laufende UI-Referenz dazu ist
[docs/05](../../05-ui-design-reference.md).

## Ziel

Die Modul-Detailseite wird der eine Ort, an dem Operatoren arbeiten: Tests
erfassen (Datei-Drop und Formulare), Stage-Moves vorschlagen, ausstehende
Änderungen als „Ghost"-Vorschau sehen. Triage schrumpft zum reinen Ingest-Log,
die Outbox wird zum „Staged"-Fenster. Alles, was die PDB über die eigenen
Komponenten weiß — Messwerte, Rohdateien, Bilder — wird automatisch lokal
gespiegelt: itkFlow ist ohne Netz vollständig auskunftsfähig.

Kein Nutzer sieht oder editiert jemals rohes JSON (zFlow-Spreadsheet-Modell:
Formulare rein, JSON wird intern erzeugt).

## Nicht-Ziele

- Echte Produktions-Writes: `pdb_write_scope=dummy_only` bleibt unangetastet
  (ADR 003). Das Staged-Fenster macht die Grenze nur sichtbar.
- Watched-Folder-Agent (bleibt Phase 2; das Ingest-Log ist dafür vorbereitet).
- Schema-Formulare für Registrierung/Assembly (nur Test-Runs).

## Empirische Grundlage (Live-Validierung 2026-08-25)

- Alle 713 gespiegelten TUDO-Modul-Testläufe gescannt: 360 Attachments,
  ausnahmslos Binary-Store (`type: "file"`; 351 × `binaryStoreg02=true`,
  9 × ältere Store-Generation). IV 218/219, Metrologie 104/104, Bow 28/28
  tragen ihre Rohdatendatei. Download-Route validiert:
  `getTestRunAttachment` mit `code` + `testRun`.
- EOS-Attachments (`type: "eos"`): bei TUDO nicht vorhanden; Mechanismus per
  itkdb-Doku belegt: `noEosToken: false` ⇒ vorsignierte
  `eosatlas.cern.ch`-URL, Download nur mit PDB-Codes, kein CERN-SSO;
  itkdb ≥ 0.6.13 nötig (installiert: 0.6.20, CERN-CA-Kette gebündelt).
- zFlow-Erbe (DESYZ): VI-Bilder liegen NICHT als Attachments, sondern als
  öffentliche CERNBox-/Sync&Share-Links in Result-Feldern
  (`URLSCRATCHPAD`, `URLS1..6`); plain unauthentifizierter GET
  (references/zeuthenflow, processVisualInspection.py:399-402, 759-778).
  Sentinel-Wert `"failed"` möglich; Nextcloud-Ausfälle liefern historisch
  HTML-Seiten statt Daten.

## A — Preview-Endpunkt (Ghost-Fundament)

`GET /api/components/{sn}/preview` → `ComponentPreviewOut`:

- `current`: `{stage, checks}` — Checks für die aktuelle Stage
  (aus `stage_service`).
- `staged_actions[]`: offene (nicht-terminale) Outbox-Actions für diese SN:
  `{id, kind, status, summary, to_stage?, test_type?, created_by, created_at,
  submittable}` — `summary` menschenlesbar, `submittable=false` mit Grund
  (`not_dummy`), wenn `dummy_only` den PDB-Push verweigern würde.
- `projected`: `{stage, checks, ghost_tests[]}` — Stage nach Anwendung aller
  Stage-Moves in Erstellungsreihenfolge; `checks` neu berechnet für die
  projizierte Stage, wobei ausstehende `upload_test_run`-Actions als
  `pending` zählen (eigener Status neben passed/failed/missing);
  `ghost_tests[]` enthält **nur** die ausstehenden, noch nicht gepushten
  Upload-Actions (`ghost: true, outbox_action_id`) — keine gespiegelten
  Läufe. (Nachtrag §H1: das Feld hieß ursprünglich `tests[]` und trug
  gespiegelte Läufe zusätzlich zu den Ghost-Einträgen; die Preview verlor
  die gespiegelten Läufe im Review-Nachzug wieder — rohe Messwerte liefert
  seither ausschließlich `GET /api/components/{sn}/tests`.)

Implementierung: `backend/app/preview.py` als reine Funktion
`build_component_preview(session, component, settings) -> dict`, neben
`stage_service`; Endpunkt in `api.py` (require_user). Kein PDB-Zugriff —
arbeitet ausschließlich auf Spiegel + Outbox. pytest:
`tests/test_component_preview.py` (Projektion, Reihenfolge mehrerer Moves,
pending-Checks, not_dummy-Flag, leerer Fall).

## B — Ghost-Darstellung mit Nutzer-Toggle

Neues Panel „Preferences" im Account-Screen. Einstellung „Staged preview":

- `tabs` (Default): Tab-Leiste `[Current] [Staged (n)]` im Detailkopf.
  Staged-Tab rendert `projected` gestrichelt/abgesetzt (bestehende
  Ghost-Optik der `.ghost-row` fortgeführt), je Action Submit/Discard.
  Bei 0 offenen Actions kein zweiter Tab.
- `inline`: keine Tabs; Annotationen in situ — Stage-Chip
  `HV_TAB_ATTACHED → ⌇GLUED⌇`, Ghost-Zeilen in der Testliste, Checks mit
  pending-Chips.
- `off`: heutiges Verhalten (nur StagedChangesSection).

Persistenz: `localStorage` (`itkflow.stagedPreview`), Fallback `tabs`;
try/catch um jeden Zugriff. Beide Modi konsumieren denselben
Preview-Payload — keine Frontend-Projektionslogik.

## C — Testerfassung auf der Modulseite

Ein Rohr, zwei Eingänge; beide erzeugen einen `IngestFile` und laufen durch
denselben Dry-Run (`GET /api/ingest/files/{id}/preview`) und dasselbe
`propose-outbox` (409 bei Issues bleibt).

1. **Datei-Drop**: Dropzone auf der Detailseite (Karte „Add test result").
   Drop/Dateiauswahl → `POST /api/ingest/files` mit `component_sn`-Pin
   (neues optionales Feld; Server validiert gegen den Mirror und überschreibt
   einen abweichenden SN im Payload nicht stillschweigend, sondern meldet die
   Diskrepanz als Issue). Ergebnis-Karte zeigt den Dry-Run (Messwerte,
   Warnungen, Issues); Knopf „Stage upload" → Outbox-Draft → Ghost.
2. **Formular** („Record test"): Testtyp-Auswahl aus gespiegelten Schemata,
   Formular generiert aus dem Schema, Submit erzeugt intern das kanonische
   Payload-JSON und POSTet es als IngestFile (`parser`-Feld markiert
   `manual-entry`). Gleiche Karte, gleicher Weg.

**Schema-Spiegel**: neue Tabelle `test_type_schema`
`(id, component_type, test_code, name, schema JSON, synced_at;
unique(component_type, test_code))`. Sync read-only über das persönliche
Gateway: `listTestTypes {project, componentType}` + `getTestTypeByCode`;
Endpunkte `GET /api/test-types?component_type=` (Liste) und
`POST /api/test-types/sync?component_type=` (require_operator; strict-503 wie
sync-evidence). Formulargenerator (Frontend, `TestForm.tsx`): `properties` und
`results` aus dem Schema; Datentypen string/float/integer/boolean als Felder,
`valueType=array` als Textarea „ein Wert pro Zeile" (numerisch validiert);
Pflichtfelder aus `required`. Unbekannte Datentypen ⇒ Feld read-only mit
Hinweis statt Absturz.

## D — Outbox → „Staged"-Fenster

Screen-Umbau (`OutboxScreen.tsx` → `StagedScreen.tsx`, Nav „Staged"):

- Gruppiert nach Komponente: Kopfzeile mit Local Name, SN, Thumbnail
  (bestehender Thumbnail-Index), Stage-Chip.
- Je Action: menschenlesbare Summary (`→ GLUED`, `GLUE_WEIGHT upload`),
  Status-Chip, `[Push to PDB]`, `[Discard]`.
- **Push** kettet die bestehenden Transitions draft→validated→approved→
  submitted über die vorhandene Transition-API; bricht beim ersten Fehler ab
  und zeigt ihn. Statusmaschine/Worker/ADR 001 unverändert.
- **Ehrlichkeit**: `submittable=false` (nicht-DUMMY) ⇒ kein Push-Knopf,
  stattdessen Hinweis „Production writes are not enabled — stays staged
  (dummy-only scope)".
- Aufklappbares Detail je Action: attempts, error, external_ref,
  Audit-Einträge.
- Terminale Actions (confirmed/cancelled) in einem eingeklappten
  „History"-Abschnitt, damit das Fenster ein Arbeitsvorrat bleibt.

## E — Triage → „Ingest log"

`TriageScreen.tsx` verliert Upload-Formular, JSON-Textarea und
Propose-Knöpfe. Bleibt: read-only Tabelle (Datei, Parser, Komponente als
Link auf die Detailseite, Status, uploaded_by, Zeit, Fehler) + bestehender
Dry-Run-Preview als Anzeige. Nav-Label „Ingest log". Kein API-Abbau —
nur die UI-Einstiege wandern auf die Modulseite.

## F — Auto-Mirror

„Sync" heißt ab jetzt immer: Komponenten **und** Evidence-Detail **und**
Attachments.

1. **Per Komponente**: `POST /api/components/{sn}/sync-evidence` lädt nach
   dem Evidence-Upsert automatisch alle Attachments
   (`download_attachments`); Antwort erweitert um Attachment-Zählung.
   Kein separater Download-Knopf mehr in der UI.
2. **Institutsweit**: neuer Job-Kind `evidence` im bestehenden
   `sync_jobs`-Rahmen (Lease, Fortschritt, Interrupt-Recovery): iteriert
   live Komponenten des Instituts; welche Komponententypen, bestimmt das
   Institutsprofil (`settings.evidence_component_types`, Default
   `["MODULE"]` — kein Hardcoding, Regel 4),
   je Komponente Detail-Fetch + Attachment-Downloads; Phasen
   `fetching/attachments/committing`; Zähler Komponenten/Läufe/Dateien.
   Ersetzt den synchronen `/api/sync/evidence/{institute}`-Pfad in der UI.
3. **Auto-Kette**: läuft ein Komponentensync-Job erfolgreich durch, stellt
   der Job-Manager automatisch einen Evidence-Job für dasselbe Institut ein
   (keine Nutzeraktion). Single-Flight-Lease verhindert Stapelbildung.
4. **Drei Quellen im Download** (`attachment_store`):
   - Binary-Store: wie validiert (`getTestRunAttachment` zuerst,
     HTML-Antworten verworfen).
   - EOS: Spiegel behält ab jetzt `type`/`url` der Attachment-Metadaten
     (`_attachment_summaries` erweitert). Bei `type=="eos"`: zum
     Download-Zeitpunkt frische vorsignierte URL via
     `getTestRun {…, noEosToken: false}` holen (URLs/Tokens laufen schnell
     ab — niemals cachen), dann `client.get(url)`; Bytes wie gehabt
     validieren.
   - CERNBox/Sync&Share-Links: URL-förmige Werte in Result-Feldern werden
     beim Evidence-Upsert erkannt (http(s)-Strings, auch in Arrays;
     Sentinel `"failed"` ignoriert) und als Attachment-Deskriptoren
     `source='share_link'` registriert (code = SHA-256 der URL); Download =
     unauthentifizierter GET mit denselben HTML-/Größen-Checks. Kein
     Zugangsdaten-Einsatz.
5. Fehlerbudget: jede Datei best effort (failed-Zähler), der Job läuft
   weiter; strict-503-Verhalten des Einzelkomponenten-Syncs bleibt.

pytest: Job-Verlauf mit Fakes (Fortschritt, Auto-Kette, Lease), EOS-Branch
(frische URL je Download, kein Token im Log/DB), Share-Link-Erkennung
(Arrays, Sentinel, HTML-Abwehr), Antwort-Erweiterung von sync-evidence.

## G — Doku (Regel 6)

- Neues ADR 006 „Staged-first UI + Auto-Mirror" (Entscheidung, Ehrlichkeits-
  regel fürs Staged-Fenster, drei Attachment-Quellen inkl. Sicherheits-
  begründung der Pfad-/HTML-Checks).
- [`docs/05`](../../05-ui-design-reference.md) (UI-Referenz): Modulseiten-Tabs,
  Staged-Fenster, Ingest-Log, Preferences-Panel.
- [`docs/10`](../../10-itk-domain-reference.md):
  CATEGORY_A/X/BOND_PULLING-Erklärung für ASIC-Bestände.
- [`docs/04`](../../04-roadmap.md) „Aktueller Stand" +
  [`docs/00-doc-map.md`](../../00-doc-map.md) (preview.py, test_type_schema,
  Job-Kind evidence).

## Etappen

1. **M1 Auto-Mirror-Backend**: Spiegel behält type/url; EOS- und
   Share-Link-Quellen; sync-evidence lädt Attachments mit; Job-Kind
   `evidence` + Auto-Kette. (Nur Backend + bestehende UI-Knöpfe.)
2. **M2 Preview + Ghost**: preview.py + Endpunkt; Tabs/Inline/Aus-Toggle;
   Account-Preferences-Panel.
3. **M3 Testerfassung**: component_sn-Pin im Ingest, Schema-Spiegel +
   Endpunkte, Dropzone, Formulargenerator.
4. **M4 Staged-Fenster + Ingest-Log + Doku**: Screen-Umbauten, ADR 006,
   docs/05, docs/10, Roadmap, Doc-Map.

Jede Etappe: Tests grün (pytest, tsc, Vite-Build), Verhalten einzeln
lauffähig, eigener Commit-Satz.

## H — Modul-Worksheet (Nachtrag 2026-08-26, vom Nutzer angefordert)

Befund nach M1–M4: Die Testliste der Detailseite rendert jeden Run voll
(Inline-Kurvenplots + komplettes Wertegitter) — bei >100 gespiegelten Läufen
ein unlesbarer Zahlen-Wall. Werte erfassen geht nur über die separate
Formular-Karte. Nutzerentscheid: **Spreadsheet-Modell** — pro Modul EINE
kompakte Tabelle (Zeile = Test), Werte inline sichtbar UND editierbar;
Änderungen werden gestaged (Ghost-Optik) und im Staged-Fenster approved.

### H1 — Worksheet-Payload (preview.py, kein neuer Endpunkt)

`build_component_preview` erhält zusätzlich `worksheet`:

```text
worksheet: { groups: [ {
  stage: str | null,        # null = Gruppe „Additional" (gespiegelte Typen
                            # außerhalb des Stage-Modells)
  reached: bool,            # Stage-Index <= aktueller Stage-Index
  rows: [ {
    test_type: str,
    status: passed|failed|missing|pending,   # Semantik wie checks
    latest: {                                # jüngster gespiegelter Run
      external_ref, measured_at, run_number, passed,
      scalars: [{code, name, value}],        # NUR Skalare; befüllte zuerst
      arrays:  [{code, name, points, kind}], # Umfang, NIE die Daten
      attachment_count: int
    } | null,
    staged: [{outbox_action_id, status}],    # offene upload_test_run-Actions
    run_count: int
  } ]
} ] }
```

Gruppen für JEDE Stage aus `model.order` (auch künftige — Spreadsheet-
Spaltengruppen), Requirements je Stage aus dem Institutsprofil; Kompaktheit
ist Payload-Vertrag: Arrays verlassen den Server nie als Rohdaten.
pytest: Gruppenbildung, latest-Auswahl, pending-Verzahnung, Additional-Gruppe.

**Am Echtbestand nachgeschärft (Probe gegen den TUDO-Spiegel, 2026-08-26,
Review-Nachzug).** Die ursprüngliche Messung verglich nur das kompakte
Worksheet gegen das damalige `tests[]` innerhalb derselben Preview
(Modul 20USEM50000064, 29 Läufe: 3 146 Byte Worksheet gegen 241 906 Byte
`tests[]`, Faktor 77). Der Review-Nachzug ging weiter, statt den Zahlen-Spam
nur wegzurechnen: `tests[]` verließ die Preview vollständig — es heißt jetzt
`projected.ghost_tests[]` und enthält ausschließlich offene, noch nicht
gepushte Uploads; rohe gespiegelte Läufe liefert nur noch `GET
/api/components/{sn}/tests`, lazy beim Öffnen von „All mirrored runs".
Gemessen mit demselben Serializer gegen den echten TUDO-Spiegel, komplette
Preview vorher/nachher: 20USEM50000064 (29 Läufe) 227 589 → 3 039 Byte
(−98,7 %); 20USEM50000063 129 916 → 3 916 Byte; 20USE5L0000031 63 307 →
5 444 Byte. Drei Regeln stammen aus der ursprünglichen Probe und gelten
unverändert:

- **Maps zählen wie Arrays.** Metrologie liefert Dict-Werte
  (`Hybrid glue thickness [um] = {'ABC_R5H1_0': …}`). Sie gehören nie in
  `scalars`, sondern in `arrays` mit `kind: "array"|"map"`; `points` ist bei
  Maps die Schlüsselzahl (UI: „⌁ 20 entries" statt „⌁ 40 pts"). Ohne diese
  Regel kippt eine einzige Metrologie-Zeile den Messblock zurück in die Zelle.
- **Befüllte Skalare zuerst** (stabile Partition, Nulls behalten ihre
  Reihenfolge am Ende). Sonst zeigt VISUAL_INSPECTION drei Mal „None",
  während die echten Werte hinter der 3er-Grenze liegen.
- **Stage außerhalb des Modells ⇒ `reached=True` für alle Gruppen.** Reale
  TUDO-Module stehen auf `FAILED`, das in keiner Stage-Order vorkommt; die
  Gegenregel hätte ein Modul mit 29 Läufen komplett als „noch nicht erreicht"
  ausgegraut. Wir wissen bei einer modellfremden Stage nicht, wie weit sie
  fortgeschritten ist — ehrlicher ist ein voll lesbares Sheet.

Offen (Domänenfrage an den Owner, kein Code-Bug): Der Pflichttest
`MODULE_IV_AMAC_TC` steht auf „missing", während `MODULE_IV_AMAC` mit 28
Läufen in „Additional" landet — das Seed-Stage-Profil verlangt einen Testtyp,
den TUDO real nicht so aufzeichnet.

### H2 — ModuleWorksheet.tsx (neu)

Eine Tabelle je Stage-Gruppe: Spalten Test | Values | Status | Date | ✎.
Values-Zelle: erste 3 Skalare (`Label Wert`), Rest als „+n", Arrays als Chip
(`⌁ 40 pts`). Ghost-Zeilen (offene Staged-Actions) in bestehender
`.ghost-row`-Optik mit Link ins Staged-Fenster. Zeile aufklappbar:
Voll-Detail (Kurven, Attachments, Conditions) über die aus `TestResults.tsx`
exportierten Renderer, Daten via `getComponentTests` (Filter external_ref).

**Edit-Strip**: ✎ (write-gated, ersetzt das Scroll-Ziel des 0.2.1-Ghost-
Stifts) klappt schema-getriebene Felder (TestForm-Generator) INNERHALB der
Zeile auf, vorbefüllt aus dem jüngsten Run; „Stage" nutzt exakt den
bestehenden Weg manual-entry-Ingest → Dry-Run → propose-outbox (409-Regeln
unverändert). Staging-Plumbing wird aus `AddTestResult.tsx` nach
`testStaging.ts` extrahiert und von beiden genutzt.

### H3 — Integration (ComponentsScreen)

Worksheet ersetzt Requirements-Tabelle + Run-Liste als Primäransicht in
allen drei Preview-Modi; die bisherige `TestResultsSection` wandert in ein
eingeklapptes „All mirrored runs" (Details-Element) darunter — nichts
entfällt, nichts spammt. Datei-Drop-Karte (`AddTestResult`) bleibt.

Reihenfolge wie gebaut: Aktionspanel (`StagedActionsPanel` bzw.
`StageSuggestionSection`) → Worksheet → Projektions-Hinweis → „All mirrored
runs" (eingeklappt, lazy) → `ImagesSection`. `ProjectedChecksSection`
entfällt; ihre Status inklusive `pending` trägt jetzt das Worksheet.

**Korrektur zur Vorgabe (bewusst übernommen):** Das Worksheet mountet in
JEDEM Staged-Preview-Modus, auch `off`. Der Schalter aus §B steuert die
Ghost-/Projektionsebene, nicht die Existenz der Datentabelle — das Worksheet
ist die normale Modulansicht, kein Vorschau-Feature. Kein Mehrverkehr: der
Preview-Endpunkt wurde ohnehin schon in jedem Modus geladen. §B bleibt
ansonsten unverändert gültig (`off` = keine Ghost-Projektion).

Dateibesitz (parallele Agenten): Backend preview.py/schemas.py/Tests ·
Agent A ModuleWorksheet.tsx, testStaging.ts, AddTestResult.tsx (Extraktion),
api.ts, i18n.ts, app.css · Agent B ComponentsScreen.tsx, TestResults.tsx.

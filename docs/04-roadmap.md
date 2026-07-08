# Living Roadmap: itkFlow

> Dieses Dokument ist der aktive Ausfuehrungsfahrplan. `docs/02-revamp-plan.md`
> beschreibt die Produktvision und Architektur; diese Roadmap beschreibt, was
> als Naechstes gebaut, stabilisiert und abgenommen werden soll.

## Agenten-Regel

Jeder Agent liest vor groesserer Planung oder Implementierung `CLAUDE.md` und
dieses Dokument. Arbeit wird dem naechsten passenden Meilenstein zugeordnet.
Wenn ein Agent Roadmap-Arbeit erledigt, neu zuschneidet oder blockiert, muss er
entweder diese Roadmap aktualisieren oder im Abschluss klar notieren, welcher
Roadmap-Punkt betroffen ist und warum keine Aktualisierung erfolgt ist.

UI-Arbeit folgt zusaetzlich der verbindlichen Design-Referenz
`docs/05-ui-design-reference.md` (+ Mockup `docs/itkflow-ui-mockup.html`), damit
die Umsetzung nicht vom Design-Ziel abdriftet.

## Aktueller Stand (2026-07-08)

- Monorepo steht mit `backend/`, `frontend/`, `agent/`, `deploy/`, CI- und
  Docker-Grundstruktur.
- Harte Sicherheitsregeln sind dokumentiert: keine produktive PDB in Dev/Tests,
  `references/zeuthenflow` nur lesen, keine Secrets, kein Institut-Hardcoding.
- Backend-Basis: FastAPI-App, SQLAlchemy-Modelle fuer Institute, Komponenten,
  Outbox und Audit; Pydantic-Schemas; Health-, Institute-, Component-, Outbox-
  und Audit-Endpunkte; Outbox-Statusvertrag als Backend-Quelle der Wahrheit.
- Read-only PDB-Mirror ist im Aufbau: Komponentensync, PDB-Testinstanz-Gateway,
  Mapping von PDB-Komponenten in lokale Mirror-Records, Demo-Fixtures und ein
  API-Endpunkt zum Starten eines Institute-Komponentensyncs.
- Frontend-Basis: Vite/React-Shell mit Navigation, Health-Anzeige,
  Komponentenliste mit Such-/Scan-Ergonomie, Detail-/Familienansicht und
  Institute-Sync-Control, Outbox-Screen mit Statusuebergaengen/Demo-Fallback
  und Dashboard-Summary.
- Ingestion-Basis: lokale Inbox fuer Instrument-JSONs mit Hash, Auditspur und
  Triage-UI; erkannte Dateien koennen einen `upload_test_run`-Draft mit
  `dry_run_required` in der Outbox vorschlagen, aber noch keine PDB-Writes.
- Ingestion-Parser: Registry in `app/ingestion.py` (`glue-weight-v1`,
  `iv-curve-v1`, `pull-test-v1`, `pdb-test-run-v1`, generischer Fallback)
  normalisiert Payloads zu einem Preview mit blockierenden Issues und
  Warnungen; lokale Namen im `component`-Feld werden gegen den Mirror
  aufgeloest. Testtyp-spezifische Dry-Run-Checks fangen abgeschnittene
  Instrument-Ausgaben (gepaarte VOLTAGE/CURRENT- bzw.
  PULL_STRENGTH/PULL_GRADE-Arrays, NUMBER_WIRES-Abgleich). `GET
  /api/ingest/files/{id}/preview` liefert den Dry-Run (auch im Triage-UI),
  und `propose-outbox` blockt bei Dry-Run-Issues mit 409.
- Stage-Move-Suggestion-Engine (Phase-3-Kickoff): reine Domain-Logik in
  `app/domain/stages.py` (Pflicht-Tests je Stage, institutsneutral via
  `InstituteProfile.settings`, Seed-Default aus der UI-Design-Referenz).
  `GET /api/components/{sn}/stage-suggestion` wertet bestaetigte Uploads
  (confirmed `upload_test_run`) zu passed/failed/missing aus und schlaegt den
  naechsten Stage-Move vor, wenn alle Pflicht-Tests der aktuellen Stage passen.
  Das Detail-UI zeigt die Pflicht-Tests-Tabelle + Vorschlag-Callout, und
  „Propose stage move" legt einen auditierten `stage_move`-Draft in die Outbox.
- Async-Outbox-Worker: eigenstaendiger Prozess (`app/run_worker.py`,
  `worker`-Service in Compose) beansprucht `approved`/`submitted`-Aktionen,
  wiederholt den Dry-Run gegen den aktuellen Mirror, ruft einen injizierten
  Submitter und setzt `confirmed` (mit `external_ref`) oder `failed`. Realer
  Submitter schreibt `uploadTestRunResults` gegen die Testinstanz, ist ohne
  Access-Codes inaktiv. Idempotenz ueber `external_ref`. Details: ADR 002.
- Watched-Folder-Agent ist bisher nur als Phase-2-Platzhalter dokumentiert.

## Naechste Arbeitspakete

1. **Stage-Move-Strecke schliessen** (`domain-modeler`, `backend-dev`,
   `pdb-gateway-dev`): Die Suggestion-Engine + `stage_move`-Draft stehen
   (2026-07-08). Offen: realer Submitter fuer `stage_move` im Outbox-Worker
   (PDB-Stage-Move via itkdb, Testinstanz), und die „satisfied tests"-Quelle
   perspektivisch aus einem PDB-Test-Run-Mirror statt nur aus confirmed
   itkFlow-Uploads speisen (fuer Parallelbetrieb mit zFlow).
2. **Dashboard ausbauen** (`frontend-dev`, `backend-dev`): Summary um offene
   Tests, Sync-Alter und auffaellige Stage-/Outbox-Zustaende erweitern.
3. **Outbox-Worker haerten** (`backend-dev`, `pdb-gateway-dev`, `qa-engineer`):
   Async-Worker steht (2026-07-08, ADR 002). Offen: automatischer Retry mit
   Backoff fuer transiente Fehler, `worker_max_attempts` durchsetzen, und die
   reale Idempotenz-Pruefung gegen die Testinstanz, bevor der
   `submitted`-Recovery-Pfad mit echten Tokens scharf geschaltet wird.
4. **Upload-Converter und Worker-Schnitt** (`ingestion-dev`, `architect`,
   `backend-dev`): Registry, Preview und Dry-Run-Gate stehen inkl. Glue-Weight-,
   IV-, Pulltest- und generischem Parser (2026-07-08). Als Naechstes den
   Uebergang `ParsedTestRun` → PDB-Uploadcall im Outbox-Worker definieren
   (Wer submittet? Wie wird der Dry-Run vor dem echten Upload wiederholt?),
   plus optional Metrologie-Rohformat-Parser.
5. **Sandbox-Sync validieren** (`pdb-gateway-dev`, `qa-engineer`): markierten
   PDB-Testinstanz-Check fuer `listComponents` mit echten Sandbox-Tokens laufen
   lassen und dokumentieren, welche Filter pro Institute-Profil noetig sind.

## Geplant (Design steht, Umsetzung nach Freigabe)

Drei durchdachte, aber noch nicht gebaute Erweiterungen. Details im jeweiligen
Dokument:

- **Nutzer, Rollen & Audit-Zuordnung** — `docs/06-users-roles-audit.md`. Echte
  Konten (admin/operator/viewer), Institut nur durch Admin, serverseitige
  `user_id`-Zuordnung statt client-gelieferter Actor-Strings. Empfehlung: lokale
  Accounts fuer v1, OIDC/CERN-SSO als spaeterer Adapter. **Fundament fuer echte
  Nachvollziehbarkeit — sollte vor Remote-Zugriff stehen.**
- **Jig-/Tool-Registry + typ-gefilterter Quick-Select** —
  `docs/07-jig-tool-quickselect.md`. Jigs/Tools/Glue-Batches im Assembly-Wizard
  nach Modultyp vorfiltern statt per Hand eintippen; Kompatibilitaet als
  Config/Registry (Regel #4). Phase 3/4.
- **Remote-Zugriff / Tunneling** — `docs/08-remote-access.md`. Zugriff von
  zuhause; Empfehlung Tailscale/WireGuard (spaeter Cloudflare Tunnel).
  **Abhaengigkeit:** erst nach dem Auth-Fundament scharf schalten.

## Meilensteine

### Phase 0 - Fundament stabilisieren

**Ziel:** Ein sicherer, reproduzierbarer Entwicklungsstand, auf dem alle
weiteren Features ohne PDB-Produktionsrisiko entstehen.

**Epics:**

- Dev- und CI-Kommandos dokumentieren und gruene Offline-Tests erhalten.
- PDB-Testinstanz als einzigen vorkonfigurierten Remote-Zielpunkt absichern.
- Institute-Profil, Component-Mirror, Outbox und Audit als Kernmodell
  konsolidieren.
- Agentenvertrag und Roadmap-Pflege verbindlich in Repo-Dokumente schreiben.

**Done-Kriterien:**

- Standardtestlauf braucht keine PDB-Tokens und keine Netzwerkverbindung.
- Jede PDB-nahe Arbeit ist entweder gemockt oder als Sandbox-Test markiert.
- Neue Agenten finden `CLAUDE.md` und diese Roadmap ohne Rueckfrage.
- Kein neuer Code hardcodiert Institutscodes, lokale Prefixe oder PDB-IDs.

**Owner-Agenten:** `architect`, `backend-dev`, `pdb-gateway-dev`,
`qa-engineer`, `docs-writer`.

**Abhaengigkeiten:** Zugriff auf PDB-Testinstanz nur fuer markierte
Integrationschecks; anonymisierte Referenz bleibt read-only.

### Phase 1 - Read-only-Cockpit

**Ziel:** itkFlow liefert taeglichen Nutzen ohne PDB-Schreibrisiko:
Komponenten suchen, Status verstehen, Familien sehen, Dashboards lesen.

**Epics:**

- Komponenten-/Test-/Shipment-Sync aus der PDB-Testinstanz in lokale
  Mirror-Tabellen.
- Komponentenbrowser mit Scanner-first-Suche, Filtern, Detailseite und
  Familienbaum.
- Erste Dashboards fuer Durchsatz, offene Tests, Stage-Verteilung und
  auffaellige Abweichungen.
- Reconciliation-Report zwischen lokalem Mirror, erwarteten Workflowdaten und
  zFlow/PDB-Zustand vorbereiten.

**Done-Kriterien:**

- Ein Institut kann einen Read-only-Sync starten und danach Komponenten ohne
  Netzwerk-Latenz durchsuchen.
- Detailseiten zeigen Parent/Children, Stage, Typ, Location, lokale Namen und
  Sync-Zeitpunkt verlaesslich.
- UI bleibt produkt-facing Englisch und i18n-faehig; interne Planungsdoku
  bleibt Deutsch.
- Keine PDB-Schreiboperation existiert ausserhalb der Outbox-Grenze.

**Owner-Agenten:** `pdb-gateway-dev`, `backend-dev`, `frontend-dev`,
`qa-engineer`.

**Abhaengigkeiten:** Stabile Component-Mirror-Semantik aus Phase 0; genuegend
anonymisierte Demo-/Testdaten.

### Phase 2 - Test-Ingestion und Upload-Queue

**Ziel:** Instrument-JSONs landen nachvollziehbar in itkFlow, werden
serverseitig geparst, validiert, triagiert und als gepruefte Outbox-Aktion fuer
die PDB vorbereitet.

**Epics:**

- Inbox-Modell fuer Dateien, Parserstatus, erkannte Komponente und Testtyp.
- Parser-Plugins fuer die wichtigsten Testtypen mit anonymisierten Fixtures.
- Watched-Folder-Agent als duenner Client: beobachten, hochladen, Status
  melden; kein Fachparsing auf Instrument-PCs.
- Triage-UI mit Vorschau, Validierungsfehlern, Pass/Fail-Signalen und
  Freigabe in die Outbox.
- Outbox-Dry-Run, Review/Audit und Retry-Regeln fuer Test-Uploads.

**Done-Kriterien:**

- Parser laufen deterministisch gegen Fixture-Sets und schreiben keine PDB.
- Jede Upload-Absicht wird als Outbox-Aktion mit Auditspur erzeugt.
- Operatoren koennen fehlerhafte Dateien korrigieren, zurueckstellen oder
  begruendet verwerfen.
- Netzwerk- und PDB-Ausfaelle verlieren keine Dateien und erzeugen sichtbare
  Statusmeldungen.

**Owner-Agenten:** `ingestion-dev`, `backend-dev`, `frontend-dev`,
`qa-engineer`, `code-reviewer`.

**Abhaengigkeiten:** Outbox-Kontrakt aus Phase 0/1; Fixture-Inventar aus
`references/zeuthenflow` nur lesend.

### Phase 3 - Assembly-Workflows

**Ziel:** Registrierung, Assemblierung und Stage-Vorschlaege ersetzen die
fehleranfaelligen Sheet-Pfade schrittweise, waehrend zFlow parallel weiter
abgeglichen wird.

**Epics:**

- Wizards fuer Hybrid- und Modul-Bau mit Scanner-first Eingaben.
- Registrierung/Assemblierung als validierte Outbox-Aktionen mit Preview.
- Attachment-Properties fuer Jigs, Pickup-Tools, Glue-Samples und Panels.
- Stage-Vorschlaege aus PDB-Stages, Pflichttests und Institute-Profil.
- Taeglicher Abgleichreport fuer Parallelbetrieb und Cutover-Vorbereitung.

**Done-Kriterien:**

- Keine direkte PDB-Schreibroute aus Request-Handlern oder UI-Actions.
- Coordinator kann Vorschlaege pruefen, bestaetigen oder begruendet ablehnen.
- Workflows enthalten keine hartcodierten DESY/Zeuthen-Spezifika.
- Parallelbetrieb zeigt Abweichungen zwischen zFlow, PDB und itkFlow sichtbar an.

**Owner-Agenten:** `architect`, `domain-modeler`, `backend-dev`,
`frontend-dev`, `pdb-gateway-dev`, `qa-engineer`.

**Abhaengigkeiten:** Read-only Mirror und Outbox aus Phase 1/2; validierte
Stage-/Test-Mappings im Institute-Profil.

### Phase 4 - Logistik und Betrieb

**Ziel:** Operative Nebenprozesse wandern aus Sheets/Skripten in nachvollziehbare
itkFlow-Module.

**Epics:**

- Shipments mit Empfangspruefung, Checklisten und PDB-Abgleich.
- Glue-Batch-Registry mit Topfzeit, Verbrauch, Warnungen und PDB-Bezug.
- Tool-/Jig-Registry inklusive RFID-Mapping und Blacklist/Flag-Verwaltung.
- Reminder und Notification-Adapter fuer E-Mail, Mattermost/Telegram oder
  institutspezifische Kanaele.
- Health-/Betriebsansicht fuer Sync, Outbox, Agenten und Parser.

**Done-Kriterien:**

- Operative Aktionen sind auditiert und rollenfaehig.
- Reminder/Notifications sind konfigurierbar und nicht institutsspezifisch im
  Code verdrahtet.
- Glue-/Tool-/Shipment-Daten sind mit Komponenten und Outbox-Aktionen
  verknuepfbar.

**Owner-Agenten:** `backend-dev`, `frontend-dev`, `domain-modeler`, `devops`,
`qa-engineer`.

**Abhaengigkeiten:** Institute-Profil-Konfiguration; Auth/Rollenmodell.

### Phase 5 - Visual Inspection und Kollaboration

**Ziel:** VI-Bilder, Annotationen, Berichte und externe Leseansichten ersetzen
CERNBox-HTML und manuelle Share-Flows.

**Epics:**

- Bild-/Anhangspeicher ueber lokales Dateisystem oder S3-kompatiblen Store.
- VI-Galerie mit Defekt-Annotation und komponentenbezogener Historie.
- Bericht-/Export-Generierung fuer Koordinatoren und Review-Runden.
- Read-only Share-Links mit Ablauf, Audit und Zugriffsbeschraenkung.

**Done-Kriterien:**

- Rohbilder, Annotationen und PDB-relevante JSONs bleiben nachvollziehbar
  verknuepft.
- Externe Links geben nur freigegebene, read-only Inhalte preis.
- Speicherbackend ist deploybar ohne CERN-spezifische Dienste.

**Owner-Agenten:** `frontend-dev`, `backend-dev`, `devops`, `docs-writer`,
`qa-engineer`.

**Abhaengigkeiten:** Objektstore-/Dateisystem-Entscheidung; Auth/Share-Link
Policy.

### Phase 6 - Multi-Institut-Haertung und v1.0

**Ziel:** Ein zweites Institut kann itkFlow mit minimaler Sonderarbeit pilotieren;
v1.0 ist installierbar, dokumentiert und betreibbar.

**Epics:**

- Onboarding-Assistent "neues Institut in 30 Minuten".
- Mandantentrennung, Rollen, Token-Ablage und Audit fuer mehrere Institute.
- Beispielprofile fuer Endcap/Barrel und konfigurierbare Workflows.
- i18n-Grundlage fuer EN/DE, mit Englisch als Produkt-Default.
- Release-/Upgrade-Doku, Backup/Restore, Monitoring und Pilot-Checkliste.

**Done-Kriterien:**

- Neues Institut braucht keine Codeaenderung fuer Namensschema, Workflows,
  Stage-/Test-Mappings oder Notifications.
- Deployment funktioniert per dokumentiertem `docker compose up`.
- v1.0-Pilot hat dokumentierte Akzeptanzkriterien, bekannte Risiken und
  Rollback-Pfad.

**Owner-Agenten:** `architect`, `devops`, `docs-writer`, `backend-dev`,
`frontend-dev`, `qa-engineer`.

**Abhaengigkeiten:** Reife Phase-1-bis-5-Workflows; echte Pilot-Rueckmeldungen.

## Pflege

- Diese Roadmap wird aktualisiert, wenn sich Reihenfolge, Scope oder
  Done-Kriterien eines Meilensteins aendern.
- Abgeschlossene Punkte werden nicht geloescht, sondern kurz als erledigt oder
  ersetzt markiert, sobald ein entsprechender Arbeitsabschnitt committet ist.
- Neue Ideen gehoeren zuerst in den passenden Meilenstein oder in
  `docs/02-revamp-plan.md`, falls sie die Produktvision statt die Ausfuehrung
  betreffen.

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

## Aktueller Stand (2026-08-26)

- Monorepo steht mit `backend/`, `frontend/`, `agent/`, `deploy/`, CI- und
  Docker-Grundstruktur.
- **Evidence-Umfang erweitert (2026-08-26):** Der Sweep deckt jetzt alle
  Baugruppentypen mit echten Testlaeufen ab (Module, Sensoren, Hybride,
  Flexes, Powerboard-Flex, HV-Tab-Sheets — per PDB-Stichprobe bestimmt) und
  beruecksichtigt auch Komponenten, die **hier stehen, aber anderen
  Instituten gehoeren** (bei TUDO die Mehrheit). Chips (ABC/HCC/AMAC) bleiben
  optional. Details docs/09.
- **Messwert-Statistik auf der Statistics-Seite (2026-08-26):** Neue Endpunkte
  `GET /api/stats/measurements/dimensions` und `GET /api/stats/measurements`
  (`app/measurement_stats.py`) aggregieren die gespiegelten Testlauf-Messwerte
  eines Instituts: Array-Ergebnisse als ueberlagerte Kurven (alle IV-Kurven in
  einem Chart, gepaart gegen ein waehlbares X-Result), skalare Ergebnisse als
  Verteilung mit Kennzahlen. Testtypen und Result-Codes werden aus den Daten
  entdeckt, nie hartkodiert. UI: `Measurements`-Block im StatisticsScreen mit
  Inline-SVG (Pass/Fail zusaetzlich ueber Strichelung kodiert, Palette gegen
  Hell/Dunkel validiert). Details docs/05 §5b.
- **Staged-Preview-Preference wirkt sofort (2026-08-26, Bugfix):** Die
  Account-Einstellung `Staged preview: Tabs|Inline|Off` wurde nur beim Mount
  gelesen — der Staged-Tab schien nach dem Umschalten „verschwunden", bis man
  neu lud. `stagedPreview.ts` benachrichtigt jetzt Abonnenten im selben Tab
  (`storage`-Events feuern nur in anderen Tabs).
- **Desktop kann Outbox-Aktionen wirklich pushen (2026-08-26):** Das Bundle
  laeuft als ein Prozess und startete keinen Outbox-Worker — eine in der UI
  gepushte Aktion erreichte `submitted` und blieb dort fuer immer liegen, sah
  aber gepusht aus. Neu: `ITKFLOW_OUTBOX_PROCESSOR` (`worker` Default, Desktop
  `app`) und `app/outbox_processor.py` draenen die Outbox im API-Prozess.
  Sicherheitsmodell unveraendert: keine deployment-weiten Credentials,
  Approval-Identitaet, `dummy_only`. Details docs/11.
- **Sync-Datenverlust behoben (2026-08-26, gegen echte TUDO-Daten verifiziert):**
  Zwei unabhaengige Fehler liessen die App unvollstaendig aussehen.
  (1) `useOrInLocationSearch` blaettert inkonsistent: 3799 gemeldete
  Komponenten, 3799 Zeilen, aber nur 2539 verschiedene — ~1260 fehlten, darunter
  **alle 92 Jigs/Tools**, weshalb die Tool-Registry leer blieb. Der Fetch stellt
  jetzt zwei getrennte Abfragen (owned / located) und fuehrt sie lokal zusammen:
  3044 Komponenten, 0 Dubletten, 92 Tools. Zusaetzlich bricht eine
  Dublettenpruefung einen lueckenhaften Sync ab, statt ihn zu verschweigen.
  (2) Der Evidence-Sweep committete erst ganz am Ende; ein geschlossenes
  App-Fenster verwarf die komplette Arbeit (real: 29/262 Komponenten, danach
  `test_run_evidence` = 0 Zeilen → alle Pflichttests „missing"). Jetzt
  committet jede Komponente einzeln. Details docs/09.
- **Sync ueberlebt kurze Internet-Ausfaelle (2026-08-26):** Drei Luecken
  machten aus einer Funkloch-Minute dauerhaften Verlust. (1)
  Attachment-Downloads hatten gar keinen Retry — ein realer Sweep endete mit
  `attachments_failed=11` von 363. Transiente Fehler (DNS, Connection Reset,
  TLS-Handshake-Timeout, 408/425/429, 5xx) werden jetzt mit exponentiellem
  Backoff bis `ITKFLOW_SYNC_PAGE_MAX_ATTEMPTS` wiederholt, permanente (4xx,
  HTML-Fehlerseite, zu grosser Body) scheitern sofort; ein Fehlschlag wird nie
  als gespeichert vermerkt und deshalb im naechsten Sweep automatisch
  nachgeholt. (2) Ein transient gescheiterter Sync-Job blieb bis zum
  Menschen-Klick liegen — er plant jetzt **genau einen** automatischen
  Wiederholungslauf nach 60 s; die Obergrenze steckt im dauerhaften
  `requested_by`-Marker „automatic retry (…)", sodass die Kette auch ueber
  Neustarts hinweg bei Original + ein Retry endet. Der Retry laeuft durch die
  normale Lease-Akquise und konvergiert auf einen bereits vorhandenen Job;
  nicht-transiente Fehler (Credentials, Bugs) bekommen keinen. (3) Eine
  Zombie-Lease nach Crash-plus-Sofortneustart blockierte den Single-Flight
  dauerhaft, weil Startup-Recovery ihren frischen Heartbeat sah; die
  Lease-Akquise uebernimmt sie jetzt nach derselben Drei-Minuten-Regel.
  Zusaetzlich schreiben Evidence-Retry und Download-Phase Heartbeats, damit
  eine lange Retry-Leiter nicht als verwaist gilt. Nebenbefund und mitgefixt:
  oeffentliche CERNBox-/Sync&Share-Attachments (Visual Inspection) wurden nie
  gespiegelt, weil der Mirror die HTML-Betrachterseite statt der Datei anfragte
  — jetzt ueber `remote.php/dav/public-files/<token>` bzw. `/s/<token>/download`.
  Details docs/09.
- **Sync: inkrementeller Evidence-Sweep + konfigurierbares Retry-Budget
  (2026-08-26):** Der Institutssweep vergleicht pro Testlauf einen
  Flat-Fingerprint gegen den Mirror und holt `getTestRun`-Detail nur noch fuer
  neue/veraenderte Laeufe (Marker `detail_synced`; Wiederholungs-Sync ~1
  Request pro Komponente statt pro Lauf; Einzelkomponenten-Sync bleibt voller
  Fetch). Seiten-Retries beim Komponenten-Sync sind konfigurierbar
  (`ITKFLOW_SYNC_PAGE_MAX_ATTEMPTS`, Default 3). Details docs/09.
- **PDB: Offline-Default statt toter Testinstanz (2026-08-26):**
  `pdb_instance` kennt nur noch `offline` (Code-Default, erreicht nichts) und
  `production`; `pdb_test_api_url` und die unicorncollege-URLs sind gestrichen.
  Desktop-Bundle und Compose aktivieren Produktions-**Reads** ab Werk
  (Owner-Entscheidung; Env gewinnt weiterhin, Writes bleiben `dummy_only`,
  Traffic erst mit persoenlichen Codes). Der Account-Screen zeigt fuer eine
  Offline-Instanz die ehrliche Server-Meldung statt „check your network".
  Harte Regel 2 in CLAUDE.md neu gefasst; Details docs/09 + ADR-003-Ergänzung.
- **Logistik & Betrieb (Phase-4-Kickoff, 2026-08-26):** Die drei
  Phase-4-Kernmodule sind implementiert (Vertrag/Details:
  `docs/11-logistics-operations.md`): **Glue-Batch-Registry** (lokale Batches
  mit Lebenszyklus new→in_use→expired/empty, Topfzeit-Timer ab `mixed_at` mit
  Profil-Default `glue_pot_life_minutes[glue_type]`, Verbrauchslog je
  Komponente, Scan nach PDB-SN/Batch-Nr.; keine PDB-Registrierung von GLUE —
  nur Referenz); **Shipment-Mirror + Empfangspruefung** (read-only Sync ueber
  `listShipmentsByInstitution` in beide Richtungen + `listShipmentItems`,
  Dedupe per Id, 503 statt Null-Erfolg; lokal fuehrende `reception_*`-Felder
  mit Checklisten-Template aus `shipment_reception_checklist`, die kein
  Re-Sync ueberschreibt); **Reminder + Notification-Adapter**
  (`once|daily|weekly|monthly` mit Catch-up, Feuern im Worker-Poll-Loop;
  Kanaele als `notification_channels` im Institutsprofil — Mattermost-/
  generischer Webhook via stdlib-urllib, Webhook-URLs werden in allen
  API-Antworten als `***` maskiert und tauchen nie in Fehlern/Logs auf;
  kanallose Reminder feuern nur ins Audit). Drei neue Screens (Glue Batches,
  Shipments, Reminders) ersetzen die P4-Platzhalter in der Rail. Als dritter
  Kanaltyp kam **Telegram** dazu (eigener `kind`, weil Telegram `chat_id` im
  Body braucht und die generische Webhook-Form ignoriert; Bot-Token steckt in
  der URL und faellt damit unter dieselbe Maskierung) — der Alt-Kanal des
  zFlow ist damit abgedeckt. Der Assembly-Wizard-Quick-Select ist inzwischen
  umgesetzt; offen bleiben E-Mail/SMTP-Adapter und Eskalation
  (docs/11 „Remaining Phase 4 scope").
- **Shipment -> Reception Tests (Phase 4, 2026-08-26):** Das je Institut
  gepflegte `shipment_reception_tests`-Mapping ordnet Komponententypen ihre
  erforderlichen Testtypen zu. Shipment-Responses projizieren je Item und
  aggregiert `missing|pending|passed|failed` aus lokalem `TestRunEvidence` und
  `upload_test_run`-Actions; pending gilt ausdruecklich nicht als bestanden.
  Fehlende/fehlgeschlagene Nachweise verlinken in die auf SN und exakten
  Testtyp gepinnte Testerfassung. `done` wird serverseitig bis zum Pass aller
  konfigurierten Nachweise blockiert. Nur Admins koennen mit explizitem Grund
  uebersteuern; dafuer entsteht ein eigenes Audit-Event. Die UI weist getrennt
  aus, ob ein DUMMY spaeter gepusht werden darf oder ein Produktionsbauteil nur
  staged bleibt. Mapping, Projektion, Re-Sync-Erhalt, Rollen/Scope, Gate,
  Deep-Link und strukturierte Settings sind offline getestet; kein Testpfad
  ruft die Live-PDB auf.
- **Reminder feuern in jeder Deployment-Form (2026-08-26, Nachzug):** Der erste
  Wurf haengte das Ticken allein am Outbox-Worker — den es weder im
  Desktop-Bundle (ein einziger Prozess) noch beim Dev-Launcher gibt. Ein
  geplanter Reminder waere dort **nie** gefeuert. `ITKFLOW_REMINDER_SCHEDULER`
  (`worker` = Default/Compose, `app`, `off`) waehlt jetzt den tickenden
  Prozess; `create_app` startet dafuer einen `ReminderScheduler` als
  Hintergrund-Task (Tick im Worker-Thread, da DB und Webhook blockieren),
  Desktop-Bundle und `start-itkflow.ps1` setzen `app`. Zustellung ist dabei
  **at most once**: eine Faelligkeit wird per guarded UPDATE in eigener
  Transaktion beansprucht, bevor gesendet wird — zwei Scheduler koennen
  denselben Termin nicht doppelt verschicken. Reminder bleiben PDB-inert.
- **Operations Health (Phase 4, 2026-08-26):** Persistente Heartbeats fuer
  Outbox-Worker und Reminder-Scheduler sowie `GET /api/ops/health` aggregieren
  ausschliesslich lokale Telemetrie: aktive/letzte Sync-Jobs, Staged-Backlog,
  Fehler und Retry-Limit, offene Reminder-Tasks und Parser-/Triage-Probleme.
  Der admin-only Screen zeigt Fresh/Stale/Missing textuell, ist fuer
  Institutsadmins mandantengefiltert und verlinkt nach Staged, Ingest log und
  Reminders. Kein Refresh fuehrt einen Live-PDB-Aufruf aus.
- **First-Run-Setup in der UI (2026-08-25):** `GET /api/setup` +
  `POST /api/setup/admin` legen den allerersten Admin ohne CLI an (nur solange
  die User-Tabelle leer ist, danach dauerhaft 409; AuditEvent
  `setup.admin_created`, Auto-Login). Frontend zeigt dafuer den `SetupScreen`
  (Auth-Status `setup`). Der `create_admin`-Schritt entfaellt fuer Desktop wie
  Compose (docs/06, deploy/README). Ausserdem baut `npm run build` in
  `desktop/` jetzt die komplette Tauri-App in einem Schritt:
  `build-sidecar.py --bundle` haengt `tauri build --target <host triple>` an,
  womit das Triple-Problem aus ADR 005 automatisch geloest ist.
- **Desktop-Paketierung (2026-08-25):** `desktop/` enthaelt eine Tauri-Shell,
  die den als PyInstaller-Onefile gepackten Backend-Sidecar startet, auf
  `/health` wartet und den Webview darauf zeigt. Das Backend kann die gebaute
  SPA selbst ausliefern (`app/static_spa.py`, Setting `static_dir`), damit UI
  und API auf einer Origin liegen und Session-Cookie/CSRF unveraendert
  funktionieren. Zustand (DB, Credential-Key, Logs) liegt im
  Anwendungsdatenverzeichnis, dasselbe wie beim Windows-Launcher. Die
  PDB-Defaults bleiben unangetastet (test / kein Produktions-Opt-in /
  `dummy_only`). Details: `docs/adr/005-desktop-packaging.md`.
- **PDB-Request-Timeout griff nie (2026-08-25, Bugfix):** `requests` waehlt den
  Adapter mit dem *laengsten* Prefix, und itkdb mountet einen eigenen fuer die
  PDB-Basis-URL. Der generische `https://`-Adapter war damit fuer jeden echten
  API-Call verschattet — Reads liefen unbegrenzt. Ein haengender Request hat
  reproduzierbar den Evidence-Sync bei 60/263 Komponenten eingefroren.
  `app/pdb_gateway.py` bindet den Timeout jetzt an *jeden* gemounteten Adapter
  (Instanz-Wrapping, damit itkdbs Cache erhalten bleibt). Danach lief derselbe
  Sync in 97 s durch: 713 Testlaeufe ueber 222 Module.
- **Testlauf-Detail statt nur pass/fail (2026-08-25):** `fetch_test_run_evidence`
  kennt jetzt `with_detail` und spiegelt Messwerte, Properties und
  Attachment-Metadaten (`getTestRun` pro Lauf). Der Institutssweep bleibt
  flach/billig, die Einzelkomponente holt Detail. Damit stehen Klebegewichte,
  Metrologie und IV-Kurven lokal zur Verfuegung; neue Endpunkte
  `GET /api/components/{sn}/tests` und `GET /api/components/thumbnails`.
- **Attachments lokal (2026-08-25):** `app/attachment_store.py` spiegelt
  Bilder/Plots in einen Ordner (`attachment_dir`), ein Verzeichnis je
  Seriennummer. PDB-Dateinamen wandern nie in einen Pfad; gespeichert wird
  unter dem Attachment-Code plus Extension aus einer Allowlist. Die UI zeigt
  Messwerte, IV-Kurven und Thumbnails (Detailseite und Komponentenliste).
- **`sync-evidence` antwortet 503 statt „0 gespiegelt" (2026-08-25):** eine
  nicht erreichbare PDB sah bisher aus wie „diese Komponente hat keine Tests" —
  genau die Verwechslung, die eine ganze Instituts-Ansicht wie lauter fehlende
  Pflichttests aussehen laesst.
- **Staged-first + Auto-Mirror (ADR 006, M1–M4 umgesetzt,
  2026-08-26):** Der zusammenhaengende Produktschnitt liegt im Arbeitsbaum;
  die abschliessende gemeinsame Regression und Abnahme laeuft getrennt davon.

  - **M1 Auto-Mirror:** Binary-Store, EOS mit frisch bezogener URL und
    credential-freie Share-Links verwenden denselben abgesicherten lokalen
    Attachment-Store. Nach einem erfolgreichen persistenten Komponentenjob
    startet automatisch ein ebenfalls persistenter Evidence-/Attachment-Job.
    Topbar und Components-Screen verfolgen beide Jobs ueber Navigation und
    Reload hinweg. Detailgalerie, Testlaufkarten und Thumbnails lesen nur noch
    lokal gespiegelte Dateien; Metrologie-Bilder brauchen deshalb nach dem
    Mirror keinen direkten PDB-/EOS-Zugriff mehr.
  - **M2 Preview + Ghost:** `GET /api/components/{sn}/preview` projiziert den
    aktuellen Mirror mit offenen Actions serverseitig. Die Detailseite bietet
    `Current`/`Staged`-Tabs, Inline- oder Off-Modus; die browserlokale
    Preference aendert weder Status noch Berechtigung. Ghost-Tests zeigen ihre
    servergebundene Ingest-Evidenz inklusive lokaler Attachments und zaehlen
    bis zur Bestaetigung nur als `pending`.
  - **M3 Testerfassung:** `GET /api/test-types` und
    `POST /api/test-types/sync` spiegeln Testtyp-Schemata read-only ueber die
    persoenliche PDB-Verbindung. `Add test result` auf der
    Komponentendetailseite bietet Datei-Drop sowie ein schemaerzeugtes Formular;
    beide erzeugen einen an `component_sn` gepinnten `IngestFile`, durchlaufen
    denselben Dry-Run und legen erst danach eine Staged-Action an. Abweichende
    Payload-SNs blockieren statt still umgeschrieben zu werden.
  - **M4 Staged + Ingest log:** `Staged` ersetzt die generische Outbox-Ansicht
    als gruppierter Arbeitsvorrat mit Komponentenbild, Stage, lesbarer Summary,
    `Push to PDB`/`Discard` und separater History. Das `Ingest log` ist ein
    read-only Verlauf mit Dry-Run und Komponentenlinks; Upload und manuelle
    Erfassung liegen ausschliesslich auf der Detailseite. ADR, UI-Referenz und
    Offline-Mockup sind auf diesen Zuschnitt nachgezogen.

  Kein M-Punkt hebt `dummy_only`, Outbox/Audit oder persoenliche
  Credential-Bindung auf. Zielvertrag und Abnahmekriterien stehen in
  `docs/superpowers/specs/2026-08-25-staged-first-module-page-design.md`.
- **Admin Settings fuer operative Institutsprofile (2026-08-26):** Ein
  strukturierter, admin-only Settings-Screen verwaltet Stammdaten sowie
  Mattermost-/Webhook-Kanaele, Shipment-Empfangscheckliste,
  typabhaengige Shipment-Reception-Tests, Glue-Topfzeiten und den
  Evidence-Mirror-Scope ohne Raw-JSON. Die API
  validiert diese Profilwerte zentral, erhaelt ein bereits gespeichertes
  Channel-Secret bei Rueckgabe des Maskenwerts `***` und auditiert nur
  geaenderte Schluessel/Kanalnamen — nie URLs oder sonstige Secret-Werte.
  Institutgebundene Admins bleiben auf ihr eigenes Profil beschraenkt; globale
  Admins koennen das Zielinstitut waehlen. Die gemeinsame UI-/API-Verifikation
  ist Teil der noch laufenden Gesamtabnahme.
- Harte Sicherheitsregeln sind dokumentiert: keine produktive PDB in Dev/Tests,
  `references/zeuthenflow` nur lesen, keine Secrets, kein Institut-Hardcoding.
- Backend-Basis: FastAPI-App, SQLAlchemy-Modelle fuer Institute, Komponenten,
  Outbox und Audit; Pydantic-Schemas; Health-, Institute-, Component-, Outbox-
  und Audit-Endpunkte; Outbox-Statusvertrag als Backend-Quelle der Wahrheit.
- Read-only PDB-Mirror ist im Aufbau: Komponentensync, PDB-Gateway (seit
  2026-07-08 produktionsfaehig hinter doppeltem Opt-in — es gibt keine
  Testinstanz mehr, siehe docs/09 + ADR 003), Mapping von PDB-Komponenten in
  lokale Mirror-Records, Demo-Fixtures und ein API-Endpunkt zum Starten eines
  Institute-Komponentensyncs.
- Frontend-Basis: Vite/React-Shell mit Navigation, Health-Anzeige,
  Komponentenliste mit Such-/Scan-Ergonomie, Detail-/Familienansicht und
  persistentem Component-/Evidence-Sync-Control, gruppiertem Staged-Screen,
  read-only Ingest-Log und Dashboard-Summary.
- Ingestion-Basis: lokale Inbox fuer Instrument-JSONs mit Hash und Auditspur.
  Datei-Drop und schemaerzeugte manuelle Erfassung auf der Komponentendetailseite
  koennen nach komponentengebundenem Dry-Run einen `upload_test_run`-Draft
  stagen; das separate Ingest-Log bleibt read-only und kein Pfad schreibt
  direkt in die PDB.
- Ingestion-Parser: Registry in `app/ingestion.py` (`glue-weight-v1`,
  `iv-curve-v1`, `pull-test-v1`, `pdb-test-run-v1`, generischer Fallback)
  normalisiert Payloads zu einem Preview mit blockierenden Issues und
  Warnungen; lokale Namen im `component`-Feld werden gegen den Mirror
  aufgeloest. Testtyp-spezifische Dry-Run-Checks fangen abgeschnittene
  Instrument-Ausgaben (gepaarte VOLTAGE/CURRENT- bzw.
  PULL_STRENGTH/PULL_GRADE-Arrays, NUMBER_WIRES-Abgleich). `GET
  /api/ingest/files/{id}/preview` liefert den Dry-Run auf der Detailseite und
  im read-only Ingest-Log; `propose-outbox` blockt bei Dry-Run-Issues mit 409.
- PDB-Upload-Converter (Phase-2/Worker-Schnitt): `app/pdb_upload.py` baut aus
  dem geprueften Ingest-Payload einen kanonischen `uploadTestRunResults`-Body.
  Der Worker revalidiert mit demselben Converter direkt vor dem Submit; der
  reale Submitter postet nie mehr das rohe Instrument-JSON, sondern die
  normalisierte SN/TestType/Results-Form (lokale Namen werden zur Mirror-SN).
- Test-Run-Evidence-Mirror (Phase-1/3-Basis): `TestRunEvidence` +
  `app/test_run_evidence.py` koennen externe/PDB-Testlaufresultate lokal
  idempotent spiegeln. `stage_service.satisfied_test_results` mischt diese
  Evidence mit confirmed itkFlow-Uploads; Stage-Suggestions und Dashboard-Gaps
  koennen damit bereits aus Mirror-Evidence gespeist werden.
- Stage-Move-Suggestion-Engine (Phase-3-Kickoff): reine Domain-Logik in
  `app/domain/stages.py` (Pflicht-Tests je Stage, institutsneutral via
  `InstituteProfile.settings`, Seed-Default aus der UI-Design-Referenz).
  `GET /api/components/{sn}/stage-suggestion` wertet bestaetigte Uploads
  (confirmed `upload_test_run`) zu passed/failed/missing aus und schlaegt den
  naechsten Stage-Move nur vor, wenn alle angezeigten Pflicht-Tests bis
  einschliesslich der aktuellen Stage passen; fehlende/fruehere Tests blocken
  konservativ; der PDB-Test-Run-Mirror wird als zusaetzliche Evidenzquelle herangezogen.
  Das Detail-UI zeigt die Pflicht-Tests-Tabelle + Vorschlag-Callout, und
  „Propose stage move" legt einen auditierten `stage_move`-Draft in die Outbox.
- Async-Outbox-Worker: eigenstaendiger Prozess (`app/run_worker.py`,
  `worker`-Service in Compose) beansprucht `approved`/`submitted`-Aktionen,
  wiederholt den Dry-Run gegen den aktuellen Mirror, ruft einen injizierten
  Submitter und setzt `confirmed` (mit `external_ref`) oder `failed`. Realer
  Submitter schreibt `uploadTestRunResults`/`setComponentStage`, verlangt die
  beim Approve gebundene persoenliche Credential und lehnt jedes Ziel ab, das keine eigene
  DUMMY-Testkomponente ist (`pdb_write_scope=dummy_only`, ADR 003).
  Idempotenz ueber `external_ref`; transiente `PdbSubmitUnavailable`-Fehler
  werden nach exponentiellem Backoff automatisch bis `worker_max_attempts`
  erneut versucht. Details: ADR 002.
- Watched-Folder-Agent ist bisher nur als Phase-2-Platzhalter dokumentiert.
- **Gegen echte Produktions-PDB validiert (2026-07-08):** Voller TUDO-Sync
  laeuft (read-only), reale Mapping-/Pagination-/Schema-Bugs gefixt, Prune
  (`stale`) fuer verschwundene Komponenten. Erstes DUMMY-Modul registriert
  (`20USEM00000435`). `is_dummy` leitet sich aus DUMMY-**Batch**-Mitgliedschaft
  ab (nicht dem `dummy`-Flag).
- **Navigationstoleranter Komponenten-Sync (2026-08-24):** Der lange
  Produktions-Read laeuft jetzt als persistenter, globaler Single-Flight-Job
  mit Poll-API und atomarem Mirror-Commit. Topbar und Components-Screen zeigen
  Phase, echten Zaehler, Fortschrittsbalken, Laufzeit und letztes Update; ein
  Screen-Wechsel oder Reload verliert den laufenden Job nicht. Der PDB-Fetch
  filtert serverseitig auf `state=ready`, liest feste 50er-Seiten seriell mit
  Timeout/Retry (einschliesslich Auth/JWKS) und verweigert metadatafreie
  Nutzdaten sowie Total-/Page-Drift. Jeder Retry aktualisiert den persistenten
  Job-Heartbeat, damit das UI trotz wartendem PDB-Read ein aktuelles
  Lebenszeichen zeigt. Alter synchroner und neuer Background-Endpunkt teilen
  denselben DB-Lease; parallele Mirror-Prunes sind damit ausgeschlossen. Lokale
  Komponenten werden blockweise vorgeladen, Stage-Events gebuendelt geschrieben.
  Ein Server-Neustart markiert den Job als `interrupted`; Teilstaende werden
  nie committed.
- **Statistik/Verlauf (Phase-1-Dashboard-Ausbau):** `StageEvent`-Historie wird
  beim Sync aus dem PDB-`stages[]`-Log rekonstruiert; `app/stats.py` +
  `/api/stats/production` liefern Throughput, Lead-Time, Stage-Dwell und Rework;
  eigener **Statistics-Screen** im Frontend. Kein separater Zeitreihen-Speicher
  noetig — alles aus einem Fetch.
- **Stage-Farbsystem:** geordneter Ramp kuehl→gruen (Fortschritt); Gruen nur
  FINISHED, Rot nur FAILED/TRASHED (CVD-sicher, `ui.ts`/`app.css`).

- **Jig-/Tool-Registry + Assembly-Wizard (Phase 3/4, 2026-08-26):** Die lokale
  Registry besitzt auditiertes strukturiertes CRUD, RFID/Code-Scan und
  `active|flagged|blacklisted`-Verwaltung. `POST /api/sync/tools/{institute}` spiegelt bereits gesyncte
  PDB-`TOOLS`-Komponenten read-only in die Registry (Code=SN, Label=lokaler
  Name, kompatible Typen aus Profil-Regeln oder generischem R-Type-Parsing).
  Komponenten-Sync triggert diesen Registry-Refresh automatisch; lokale
  RFID-/Blacklist-Informationen werden nicht durch normale Syncs
  heruntergestuft. Der scanner-first Assembly-Wizard loest Parent/Child exakt
  aus dem Mirror auf, bietet aktive typkompatible Tools und benutzbare
  Glue-Batches als Quick-Select/Scan, zeigt den kanonischen Server-Dry-run und
  staged `assemble_component`. Worker und Submitter revalidieren Zustand,
  Snapshots, Glue-Ablauf/Topfzeit und beide Teilnehmer. Der PDB-Guard laeuft vor
  Client-Aufbau: nur registrierte DUMMY-`MODULE|HYBRID`, nie Sensor/ASIC. Die
  fokussierten Offline-Suites enthalten keine Live-PDB-Aufrufe.

- **Phase-4-Backend fuer Glue-Batches, Shipments und Reminder (2026-08-26):**
  lokale Glue-Batch-Registry mit profilbasierter Topfzeit und auditiertem
  Komponentenverbrauch; read-only PDB-Shipment-Mirror fuer beide Richtungen
  mit lokal fuehrender Empfangscheckliste; sowie wiederkehrende Reminder im
  bestehenden Worker inklusive Mattermost-/generischem HTTPS-Webhook-Adapter
  stehen. Webhook-URLs werden in Institute-Antworten immer redigiert und aus
  Fehlern/Logs ferngehalten. Der fokussierte Offline-Schnitt ist mit 33 Tests
  verifiziert. Nutzer-/Entwicklervertrag: `docs/11-logistics-operations.md`.
  Die drei Produktscreens sind verdrahtet. Operative Profilwerte sind
  zusaetzlich ueber den strukturierten Admin-Settings-Screen pflegbar;
  Assembly-Quick-Select und Shipment-Reception-Test-Integration sind im
  nachfolgenden Ausbau inzwischen umgesetzt.

- **Auth End-to-End (docs/06, 2026-07-10):** Lokale Konten `viewer/operator/admin`
  vollstaendig — Login/Session/`create_admin`, serverseitige `user_id`-
  Attribution (statt Client-Actor), `require_operator`-Enforcement auf
  Sync/Outbox/Ingest, Double-Submit-CSRF (`itkflow_csrf`/`X-CSRF-Token`) +
  konfigurierbares `Secure`-Cookie, und das Frontend (Login-Screen, User-Rail,
  Rollen-Gating, Demo-Fallback) plus **Admin-`Users`-Screen** (Konten anlegen,
  Rolle/aktiv setzen, Passwort-Reset). Verifiziert: 211 Backend-Tests +
  Frontend-`tsc` gruen. Offen: Demo-User-Seed, 4-Augen-Approve, OIDC. Details docs/06.
- **Persoenliche Plus4U/PDB-Verbindung (Phase 6 vorgezogen, 2026-08-24):**
  Jedes lokale Konto verwaltet im neuen Account-Screen sein eigenes
  Access-Code-Paar. Das Backend verifiziert vor dem Speichern, erzwingt
  eindeutige PDB-Identitaeten und gleiche Institutsmitgliedschaft und legt nur
  AES-256-GCM-Ciphertext mit usergebundener AAD ab. Web-Reads haben keinen
  globalen Fallback; Background-Syncs laden ueber `SyncJob.user_id`. Beim
  Approve bindet `OutboxPdbPrincipal` Worker und Retries an die PDB-Identity
  des Freigebenden. API/Browser/Audit/Jobs/Logs bleiben secret-frei; der
  Windows-Launcher verwaltet einen stabilen Master-Key ausserhalb des Repos.
  Details: docs/06, docs/09, ADR 004.
- **Doku-Disziplin & -Waechter (2026-07-10):** CLAUDE.md-Regel #6 macht
  Doku-Updates verbindlich; `docs/00-doc-map.md` haelt die Ownership fest. Zwei
  Haiku-Subagenten pflegen die Doku — `yatagarasu` (Drift-Audit, read-only) und
  `tenjin` (Doku-Sync) — plus der `Stop`-Hook `.claude/hooks/doc-guard.ps1`
  (erinnert bei Code-Change ohne Doku-Update, fail-open/loop-sicher) und der
  `/sync-docs`-Command. Siehe `docs/00-doc-map.md`, `docs/03-agent-team.md`.
- **Komponenten-Typ-Decodierung (2026-07-10):** `frontend/src/ui.ts` uebersetzt
  die kodierten PDB-`type_code`s (`R5M0`, `ATLAS18R5`, `PBR5`) institutsneutral
  in lesbare Kurzform („Module · Endcap R5, pos 0"); verdrahtet in
  Komponentenliste, Detail, Family-Tree und Board. Volle Taxonomie/Legende in
  `docs/10-itk-domain-reference.md`.
- **Create-Module (2026-07-10):** DUMMY-Modul/Hybrid-Registrierung als
  Outbox-Flow — `POST /api/components/register` (operator-gated, Typ-Guard nur
  MODULE/HYBRID → 400 sonst) legt einen `register_component`-Draft an;
  Worker-Revalidate + `register_dummy_component` schreiben (dummy-only,
  Access-Codes). Frontend: `RegisterModuleForm` (`canWrite`). 220 Backend-Tests
  und Frontend-`tsc` gruen. Siehe `docs/10`.
- **Jig-/Pflicht-Property-Pruefung (2026-07-10):** institutskonfigurierbare
  Pflicht-Properties pro Testtyp (`InstituteProfile.settings['required_properties']`,
  z. B. `{"GLUE_WEIGHT": ["JIG"]}`); der Ingest-Dry-Run (`preview` +
  `propose-outbox`) blockt, wenn das benutzte Jig fehlt. Regel-#4-safe, Default
  leer. `ingestion.missing_required_properties` + 227 Backend-Tests gruen. Siehe
  `docs/07`.
- **Metrologie-Parser (2026-07-10):** `module-metrology-v1` validiert die
  `MODULE_METROLOGY`-Result-Groups. Wichtiger Befund: die Messprogramm-/zFlow-JSON
  ist bereits die Standard-PDB-`uploadTestRunResults`-Form → itkFlow ingestet
  Metrologie direkt. Offen: der Roh-`.txt`→JSON-Converter (Nominal-Tabellen).
  Siehe `docs/10`.
- **Auth-Login-Fix (2026-07-10):** Alt-/Legacy-Session-Cookies liessen Login
  (403) und `/api/auth/me` (500) crashen — gefixt (`whoami` mintet fehlende
  CSRF-Token, `csrf_protect` nimmt Login aus), 3 Regressionstests. 240 Tests gruen.
- **Dev-Server-Login-Fix (2026-07-10):** Das hartnaeckige „kann mich nicht
  einloggen" war letztlich **kein Auth-Code-Problem** (Login funktioniert
  end-to-end durch den Proxy, per Cookie-Jar-Probe verifiziert), sondern ein
  Fleet aus veralteten Dev-Servern (ein IPv6-only `:5173`, Streuner auf `:5192`,
  Vite-Drift auf `:5174`), der den Browser auf einem toten/veralteten Tab
  stranden liess. `frontend/vite.config.ts` pinnt jetzt `host:127.0.0.1`,
  `port:5173`, `strictPort:true` (faellt laut aus statt zu driften) und proxyt
  auf explizit `http://127.0.0.1:8000` (nie `localhost` — Windows/modernes Node
  loest zuerst `::1` auf und verfehlt das IPv4-only-Backend).
- **Windows-Dev-Neustart (2026-08-24):** Das Root-Skript
  `start-itkflow.ps1` raeumt erkannte laufende itkFlow-Listener auf den fest
  konfigurierten Dev-Ports `8000`/`5173` auf und startet FastAPI und Vite
  reproduzierbar auf `127.0.0.1` neu. Unbekannte Portbesitzer werden ohne
  explizites `-ForcePortCleanup` nicht beendet; das Skript setzt Anwendungsdaten
  und Konten nicht zurueck. Der Default bleibt PDB-inert; der explizite Schalter
  `-EnableProductionReads` aktiviert den produktiven Read-Pfad fuer Component-
  Syncs, ohne den Outbox-Worker zu starten (`dummy_only`, Write-Test-Opt-in aus).
  Browserzugriff: `http://127.0.0.1:5173`.
- **UI: Label-Humanisierung & Workflow-Klarheit (2026-07-10):** `stageLabel()`
  (`ui.ts`) humanisiert `SNAKE_CASE`-Stages (`HV_TAB_ATTACHED` → „HV Tab
  Attached"), institutsneutral, ITk-Akronyme (HV/QC/PWB…) bleiben gross;
  verdrahtet in Board-Spaltenkoepfe (Klartext + Rohcode-Unterzeile), Stage-Chips
  (Rohcode im `title`), Stage-Vorschlaege, Legende, Dashboard- und
  Statistik-Balken sowie den Komponententyp-Filter (`roleLabel`). Der damalige
  Triage/Outbox-Schnitt benannte den Zwei-Schritt-Flow explizit; seit ADR 006
  liegen Erfassung/Dry-Run auf der Detailseite und Review/Submit im
  komponentengruppierten `Staged`-Screen. Rohcodes bleiben ueberall als
  kanonische Referenz (Hover / Stammdaten-Feld). Siehe `docs/10`.

## Naechste Arbeitspakete

1. **Stage-Move-Strecke schliessen** (`domain-modeler`, `backend-dev`,
   `pdb-gateway-dev`): Suggestion-Engine, `stage_move`-Draft und realer
   Submitter (setComponentStage, DUMMY-Scope) stehen (2026-07-08). Erledigt
   (2026-07-10): PDB-Test-Run-Fetcher (`POST /api/components/{sn}/sync-evidence`,
   `POST /api/sync/evidence/{institute_code}`) an den lokalen
   `TestRunEvidence`-Mirror angebunden.
2. **Dashboard ausbauen** (`frontend-dev`, `backend-dev`): Summary erweitert
   (2026-07-08): `/api/dashboard/summary` liefert Required-Test-Gaps fuer
   aktive Module, Sync-Alter (neueste/aelteste Mirror-Zeile), stale/trashed
   Mirror-Zeilen sowie Review-/Approved-/Submitted-/Failed-Outbox-Zaehler; das
   Dashboard zeigt diese als kompakte KPI-Tiles und die Institutsverteilung mit
   profilbasierten Logos bzw. generischen Code-Icons. Required-Test-Gaps nutzen
   denselben Evidence-Service wie Stage-Suggestions und arbeiten mit dem
   Mirrored PDB-Test-Run-Evidence.
3. **Outbox-Worker haerten** (`backend-dev`, `pdb-gateway-dev`, `qa-engineer`):
   Async-Worker steht (2026-07-08, ADR 002); automatischer Retry mit Backoff
   fuer transiente Fehler und `worker_max_attempts` sind durchgesetzt. Offen:
   die reale Idempotenz-Pruefung gegen die Produktions-PDB im strikt
   DUMMY-gescopeten E2E, bevor der `submitted`-Recovery-Pfad scharf geschaltet wird.
4. **Upload-Converter und Worker-Schnitt** (`ingestion-dev`, `architect`,
   `backend-dev`): Registry, Preview und Dry-Run-Gate stehen inkl. Glue-Weight-,
   IV-, Pulltest- und generischem Parser (2026-07-08). Der Uebergang
   `ParsedTestRun`/Ingest-Payload -> PDB-Uploadcall ist ueber den reinen
   Converter `app/pdb_upload.py` definiert; Worker-Revalidierung und realer
   Submitter nutzen denselben kanonischen Payload-Build. Offen: optional
   Metrologie-Rohformat-Parser und weitere instrumentspezifische Converter.
5. **Produktions-Reads + DUMMY-Write-E2E validieren** (`pdb-gateway-dev`,
   `qa-engineer`): Read-Smoke gegen Produktion und **voller TUDO-Sync
   validiert** (2026-07-08): 3628 Payloads → ~2655 Mirror-Zeilen. Dabei mehrere
   reale Bugs gefunden+gefixt (Parent-ObjectId-Crash, Pagination-Check,
   `institute_code`-Overflow auf 32, `is_dummy` aus DUMMY-**Batch** statt
   `dummy`-Flag, Prune/`stale`). **Erstes echtes Dummy-Modul registriert**
   (`20USEM00000435`, `DUMMY_TUDO`). Offen: der volle `pytest -m pdb_write`
   (Upload + Stage-Move-Kreis auf der Dummy-SN) noch scharf durchziehen.
   Erledigt (2026-08-24): sichtbarer Background-Sync, navigationstolerantes
   Polling, explizites serielles Paging mit Timeout/Retry (auch fuer die vom
   Client intern ausgefuehrte Authentifizierung), Retry-Heartbeat, gemeinsamer
   Single-Flight-Lease fuer beide API-Pfade sowie Bulk-Mirror-Optimierung.
   Reale Messung: Die erste `full`-100er-Seite brauchte ohne State-Filter ca.
   14,0 s, mit `state=ready` ca. 3,6 s. Am problematischen Offset 300 lief
   `pageSize=100` (`pageIndex=3`) in einen Read-Timeout von mehr als 60 s;
   dieselben Datenbereiche kamen mit den festen 50er-Seiten (`pageIndex=6/7`)
   in 4,49 s beziehungsweise 2,24 s. Deshalb ist 50 die feste Seitengroesse;
   erschoepfte Retries markieren den Job als fehlgeschlagen, ohne den
   bestehenden Mirror zu veraendern.

## Geplant / verbleibende Ausbaustufen

Details im jeweiligen Dokument:

- **Nutzer, Rollen & Audit-Zuordnung** — `docs/06-users-roles-audit.md`.
  Lokale Accounts, Rollen, Attribution, Frontend, CSRF und persoenliche
  PDB-Verbindungen sind umgesetzt. Offen bleiben optionales OIDC/CERN-SSO,
  Demo-User-Policy und konfigurierbares 4-Augen-Prinzip.
- **Jig-/Tool-Registry + typ-gefilterter Quick-Select** —
  `docs/07-jig-tool-quickselect.md`. Registry, auditiertes CRUD/Statuspflege,
  PDB-`TOOLS`-Mirror, Glue-Batch-Auswahl und direkte Einbindung in den
  scanner-first Assembly-Wizard sind umgesetzt (2026-08-26). Verbleibend ist
  nur die fachliche Bestaetigung exakter PDB-Property-Codes je Institut/Typ;
  sie werden danach per `assembly_property_keys` konfiguriert.
- **Logistik, Glue und Reminder** — `docs/11-logistics-operations.md`.
  Backend-Modelle, API, Audit, Shipment-Read-Sync, Worker-Notifier und die
  drei Produktscreens (Glue Batches, Shipments, Reminders; 2026-08-26) stehen.
  Die profilgesteuerte Reception-Test-Verknuepfung samt Deep-Link, Done-Gate
  und auditiertem Admin-Override ist umgesetzt. Die lokale admin-only
  Betriebsansicht samt persistenten Worker-/Scheduler-Heartbeats, Queue-,
  Reminder-, Sync- und Parser-Signalen steht ebenfalls. Offen bleiben weitere
  Notification-Adapter/Eskalationen sowie das Phase-6-Row-/Query-Scoping.
  Shipment-Erstellung und GLUE-Registrierung in der PDB bleiben ausserhalb des
  aktuellen sicheren Schreibumfangs.
- **Remote-Zugriff / Tunneling** — `docs/08-remote-access.md`. Zugriff von
  zuhause; Empfehlung Tailscale/WireGuard (spaeter Cloudflare Tunnel).
  **Abhaengigkeit:** erst nach dem Auth-Fundament scharf schalten.

## Meilensteine

### Phase 0 - Fundament stabilisieren

**Ziel:** Ein sicherer, reproduzierbarer Entwicklungsstand, auf dem alle
weiteren Features ohne PDB-Produktionsrisiko entstehen.

**Epics:**

- Dev- und CI-Kommandos dokumentieren und gruene Offline-Tests erhalten.
- PDB-inerten Default sowie produktive Reads hinter doppeltem Opt-in absichern.
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

**Abhaengigkeiten:** Produktive PDB-Reads nur mit doppeltem Opt-in und fuer
markierte Integrationschecks; anonymisierte Referenz bleibt read-only.

### Phase 1 - Read-only-Cockpit

**Ziel:** itkFlow liefert taeglichen Nutzen ohne PDB-Schreibrisiko:
Komponenten suchen, Status verstehen, Familien sehen, Dashboards lesen.

**Epics:**

- Komponenten-/Test-/Shipment-Sync aus der produktiven PDB hinter Read-Opt-in in lokale
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
serverseitig geparst und validiert und auf der Komponentendetailseite als
gepruefte Staged-Action fuer die PDB vorbereitet.

**Epics:**

- Inbox-Modell fuer Dateien, Parserstatus, erkannte Komponente und Testtyp.
- Parser-Plugins fuer die wichtigsten Testtypen mit anonymisierten Fixtures.
- Watched-Folder-Agent als duenner Client: beobachten, hochladen, Status
  melden; kein Fachparsing auf Instrument-PCs.
- Komponentengebundene Datei-/Formularerfassung mit Vorschau,
  Validierungsfehlern, Pass/Fail-Signalen und Freigabe nach Staged.
- Read-only Ingest-Log sowie Staged-Review/Audit und Retry-Regeln fuer
  Test-Uploads.

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

**Teilstand (2026-08-26):** Glue-Batch-Registry und Produktscreen, read-only
Shipment-Mirror mit lokalem Empfang, profilgesteuerten Reception-Tests und
Produktscreen sowie Reminder/HTTPS-Notifier mit Produktscreen stehen. Der
admin-only Settings-Screen pflegt Notification-Kanaele, Empfangscheckliste,
Reception-Test-Mapping, Glue-Topfzeiten und Evidence-Scope strukturiert im
Institutsprofil. Tool-CRUD/Statuspflege und die direkte Tool-/Glue-Integration
im Assembly-Wizard samt Dry-run/Outbox/Worker-Revalidierung stehen ebenfalls.
Die lokale Operations-Health-Ansicht samt Heartbeats und Deep-Links steht.
Offen sind weitere Notification-Adapter/Eskalationen und das vollstaendige
Mandanten-Scoping. Details in
`docs/11-logistics-operations.md`.

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
- Mandantentrennung, Rollen, Credential-Ablage und Audit fuer mehrere
  Institute. Persoenliche verschluesselte PDB-Credentials und gebundene
  Worker-Identitaet sind seit 2026-08-24 umgesetzt (ADR 004); vollstaendiges
  Row-/Query-Scoping aller lokalen Read-Modelle bleibt offen.
- Beispielprofile fuer Endcap/Barrel und konfigurierbare Workflows.
- i18n-Grundlage fuer EN/DE, mit Englisch als Produkt-Default.
- Release-/Upgrade-Doku, Backup/Restore, Monitoring und Pilot-Checkliste.

**Done-Kriterien:**

- Neues Institut braucht keine Codeaenderung fuer Namensschema, Workflows,
  Stage-/Test-Mappings oder Notifications.
- Deployment funktioniert per dokumentiertem `docker compose up`.
- Kein Web-/Worker-PDB-Pfad faellt auf globale oder fremde Credentials zurueck;
  Backup/Restore umfasst DB und getrennten Master-Key.
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

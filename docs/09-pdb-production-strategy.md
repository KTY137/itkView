# PDB-Strategie: Produktions-PDB mit DUMMY-Schreib-Scope

> Verbindlich seit 2026-07-08. Ersetzt die Testinstanz-Annahme aus der
> Anfangsphase (harte Regel #2 in [`../CLAUDE.md`](../CLAUDE.md) wurde
> entsprechend neu gefasst). Entscheidung als ADR:
> [`adr/003-pdb-dummy-write-scope.md`](adr/003-pdb-dummy-write-scope.md).
>
> - **Besitzt:** das PDB-Sicherheitsmodell — Offline-Default, Read-Opt-ins,
>   Schreib-Scope `dummy_only`, DUMMY-Batch-Konvention, Env-Setup, Paging und
>   Ausfallverhalten des Syncs sowie die drei Verifikationsstufen. Bei jedem
>   Widerspruch zu einem anderen Dokument gilt dieses hier.
> - **Für wen:** alle, die PDB-Code anfassen, eine Instanz konfigurieren oder
>   einen Integrationslauf starten wollen.
> - **Verwandt:** [`adr/003-pdb-dummy-write-scope.md`](adr/003-pdb-dummy-write-scope.md)
>   (die Entscheidung), [`adr/004-personal-pdb-credentials.md`](adr/004-personal-pdb-credentials.md)
>   (wessen Identität PDB-Traffic erzeugt),
>   [`adr/002-async-outbox-worker.md`](adr/002-async-outbox-worker.md)
>   (der einzige schreibende Prozess),
>   [`adr/006-staged-first-ui-auto-mirror.md`](adr/006-staged-first-ui-auto-mirror.md)
>   und [`12-attachments-and-images.md`](12-attachments-and-images.md)
>   (Evidence- und Attachment-Mirror),
>   [`10-itk-domain-reference.md`](10-itk-domain-reference.md) (welche Typen nie
>   registriert werden dürfen), [`README.md`](README.md) (Lesepfade).

## Ausgangslage

- **Es gibt keinen PDB-Test-Server.** Die historische Testinstanz
  (`itkpd-test.unicorncollege.cz`) existiert nicht mehr. Seit 2026-08-26 ist
  sie auch aus der Konfiguration gestrichen: `pdb_instance` kennt nur noch
  `offline` (Code-Default, erreicht nichts) und `production` (siehe Abschnitt
  „Offline-Default und Reads ab Werk" unten).
- Supervisor-Anweisung (E-Mail, sinngemäß): Für **Strips** gibt es keine
  dedizierten Testkomponenten. Testteile werden über den **DUMMY-Batch-Präfix**
  von der Produktion getrennt; das Registrieren von **Hybriden und Modulen**
  zu Testzwecken ist erlaubt. **Sensoren oder ASICs dürfen niemals selbst
  registriert werden** — dafür gibt es keinen Dummy-Mechanismus, und es
  korrumpiert die Seriennummernvergabe der Kollaboration.
- Die `DB_TEST_*`-Objekte (Test-Structures-Folien) leben im Projekt
  „Common mechanics" und sind für Strips **nicht** der vorgesehene Weg.
- TUDO macht **nur Module Assembly** (keine Hybrid-Produktion) — praktisch
  registrieren wir also nur Module. Die Allowlist erlaubt kollaborationsweit
  Module+Hybride und kann per Env auf `["MODULE"]` verengt werden.

## Batch-Konvention (Module-Meeting-Intro-Folien, Backup)

- Hybrid-/Modul-Batches heißen `[Phase]_[Institute]`; Phase u. a. `PROTOTYPE`,
  `PPA`, `PPB`, `PPB1/2`, `(i)PPC`, `(i)PRESERIES`, `PRODUCTION`, `OTHER`,
  **`DUMMY`**. Unser Test-Batch ist damit `DUMMY_TUDO` (Code aus dem
  Institute-Profil, nie hartkodiert).
- Batch-Typen in der PDB: `MODULE_BATCH`, `HYBRID_BATCH` (zeuthenflow-Referenz
  `dbBatch.py` / `moduleManager.py`).

## Sicherheitsmodell (in Code erzwungen)

1. **Erreichbarkeit:** Produktion nur mit doppeltem Opt-in —
   `ITKFLOW_PDB_INSTANCE=production` **und** `ITKFLOW_ALLOW_PRODUCTION=true`.
   Der Code-Default ist seit 2026-08-26 `offline` (siehe Abschnitt
   „Offline-Default und Reads ab Werk").
2. **Persoenliche Identitaet:** Jeder Web-Read und Sync verwendet nur die
   AES-GCM-verschluesselte PDB-Verbindung des angemeldeten Users. Background-
   Syncs laden die Credentials ueber `SyncJob.user_id`. Beim Approve wird eine
   Outbox-Aktion dauerhaft an User-ID + PDB-Identity des Freigebenden gebunden;
   der Worker prueft diese Bindung bei jedem Retry. Deployment-weite
   Access-Codes sind kein Runtime-Fallback
   ([ADR 004](adr/004-personal-pdb-credentials.md)).
3. **Schreib-Scope:** `ITKFLOW_PDB_WRITE_SCOPE=dummy_only` (Default). Der
   Submitter (`backend/app/pdb_submit.py`) verweigert jede Schreibaktion
   (Test-Run-Upload, Stage-Move), deren Ziel-SN nicht im lokalen Mirror mit
   `is_dummy=True` steht (`backend/app/pdb_scope.py::is_dummy_target`).
   Dieses Flag setzt nur itkFlow selbst beim Registrieren eigener
   DUMMY-Teile (bzw. der Sync, wenn die PDB `dummy=true` meldet).
   ⇒ Writes auf echte Produktionsteile sind technisch unmöglich.
4. **Registrierung:** einzig über
   `pdb_submit.register_dummy_component(...)` — Komponententyp muss auf der
   Allowlist stehen (`ITKFLOW_PDB_DUMMY_COMPONENT_TYPES`, Default
   `["MODULE","HYBRID"]`; alles andere, insbesondere Sensoren/ASICs, wird
   abgelehnt), Teil landet immer im Batch `DUMMY_<Institut>` (wird bei Bedarf
   angelegt). Payload-Form folgt der zeuthenflow-Referenz
   (`registerComponent` mit project/subproject/institution/componentType/
   type/properties; Batch separat via `listBatches`/`createBatch`/
   `addBatchComponent`).
5. `unrestricted` ist als Scope-Wert bekannt, wird aber im Code abgelehnt —
   echte Produktions-Writes brauchen später einen eigenen, bewussten
   Freigabeschritt.
6. Die Offline-Testsuite bleibt netzwerkfrei; alle Guards sind mit Fakes
   getestet (`tests/test_pdb_scope.py`, `tests/test_outbox_worker.py`).

## itkView: staerkerer Produkt-Scope als `dummy_only`

`ITKFLOW_PRODUCT_VARIANT=view` baut itkView aus derselben Codebasis. Dieser
Modus ist kein weiterer Rollenname und kein Alias fuer `viewer`: er ist eine
serverseitige Produktgrenze, die auch fuer Admins und direkte API-Aufrufe gilt.

- Die ausgelieferten Produktions-**Reads** bleiben moeglich. Persoenliche
  Credentials, Component-/Testdefinition-/Evidence-/Attachment-/Tool- und
  Shipment-Sync schreiben ausschliesslich den getrennten lokalen itkView-
  Spiegel und duerfen deshalb weiterhin ueber explizit klassifizierte POST-
  Routen gestartet werden.
- Produktionsdatenerfassung und operative Mutationen (Ingest, Outbox,
  Assembly, Registrierung, Stage-Move, Tool-/Glue-Registry-Aenderungen,
  Shipment-Reception, Reminder/Notification) werden vor dem Handler zentral
  abgelehnt. Eine neue unsichere Route ist in `view` standardmaessig gesperrt,
  bis sie bewusst als notwendiger Read-Sync oder lokale Administration
  klassifiziert wurde.
- Settings erzwingen `pdb_write_scope=disabled`, `allow_pdb_writes=false`,
  `outbox_processor=off` und `reminder_scheduler=off`. Zusaetzlich verweigern
  `make_pdb_submitter`, `register_dummy_component` und der Standalone-Worker
  jeden Drain. UI-Gating ist damit nur Darstellung, nie die Schutzgrenze.
- itkFlow und itkView teilen weder DB/Attachments/Keys/Logs noch Cookies. Eine
  alte, bereits `submitted` stehende itkFlow-Aktion kann daher nicht in den
  Viewer gelangen.
- Das dedizierte Compose-Deployment setzt diese Grenze ebenfalls physisch um:
  fester Projektname `itkview`, PostgreSQL-Datenbank/-User `itkview`, eigene
  Datenbank- und Attachment-Volumes und ein neu erzeugter Credential-Key.
  Eine itkFlow-`.env`, deren Key oder deren Volumes werden nicht uebernommen.

Der vollstaendige Varianten- und Packaging-Vertrag steht in
[`ADR 007`](adr/007-itkview-read-only-product.md).

## Offline-Default und Reads ab Werk (2026-08-26)

Die tote Testinstanz-Konfiguration ist gestrichen: `pdb_instance` kennt nur
noch `offline` und `production`; `pdb_test_api_url` und die zugehoerigen
URL-Konstanten existieren nicht mehr. Motivation: Der „test"-Default erzeugte
irrefuehrende Fehlermeldungen („PDB could not be reached — check your
network"), obwohl die Unerreichbarkeit Konfiguration war, kein Netzproblem.
Der Account-Screen zeigt fuer eine Offline-Instanz jetzt die ehrliche
Server-Meldung „no PDB configured".

Owner-Entscheidung dazu (Nachkonfiguration soll entfallen):

- **Code-Default `offline`:** Dev-Umgebungen, die Testsuite und jede
  Agenten-Session erreichen weiterhin keine PDB. Agenten setzen die beiden
  Opt-ins niemals selbst (CLAUDE.md, harte Regel 2).
- **Endnutzer-Artefakte liefern Reads ab Werk:** Das Desktop-Bundle
  (`app/desktop_server.py`) und Compose (`deploy/docker-compose.yml`) setzen
  `production` + `allow_production=true` als Default; eine explizit gesetzte
  Env-Variable gewinnt weiterhin (`ITKFLOW_PDB_INSTANCE=offline` ergibt ein
  Deployment, das nichts erreicht).
- Das aendert nichts an den uebrigen Schichten: PDB-Traffic entsteht erst,
  wenn eine Person ihre persoenlichen Access-Codes verbindet
  ([ADR 004](adr/004-personal-pdb-credentials.md)). Fuer itkFlow bleiben Writes
  `dummy_only` ([ADR 003](adr/003-pdb-dummy-write-scope.md)); itkView erzwingt
  den staerkeren Scope `disabled` wie oben beschrieben.

## Zurueckgezogene Testlaeufe (`run_state`, 2026-08-27)

Die PDB liefert einen **zurueckgezogenen** Testlauf ueber `getComponent`
weiter aus; er traegt lediglich `state='deleted'`. Bis 2026-08-27 hatte
`test_run_evidence` keine Statusspalte, ein solcher Lauf war im Spiegel von
einer gueltigen Messung nicht zu unterscheiden — und zaehlte damit als
Nachweis. Im echten TUDO-Spiegel sind das **102 von 14 759 Laeufen**
(13 % aller `GLUE_WEIGHT`, 25 % aller `MODULE_BOW`, verteilt auf 45
Komponenten).

- `TestRunEvidence.run_state` spiegelt den PDB-Zustand als eigene Spalte;
  `pdb_test_evidence` fuellt sie aus demselben Feld, das auch im Payload
  bleibt (der inkrementelle Sweep fingerprintet den Payload).
- `app.test_run_evidence.WITHDRAWN_RUN_STATE` / `is_withdrawn()` /
  `live_runs_only()` sind die **einzige** Auslegung: nur der terminale
  Zustand `deleted` zieht einen Lauf zurueck. `NULL` (unbekannt, z. B. eine
  Nicht-PDB-Quelle) und das PDB-eigene `requestedToDelete` (ein noch nicht
  ausgefuehrter Antrag; im Spiegel genau einmal vorhanden) zaehlen weiter.
- Ausgeschlossen wird ein zurueckgezogener Lauf ueberall dort, wo er als
  Nachweis gelesen wuerde: `stage_service.satisfied_test_results` (und damit
  jedes Stage-Gate), die Worksheet-Zeilen samt `latest`, und die
  Messwert-Statistik. Sind **alle** Laeufe eines Testtyps zurueckgezogen,
  liest die Pflichtpruefung wieder `missing` — nie das Urteil einer Messung,
  zu der niemand mehr steht.
- Er verschwindet aber nicht: `GET /api/components/{sn}/tests` listet ihn
  weiterhin und liefert `run_state` dazu, und die Worksheet-Zeile meldet
  `withdrawn_count`. Daten zu verstecken, die die PDB noch haelt, waere eine
  eigene Form der Falschaussage.
- **Retrofit statt Re-Sync:** `ensure_phase0_sqlite_schema` legt die Spalte an
  und befuellt sie per `json_extract` aus den bereits gespiegelten Payloads.
  Gemessen am 630-MB-Spiegel des Owners: 27 s einmalig, danach 0,1 s je Start
  (die Variante „nur `deleted` schreiben" waere dauerhaft 5,3 s pro Start).
  Fehlt JSON1 im SQLite-Build, bleibt die Spalte NULL — also das Verhalten von
  vorher — und der Start meldet das, statt zu scheitern.

## Ring-Module / Halbmodule

R3–R5-Module sind Split-Module: Halbmodule (z. B. `R5M0`, `R5M1`) werden auf
ein Ring-Modul assembliert (zeuthenflow: `DBHalfModule`/`DBRingModule`,
Assemblierung über `assembleComponent` mit parent=Ring-SN). In der PDB ist das
eine normale Parent/Child-Beziehung — unser Mirror (`parent_sn` aus dem
`parents`-Array von `listComponents`) und der Family-Tree im UI bilden das
bereits ab. Für DUMMY-Tests registrieren wir einzelne (Halb-)Module; eine
Ring-Assemblierung von DUMMY-Teilen ist möglich, aber nicht Teil des E2E.

Fachlich folgt daraus, dass ein Ring-Modul seine Nachweise gar nicht selbst
traegt: Metrologie, Klebegewicht und PS-IV liegen auf den beiden Halbmodulen.
Deshalb liefert die Worksheet-Payload seit 2026-08-27 auch die Evidence der
**direkten Kinder** (`worksheet.children`, siehe docs/05) — im Spiegel haengen
nur 720 von 14 759 Laeufen an MODULE-Komponenten, aber 10 114 an deren
Kindern.

## Betrieb: Env-Setup (niemals committen)

```
ITKFLOW_PDB_INSTANCE=production
ITKFLOW_ALLOW_PRODUCTION=true
ITKFLOW_PDB_CREDENTIAL_ENCRYPTION_KEY=<urlsafe-base64-32-byte-key>
# Nur für den Write-E2E, bewusst setzen und danach entfernen:
# ITKFLOW_ALLOW_PDB_WRITES=true
# ITKFLOW_ITKDB_ACCESS_CODE1=…
# ITKFLOW_ITKDB_ACCESS_CODE2=…
# Nach dem ersten Lauf: registrierte DUMMY-SN wiederverwenden:
# ITKFLOW_PDB_WRITE_TEST_SN=20U…
```

Die beiden `ITKFLOW_ITKDB_ACCESS_CODE*`-Werte gehoeren nur zu explizit
markierten manuellen `pdb_sandbox`/`pdb_write`-Tests. Backend-Webrequests und
der produktive Worker ignorieren sie als Fallback. Im Produkt verbindet jede
Person ihre Codes nach dem Login im **Account**-Screen. Bestehende globale
`.env`-Codes werden absichtlich nicht automatisch einem User zugeordnet.

Der Master-Key muss fuer Backend und Worker identisch und stabil sein. Der
Windows-Launcher erzeugt ihn ausserhalb des Repos unter
`%LOCALAPPDATA%\itkflow\pdb-credential.key`; Compose erwartet ihn im
Deployment-Secret. Verlust macht gespeicherte Verbindungen unlesbar, ein
unkoordiniertes Ersetzen ist keine Keyrotation.

Der lokale Windows-Launcher setzt die beiden Production-Read-Opt-ins nur nach
einem expliziten Schalter für seinen Backend-Kindprozess und stellt die
aufrufende Shell danach wieder her:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-itkflow.ps1 -EnableProductionReads
```

Ohne den Schalter laeuft der Launcher mit `pdb_instance=offline` — es gibt
nichts zu erreichen und die UI sagt das auch so; fuer einen echten Sync muss
der Production-Read-Schalter gesetzt sein.
Mit dem Schalter startet er keinen Outbox-Worker, setzt
`ITKFLOW_ALLOW_PDB_WRITES=false` und erzwingt weiter
`ITKFLOW_PDB_WRITE_SCOPE=dummy_only`.

**SQLite: WAL, Busy-Timeout und ruhige Skips bei Lastkontention (2026-08-26).**
Ein Desktop-Bundle teilt eine einzelne SQLite-Datei zwischen API-Prozess,
Outbox-Processor und Reminder-Scheduler; ohne PRAGMAs gibt Pythons
sqlite3-Treiber nach 5 s auf, was live als 500er in einem Request sowie als
„cycle failed"/„tick failed" auftrat. `make_engine` (`app/db.py`) aktiviert
deshalb fuer jede dateibasierte SQLite-Engine ueber ein `connect`-Event
`journal_mode=WAL`, `busy_timeout=30000` und `synchronous=NORMAL`;
In-Memory-Engines (Tests) bleiben unangetastet. WAL hebt genau die Blockade
auf, die den Bug ausloeste: Schreiber und Leser laufen nebenlaeufig, und
`busy_timeout` faengt konkurrierende Schreiber mit 30 s Wartezeit statt 5 s ab.
Die gemeinsam genutzte Klassifizierung `is_sqlite_busy` (von `sync_jobs.py`
nach `app/db.py` gezogen) behandelt „database is locked" in
`OutboxProcessor.tick` und im `ReminderScheduler` als erwarteten, ruhigen Skip
(„database busy — skipped this cycle") statt als Fehler — insbesondere ohne
Fehler-Heartbeat, der den Ops-Health-Screen faelschlich auf „error" springen
liesse. Zusaetzlich holt `ensure_phase0_sqlite_schema` den Unique-Index
`uq_tool_institute_code` auf Bestands-DBs nach (vorher echte Duplikate
deduplizieren, kleinste `id` gewinnt; `institute_id IS NULL` bleibt
unangetastet), idempotent bei jedem Start.

## Komponenten-Sync: Paging, Fortschritt und Fehlergrenze

Der UI-Pfad startet einen persistenten `SyncJob` ueber
`POST /api/sync/jobs/components/{institute_code}`. Es darf global nur einen
aktiven Komponenten-Job geben, weil Instituts-Sichten ueberlappen koennen und
der Mirror nach SN eindeutig ist. Viewer koennen den Status ueber
`GET /api/sync/jobs/{id}` beziehungsweise den aktiven Job ueber
`GET /api/sync/jobs/active?kind=components` lesen. Dadurch laeuft der Fetch
unabhaengig vom Browser-Screen weiter und wird nach Navigation oder Reload
wiedergefunden.
Der Start verlangt eine verifizierte persoenliche PDB-Verbindung und speichert
nur die lokale `user_id`. Der Background-Thread entschluesselt das Paar erst
aus einer frischen DB-Session; weder Jobzeile noch Executor-Queue enthalten
Codes. Ein anderer User kann den global sichtbaren Fortschritt beobachten,
uebernimmt aber nicht die PDB-Identitaet des laufenden Jobs.

Der produktive `listComponents`-Read ist weiterhin rein lesend und verwendet:

- **zwei getrennte Listings statt der serverseitigen OR-Suche (2026-08-26):**
  je eine Abfrage fuer „gehoert dem Institut" (`institute`) und „liegt beim
  Institut" (`currentLocation`), lokal per Seriennummer zusammengefuehrt.
  `useOrInLocationSearch=true` blaettert nachweislich inkonsistent: ein
  TUDO-Listing meldete 3799 Komponenten, lieferte 3799 Zeilen — aber nur 2539
  verschiedene. Rund 1260 Komponenten fehlten stillschweigend, darunter
  **alle 92 Jigs/Tools** (Typ `TOOLS`, bei TUDO stehend, aber anderen
  Instituten gehoerend), weshalb die Tool-Registry leer blieb. Einzeln
  abgefragt kommen beide Scopes dublettenfrei und vollstaendig zurueck;
  zusammengefuehrt ergibt das 3044 statt 2538 gespiegelte Komponenten.
  Sortierhinweise (`orderBy`/`sortBy`) akzeptiert die API nicht.
- den festen, verhaltensaequivalenten Filter `state=ready` (der Mapper konnte
  andere States ohnehin nicht spiegeln),
- `outputType=full`, weil Parents, DUMMY-Batches und Stage-Historie gebraucht
  werden,
- serielle, feste 50er-Seiten mit Connect-/Read-Timeout und begrenztem Retry
  (Budget pro Seite konfigurierbar via `ITKFLOW_SYNC_PAGE_MAX_ATTEMPTS`,
  Default 3, exponentieller Backoff — auf wackliger Leitung hochsetzen);
  derselbe Default-Timeout gilt auch fuer den separaten
  itkdb-Auth-/JWKS-HTTP-Client; jeder Retry aktualisiert den persistenten
  Job-Heartbeat, damit das UI waehrend des wartenden Reads ein aktuelles
  Lebenszeichen behaelt,
- ein eingefrorenes `total`/`pageSize` sowie strikte Index-, Seitenlaengen- und
  Abschlusspruefungen vor jedem Prune. Metadatafreie Antworten duerfen nur
  leer sein; nichtleere Daten ohne `pageInfo` brechen sicher ab.
- eine Dublettenpruefung am Ende: Die reine Zeilenzahl ist **kein**
  Vollstaendigkeitsbeweis — genau so passierte der OR-Such-Fehler oben jede
  bisherige Pruefung. Wiederholte Seriennummern bedeuten ebenso viele fehlende
  Komponenten und brechen den Sync jetzt ab, statt einen lueckenhaften Mirror
  zu schreiben.

Seiten werden bewusst nicht parallel abgefragt: Die real gemessenen groesseren
`full`-Seiten waren langsamer, der itkdb-Client garantiert keine Thread-
Sicherheit und unnoetige Parallelitaet wuerde die Produktions-PDB belasten.
Im reproduzierten Problemfall am Offset 300 lief `pageSize=100`
(`pageIndex=3`) in einen Read-Timeout von mehr als 60 s. Die aequivalenten
festen 50er-Seiten (`pageIndex=6` und `7`) antworteten in 4,49 s und 2,24 s;
deshalb ist 50 die feste Seitengroesse und kein adaptives Paging-Fallback.
Nach dem Fetch werden bestehende Komponenten/Parents blockweise vorgeladen und
Stage-Events per Bulk-Insert erneuert. Mirror, Parent-Links, Prune, Stage-
Historie, Tool-Ableitung und erfolgreiches Jobresultat committen zusammen.
Der historische synchrone `POST /api/sync/components/{institute_code}` teilt
denselben eindeutigen DB-Lease mit dem Background-Pfad; ein paralleler Lauf
antwortet mit `409`, statt einen zweiten Mirror-Writer zu starten. SQLite-BUSY
beim gleichzeitigen Start wird nur in dieser kurzen Lease-Transaktion begrenzt
wiederholt.
Bei Fetch-/Mapping-/DB-Fehlern, einschliesslich erschoepfter Page-Retries,
wechselt der Job auf `failed` und der vorige Mirror bleibt vollstaendig
erhalten. Ein beim Serverstart noch aktiver Job wird nur dann als
`interrupted` geschlossen, wenn sein Fortschritts-Heartbeat aelter als drei
Minuten ist (laengste legitime Funkstille ist ein ~60s-Page-Timeout): eine
zweite App-Instanz gegen dieselbe Datenbank toetet damit keinen lebenden Sync
mehr — real passiert bei 600/3766 —, waehrend ein echter Crash seine
Single-Flight-Lease nach spaetestens drei Minuten freigibt. Automatisch
fortgesetzt wird weiterhin nichts.
Der Evidence-Sweep wiederholt zudem einen transienten `getComponent`-Fehler
pro Komponente bis zum konfigurierten Retry-Budget
(`ITKFLOW_SYNC_PAGE_MAX_ATTEMPTS`), statt bei einem einzelnen
Leitungs-Wackler den ganzen Institutslauf bei null abzubrechen; eine dauerhaft
unerreichbare Komponente laesst den Job weiterhin ehrlich scheitern. Jeder
dieser Wiederholungsversuche schreibt vor dem Backoff einen Job-Heartbeat:
die volle Retry-Leiter kann sonst laenger schweigen als die Drei-Minuten-Grenze
der Startup-Recovery, und eine zweite App-Instanz haette einen lebenden Job als
verwaist geschlossen.

**Kurze Internet-Ausfaelle ueberleben (2026-08-26).** Drei Luecken liessen eine
Funkloch-Minute wie dauerhaften Verlust aussehen:

- **Attachment-Downloads hatten keinen Retry.** Ein realer Sweep endete mit
  `attachments_failed=11` von 363 — jeder Netzwerkfehler zaehlte sofort als
  endgueltig. `app/attachment_store.py` unterscheidet jetzt transient von
  permanent (`is_transient_download_error`): DNS-Ausfall, Connection Reset,
  TLS-Handshake-Timeout, 408/425/429 und 5xx werden mit exponentiellem Backoff
  bis `ITKFLOW_SYNC_PAGE_MAX_ATTEMPTS` wiederholt (dasselbe geteilte Budget wie
  Seiten- und Evidence-Retry); 4xx, HTML-Fehlerseiten und uebergrosse Bodies
  scheitern sofort, weil Warten daran nichts aendert. Auch der Aufbau des
  authentifizierten Clients faellt darunter — er ist waehrend eines Ausfalls
  genauso betroffen wie jeder andere Request. Ist das Budget dafuer erschoepft,
  scheitern die restlichen PDB-Dateien dieses Sweeps schnell, statt das Gateway
  je Datei erneut zu befragen. Ein Fehlschlag wird **nie** als gespeichert
  vermerkt (`relative_path` bleibt leer), der naechste Sweep holt ihn also
  automatisch nach. Waehrend der Download-Phase feuert ein Heartbeat pro Datei
  und vor jedem Backoff, damit eine Komponente mit vielen langsamen Dateien
  nicht verwaist wirkt.
- **Ein transient gescheiterter Job blieb bis zum Klick liegen.** Jobs, die an
  einem `PdbSyncUnavailable`/`PdbEvidenceUnavailable` scheitern, planen jetzt
  **genau einen** automatischen Wiederholungslauf nach
  `SYNC_AUTO_RETRY_DELAY_SECONDS` (60 s; deutlich unter der Heartbeat-Grenze).
  Die Obergrenze steckt im dauerhaften Marker `requested_by` = „automatic retry
  (…)": ein so gestarteter Job plant selbst keinen weiteren — die Kette ist
  damit auch ueber Neustarts hinweg auf Original + ein Retry begrenzt.
  Waehrend der Wartezeit existiert bewusst **keine** Jobzeile: der
  fehlgeschlagene Job bleibt sichtbar und lease-frei, ein Mensch kann jederzeit
  selbst starten. Feuert der Timer, laeuft der Retry durch die normale
  Lease-Akquise und **konvergiert** auf einen bereits vorhandenen Job, statt
  einen zweiten zu stapeln; Single-Flight bleibt unangetastet. Nicht-transiente
  Fehler (fehlende Credentials, verschwundenes Institut, echte Bugs) bekommen
  keinen Retry — sie wuerden nur denselben Fehler wiederholen.
- **Zombie-Leases blockierten den Neustart.** Startup-Recovery schliesst nur
  Jobs mit altem Heartbeat; ein Crash mit sofortigem Neustart hinterlaesst aber
  eine frisch aussehende Zeile, die die Single-Flight-Lease dauerhaft
  blockierte. `acquire_*_sync_lease` uebernimmt eine Lease jetzt selbst, sobald
  deren Heartbeat aelter als die Drei-Minuten-Grenze ist (dieselbe Regel und
  derselbe Code-Pfad wie die Startup-Recovery); ein Job zwischen zwei
  Heartbeats bleibt unangetastet.
- **Eine uebernommene Lease zaehmt auch den alten Worker.** Die Jobzeile traegt
  ein Lease-Token; Claim, Fortschritt, Fehler und Finalisierung aktualisieren
  nur noch per Compare-and-swap auf `(job_id, lease_token)`. Dieselbe Fence
  laeuft unmittelbar vor Component-/Evidence-Commit und vor dem atomaren
  Publizieren einer fertigen Attachment-Datei. Wacht ein alter Prozess nach
  der stale-Uebernahme wieder auf, darf er lesen und seinen lokalen Download
  verwerfen, aber weder DB-Zustand noch Datei des Nachfolgers ueberschreiben.
  Jeder Fetch besitzt dafuer eine exklusiv erzeugte, zufaellige `.part`-Datei
  neben dem Ziel. Prozesslokale Blob-Sperren bleiben eine Deduplizierungs-
  Optimierung; die getrennten Temp-Pfade verhindern auch zwischen zwei
  Prozessen, dass der alte Worker Bytes des Nachfolgers ueberschreibt oder bei
  Fence-Verlust dessen Staging-Datei loescht. Erst nach erfolgreicher Fence
  publiziert `os.replace` die eigene Datei atomar.
  Der Public-Jobvertrag nennt `heartbeat_stale` und
  `stale_after_seconds`; erst daraufhin bietet die UI den bewussten Retry an.
  `Check status` allein mutiert nichts. Ein vom Executor abgelehnter Job wird
  terminalisiert und gibt Lease sowie Queue-Heartbeat sofort frei.

**Share-Link-Attachments landeten nie auf der Platte (2026-08-26, Bugfix).**
Visual-Inspection-Ergebnisse tragen oefter eine oeffentliche CERNBox-/
Sync&Share-URL statt eines PDB-Attachments. Diese Links zeigen auf die
HTML-Betrachterseite, nicht auf die Datei — der Mirror forderte genau diese
Seite an, erkannte korrekt HTML und verwarf sie, womit jedes solche Attachment
als „bekannt, aber nicht gespiegelt" liegen blieb. Der Download probiert jetzt
in dieser Reihenfolge: `remote.php/dav/public-files/<token>` (liefert die
Bytes und eine Content-Length), dann `/s/<token>/download`, zuletzt die
Original-URL. Erkannt wird die Form am URL-Muster `/s/<token>` — eine
Konvention der Share-Software, kein Institutsdetail (harte Regel 4);
`/index.php/s/<token>/download` wird bewusst nie erzeugt, weil diese Variante
in der Live-Pruefung an der Namensaufloesung scheiterte. Liefern alle
Kandidaten nur HTML, bleibt es bei „nicht gespiegelt" (eine gespeicherte
Betrachterseite waere ein kaputtes Bild, das wie ein Galerie-Bug aussieht) —
protokolliert wird dabei nur der Attachment-Code, nie die URL. Der Content-Type
kommt aus der Antwort, weil Share-Deskriptoren keinen mitbringen; erst dadurch
werden gespiegelte Fotos als Bild erkannt und bekommen ihre Dateiendung.

**Passwortgeschuetzte oeffentliche Shares (2026-08-27).** Jedes lokale Konto
kann im Account-Screen ein Passwort fuer eine konkrete oeffentliche
ownCloud-/Reva-Freigabe hinterlegen. Das Backend akzeptiert nur HTTPS-Formen
mit Public-Token, prueft das Passwort vor dem Speichern per DAV-`PROPFIND` und
legt nur AES-256-GCM-Ciphertext mit usergebundener AAD ab. Listen-/API-
Antworten enthalten nur Host und Token-Ende. Evidence-Jobs laden ausschliesslich
die Share-Credentials ihres `SyncJob.user_id`; Basic-Auth nutzt den
oeffentlichen ownCloud-Benutzer `public`, niemals PDB-Codes. Mit Credentials
muss jeder Redirect dieselbe HTTPS-Origin (Host und effektiver Port) behalten;
non-default Public-Share-Ports und HTTPS-Downgrades werden verweigert.
401/403, Login-HTML, ein fehlendes Passwort und private Dateibrowser-Links
zaehlen im Job als `skipped`/`authentication_required`, nicht als PDB-Ausfall.
Nach dem ersten Auth-Befund wird dieselbe gehashte Share-Identitaet im Sweep
nicht je Komponente neu angefragt. Private CERNBox-Account-URLs brauchen einen
spaeteren CERN-OAuth-Schnitt; itkFlow nimmt kein CERN-Account-Passwort an.
Details und der bestehende schema-gebundene Weg fuer manuell erfasste URL-
Resultate stehen in [`12`](12-attachments-and-images.md) §2.3b.

Die Transient-/Permanent-Einstufung ist an allen drei Grenzen dieselbe Frage
und jeweils lokal beantwortet: `app/pdb_sync.py` fuer Listing-Seiten,
`app/attachment_store.py` fuer Dateien und `app/pdb_submit.py::_call_pdb` fuer
Writes (4xx = Ablehnung der Daten, 408/425/429 + 5xx + Transportfehler =
wiederholbar). Der Outbox-Worker erkennt einen wiederholbaren Fehlschlag am
Prefix `PDB unavailable:`, den ausschliesslich `PdbSubmitUnavailable` erzeugt.
`backend/tests/test_transient_classification.py` pinnt diese Aufteilung fuer die
real beobachteten Ausfallformen fest.

**Evidence-Umfang: Baugruppen statt nur Module (2026-08-26).** Der Sweep deckte
nur `MODULE` ab und filterte zusaetzlich auf *Besitz* (`institute_code`) — an
einem Assembly-Standort gehoert das meiste aber dem sendenden Institut und
steht nur hier (bei TUDO: ~2000 von 3044 Komponenten). Beide Grenzen sind
gefallen:

- Scope ist jetzt „uns gehoerend **oder** hier stehend", analog zum
  Zwei-Scope-Fetch des Komponenten-Mirrors.
- `DEFAULT_EVIDENCE_COMPONENT_TYPES` deckt die Typen ab, die real Testlaeufe
  tragen (per Stichprobe gegen die Produktions-PDB ermittelt): `MODULE`,
  `SENSOR`, `SENSOR_S_TEST`, `HYBRID`, `HYBRID_ASSEMBLY`, `HYBRID_FLEX`,
  `HYBRID_TEST_PANEL`, `EC_POWERBOARD_FLEX`, `PWB`, `HV_TAB_SHEET`.
  Sensoren tragen dabei die meisten Attachments (26 in einer 3er-Stichprobe).
  Die Chip-Typen `ABC`/`HCC`/`AMAC` bleiben bewusst draussen: sie
  verfuenffachen den Sweep fuer Wafer-QA, die nicht die Produktionsakte des
  Standorts ist — ein Standort kann sie ueber `evidence_component_types`
  jederzeit dazunehmen. Das Profil-Setting ueberschreibt die Liste weiterhin
  vollstaendig (harte Regel 4: Typcodes sind kollaborationsweit, nicht
  institutsspezifisch).

**Attachment-Downloads hielten die Schreibsperre waehrend des Netzwerk-I/O
offen (2026-08-26, Bugfix).** `download_attachments` schrieb bisher zuerst die
Zeile (`_upsert_row` + `flush()`) und lud danach die Bytes aus dem Netz — bei
einem 6,7-MB-Bild ueber eine wacklige Leitung inklusive Retries hielt das die
SQLite-Datei minutenlang in einer offenen Schreibtransaktion. Live-Folge:
parallele HTTP-Requests und Worker-Ticks scheiterten mit „database is locked".
`app/attachment_store.py` trennt den Ablauf jetzt strikt in drei Phasen:
(1) ein rein lesender Plan, welche `(source, code)`-Paare bereits eine Datei
auf der Platte haben; (2) der Netzwerk-Fetch mit der bestehenden Retry-/
Klassifikations-/Heartbeat-Logik, dem gar keine `Session` mehr uebergeben wird
— die Bytes landen sofort in einer exklusiven `.part`-Datei neben ihrem
Zielpfad; und
(3) ein kurzer, netzwerkfreier Commit, der die fertigen Dateien atomar
(`os.replace`) umbenennt und die Zeilen upsertet. Ein Fehlschlag hinterlaesst
weder die eigene `.part`-Datei noch einen `relative_path`; eine durch harten
Prozessabbruch verwaiste Datei unbekannten Owners wird bewusst nicht von einem
neuen Worker ueberschrieben oder geloescht. Ein Regressionstest schreibt
waehrend des simulierten Fetches ueber eine zweite unabhaengige
`sqlite3`-Verbindung und beweist, dass nichts mehr blockiert (reproduzierbar
rot gegen den alten Code). Ein weiterer Zwei-Prozess-Test verliert einen
Lease-Fence nach parallelem Staging und beweist, dass sein Cleanup die Datei
des aktiven Workers nicht beruehrt. Stats, Share-Link-Kette, Client-Retry und
Heartbeat-Timing bleiben unveraendert.

**Evidence-Sync committet pro Komponente (2026-08-26):** Der Sweep sammelte
alle Testlaeufe im Speicher und schrieb sie in einer einzigen Transaktion am
Ende. Ein Abbruch — App-Fenster zu, PDB-Aussetzer — verwarf damit die komplette
Arbeit; real beobachtet: 29 von 262 Komponenten gespiegelt, dann Fenster zu,
`test_run_evidence` blieb bei 0 Zeilen, und die UI zeigte folgerichtig jeden
Pflichttest als „missing". Jede Komponente committet jetzt einzeln (der Upsert
ist idempotent), sodass ein abgebrochener Sweep seinen Fortschritt behaelt und
Statusflags waehrend des Laufs fortschreitend erscheinen.

**Evidence-Sync ist inkrementell (2026-08-26):** Der Institutssweep holte
bisher bei jedem Lauf `getTestRun` pro Testlauf — der teuerste Teil, weil ein
HTTP-Roundtrip pro Lauf seriell anfaellt. Jetzt wird pro Lauf ein
Flat-Fingerprint (`passed`, `measured_at`, `state`, `problems`) gegen den
Mirror verglichen; nur veraenderte oder noch nicht detailliert gespiegelte
Laeufe (Marker `detail_synced` im Payload) nehmen den Detail-Roundtrip. Ein
Wiederholungs-Sync kostet damit ~1 Request pro Komponente statt ~1 pro Lauf.
Der Einzelkomponenten-Sync (`POST /api/components/{sn}/sync-evidence`) bleibt
bewusst ein voller Detail-Fetch: Wer ein Modul offen hat, bekommt frische
Daten (z. B. nachtraeglich angehaengte Attachments), auch wenn der Flat-State
gleich blieb. Die Attachment-Phase am Ende des Sweeps war schon vorher
inkrementell (bereits gespeicherte Dateien werden nur referenziert) — sie ist
beim Erstlauf naturgemaess der langsamste Teil, weil dort echte Dateien
uebertragen werden.

**Schneller + ausfallrobuster Sweep (2026-08-26).** Ein realer Evidence-Sweep
brauchte 29 Minuten fuer nur 262 Module (~1336 serielle PDB-Roundtrips a
~1,3 s); mit dem inzwischen erweiterten Scope (~1086 Komponenten inkl.
Sensoren) waere der naechste Volllauf in die Stunden gegangen, und ein
Ausfall mitten in der Attachment-Phase sah wie ein eingefrorener Sync aus.
Fuenf Aenderungen (`app/sync_jobs.py`, `app/attachment_store.py`):

- **Begrenzt paralleler Evidence-Fetch.** Die per-Komponente-Reads
  (`getComponent` + `getTestRun` je Lauf) sind unabhaengige Netzwerk-Reads
  und laufen jetzt in einem kleinen Pool
  (`ITKFLOW_SYNC_FETCH_CONCURRENCY`, Default 4, Bereich 1–16; `1` ist exakt
  das bisherige serielle Verhalten). itkdb-Clients erben von
  `requests.Session` und sind **nicht** threadsicher — jeder Fetch-Worker
  baut sich deshalb aus denselben Access-Codes sein eigenes Gateway
  (`threading.local`); saemtliche DB-Schreibzugriffe (Evidence-Commits pro
  Komponente, Fortschritt/Heartbeat) bleiben auf dem Job-Thread. Ergebnisse
  werden in Einreihungs-Reihenfolge konsumiert: Commits, Fortschritt und der
  Fehlerpunkt sind damit so deterministisch wie beim seriellen Sweep, der
  Speicher bleibt auf die Poolbreite begrenzt, und eine Komponente mit
  erschoepftem Retry-Budget laesst den Job weiterhin transient scheitern
  (inkl. des einen Auto-Retries). Weil die Retry-Leitern jetzt in den
  Workern laufen (die nie in die DB schreiben), schreibt der wartende
  Job-Thread alle `PARALLEL_FETCH_HEARTBEAT_SECONDS` (30 s) einen
  Zwischen-Heartbeat. Scheitert ein Worker terminal, werden noch nicht
  gestartete Futures abgebrochen und bereits laufende Reads mit periodischem
  Job-Heartbeat gejoint, bevor der Job fehlschlaegt oder sein Auto-Retry
  beginnen kann; auch eine lange letzte Retry-Leiter verliert dadurch ihre
  Lease nicht, und kein alter Pool liest parallel zum Nachfolger weiter aus
  der Produktions-PDB.
- **Ein Worker je Job-Art.** Der Manager besitzt jetzt getrennte
  Single-Worker-Executor fuer Komponenten- und Evidence-Jobs: ein
  stundenlanger Evidence-Sweep blockiert keinen Komponenten-Sync mehr.
  Mirror-Schreiber bleiben je Art serialisiert; die eindeutigen
  `active_key`-Leases bleiben der Single-Flight-Guard. Ein Job, der in der
  Queue auf seinen Worker wartet (z. B. Institut B hinter dem Sweep von
  Institut A), bekommt seinen Heartbeat von einem Keeper-Thread alle
  `QUEUED_HEARTBEAT_INTERVAL_SECONDS` (60 s) aufgefrischt, solange der
  besitzende Prozess lebt — sonst haette ihn die Drei-Minuten-Grenze der
  Lease-Uebernahme als verwaist geschlossen. Stirbt der Prozess, bleiben die
  Refreshes aus und die Reaping-Regel greift wie gehabt. Wird ein Job zwar
  angelegt, aber vom Executor nicht angenommen, entfernt der Manager den
  Queue-Watch sofort, terminalisiert die Zeile und gibt die Lease frei; ein
  niemals gestarteter Job kann damit nicht kuenstlich frisch bleiben.
- **Outage-Circuit-Breaker in der Attachment-Phase.** Jeder transiente
  Datei-Fehlschlag hat seine volle Retry-Leiter bereits verbrannt
  (Versuche × bis zu 60 s Read-Timeout + Backoff ≈ Minuten pro Datei);
  mehrere davon **in Folge** bedeuten „die Leitung ist weg", nicht „diese
  Dateien sind kaputt". Nach `ATTACHMENT_OUTAGE_BREAKER_THRESHOLD` (5)
  aufeinanderfolgenden transienten Datei-Fehlschlaegen stoppt die Phase und
  der Job scheitert als `PdbEvidenceUnavailable` (transient) — der
  bestehende einmalige Auto-Retry uebernimmt, statt dass hunderte Dateien
  stundenlang bei null Fortschritt durchkriechen. Alles bereits Gespiegelte
  bleibt committed (idempotente Wiederaufnahme). **Permanente**
  Datei-Antworten (404, HTML-Seite, uebergrosser Body) setzen die Serie
  zurueck und bleiben Best-Effort pro Datei wie bisher. Schlaegt schon der
  Client-Aufbau transient fehl, zaehlen die danach schnell scheiternden
  Dateien ebenfalls als transient, sodass der Breaker den Sweep zuegig
  beendet; ein permanenter Konfigurationsfehler loest ihn nicht aus. Ein lokal
  bereits vorhandener, nur wiederverwendeter Anhang ist fuer den Breaker
  neutral: ohne Netzrequest beweist er keine Erholung und darf die Serie nicht
  zuruecksetzen.
- **Eine Attachment-Planungsrunde statt zwei.** Die Pending-Deskriptoren
  werden einmal pro Komponente in kurzlebigen Sessions gelesen und treiben
  sowohl das Datei-Total als auch die Downloads (`download_attachments`
  nimmt den vorberechneten Plan entgegen). Vorher lud eine einzige Session
  saemtliche Evidence-Zeilen inkl. ~10-KB-Payloads in ihre Identity-Map, nur
  um zu zaehlen — und die Download-Schleife las alles ein zweites Mal. Die
  Attachment-Downloads selbst bleiben bewusst seriell: die Byte-Transfers
  sind nicht der Engpass, und „consecutive" als Breaker-Signal sowie die
  Client-Unavailable-Schnellpfade waeren unter Parallelitaet mehrdeutig.
- **Dauerhafter Component→Evidence-Follow-up.** Eine Evidence-Phase kann ihren
  Komponenten-Scope schon vor dem parallel erfolgreichen Component-Sync
  aufgenommen haben. Der Component-Commit speichert deshalb atomar einen
  privaten Follow-up-Wunsch. Nur ein danach gestarteter und erfolgreicher
  Evidence-Snapshot loescht ihn. Startup und Future-Ende reconciliieren diese
  Generation; eine frische fremde Lease wird nur beobachtet, eine stale Lease
  nur per Heartbeat-CAS uebernommen. Auch die Entscheidung fuer genau einen
  transienten Auto-Retry wird zusammen mit diesem Wunsch dauerhaft
  gespeichert: ein Crash vor dem prozesslokalen Timer verliert den Retry
  nicht, permanente Fehler und ein bereits erschoepfter Retry starten dagegen
  keine Schleife. Die internen Marker werden vom oeffentlichen
  Job-Result-Schema herausgefiltert und tauchen weder in `/active`, `/latest`
  noch Ops-Antworten auf.

Der Background-Executor setzt weiterhin genau **einen FastAPI/Uvicorn-App-
Prozess** voraus (jetzt mit einem Worker-Thread je Job-Art in diesem
Prozess); sowohl `start-itkflow.ps1` als auch das Docker-CMD erfuellen
diesen Vertrag. Mehrere Uvicorn-Worker duerfen erst aktiviert werden, wenn der
Lease einen Prozess-Owner mit Heartbeat/Expiry besitzt und Startup-Recovery
nur verwaiste Jobs dieses Owners schliesst.

## Evidence-Sweep: Index-dann-Bulk statt ein Request pro Komponente (2026-08-27)

**Das gemessene Problem.** Der Institutssweep fragte die PDB einmal *pro
Komponente* (`getComponent`), auch wenn sich nichts geaendert hatte. Am echten
TUDO-Spiegel sind das **1170 Komponenten = 1170 Requests je Sweep**, bei ~1,3 s
pro Request also ~25 min seriell bzw. ~6 min bei der Default-Parallelitaet 4.
Die Ebene *darunter* war laengst inkrementell: von 14 759 gespiegelten Laeufen
tragen alle den Marker `detail_synced`, ein unveraenderter Lauf kostet also
keinen `getTestRun` mehr. Der gesamte verbleibende Aufwand steckte im
Ein-Request-pro-Komponente.

**Die Ablaufform.** Drei Schritte statt einem (`app/pdb_test_evidence.py`,
`app/sync_jobs.py`):

1. **Index** — `listTestRunsByComponent` mit `filterMap.serialNumber` als
   *Liste* vieler Seriennummern liefert die billigen Listendaten aller Laeufe
   dieser Komponenten (Lauf-Id, Testtyp, `passed`/`problems`, `state`,
   Zeitstempel). Bewusst **ohne** `state`-Filter: ein zurueckgezogener Lauf
   (`state='deleted'`) muss genau hier ankommen, weil dies der billige Pfad
   ist, auf dem eine Zurueckziehung ueberhaupt erkannt wird.
2. **Diff** — derselbe `flat_fingerprint`-Vergleich gegen den Mirror wie
   bisher; nur neue oder veraenderte Laeufe brauchen Detail.
3. **Bulk-Detail** — `getTestRunBulk` mit `{"testRun": [id, …]}` holt viele
   Detailobjekte in einem Request. Ids, die die Antwort auslaesst, werden mit
   je einem `getTestRun` nachgeholt — genau der Aufruf, den der
   Pro-Komponente-Pfad ohnehin macht.

**Woher die Endpunkt-Formen stammen.** Aus dem installierten Client selbst:
`backend/.venv/Lib/site-packages/itkdb/client.py::_get_duplicate_test_runs`
baut `filterMap` (`serialNumber`/`code`, `testType`, `stage`, `state`) und ruft
`get("listTestRunsByComponent", json={"filterMap": …})`, liest daraus
`test_run["id"]`, und ruft danach
`get("getTestRunBulk", json={"testRun": test_run_ids})`, wo es `passed`,
`problems`, `id` und `properties` je Eintrag liest. Dass filterMap-Werte
Listen sein duerfen, ist die Konvention, die `app/pdb_sync.py` fuer
`institute`/`currentLocation` bereits nutzt. **Nicht** verifizierbar war
irgendetwas davon gegen eine echte PDB — es gibt keine Testinstanz, und diese
Session darf die Produktion nicht anfassen. Deshalb der naechste Abschnitt.

**Vollstaendigkeit vor Geschwindigkeit: wann der Index geglaubt wird.** Der
Sweep behandelt jede batched Antwort als unbewiesen, bis sie sich selbst
beweist. Faellt eine Pruefung, geht **nur der betroffene Umfang** zurueck auf
den bewaehrten `getComponent`-Pfad — nie wird weniger gespiegelt:

- **Strukturell (ganze Batch unbrauchbar → Rest des Sweeps laeuft pro
  Komponente):** fehlende Lauf-Id, fehlender Testtyp (das Feld `code` wird
  bewusst *nicht* als Ersatz gelesen — auf einem Lauf-Eintrag ist das der Code
  des Laufs, nicht der Testtyp), fehlendes `passed`/`problems` (`_passed`
  wuerde sonst still `False` erfinden, also ein *falsches* Messergebnis),
  ein Eintrag fuer eine **nicht angefragte** Seriennummer (Filter nicht
  honoriert), eine wiederholte Lauf-Id (Zeilenzahl ist kein
  Vollstaendigkeitsbeweis — genau so lief der `useOrInLocationSearch`-Fehler
  durch jede Pruefung), driftende Paginierungs-Metadaten, sowie eine
  metadatenfreie Antwort, die die angeforderte Seitengroesse **exakt fuellt**
  (von einer abgeschnittenen ersten Seite nicht unterscheidbar).
- **Kalibrierungs-Probe (einmal je Sweep, 1 Request):** die erste Komponente
  des ersten Batches wird zusaetzlich per `getComponent` gelesen und Lauf fuer
  Lauf gegen den Index verglichen (Id, Testtyp, `passed`, `measured_at`,
  `state`, `problems`). Weichen sie ab, wird der **ganze** Sweep auf den
  Pro-Komponente-Pfad degradiert. Das ist der einzige Beweis, den man offline
  fuehren kann, dass der Index dasselbe erzaehlt wie der Endpunkt, auf dem der
  ganze Spiegel aufgebaut wurde.
- **Pro Komponente (nur diese eine wird nachgelesen):**
  1. Der Index deckt nicht jeden Lauf ab, den wir als **lebend** gespiegelt
     haben. Zurueckgezogen-worden und vom-Filter-verloren sind von hier aus
     ununterscheidbar, und nur eines davon darf man glauben. Ein bereits als
     `deleted` gespiegelter Lauf ist ausgenommen: dieser Zustand ist terminal,
     sein Fehlen im Index beweist nichts. (Damit heilt sich der Fall selbst,
     falls der Endpunkt geloeschte Laeufe gar nicht ausliefert: der erste
     Sweep liest die betroffene Komponente voll, danach steht `deleted` im
     Spiegel und sie faellt nicht mehr zurueck.) Verschwindet ein Lauf
     dagegen **ganz** aus der PDB — ohne `deleted`-Zustand —, bleibt die
     betroffene Komponente dauerhaft auf dem Pro-Komponente-Pfad; das ist der
     bewusst in Kauf genommene Preis dafuer, „zurueckgezogen" nie zu raten.
     Beobachtet ist dieser Fall nicht: die PDB liefert geloeschte Laeufe
     weiter aus (siehe Abschnitt „Zurueckgezogene Testlaeufe").
  2. Der Index wuerde einen **bekannten** `run_state` oder ein bekanntes
     `measured_at` durch „unbekannt" ersetzen. Ersteres wuerde einen
     zurueckgezogenen Lauf still wieder gueltig machen, letzteres den
     Zeitstempel loeschen, der ueberall entscheidet, welcher Lauf der juengste
     ist.
  3. Der Index meldet **gar keine** Laeufe, obwohl derselbe Batch nie gezeigt
     hat, dass der Mehrfach-Seriennummern-Filter ueberhaupt honoriert wurde.
     Als Beweis genuegt: Laeufe fuer mindestens **zwei verschiedene**
     angefragte Komponenten. „Diese Komponente hat nichts" ist genau die
     Antwort, die ein stillschweigend ignorierter Filter erzeugt — und genau
     die, die in der UI als lauter fehlende Pflichttests erscheint.

Ein **transienter** Ausfall degradiert *nicht*: das waere nur der Weg in
1170 ebenso aussichtslose Einzel-Requests. Nach dem geteilten Retry-Budget
(`ITKFLOW_SYNC_PAGE_MAX_ATTEMPTS`, exponentieller Backoff, Heartbeat vor jedem
Backoff) scheitert der Job ehrlich transient und faellt in den bestehenden
einmaligen Auto-Retry. Nicht-transiente Fehler (Endpunkt existiert hier nicht,
strukturelle Anomalie) degradieren einmal und still — protokolliert wird nur
die eigene, uebersetzte Meldung, nie Upstream-Text: `_safe_page_error_summary`
liefert ausschliesslich „HTTP 404" / „transient network error" /
„non-retryable PDB error", und jedes Re-Raise ist `from None`, weil eine
itkdb-Exception einen gerenderten Auth-Request und damit Access-Codes tragen
kann.

**Bulk-Detail degradiert ebenfalls statt zu luegen.** Nur eine echte Antwort
darf `detail_synced` setzen. Ids, die die Bulk-Antwort auslaesst, werden per
`getTestRun` repariert. Traegt schon der **erste** Bulk-Batch in keinem
einzigen Eintrag Detailfelder, gilt der Endpunkt fuer diesen Job als
nutzlos — der Rest wird per `getTestRun` geholt, statt Laeufe auf ein leeres
Objekt hin als „detailliert gespiegelt" zu markieren und sie damit fuer immer
flach einzufrieren.

**Request-Profil (Zahlen aus dem echten TUDO-Spiegel: 1170 Komponenten im
Sweep-Scope, 14 759 Laeufe, Defaults 50 SN/Index-Request, 100 Eintraege/Seite,
50 Ids/Bulk-Request).**

| Lauf | bisher | neu | Faktor |
|---|---|---|---|
| Wiederholungs-Sweep (nichts geaendert) | 1170 `getComponent` | ~24 Index-Requests, wegen Paginierung ~150–166 Seiten insgesamt, 0 Bulk, 1 Probe | ~7× |
| Erst-Sweep (leerer Spiegel) | 1170 + 14 759 = 15 929 | ~166 Index + ~296 Bulk + 1 Probe ≈ 463 | ~34× |
| Endpunkt nicht nutzbar | 1170 | 1170 + 1 verworfener Index-Request | ~1× (bewusst) |

Bei den Wiederholungs-Sweeps dominiert die **Paginierung**, nicht die
Batch-Groesse: ~12,6 Laeufe je Komponente × 50 Komponenten = ~630 Eintraege je
Batch = ~7 Seiten. Wer den Sweep weiter druecken will, dreht deshalb an
`ITKFLOW_SYNC_EVIDENCE_INDEX_PAGE_SIZE`, nicht an der Batch-Groesse.

**Neue Settings** (alle mit Praefix `ITKFLOW_`, validierte Grenzen):

| Setting | Default | Bedeutung |
|---|---|---|
| `SYNC_EVIDENCE_STRATEGY` | `index_bulk` | `per_component` stellt exakt den bisherigen Sweep wieder her — die Ein-Schalter-Notbremse, weil die batched Endpunkte nicht live verifiziert werden konnten. |
| `SYNC_EVIDENCE_INDEX_BATCH_SIZE` | 50 (1–500) | Seriennummern je `listTestRunsByComponent`-Request. |
| `SYNC_EVIDENCE_INDEX_PAGE_SIZE` | 100 (10–500) | Seitengroesse des Index. Erhoehen senkt die Requestzahl **und** vergroessert den Sicherheitsabstand zur „metadatenfreie Antwort fuellt die Seite exakt"-Regel. |
| `SYNC_EVIDENCE_BULK_BATCH_SIZE` | 50 (1–200) | Lauf-Ids je `getTestRunBulk`-Request; klein gehalten, damit die Reparatur ausgelassener Ids billig bleibt. |

**Warum `index_bulk` der Default ist.** Der einzige Weg, wie der neue Pfad
weniger spiegeln koennte, waere eine Antwort, die *alle* obigen Pruefungen
besteht und trotzdem luegt. Jede Pruefung, die faellt, kostet Requests statt
Daten. Der teuerste Fehlerfall ist exakt das heutige Verhalten. Wer trotzdem
nichts riskieren will, setzt `ITKFLOW_SYNC_EVIDENCE_STRATEGY=per_component`.

**Unveraendert:** Commit-Granularitaet je Komponente (ein abgeschossenes
Fenster verliert nichts Geholtes), monotoner Fortschritt ueber beide Routen
mit einem gemeinsamen Zaehler (jede Komponente zaehlt genau einmal), der
dauerhafte Heartbeat waehrend langer Operationen, das Retry-/Backoff-Budget
samt Heartbeat-Callback, die strikte Fehlersemantik als Futter fuer den
einmaligen Auto-Retry, der Attachment-Circuit-Breaker, und die
Threading-Regel (ein Gateway je Worker-Thread; der Index-Pfad laeuft
ausschliesslich auf dem Job-Thread, `ITKFLOW_SYNC_FETCH_CONCURRENCY` steuert
weiterhin den Pro-Komponente-Pfad). Der Einzelkomponenten-Sync
(`POST /api/components/{sn}/sync-evidence`) bleibt unangetastet ein strikter
Voll-Fetch mit Detail.

**Was nur ein echter PDB-Lauf bestaetigen kann** (offline nicht entscheidbar,
alle mit definiertem sicheren Ausgang):

- ob `listTestRunsByComponent` eine **Liste** von Seriennummern honoriert
  (sonst: Fremd-SN oder unbewiesene Leerantworten → Degradierung);
- ob die Eintraege die Komponente in einer der akzeptierten Formen nennen
  (`serialNumber`, `componentSerialNumber`, `component.serialNumber`,
  `component.alternativeIdentifier`, oder ein String/Code, der in der Batch
  vorkommt) — ein blosser Objekt-Id-String zaehlt bewusst nicht;
- ob sie `state`, `date`/`cts`/`stateTs` und `passed`/`problems` genauso
  tragen wie `getComponent` (sonst schlaegt die Kalibrierungs-Probe an);
- ob **zurueckgezogene** (`deleted`) Laeufe im Index erscheinen;
- ob der Endpunkt das mitgeschickte `pageInfo` im Body akzeptiert und
  Paginierungs-Metadaten zurueckliefert, und ob `getTestRunBulk` paginiert
  (ein abgelehnter Request degradiert, fehlende Ids werden einzeln repariert);
- ob `getTestRunBulk` `results`/`properties`/`attachments` traegt und ob es
  `noEosToken` akzeptiert. Der Bulk-Request sendet das Flag **nicht** (itkdb
  tut es auch nicht); ein etwaiger EOS-Token wird stattdessen von
  `_attachment_summaries` aus der URL gestrippt und der Downloader holt sich
  ohnehin eine frische URL.

## Zeitstempel-Gleichstand im Evidence-Nachlauf (Bugfix 2026-08-27)

`_timestamp_after` vergleicht **strikt** (`>`), und das ist fuer die
*Abdeckungs*-Frage richtig: Ein Gleichstand muss „nicht abgedeckt" bedeuten,
damit die Generation erneut gespiegelt wird — sie faelschlich als abgedeckt zu
werten hiesse, einen Sweep zu ueberspringen und Daten zu verlieren.

Derselbe Helfer entschied aber auch, ob das **Retry-Verdikt** ueberhaupt auf
den Komponenten-Job geschrieben wird. Dort kippte der Gleichstand in die
falsche Richtung: Der Schluessel wurde nie geschrieben, ein fehlender
Schluessel ist weder `due` noch `blocked`, also kehrte
`_reconcile_evidence_followup` zurueck, ohne irgendetwas zu planen — **ein
transient gescheiterter Evidence-Nachlauf verschwand still, bis jemand von
Hand synct.**

Der Gleichstand ist nicht theoretisch: Windows loest die Systemuhr auf rund
**15,6 ms** auf, und ein Komponenten-Sync, der unmittelbar vor der Uebernahme
seines Evidence-Jobs committet, schreibt beide Zeitstempel in denselben Tick.

Behoben: An der Verdikt-Stelle zaehlt der Gleichstand jetzt mit (ein
Komponenten-Job, der genau beim Start des Evidence-Jobs endet, **ist** die
Nachlaufkette), waehrend die Abdeckungs-Stellen strikt bleiben. Beide
Richtungen sind an der Zeile kommentiert — die naheliegende „Vereinheitlichung"
der beiden Vergleiche wuerde den Fehler wieder einbauen.

Gefunden wurde er als vermeintlich flakiger Test. Die Testvorbedingung haengt
deshalb nicht mehr an der Uhr: `_commit_pending_component_generation`
datiert den Commit um fuenf Sekunden zurueck. Vorher scheiterten die
betroffenen Tests etwa in einem Drittel der Laeufe **am korrekten Verhalten** —
und Tests, die grundlos rot werden, bringen ein Team dazu, rote Balken
wegzuerklaeren.

## Attachment-Ausfaelle: pro Remote, nicht global (Bugfix 2026-08-27)

Der Owner meldete: „Der Sync bricht immer bei Step 2 ab." Zweimal exakt bei
**489 von 3839** Dateien — deterministisch, also kein Netzausfall. Am echten
Spiegel nachgemessen:

- Ab Position 487 wechseln die Deskriptoren auf **87 aufeinanderfolgende
  CERNBox-Links**, die alle in **eine** Ordner-Freigabe zeigen
  (`/files/link/public/<token>/<ordner>`).
- CERNBox beantwortet die DAV-Route dafuer mit **HTTP 501 Not Implemented**.
- `is_transient_download_error` hielt jedes 5xx fuer voruebergehend. Also:
  volle Retry-Leiter je Datei, fuenf Fehlschlaege in Folge, **Outage-Breaker
  reisst den ganzen Job ab** — waehrend die PDB einwandfrei antwortete und die
  486 Dateien davor sauber liefen.

Zwei Ursachen, beide behoben:

1. **501/505 sind keine Stoerung, sondern eine Aussage ueber Faehigkeiten.**
   Ein Retry kann daran nichts aendern. `_PERMANENT_5XX_STATUSES` nimmt sie
   aus der transienten Klasse heraus; `app/pdb_sync.py` wurde bewusst
   gleichgezogen, damit die beiden Klassifikationen nicht auseinanderlaufen.
2. **Der Breaker zaehlt jetzt pro Remote** (`descriptor_route`: PDB, EOS,
   Share-Host). Fehlschlaege haeufen sich naturgemaess nach Host, weil
   Anhaenge komponentenweise gruppiert sind — eine globale Strecke konnte
   „das Netz ist weg" nicht von „dieser eine Host antwortet hier nicht"
   unterscheiden. Ein totes Remote wird fuer den Rest des Sweeps
   uebersprungen (seine Dateien scheitern sofort statt je Minuten an
   Retries), und **nur die PDB-Route** laesst den Job scheitern
   (`sweep_is_doomed`). Ein toter Share-Host kostet seine eigenen Dateien und
   sonst nichts; nichts davon wird als gespeichert vermerkt, der naechste
   Sweep versucht es erneut.

**Nachfolgeschnitt abgeschlossen:** Die 87 Deskriptoren sind Ordner-Eintraege;
`/s/<token>/download?files=<name>` liefert ein POSIX-`ustar`, nicht die
Einzeldatei. Der Mirror streamt dieses Archiv ohne `extract`/`extractall`,
akzeptiert nur regulaere sichere Mitglieder innerhalb des benannten Eintrags,
begrenzt Draht-, Dekompressions-, Summengroesse und Anzahl und waehlt
deterministisch das beste echte Bild anhand Magic Bytes und Pfad. Im Beispiel
gewinnt das lexikografisch erste browserfaehige JPEG; CR2/TIFF kann es nicht
verdraengen. Die ausgewaehlten Bytes durchlaufen danach unveraendert
HTML-Abwehr, Groessenlimit, Sniffing und den lease-gefenceten Dateicommit.
Damit werden die frueher fehlenden Bilder im naechsten erfolgreichen
Evidence-Sweep nachgeholt; die vollstaendige Sicherheits- und Auswahlregel
steht in [`12`](12-attachments-and-images.md) §2.3a.

## Unbeaufsichtigter Auto-Sync (`app/auto_sync.py`, 2026-08-27)

Ein Sweep war frueher zu teuer, um ihn auf einen Timer zu legen: ein Request
je Komponente bedeutete 1170 Requests fuer TUDO. Erst Index-dann-Bulk (siehe
oben) druckt einen Wiederholungs-Sweep auf ~150 Requests — **das billige
Primitiv ist der Grund, warum dieser Scheduler ueberhaupt existieren darf**,
nicht umgekehrt.

Es ist die einzige Stelle in itkFlow, an der PDB-Verkehr entsteht, ohne dass
jemand zusieht. Entsprechend eng sind die Grenzen:

- **Opt-in je Institut, in den Admin Settings.** „Wie oft und wann" ist eine
  Institutsentscheidung (harte Regel 4) und steht deshalb im Institutsprofil
  unter `settings["auto_sync"]`, nicht in einer Env-Variable:

  ```json
  {"enabled": false, "interval_minutes": 60,
   "window_start": "22:00", "window_end": "06:00",
   "weekdays": [1, 2, 3, 4, 5]}
  ```

  Fehlt der Block oder steht `enabled: false`, entsteht **kein**
  unbeaufsichtigter Verkehr — das ist der Default. `interval_minutes` ist die
  Mindestwartezeit ab der neueren Grenze aus letztem erfolgreichen Sync und
  letztem Scheduled-Versuch (einschliesslich dessen Auto-Retry); Werte unter **15** werden
  abgelehnt und vom Reader als *aus* behandelt. `weekdays` sind ISO-Nummern (1 = Montag …
  7 = Sonntag), fehlend = jeden Tag. **Der Reader scheitert geschlossen:** ein
  fehlerhafter Block (kaputte `HH:MM`, halbes Fensterpaar, Wochentag ausser
  Bereich) wird als *aus* gelesen statt zu einem Rateergebnis repariert — die
  Validierung im API sagt der Person, was falsch war; ein ratender Reader
  wuerde zu Zeiten syncen, die niemand gewaehlt hat.
  Deployment-seitig bleibt nur `ITKFLOW_AUTO_SYNC_POLL_MINUTES` (Default 5):
  wie oft der Scheduler **auswertet** — eine Datenbankabfrage, kein
  PDB-Verkehr. `0` schaltet den Scheduler ganz ab.
- **Fenster ueber Mitternacht sind der Normalfall, nicht der Sonderfall.**
  `22:00`–`06:00` heisst „nachts, wenn niemand arbeitet"; eine naive
  `start <= jetzt <= end`-Pruefung waere hier immer falsch. Zusaetzlich gilt
  ein Nachtfenster dem **Wochentag, an dem es geoeffnet hat**: Freitag
  22:00–06:00 laeuft um 02:00 am Samstag weiter, sonst wuerde „nur werktags"
  stillschweigend jede halbe Freitagnacht mit abschalten.
- **Zwei Uhren, mit Absicht.** Fenster und Wochentag werden gegen die
  **lokale** Serverzeit geprueft (das ist die Zeit, die die Person gemeint
  hat), das Intervall dagegen gegen **UTC**, weil `finished_at` in UTC
  gespeichert ist. Beides mit einer Uhr zu messen waere um den UTC-Offset
  falsch — im Berliner Sommer zwei Stunden, was ein Nachtfenster lautlos in
  den Vormittag schoebe. Ein Test scheitert, wenn jemand die beiden zusammen-
  legt. **Bewusste Grenze:** das Profil traegt keine benannte Zeitzone; die
  Deployment-Zeitzone ist Teil der Serverkonfiguration. Das Desktop-Bundle
  nutzt die Betriebssystemzeit. Das Compose-Image enthaelt `tzdata` und liest
  `TZ` aus `deploy/.env` (z. B. `Europe/Berlin`); ohne Anpassung gilt der
  sichtbare Default `Etc/UTC`. Vor dem Aktivieren eines Zeitfensters muss `TZ`
  deshalb zur lokalen Institutszeit passen.
- **Er setzt nur fort, was ein Mensch begonnen hat.** Der Scheduler hat keine
  eigenen Credentials. Je Institut laeuft er als die Person, deren **eigener**
  Komponenten-Sync dort zuletzt erfolgreich war — jemand, der das Spiegeln
  dieses Instituts bereits selbst gewaehlt hat. Ein Institut, das nie von Hand
  gesynct wurde, wird nie automatisch gesynct.
- **Er endet von selbst.** Der Credential-Owner muss weiterhin aktiver
  Operator/Admin im passenden Institute-Scope sein. Deaktivierung, Downgrade,
  fremder Scope, geloeschte Codes sowie unbekannter, kaputter oder `invalid`
  Credential-Status stoppen den Zeitplan fuer dieses Institut still.
  `unreachable` stoppt ihn bewusst **nicht** — das heisst nur, dass beim
  letzten Test das Netz weg war, also genau der Fall, fuer den ein spaeterer
  Versuch existiert.
- **Er kann nicht stapeln.** Jobs entstehen ueber dieselbe dauerhafte
  `active_key`-Lease wie in der UI; ein geplanter Lauf konvergiert auf einen
  bereits laufenden Sweep, statt sich dahinter zu haengen.
- **Er liest.** Komponenten-Sync und der daran haengende Evidence-Job (ADR 006)
  sind read-only; `pdb_write_scope="dummy_only"` bleibt unberuehrt, kein
  Schreibpfad fuehrt durch dieses Modul.
- **Er ist ehrlich.** Jobs tragen `scheduled refresh (<email>)` in
  `requested_by` — Marker zuerst, Eigentuemer benannt, weil dessen Zugang die
  PDB erreicht hat. Ein Audit-Trail, der eine unbeaufsichtigte Aktion einer
  Person zuschreibt, waere schlimmer als einer, der sie weglaesst.

**Fairness bei mehreren Instituten:** Die Komponenten-Sync-Lease ist
absichtlich **global** (ein autoritativer Mirror-Fetch zur Zeit im ganzen
Deployment), ein Tick kann also nur **einen** Sweep starten. Bei fester
Reihenfolge wuerde dasselbe Institut jeden Tick gewinnen und ein zweiter
Standort nie aktualisiert. `institutes_by_staleness()` sortiert deshalb nach
„neueste relevante Aktivitaet (Erfolg oder Scheduled-Versuch), aeltester
zuerst"; nie gesyncte Institute sortieren als laengste Wartezeit. Scheduled-
Fehler inklusive Auto-Retry verschieben diese Grenze, damit ein altes
Erfolgsdatum nicht bei jedem Poll neue Jobs erzeugt; manuelle Fehler tun es
bewusst nicht. Kein gespeicherter Cursor, der driften koennte.

## Verifikation

| Stufe | Kommando | Wirkung |
|---|---|---|
| Offline (Default/CI) | `uv run pytest -q` | kein Netz, alle Guards getestet |
| Read-Smoke | `uv run pytest -m pdb_sandbox` | Identität + listComponents, rein lesend |
| Write-E2E | `uv run pytest -m pdb_write` | registriert DUMMY-Modul, Upload + Stage-Move nur darauf |

Der Write-E2E gibt die registrierte SN aus — beim nächsten Lauf über
`ITKFLOW_PDB_WRITE_TEST_SN` wiederverwenden statt neue Teile anzulegen.

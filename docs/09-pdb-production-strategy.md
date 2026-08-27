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
  ([ADR 004](adr/004-personal-pdb-credentials.md)), und Writes bleiben
  `dummy_only` ([ADR 003](adr/003-pdb-dummy-write-scope.md)).

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
— die Bytes landen sofort in einer `.part`-Datei neben ihrem Zielpfad; und
(3) ein kurzer, netzwerkfreier Commit, der die fertigen Dateien atomar
(`os.replace`) umbenennt und die Zeilen upsertet. Ein Fehlschlag hinterlaesst
weder eine `.part`-Leiche noch einen `relative_path`; verwaiste `.part`-Dateien
aus abgestuerzten Laeufen werden ueberschrieben. Ein Regressionstest schreibt
waehrend des simulierten Fetches ueber eine zweite unabhaengige
`sqlite3`-Verbindung und beweist, dass nichts mehr blockiert (reproduzierbar
rot gegen den alten Code). Stats, Share-Link-Kette, Client-Retry und
Heartbeat-Timing unveraendert.

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
Vier Aenderungen (`app/sync_jobs.py`, `app/attachment_store.py`):

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
  Zwischen-Heartbeat.
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
  Refreshes aus und die Reaping-Regel greift wie gehabt.
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
  beendet; ein permanenter Konfigurationsfehler loest ihn nicht aus.
- **Eine Attachment-Planungsrunde statt zwei.** Die Pending-Deskriptoren
  werden einmal pro Komponente in kurzlebigen Sessions gelesen und treiben
  sowohl das Datei-Total als auch die Downloads (`download_attachments`
  nimmt den vorberechneten Plan entgegen). Vorher lud eine einzige Session
  saemtliche Evidence-Zeilen inkl. ~10-KB-Payloads in ihre Identity-Map, nur
  um zu zaehlen — und die Download-Schleife las alles ein zweites Mal. Die
  Attachment-Downloads selbst bleiben bewusst seriell: die Byte-Transfers
  sind nicht der Engpass, und „consecutive" als Breaker-Signal sowie die
  Client-Unavailable-Schnellpfade waeren unter Parallelitaet mehrdeutig.

Der Background-Executor setzt weiterhin genau **einen FastAPI/Uvicorn-App-
Prozess** voraus (jetzt mit einem Worker-Thread je Job-Art in diesem
Prozess); sowohl `start-itkflow.ps1` als auch das Docker-CMD erfuellen
diesen Vertrag. Mehrere Uvicorn-Worker duerfen erst aktiviert werden, wenn der
Lease einen Prozess-Owner mit Heartbeat/Expiry besitzt und Startup-Recovery
nur verwaiste Jobs dieses Owners schliesst.

## Verifikation

| Stufe | Kommando | Wirkung |
|---|---|---|
| Offline (Default/CI) | `uv run pytest -q` | kein Netz, alle Guards getestet |
| Read-Smoke | `uv run pytest -m pdb_sandbox` | Identität + listComponents, rein lesend |
| Write-E2E | `uv run pytest -m pdb_write` | registriert DUMMY-Modul, Upload + Stage-Move nur darauf |

Der Write-E2E gibt die registrierte SN aus — beim nächsten Lauf über
`ITKFLOW_PDB_WRITE_TEST_SN` wiederverwenden statt neue Teile anzulegen.

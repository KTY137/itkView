# PDB-Strategie: Produktions-PDB mit DUMMY-Schreib-Scope

> Verbindlich seit 2026-07-08. Ersetzt die Testinstanz-Annahme aus der
> Anfangsphase (harte Regel #2 in CLAUDE.md wurde entsprechend neu gefasst).
> Entscheidung als ADR: `docs/adr/003-pdb-dummy-write-scope.md`.

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
   Access-Codes sind kein Runtime-Fallback (ADR 004).
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
  wenn eine Person ihre persoenlichen Access-Codes verbindet (ADR 004), und
  Writes bleiben `dummy_only` (ADR 003).

## Ring-Module / Halbmodule

R3–R5-Module sind Split-Module: Halbmodule (z. B. `R5M0`, `R5M1`) werden auf
ein Ring-Modul assembliert (zeuthenflow: `DBHalfModule`/`DBRingModule`,
Assemblierung über `assembleComponent` mit parent=Ring-SN). In der PDB ist das
eine normale Parent/Child-Beziehung — unser Mirror (`parent_sn` aus dem
`parents`-Array von `listComponents`) und der Family-Tree im UI bilden das
bereits ab. Für DUMMY-Tests registrieren wir einzelne (Halb-)Module; eine
Ring-Assemblierung von DUMMY-Teilen ist möglich, aber nicht Teil des E2E.

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
unerreichbare Komponente laesst den Job weiterhin ehrlich scheitern.

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

Der Background-Executor setzt derzeit genau **einen FastAPI/Uvicorn-App-
Prozess** voraus; sowohl `start-itkflow.ps1` als auch das Docker-CMD erfuellen
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

# ADR 002: Asynchroner Outbox-Worker fuer PDB-Writes

## Status

Angenommen am 2026-07-08. Baut auf [ADR 001](001-outbox-status-contract.md) auf.

## Kontext

Der Outbox-Statusvertrag (ADR 001) definiert *wann* eine Aktion PDB-wirksam
werden darf, aber nicht *wer* den tatsaechlichen Schreib-Call ausfuehrt. Bisher
setzte der `submitted`-Uebergang nur den Status; es fand kein PDB-Write statt.

Zwei Muster standen zur Wahl: synchroner Write im Request-Handler oder ein
asynchroner Hintergrund-Worker. Der Revamp-Plan ([`docs/02-revamp-plan.md`](../02-revamp-plan.md))
nennt Outbox/Queue mit Retry als Kernidee und sieht einen `worker`-Container
vor. Ein synchroner Write koppelt den HTTP-Request an die PDB-Latenz und
hinterlaesst bei Timeout/Absturz einen unklaren Zustand.

## Entscheidung

Ein eigenstaendiger asynchroner Worker (`app/run_worker.py`, `worker`-Service in
`deploy/docker-compose.yml`) ist der einzige Prozess, der reviewte Aktionen in
die PDB schreibt. Produktionszugriff und DUMMY-Scope folgen
[ADR 003](003-pdb-dummy-write-scope.md). Welcher Prozess in welcher
Betriebsart tatsaechlich draint, steht in
[`docs/11-logistics-operations.md`](../11-logistics-operations.md).

- **Zustaendigkeit:** Der Worker beansprucht Aktionen in `approved` (frisch
  freigegeben), `submitted` (Crash-Recovery: `external_ref` bereits gesetzt
  bedeutet bereits geschrieben) und **direkt auch `failed`** — aber nur
  transiente, an `PDB unavailable:` erkennbare Fehler, und erst wenn ihr
  exponentielles Backoff abgelaufen ist (`retry_ready()` in
  `app/outbox_worker.py`). Menschen fuehren nur bis `approved`; das UI muss
  weder Submit/Confirm noch einen Failed-Retry manuell ausloesen. Ein
  `failed → submitted` per `POST /api/outbox/{id}/transition` bleibt als
  Notausgang moeglich (z. B. um einen nicht-transienten, nach Korrektur wieder
  gueltigen Fehler erneut zu versuchen), ist aber kein Teil des normalen
  Ablaufs.
- **Ein-Prozess-Deployments (Ergaenzung 2026-08-26):** `Settings.outbox_processor`
  waehlt, wer drainet: `"worker"` (Compose startet `app.run_worker` als
  eigenen Service, Default), `"app"` (die API drained sich selbst ueber
  `app/outbox_processor.py::OutboxProcessor`, einen Asyncio-Task im selben
  Prozess) oder `"off"` (niemand, Tests). Genau ein Prozess darf drainen;
  Aktionen werden transaktional beansprucht, eine Fehlkonfiguration kann
  dieselbe Aktion nicht doppelt schreiben. Desktop-Bundle
  (`backend/app/desktop_server.py`) setzt `"app"`, weil das Einzelprozess-Paket
  keinen separaten Worker mitbringt — ohne das bliebe eine freigegebene Aktion
  fuer immer bei `submitted` stehen. Der Dev-Launcher laesst den Drain bewusst
  aus (Default bleibt `"worker"`, ohne dass dort ein Worker-Prozess laeuft);
  manuelles `python -m app.run_worker --once` bleibt der bewusste Handgriff,
  eine Entwicklungssession trotzdem einmal draining zu lassen.
- **Ablauf je Aktion** (`app/outbox_worker.py`): `approved → submitted`
  (attempts++) → Dry-Run erneut gegen den *aktuellen* Mirror pruefen → Submitter
  aufrufen → `confirmed` (mit `external_ref`) oder `failed`.
- **Gebundene PDB-Identitaet (Ergaenzung 2026-08-24):** Beim menschlichen
  Uebergang nach `approved` wird `OutboxPdbPrincipal` mit User-ID und Snapshot
  der persoenlichen PDB-Identity angelegt. Der Worker laedt bei jedem Versuch
  genau die aktuelle, verifizierte `PdbCredential` dieses Users, entschluesselt
  sie kurzzeitig und vergleicht die Identity. Creator, anderer Approver und
  Server-Env-Codes sind kein Fallback; damit behalten auch Retries dieselbe
  handelnde PDB-Identitaet (ADR 004).
- **Injizierter Submitter:** Der PDB-Write ist ein `Submitter`-Callable. Die
  Offline-Tests injizieren einen Fake; der reale `app/pdb_submit.py` ruft
  `uploadTestRunResults` ueber einen operation-lokalen `PdbGateway` mit der
  gebundenen persoenlichen Credential. Fehlt die Bindung, ist sie ungueltig
  oder stimmt die Identity nicht mehr, scheitert die Aktion geschlossen mit
  `PdbSubmitUnavailable`.
- **Idempotenz:** `OutboxAction.external_ref` haelt die PDB-Run-ID. Eine Aktion
  mit gesetztem `external_ref` gilt als *bereits geschrieben* und wird ohne
  zweiten Submit auf `confirmed` gesetzt (deckt Crash-nach-Write ab).
- **Fehlerklassen:** Ein `PdbSubmitUnavailable` (Write konnte nicht versucht
  werden) wird als *transient* auditiert, eine PDB-*Ablehnung* der Daten als
  fachlicher Fehler — unterschiedlich, weil nur beim transienten Fall sicher
  nichts geschrieben wurde.

## Konsequenzen

- Nichts schreibt in die PDB ausser dem Worker ueber einen `Submitter`.
- Der HTTP-Pfad bleibt frei von PDB-Latenz; Ausfaelle sind sichtbar und
  wiederaufnehmbar statt „vielleicht passiert".
- Automatischer Retry mit exponentiellem Backoff und Max-Attempts-Cap ist
  umgesetzt. Offen bleibt die reale Idempotenz-Pruefung gegen die PDB fuer den
  Crash-nach-Write-Fall.
- Raw-Upstream-Exceptions duerfen nicht in Action-Fehler oder Logs gelangen:
  `itkdb` kann Auth-Requests inklusive Access-Codes rendern. Der reale Submitter
  verwendet deshalb feste, sanitierte Fehlermeldungen.

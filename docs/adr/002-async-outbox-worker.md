# ADR 002: Asynchroner Outbox-Worker fuer PDB-Writes

## Status

Angenommen am 2026-07-08. Baut auf [ADR 001](001-outbox-status-contract.md) auf.

## Kontext

Der Outbox-Statusvertrag (ADR 001) definiert *wann* eine Aktion PDB-wirksam
werden darf, aber nicht *wer* den tatsaechlichen Schreib-Call ausfuehrt. Bisher
setzte der `submitted`-Uebergang nur den Status; es fand kein PDB-Write statt.

Zwei Muster standen zur Wahl: synchroner Write im Request-Handler oder ein
asynchroner Hintergrund-Worker. Der Revamp-Plan (`docs/02-revamp-plan.md`)
nennt Outbox/Queue mit Retry als Kernidee und sieht einen `worker`-Container
vor. Ein synchroner Write koppelt den HTTP-Request an die PDB-Latenz und
hinterlaesst bei Timeout/Absturz einen unklaren Zustand.

## Entscheidung

Ein eigenstaendiger asynchroner Worker (`app/run_worker.py`, `worker`-Service in
`deploy/docker-compose.yml`) ist der einzige Prozess, der reviewte Aktionen in
die PDB-Testinstanz schreibt.

- **Zustaendigkeit:** Der Worker beansprucht Aktionen in `approved` (frisch
  freigegeben) und `submitted` (Crash-Recovery oder manueller
  `failed → submitted`-Retry). Menschen fuehren nur bis `approved`; das UI muss
  Submit/Confirm nicht mehr manuell ausloesen.
- **Ablauf je Aktion** (`app/outbox_worker.py`): `approved → submitted`
  (attempts++) → Dry-Run erneut gegen den *aktuellen* Mirror pruefen → Submitter
  aufrufen → `confirmed` (mit `external_ref`) oder `failed`.
- **Injizierter Submitter:** Der PDB-Write ist ein `Submitter`-Callable. Die
  Offline-Tests injizieren einen Fake; der reale `app/pdb_submit.py` ruft
  `uploadTestRunResults` ueber den `PdbGateway` (Testinstanz-only, itkdb lazy)
  und ist ohne konfigurierte Access-Codes inaktiv (`PdbSubmitUnavailable`).
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
- Offene Punkte fuer den naechsten Schritt: automatischer Retry mit Backoff fuer
  transiente Fehler (heute nur manuell via `failed → submitted`), ein
  Max-Attempts-Cap durchsetzen (`worker_max_attempts` existiert, wird noch nicht
  erzwungen), und die reale Idempotenz-Pruefung gegen die PDB, bevor der
  `submitted`-Recovery-Pfad gegen die Testinstanz scharf geschaltet wird.
- Der reale Submitter ist bewusst noch nicht gegen die Sandbox verifiziert
  (Test-URL aufloesbar + Tokens noetig); er bleibt bis dahin ueber die
  fehlende Konfiguration inaktiv.

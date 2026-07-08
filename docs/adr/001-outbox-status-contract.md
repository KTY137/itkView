# ADR 001: Outbox-Statusvertrag

## Status

Angenommen am 2026-07-08.

## Kontext

PDB-wirksame Aktionen duerfen nicht direkt aus Request-Handlern oder UI-Actions
geschrieben werden. Sie laufen ueber die Outbox mit Auditspur. Damit UI,
spaetere Worker und Reviews dieselbe Statusmaschine verwenden, darf die
Transition-Logik nicht parallel in mehreren Clients gepflegt werden.

## Entscheidung

Die Backend-Datei `backend/app/outbox.py` ist die Quelle der Wahrheit fuer:

- alle Outbox-Statuswerte,
- erlaubte Statusuebergaenge,
- Terminalzustaende,
- Fehlermeldungen bei ungueltigen Uebergaengen.

Der Endpoint `GET /api/outbox/contract` veroeffentlicht diesen Vertrag als
JSON fuer Frontend und spaetere Worker. Clients duerfen lokale Defaults nur als
Offline-/Demo-Fallback verwenden. Jede echte Transition laeuft weiterhin ueber
`POST /api/outbox/{action_id}/transition`, wo der Backend-Vertrag erneut
validiert und ein Audit-Event geschrieben wird.

Ingestion-Dateien duerfen PDB-wirksame Uploads ebenfalls nicht direkt ausloesen.
`POST /api/ingest/files/{id}/propose-outbox` erstellt nur einen
`upload_test_run`-Draft mit `dry_run_required: true` und verknuepft ihn mit der
Inbox-Datei. Submission, Dry-Run und PDB-Write bleiben spaeteren Outbox-Worker-
Schritten vorbehalten.

## Konsequenzen

- Frontend-Buttons entstehen aus dem Backend-Vertrag statt aus duplizierter
  Transition-Logik.
- Spaetere Worker koennen denselben Contract lesen oder direkt `app.outbox`
  importieren.
- Neue Statuswerte oder Uebergaenge brauchen Tests fuer `app.outbox`, den
  Contract-Endpoint und mindestens einen UI-/Client-Fallback-Check.
- Dry-Run-, Review- und Worker-Semantik bauen auf diesem Vertrag auf, ersetzen
  ihn aber nicht.

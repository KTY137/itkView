# ADR 004: Persoenliche PDB-Verbindung pro itkFlow-Konto

## Status

Angenommen am 2026-08-24. Ergaenzt [ADR 002](002-async-outbox-worker.md) und
[ADR 003](003-pdb-dummy-write-scope.md). Produktseite und Rollen:
[`docs/06-users-roles-audit.md`](../06-users-roles-audit.md); Betrieb und
Env-Setup: [`docs/09-pdb-production-strategy.md`](../09-pdb-production-strategy.md).

## Kontext

Die bisherige Laufzeitkonfiguration hielt ein einziges Paar
`ITKFLOW_ITKDB_ACCESS_CODE1/2`. Damit liefen Syncs und Worker-Writes unter der
Person, der diese Server-Keys gehoerten, unabhaengig vom angemeldeten
itkFlow-Konto. Das verletzt Attribution und Mandantentrennung.

Der eingesetzte Client `itkdb 0.6.20` bietet keinen Browser-OAuth-Redirect,
keinen PKCE-/Device-Flow und keinen Refresh-Token. Er authentifiziert ein
persoenliches Plus4U/PDB-Access-Code-Paar serverseitig am `grantToken`-Endpoint.
Die Produktbezeichnung lautet deshalb bewusst **Personal PDB connection** und
nicht Browser-OAuth.

## Entscheidung

- Jedes aktive lokale `User`-Konto kann genau eine eigene `PdbCredential`
  verbinden. Eine PDB-Identitaet ist ueber alle lokalen Konten eindeutig.
- `PUT /api/account/pdb-connection` prueft das neue Paar zuerst read-only gegen
  `getUser`. Erst danach ersetzt es den bisherigen Ciphertext. Ein fehlgeschlagener
  Ersatz laesst die alte Verbindung unveraendert.
- Bei institutsgebundenen lokalen Konten muss der PDB-User Mitglied desselben
  Institutscodes sein. Globale Legacy-/Admin-Konten ohne Institut bleiben
  zulaessig.
- Die Codes werden als versionierter `v1`-Payload mit AES-256-GCM, zufaelligem
  12-Byte-Nonce und AAD `itkflow:pdb:v1:user:{user_id}` verschluesselt. Ein
  Ciphertext kann daher nicht unbemerkt in die Zeile eines anderen Users
  verschoben werden.
- Der 32-Byte-Master-Key kommt ausschliesslich aus
  `ITKFLOW_PDB_CREDENTIAL_ENCRYPTION_KEY`. Er liegt nicht in Datenbank, Repo,
  API-Antworten oder Logs. Der Windows-Launcher erzeugt ihn einmal unter
  `%LOCALAPPDATA%\itkflow\pdb-credential.key`; Backend und separater Worker
  muessen denselben stabilen Key erhalten.
- Die Account-API liefert nur Statusmetadaten: Zustand, Instanz, PDB-Identity,
  Institute und Zeitstempel. Codes und Ciphertext werden nie zurueckgegeben.
  Testen aktualisiert `verified|invalid|unreachable`; Disconnect loescht die
  lokale Zeile. Eine Remote-Token-Revoke-Funktion existiert im Client nicht.
- Web-PDB-Reads erzeugen fuer jede Operation einen neuen `PdbGateway` mit den
  Codes des angemeldeten Users. Es gibt keinen Fallback auf Deployment-Codes
  und keinen useruebergreifenden Client-/Token-Cache.
- Ein Background-Komponentensync speichert nur `SyncJob.user_id`; der Worker-
  Thread laedt die Codes des Startenden aus einer frischen Session. Queue und
  Fortschrittsdatensatz bleiben secret-frei.
- Beim Uebergang einer Outbox-Aktion nach `approved` wird eine separate
  `OutboxPdbPrincipal`-Zeile mit User-ID und PDB-Identity-Snapshot gebunden.
  Der Worker laedt bei jedem Versuch genau deren aktuelle, verifizierte
  Credential und vergleicht die Identity. Creator, globale Server-Codes oder
  ein anderer Approver sind kein Fallback; Retries behalten dieselbe Identitaet.
- Upstream-Exceptions werden nie roh formatiert oder geloggt. `itkdb` kann in
  einer `ResponseException` die komplette `grantToken`-Anfrage inklusive Codes
  rendern; API, Sync-Job und Submitter geben deshalb nur feste, sanitierte
  Fehlerklassen aus.

Deployment-weite Access-Codes bleiben ausschliesslich Eingabe explizit
markierter manueller PDB-Integrationstests. Sie sind kein Produktpfad.

## Konsequenzen

- Eine gestohlene Datenbank allein enthaelt nur authentifizierten Ciphertext.
  Wer Datenbank **und** Master-Key kompromittiert, kann Codes entschluesseln;
  der Key gehoert daher in Secret-Management/gesichertes Backup.
- Key-Verlust macht bestehende Verbindungen unlesbar. In-Place-Keyrotation ist
  ohne Re-Encryption-Migration nicht zulaessig; Nutzer muessen sonst neu
  verbinden.
- Bestehende globale `.env`-Codes werden nicht automatisch einem User
  zugeordnet. Nach dem Rollout verbindet jede Person ihr Paar selbst im
  Account-Screen.
- Deaktivierte lokale User koennen ihre gespeicherte Verbindung weder laden
  noch verwenden. Historische Audit-/Outbox-Attribution bleibt erhalten.

## Verworfene Alternativen

- **Ein gemeinsamer Instituts-/Server-Account:** einfache Bedienung, aber
  falsche PDB-Attribution und keine Kontentrennung.
- **Codes im Browser/localStorage:** XSS-/Leak-Risiko und keine sichere
  Background-Worker-Nutzung.
- **`itkdb.save_auth`:** serialisiert User, Codes und Tokens zusammen und ist
  fuer einen Multi-User-Webdienst ungeeignet.
- **Vorgeblicher OAuth-Callback:** wird vom verwendeten PDB-Client nicht
  angeboten und waere eine irrefuehrende Sicherheitsbehauptung.

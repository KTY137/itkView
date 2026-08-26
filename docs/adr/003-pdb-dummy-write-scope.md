# ADR 003: PDB-Writes nur gegen eigene DUMMY-Testkomponenten

Status: akzeptiert (2026-07-08)

## Kontext

Die PDB-Testinstanz, auf der das ursprüngliche Sicherheitsmodell basierte
(ADR 002 setzte sie für Worker-Writes voraus), existiert nicht mehr. Der
Supervisor hat den für Strips sanktionierten Weg benannt: Testteile werden in
der **produktiven** PDB über den `DUMMY`-Batch-Präfix von der Produktion
getrennt; Hybride/Module dürfen dafür frei registriert werden, Sensoren/ASICs
niemals (keine Dummy-SN-Vergabe).

## Entscheidung

1. itkFlow spricht die produktive PDB an: Reads hinter dem bestehenden
   doppelten Env-Opt-in, Writes zusätzlich hinter
   `pdb_write_scope=dummy_only` (Default).
2. Das Write-Gate ist das Mirror-Flag `is_dummy`: der reale Submitter lehnt
   jede Aktion ab, deren Ziel-SN nicht als DUMMY-Komponente gespiegelt ist
   (`app/pdb_scope.py`). Das Flag entsteht nur durch itkFlow-eigene
   Registrierung (`register_dummy_component`, Allowlist Module/Hybride,
   Batch `DUMMY_<Institut>`) oder durch `dummy=true` aus der PDB selbst.
3. `unrestricted` bleibt unimplementiert; echte Produktions-Writes erfordern
   eine spätere, eigene Freigabestufe.
4. Verifikation dreistufig: Offline-Suite (Fakes), `pdb_sandbox` (read-only
   Smoke), `pdb_write` (DUMMY-E2E, nur mit `ITKFLOW_ALLOW_PDB_WRITES=true`).
5. Eine Assembly veraendert die Beziehung von **zwei** Komponenten. Deshalb
   pruefen Worker und realer Submitter Parent und Child samt Typ. Der harte
   Submitter-Guard laeuft vor dem Aufbau eines authentifizierten PDB-Clients
   und akzeptiert ausschliesslich itkFlow-registrierte DUMMY-Module/-Hybride;
   Sensoren und ASICs bleiben auch bei manipuliertem Payload/Flag gesperrt.

## Konsequenzen

- Die Worker-/Outbox-Architektur aus ADR 002 bleibt unverändert; nur die
  Submitter-Vorbedingungen wurden verschärft (Scope-Check vor Client-Aufbau,
  Ablehnung als fachliche Rejection ohne Retry).
- Harte Regel #2 in [`CLAUDE.md`](../../CLAUDE.md) wurde neu gefasst; Details in
  [`docs/09-pdb-production-strategy.md`](../09-pdb-production-strategy.md).
- Der Sync darf produktive Daten lesen; damit läuft das komplette lokale
  Cockpit (Board/Detail/Stage-Engine) erstmals mit echten Instituts-Daten.
- `assemble_component` wird zuerst lokal als servervalidierter Outbox-Draft
  erzeugt. Der Worker wiederholt Dry-run und Snapshot-Pruefung; es gibt keinen
  direkten PDB-Aufruf aus Wizard oder Request-Handler.

## Ergänzung (2026-08-26): Offline-Default, Reads ab Werk

Die tote Testinstanz wurde aus der Konfiguration entfernt: `pdb_instance` ist
jetzt `offline` (Code-Default, erreicht nichts) oder `production`. Die
Endnutzer-Artefakte (Desktop-Bundle, Compose) setzen die beiden
Read-Opt-ins ab Werk — Owner-Entscheidung, damit kein Institut Env-Variablen
nachkonfigurieren muss. Alle uebrigen Schichten dieses ADRs (persoenliche
Credentials als Traffic-Gate, `dummy_only`-Write-Scope, keine
Produktions-Writes) bleiben unveraendert. Details:
[docs/09](../09-pdb-production-strategy.md), Abschnitt „Offline-Default und
Reads ab Werk".

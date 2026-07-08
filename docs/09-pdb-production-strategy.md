# PDB-Strategie: Produktions-PDB mit DUMMY-Schreib-Scope

> Verbindlich seit 2026-07-08. Ersetzt die Testinstanz-Annahme aus der
> Anfangsphase (harte Regel #2 in CLAUDE.md wurde entsprechend neu gefasst).
> Entscheidung als ADR: `docs/adr/003-pdb-dummy-write-scope.md`.

## Ausgangslage

- **Es gibt keinen PDB-Test-Server.** Die historische Testinstanz
  (`itkpd-test.unicorncollege.cz`) existiert nicht mehr; die Default-
  Konfiguration von itkFlow zeigt weiter dorthin und erreicht damit bewusst
  gar nichts.
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
2. **Schreib-Scope:** `ITKFLOW_PDB_WRITE_SCOPE=dummy_only` (Default). Der
   Submitter (`backend/app/pdb_submit.py`) verweigert jede Schreibaktion
   (Test-Run-Upload, Stage-Move), deren Ziel-SN nicht im lokalen Mirror mit
   `is_dummy=True` steht (`backend/app/pdb_scope.py::is_dummy_target`).
   Dieses Flag setzt nur itkFlow selbst beim Registrieren eigener
   DUMMY-Teile (bzw. der Sync, wenn die PDB `dummy=true` meldet).
   ⇒ Writes auf echte Produktionsteile sind technisch unmöglich.
3. **Registrierung:** einzig über
   `pdb_submit.register_dummy_component(...)` — Komponententyp muss auf der
   Allowlist stehen (`ITKFLOW_PDB_DUMMY_COMPONENT_TYPES`, Default
   `["MODULE","HYBRID"]`; alles andere, insbesondere Sensoren/ASICs, wird
   abgelehnt), Teil landet immer im Batch `DUMMY_<Institut>` (wird bei Bedarf
   angelegt). Payload-Form folgt der zeuthenflow-Referenz
   (`registerComponent` mit project/subproject/institution/componentType/
   type/properties; Batch separat via `listBatches`/`createBatch`/
   `addBatchComponent`).
4. `unrestricted` ist als Scope-Wert bekannt, wird aber im Code abgelehnt —
   echte Produktions-Writes brauchen später einen eigenen, bewussten
   Freigabeschritt.
5. Die Offline-Testsuite bleibt netzwerkfrei; alle Guards sind mit Fakes
   getestet (`tests/test_pdb_scope.py`, `tests/test_outbox_worker.py`).

## Ring-Module / Halbmodule

R3–R5-Module sind Split-Module: Halbmodule (z. B. `R5M0`, `R5M1`) werden auf
ein Ring-Modul assembliert (zeuthenflow: `DBHalfModule`/`DBRingModule`,
Assemblierung über `assembleComponent` mit parent=Ring-SN). In der PDB ist das
eine normale Parent/Child-Beziehung — unser Mirror (`parent_sn` aus dem
`parents`-Array von `listComponents`) und der Family-Tree im UI bilden das
bereits ab. Für DUMMY-Tests registrieren wir einzelne (Halb-)Module; eine
Ring-Assemblierung von DUMMY-Teilen ist möglich, aber nicht Teil des E2E.

## Betrieb: Env-Setup (backend/.env, niemals committen)

```
ITKFLOW_PDB_INSTANCE=production
ITKFLOW_ALLOW_PRODUCTION=true
ITKFLOW_ITKDB_ACCESS_CODE1=…
ITKFLOW_ITKDB_ACCESS_CODE2=…
# Nur für den Write-E2E, bewusst setzen und danach entfernen:
# ITKFLOW_ALLOW_PDB_WRITES=true
# Nach dem ersten Lauf: registrierte DUMMY-SN wiederverwenden:
# ITKFLOW_PDB_WRITE_TEST_SN=20U…
```

## Verifikation

| Stufe | Kommando | Wirkung |
|---|---|---|
| Offline (Default/CI) | `uv run pytest -q` | kein Netz, alle Guards getestet |
| Read-Smoke | `uv run pytest -m pdb_sandbox` | Identität + listComponents, rein lesend |
| Write-E2E | `uv run pytest -m pdb_write` | registriert DUMMY-Modul, Upload + Stage-Move nur darauf |

Der Write-E2E gibt die registrierte SN aus — beim nächsten Lauf über
`ITKFLOW_PDB_WRITE_TEST_SN` wiederverwenden statt neue Teile anzulegen.

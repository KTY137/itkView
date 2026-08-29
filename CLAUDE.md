# itkFlow — ITk Production Webapp

Webapp, die den Google-Sheet+CERNBox+zFlow-Workflow der ATLAS-ITk-Strip-Modulproduktion ersetzt.
Multi-Institut (TUDO, DESYZ, …), die ITk Production Database (PDB) bleibt Source of Truth.
Pläne: `docs/01-ist-analyse-zeuthenflow.md`, `docs/02-revamp-plan.md`,
Roadmap: `docs/04-roadmap.md`, UI-Design: `docs/05-ui-design-reference.md`,
Team: `docs/03-agent-team.md`.

## Startkontext (Pflicht)

1. Vor groesserer Planung oder Implementierung `docs/04-roadmap.md` lesen.
2. Arbeit dem naechsten passenden aktiven Meilenstein zuordnen.
3. Keinen konkurrierenden Roadmap-Plan im Chat erfinden, wenn die Roadmap existiert:
   stattdessen `docs/04-roadmap.md` aktualisieren oder im Abschluss klar notieren,
   welcher Roadmap-Punkt betroffen ist.
4. Vor UI-Arbeit `docs/05-ui-design-reference.md` (+ Mockup) lesen und nicht vom
   Design-Ziel abdriften. Layout/Interaktion uebernehmen, Labels bleiben Englisch.
5. **Vor jeder Arbeit am Produktionsablauf zuerst das lebende Google-Sheet lesen**,
   nicht die Abschrift. Der Drive-Connector ist verbunden; massgeblich ist
   „Production Overview TU Dortmund"
   (`1Qw2RLTFfhCIKJhXrmbtF74DF5ozwXkak6CTjsg4EoXs`), daneben Zeuthens
   „Production Overview" (`1oTtKDJ8cFc1RGqU0lU--XhF9tjvBD6CcrTEPePFJMk8`).
   Die Dateien in `docs/superpowers/research/` sind **Momentaufnahmen** —
   `2026-08-27-tudo-sheet-live.md` schlaegt die aeltere Screenshot-Abschrift,
   und beide schlaegt das Blatt selbst. Wer ohne diesen Blick plant, driftet:
   drei Annahmen dieses Projekts (R2H0, die Ohren-Formel, die angeblich
   fehlende Metrologie) waren genau so entstanden. Das Blatt ist gross
   (~200k Zeichen) — in einem Subagenten lesen, nicht im Hauptkontext.
   Keine Klarnamen aus dem Blatt ins Repo.

## Harte Regeln (gelten für ALLE Agenten)

1. **`references/zeuthenflow` NIEMALS ausführen oder importieren** — nur mit Read/Grep lesen.
   Schon ein Import baut DB-Verbindungen auf. Der Ordner ist eine anonymisierte Lese-Referenz
   (siehe `references/zeuthenflow/ANONYMIZATION.md`); sein `.git` enthält noch Originaldaten — nicht anfassen.
2. **PDB-Schutzmodell (es gibt keine Testinstanz mehr).** Der Code-Default ist
   `pdb_instance=offline` und erreicht keine PDB — das gilt für Dev, Tests und jede
   Agenten-Session; **Agenten setzen die Produktions-Opt-ins (`ITKFLOW_PDB_INSTANCE=production`
   + `ITKFLOW_ALLOW_PRODUCTION=true`) niemals selbst.** Die ausgelieferten Endnutzer-Artefakte
   (Desktop-Bundle, Compose) aktivieren Produktions-**Reads** ab Werk (Owner-Entscheidung
   2026-08-26, docs/09); PDB-Traffic entsteht trotzdem erst, wenn eine Person ihre
   persönlichen Access-Codes verbindet. **Schreiboperationen ausschließlich gegen von itkFlow
   selbst registrierte DUMMY-Batch-Testkomponenten** (nur Module/Hybride; **niemals Sensoren
   oder ASICs registrieren** — dafür gibt es keinen Dummy-Mechanismus, das korrumpiert
   Seriennummern). Technisch erzwungen via `pdb_write_scope=dummy_only`
   (`backend/app/pdb_scope.py`); echte Produktions-Writes sind bewusst nicht implementiert.
   Details: `docs/09-pdb-production-strategy.md`, `docs/adr/003-pdb-dummy-write-scope.md`.
3. **Keine Secrets/Tokens/personenbezogene Daten** in Repo, Logs, Fixtures oder Doku.
   Beispieldaten nur anonymisiert (Schema wie in der Referenz: `Anna Abel <anna.abel@example.org>`).
4. **Kein Institut-Hardcoding.** `TUDO`/`DESYZ`, lokale Namensschemata, Stage-/Test-Mappings,
   Klebegewichts-Formeln usw. gehören ins Institute-Profil (DB/Config), nie in den Code.
5. **Alleinige Autorenschaft in Commits.** Commit-Nachrichten tragen **keine**
   `Co-Authored-By:`-Zeile fuer Agenten oder Modelle. Der Owner ist alleiniger
   Autor; Copyright und `LICENSE` nennen ihn ebenso. Owner-Entscheidung
   2026-08-29, rueckwirkend auf die gesamte Historie angewandt.
6. **Alles Produkt-Facing ist Englisch** (internationale Nutzung): App-UI, Nutzerdoku,
   API-/Fehlermeldungen, Code, Kommentare, Commits. Nur die internen Planungsdokumente
   in `docs/` bleiben Deutsch. UI-Texte i18n-fähig aufbauen (EN als Default-Locale).
7. **Dokumentationsdisziplin.** Jede Verhaltens- oder Vertragsänderung am Code aktualisiert im
   selben Change das zuständige Dokument (Ownership: `docs/00-doc-map.md`) und den Abschnitt
   „Aktueller Stand" in `docs/04-roadmap.md`. Keinen konkurrierenden Plan im Chat erfinden
   (siehe Startkontext). Der `Stop`-Hook `.claude/hooks/doc-guard.ps1` erinnert, wenn Produktivcode
   ohne Doku-Update geändert wurde; die Subagenten **Yatagarasu** (Drift-Audit, read-only) und
   **Tenjin** (Doku-Sync) übernehmen die Pflege, `/sync-docs` startet beides. Reine Refactors/Tests
   ohne Verhaltensänderung sind ausgenommen — dann kurz begründen.

## Stack (Kurzreferenz)

Backend `backend/`: Python 3.12, FastAPI, SQLAlchemy, Pydantic, PostgreSQL; PDB-Zugriff via `itkdb`.
Frontend `frontend/`: React + TypeScript (Vite), Mantine, TanStack Query/Table.
Deployment `deploy/`: Docker Compose (app, worker, postgres). Tests: pytest / vitest / Playwright.

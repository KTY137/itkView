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

## Harte Regeln (gelten für ALLE Agenten)

1. **`references/zeuthenflow` NIEMALS ausführen oder importieren** — nur mit Read/Grep lesen.
   Schon ein Import baut DB-Verbindungen auf. Der Ordner ist eine anonymisierte Lese-Referenz
   (siehe `references/zeuthenflow/ANONYMIZATION.md`); sein `.git` enthält noch Originaldaten — nicht anfassen.
2. **PDB-Schreibschutz (es gibt keine Testinstanz mehr).** Lesende Zugriffe auf die produktive
   PDB nur mit doppeltem Opt-in (`ITKFLOW_PDB_INSTANCE=production` + `ITKFLOW_ALLOW_PRODUCTION=true`);
   der Default erreicht keine PDB. **Schreiboperationen ausschließlich gegen von itkFlow selbst
   registrierte DUMMY-Batch-Testkomponenten** (nur Module/Hybride; **niemals Sensoren oder ASICs
   registrieren** — dafür gibt es keinen Dummy-Mechanismus, das korrumpiert Seriennummern).
   Technisch erzwungen via `pdb_write_scope=dummy_only` (`backend/app/pdb_scope.py`); echte
   Produktions-Writes sind bewusst nicht implementiert. Details:
   `docs/09-pdb-production-strategy.md`, `docs/adr/003-pdb-dummy-write-scope.md`.
3. **Keine Secrets/Tokens/personenbezogene Daten** in Repo, Logs, Fixtures oder Doku.
   Beispieldaten nur anonymisiert (Schema wie in der Referenz: `Anna Abel <anna.abel@example.org>`).
4. **Kein Institut-Hardcoding.** `TUDO`/`DESYZ`, lokale Namensschemata, Stage-/Test-Mappings,
   Klebegewichts-Formeln usw. gehören ins Institute-Profil (DB/Config), nie in den Code.
5. **Alles Produkt-Facing ist Englisch** (internationale Nutzung): App-UI, Nutzerdoku,
   API-/Fehlermeldungen, Code, Kommentare, Commits. Nur die internen Planungsdokumente
   in `docs/` bleiben Deutsch. UI-Texte i18n-fähig aufbauen (EN als Default-Locale).

## Stack (Kurzreferenz)

Backend `backend/`: Python 3.12, FastAPI, SQLAlchemy, Pydantic, PostgreSQL; PDB-Zugriff via `itkdb`.
Frontend `frontend/`: React + TypeScript (Vite), Mantine, TanStack Query/Table.
Deployment `deploy/`: Docker Compose (app, worker, postgres). Tests: pytest / vitest / Playwright.

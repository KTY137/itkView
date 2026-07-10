# Das itkFlow-Agenten-Team

12 Subagenten in `.claude/agents/` (Projekt-Scope, im Repo versioniert). Claude Code wählt
anhand der `description` automatisch den passenden Agenten; explizit anfordern geht immer
("nutze den code-reviewer für …"). Alle Agenten laden `CLAUDE.md` — dort stehen die harten
Regeln (zeuthenflow nie ausführen, nur PDB-Testinstanz, keine Secrets, kein Institut-Hardcoding).
Vor Planung oder Implementierung lesen alle Agenten zusätzlich `docs/04-roadmap.md` und ordnen
ihre Arbeit dem nächsten passenden Meilenstein zu, sofern der Nutzer nichts anderes vorgibt.

| # | Agent | Rolle | Werkzeuge | Besonderheit |
|---|---|---|---|---|
| 1 | `architect` | Systemdesign, API-Contracts, ADRs | read-only + Web | `effort: high`, implementiert nicht |
| 2 | `pdb-gateway-dev` | itkdb-Integration, Token, Paging, Sync | voll | portiert Muster aus zFlow (lesend) |
| 3 | `backend-dev` | FastAPI, SQLAlchemy, Outbox, Auth | voll | Alembic-Migrationen Pflicht |
| 4 | `frontend-dev` | React/TS, Wizards, Kanban, Triage-UI | voll | Scanner-first UX |
| 5 | `ingestion-dev` | Instrument-Parser, Watched-Folder, **Legacy-Migration** | voll | Fixtures aus anonymisierter Referenz |
| 6 | `domain-modeler` | Stages, Test-Mappings, Klebegewichts-Formeln, Institute-Profile | voll | `effort: high`, pure functions |
| 7 | `devops` | Docker Compose, CI, Packaging | voll | Ziel: `docker compose up` |
| 8 | `qa-engineer` | pytest/vitest/Playwright, Fixtures | voll | PDB nur gemockt/Sandbox-markiert |
| 9 | `code-reviewer` | Review: PDB-Sicherheit, Korrektheit, Regeln | read-only + git diff | `effort: high` |
| 10 | `docs-writer` | Nutzerdoku (DE), API-Doku (EN), Onboarding | Read/Write/Edit | `model: sonnet` (günstig) |
| 11 | `yatagarasu` | Doku-Drift-Audit (findet Drift) | read-only (Read/Grep/Glob) | `model: haiku`, fixt nicht |
| 12 | `tenjin` | Doku-Sync (schreibt Fixes) | Read/Write/Edit/Glob/Grep | `model: haiku`, Partner von yatagarasu |

## Typischer Ablauf pro Feature

1. `architect` entwirft (bei Bedarf) → ADR-Text
2. Fach-Agent implementiert (`backend-dev`/`frontend-dev`/`pdb-gateway-dev`/`ingestion-dev`/`domain-modeler`)
3. `qa-engineer` ergänzt Tests, `code-reviewer` befundet den Diff
4. `docs-writer` zieht die Doku nach, `devops` hält Build/CI grün

## Hinweise

- Frontmatter-Felder siehe [Claude-Code-Doku „Create custom subagents"](https://code.claude.com/docs/en/sub-agents);
  `tools` ist eine Allowlist, `model: inherit` ist Default, `effort` überschreibt das Session-Level.
- Für parallele, voneinander unabhängige Arbeitspakete können Agenten mit `isolation: worktree`
  gestartet werden (eigene Repo-Kopie) — sinnvoll ab Phase 1, wenn backend/frontend parallel laufen.
- Nicht alles braucht einen Agenten: kleine Fixes macht die Hauptsession direkt; Agenten lohnen
  sich für abgegrenzte Pakete, deren Zwischenschritte den Hauptkontext fluten würden.
- **Dokumentationsdisziplin** ist über CLAUDE.md-Regel #6 verankert: Verhaltensänderungen ziehen
  im selben Change das zuständige Doc (`docs/00-doc-map.md`) + „Aktueller Stand" nach. Die
  Haiku-Wächter `yatagarasu` (Audit) und `tenjin` (Sync) sowie der `Stop`-Hook
  `.claude/hooks/doc-guard.ps1` erzwingen das; `/sync-docs` startet Audit + Fix in einem Rutsch.

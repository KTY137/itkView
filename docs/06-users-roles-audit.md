# Plan: Nutzer, Rollen und Audit-Zuordnung

> Planungsdokument (noch nicht umgesetzt). Legt fest, wie itkFlow echte
> Nutzerkonten, Rollen und eine faelschungssichere „wer hat was gemacht"-Spur
> bekommt. Umsetzung erst nach Freigabe.

## Problem / Motivation

Heute sind `AuditEvent.actor`, `OutboxAction.created_by` und der `actor` bei
Outbox-Uebergaengen **freie Strings, die der Client mitschickt** (z. B.
`"ui-user"`). Damit ist die Nachvollziehbarkeit nicht faelschungssicher und an
keine echten Konten gebunden. Anforderung:

1. Nur ein **Admin** darf das Institut-Profil (Config, Branding, Mappings) und
   Nutzer verwalten.
2. Jede Person, die mit der App arbeitet, hat ein **eigenes Profil**.
3. Jede Aktion ist einer **echten, serverseitig bestimmten Identitaet**
   zugeordnet.

## Empfehlung: Auth-Mechanismus

**v1 = lokale Accounts (E-Mail + Passwort), OIDC/CERN-SSO als spaeterer
Adapter.** Begruendung:

- Die App soll self-hostbar per `docker compose up` auf einem Lab-PC/Instituts-VM
  laufen, **ohne CERN-Dienst** (Revamp-Plan §Deployment). Lokale Accounts haben
  keine externe Abhaengigkeit.
- Die Audit-Zuordnung ist eine `user_id` — **unabhaengig davon, wie die
  Identitaet entstand**. SSO wird spaeter hinter derselben Naht eingesteckt,
  ohne Audit-Trail oder Endpoints umzubauen.

Deshalb: Identitaet hinter einer schmalen **Identity-Naht** kapseln
(`authenticate(credentials) -> User`), sodass „local" heute und „oidc" spaeter
austauschbare Implementierungen derselben Naht sind.

## Datenmodell (additiv)

`User`
- `id` PK
- `email` (unique, Identitaet)
- `display_name`
- `institute_id` FK -> `institute_profile` (Zugehoerigkeit)
- `role`: `admin` | `operator` | `viewer`
- `is_active` (deaktivieren statt loeschen — Audit bleibt referenzierbar)
- `password_hash` (nullable; nur bei lokalem Auth; argon2/bcrypt)
- `external_subject` (nullable; fuer spaeteren OIDC-Adapter)
- `created_at`

`Session` (oder stateless Token — siehe offene Fragen)
- `id`/`token`, `user_id`, `expires_at`, `created_at`

**Attribution-Umbau:** `AuditEvent.actor` und `OutboxAction.created_by` bekommen
zusaetzlich `user_id` FK. Der freie Textname bleibt denormalisiert erhalten
(historische Eintraege, Anzeige), aber **neue Schreibaktionen setzen `user_id`
serverseitig aus der Session** — der Request-Body liefert keinen Actor mehr.

## Rollen (Matrix)

| Aktion | viewer | operator | admin |
|---|---|---|---|
| Komponenten/Board/Dashboard lesen | ✓ | ✓ | ✓ |
| Sync starten | – | ✓ | ✓ |
| Ingestion-Upload, Outbox anlegen | – | ✓ | ✓ |
| Outbox freigeben (approve) | – | ✓ (oder 4-Augen, s. u.) | ✓ |
| Stage-Move vorschlagen | – | ✓ | ✓ |
| Institut-Profil / Branding / Mappings | – | – | ✓ |
| Nutzer verwalten | – | – | ✓ |

Institut-Scoping: ein Nutzer agiert in seinem Institut; Reads/Writes werden auf
`institute_id` gefiltert. (Mandantentrennung, Revamp-Plan Phase 6.)

## API (Skizze)

- `POST /api/auth/login` (E-Mail+Passwort) -> Session-Cookie (httpOnly).
- `POST /api/auth/logout`.
- `GET /api/auth/me` -> aktueller User (Rolle, Institut) fuer die Rail.
- `GET/POST/PATCH /api/users` (admin) — Nutzer im eigenen Institut verwalten.
- Bestehende Schreib-Endpoints: `created_by`/`actor` **entfaellt aus dem Body**;
  der Server nimmt den User aus der Session. Autorisierung per Rollen-Dependency.

## Frontend

- **Login-Screen** (unauth -> Login).
- **Operator-Feld unten links in der Rail** wird der eingeloggte User: Name,
  Rolle, Institut, Logout. (Genau die Stelle, die heute Platzhalter ist.)
- **Rollen-Gating:** Viewer sieht keine Schreib-Buttons (Approve, Propose,
  Sync); Institut-/Nutzerverwaltung nur fuer Admin sichtbar.

## Sicherheit

- Passwort-Hash mit argon2id (oder bcrypt); nie Klartext, nie im Repo/Log.
- Session-Cookie `httpOnly`, `SameSite=Lax`; CSRF-Schutz fuer State-Change.
- Erst-Admin per Seed/CLI (`create-admin`), nicht hartkodiert.
- Keine Secrets in Fixtures/Doku (harte Regel #3).

## Migration / Rollout

1. Additive Tabellen `user`, `session`; `user_id`-Spalten an `audit_event`
   und `outbox_action` (SQLite-Patch analog `ensure_phase0_sqlite_schema`,
   spaeter Alembic).
2. Uebergangsphase: alte Eintraege behalten den freien Actor-String; neue
   Aktionen fuellen `user_id`.
3. Erst-Admin anlegen, dann Login scharf schalten (Endpoints hinter Auth).

## Offene Fragen

- Admin-Reichweite: **pro Institut** (empfohlen, passt zu Multi-Institut) oder
  ein globaler Super-Admin?
- Session: server-seitige Session-Tabelle vs. signiertes JWT.
- 4-Augen-Prinzip fuer Outbox-Approve (Ersteller ≠ Freigeber) — als
  Institut-Profil-Flag?
- Zeitpunkt OIDC/CERN-SSO.

## Roadmap-Einordnung

Fundament fuer echte Nachvollziehbarkeit; zieht Teile der „Auth/Rollen"-Arbeit
aus Phase 4/6 nach vorne, weil Outbox-Writes und Uploads schon existieren und
eine echte Zuordnung brauchen. Siehe `docs/04-roadmap.md`.

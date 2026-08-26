# Plan: Nutzer, Rollen und Audit-Zuordnung

> Legt fest, wie itkFlow echte Nutzerkonten, Rollen und eine faelschungssichere
> „wer hat was gemacht"-Spur bekommt. **Umgesetzt und End-to-End verdrahtet
> (Stand 2026-08-24): Attribution, Rollen-Enforcement, CSRF, Frontend-Login und
> persoenliche PDB-Verbindungen stehen und sind getestet** — siehe Umsetzungsstand.

## Umsetzungsstand (2026-08-24)

**End-to-End umgesetzt und getestet (211 Backend-Tests gruen, Frontend `tsc`
gruen).** Was steht:

- Auth-Primitive `backend/app/auth.py`: PBKDF2-HMAC-SHA256 (nur stdlib),
  konstantzeitiges Verify, opake Session-Tokens, CSRF-Token, Rollen-Vokabular
  `("viewer","operator","admin")`, Session-TTL 12 h.
- Modelle `backend/app/models.py`: `User` (`app_user`, inkl. `external_subject`
  fuer spaeteres OIDC), `UserSession` (serverseitige Session-Tabelle, jetzt mit
  `csrf_token`). `user_id`-FK additiv auf `outbox_action` und `audit_event`
  (Patch in `ensure_phase0_sqlite_schema`, denormalisierte Actor-Strings bleiben).
- Login/Session `backend/app/api.py`: `POST /api/auth/login` (httpOnly-Session +
  lesbares `itkflow_csrf`-Cookie, `csrf_token` in `MeOut`), `logout`,
  `GET /api/auth/me`; `GET/POST/PATCH /api/users` (admin, institut-gescoped).
- **Attribution serverseitig:** Schreib-Endpunkte setzen `user_id` + den
  denormalisierten Actor aus der Session (E-Mail), nie aus dem Body; die
  Client-Actor-Felder sind aus den Request-Schemas entfernt.
- **Rollen-Enforcement (`require_operator`)** auf Component-/Tool-Sync,
  Outbox-Create, Outbox-Transition (inkl. Approve), Ingest-Upload und
  Propose-Outbox. Reads bleiben offen; `/api/users*` admin-only.
- **CSRF:** Double-Submit — router-weites `csrf_protect`, no-op fuer
  GET/HEAD/OPTIONS und unauthentifizierte Requests; sonst muss `X-CSRF-Token`
  dem Session-Token entsprechen (`hmac.compare_digest`). `POST /api/auth/login`
  ist ausgenommen (ein Alt-Session-Cookie darf den Login nicht mit 403 blocken);
  Legacy-Sessions ohne Token werden von `GET /api/auth/me` geheilt (Token wird
  gemintet und persistiert), statt mit 500 zu crashen. `session_cookie_secure`
  (Default False fuer lokales http, True hinter TLS).
- **Frontend** (`frontend/src/auth.tsx`, `LoginScreen.tsx`, `api.ts`): Login,
  `useAuth`, Session-Probe auf `/api/auth/me`, User-Rail unten links (Name,
  Rolle, Institut, Logout), Rollen-Gating der Write-Buttons (Viewer sieht keine),
  zentraler `X-CSRF-Token`-Versand + 401→Login/403→Toast; Offline-Demo-Fallback
  bleibt erhalten. **Admin-`Users`-Screen** (`frontend/src/screens/UsersScreen.tsx`):
  Personen anlegen, Rolle wechseln, aktivieren/deaktivieren, Passwort
  zuruecksetzen — admin-gated (Nav-Eintrag nur fuer Admins).
- **Persoenliche PDB-Verbindung (2026-08-24):** Der User-Block in der Rail
  oeffnet den Account-Screen. Jeder angemeldete User verbindet/testet/ersetzt
  oder entfernt dort sein eigenes Plus4U/PDB-Access-Code-Paar. Das Backend
  prueft es vor dem Speichern, verlangt bei institutsgebundenen Konten dieselbe
  PDB-Institutsmitgliedschaft und speichert nur AES-256-GCM-Ciphertext plus
  nicht geheime Statusmetadaten. Eine PDB-Identity kann nur einem lokalen Konto
  gehoeren. API-Antworten, Audit und Browser-Speicher enthalten keine Codes.
- **Identitaet auf PDB-Operationen:** Component-/Evidence-/Attachment-Reads
  verwenden ausschliesslich die Verbindung des Request-Users. Background-Syncs
  verwenden `SyncJob.user_id`; beim Approve bindet `OutboxPdbPrincipal` den
  Worker und alle Retries an User+PDB-Identity des Freigebenden. Es gibt keinen
  globalen Credential-Fallback. Details: ADR 004.
- Tests: `backend/tests/test_auth.py` + `test_auth_enforcement.py` (401/403 je
  Write, Attribution, CSRF, Migration); Erst-Admin per CLI
  `python -m app.create_admin` **oder per First-Run-Setup in der UI**.
- **Security-Härtung Login/Reads (2026-08-26):** `GET /api/audit`, `GET /api/outbox`
  und `GET /api/outbox/{id}` verlangen jetzt `require_user` (jede angemeldete
  Rolle genügt) — sie lieferten zuvor Akteurs-E-Mails bzw. Staged-Action-Payloads
  anonym aus; der breitere Read-Rollout für alle übrigen Endpunkte bleibt
  bewusst unverändert offen. `POST /api/auth/login` verifiziert bei unbekannter
  E-Mail zusätzlich gegen einen fest erzeugten Dummy-Passworthash (Antwort
  unverändert `401 Invalid email or password.`), damit die Login-Antwortzeit
  nicht verrät, ob ein Konto existiert. `PATCH /api/users/{id}` invalidiert bei
  gesetztem `password`-Feld alle bestehenden `UserSession`-Zeilen des
  Zielnutzers (Rollen-/Namensänderung ohne Passwort lässt Sessions unberührt).
- **First-Run-Setup (2026-08-25):** `GET /api/setup` meldet `needs_admin=true`,
  solange die User-Tabelle leer ist; `POST /api/setup/admin` legt genau dann den
  ersten Admin an (Rolle fest `admin`, kein Institut), loggt ihn direkt ein
  (Session + CSRF wie beim Login) und schreibt das AuditEvent
  `setup.admin_created`. Sobald irgendein User existiert, antwortet der Endpoint
  dauerhaft 409 — danach laeuft Kontenpflege nur noch admin-gated ueber
  `/api/users`. Das Frontend zeigt bei `needs_admin` statt des Logins den
  `SetupScreen` (Auth-Status `setup`). Ein frisches Deployment (Desktop wie
  Server) braucht damit keinen Shell-Zugriff mehr.
  Nebenlaeufigkeit: auf PostgreSQL serialisiert ein transaktionsgebundener
  Advisory-Lock (`pg_advisory_xact_lock`) konkurrierende Bootstrap-Calls,
  damit unter READ COMMITTED nicht zwei „erste Admins" entstehen; SQLite
  (Desktop) ist single-writer und braucht das nicht. Bis zum Setup kann
  jeder, der den Port erreicht, die Instanz beanspruchen — deploy/README
  weist an, das Setup sofort nach dem ersten Start abzuschliessen und den
  Dienst vorher nicht ueber das vertrauenswuerdige Netz hinaus zu exponieren.
  Tests: `backend/tests/test_setup_bootstrap.py`.

**Offen:**

- Kein Demo-User im Seed: echtes Login ist erst nach dem First-Run-Setup (oder
  `create_admin`) nutzbar (offline greift der Demo-Modus, kein Login-Zwang).
- 4-Augen-Prinzip fuer Outbox-Approve und OIDC/CERN-SSO bleiben spaeter (siehe
  Offene Fragen).

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
| Lokalen Mirror/Board/Dashboard lesen | ✓ | ✓ | ✓ |
| Eigene PDB-Verbindung verwalten / direkte PDB-Reads | ✓ | ✓ | ✓ |
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
  Rolle, Institut; Klick oeffnet Account/PDB-Verbindung, Logout bleibt separat.
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

- Admin-Reichweite: **entschieden — beides unterstuetzt.** Ein Admin mit
  `institute_id` verwaltet nur sein Institut; ein Admin mit `institute_id = NULL`
  agiert global. Default bleibt per-Institut.
- Session: **entschieden — serverseitige Session-Tabelle** (`UserSession`),
  kein JWT.
- 4-Augen-Prinzip fuer Outbox-Approve (Ersteller ≠ Freigeber) — noch offen, als
  Institut-Profil-Flag denkbar.
- Zeitpunkt OIDC/CERN-SSO — noch offen; `external_subject` ist bereits
  vorgesehen.

## Roadmap-Einordnung

Fundament fuer echte Nachvollziehbarkeit; zieht Teile der „Auth/Rollen"-Arbeit
aus Phase 4/6 nach vorne, weil Outbox-Writes und Uploads schon existieren und
eine echte Zuordnung brauchen. Siehe `docs/04-roadmap.md`.

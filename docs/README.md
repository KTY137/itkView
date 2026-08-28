# itkView-Doku: Einstieg und Lesepfade

Dieses dedizierte Release-Repository liefert itkView als fail-closed
Read-only-Produkt. Die folgenden Planungsdokumente beschreiben weiterhin den
gemeinsamen itkFlow-Kern und seine Historie; fuer die Viewer-Grenze und die
sicheren Defaults sind [`ADR 007`](adr/007-itkview-read-only-product.md),
[`04`](04-roadmap.md) und die produktseitige
[`README`](../README.md) massgeblich.

itkFlow ersetzt den Google-Sheet-, CERNBox- und zFlow-Workflow der
ATLAS-ITk-Strip-Modulproduktion durch eine selbst hostbare, institutsneutrale
Webapp, die ein Institut per Desktop-Bundle oder `docker compose up` betreibt.
Die ITk Production Database (PDB) am CERN bleibt Source of Truth; itkFlow ist
der lokale Spiegel und das Cockpit davor — Komponenten suchen, Testergebnisse
erfassen, Stage-Moves und Uploads vorbereiten, Werkzeuge, Klebstoff, Sendungen
und Erinnerungen verwalten. Jede PDB-wirksame Aktion laeuft ueber eine
auditierte Outbox, und geschrieben wird ausschliesslich auf selbst registrierte
DUMMY-Testkomponenten.

> Diese Seite ist ein **Router**, keine Zusammenfassung: sie sagt nur, welches
> Dokument als naechstes dran ist und warum.
> **Wer welches Dokument besitzt**, steht verbindlich in
> [`00-doc-map.md`](00-doc-map.md) (inklusive Reverse-Index Code → Dokument);
> diese Seite wiederholt die Ownership-Tabelle bewusst nicht.

**Sprache.** Die internen Planungsdokumente in `docs/` sind Deutsch
(Ausnahme: [`11-logistics-operations.md`](11-logistics-operations.md) ist als
Nutzer-/Entwicklervertrag Englisch geschrieben). Alles Produkt-Facing ist
Englisch: App-UI, API-/Fehlermeldungen, [`../deploy/README.md`](../deploy/README.md),
[`../agent/README.md`](../agent/README.md) und der Code.

---

## Lesepfade

### „Ich bin neu im Projekt"

1. [`../CLAUDE.md`](../CLAUDE.md) — die harten Regeln (zeuthenflow nie
   ausfuehren, PDB-Schutzmodell, keine Secrets, kein Institut-Hardcoding).
   Ohne die darf niemand loslegen.
2. [`02-revamp-plan.md`](02-revamp-plan.md) — Produktvision, Architektur und
   Phasenschnitt: was gebaut wird und warum dieser Stack.
3. [`01-ist-analyse-zeuthenflow.md`](01-ist-analyse-zeuthenflow.md) — der
   abzuloesende Ist-Workflow. Erklaert, welches Problem jedes Feature loest.
4. [`10-itk-domain-reference.md`](10-itk-domain-reference.md) — die Domain-
   Vokabeln (`MODULE`, `R5M0`, `ATLAS18R5`, Stages) und welche Bauteile man
   niemals registrieren darf.
5. [`04-roadmap.md`](04-roadmap.md), Abschnitt „Aktueller Stand" — was heute
   wirklich existiert. Die Roadmap ist das laufende Protokoll, nicht der Plan
   aus 02.
6. [`05-ui-design-reference.md`](05-ui-design-reference.md) plus das Mockup
   [`itkflow-ui-mockup.html`](itkflow-ui-mockup.html) — wie sich das Produkt
   anfuehlt und welche Screens es gibt.
7. [`00-doc-map.md`](00-doc-map.md) — wo deine naechste Aenderung dokumentiert
   werden muss.

### „Ich muss die UI aendern"

1. [`05-ui-design-reference.md`](05-ui-design-reference.md) — verbindliche
   Design-Referenz: Design-Sprache, Screens, globale Muster. Umsetzung folgt
   der Referenz, nicht umgekehrt.
2. [`itkflow-ui-mockup.html`](itkflow-ui-mockup.html) — dieselbe Referenz zum
   Anschauen; enthaelt die Design-Tokens als CSS-Variablen.
3. [`adr/006-staged-first-ui-auto-mirror.md`](adr/006-staged-first-ui-auto-mirror.md)
   — warum die Komponentendetailseite der Arbeitsort ist und warum das
   Frontend keine Stage-Logik selbst rechnet.
4. [`superpowers/specs/2026-08-25-staged-first-module-page-design.md`](superpowers/specs/2026-08-25-staged-first-module-page-design.md)
   — der Zielvertrag dahinter; §H beschreibt das Modul-Worksheet feldgenau
   inklusive Payload-Grenzen.
5. [`10-itk-domain-reference.md`](10-itk-domain-reference.md) §7 — woher
   Stage-Reihenfolge und Pflichttests kommen und wie weit sie von den echten
   Daten abweichen. Wer Pflicht-Test-Tabellen anfasst, braucht das.
6. Bereichsspezifisch: [`07-jig-tool-quickselect.md`](07-jig-tool-quickselect.md)
   (Tool-Slots im Assembly-Wizard),
   [`11-logistics-operations.md`](11-logistics-operations.md) (Glue-, Shipment-,
   Reminder- und Operations-Screens),
   [`12-attachments-and-images.md`](12-attachments-and-images.md) (Bilder,
   Galerie, Thumbnails),
   [`13-metrology-artifacts.md`](13-metrology-artifacts.md) (warum die
   Metrologie-Kachel kein Bild zeigen kann und was ihre Dateinamen wert sind).
7. [`04-roadmap.md`](04-roadmap.md) — dort steht jede UI-Aenderung im
   „Aktueller Stand", und dorthin gehoert auch deine.

### „Ich fasse die PDB-Integration an"

1. [`../CLAUDE.md`](../CLAUDE.md), harte Regel 2 — das Schutzmodell in Kurzform.
   Agenten setzen die Produktions-Opt-ins niemals selbst.
2. [`09-pdb-production-strategy.md`](09-pdb-production-strategy.md) — das
   massgebliche Dokument: Offline-Default, Read-Opt-ins, Schreib-Scope,
   Sync-Paging, Retry- und Ausfallverhalten, Env-Setup, Verifikationsstufen.
3. [`adr/003-pdb-dummy-write-scope.md`](adr/003-pdb-dummy-write-scope.md) — die
   Entscheidung hinter `pdb_write_scope=dummy_only` und warum es keine
   Testinstanz mehr gibt.
4. [`adr/004-personal-pdb-credentials.md`](adr/004-personal-pdb-credentials.md)
   — jede PDB-Anfrage laeuft unter der persoenlichen Verbindung eines Kontos;
   es gibt keinen deployment-weiten Fallback.
5. [`adr/001-outbox-status-contract.md`](adr/001-outbox-status-contract.md) und
   [`adr/002-async-outbox-worker.md`](adr/002-async-outbox-worker.md) — der
   Statusvertrag und der einzige Prozess, der wirklich schreibt.
6. [`adr/006-staged-first-ui-auto-mirror.md`](adr/006-staged-first-ui-auto-mirror.md)
   plus [`12-attachments-and-images.md`](12-attachments-and-images.md) — wie
   Evidence und Dateien automatisch gespiegelt werden und wie die drei
   Attachment-Quellen abgesichert sind.
7. [`10-itk-domain-reference.md`](10-itk-domain-reference.md) — welche
   Komponententypen DUMMY-registrierbar sind und welche (Sensoren, ASICs)
   niemals.
8. [`11-logistics-operations.md`](11-logistics-operations.md) — der
   read-only Shipment-Mirror ist der zweite PDB-Lesepfad neben Komponenten und
   Evidence.

### „Ich will den Produktionsablauf verstehen"

1. [`10-itk-domain-reference.md`](10-itk-domain-reference.md) — Modulaufbau,
   Taxonomie, Label-Legende und der Ablauf von Anfang bis Ende.
2. [`01-ist-analyse-zeuthenflow.md`](01-ist-analyse-zeuthenflow.md) — wie
   derselbe Ablauf heute im Sheet und in zFlow abgebildet ist.
3. [`superpowers/research/2026-08-26-zflow-sheet-transcription.md`](superpowers/research/2026-08-26-zflow-sheet-transcription.md)
   — die woertliche Abschrift der echten Arbeitsblaetter: jede Zeile, die eine
   Schichtcrew heute ausfuellt.
4. [`10-itk-domain-reference.md`](10-itk-domain-reference.md) §7 — Abgleich des
   Stage-Profils mit echten TUDO-Daten: was wirklich aufgezeichnet wird.
5. [`07-jig-tool-quickselect.md`](07-jig-tool-quickselect.md) — Jigs,
   Pickup-Tools und Panels, die an jedem Klebeschritt haengen.
6. [`11-logistics-operations.md`](11-logistics-operations.md) — Klebstoff-
   Batches mit Topfzeit, Wareneingang und Erinnerungen rund um die Assembly.
7. [`05-ui-design-reference.md`](05-ui-design-reference.md) — wie derselbe
   Ablauf im Produkt als Screens erscheint.

### „Ich will wissen, woran gerade gearbeitet wird"

1. [`04-roadmap.md`](04-roadmap.md), Abschnitt „Aktueller Stand" — das
   fortlaufende Protokoll jeder Verhaltensaenderung, neueste Eintraege oben im
   Abschnitt.
2. [`04-roadmap.md`](04-roadmap.md), Abschnitt „Naechste Arbeitspakete" — was
   als Naechstes ansteht und was daran noch offen ist.
3. [`04-roadmap.md`](04-roadmap.md), Abschnitte „Geplant / verbleibende
   Ausbaustufen" und „Meilensteine" — Restumfang je Dokument und die
   Phasen 0–6 mit Done-Kriterien.
4. [`superpowers/specs/`](superpowers/specs) — die Zielvertraege der zuletzt
   geschnittenen Feature-Pakete (Index unten).
5. [`02-revamp-plan.md`](02-revamp-plan.md) §4 — die Phasenlogik, falls die
   Reihenfolge in der Roadmap erklaerungsbeduerftig wirkt.
6. [`03-agent-team.md`](03-agent-team.md) — wer (welcher Subagent) welche Art
   von Arbeit uebernimmt.

### „Ich will itkFlow installieren oder betreiben"

1. [`../deploy/README.md`](../deploy/README.md) — der Compose-Weg fuer ein
   Institut inklusive First-Run-Setup und Sicherheitshinweisen (Englisch).
2. [`adr/005-desktop-packaging.md`](adr/005-desktop-packaging.md) — die
   Einzelplatzvariante als Desktop-Bundle und warum sie dieselbe App startet.
3. [`06-users-roles-audit.md`](06-users-roles-audit.md) — Konten, Rollen,
   Sessions und die persoenliche PDB-Verbindung, die jede Person selbst
   verbindet.
4. [`09-pdb-production-strategy.md`](09-pdb-production-strategy.md) — welche
   Env-Schalter eine Instanz PDB-faehig machen und was sie ausdruecklich nicht
   erlauben.
5. [`08-remote-access.md`](08-remote-access.md) — Zugriff von ausserhalb des
   Labornetzes; Empfehlung und Vorbedingungen.
6. [`11-logistics-operations.md`](11-logistics-operations.md) — welcher Prozess
   Outbox und Reminder abarbeitet und was der Operations-Health-Screen zeigt.

---

## Entscheidungen, Specs und Recherche

Diese drei Verzeichnisse enthalten die Begruendungen, die in den numerierten
Dokumenten nur als Ergebnis auftauchen. „Stand" sagt, ob der Text noch den
heutigen Code beschreibt.

### Architecture Decision Records (`adr/`)

| ADR | Entschieden | Stand |
|---|---|---|
| [`001-outbox-status-contract.md`](adr/001-outbox-status-contract.md) | `backend/app/outbox.py` ist die einzige Quelle fuer Outbox-Status, Uebergaenge und Terminalzustaende; `GET /api/outbox/contract` veroeffentlicht sie. | Aktuell. |
| [`002-async-outbox-worker.md`](adr/002-async-outbox-worker.md) | Nur ein eigenstaendiger Worker schreibt in die PDB: Dry-Run erneut pruefen, Submitter aufrufen, `confirmed`/`failed`, Retry mit Backoff. | Aktuell; ergaenzt durch den In-Process-Drain fuer Ein-Prozess-Deployments (`ITKFLOW_OUTBOX_PROCESSOR`, siehe [`11`](11-logistics-operations.md)). |
| [`003-pdb-dummy-write-scope.md`](adr/003-pdb-dummy-write-scope.md) | Writes ausschliesslich gegen selbst registrierte DUMMY-Module/-Hybride (`pdb_write_scope=dummy_only`); `unrestricted` bleibt unimplementiert. | Aktuell, inklusive Ergaenzung 2026-08-26 (Offline-Default, Reads ab Werk). |
| [`004-personal-pdb-credentials.md`](adr/004-personal-pdb-credentials.md) | Jedes Konto verbindet sein eigenes Access-Code-Paar, AES-256-GCM verschluesselt; Outbox-Aktionen sind an die PDB-Identitaet des Freigebenden gebunden. | Aktuell. |
| [`005-desktop-packaging.md`](adr/005-desktop-packaging.md) | Tauri-Shell plus PyInstaller-Sidecar, das Backend liefert die SPA selbst aus; Zustand liegt im Anwendungsdatenverzeichnis. | Aktuell bis auf den PDB-Default in „Entscheidung" Punkt 6: dort steht noch die gestrichene `test`-Instanz. Massgeblich ist [`09`](09-pdb-production-strategy.md). |
| [`006-staged-first-ui-auto-mirror.md`](adr/006-staged-first-ui-auto-mirror.md) | Die Komponentendetailseite ist der Arbeitsort, Staged ist eine Serverprojektion, und ein Komponentensync zieht automatisch Evidence und Dateien nach. | Aktuell; M1–M4 umgesetzt, die gemeinsame Abnahme wird in [`04`](04-roadmap.md) verfolgt. |
| [`007-itkview-read-only-product.md`](adr/007-itkview-read-only-product.md) | itkView ist eine fail-closed Read-only-Buildvariante derselben Codebasis: Mirror-Syncs bleiben, Produktionsdatenerfassung, Outbox und finale PDB-Sinks sind gesperrt; App-Zustand und Cookies sind isoliert. | Aktuell. |

### Specs (`superpowers/specs/`)

- [`2026-08-25-staged-first-module-page-design.md`](superpowers/specs/2026-08-25-staged-first-module-page-design.md)
  — Zielvertrag fuer Staged-first-Modulseite, Ingest-Log, Staged-Fenster und
  Auto-Mirror, mit der Live-Validierung der Attachment-Quellen (713 Testlaeufe,
  360 Attachments). **Stand:** umgesetzt (M1–M4 plus Nachtrag §H
  „Modul-Worksheet"); §A traegt den Nachtrag, dass `projected.tests[]` heute
  `projected.ghost_tests[]` heisst. Bleibt der Abnahmevertrag.
- [`2026-08-26-logistik-reminders-design.md`](superpowers/specs/2026-08-26-logistik-reminders-design.md)
  — Entwurf fuer Glue-Batch-Registry, read-only Shipment-Mirror mit lokaler
  Empfangspruefung und wiederkehrende Reminder mit Notification-Adaptern.
  **Stand:** umgesetzt; der geltende Vertrag ist inzwischen
  [`11-logistics-operations.md`](11-logistics-operations.md), die Spec ist die
  Begruendung dahinter (der Kanaltyp Telegram kam spaeter dazu).

### Recherche (`superpowers/research/`)

- [`2026-08-26-zflow-sheet-transcription.md`](superpowers/research/2026-08-26-zflow-sheet-transcription.md)
  — woertliche Abschrift der TUDO- und DESYZ-Modulblaetter samt Referenzblatt
  „Daten" (Klebeformeln, Zieltabellen, Werkzeug-Dropdowns). **Stand:** bleibt als
  Protokoll der Screenshots stehen, ist aber **ueberholt**, wo die
  Volltext-Analyse unten widerspricht.
- [`2026-08-27-tudo-sheet-live.md`](superpowers/research/2026-08-27-tudo-sheet-live.md)
  — Volltext-Analyse des echten Google-Sheets (18 Blaetter): vollstaendiges
  Zeileninventar des aktiven TUDO-Modulblatts, das Referenzblatt „Daten" Zelle
  fuer Zelle, verifizierte Klebeformeln, Nutzungsstatistik, zFlow-Ausgabeblatt
  und PDB-Property-Namen. **Stand:** maßgeblich; **hat Vorrang vor der
  Abschrift**, wo beide sich unterscheiden.

---

## Wie diese Doku funktioniert

- **Jede Verhaltens- oder Vertragsaenderung am Code aktualisiert im selben
  Change das besitzende Dokument** (Tabelle in [`00-doc-map.md`](00-doc-map.md))
  **und** den Abschnitt „Aktueller Stand" in [`04-roadmap.md`](04-roadmap.md).
  Das ist harte Regel 6 in [`../CLAUDE.md`](../CLAUDE.md). Reine Refactors oder
  Testverdrahtung ohne Verhaltensaenderung sind ausgenommen — dann genuegt eine
  Zeile Begruendung im Abschluss.
- **Der „Aktueller Stand" ist das laufende Protokoll**, nicht der Plan.
  Geplantes gehoert in [`02-revamp-plan.md`](02-revamp-plan.md) oder in den
  passenden Meilenstein der Roadmap; Anleitungen beschreiben immer den
  Ist-Zustand des Codes.
- **Der `Stop`-Hook `.claude/hooks/doc-guard.ps1`** erinnert automatisch, wenn
  Produktivcode ohne Doku-Aenderung geaendert wurde (fail-open und
  loop-sicher) — er blockiert nichts, er faellt auf.
- **Zwei Subagenten pflegen die Doku:** `yatagarasu` auditiert read-only die
  Drift zwischen Code und Doku, `tenjin` wendet die Fixes an und haelt
  „Aktueller Stand" und ADRs nach. `/sync-docs` startet Audit und Fix in einem
  Rutsch. Details in [`03-agent-team.md`](03-agent-team.md) und
  [`00-doc-map.md`](00-doc-map.md).
- **Neue Dokumente** bekommen eine Zeile in der Ownership-Tabelle in
  [`00-doc-map.md`](00-doc-map.md), einen Kopfblock nach dem Muster der
  bestehenden Dokumente (besitzt / fuer wen / verwandt) und einen Platz in
  einem der Lesepfade oben.

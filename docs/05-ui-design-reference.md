# UI-Design-Referenz: itkFlow

> **Verbindliche Design-Referenz.** Diese Datei und das zugehoerige Mockup legen
> Look, Layout und Interaktion fest, damit die Umsetzung nicht vom Design-Ziel
> abdriftet. Wer UI baut oder aendert, liest sie vorher.
>
> Mockup (eigenstaendig, offline lauffaehig, im Browser oeffnen):
> [`docs/itkflow-ui-mockup.html`](itkflow-ui-mockup.html)

## Warum diese Datei existiert

Das Mockup wurde urspruenglich als Claude-Artifact erzeugt. Heruntergeladene
Artifact-HTML ist manchmal kaputt (Browser-„Seite speichern"-Dumps enthalten
Extension-Muell und den Sandbox-Wrapper). Deshalb liegt hier eine **saubere,
selbsttragende Kopie** als Quelle der Wahrheit im Repo — nur Inline-CSS/JS,
keine externen Assets, rendert offline identisch.

## Sprach-Hinweis (wichtig)

Das Mockup ist **Deutsch beschriftet** — es ist eine Design-Skizze, kein
Text-Kanon. Das ausgelieferte Produkt-UI ist **Englisch** und i18n-faehig
(CLAUDE.md Regel #5). Uebernimm aus dem Mockup **Layout, Hierarchie, Interaktion
und Design-Sprache**, nicht die deutschen Labels.

## Design-Sprache

- **Thema „Cleanroom-Cockpit":** Silizium-Grau als Grund, Kapton-Kupfer
  (`--accent`) als einziger Akzent, Mono-Schrift als „Datenstimme" fuer
  Seriennummern/Messwerte, Sans fuer Fliesstext.
- **Design-Tokens** stehen als CSS-Variablen im `:root` des Mockups (Farben,
  Radius, Schatten, Fonts). Light **und** Dark sind definiert
  (`prefers-color-scheme` + `data-theme`-Override). Neue UI nutzt dieselben
  Tokens statt eigener Farben.
- **Statusfarben** sind semantisch und konsistent: `good` (gruen), `warn`
  (gelb), `serious` (orange), `crit` (rot), plus neutrale/`queued`-Chips fuer
  Outbox-Zustaende. Chips tragen einen farbigen Punkt + Label, nie Farbe allein.
- **Charts** nutzen die Serienfarbe und die validierte Referenzpalette
  (`--series`, `--grid`, `--axis`); siehe auch das `dataviz`-Skill.
- **Barrierefreiheit:** sichtbarer Fokusring, `prefers-reduced-motion`, `role`/
  `aria-label` an Diagrammen; horizontale Scroll-Container fuer breite Tabellen/
  Boards statt Seiten-Overflow.

## Screens & Muster (Soll-Zustand)

1. **Assembly-Board (Kanban):** Spalten = PDB-Stages
   (`HV_TAB_ATTACHED → GLUED → STITCH_BONDING → BONDED → TESTED → FINISHED`),
   Karten = Module mit lokalem Namen, Typ-Badge, SN und Status-Chips. Karte →
   Detailseite. „Geist"-Karte zum Anlegen (Sensor scannen).
2. **Komponenten-Detail:** Stammdaten (Key/Value, Mono), Familienbaum
   (Modul → Sensor/Hybrid/Powerboard), Outbox-Timeline der letzten Aktionen,
   Pflicht-Tests je Stage als Tabelle, und ein Stage-Move-Vorschlag als Callout
   mit Freigeben/Ablehnen (→ Outbox, auditiert).
3. **Test-Triage:** Tabelle der Inbox-Dateien mit Parser, erkannter Komponente,
   Vorschau, Validierungs-Chip (valide/FAILED/Zuordnung noetig/ignoriert) und
   Aktionen (Ansehen, Freigeben, Zuordnen). Deckt sich mit der
   Ingestion-Parser-Registry + Preview/Dry-Run (siehe Roadmap Phase 2).
4. **Dashboard:** KPI-Kacheln (Module in Arbeit, Outbox offen, Tests
   ausstehend, Yield) plus Charts (Module je Stage, Durchsatz/Woche).

## Globale UI-Elemente

- **Scanner-first:** globale Scan-Leiste oben (SN/RFID/lokaler Name), Enter
  oeffnet die Komponente. Erfassung ist scan-getrieben, nicht maus-getrieben.
- **Nav-Rail** mit Gruppen „Produktion" und „Standort"; noch nicht gebaute
  Bereiche (Glue-Batches, Shipments, Werkzeuge, Reminder) sind sichtbar,
  deaktiviert und mit Phasen-Badge (`P4`) markiert.
- **PDB-Sync-Indikator** und **`itkpd-test`-Kennzeichnung** in der Topbar —
  nie so tun, als sei Produktion im Spiel.
- **Wizard-Modal** (z.B. Kleben erfassen) mit Schritt-Indikator und
  Live-Berechnung (Klebegewicht + Toleranz-Verdikt); Ergebnis geht in die
  Outbox, nicht direkt in die PDB.
- **Toast** fuer Aktions-Feedback; jede PDB-wirksame Aktion formuliert „… in
  Outbox eingereiht", nie „gespeichert".

## Pflege

- Aendert sich die Design-Sprache oder ein Screen-Muster, wird zuerst das Mockup
  aktualisiert, dann diese Referenz. Umsetzung folgt der Referenz, nicht
  umgekehrt.
- Bei bewusster Abweichung von der Referenz: kurz in dieser Datei oder im
  Abschluss begruenden (analog zur Roadmap-Regel).

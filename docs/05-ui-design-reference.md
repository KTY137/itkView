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

Mockup und ausgeliefertes Produkt-UI sind **Englisch** und i18n-faehig
(CLAUDE.md Regel #5). Das Mockup bleibt eine Design-Skizze: Seine Labels zeigen
die beabsichtigte Informationshierarchie, waehrend der eigentliche Text-Kanon
im Frontend-i18n-Modul liegt.

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
   (Modul → Sensor/Hybrid/Powerboard), Pflicht-Tests je Stage, gespiegelte
   Testlaeufe/Attachments, Stage-Move-Vorschlag und die Karte `Add test result`.
   Offene Aenderungen werden als serverberechnete Ghost-Projektion gezeigt;
   die Detailseite berechnet keine Stage-Regeln selbst. Bildgalerie,
   Testlaufkarten und Thumbnails verwenden ausschliesslich lokal gespiegelte
   Attachment-Bytes; ein geoeffneter Screen holt keine Bilder direkt aus PDB
   oder EOS.
3. **Staged:** Arbeitsvorrat offener PDB-Absichten, nach Komponente gruppiert.
   Jede Gruppe zeigt Local Name, SN, Thumbnail und aktuelle Stage; jede Action
   zeigt eine lesbare Summary, Status, `Push to PDB` oder `Discard` und ein
   aufklappbares technisches Detail. Terminale Actions liegen in `History`.
4. **Ingest log:** read-only Tabelle der eingegangenen Dateien mit Parser,
   erkannter Komponente als Detail-Link, Status, Uploader, Zeit, Fehler und
   einsehbarem Dry-Run. Upload, manuelle Erfassung und `Stage upload` liegen
   ausschliesslich auf der Komponentendetailseite.
5. **Dashboard:** KPI-Kacheln (Module in Arbeit, Staged offen, Tests
   ausstehend, Yield) plus Charts (Module je Stage, Durchsatz/Woche).
5b. **Statistics — Messwert-Sektion (2026-08-26):** Unter den Prozess-Charts
   (Durchsatz, Stage-Dwell, Rework) aggregiert ein `Measurements`-Block die
   gespiegelten Testlauf-Messwerte des Instituts. Zwei Auswahlfelder
   (`Test type`, `Result`, bei Arrays zusaetzlich `X axis`) werden **aus den
   Daten** befuellt (`GET /api/stats/measurements/dimensions`) — kein Testtyp
   und kein Result-Code steht im Code (harte Regel 4). Array-Ergebnisse
   erscheinen als **ueberlagerte Kurven, ein Polyline je Testlauf** (alle
   IV-Kurven des Instituts in einem Chart), gepaart gegen das gewaehlte
   X-Result, sonst gegen den Sample-Index. Skalare Ergebnisse (Klebegewicht,
   Bow, I_500V …) erscheinen als Verteilungshistogramm mit Kennzahl-Kacheln
   (n, Median, Mittel, P25–P75, Min–Max). Farbe traegt nur die
   Pass/Fail-Identitaet: bestandene Laeufe in `--series` mit niedriger Deckung,
   fehlgeschlagene in `--crit` **plus gestrichelter Linie** (Identitaet nie nur
   ueber Farbe), beide in der Legende; Hover-Ziel ist eine breitere unsichtbare
   Zwillingslinie. Achsen tragen die Einheit aus `result_meta.name`.
6. **Account / persoenliche PDB-Verbindung + Preferences:** Klick auf den angemeldeten
   User-Block in der Rail oeffnet einen eigenen Screen; Logout bleibt eine
   getrennte Aktion. Links stehen lokale Identitaet/Rolle/Institut, rechts die
   PDB-Verbindung mit `not configured|verified|invalid|unreachable`, Identity,
   Instituten und Pruefzeitpunkten. Codes sind zwei leere Password-Felder und
   werden nie maskiert zurueckgelesen oder im Browser gespeichert. Muster:
   Connect & test, Test, Replace sowie Disconnect mit Inline-Bestaetigung. Ein
   eigenes `Preferences`-Panel bietet `Staged preview: Tabs | Inline | Off`.
7. **Admin Settings:** Nur fuer Admins sichtbarer Screen fuer ein ausgewaehltes
   Institutsprofil. Er bietet strukturierte Abschnitte fuer Name/Prefix,
   Mattermost-/Webhook-Kanaele, Shipment-Empfangscheckliste,
   komponententypabhaengige Reception-Tests, Glue-Topfzeiten und den
   Evidence-Komponentenscope. Reception-Tests werden als wiederholbare Paare
   `Component type` / `Required test type` gepflegt und beim Speichern gruppiert;
   es gibt keinen Raw-JSON-Editor. Gespeicherte Webhook-URLs erscheinen nur als
   maskiertes Secret; unveraendertes Speichern bewahrt das Secret, Entfernen
   eines Kanals entfernt es bewusst. Kanaltests verwenden nur den gespeicherten
   Kanalnamen.
8. **Assembly-Wizard:** Eigener, vom Board-CTA erreichbarer scanner-first
   Arbeitsbereich mit vier sichtbaren Schritten: Parent, Child, Resources,
   Review. Komponenten werden exakt per SN/lokalem Namen aufgeloest. Das
   Resource-Panel bietet typgefilterte aktive Tools (Quick-Select plus
   RFID/Code-Scan), optionale benutzbare Glue-Batches samt Topfzeit und den
   Assembly-Slot. Erst der serverseitige Dry-run zeigt Blocking Issues,
   Warnings und abgeleitete PDB-Properties; nur ein gueltiger Preview kann eine
   Staged-Action erzeugen. `submittable=false` bleibt sichtbar erklaert. Der
   Wizard schreibt nie direkt in die PDB.
   **Kombinierte Tool-Slots (2026-08-26):** Definiert das Institutsprofil
   `assembly_tool_slots` (die Sheet-Spalten „Hybrid glue jigs top/bottom",
   „Pickups top/bottom", „Module jig"), ersetzt eine Slot-Karten-Liste das
   einzelne Tool-Select: je Slot ein nach Typ und `kinds` gefilterter
   Quick-Select plus entfernbare Chips (`multiple: true` erlaubt bis zu vier
   Tools, sonst genau eins); Slot-Labels sind Institutsdaten und werden nie
   uebersetzt. Es bleibt EIN gemeinsames Scan-Feld: der Scan landet im
   „aktiven" Slot (Scan-Target), der nicht nur ueber Farbe markiert ist;
   nach dem Fuellen rueckt das Scan-Target automatisch zum naechsten freien
   Slot weiter, und ein Scan, dessen Tool-Kind eindeutig zu genau einem
   Slot passt, routet dorthin. Ein abgelehnter Scan leert das Feld immer
   und meldet den Grund direkt am Scan-Feld. Der Review-Schritt zeigt die
   vom SERVER aufgeloesten Tools je Slot (`AssemblyPreviewOut.tools`),
   nie den lokalen Auswahlzustand. Ohne Profil-Setting bleibt alles beim
   bisherigen Ein-Tool-Verhalten. Details docs/07.
9. **Operations Health:** Admin-only Cockpit aus ausschliesslich lokal
   gespeicherter Telemetrie. Textuell benannte Heartbeat-Zustaende fuer
   Outbox-Worker und Reminder-Scheduler stehen neben aktiven/letzten Sync-Jobs,
   Staged-Backlog und Retry-Limit, offenen Reminder-Tasks sowie Parser-/Triage-
   Problemen. Institutsgebundene Admins sehen nur ihr eigenes Profil; globale
   Admins koennen Institut oder Gesamtansicht waehlen. Jede Problemgruppe
   verlinkt direkt nach `Staged`, `Ingest log` oder `Reminders`. Ein Refresh
   fuehrt niemals einen Live-PDB-Probe aus.

### Staged-Preview auf der Komponentendetailseite

- **`Tabs` (Default):** Im Detailkopf stehen `Current` und, nur bei mindestens
  einer offenen Action, `Staged (n)`. `Current` zeigt ausschliesslich den
  bestaetigten Mirror. `Staged` zeigt die projizierte Stage, Pending-Checks und
  Ghost-Testlaeufe gestrichelt/abgesetzt. Jede Action bleibt einzeln push- oder
  verwerfbar.
- **`Inline`:** Keine zweite Tab-Ansicht. Der Stage-Chip zeigt beispielsweise
  `HV Tab Attached → ⌇Glued⌇`; Ghost-Testlaeufe stehen in der bestehenden
  Testliste und Pflicht-Checks erhalten einen textuell bezeichneten
  `Pending`-Chip.
- **`Off`:** Keine projizierte Stage und keine Ghost-Testzeilen. Die bestehende
  kompakte Liste `Staged changes` bleibt sichtbar, damit die Praeferenz offene
  Arbeit nie versteckt oder verwirft.

Die Einstellung wird best effort in `localStorage` unter
`itkflow.stagedPreview` gespeichert. Jeder Zugriff ist mit Fallback auf `tabs`
abgesichert; blockierter Storage darf den Screen nicht brechen. Die
Praeferenz ist browserlokal, enthaelt keine Secrets und veraendert keine
Berechtigung oder Outbox-Action.

### Testerfassung auf der Komponentendetailseite

Die Karte `Add test result` bietet zwei Eingaenge in denselben serverseitigen
Pfad:

- Datei ablegen/auswaehlen: Upload mit an die aktuelle Komponente gebundenem
  `component_sn`; eine abweichende SN im Inhalt wird als blockierendes Issue
  gezeigt, nicht korrigiert.
- `Record test`: Testtyp aus dem lokalen PDB-Schema-Mirror waehlen und ein
  kontrolliertes Formular ausfuellen. Skalare Typen erhalten passende Felder,
  Arrays eine validierte Zeilen-Eingabe; unbekannte Typen bleiben read-only mit
  Erklaerung. Rohes JSON wird nie angezeigt oder editiert.

Beide Eingaenge erzeugen zuerst einen `IngestFile`, zeigen denselben Dry-Run
mit Messwerten, Warnungen und Issues und bieten erst bei gueltigem Ergebnis
`Stage upload` an. Das erzeugt eine Ghost-Action; es schreibt nicht direkt in
die PDB.

Kommt die Testerfassung vom Shipment-Screen, werden Seriennummer und Testtyp
als gemeinsamer Navigation-Intent uebergeben. Die Detailkarte oeffnet sofort
das Formular, zeigt `Pinned test: <TYPE>` und sperrt den Testtyp-Select auf den
exakten geforderten Typ. Fehlt dessen lokales Schema, bleibt die Erfassung mit
einer konkreten Sync-Erklaerung blockiert. Datei- und Formularpfad senden beide
Pins an den Server; Browserzustand allein gilt nie als Bindung.

**Edit-Ghost in der Pflicht-Tests-Tabelle (2026-08-26):** In beiden Varianten
von „Required tests per stage" (bestaetigter Mirror und projizierte
Staged-Ansicht) erhaelt jede Zeile mit Status `missing` oder `failed` eine
Ghost-Edit-Affordance: gestrichelt/gedaempft in Ruhe, bei Hover/Tastaturfokus
sichtbar (auf Touch dauerhaft dezent), Stift-Glyphe im Mono-Stil statt
Farb-allein-Signal. Nur fuer Nutzer mit Schreibrecht auf das Institut sichtbar
(deckungsgleich mit `Add test result`). Klick oeffnet die bestehende
Testerfassungskarte und belegt die Testtyp-Auswahl mit dem Typ der Zeile vor —
die Auswahl bleibt dabei aenderbar; existiert fuer den Typ kein lokal
gespiegeltes Schema, oeffnet sich das Formular trotzdem mit leerer Auswahl.

### Shipment-Empfang und Reception-Tests

Die Shipment-Tabelle zeigt neben dem Empfangsstatus eine eigene Spalte
`Reception tests` mit textuell benannten Chips `Missing`, `Pending`, `Passed`
oder `Failed`; ohne Profilanforderung steht `Not required`. Im Detail wird je
Shipment-Item die Seriennummer, der Komponententyp und jede geforderte
Testtyp-/Status-Zeile gezeigt. Fuer `Missing` und `Failed` fuehrt `Record test`
in den oben beschriebenen gepinnten Flow. `Pending` bietet keinen zweiten
Erfassungsbutton und wird nie wie `Passed` dargestellt.

Unter jeder Requirement-Gruppe steht der Schreib-Scope explizit: ein lokal
registrierter DUMMY kann nach Review ueber den geschuetzten Staged-Flow gepusht
werden; bei Produktionskomponenten oder noch nicht gespiegelten Items lautet
die Aussage, dass Erfassen/Stagen moeglich bleibt, Production Writes aber
deaktiviert sind.

Vor der Empfangscheckliste fasst ein Banner den serverseitig projizierten Gate-
Status zusammen. `Finish receiving check` bleibt deaktiviert, solange ein
konfigurierter Test nicht bestanden ist. Admins koennen bewusst `Override
incomplete reception tests` aktivieren, muessen einen Grund eingeben und sehen
den Audit-Hinweis; der Button benennt sich dann in `Finish with admin override`
um. Operatoren sehen stattdessen die Aussage, dass nur ein Admin uebersteuern
kann. Die UI ist eine Erklaerung des Gates, nicht dessen Sicherheitsgrenze; der
Server prueft den Status erneut.

### Ehrlichkeit im Staged-Fenster

`Push to PDB` kettet nur die bestehende Outbox-Statusmaschine bis
`submitted`; der Worker, die persoenliche Credential-Bindung, Audit und ADR
003 bleiben die einzige Schreibgrenze. Bei `submittable=false` fehlt der
Push-Button. Stattdessen erklaert der Screen sichtbar: `Production writes are
not enabled — stays staged (dummy-only scope)`. Farbe allein reicht fuer Ghost,
Pending, Fehler oder Schreibschutz nie als Unterscheidungsmerkmal.

## Globale UI-Elemente

- **Scanner-first:** globale Scan-Leiste oben (SN/RFID/lokaler Name), Enter
  oeffnet die Komponente. Erfassung ist scan-getrieben, nicht maus-getrieben.
  Wo ein Screen mehrere Scan-Ziele hat (z. B. Tool-Slots im Assembly-Wizard),
  gibt es trotzdem genau EIN Scan-Feld plus ein sichtbares, nicht nur farblich
  markiertes „Scan-Target", das nach jedem Treffer automatisch weiterrueckt —
  eine Scan-Salve von oben nach unten darf nie einen Mausgriff erfordern.
- **User-Rail als Account-Einstieg:** Avatar/Name/Rolle sind ein klar
  fokussierbarer Button zum Account-Screen. Der danebenliegende Logout-Button
  bleibt separat, damit Kontoeinstellungen nicht versehentlich abmelden.
- **Nav-Rail** mit Gruppen „Produktion" und „Standort". Der Produktionsblock
  nennt die Arbeitsorte `Assembly board`, `Components`, `Ingest log`, `Staged`,
  `Dashboard` und `Statistics`. Der Standortblock enthaelt `Tools`,
  `Glue batches`, `Shipments` und `Reminders`; Admins sehen zusaetzlich
  `Operations health` und `Settings`. Nur tatsaechlich noch nicht gebaute Bereiche sind deaktiviert und
  tragen ein Phasen-Badge.
- **Globaler PDB-Sync-Indikator** in der Topbar: Ein laufender Component- oder
  Evidence-Sync
  bleibt beim Screen-Wechsel und nach Reload sichtbar. Er zeigt Statuspunkt,
  aktuelle Phase, `aktuell/gesamt` (sobald bekannt), Laufzeit und einen schmalen
  Fortschrittsbalken. Die Components-Ansicht ergaenzt ein kompaktes Detailpanel
  mit Phase, Laufzeit, letztem Update und persistentem Erfolg/Fehler. Vor dem
  ersten Gesamtwert ist der Balken unbestimmt; Farbe ist nie der einzige
  Statustraeger. Nach erfolgreichem Component-Mirror folgt sichtbar der
  Evidence-/Attachment-Mirror; `Sync complete` darf erst den vorgesehenen
  Offline-Umfang ehrlich benennen. Der Sync laeuft als Server-Job weiter, nicht
  als Lebensdauer des gerade montierten React-Screens.
- **PDB-Umgebung ehrlich kennzeichnen:** Im inerten Default ist Remote-Sync als
  nicht verfuegbar erkennbar; bei explizit aktivierten Produktions-Reads lautet
  die Kennzeichnung entsprechend `Production reads` und verschweigt nie den
  separaten DUMMY-Schreib-Scope. Die historische, nicht mehr existente
  `itkpd-test`-Instanz ist kein Produktlabel mehr.
- **Assembly als eigener Wizard-Screen:** Der laengere Scan-/Resource-/Review-
  Flow bleibt als eigener Arbeitsbereich stabil und darf nicht durch ein
  versehentlich geschlossenes Modal verloren gehen. Kurze Test-Erfassungen
  duerfen weiterhin als kompakte Karte/Modal erscheinen; jedes Ergebnis geht
  in Staged-Actions, nie direkt in die PDB.
- **Toast** fuer Aktions-Feedback; jede PDB-wirksame Aktion formuliert zum
  Beispiel `… staged for PDB review`, nie `saved to PDB`.

## Pflege

- Aendert sich die Design-Sprache oder ein Screen-Muster, wird zuerst das Mockup
  aktualisiert, dann diese Referenz. Umsetzung folgt der Referenz, nicht
  umgekehrt.
- Bei bewusster Abweichung von der Referenz: kurz in dieser Datei oder im
  Abschluss begruenden (analog zur Roadmap-Regel).

# UI-Design-Referenz: itkFlow

> **Verbindliche Design-Referenz.** Diese Datei und das zugehoerige Mockup legen
> Look, Layout und Interaktion fest, damit die Umsetzung nicht vom Design-Ziel
> abdriftet. Wer UI baut oder aendert, liest sie vorher.
>
> Mockup (eigenstaendig, offline lauffaehig, im Browser oeffnen):
> [`docs/itkflow-ui-mockup.html`](itkflow-ui-mockup.html)
>
> - **Besitzt:** Design-Sprache und Tokens, alle Screens und Interaktionsmuster,
>   die Darstellung von Pflicht-Tests, Staged-Preview und Modul-Worksheet sowie
>   die globalen UI-Elemente.
> - **Fuer wen:** alle, die UI bauen oder aendern — vor der ersten Zeile Code.
> - **Verwandt:** [`adr/006-staged-first-ui-auto-mirror.md`](adr/006-staged-first-ui-auto-mirror.md)
>   (warum die Detailseite der Arbeitsort ist),
>   [`superpowers/specs/2026-08-25-staged-first-module-page-design.md`](superpowers/specs/2026-08-25-staged-first-module-page-design.md)
>   (Zielvertrag, §H = Worksheet), [`10-itk-domain-reference.md`](10-itk-domain-reference.md)
>   (Stage-Modell und Pflichttests hinter den Anzeigen),
>   [`07-jig-tool-quickselect.md`](07-jig-tool-quickselect.md) (Tool-Slots),
>   [`11-logistics-operations.md`](11-logistics-operations.md) (Glue-, Shipment-,
>   Reminder- und Ops-Screens),
>   [`12-attachments-and-images.md`](12-attachments-and-images.md) (Bilder und
>   Galerie), [`README.md`](README.md) (Lesepfade).

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
   (Modul → Sensor/Hybrid/Powerboard), Pflicht-Tests je Stage (Stage-Modell und
   Pflichttest-Vokabular gehoeren [`10-itk-domain-reference.md`](10-itk-domain-reference.md)
   §7 und [`../backend/app/domain/stages.py`](../backend/app/domain/stages.py)),
   gespiegelte
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
   **Production stages (2026-08-26):** Eigener Abschnitt mit GUI-Editor fuer
   `stage_order` und `stage_requirements` je Institut, tastaturbedienbar;
   Testtyp-Vorschlaege stammen aus gespiegelten Schemata und aus in
   gespiegelter Evidence vorkommenden Testtypen, ein unbekannter Wert wird als
   `Not mirrored` markiert statt abgelehnt. Seed-Stages lassen sich
   umsortieren, aber nicht entfernen (der Merge haengt sie beim Speichern
   immer wieder an; neutralisieren geht nur ueber leere Pflicht-Tests fuer die
   betroffene Stage). Der Screen dupliziert noch die Seed-Stage-Konstanten,
   weil kein Endpunkt das effektive (gemergte) Stage-Modell liefert — ein
   Read-Endpunkt dafuer ist der empfohlene naechste Schritt.
   **Glue judgement (2026-08-27):** Ein eigener strukturierter Abschnitt
   pflegt `glue_weight_inputs` und `glue_targets` ohne Raw-JSON: Formelschritte
   mit Result-Codes sowie Regelsaetze aus Prozess, `valid_from`, Modultyp,
   Ziel und Toleranz. Daneben stehen `Default glue process` als Auswahl aus den
   konfigurierten Prozessen und die optionale `Run process property`. Ein leerer
   Wert wird nur bei zuvor konfiguriertem Feld als `null` gespeichert; ein
   unberuehrtes Institut bekommt keine implizite Glue-Konfiguration. Exakte
   `by_type_code`-Formelvarianten sind vorerst kein eigener verschachtelter
   Editor, muessen aber beim Laden, Dirty-Vergleich und jedem beliebigen Save
   typisiert und verlustfrei erhalten bleiben.
   **Scheduled sync (2026-08-27):** Eigener Abschnitt fuer `auto_sync` im
   Institutsprofil (Enable-Checkbox, Intervall, optionales Zeitfenster,
   sieben tastaturbedienbare Weekday-Toggles mit `aria-pressed`). Er ist die
   einzige Stelle, an der itkFlow die PDB **von sich aus** kontaktiert, ohne
   dass jemand in dem Moment danach fragt — der Outbox-Worker laeuft zwar
   ebenfalls unbeaufsichtigt, fuehrt aber nur eine bereits freigegebene
   Entscheidung aus. Deshalb steht die Erklaerung als Fliesstext neben dem
   Schalter, nicht im Kleingedruckten: (a) unter wessen Identitaet gelesen
   wird (die Person mit dem zuletzt erfolgreichen Component-Sync, sofern sie
   dort weiterhin aktiver Operator/Admin ist; deaktivierte oder herabgestufte
   Konten, fremder Institute-Scope, fehlende Codes sowie unbekannter, kaputter
   oder `invalid` Status werden uebersprungen, `unreachable` nicht; qualifiziert
   sich niemand, laeuft schlicht nichts), (b) dass Fenster
   und Wochentage in der **lokalen Serverzeit** ausgewertet werden (Compose:
   `TZ` aus `deploy/.env`, Default `Etc/UTC`), waehrend das Intervall in UTC ab
   der neueren Grenze aus letztem Erfolg und letztem Scheduled-Versuch gemessen
   wird, und (c) dass ein Fenster
   ueber Mitternacht laufen darf. Die Live-Notiz unter den Zeitfeldern benennt
   `22:00`–`06:00` ausdruecklich als `Overnight window`, damit niemand spaeter
   eine `start < end`-Pruefung „repariert". Ein Institut ohne Konfiguration
   bekommt durch ein unabhaengiges Speichern **keinen** `auto_sync`-Block —
   auch keinen abgeschalteten. Validierung: `app/institute_settings.py`
   (Untergrenze 15 min wird abgelehnt, nicht angehoben; Zeitfenster nur als
   Paar; Wochentage 1–7 eindeutig und nicht leer; unbekannte Keys, u. a.
   `timezone`, werden abgelehnt).
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
   bisherigen Ein-Tool-Verhalten. Details
   [`07-jig-tool-quickselect.md`](07-jig-tool-quickselect.md).
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

Die Praeferenz steuert ausschliesslich die **Ghost-/Projektionsebene**, nicht
den Bestand der Datenansicht: das Modul-Worksheet (siehe unten) ist in allen
drei Modi vorhanden, auch in `Off`. Es ist die normale Modulansicht, kein
Vorschau-Feature; Mehrverkehr entsteht dadurch nicht, weil der
Preview-Endpunkt ohnehin in jedem Modus geladen wird.

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

**Modul-Worksheet als Primaeransicht (2026-08-26):** Die Detailseite rendert
Testlaeufe nicht mehr einzeln und voll ausgeklappt — bei >100 gespiegelten
Laeufen war das eine unlesbare Wand aus ueberlappenden Zahlen. Primaeransicht
ist jetzt das Spreadsheet-Modell ([Spec §H](superpowers/specs/2026-08-25-staged-first-module-page-design.md)):
pro Stage-Gruppe **eine**
kompakte Tabelle, Zeile = Testtyp, Spalten `Test | Values | Status | Date | ✎`.
Die Preview traegt dafuer keine gespiegelten Laeufe mehr mit:
`projected.tests[]` heisst jetzt `projected.ghost_tests[]` und enthaelt
ausschliesslich offene, noch nicht gepushte Staged-Uploads. Rohe Messwerte
liefert ausschliesslich `GET /api/components/{sn}/tests`, abgerufen erst beim
ersten Oeffnen von „All mirrored runs".

- **Values-Zelle:** die ersten drei Skalare als `Label Wert`, der Rest als
  `+n`-Chip; Array-/Map-Ergebnisse nur als Umfangs-Chip (`⌁ 40 pts` bzw.
  `⌁ 20 entries`; ein Dict zaehlt wie ein Array, Diskriminator `kind:
  "array"|"map"`). Rohe Messreihen verlassen den Server gar nicht erst — das
  ist Payload-Vertrag, nicht nur Darstellung. Befuellte Skalare sortieren
  stabil zuerst. Steht eine Komponente auf einer modellfremden Stage (reale
  TUDO-Module auf `FAILED`), gilt jede Gruppe als erreicht statt das ganze
  Sheet abzudunkeln.
- **Gruppen** folgen der Stage-Order des Komponententyps; noch nicht erreichte
  Stages stehen gedaempft mit Chip `Not reached yet`, gespiegelte Testtypen
  ausserhalb des Stage-Modells sowie nur-staged oder bestaetigt-aber-noch-
  nicht-gespiegelte Testtypen sammelt die Gruppe `Additional`.
- **Zeile aufklappbar** zum vollen Run-Detail (Kurven, Werte, Conditions,
  Attachments) ueber dieselben Renderer wie bisher; geladen wird erst beim
  Oeffnen. Dict-wertige Ergebnisse (Metrologie, Wire Bonding) rendern als
  Position/Wert-Paare statt als `[object Object]`.
- **Edit-Strip statt Sprung:** Der Ghost-Stift oeffnet die schema-getriebenen
  Felder jetzt **innerhalb der Zeile**, vorbelegt aus dem juengsten Lauf, und
  stageed ueber den unveraenderten Weg manual-entry-Ingest → Dry-Run →
  Propose-Outbox. Offene Staged-Actions erscheinen als gestrichelte
  Ghost-Zeilen unter ihrer Testzeile. Vorbelegt wird nur, was nachweislich
  durchs Schema-Formular hin- und zurueckgeht: Maps, vom Schema nicht als
  Array deklarierte Arrays und Arrays mit `null` werden nie vorbelegt oder
  abgeflacht; ein nicht wegklickbarer Hinweis nennt die betroffenen Felder.
  Ist ein solches Feld REQUIRED, blockt der Strip komplett mit Verweis auf
  den Datei-Drop-Pfad — sichtbar blockiert statt stillem Datenverlust. Ein
  blockierter Dry-Run ohne Issues wird angezeigt statt zu verschwinden, ein
  fehlgeschlagener Fetch des vorherigen Laufs blockt den Strip statt ein
  leeres Formular zu zeigen, und der Zeilenzustand ist nach Stage+Testtyp
  geschluesselt.
- Die frueheren Vollansichten sind nicht entfallen, sondern in ein
  eingeklapptes, lazy geladenes `All mirrored runs` unter dem Worksheet
  gewandert; die Datei-Drop-Karte bleibt unveraendert.

**Zurueckgezogene Laeufe und Kind-Evidenz (2026-08-27):** Zwei datengetriebene
Korrekturen an genau diesem Worksheet
([Plan §1](superpowers/specs/2026-08-27-modulseite-als-arbeitsblatt.md)).

- **Zurueckgezogene Messungen zaehlen nicht mehr.** Die PDB liefert einen
  geloeschten Testlauf (`state='deleted'`) weiter aus; im Spiegel sind das 102
  von 14 759 Laeufen. Sie sind jetzt aus `latest`, `run_count` und dem
  Pflichttest-Status ausgeschlossen; die Zeile meldet sie stattdessen als
  `withdrawn_count`. Sind **alle** Laeufe eines Testtyps zurueckgezogen, steht
  die Zeile wieder auf `missing`. Sichtbar bleiben sie: `GET
  /api/components/{sn}/tests` listet sie samt `run_state` weiter (Vertrag in
  docs/09). In der aufgeklappten Lauf-Ansicht ersetzt bei exakt
  `state='deleted'` ein amberner Text-Chip `withdrawn in PDB` das alte Urteil;
  die Messwerte bleiben zur Nachvollziehbarkeit sichtbar. Der noch lebende
  Zwischenzustand `requestedToDelete` zeigt weiterhin `passed` oder `failed`.
- **Neuer Block `Evidence on child components`** unter den Stage-Gruppen, eine
  read-only Tabelle je direktem Kind (Kopf: dekodierter Typ, Seriennummer,
  lokaler Name; Spalten `Test | Values | Result | Date`). Grund: nur 720 von
  14 759 gespiegelten Laeufen haengen an MODULE-Komponenten, der Rest an
  Sensoren, Hybriden, Powerboards — und bei R5-Ringmodulen an den beiden
  Halbmodulen (docs/10 §7). Die `Values`-Zelle folgt exakt demselben
  Kompaktheitsvertrag wie oben.
  Bewusst **nicht** enthalten: eine `Status`-Spalte und der Edit-Stift. Ein
  Pflichttest-Status ist eine Aussage ueber *diese* Komponente, und ob der
  bestandene Test eines Kindes die Anforderung des Elternteils erfuellt, ist
  eine offene Fachentscheidung (zFlow aggregiert ueber Halbmodule) — die
  Anzeige beantwortet sie nicht. Erfassen gehoert auf die Seite des Kindes,
  wo die Seriennummer im Payload stimmt. Ein Kind ohne gespiegelte Laeufe
  bekommt trotzdem seine Gruppe („wir haben nachgesehen" ist etwas anderes als
  „wir haben nicht nachgesehen").

**Klebegewichts-Urteil im Worksheet (2026-08-27):** Traegt eine Zeile eine
serverseitige Ableitung (`WorksheetRow.derived`, Kind `glue_weight`, Vertrag
in [Spec §9.3](superpowers/specs/2026-08-27-modulseite-als-arbeitsblatt.md)),
zeigt die `Values`-Zelle das Urteil **vor** den rohen Waagenwerten: je
Ableitungsschritt (`hybrids`, `powerboard` — zwei Klebungen bleiben zwei
Chips, nie zu einem Bit zusammengefasst, weil das PDB-`passed`-Bit genau das
tut) ein Wortchip `OK` / `Too little` / `Too much` (rot) oder — faellt keine
Zahl heraus — der konkrete Grund `No target` / `Missing readings` /
`Not measured` / `No verdict` als gedaempfter Chip; nie ein neutraler Chip,
der wie ein bestandenes Ergebnis aussieht (die Haelfte der Powerboard-Urteile
auf dem alten Blatt war genau das: Arithmetik ueber leeren Zellen). Daneben
steht die Kompaktformel `gemessen / Ziel ± Toleranz mg` unveraendert wie vom
Server geliefert; der Browser rechnet, rundet oder loest die Toleranz nie zu
einer Spanne auf. Der geoeffnete Edit-Streifen zeigt dieselbe Ableitung
ausfuehrlicher unterhalb der Rohwertfelder: das aufgeloeste Klebeverfahren mit
Quelle (`recorded with the run` / `profile default` / `source unknown`) sowie
je Schritt Messwert, Ziel und Toleranz als Definitionsliste. Diese Sektion
erscheint nur, wenn die Zeile ueberhaupt eine Ableitung traegt (Dry-Run- oder
letzter Lauf-Wert); kennt das Regelwerk zwar den Testtyp, aber keinen einzigen
Schritt fuer den vorliegenden Modultyp, steht dort statt einer leeren Liste
der Hinweistext „the profile configures no derivation step for this test
type". Beide Ansichten formatieren ausschliesslich eine in
`backend/app/domain/glue.py` und `backend/app/glue_service.py` berechnete
Ableitung — Ziel, Toleranz und Formel kommen ausschliesslich aus dem
Institutsprofil (`glue_targets`, `glue_weight_inputs`), es gibt keine zweite
Formel im Frontend. Der PDB-Schreibpfad mischt `derived_results` noch nicht in
das hochgeladene Dokument (offene Naht E3, siehe Spec §9.4).

### Shipment-Empfang und Reception-Tests

Vertrag, Profilschluessel und Gate-Semantik dahinter:
[`11-logistics-operations.md`](11-logistics-operations.md). Dieser Abschnitt
beschreibt nur die Darstellung.

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
`submitted`; der Worker, die persoenliche Credential-Bindung, Audit und
[ADR 003](adr/003-pdb-dummy-write-scope.md) bleiben die einzige Schreibgrenze. Bei `submittable=false` fehlt der
Push-Button. Stattdessen erklaert der Screen sichtbar: `Production writes are
not enabled — stays staged (dummy-only scope)`. Farbe allein reicht fuer Ghost,
Pending, Fehler oder Schreibschutz nie als Unterscheidungsmerkmal.

Jede offene Test-Upload-Action zeigt zusaetzlich Komponente, Testtyp und die
vorgeschlagenen Messwerte im selben kompakten Worksheet-Format (Arrays/Maps
als Umfangs-Chip, nie Rohdaten); die Werte kommen aus den Preview-Ghost-
Eintraegen, kein neuer Endpunkt. Terminale (`History`-)Uploads haben keinen
Ghost und damit keine Werte — der Screen sagt das explizit statt Leere zu
suggerieren; dieselbe ehrliche Meldung erscheint, wenn die Komponente noch
nicht gespiegelt ist. Ein Betrachter ohne Schreibrecht sieht den Grund statt
gar keiner Steuerung.

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
- **Rollierende Anzeige waehrend eines Evidence-Sweeps (2026-08-27):** Der
  Sweep committet **jede Komponente einzeln**, die Daten stehen also laengst im
  Spiegel, waehrend der Job noch laeuft. Bisher las die Oberflaeche erst beim
  Status `succeeded` neu — man sah minutenlang alte Zeilen, dann fiel alles auf
  einmal hinein. Der Controller (`componentSync.ts`) liefert dafuer `dataEpoch`:
  ein Zaehler, der waehrend eines laufenden Jobs hochzaehlt, aber nur wenn der
  Job **wirklich vorangekommen** ist (`current` gewachsen) und hoechstens
  einmal je `PROGRESSIVE_REFRESH_MS` (8 s). Beide Bedingungen sind Absicht: ein
  Job in der Retry-Leiter haelt seinen Heartbeat frisch, ohne voranzukommen —
  dafuer den Spiegel neu zu lesen kostet einen Request und zeigt nichts. Die
  Komponentenliste (inkl. Thumbnails) und eine **geoeffnete Detailseite**
  (Preview, Pflichttest-Status, Stage-Vorschlag) haengen daran; letztere ist
  der wichtigere Fall, weil dort sonst ein veralteter Pflichttest-Status stehen
  bleibt. Am Terminalstatus zaehlt `dataEpoch` bewusst nicht weiter — die
  bestehende `succeeded`-Behandlung deckt das ab, ein zusaetzlicher Schritt
  waere nur ein doppelter Abruf. Ausdruecklich **nur** fuer den Evidence-Sweep:
  der Component-Sync schreibt seinen ganzen Spiegel in einer abschliessenden
  Transaktion und hat zwischendurch nichts zu zeigen.
- **PDB-Umgebung ehrlich kennzeichnen:** Im inerten Default ist Remote-Sync als
  nicht verfuegbar erkennbar; bei explizit aktivierten Produktions-Reads lautet
  die Kennzeichnung entsprechend `Production reads` und verschweigt nie den
  separaten DUMMY-Schreib-Scope. Die historische, nicht mehr existente
  `itkpd-test`-Instanz ist kein Produktlabel mehr. Was welche Instanz technisch
  darf, steht in [`09-pdb-production-strategy.md`](09-pdb-production-strategy.md).
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

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
   oder EOS. Jedes gespeicherte `image/*` bleibt dabei als vorhandener Eintrag
   sichtbar: Browserformate oeffnen als Bild/Lightbox, TIFF und andere nicht
   darstellbare Formate als beschrifteter Platzhalter — nie als kaputtes
   `<img>` und nie als falscher Leerzustand. Eigene und Kind-Anhaenge bleiben
   nach ihrer echten Besitzer-SN getrennt.
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
5a. **Statistics — Pflichttests je Produktionsstufe (2026-08-27):** Vor den
   Messwert- und Kollektivplots steht eine kompakte Liste `Required tests by
   stage`. Sie folgt der effektiven Stage-Reihenfolge des Instituts und zeigt
   je konfiguriertem Testtyp `Passed`, `Failed` und `Missing`. Nenner sind nur
   lebende Komponenten, die diese Stage erreicht oder ueberschritten haben;
   Drafts, Staged-Actions, zurueckgezogene und geloeschte Laeufe zaehlen nie
   als bestaetigte Evidenz. Pro Komponente entscheidet der neueste lebende
   gespiegelte Lauf; ein bestaetigter itkFlow-Upload ist nach seinem Mirror
   deshalb gleichwertig. Loading, leerer Zustand, Fehler und `Retry` stehen in
   der Karte selbst. Testtypen und Reihenfolge kommen aus dem Institutsprofil,
   nicht aus Frontend-Konstanten.
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

   **Explizite Kollektivkurven fuer IV und CV (2026-08-27):** Nach dem
   generischen Messwert-Explorer stehen zwei dauerhaft sichtbare Karten
   `Collective IV curves` und `Collective CV curves`. Ihre Kandidaten werden
   aus den gespiegelten Dimensionen entdeckt, nicht aus einer Liste exakter
   PDB-Testtypen: Ein IV-Schema braucht den Familienmarker `IV` im Testtyp oder
   auf beiden Achsencodes sowie numerische Current-/Voltage-Arrays; fuer CV
   entsprechend `CV` plus Capacitance/Voltage. Damit werden etwa Current-
   Stability- oder Load-Regulation-Arrays nicht als IV umetikettiert. Mehrere
   passende Schemata bleiben im `PDB test schema`-Select getrennt, weil
   Einheiten und Sweep-Protokolle nicht auf einer Achse vermischt werden
   duerfen. Die Karten nutzen denselben lokalen Messwert-Endpunkt und
   SVG-Renderer wie der Explorer (neueste hoechstens 300 Laeufe; ein Cap wird
   sichtbar benannt), zeichnen aber **ausschliesslich** Laeufe mit explizitem,
   gleich langem X/Y-Paar. Jede Karte hat einen getrennt lokal gespeicherten
   Modus `Curve display`: `Representative curves` ist der Default und zeigt
   eine deterministische, ueber den Rueckgabezeitraum verteilte Auswahl von
   hoechstens 32 Kurven; vorhandene fehlgeschlagene Laeufe erhalten reservierte
   Plaetze. `All returned curves` zeichnet alle vom Endpoint gelieferten
   paarbaren Kurven. Klartext nennt in beiden Modi gezeigte, paarbare und
   insgesamt gelieferte Laeufe. Der generische Explorer darf weiter auf
   Sample-Index zurueckfallen; eine als IV/CV bezeichnete Karte nie. Fehlende
   Schemata, fehlende gleich lange Paare, ausgeschlossene Laeufe und Ladefehler
   erhalten eigene Textzustaende. Read-only am lokalen TUDO-Spiegel belegt: fuenf
   IV-Schemata mit zusammen 1 960 lebenden Laeufen und ein CV-Schema mit 364;
   alle 2 324 aktuellen Paare sind laengengleich. Der generische
   `Measurements`-Block bleibt davor fuer alle anderen Arrays und skalaren
   Verteilungen sichtbar; die Spezialkarten verdraengen ihn nicht.

   **Messwert-Cache und Hintergrundladen (2026-08-27):** Dimensionen und
   Serien verwenden einen persistenten, nach lokalem Benutzer-/Institutsscope
   getrennten Stale-while-revalidate-Cache. Bei Navigation oder Remount wird
   ein Eintrag derselben Revision sofort ohne Aggregationsrequest gezeichnet;
   bei geaenderter Revision bleibt der alte Plot sichtbar, waehrend genau ein
   geteilter Request im Hintergrund aktualisiert. Gespeichert werden nur
   Spiegelantworten und der nicht geheime Scope, nie Session-, CSRF- oder
   PDB-Zugangsdaten. Der heutige Revisions-Hinweis aus Evidence-Job-ID,
   progressivem Data-Epoch und Status invalidiert Evidence-Sync-Aenderungen,
   ist aber noch **nicht autoritativ** fuer andere Schreiber. Der offene
   Backend-Vertrag ist ein billiges, auth-/institutsgescoptes
   `GET /api/stats/measurements/revision -> { revision: <opaque token> }`:
   Der Token muss in derselben DB-Transaktion bei jeder fuer Measurement-
   Dimensionen/-Serien sichtbaren Mutation wechseln (`TestRunEvidence`
   insert/update/delete/state sowie relevante Component-Zuordnung/Local-Name-
   Aenderung). Optionales `ETag`/`If-None-Match` darf 304 liefern. Erst dieser
   Token ersetzt den Job-Hinweis als autoritative Cache-Revision.
6. **Account / persoenliche PDB-Verbindung + Preferences:** Klick auf den angemeldeten
   User-Block in der Rail oeffnet einen eigenen Screen; Logout bleibt eine
   getrennte Aktion. Links stehen lokale Identitaet/Rolle/Institut, rechts die
   PDB-Verbindung mit `not configured|verified|invalid|unreachable`, Identity,
   Instituten und Pruefzeitpunkten. Codes sind zwei leere Password-Felder und
   werden nie maskiert zurueckgelesen oder im Browser gespeichert. Muster:
   Connect & test, Test, Replace sowie Disconnect mit Inline-Bestaetigung. Ein
   eigenes `Preferences`-Panel bietet `Staged preview: Tabs | Inline | Off`.
   Ein getrenntes Panel `Public share passwords` akzeptiert nur
   passwortfaehige oeffentliche HTTPS-Links und ein write-only Share-Passwort.
   `Save password` validiert nur die sichere Public-Link-Form und speichert das
   Secret verschluesselt; dieser nutzergesteuerte Request kontaktiert keinen
   externen Host. Danach zeigt die Liste nur Host, Token-Ende und
   Speicherzeit. Ob das Passwort stimmt, prueft erst der evidenzgebundene Sync.
   Entfernen hat eine eigene Aktion. Private CERNBox-Dateibrowser-Links werden
   mit dem Hinweis abgelehnt, dass sie CERN-Anmeldung/OAuth brauchen; itkFlow
   fragt nie nach dem CERN-Account-Passwort. Ein Sync nennt ein fehlendes oder
   falsches Passwort sowie private Links sichtbar als
   `skipped`/`authentication required`, statt sie als Netzstoerung oder Erfolg
   auszugeben.
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
   fuehrt niemals einen Live-PDB-Probe aus. Nur im paketierten Desktop und nur
   fuer globale Admins erscheint `Download diagnostics`: ein lokales ZIP aus
   den rollierenden, fest erlaubten `server.log`-/`desktop.log`-Dateien und
   sanitisierten Metadaten zu den letzten Sync-Jobs. Die UI warnt vor dem
   Teilen, weil freie Logtexte weiterhin Identifikatoren enthalten koennen.
   Web-Deployments und Institutsadmins bekommen weder Button noch Endpoint.

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
  primitive Arrays nur bei fehlendem oder hoechstens eindimensionalem
  `arrayDimensions` eine validierte Zeilen-Eingabe. Rohes JSON wird nie
  angezeigt oder editiert.

Beide Eingaenge erzeugen zuerst einen `IngestFile`, zeigen denselben Dry-Run
mit Messwerten, Warnungen und Issues und bieten erst bei gueltigem Ergebnis
`Stage upload` an. Das erzeugt eine Ghost-Action; es schreibt nicht direkt in
die PDB.

**Messfelder kommen aus `parameters`, nicht aus `results` (2026-08-27).** Eine
PDB-Testtyp-Definition (`getTestTypeByCode`, roh gespiegelt) nennt den
Messfeldblock **`parameters`**; alle 14 gespiegelten MODULE-Definitionen haben
ueberhaupt keinen `results`-Schluessel. Das Formular las nur `properties` und
`results` — es zeigte also die Handvoll Bedingungsfelder und **kein einziges
Messfeld**, verweigerte aber gleichzeitig das Absenden ohne Messwert: kein
Testtyp war erfassbar. `TestForm.measurementCollection()` entscheidet jetzt
bewusst mit Vorrang: `results` gewinnt, **solange es Felder traegt**; ein
fehlendes, `null`-wertiges oder leeres `results` faellt auf `parameters`
zurueck. Genau ein Block wird gerendert, ein Schema mit beiden Schluesseln
zeigt kein Feld doppelt. „Traegt Felder" statt „ist vorhanden" ist die
entscheidende Bedingung, weil ein Aufrufer legitim `results: []` erzeugt (der
Edit-Strip beim Vorbelegen) — das als „dieser Testtyp hat keine Messwerte" zu
lesen war der Weg, auf dem das leere Formular eine Schicht weiter
ueberlebt haette.

**Fail-closed vor dem Formular (2026-08-27).** Die gemeinsame reine Funktion
`TestForm.manualEntryCapability()` bewertet das nach Field-Layout effektive
Schema fuer beide Oberflaechen. Ein REQUIRED-Feld vom Typ `object`, `testRun`
oder einem anderen nicht kontrolliert erfassbaren Typ blockiert. Ein primitives
Array mit explizitem `arrayDimensions > 1` oder unlesbarer Dimensionsangabe
macht den gesamten Testtyp file-only — auch wenn dieses Array optional ist;
sonst koennte eine reale mehrdimensionale Messung still fehlen, waehrend ein
einziger Skalar als scheinbar vollstaendiger Lauf gestagt wird. Fehlt
`arrayDimensions`, ist es `null`, `0` oder `1`, bleibt die Zeileneingabe
zulaessig. Ein Schema ohne irgendein erfassbares Messfeld blockiert ebenfalls.
Optionale unbekannte Einzel-Felder blockieren dagegen nicht, solange mindestens
ein echtes Messfeld erfassbar ist.

Bei einem Block rendern weder `Add test result` noch der Worksheet-Edit-Strip
Tool-Felder oder ein halbes/totes `TestForm`. Der `info-banner` nennt Testtyp
und blockierende Felder; `Use JSON file upload` schliesst die tote Eingabe,
scrollt zum bestehenden Datei-Drop und setzt den Tastaturfokus dorthin. Dieser
Dateiweg bleibt der einzige Weg fuer die verschachtelte Originalform — es gibt
bewusst keinen Raw-JSON-Object-Editor. Das betrifft am gespiegelten MODULE-
Bestand sieben von vierzehn Definitionen, darunter `MODULE_METROLOGY`
(REQUIRED-Positionskarten) und `MODULE_IV_AMAC_TC` (REQUIRED-Objektbloecke und
echte zweidimensionale Kurven). Der Guard ist ein UI-Sicherheitsvertrag; der
Manual-Entry-API-Pfad muss separat noch gegen das gespiegelte Schema gehaertet
werden.

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
- **Zeile aufklappbar** zum vollen Run-Detail (Attachments, Kurven, Werte,
  Conditions) ueber dieselben Renderer wie bisher; geladen wird erst beim
  Oeffnen. Die Aktion ist als beschrifteter Button `Runs & plots` sichtbar und
  nicht mehr nur ein unbeschriftetes kleines Caret. Ein lokal gespeichertes,
  browserdarstellbares Attachment/Instrument-Plot steht vor der daraus
  rekonstruierten numerischen Array-Kurve; beide bleiben sichtbar.
  Dict-wertige Ergebnisse (Metrologie, Wire Bonding) rendern als
  Position/Wert-Paare statt als `[object Object]`. Ist eine Map vollstaendig
  numerisch und endlich, steht vor der weiterhin vollstaendigen Tabelle ein
  generierter kategorischer **Balkenplot — aber nur als Fallback**, wenn der
  Lauf weder eine numerische Array-Kurve noch ein darstellbares Attachment
  besitzt. Maps aus exakten `[number, number]`-Paaren bleiben Tabelle; ohne
  ausdrueckliche semantische Schema-Metadaten darf die UI daraus weder Achsen
  noch einen Scatter und insbesondere kein `Δx`/`Δy` erfinden. Gemischte,
  leere oder nicht-endliche Maps bleiben ebenfalls nur
  Tabelle, weil die Anzeige keine Punkte erfinden oder Werte umdeuten darf.
  Der bestehende Array-/IV-Kurvenpfad bleibt unveraendert und hat zusammen mit
  einem echten darstellbaren Plot-Attachment Vorrang vor diesem Fallback.
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
  geschluesselt. Ein in der PDB zurueckgezogener Lauf (`state='deleted'`)
  bleibt nur in der aufklappbaren Historie sichtbar: Der Edit-Strip darf ihn
  weder als juengsten Lauf vorbelegen noch nach einem asynchronen Fetch in
  bereits eingegebene Werte laden. `requestedToDelete` bleibt bis zum
  terminalen PDB-Zustand ein lebender Lauf.
- **File-only statt halbem Edit-Strip:** Vor Tooling und Formular gilt derselbe
  `manualEntryCapability()`-Check wie in `Add test result`. REQUIRED-
  `object`/`testRun`, mehrdimensionale primitive Arrays oder ein Schema ohne
  erfassbares Messfeld zeigen die benannten Blocker und eine direkte,
  fokussierende Aktion zum bestehenden JSON-Datei-Drop. Kein roher
  Objekt-Editor wird als Abkuerzung eingebaut.
- **Dichte Formulare bleiben scanbar:** In der Worksheet-Variante bilden
  Laufkopf, Conditions/Properties und Measurements klar getrennte kompakte
  Flaechen. Schema-Beschreibungen, die sonst jede Messzeile verdoppeln,
  bleiben per `aria-describedby` und Hover-Titel erreichbar, sind im
  Ruhezustand aber visuell verborgen; Hinweise fuer Arrays und nicht
  unterstuetzte Datentypen bleiben sichtbar, weil sie die Eingabehandlung
  aendern. Kein Feld darf fuer die Verdichtung entfallen. Sekundaer- und
  Primaeraktion (`Cancel`, `Stage test result`) stehen in derselben
  abschliessenden Aktionsleiste.
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
  Kompaktheitsvertrag wie oben. Jede Zeile mit Laeufen hat zusaetzlich den
  sichtbaren read-only Button `Runs & plots`; er laedt das volle Run-Detail
  fuer die **Seriennummer des Kindes** lazy nach, sodass dessen Attachments
  und Kurven auf der Modulseite nicht mehr unsichtbar bleiben.
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
Formel im Frontend. Der PDB-Schreibpfad validiert die auf der Action
gespeicherten `derived_results` **und** `derived_result_codes` erneut gegen
Ingest, Profil und Modultyp. Alle serverkontrollierten Codes werden zuerst aus
einer Kopie der PDB-`results` entfernt; nur vorhandene berechnete Werte werden
danach autoritativ eingesetzt. So bleibt auch bei einer fehlenden
Waagenablesung kein alter Roh-/Formelwert stehen. Der empfangene Ingest bleibt
unveraendert. Ein abweichender oder frei injizierter Wert/Code blockiert den
Worker und muss neu gestagt werden.

### Feldreihenfolge, Baender und Tool-Dropdowns in der Erfassung (2026-08-27)

Die Erfassungspanels folgen dem Produktionsblatt, nicht der Reihenfolge des
PDB-Schemas. Modul: [`frontend/src/fieldLayout.ts`](../frontend/src/fieldLayout.ts)
(rein, testbar), Laden: `dataEntryProfile.ts`, Auswahl: `ToolFieldSelect.tsx`.
Betroffen sind die Karte `Add test result` und der Edit-Strip des
Modul-Worksheets; `TestForm` bleibt der einzige Renderer der Schemafelder.

- **Reihenfolge und schreibgeschuetzte Ableitung.** Das Blatt fuehrt eine
  Klebung als „erst die Teile wiegen, dann die Baugruppe, dann das berechnete
  Klebegewicht" (Zeilen 10/17/21/24 fuer die Hybride, 35/40/43 fuer das
  Powerboard). Genau das steht bereits im
  Institutsprofil: `glue_weight_inputs` nennt je Schritt `subtract`
  (die vorher gewogenen Teile), `measured` (die Baugruppe) und `result_code`
  (die Ableitung). Die Reihenfolge wird **aus der Formel gelesen**, nicht aus
  einer Tabelle im Code — kein Feldcode, kein Modultyp ist ein Literal
  (harte Regel 4), und ein Institut mit anderer Klebekette bekommt seine
  Reihenfolge ohne Codeaenderung. Zum Vergleich die PDB-Reihenfolge von
  `GLUE_WEIGHT`: `GW_SENSOR, GW_GLUE_H2, GW_HYBRID1, GW_GLUE_PB, …` — jedes
  abgeleitete Klebegewicht zwischen den Waagenwerten, und **jedes `order`-Feld
  der Definition steht auf `1`**, es gibt dort also nichts zu sortieren.
  Ein Code, den zwei Schritte nennen (`GW_MODULE_H1` ist Ergebnis der
  Hybridklebung und Eingang der Powerboardklebung), erscheint **einmal**, im
  Band, das ihn gemessen hat — wie im Blatt. Felder, die kein Schritt nennt,
  behalten die Schemareihenfolge und stehen hinten. Ohne Profil aendert sich
  nichts. Ein aktiver `result_code` ist dagegen kein zweiter Rohwert: er wird
  aus `TestForm` entfernt und nur in der serverseitigen Ableitung angezeigt.
  Damit kann ein Operator den spaeter autoritativ hochgeladenen Wert nicht
  parallel als widerspruechliche Zahl eintippen.
  **Noch offen:** Das Live-Blatt berechnet in allen 290 Modulspalten
  `Hybrid ohne Tabs = Hybrid mit Tabs - Tabs` (Zeilen 17/20). itkFlow setzt
  `GW_HYBRID1/2` heute als fertigen Rohwert voraus; fuer diese vorgelagerte,
  abhaengige Ableitung fehlt noch ein serverseitiger Profilvertrag.
- **Baender.** Ein Band traegt das `label` des Profilschritts **woertlich**
  (Institutsdaten, wie die `assembly_tool_slots`-Labels im Wizard), nie eine
  erfundene Ueberschrift. Ein unbenanntes Restband bekommt keine.
  **Grenze, bewusst:** Ueberschriften **zwischen** den generierten
  Messfeldern kann nur `TestForm` selbst zeichnen; heute stehen sie ueber der
  Tooling-Sektion. Der fehlende Baustein ist eine `groups`-Prop an `TestForm`
  (Plan im Abschlussbericht des Schnitts).
- **Konfigurierte PDB-Tool-Felder sind Dropdowns.** Im Live-Blatt sind die
  Hybrid-Jig- und Pickup-Zeilen 28/29 praktisch durchgaengig validierte
  Serienlisten; Zeile 30 ist es nur in einzelnen Farb-Zellen, Zeile 38 fuehrt
  kombinierte Serien ueberwiegend als Freitext. Eine PDB-Definition kann ein
  echtes Tool-Feld nicht von anderem `dataType: "string"` unterscheiden, und
  der Spiegel zeigt die Folge: dieselbe
  Jig steht in 28 `MODULE_BOW`-Laeufen unter **drei** Schreibweisen, eine
  Bondmaschine in 17 Laeufen unter **vier**. Der neue, validierte
  Profilschluessel `test_tool_fields` (`{"<TEST_TYPE>": [{"code": …,
  "kinds": […], "step": …}]}`, `backend/app/institute_settings.py`) benennt
  diese Felder; sie werden aus dem generierten Formular **entfernt** und als
  Auswahl ueber die Tool-Registry gerendert (gefiltert nach `Tool.kind` und
  `compatible_types`, Label vorn, Seriennummer hinten —
  `fieldLayout.toolOptionLabel`, dieselbe Regel wie im Assembly-Wizard).
  `step` verweist auf einen `glue_weight_inputs`-Schritt und setzt das Feld
  in dessen Band, weil das Blatt seine Werkzeugzeilen **innerhalb** der
  Klebebaender fuehrt und keine Klebeformel eine Jig nennt. Wichtig:
  `GLUE_WEIGHT` besitzt im PDB-Schema **kein** Jig-/Pickup-Feld;
  `GW_METHOD` ist die Auftragsart und `GLUE_METHOD_V_*` sind
  Programmversionen. Diese Codes duerfen nicht als Tool-Slot konfiguriert
  werden. Der Glue-Werkzeugnachweis bleibt E5 und braucht den geplanten lokalen
  Nachbarspeicher; der reale, heute nutzbare Fall ist z. B. `MODULE_BOW.JIG`.
- **Scannen bleibt.** Neben jeder Auswahl steht ein Enter-terminiertes
  Scanfeld (Keyboard-Wedge, Barcode oder RFID, lokal gegen die geladenen
  Kandidaten aufgeloest). Ein Dropdown darf den schnelleren Weg nicht
  ersetzen. Die Auswahl selbst ist ein natives `<select>` und damit ohne Maus
  bedienbar; Ziele sind 40 px hoch (Handschuh, Touchscreen).
- **Nie stillschweigend aendern.** Ein gespeicherter Wert, den die Registry
  nicht kennt (der alte Freitext), bleibt ausgewaehlt und wird als
  „not in the tool registry" gekennzeichnet — statt beim Oeffnen des Strips
  auf leer zu fallen. Ein **Pflicht**-Tool-Feld blockiert das Staging mit
  Begruendung: `TestForm` kann ein Feld nicht pruefen, das es nie gesehen hat.
- **Parser faellt geschlossen zurueck.** Ein unlesbarer gespeicherter Block
  liest sich als „keine Konfiguration"
  (Schemareihenfolge, kein Dropdown) — nie halb angewandt, sonst waeren
  einzelne Felder Picker und der Rest Freitext.
- **Nebenbefund, im selben Schnitt behoben:** Der Edit-Strip belegte nur
  `definition.results` vor. Keine gespiegelte MODULE-Definition hat diesen
  Schluessel — die Messfelder liegen unter `parameters`. Der Strip oeffnete
  sich damit **leer ueber einem erfassten Lauf**. Er waehlt den Messblock
  jetzt mit derselben Praezedenz wie `TestForm.measurementFields`.

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

Auf einer geoeffneten Komponentendetailseite startet jede workeraktive Action
(`approved`, `submitted`, `failed`) einen begrenzten Poll des einzelnen
Outbox-Statusdatensatzes (hoechstens 20 Minuten; normal sekundenweise, bei
`failed` alle fuenf Sekunden). Das gilt auch nach Reload und wenn die Antwort
einer bereits serverseitig gespeicherten Push-Transition verloren ging. Jede
Statusaenderung laedt Stammdaten, Preview/Worksheet und Stage-Suggestion genau
einmal gemeinsam neu. Nur `confirmed` und `cancelled` beenden die Beobachtung:
`failed` ist nicht terminal, weil der Worker nach Backoff ueber `submitted`
erneut versucht. Damit kann ein frisch bestaetigter Pflichttest ohne
Navigation den Stage-Move freischalten; Draft/Validated/Approved/Submitted
bleiben ausschliesslich Preview und duerfen das echte Gate nie erfuellen.

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
- **Freeze-/Retry-Vertrag (2026-08-27):** `Check status` liest einen
  vermeintlich haengenden Job neu. Erst wenn das Backend dessen Heartbeat nach
  derselben Lease-Grenze als stale markiert, bietet die UI `Retry sync` an.
  Der neue Lauf uebernimmt die Lease per Compare-and-swap; jeder Schreib- und
  Dateipublikationsschritt des alten Workers prueft weiterhin Job-ID und
  Lease-Token. Ein spaet erwachender Worker kann deshalb weder Fortschritt,
  Terminalstatus noch Attachment-Datei des Nachfolgers ueberschreiben. Die UI
  dedupliziert den aktiven Job nach Job-ID und entdeckt nach einem Reload den
  serverseitig weiterlaufenden Sync wieder.
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

### Klebe-Urteil: unmoegliche Messwerte (2026-08-27)

Neben `No target`, `Missing readings` und `Not measured` gibt es einen vierten
Grund fuer ein ausbleibendes Urteil: **`Readings contradict each other`**
(`implausible_result`). Er erscheint, wenn alle Waagenwerte vorliegen, das
daraus errechnete Klebegewicht aber negativ ist — physikalisch unmoeglich, in
der Praxis zwei vertauschte Felder. Der Chip bleibt bernsteinfarben wie jeder
andere unbekannte Ausgang; entscheidend ist, dass die Zeile **nicht** „zu
wenig" sagt und damit dem Operator einen Fehler zuschreibt, den die Eingabe
gemacht hat. Begruendung und Zahlen: [`11`](11-logistics-operations.md).

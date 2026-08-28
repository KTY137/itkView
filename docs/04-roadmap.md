# Living Roadmap: itkFlow

> Dieses Dokument ist der aktive Ausfuehrungsfahrplan.
> [`02-revamp-plan.md`](02-revamp-plan.md) beschreibt die Produktvision und
> Architektur; diese Roadmap beschreibt, was als Naechstes gebaut, stabilisiert
> und abgenommen werden soll.
>
> - **Besitzt:** den Abschnitt „Aktueller Stand" (das laufende Protokoll jeder
>   Verhaltensaenderung), die naechsten Arbeitspakete, den Restumfang je
>   Fachdokument und die Meilensteine Phase 0–6.
> - **Fuer wen:** jeden Agenten und jede Person vor groesserer Planung oder
>   Implementierung — und jeden, der wissen will, was heute wirklich existiert.
> - **Verwandt:** [`00-doc-map.md`](00-doc-map.md) (welches Fachdokument im
>   selben Change nachgezogen wird), [`02-revamp-plan.md`](02-revamp-plan.md)
>   (Vision statt Ausfuehrung), [`05-ui-design-reference.md`](05-ui-design-reference.md)
>   (verbindlich fuer UI-Arbeit), [`superpowers/specs/`](superpowers/specs)
>   (Zielvertraege einzelner Schnitte), [`README.md`](README.md) (Lesepfade).

## Agenten-Regel

Jeder Agent liest vor groesserer Planung oder Implementierung `CLAUDE.md` und
dieses Dokument. Arbeit wird dem naechsten passenden Meilenstein zugeordnet.
Wenn ein Agent Roadmap-Arbeit erledigt, neu zuschneidet oder blockiert, muss er
entweder diese Roadmap aktualisieren oder im Abschluss klar notieren, welcher
Roadmap-Punkt betroffen ist und warum keine Aktualisierung erfolgt ist.

UI-Arbeit folgt zusaetzlich der verbindlichen Design-Referenz
[`05-ui-design-reference.md`](05-ui-design-reference.md) (+ Mockup
[`itkflow-ui-mockup.html`](itkflow-ui-mockup.html)), damit die Umsetzung nicht
vom Design-Ziel abdriftet.

## Aktueller Stand (2026-08-28)

- **itkView wird als eigenes fail-closed Read-only-Release `v0.1.0`
  vorbereitet (2026-08-28):** Der gemeinsam gepruefte Kern baut wahlweise
  itkView oder fuer explizite Regressionen itkFlow; das dedizierte
  itkView-Repository startet, testet und paketiert ohne Variantenschalter
  immer das eigenstaendig gebrandete itkView. Im Viewer verschwinden
  `Staged`/Outbox, `Triage`, Assembly, Registrierung, Test-Dateiupload, manuelle
  Testerfassung, Stage-Moves und die zugehoerigen Edit-/Push-Einstiege;
  Mirror-Sync, Bilder, Plots, Statistics, Suche und Production-Hold-Anzeigen
  bleiben. Die Grenze ist nicht nur UI: der Server klassifiziert unsichere
  Mutationen fail-closed, erlaubt nur die benoetigten Auth-/Admin-/Credential-
  und Read-Sync-POSTs und sperrt PDB-Submitter, direkte Registrierung,
  In-Process- sowie Standalone-Outbox-Worker. Desktop-App-ID, Sidecar,
  Datenbank/Attachments/Logs, Credential-Key und hostweit geltende Cookies
  sind zwischen beiden Produkten getrennt. Der dedizierte Compose-Stack
  besitzt ausserdem den Projektnamen `itkview`, eine eigene PostgreSQL-
  Datenbank und getrennte persistente Datenbank-/Attachment-Volumes; eine
  itkFlow-`.env` oder deren Key ist keine Migrationsquelle. Vertrag und
  Begruendung: [`ADR 007`](adr/007-itkview-read-only-product.md).
  **Abnahme:** Backend offline `1282 passed` plus `41` fokussierte finale
  Varianten-/Desktop-Tests, Frontend `316 passed`, View-Default- und expliziter
  Flow-Regressionsbuild, sechs Desktop-Variantenvertraege sowie Compose-
  Aufloesung sind gruen. Offen sind nur noch der paketierte Sidecar-Smoke, die
  Installer-Pruefung, Tag und GitHub-Release.

- **Modul-Uebersichten markieren konfigurierte Gate-Abweichungen
  fail-closed (2026-08-28):** `GET /api/components` und die Detailantwort
  tragen eine serverseitig gebatchte `production_status`-Projektion. Ein rotes
  `Production hold` erscheint erst, wenn ein Modul eine konfigurierte
  Requirement-Stage bereits ueberschritten hat und deren neueste lebende
  Evidenz `failed`/`missing` ist; ein Test in der aktuellen Arbeitsstage ist
  weiterhin normales WIP. Board, Komponentenliste, Family-Tree und Detailkopf
  zeigen den textlich/barrierefrei erklaerten `!`-Marker, Hold-Karten verlieren
  den irrefuehrenden gruenen `FINISHED`-Ton, Liste/Board koennen Holds priorisieren
  und die Detailseite zeigt einen persistenten Hinweis. Seed- oder nicht
  explizit mit `stage_policy_approved=true` abgenommene Profile heissen
  `provisional workflow`; ohne Abweichung liefern sie niemals ein fachliches
  `clear`. Admin Settings bietet dafuer eine separate bewusste Freigabe; jede
  Aenderung an Stage-Reihenfolge oder Requirements verwirft sie automatisch.
  Modellfremde/stale
  Module bleiben `unknown`, Nicht-Module und trashed Zeilen `not_applicable`.
  Gleichzeitig ist die Evidence-Fusion gehaertet: nur worker-bestaetigte,
  institutsrichtige Uploads mit External-Ref und echtem Boolean zaehlen
  provisorisch; ein spaeterer bzw. derselbe gespiegelte PDB-Lauf bleibt
  autoritativ. Operatoren koennen `confirmed`/`failed` nicht mehr ueber den
  generischen Transition-Endpunkt setzen. **Offen:** TUDO braucht weiterhin
  das fachlich abgenommene, familien-/Requirement-Modi-faehige Profil aus
  [`10`](10-itk-domain-reference.md) §7; der Marker ist keine Aussage ueber
  einen physischen Defekt.

- **Manuelle Testerfassung entscheidet jetzt fail-closed aus dem effektiven
  Schema (2026-08-27):** `TestForm.manualEntryCapability()` ist die gemeinsame
  Entscheidung fuer Karte und Worksheet-Edit-Strip, jeweils **nach** dem
  Feldlayout. REQUIRED-`object`-/`testRun`-Felder blockieren die manuelle
  Erfassung; primitive Arrays sind nur bei fehlendem oder hoechstens
  eindimensionalem `arrayDimensions` sicher, jede explizit hoehere oder
  unlesbare Dimension macht den Testtyp file-only. Statt Tool-Felder plus
  halbem/totem Formular nennen beide Oberflaechen die blockierenden Felder und
  fuehren mit `Use JSON file upload` direkt (Scroll + Fokus) zum bestehenden
  Datei-Drop. Es gibt bewusst keinen Raw-JSON-Object-Editor. Am anonymisiert
  ausgewerteten MODULE-Spiegel sind damit 7 von 14 Definitionen vollstaendig
  manuell erfassbar (`ATLAS18_RECOVERY`, `GLUE_WEIGHT`, `MODULE_BOW`,
  `MODULE_IV_PS_BONDED`, `MODULE_IV_PS_V1`, `MODULE_WIRE_BONDING`,
  `VISUAL_INSPECTION`); die anderen sieben, insbesondere
  `MODULE_METROLOGY` und `MODULE_IV_AMAC_TC`, bleiben ehrlich Datei-Upload.
  Der Frontend-Vertrag ist mit Capability-, Formular-, Worksheet- und echter
  Screen-Integration abgedeckt. **Offene Haertung:** Der Manual-Entry-Ingestor
  validiert API-Payloads noch nicht gegen das gespiegelte Schema; der UI-Guard
  allein ist keine serverseitige Autorisierung.

- **TUDO nutzt fuer Stage-Gates weiterhin den Seed-Default, nicht ein
  abgenommenes Institutsprofil (read-only Audit 2026-08-27):** Das lokale
  Live-Profil enthaelt weder `stage_order` noch `stage_requirements` oder
  `required_properties`; damit greift die generische Seed-Reihenfolge. Vor
  einer fachlichen Freigabe muss der Owner fuer jede Modul-Familie
  `required`/`mayFail`/optional/if-present festlegen, die Alternative
  `MODULE_IV_AMAC | MODULE_IV_AMAC_TC` ausdruecklich entscheiden und klaeren,
  welche Kind-Evidenz ein Eltern-Gate erfuellt. Der Code erfindet diese Policy
  nicht aus Live-Haeufigkeiten.

- **Der Inline-Editor bleibt auch bei grossen Schemata lesbar
  (2026-08-27):** Die Worksheet-Variante des generierten Formulars gruppiert
  Laufkopf, Conditions/Properties und Measurements als drei kompakte
  Flaechen. Wiederholende Schema-Beschreibungen stehen nicht mehr dauerhaft
  unter jedem der 19 `GLUE_WEIGHT`-Felder, bleiben aber fuer Screenreader ueber
  `aria-describedby` und fuer Mausnutzer als nativer Hover-Titel erhalten;
  Array- und Unsupported-Hinweise bleiben sichtbar. `Cancel` und
  `Stage test result` teilen sich jetzt eine Aktionsleiste. Im anonymisierten
  1600-px-UI-Audit sank der reale Edit-Strip von 1 698 auf 1 254 px Hoehe,
  ohne ein Feld auszublenden. Vorher-/Nachher-Aufnahmen liegen unter
  `artifacts/ui-audit/`.

- **Statistics zeigt IV und CV jetzt als eigene Kollektivkurven
  (2026-08-27):** Zwei Karten entdecken kompatible Current/Voltage- bzw.
  Capacitance/Voltage-Paare aus dem lokalen Measurement-Dimensions-Endpunkt;
  weder Instituts- noch exakte PDB-Testtyp-Codes stehen im Frontend. Ein
  Familienmarker verhindert, dass Current-Stability oder Load-Regulation als
  IV ausgegeben werden. Mehrere Schemata bleiben wegen verschiedener Einheiten
  und Sweep-Protokolle waehlbar statt vermischt. Die expliziten Karten zeichnen
  nur gleich lange X/Y-Arrays und nennen ausgeschlossene Laeufe, fehlende
  Schemata/Paare, Ladefehler und den bestehenden 300-Run-Cap; der generische
  Messwert-Explorer samt Scalar-Verteilungen steht davor und bleibt erhalten.
  IV und CV speichern getrennt `Representative curves` (Default,
  deterministische Auswahl bis 32 inklusive vorhandener Failures) oder
  `All returned curves`; sichtbarer Klartext nennt Auswahl-/Pair-/Return-
  Counts. Dimensionen und Serien liegen in einem benutzer-/institutsgescopten
  persistenten SWR-Cache: gleiche Revision rendert ohne Aggregationsrequest,
  eine geaenderte Evidence-Job-/Epoch-Revision aktualisiert im Hintergrund mit
  In-flight-Deduplizierung. Offen bleibt der kleine autoritative Backend-
  Revision-Endpoint fuer Mutationen ausserhalb dieses Sync-Jobs; sein genauer
  Vertrag steht in [`05`](05-ui-design-reference.md). Der lokale Spiegel
  belegt read-only fuenf IV-Schemata/1 960 lebende Laeufe und
  ein CV-Schema/364 Laeufe, aktuell 2 324 von 2 324 Paaren laengengleich.
  UI-Vertrag und Offline-Mockup sind in [`05`](05-ui-design-reference.md)
  nachgezogen; fokussierte Helper-/Screen-/Cache-Tests decken Erkennung,
  Fehlklassifikation, Paarfilter, Sampling, Umschalten, Remount,
  Revisionsinvalidierung und Empty States ab.

- **Statistics zeigt Pflichttest-Lage je Stage datengetrieben
  (2026-08-27):** `GET /api/stats/required-tests` aggregiert das effektive
  Institutsprofil ueber den bestaetigten lokalen Mirror. Je Stage/Testtyp
  werden Komponenten auf oder hinter der Stage in `passed`, `failed` und
  `missing` geteilt; pro Komponente zaehlt nur der neueste lebende Lauf,
  `deleted`/trashed Evidence sowie Draft/Submitted/Staged nicht. Die Liste
  steht vor den Measurement-Plots, folgt der Profilreihenfolge und besitzt
  Loading-, Empty-, Error- und Retry-Zustaende. Backendvertrag und Frontend
  sind fokussiert getestet; es gibt keine hart codierte Metrology- oder
  Instituts-Sonderregel.

- **Sync-Retry ist gegen spaete Zombie-Worker eingezaeunt (2026-08-27):** Das
  Backend kennzeichnet stale Heartbeats im Jobvertrag; nur dann bietet die UI
  nach `Check status` einen bewussten Retry. Claim, Fortschritt, Fehler,
  Finalisierung und jede DB-/Attachment-Publikation sind an Job-ID plus
  Lease-Token gebunden. Nach einer CAS-Uebernahme kann ein alter Worker weder
  neuen Status noch Dateien ueberschreiben. Seit der Mehrprozess-Haertung vom
  2026-08-28 besitzt zudem jeder Fetch eine exklusiv erzeugte `.part`-Datei;
  verliert der alte Worker seinen Fence, kann sein Cleanup weder Staging noch
  Zieldatei des Nachfolgers beruehren. Abgelehnte Executor-Submits
  terminalisieren sauber und geben Queue-Watch/Lease frei. Der Frontend-
  Controller dedupliziert Jobs und entdeckt einen nach Reload weiterlaufenden
  Serverjob wieder. Fencing-Regressionen decken Progress, Component-Commit,
  Evidence-Commit und Attachment-Publikation ab.

- **Desktop-Crashdiagnose ist lokal, rollierend und exportierbar
  (2026-08-27):** Paketierte Builds schreiben `server.log` (5 MiB, drei
  Rotationen) und `desktop.log` (1 MiB, drei Rotationen) im App-Datenordner.
  Python-Faulthandler erfasst Thread-Stacks; der Rust-Launcher protokolliert
  nur strukturierte Lifecycle-/Health-/Prozessdaten und zeigt einen
  post-navigation Backend-Ausfall im Fenster, ohne Auto-Restart-Schleife.
  Globale Desktop-Admins koennen ueber Operations Health ein Diagnose-ZIP aus
  der festen Log-Allowlist plus sanitisierten letzten Sync-Metadaten laden;
  Datenbank, Settings, Secrets, Environment, Host-/Usernamen und Attachments
  sind ausgeschlossen. Der Endpoint ist im Web nicht vorhanden.

- **Passwortgeschuetzte oeffentliche Shares sind persoenliche Account-Daten
  (2026-08-28):** Der Account-Screen speichert nur sichere
  ownCloud-/Reva-Public-Share-Formen. Der nutzergesteuerte
  `PUT /api/account/share-credentials` validiert ausschliesslich die URL-Form
  und bleibt strikt netzwerkinert; damit ist er kein direkter SSRF-Proxy.
  Das Share-Passwort liegt per-user mit AES-256-GCM/AAD verschluesselt und wird
  nie zurueckgegeben. Ob das Passwort stimmt, prueft erst der an eine
  gespiegelte Evidence-URL gebundene Sync; seine Credential-Redirects duerfen
  die HTTPS-Origin (Host plus effektiven Port) nicht verlassen. Evidence-Jobs verwenden nur die
  Credentials ihres `SyncJob.user_id`; fehlendes/falsches Passwort,
  Login-HTML und private Browserlinks werden als `skipped` und davon
  `authentication_required` gezaehlt. Derselbe geschuetzte Share wird im
  Sweep nach dem ersten Auth-Befund nicht hunderte Male angefragt. Private
  CERNBox-Accountlinks bleiben bewusst ausserhalb dieses Schnitts und
  brauchen spaeter CERN-OAuth; itkFlow sammelt kein CERN-Account-Passwort.
  Schema-deklarierte URL-Strings koennen bereits durch den normalen manuellen
  Test-/Outbox-Flow in die PDB gelangen und werden danach als Evidence
  gespiegelt; es gibt keinen erfundenen Result-Code und keinen Datei-Upload in
  CERNBox. Details [`12`](12-attachments-and-images.md) §2.3b.

- **Pflichttest-Erfassung schliesst den Stage-Move jetzt auf derselben offenen
  Detailseite (2026-08-27):** Der Requirement-Stift fuehrt durch den realen
  Worksheet-Weg `manual-entry`-Ingest -> Dry-Run -> Outbox-Draft. Nach `Push`
  pollt die Seite begrenzt den einzelnen Action-Status und laedt bei der
  Worker-Antwort Detail, Preview/Worksheet und Stage-Suggestion gemeinsam neu;
  nur `confirmed` zaehlt als Evidenz, nie ein Draft oder `submitted`. Danach
  kann der neu gueltige `stage_move` direkt vorgeschlagen werden. Ein
  zwischenzeitliches `failed` beendet den begrenzten Watch nicht: der
  automatische Retry `failed -> submitted -> confirmed` bleibt auf derselben
  Seite sichtbar; dasselbe gilt nach Reload oder einer verlorenen
  Push-Transition-Antwort. Der
  Edit-Strip ignoriert ausserdem terminal zurueckgezogene (`deleted`) Laeufe
  beim Vorbelegen und laedt sie auch nach einem spaeten Fetch nicht in eine
  laufende Eingabe. Abgedeckt durch einen echten UI-Integrationstest des
  ganzen Bedienwegs plus zwei Withdrawn-Prefill-Regressionen; UI-Vertrag in
  [`05`](05-ui-design-reference.md).

- **Unmoegliche Klebegewichte sind kein Urteil mehr (2026-08-27):** Beim ersten
  Seeden des TUDO-Glue-Profils lieferten zwei lebende Laeufe negative
  Klebegewichte (−8696 mg, −7771 mg) — vertauschte Felder, `GW_MODULE_H1` und
  `GW_GLUE_H1` ueber Kreuz — und wurden mit voller Zuversicht als `too_little`
  beurteilt. Genau der Fehler des abgeloesten Blattes, nur mit besserer
  Arithmetik. Ein negatives Ergebnis meldet jetzt
  `verdict=unknown, reason=implausible_result`; 48 der 50 lebenden Messungen
  bleiben unveraendert. Nur die Untergrenze steht im Code (Physik), jede
  Obergrenze waere eine Ermessensfrage und gehoert ins Profil. Details
  [`11`](11-logistics-operations.md), UI-Text [`05`](05-ui-design-reference.md).

- **Die 87 Bilder hinter der Ordner-Freigabe sind erreichbar — sie lagen in
  einem Tar (2026-08-27).** Live und anonym gegen die Share-Links des Owners
  gemessen (nur GET, keine Zugangsdaten, kein PDB-Kontakt). **Ein einziger**
  CERNBox-Ordner-Token trägt 87 Deskriptoren auf 76 Powerboards, zusammengefasst
  20 Attachment-Zeilen, von denen **null** je gespeichert waren. Die DAV-Route
  antwortet dort **501 Not Implemented** — eine Aussage über Fähigkeit, die
  kein Login ändert; deshalb war „CERNBox-Anmeldefeld" die falsche Antwort.
  `/s/<token>/download?files=<Eintrag>` antwortet dagegen mit einem POSIX-**Tar**
  (nicht ZIP, wie docs/12 bisher behauptete), und der „Dateiname" des
  Deskriptors ist gar keine Datei, sondern ein **Ordner** mit zwei JPEGs, zwei
  32-MB-Canon-Rohdateien und einer Notiz. Neu: itkFlow packt **genau ein**
  vollständiges Mitglied **im Speicher** aus und übergibt dessen Bytes dem
  bestehenden Ablageweg; beim Vergleich mit dem bisherigen Gewinner überlappt
  höchstens das feste 512-Byte-Sniff-Präfix eines Nachfolgers. Für verschiedene
  normalisierte Pfade gewinnt `(Rang, Pfad)` mit Rang 0 = benannter Eintrag,
  1 = per Magic Bytes gesnifftes browserdarstellbares Bild, 2 = anderes echtes
  Bild, 3 = anderes speicherbares Format, 4 = Rest. Bei einem im Tar doppelt
  vorkommenden normalisierten Pfad gilt bewusst **first wins**; spätere
  Dubletten werden ignoriert. Nennt die URL
  keinen Eintrag, wird nur ein Archiv mit genau einem Kandidaten akzeptiert.
  **Sicherheit ist hier die Sache, nicht die Fußnote:** nie `extractall` (per
  AST-Test am geparsten Modul festgenagelt), nur reguläre Dateien (Symlinks,
  Hardlinks, Geräte, FIFOs, Verzeichnisse, GNU-Sparse am Typ abgelehnt),
  Namensprüfung gegen `..`, absolute Pfade, Backslash, Laufwerksbuchstaben und
  Steuerzeichen, Scope-Prüfung gegen den benannten Eintrag (die gemessene
  „ganze Freigabe"-Antwort wählt damit **nichts**), die **deklarierte** Größe
  entscheidet vor dem Lesen, vier Deckel (komprimierte Draht-Bytes,
  dekomprimierter Tar-Strom inklusive GNU-/PAX-Metadaten, Summe der
  deklarierten Bytes, Mitgliederzahl 2048), alle aus
  `attachment_max_bytes` abgeleitet, und nie mehr als ein vollständiges
  Mitglied plus das 512-Byte-Präfix im Speicher. Tar und gzip-Tar, sonst
  nichts; ein gzip-Strom gilt erst als Archiv, wenn die `ustar`-Magic im
  **dekomprimierten** Präfix steht. Optionale gzip-Headerfelder und der
  anschließende Deflate-Strom haben getrennte feste 128-KiB-Sniff-Budgets;
  ein danach noch unentscheidbarer Strom wird abgelehnt.
  HTML-Abwehr, Größenlimit und Content-Sniffing laufen unverändert über die
  extrahierten Bytes; der `content_type` kommt aus den Magic Bytes vor der
  Endung, sonst landete die Datei endungslos und bliebe unsichtbar. Die 16
  funktionierenden Datei-Freigaben sind unberührt (eigener Test: ein Payload
  jenseits des Sniff-Fensters kommt byteweise identisch an). **Kein Cache**,
  begründet gemessen: 87 Deskriptoren fallen über `(source, code)` ohnehin auf
  20 Abrufe zusammen, und jeder Code ist ein eigener Ordner — ein LRU über
  80-MB-Archive kostete hunderte MB und spart null Abrufe. Gemerkt wird nur das
  **Verdikt**: pro Sweep die `(source, code)` mit endgültigem Fehlschlag
  (gedeckelt, ohne Bytes), sonst würde dieselbe abgelehnte Freigabe bis zu
  neunmal geholt; transiente Fehlschläge nie, und nichts überlebt den Sweep —
  ein DB-Flag hätte genau die Zeilen eingefroren, die dieser Schnitt repariert.
  Am echten Archiv nachgemessen: gewählt `20USED50000029_2.JPG`, 8 845 759 B,
  gesnifft `image/jpeg`. Preis, bewusst akzeptiert: 79 MB Archiv je Bild,
  einmalig ~1,5 GB für die 20 Zeilen — nur eine Auflistung der Freigabe könnte
  das vermeiden, und genau die verweigert die 501. 134 Attachment-Tests
  (Basis 82); die Schutzregeln sind einzeln als fehlschlagbar nachgewiesen,
  einschliesslich GNU-longname/PAX und Log-Privacy. Details
  [`12`](12-attachments-and-images.md) §1, §2.3, §2.3a,
  §3.4, §8.1, §9.

- **Live-Sheet-Korrektheitsaudit und E3-Uploadnaht (2026-08-27).** Der
  Modulkleber-Kern ist gegen alle relativ fortgeschriebenen Live-Formeln
  abgeglichen: Hybrid- und Powerboard-Arithmetik, TrueBlue-Ziele (inklusive
  R2), inklusive Toleranzgrenzen und Gramm↔Milligramm stimmen. Urteil wird auf
  dem ungerundeten Formelwert gebildet; nicht-endliche Waagenwerte gelten als
  fehlend. `result_code`-Felder sind keine editierbaren Doppelwerte mehr,
  sondern ausschliesslich Serverausgabe. Beim PDB-Write werden die auf der
  Action gestagten Werte erneut aus unveraendertem Ingest, aktuellem Profil und
  exaktem `type_code` berechnet; Werte **und** die vollstaendige Menge
  serverkontrollierter Outputcodes muessen exakt uebereinstimmen. Diese Codes
  werden zuerst aus einer Kopie der Roh-`results` entfernt und nur tatsaechlich
  berechnete Werte wieder eingesetzt. Damit kann auch bei fehlender
  Waagenablesung kein alter/fremder Formelwert durchrutschen. Freie Injection
  und kollidierende Outputcodes scheitern geschlossen. Frontend-seitig sind
  `by_type_code`, der
  echte PDB-Typ fuer Tool-Fits, leere Kompatibilitaetslisten und der
  Profil-Lade-Race korrigiert. **Noch offen:** die im Live-Sheet in 290/290
  Spalten aktiven Vorformeln `GW_HYBRID1T-GW_T1 -> GW_HYBRID1` und analog H2;
  ein gespeichertes TUDO-Profil (der auditierte Stand war `{}`); die explizite
  Regel fuer zwei Glue-Urteile gegen ein PDB-`passed`-Bit; sowie der lokale
  Glue-Werkzeugnachweis aus E5. `GW_METHOD`/`GLUE_METHOD_V_*` sind keine
  Tool-Slots. Mischungsrechner, Line-Speed-Korrektur und die historische
  einseitige Hybrid-ASIC-Regel gehoeren zu eigenen, noch nicht implementierten
  Spreadsheet-Schnitten und duerfen nicht als Teil dieses Modul-E3 gelten.

- **Erfassungspanels folgen dem Blatt: Reihenfolge, Baender, Tool-Dropdowns
  (2026-08-27).** Gegen den Live-Export des Blattes „Production Overview
  TU Dortmund" gearbeitet, nicht gegen die Abschrift. Drei Befunde, alle
  behoben. (1) **Die Feldreihenfolge war keine.** Die PDB listet `GLUE_WEIGHT`
  als `GW_SENSOR, GW_GLUE_H2, GW_HYBRID1, GW_GLUE_PB, …` — jedes abgeleitete
  Klebegewicht zwischen den Waagenwerten — und setzt **jedes `order`-Feld auf
  1**, es gab also nichts zu sortieren. Das Blatt fuehrt dieselben Felder als
  „erst die Teile, dann die Baugruppe, dann die Ableitung" (Zeilen 10/17/21/24
  bzw. 35/40/43). Genau das steht schon im Institutsprofil: `glue_weight_inputs`
  nennt je Schritt `subtract`, `measured` und `result_code`. Die neue reine
  Einheit `frontend/src/fieldLayout.ts` **liest die Reihenfolge aus der Formel**
  — kein Feldcode und kein Modultyp als Literal (harte Regel 4), und die
  Reihenfolge kann der Arithmetik nie widersprechen. Aktive `result_code`s
  werden dabei als berechnete Serverausgabe aus dem Formular entfernt. Ein
  Code, den zwei Schritte nennen, erscheint einmal, im messenden Band. Ohne
  Profil bleibt alles wie vorher. (2) **Echte PDB-Tool-Felder waren Freitext.** Eine
  PDB-Definition kann `MODULE_BOW.JIG` nicht von beliebigem
  `dataType: "string"` unterscheiden, und der Spiegel
  zeigt den Preis: dieselbe Jig in **28 `MODULE_BOW`-Laeufen unter drei**
  Schreibweisen, eine Bondmaschine in **17 Laeufen unter vier**. Neuer
  validierter Profilschluessel `test_tool_fields`
  (`{"<TEST_TYPE>": [{"code", "kinds", "step"}]}`, `app/institute_settings.py`,
  `null` loescht, leere Liste wird mit Begruendung abgelehnt): die genannten
  Felder verlassen das generierte Formular und werden zur Auswahl ueber die
  bestehende Tool-Registry, clientseitig gefiltert nach `Tool.kind` und
  `compatible_types`,
  Label vorn und Seriennummer hinten (dieselbe Regel wie im Assembly-Wizard,
  jetzt eine gemeinsame Funktion). `step` haengt das Feld an ein
  `glue_weight_inputs`-Band. Das ist Infrastruktur, keine Glue-PDB-Zuordnung:
  das reale `GLUE_WEIGHT`-Schema hat kein Jig-/Pickup-Feld; `GW_METHOD` ist die
  Auftragstechnik und `GLUE_METHOD_V_*` sind Programmversionen. Die
  Sheet-Toolzeilen 28/29 sind Serienlisten, 30/38 dagegen nur teilweise bzw.
  kombinierter Freitext und brauchen fuer E5 lokalen Nachbarspeicher.
  **Der Scanpfad bleibt** — Enter-terminiertes Wedge-Feld neben jeder Auswahl,
  lokal aufgeloest; das native `<select>` ist ohne Maus bedienbar. Ein
  gespeicherter Wert, den die Registry nicht kennt, bleibt **ausgewaehlt und
  gekennzeichnet** statt still zu verschwinden; ein Pflicht-Tool-Feld
  blockiert das Staging mit Begruendung, weil `TestForm` ein Feld nicht
  pruefen kann, das es nie gesehen hat. (3) **Der Edit-Strip oeffnete leer
  ueber einem erfassten Lauf.** Er belegte nur `definition.results` vor —
  keine gespiegelte MODULE-Definition hat diesen Schluessel, die Messfelder
  liegen unter `parameters`. Jetzt dieselbe Praezedenz wie
  `TestForm.measurementFields`.
  **Offene Naht, bewusst:** Ueberschriften **zwischen** den generierten
  Messfeldern kann nur `TestForm` zeichnen (eine `groups`-Prop); heute stehen
  die Baender ueber der Tooling-Sektion. Ebenso offen: ein Admin-Settings-
  Abschnitt fuer `test_tool_fields` — der Schluessel ist heute nur ueber die
  Settings-API setzbar. Ebenfalls offen sind die Live-Sheet-Vorformeln fuer
  Hybridgewichte ohne Tabs. Verifiziert: `tsc` und die fokussierten Frontend-
  und Backend-Suiten sauber. Details docs/05.

- **Kein Testtyp war erfassbar — Messfelder liegen unter `parameters`
  (2026-08-27).** `TestForm` baute seine Felder aus `definition.properties`
  und `definition.results`. Keine der 14 gespiegelten PDB-Definitionen hat
  einen `results`-Schluessel: die Messfelder stehen unter **`parameters`**
  (GLUE_WEIGHT 19, VISUAL_INSPECTION 18, MODULE_WIRE_BONDING 22,
  HYBRID_TESTS_SUMMARY 36). Das Formular rendert also nur die
  Bedingungsfelder und verweigerte zugleich das Absenden ohne Messwert —
  ein Totalblocker fuer jeden Testtyp, ausgeliefert und zweimal beim Owner
  aufgeschlagen. `TestForm.measurementCollection()` entscheidet den Vorrang
  jetzt an einer Stelle: `results` gewinnt, solange es Felder traegt, sonst
  `parameters`; genau ein Block wird gerendert. Am Live-Spiegel nachgemessen:
  7 der 14 Definitionen sind nach dem neuen Capability-Vertrag vollstaendig
  erfassbar. `MODULE_METROLOGY` hat zwar ein skalares Messfeld, verlangt aber
  zwei `object`-Positionskarten; `MODULE_IV_AMAC_TC` verlangt fuenf
  Objektbloecke und traegt echte zweidimensionale Kurven. Beide sind daher wie
  `HYBRID_TESTS_SUMMARY` und `MODULE_TC` file-only — ein einzelnes
  darstellbares Feld macht kein vollstaendig absendbares Schema. Ursache der Blindheit: **jede** bisherige Fixture war
  `results`-foermig, eine Form, die die PDB nie liefert; die neuen Fixtures in
  `frontend/src/test/pdbTestTypeSchemas.ts` sind wortgleich aus dem
  Live-Spiegel kopiert. Server-seitig bleibt Haertung offen: Der Dry-Run
  prueft die grundsaetzliche Payload-Form, aber nicht REQUIRED-Codes und
  Array-Dimensionen gegen die gespiegelte Definition; der API-Pfad darf sich
  langfristig nicht allein auf den Frontend-Guard verlassen.
  Doku: [`05`](05-ui-design-reference.md) „Testerfassung".

- **Sync brach immer bei Step 2 ab (2026-08-27, gegen den echten Spiegel
  diagnostiziert).** Zweimal exakt bei 489/3839 Dateien — deterministisch,
  kein Netzausfall. Ab Position 487 zeigen **87 aufeinanderfolgende**
  CERNBox-Links in **eine** Ordner-Freigabe; CERNBox antwortet dort mit
  **HTTP 501**, unser Klassifikator hielt jedes 5xx fuer voruebergehend, und
  fuenf Fehlschlaege in Folge liessen den Outage-Breaker den **ganzen Job**
  abreissen — bei einwandfrei antwortender PDB. Behoben: (1) 501/505 sind
  dauerhafte Antworten, kein Retry-Fall (`app/pdb_sync.py` gleichgezogen);
  (2) der Breaker zaehlt **pro Remote** — ein totes Share-Host wird
  uebersprungen, nur ein PDB-Ausfall laesst den Sweep scheitern. **Keine
  CERN-Zugangsdaten noetig**, cernbox ist anonym erreichbar. Offen und
  bewusst getrennt: die 87 Bilder liegen als **tar-Archiv** hinter einer
  Ordner-Freigabe; sie zu spiegeln ist ein eigener Schnitt. Details docs/09.

- **Stiller Verlust des Evidence-Retrys behoben (2026-08-27).** Ein
  Zeitstempel-Gleichstand (Windows-Uhr ~15,6 ms) liess das Retry-Verdikt eines
  transient gescheiterten Evidence-Nachlaufs ungeschrieben; ein fehlender
  Schluessel ist weder `due` noch `blocked`, also wurde **kein** Retry geplant
  und der Nachlauf verschwand bis zum naechsten Handsync. Ursache: ein Helfer,
  der fuer die Abdeckungsfrage korrekt strikt vergleicht, entschied auch ueber
  das Schreiben des Verdikts, wo die sichere Richtung die umgekehrte ist.
  Gefunden als vermeintlich flakiger Test — die Testvorbedingung haengt jetzt
  nicht mehr an der Uhraufloesung. Details docs/09.

- **Nicht darstellbare Bildformate (2026-08-27):** `is_image` beantwortet
  „ist das ein Bild?“, die Galerie braucht „malt ein Browser das?“. Die
  Content-Type-Reparatur hätte zwei 36-MB-TIFFs wahrheitsgemäß auf
  `image/tiff` gesetzt und damit zwei dauerhaft kaputte Kacheln geliefert —
  ein behobener Fehler, der einen neuen ausliefert. Die Galerien behalten
  deshalb jedes lokal gespeicherte `image/*` in seiner Besitzergruppe, prüfen
  erst beim Rendern `isDisplayableImage()` (`frontend/src/ui.ts`) und zeigen
  TIFF/sonstige nicht browserdarstellbare Formate als Platzhalter
  `Stored locally · preview unavailable` statt als kaputtes `<img>` oder falschen
  Leerzustand. Der `content_type` bleibt wahr; zurückgehalten wird nichts.
  Eigene- und Nur-Kind-TIFFs sind als Regressionen abgedeckt. Details
  [`12`](12-attachments-and-images.md) §5b.
- **Generierte Plots aus gespiegelten Map-Werten (2026-08-27):** Die
  aufgeklappte Laufansicht behaelt die unveraenderten numerischen
  Array-/IV-Kurven und zeichnet einen kategorischen **Balkenplot** fuer eine
  vollstaendig endliche Zahlen-Map, aber nur als Fallback, wenn weder eine echte
  numerische Array-Kurve noch ein darstellbares Plot-Attachment existiert.
  Echte Attachments stehen vor der Array-Kurve; beide bleiben sichtbar.
  Generische Maps exakter Zweierpaare bleiben Tabelle: Ohne Schema-Metadaten
  duerfen weder Scatter-Achsen noch `Δx`/`Δy` erfunden werden. Die
  vollstaendige Map-Tabelle bleibt immer sichtbar. Leere, gemischte oder
  nicht-endliche Maps bleiben ebenfalls bewusst nur Tabelle. Worksheet-Zeilen
  und Kind-Evidenz tragen nun den sichtbaren read-only Affordance-Text
  `Runs & plots` statt eines unbeschrifteten Carets; Kind-Details laden unter
  ihrer eigenen Seriennummer lazy nach.
- **Die Bilder werden sichtbar: vier Ursachen, alle am Live-Spiegel gemessen
  (2026-08-27).** Der Bestand hielt 432 echte Bilddateien; ein Operator sah
  fast keine. (1) **Das Listen-Limit zaehlte Zeilen, nicht Komponenten.**
  `GET /api/components/thumbnails` deckelte auf 2000 Attachment-**Zeilen**, und
  2671 der 3734 Zeilen sind Instrument-`.txt`: die ersten 2000 erreichten 460
  von 759 Seriennummern und ergaben **83 Kacheln, wo 279 Komponenten ein Bild
  haben**. Browserfaehiger Bildfilter und Ein-Zeile-je-Komponente stehen jetzt im SQL
  (`GROUP BY`/`MIN(id)` statt Fensterfunktion — gleiche Semantik, keine
  SQLite-3.25-Abhaengigkeit), das Limit begrenzt seither Komponenten: **279**.
  (2) **Eine Modulseite kannte die Bilder ihrer Kinder nicht.** Nur 3 der 432
  Bilder liegen auf einem Modul, 241 auf dessen direkten Kindern (159 Sensoren
  an 156 Modulen). `GET /api/components/{sn}/attachments` liefert jetzt
  `{component_sn, attachments, children}`: die Bilder je Kind in einer eigenen
  Gruppe mit Seriennummer und Bauteiltyp, **nie** in die eigenen gemischt —
  dieselbe Form wie die Kind-Evidenz im Worksheet (Commit `e3ba33f`), mit einem
  **konstanten Query-Satz** für die ganze Familie statt N+1 (Laufmetadaten,
  Payloads sowie Association-/Legacy-Anhänge), per Test festgenagelt. Die
  Anhaenge **pro Lauf** bleiben unberuehrt, ein Lauf
  gehoert genau einer Komponente. (3) **Eine zweite CERNBox-URL-Form wurde nie
  umgeschrieben.** 20 Zeilen auf Powerboards tragen die Weboberflaechen-Route
  `/files/link/public/<token>[/<Datei>]`; sie bekamen die HTML-Seite und wurden
  korrekt abgelehnt — also nie gespeichert. Sie wird jetzt auf dieselbe
  DAV-Route abgebildet; `/s/<token>/download` bleibt bei Ordner-Freigaben
  bewusst aussen vor (es lieferte den ganzen Ordner als ZIP unter dem Code
  eines Bildes). Eine weitere Zeile zeigt auf einen **persoenlichen**
  CERNBox-Bereich: an der Form erkannt, ohne einen einzigen Request abgelehnt,
  damit sie nicht in jedem Sweep dieselbe Login-Seite abholt. Ein
  DB-Flag „permanent gescheitert" waere die naheliegende Alternative gewesen
  und ist verworfen worden — es haette genau die 20 Bilder eingefroren, die
  dieselbe Runde repariert. Alle Schutzmechanismen unveraendert (HTML-Abwehr
  doppelt, Groessenlimit, Redirect-Pruefung). Doku: `docs/12` (§1, §2.2, §2.3,
  §5.3, §8.1, §9) und `docs/13` (§2.1) — dort auch die zwei widerlegten
  Aussagen: TUDO hat sehr wohl EOS-Attachments (425 Deskriptoren, **422 der
  432 Bilder**), und „metrology images" ist eine UI-Panel-Beschriftung, kein
  Testtyp (0 Bilder an allen vier Metrologie-Testtypen, alle 432 an
  Sichtpruefungen).
  (4) **Blob-Deduplizierung war zugleich die falsche Zuordnungsidentitaet.**
  Ein global eindeutiges `(source, pdb_code)` speicherte die Bytes richtig nur
  einmal, konnte aber nur eine `component_sn`/Testlauf-Kombination halten;
  gemeinsam verwendete Share-Codes verschwanden dadurch auf allen weiteren
  Komponenten. `test_run_attachment_reference` haelt jetzt jede
  Komponenten-/Testtyp-/Lauf-Zuordnung additiv, waehrend der Blob und seine
  Datei dedupliziert bleiben. Ein einmaliger SQLite-Start-Backfill liest nur
  den lokalen Evidence-Mirror. Auf einer read-only Online-Kopie des realen
  Mirrors blieben 3 772 Blobs unveraendert und ergaben exakt 3 839 Referenzen
  (0 fehlend, unerwartet, verwaist oder doppelt); die Bildsichtbarkeit stieg
  von 298 auf 355 Komponenten. Der zweite Start blieb in 0,08 s unveraendert.
  Parallele Direkt-/Background-Syncs desselben Blobs bleiben bis zum sichtbaren
  Root-Commit serialisiert; ein deterministischer Test deckt dabei auch
  SAVEPOINT und Commit-Autoflush ab. Auch ein `force`-Lauf holt einen Blob bei
  mehreren Lauf-Deskriptoren nur einmal und teilt den Fetch, statt redundante
  Netzwerk- und Staging-Arbeit auszufuehren. Historische PostgreSQL-Daten brauchen
  weiterhin einen Re-Sync oder eine spaetere Alembic-/JSONB-Migration.
  Nachzug aus dem finalen Datenintegritaets-Audit: Thumbnail- und
  Kind-Galerie-SQL normalisieren den MIME-Basistyp jetzt genauso wie Python
  und Frontend (inklusive Leerraum vor `;`); die SQLite-Startreparatur fuer
  historisch geleerte Typen deckt neben JPEG/PNG/TIFF auch die bereits
  unterstuetzten GIF/WebP/BMP/AVIF/SVG-Suffixe ab, streng nur fuer wirklich
  heruntergeladene Zeilen mit exakter Endung. Derselbe Audit schliesst die
  zweite Identitaetsluecke: Gallery-Read-Models tragen `source`, Binary-URLs
  koennen `(source, code)` exakt aufloesen und Thumbnails liefern diesen
  Locator statt nur `code`. Neue Downloads liegen source-qualifiziert unter
  `<SN>/<source>/<code>.<ext>`, damit gleiche Codes und gleiche Endungen aus
  verschiedenen Quellen weder im Browser noch auf der Platte kollidieren;
  gespeicherte Legacy-`relative_path` bleiben kompatibel.

- **Sync-Runde 2: Index-dann-Bulk, rollierende Anzeige, optionaler Auto-Sync
  (2026-08-27).** Die vorige Runde hatte den Sweep parallelisiert, aber den
  Boden „ein Request pro Komponente" stehen lassen — bei TUDO 1170 Requests je
  Sweep, auch wenn sich nichts geaendert hat. Aus dem lokal installierten
  `itkdb` (0.6.20, im venv, **kein** PDB-Zugriff noetig) liessen sich zwei
  ungenutzte Sammel-Endpunkte belegen: `listTestRunsByComponent` (Lauf-Index
  fuer viele Seriennummern) und `getTestRunBulk` (`{"testRun": [ids]}`, viele
  Detail-Laeufe in einem Request).
  (1) **Der Evidence-Sweep ist jetzt Index → Diff → Bulk.** Wiederholungssweep
  ~1170 → ~150 Requests (≈7×), Erstsweep 15 929 → ~460 (≈34×). Weil die
  Endpunkte nicht gegen eine echte PDB validiert werden konnten, ist der
  bewaehrte Pro-Komponenten-Pfad kein toter Code, sondern **automatischer
  Fallback** pro Komponente; alles, was die Sammelantwort nicht als
  vollstaendig beweisen kann, wird einzeln nachgelesen. `ITKFLOW_SYNC_EVIDENCE_
  STRATEGY=per_component` stellt das alte Verhalten mit einer Env-Variable her.
  Der `run_state`-Vertrag (zurueckgezogene Laeufe) bleibt gewahrt: `state` ist
  Teil des Fingerprints, eine Ruecknahme kommt auf dem billigen Pfad an.
  (2) **Rollierende Anzeige („rolling shutter").** Der Sweep committet jede
  Komponente einzeln, die Oberflaeche las aber erst bei `succeeded` neu — man
  starrte minutenlang auf alte Zeilen. `componentSync.ts` liefert jetzt
  `dataEpoch`; Liste, Thumbnails **und eine geoeffnete Detailseite** (Preview,
  Pflichttest-Status) ziehen waehrend des Laufs nach. Zwei Schutzbedingungen,
  beide mutationsgetestet: nur bei echtem Fortschritt, hoechstens alle 8 s.
  Nur fuer den Evidence-Sweep — der Komponenten-Sync schreibt in einer
  einzigen Abschlusstransaktion und hat zwischendurch nichts zu zeigen.
  (3) **Unbeaufsichtigter Auto-Sync** (`app/auto_sync.py`), **per Default aus**.
  Erst durch (1) vertretbar. „Wie oft und wann" ist eine Institutsentscheidung
  (harte Regel 4) und steht deshalb im Institutsprofil unter
  `settings["auto_sync"]`, editierbar in den Admin Settings: `enabled`,
  `interval_minutes` (Untergrenze 15), optionales Fenster
  `window_start`/`window_end` und `weekdays`. Fenster ueber Mitternacht sind
  ausdruecklich unterstuetzt (`22:00`–`06:00` = nachts) und gelten dem
  Wochentag, an dem sie geoeffnet haben — sonst schaltete „nur werktags" jede
  halbe Freitagnacht mit ab. Fenster/Wochentag werden gegen **lokale**
  Serverzeit geprueft, das Intervall gegen **UTC** (gespeicherte Zeitstempel).
  Das Profil traegt bewusst keine benannte Zeitzone: Desktop nutzt die
  Betriebssystemzeit, Compose installiert `tzdata` und bezieht `TZ` aus
  `deploy/.env` (sichtbarer Default `Etc/UTC`). Ein fehlerhafter Profilblock
  wird als *aus* gelesen, nie geraten.
  Deployment-seitig bleibt nur `ITKFLOW_AUTO_SYNC_POLL_MINUTES` (Default 5,
  `0` = Scheduler aus) — wie oft ausgewertet wird, kein PDB-Verkehr.
  Er hat keine eigenen Credentials: je Institut laeuft er als die
  Person, deren eigener Komponenten-Sync dort zuletzt erfolgreich war. Die
  Person muss dort weiterhin aktiver Operator/Admin sein; deaktivierte oder
  herabgestufte Konten, fremder Institute-Scope, geloeschte Codes sowie
  unbekannter, kaputter oder `invalid` Status werden fail-closed uebersprungen
  (`unreachable` bleibt bewusst nutzbar). Jobs tragen
  `scheduled refresh (<email>)`, damit nichts so aussieht, als haette jemand
  geklickt. Da die Komponenten-Lease global ist, sortiert
  `institutes_by_staleness()` nach laengster Wartezeit — sonst verhungert bei
  mehreren Instituten dauerhaft eines. Details docs/09, UI-Teil docs/05.

- **Auto-Sync: Profil-Validierung und Admin-UI (2026-08-27).** Der Zeitplan
  ist jetzt Institutsdaten statt Env-Variable: `auto_sync` in
  `InstituteProfile.settings`, validiert in `app/institute_settings.py` und
  bedient im Admin-Settings-Abschnitt `Scheduled sync`. Der Reader in
  `app/auto_sync.py` faellt bewusst still auf „aus" zurueck; damit ist der
  Validator die einzige Stelle, die einer Person ueberhaupt sagt, dass ihre
  Eingabe falsch war — jede Ablehnung nennt deshalb den akzeptierten Wert.
  Abgelehnt statt repariert werden: Intervall < 15 min, halbe
  Zeitfenster, identische Fenstergrenzen, Wochentage ausserhalb 1–7, doppelte
  oder leere Wochentagslisten, unbekannte Keys (`timezone`!). Ausdruecklich
  **nicht** geprueft wird `start <= end`: `22:00`–`06:00` ist ein
  Nachtfenster, und die UI benennt es auch so. Ein Institut ohne Zeitplan
  bekommt durch ein unabhaengiges Speichern keinen Block — Abwesenheit ist,
  wie „kein unbeaufsichtigter Verkehr" gespeichert wird. UI-Teil docs/05 §7.
  Das Intervall wird gegen die neuere Grenze aus letztem erfolgreichen Sync
  und letztem Scheduled-Versuch (einschliesslich dessen Auto-Retry) gemessen;
  ein Fehlschlag erzeugt daher nicht bei jedem Poll einen neuen Job. Ein
  manueller Fehlschlag verschiebt die Zeitplangrenze bewusst nicht.

- **Befund festgehalten: die Metrologie hat kein Bild, und ihre Dateinamen sind
  wertlos (2026-08-27, neues Dokument
  [`13-metrology-artifacts.md`](13-metrology-artifacts.md)).** Am kanonischen
  TUDO-Spiegel gezählt: **104 `MODULE_METROLOGY`-Läufe, 104 Anhänge, 0 Bilder**
  — jeder Anhang eine `text/plain`-Rohdatei. **24 verschiedene Dateinamen auf
  104 Läufe, davon 80× `result.txt`**; ein Modul (`20USEM20000056`) trägt fünf
  Läufe in fünf Schreibweisen bis hin zu
  `R2_module_result_tryAgain_20USEM20000056_OutputFile.txt`; **fünf Module
  haben zwei Läufe mit identischem Dateinamen** — wer auf
  `(Seriennummer, Dateiname)` schlüsselt, verliert je eine Messung lautlos.
  `title` ist bei allen 104 `resultsFile`, `content_type` bei allen 104
  `text/plain`: zwei Felder, die nichts unterscheiden können. Dazu **zwei
  Handle-Formen** (32 Hex = PDB-Code, 64 Hex = von itkFlow für
  CERNBox-Share-Links erzeugt) und **drei Schreibweisen derselben Maschine**
  (`Keyence VR-3200` 98×, `Keyence` 5×, plus ein DESY-`Flash CNC 300
  Smartscope`/`DESYv0`-Lauf im TUDO-Bestand). Daraus die verbindliche Regel:
  **eindeutig ist nur `(test_run_ref, pdb_code)`**, und die Metrologie-Kachel
  darf kein Bild versprechen. Offen bleibt, wo die Bilddateien der Keyence
  überhaupt landen — die PDB sieht sie nie. Doku-Verkabelung im selben Change:
  Doc-Map-Zeilen für [`12`](12-attachments-and-images.md) und
  [`13`](13-metrology-artifacts.md), Querverweise in 12 und `docs/README.md`.
  Reine Dokumentation, kein Code geändert.
- **Das Klebegewichts-Urteil existiert (2026-08-27, Etappe E2 aus
  [`superpowers/specs/2026-08-27-modulseite-als-arbeitsblatt.md`](superpowers/specs/2026-08-27-modulseite-als-arbeitsblatt.md)
  §9).** `glue_targets`, `glue_weight_inputs`, der ausdrückliche
  `glue_default_process` und `glue_process_property` sind validierte
  Institutsprofildaten. Fehlende, `null`- oder fehlerhafte Profile aktivieren
  **keine globalen TUDO-Seeds**; auch ein einziger Regelsatz wird nie als
  Prozessdefault geraten. Der sessiongebundene Adapter
  `backend/app/glue_service.py` speist `WorksheetRow.derived` und den
  Ingest-Dry-Run. **Der Server rechnet, die Anzeige färbt** — Gramm aus der PDB
  werden an genau einer Grenze in Milligramm umgerechnet; `unknown` trägt immer
  `no_run`, `missing_inputs` oder `no_target`.
  **Historische Auswahl:** größtes `valid_from` ≤ echter Messzeitpunkt,
  `valid_from: null` als einziger Rückfall für undatierte Läufe. Der Ingest
  reicht den Upload-Messzeitpunkt durch und verwendet für Institutswahl,
  Pflichtfelder und Ableitung dasselbe endgültige Profil; widersprüchliche
  Payload-/Operator-Auswahl scheitert geschlossen. Profildefinierte eigene
  Glue-Testtypen erscheinen bereits ohne Lauf als Additional-/`no_run`-Zeile.
  **Sheet-/zFlow-Abgleich:** der echte Spiegel führt
  `R5M1_HALFMODULE`/`R5M0_HALFMODULE`/`R2`, nicht die Blattkurzformen; die
  belegte TUDO-Basis ist die H1-Kette. Optionale, exakte `by_type_code`-Formeln
  bilden zFlows H1/H1H2-Topologieauswahl ab, ohne aus gefüllten Ergebnisfeldern
  zu raten. `GW_METHOD` bleibt korrekt die Auftragsart, nicht der Kleber. Der
  Zahlendreher des Blattes (R2-Gesamttoleranz 22 statt 25+11=36) wird nicht
  übernommen. Admins können Prozessdefault und Run-Property einstellen;
  verschachtelte Typformeln überstehen jeden Formular-Roundtrip verlustfrei.
  Fokussiert verifiziert: 88 Backend-Glue-Tests und 28 Admin-UI-Tests, Ruff und
  TypeScript sauber. Gegen den Echtbestand reproduziert die Rechnung die
  gespeicherten Werte auf 1 mg genau in 25 von 31 vollständigen Hybrid- und 13
  von 18 Powerboard-Sätzen; die übrigen 11 Läufe widersprechen ihren eigenen
  Waagenwerten. **E3-Uploadnaht geschlossen:** `pdb_submit`/`pdb_upload`
  entfernen die erneut verifizierten `derived_result_codes` aus den
  Rohwerten und mischen nur serverseitig erneut verifizierte
  `derived_results` autoritativ in das hochgeladene Dokument. Offen bleiben
  die Vorformeln fuer
  Hybridgewichte ohne Tabs und die fachliche `passed`-Bindung.
- **Zwei Falschaussagen der Modulseite behoben (2026-08-27, Etappe E1 aus
  [`superpowers/specs/2026-08-27-modulseite-als-arbeitsblatt.md`](superpowers/specs/2026-08-27-modulseite-als-arbeitsblatt.md)
  §1; beide gegen den echten TUDO-Spiegel gemessen).**
  (1) **Zurueckgezogene Messungen zaehlten als gueltig.** Die PDB liefert einen
  geloeschten Testlauf (`state='deleted'`) weiter aus, unser Spiegel hatte
  keine Statusspalte — **102 von 14 759 Laeufen**, 13 % aller `GLUE_WEIGHT`
  und 25 % aller `MODULE_BOW`, auf 45 Komponenten; der vom Owner bemerkte
  „1,859er-Block" ist zu 14 von 15 genau das. Neu: `TestRunEvidence.run_state`
  plus die einzige Auslegung in `app.test_run_evidence`
  (`WITHDRAWN_RUN_STATE`/`is_withdrawn`/`live_runs_only`) — nur der terminale
  Zustand `deleted` zieht zurueck, `NULL` und das PDB-eigene
  `requestedToDelete` zaehlen weiter, damit der Fix nie Nachweise loescht,
  ueber die er nichts weiss. Ausgeschlossen wird ueberall dort, wo ein Lauf
  als Nachweis gelesen wird: `stage_service.satisfied_test_results` (und damit
  jedes Stage-Gate), Worksheet-Zeile samt `latest`, Messwert-Statistik. Sind
  alle Laeufe eines Testtyps zurueckgezogen, liest die Pflichtpruefung wieder
  `missing`. Verschwinden duerfen sie nicht: `GET /api/components/{sn}/tests`
  listet sie weiter und liefert `run_state`, die Zeile meldet
  `withdrawn_count`. Bestandsdaten werden ohne Re-Sync korrigiert — der
  Retrofit in `ensure_phase0_sqlite_schema` befuellt die Spalte per
  `json_extract` aus den bereits gespiegelten Payloads (630-MB-Spiegel: 27 s
  einmalig, danach 0,1 s je Start).
  (2) **Die Modulseite sah 4,9 % ihrer eigenen Geschichte.** Von 14 759 Laeufen
  haengen nur 720 an MODULE-Komponenten; der Rest liegt auf Sensoren,
  Hybriden, Powerboards und — bei R5-Ringmodulen — auf den beiden
  Halbmodulen. Die Worksheet-Payload traegt jetzt `worksheet.children`: eine
  Gruppe je direktem Kind (Seriennummer + Typ + lokaler Name), streng getrennt
  von den eigenen Zeilen und mit demselben Kompaktheitsvertrag (Skalare
  inline, Arrays/Maps nur als Umfang). Abdeckung der Modulseiten damit
  **4,7 % → 73,1 %** der lebenden Laeufe (687 eigene + 10 033 Kind-Laeufe);
  39 der 265 Module hatten vorher gar keine eigene Evidenz. Kosten fest, nicht
  pro Kind: eine Metadaten-Abfrage ohne Payload-Spalte, eine fuer die Payloads
  der ausgewaehlten juengsten Laeufe, eine fuer die Attachment-Zaehler — noetig,
  weil die Kind-Laeufe eines einzigen Moduls im Spiegel bis zu **31 MB** JSON
  sind. Real gemessen: 57 ms je Modulseite, schwerstes Modul 0,36 s bei 47 kB
  Antwort. **Bewusst nicht geaendert:** was ein Stage-Gate oeffnet. Ob der
  bestandene Test eines Kindes die Anforderung des Elternteils erfuellt (zFlow
  aggregiert ueber Halbmodule), ist eine offene Owner-Entscheidung; die
  Evidenz wird gezeigt, nicht stillschweigend verrechnet. Die aufgeklappte
  Lauf-Ansicht kennzeichnet den terminalen PDB-Zustand `deleted` jetzt als
  `withdrawn in PDB`; `requestedToDelete` bleibt bis zum Abschluss ein
  lebender Lauf und zeigt weiterhin sein Ergebnis.
  Verifiziert: 838 Backend-Tests (PYTEST_EXIT=0), ruff clean, Frontend-`tsc`
  sauber, 121 Vitest-Tests gruen. Details docs/09 und docs/05.
- Monorepo steht mit `backend/`, `frontend/`, `agent/`, `deploy/`, CI- und
  Docker-Grundstruktur.
- **Doku ist navigierbar (2026-08-26, reine Doku-Aenderung):** Neue
  Einstiegsseite [`docs/README.md`](README.md) mit Lesepfaden („neu im
  Projekt", UI, PDB-Integration, Produktionsablauf, aktueller Stand, Betrieb),
  einem Index von ADRs/Specs/Recherche samt Aktualitaetsvermerk und dem
  Doku-Disziplin-Abschnitt. Jedes numerierte Dokument traegt jetzt einen
  Kopfblock (besitzt / fuer wen / verwandt), und Querverweise zwischen
  Dokumenten sind relative Links statt Klartextpfade. Ownership bleibt
  ausschliesslich in [`00-doc-map.md`](00-doc-map.md); Inhalte wurden nicht
  umgeschrieben.
- **Modul-Worksheet: Payload-Diaet + Bearbeitungssicherheit (2026-08-26):**
  Review-Nachzug zum Worksheet-Schnitt (Spec §H), vier Befunde behoben. (1)
  Die Preview traegt keine gespiegelten Laeufe mehr: `projected.tests[]`
  heisst jetzt `projected.ghost_tests[]` und enthaelt ausschliesslich noch
  nicht gepushte Staged-Uploads; rohe Messwerte liefert ausschliesslich
  `GET /api/components/{sn}/tests`, das die Detailseite erst beim ersten
  Oeffnen von „All mirrored runs" laedt. Gemessen mit demselben Serializer
  gegen den echten TUDO-Spiegel: 20USEM50000064 (29 Laeufe) 227 589 → 3 039
  Byte (−98,7 %); 20USEM50000063 129 916 → 3 916 Byte; 20USE5L0000031
  63 307 → 5 444 Byte. (2) Offene Outbox-Actions fuer eine Komponente werden
  jetzt in SQL vorgefiltert (portables `CAST(payload AS VARCHAR) LIKE
  '%sn%'`, auf SQLite und PostgreSQL geprueft) statt bei jedem
  Modulseiten-Oeffnen alle nicht-terminalen Actions instituts-weit in Python
  zu laden — das bestehende Python-Praedikat bleibt die einzige Autoritaet.
  (3) Dict-wertige Messergebnisse (echte Metrologie-Maps) zaehlen jetzt wie
  Arrays mit Diskriminator `kind: "array"|"map"` statt als Zeile zu landen;
  befuellte Skalare sortieren stabil zuerst; steht eine Komponente auf einer
  modellfremden Stage (reale TUDO-Module auf `FAILED`), gilt jede Gruppe als
  erreicht statt das ganze Sheet abzudunkeln; die „Additional"-Gruppe listet
  jetzt auch nur-staged und bestaetigt-aber-noch-nicht-gespiegelte Testtypen,
  die vorher unsichtbar waren. (4) Der Edit-Strip prefillt nur noch Werte,
  die nachweislich durchs Schema-Formular hin- und zurueckgehen: Maps, vom
  Schema nicht als Array deklarierte Arrays und Arrays mit `null` werden nie
  vorbelegt oder abgeflacht; ein nicht wegklickbarer Hinweis nennt die
  betroffenen Felder. Ist ein solches Feld REQUIRED, blockt der Strip
  komplett und verweist auf den Datei-Drop-Pfad — Datenverlust bleibt lieber
  sichtbar blockiert als still. Zusaetzlich: ein blockierter Dry-Run ohne
  Issues wird jetzt angezeigt statt stillschweigend zu verschwinden, ein
  fehlgeschlagener Fetch des vorherigen Laufs blockt den Strip statt ein
  leeres Formular zu zeigen, und der Zeilenzustand ist nach Stage+Testtyp
  geschluesselt, damit ein an zwei Stages pflichtiger Testtyp sein
  Auf-/Zuklapp- und Edit-Verhalten nicht mehr teilt. Nebenbefund: die
  aufgeklappte Lauf-Ansicht rendierte Dict-Ergebnisse (Metrologie, fuenf
  Map-Felder; Wire Bonding, acht) als woertlichen Text `[object Object]` —
  Maps rendern jetzt als Position/Wert-Paare. Das Staged-Fenster zeigt pro
  offenem Test-Upload jetzt Komponente, Testtyp und die vorgeschlagenen
  Messwerte im selben kompakten Worksheet-Format (Arrays/Maps als
  Umfangs-Chip); die Werte kommen aus den Preview-Ghost-Eintraegen, kein
  neuer Endpunkt. Terminale (History-)Uploads haben keinen Ghost und damit
  keine Werte — der Screen sagt das explizit, ebenso bei einer noch nicht
  gespiegelten Komponente; ein Betrachter ohne Schreibrecht sieht jetzt den
  Grund statt gar keiner Steuerung. Admin Settings hat einen neuen Abschnitt
  „Production stages" (GUI-Editor fuer `stage_order`/`stage_requirements` je
  Institut, tastaturbedienbar, Testtyp-Vorschlaege aus gespiegelten Schemata
  plus in gespiegelter Evidence vorkommenden Testtypen, unbekannter Wert
  markiert „Not mirrored"). Seed-Stages lassen sich umsortieren, aber nicht
  entfernen (der Merge in `stage_model_from_settings` haengt sie immer
  wieder an — neutralisieren geht nur ueber leere Pflicht-Tests); der Screen
  dupliziert deshalb noch die Seed-Stage-Konstanten, weil kein Endpunkt das
  effektive Stage-Modell liefert — ein Read-Endpunkt dafuer ist die
  empfohlene naechste Ausbaustufe. Eine echte End-to-End-Integrationssuite
  rendert jetzt den echten Komponentenbaum (Worksheet + Formular +
  Run-Renderer + Staging) mit ausschliesslich gemocktem Netzwerk und fing
  genau die Schema-Form-Kopplung und den `[object Object]`-Defekt.
  Verifiziert: 813 Backend-Tests, ruff clean; Frontend-`tsc` sauber, 117
  Vitest-Tests gruen (Timeout-Deckel auf 20 s statt 5 s angehoben, weil
  jsdom/userEvent-Interaktionstests auf belasteten Maschinen ueber 5 s
  brauchten und faelschlich rot wurden).
- **Postgres-Sortierkorrektheit bei Testlauf-Auswahl (2026-08-26):**
  `stage_service.satisfied_test_results` pinnt `measured_at NULLS FIRST`
  jetzt explizit. SQLite sortiert NULLs von sich aus zuerst, PostgreSQL
  zuletzt — im Deployment laeuft PostgreSQL, also konnten der SQL-„juengster
  Lauf" und die Python-Auswahl in `preview.py` bislang auseinanderlaufen und
  einen passed/failed-Status liefern, der dem angezeigten Lauf widersprach
  und in die Stage-Move-Pruefung einfloss. Ein reiner Datenkorrektheits-Fix,
  keine Kosmetik — die Testsuite laeuft auf SQLite und kann eine Regression
  hier nicht auffangen; ein Postgres-Job in CI ist der offene Nachzug.
- **Sync: schneller und ausfallrobust (2026-08-26):** Der Sweep wurde mit
  fortschreitender Laufzeit unbrauchbar langsam und wirkte bei Verbindungs-
  abbruechen eingefroren. Vier Ursachen, alle behoben. (1) Jeder PDB-Zugriff
  lief strikt seriell (~1,3 s/Request; real 29 min fuer 262 Module) — die
  Evidence-Fetches laufen jetzt begrenzt parallel
  (`ITKFLOW_SYNC_FETCH_CONCURRENCY`, Default 4, `1` = altes Verhalten), mit
  **eigenem itkdb-Client je Worker-Thread** (itkdb-Clients sind
  `requests.Session`-Subklassen und nicht threadsicher); Ergebnisse werden in
  Submit-Reihenfolge konsumiert, alle DB-Writes bleiben auf dem Job-Thread,
  die Commit-Granularitaet pro Komponente bleibt erhalten. (2) Der „Freeze":
  bei einem Ausfall durchlief in der Attachment-Phase **jede** verbleibende
  Datei die volle Retry-Leiter (~3 min/Datei) — ein neuer Circuit-Breaker
  (`ATTACHMENT_OUTAGE_BREAKER_THRESHOLD = 5` aufeinanderfolgende *transiente*
  Fehlschlaege) laesst den Job stattdessen ehrlich transient scheitern, sodass
  der vorhandene Ein-Schuss-Auto-Retry greift; permanente Einzelfehler (404,
  HTML-Seite, zu gross) bleiben wie bisher Best-Effort pro Datei. (3) Ein
  einziger Worker-Thread bediente Komponenten- **und** Evidence-Jobs: ein
  langer Sweep blockierte jeden Komponenten-Sync, dessen wartende Zeile dann
  nach 3 min faelschlich als verwaist geschlossen wurde — jetzt ein Worker je
  Job-Art plus Heartbeat-Keeper fuer wartende `queued`-Jobs. (4) Die doppelte,
  speicherfressende Attachment-Planung (gesamte Evidence-Tabelle inkl.
  ~10-KB-Payloads in einer Identity-Map) ist durch **eine** Planung in
  kurzlebigen Sessions ersetzt. Attachment-Downloads bleiben bewusst seriell
  (Begruendung in docs/09). (5) Der Component-Sync und der Evidence-Snapshot
  konnten sich ueberholen: eine bereits laufende Evidence-Phase hielt ihren
  alten Komponenten-Scope, waehrend der erfolgreiche Component-Callback nur
  auf diese Lease konvergierte. Der Component-Commit speichert jetzt atomar
  einen privaten, restart-sicheren Follow-up-Wunsch; Startup und Future-Ende
  gleichen `finished_at`/`started_at` ab, frische Fremd-Leases werden nie
  uebernommen und erst ein neuerer erfolgreicher Snapshot loescht den Wunsch.
  Der private Marker wird aus allen Public-Schemas gefiltert. Zwei Restfehler
  des Parallel-Schnitts sind ebenfalls geschlossen: ein lokal wiederverwendeter
  Anhang ist fuer den Outage-Breaker neutral (nur ein echter Download beweist
  Erholung), und der innere Fetch-Pool joint laufende Reads mit Heartbeats vor
  terminalem Jobstatus/Retry. Der Follow-up-Retry-Zustand ist jetzt ebenfalls
  dauerhaft (Crash vor dem Timer verliert ihn nicht), und ein abgelehnter
  Executor-Submit gibt Queue-Watch und Lease wieder frei. Fokussiert
  verifiziert: 56 Sync- und 76 Attachment-Tests.
  Details docs/09.
- **Modul-Worksheet als Primaeransicht der Detailseite (2026-08-26):** Die
  Detailansicht rendert nicht mehr jeden Lauf voll (Kurven + komplettes
  Wertegitter) — bei >100 Laeufen eine unlesbare, ueberlappende Zahlenwand.
  Neu ist das Spreadsheet-Modell aus Spec §H: pro Stage-Gruppe eine kompakte
  Tabelle (Zeile = Testtyp), Werte inline (3 Skalare + `+n`, Arrays/Maps nur
  als Umfangs-Chip — Rohdaten verlassen den Server nie), Zeilen aufklappbar
  zum vollen Detail, Inline-Edit-Strip statt Sprung zur Formularkarte
  (staged ueber den unveraenderten Ingest→Dry-Run→Propose-Outbox-Pfad), offene
  Staged-Actions als Ghost-Zeilen. Die bisherige Vollansicht lebt eingeklappt
  als `All mirrored runs` weiter. Backend liefert den `worksheet`-Block in
  `build_component_preview`; dabei gefunden und gefixt: der Latest-Run-Vergleich
  konnte bei gemischt naiven/tz-bewussten Timestamps die gesamte Preview mit
  einem 500er abbrechen. Details docs/05.
- **0.2.1-Reviews (2026-08-26, zwei Opus-Reviewer):** Beide Review-Blocker
  sind gefixt: (C1) die zwei synchronen Evidence-Endpunkte committen jetzt vor
  der Download-Phase (pro Komponente beim Institutssweep) statt die
  Schreibsperre uebers Netz zu halten; (I1) Slot-Payloads sind am Wire
  begrenzt (max 16 Slots, 4 Tools/Slot) und eine Kardinalitaetsverletzung
  bricht ab, statt jede Id einzeln aufzuloesen; (I2) JEDER Slot prueft
  Typ-Kompatibilitaet (Zusatz-Slots gegen Parent ODER Child); (I3) die
  Tool-Dedup-Migration behaelt die von tool_sync gepflegte hoechste id und
  loggt die geloeschte Zeilenzahl; dazu Pragma-Reihenfolge (busy_timeout vor
  WAL-Konversion), lazy Dummy-Hash, Dummy-Pfad auch fuer passwortlose
  Accounts, eindeutige property_keys je Slot-Layout, und ein 500er bei
  ungueltiger Tool-Id im Slot wurde zum regulaeren Preview-Issue.
  **Offen fuer die naechste Runde:** .part-Dedupe unter force bei geteilten
  Attachment-Codes; Auth auf `GET /api/institutes` (liefert
  Settings-Projektion inkl. SMTP-Host/Usernamen anonym — der Wizard braucht
  dann einen scoped Slot-Endpunkt); Kartenlimit 4 als geteilte Konstante bis
  ins Frontend; .part-Aufraeumen fuer aus der PDB verschwundene Attachments;
  `:memory:`-URI-Varianten in make_engine; dl/div-Markup im Wizard-Review.
- **0.2.1-Runde (2026-08-26, sechs parallele Implementierungs-Agenten):**
  (1) SQLite-Kontention behoben: WAL + busy_timeout 30 s an der Engine,
  Attachment-Downloads laufen nicht mehr innerhalb offener
  Schreibtransaktionen (Bytes → .part-Datei → kurzer Commit), Busy-Fehler in
  Outbox-Drain/Reminder-Tick sind ruhige Skips statt Fehler; dazu die
  nachgeholte `uq_tool_institute_code`-Migration. Details docs/09.
  (2) Edit-Ghost an jeder `missing`/`failed`-Zeile der Pflicht-Tests-Tabelle
  oeffnet die Testerfassung mit vorbelegtem Typ (docs/05).
  (3) Kombinierte Tool-Slots fuer den Assembly-Wizard: Slots aus dem
  Institutsprofil (`assembly_tool_slots`), Kombis als Komma-Liste in die
  PDB-Property, Wizard mit Chips + Scan-Zuordnung, HTTP/Preview verdrahtet
  (docs/07).
- **Security-Härtung Login/Reads (2026-08-26):** Audit- und Outbox-Reads
  verlangen jetzt Login, der Login-Pfad ist timing-neutral gegen
  Konten-Enumeration, und ein Passwortwechsel invalidiert bestehende Sessions.
  Details docs/06. (Teil der laufenden 0.2.1-Runde: 6 Implementierungs-Agenten,
  Doku wird je Abschluss konsolidiert.)
- **Evidence-Umfang erweitert (2026-08-26):** Der Sweep deckt jetzt alle
  Baugruppentypen mit echten Testlaeufen ab (Module, Sensoren, Hybride,
  Flexes, Powerboard-Flex, HV-Tab-Sheets — per PDB-Stichprobe bestimmt) und
  beruecksichtigt auch Komponenten, die **hier stehen, aber anderen
  Instituten gehoeren** (bei TUDO die Mehrheit). Chips (ABC/HCC/AMAC) bleiben
  optional. Details docs/09.
- **Messwert-Statistik auf der Statistics-Seite (2026-08-26):** Neue Endpunkte
  `GET /api/stats/measurements/dimensions` und `GET /api/stats/measurements`
  (`app/measurement_stats.py`) aggregieren die gespiegelten Testlauf-Messwerte
  eines Instituts: Array-Ergebnisse als ueberlagerte Kurven (alle IV-Kurven in
  einem Chart, gepaart gegen ein waehlbares X-Result), skalare Ergebnisse als
  Verteilung mit Kennzahlen. Testtypen und Result-Codes werden aus den Daten
  entdeckt, nie hartkodiert. UI: `Measurements`-Block im StatisticsScreen mit
  Inline-SVG (Pass/Fail zusaetzlich ueber Strichelung kodiert, Palette gegen
  Hell/Dunkel validiert). Details docs/05 §5b.
- **Staged-Preview-Preference wirkt sofort (2026-08-26, Bugfix):** Die
  Account-Einstellung `Staged preview: Tabs|Inline|Off` wurde nur beim Mount
  gelesen — der Staged-Tab schien nach dem Umschalten „verschwunden", bis man
  neu lud. `stagedPreview.ts` benachrichtigt jetzt Abonnenten im selben Tab
  (`storage`-Events feuern nur in anderen Tabs).
- **Desktop kann Outbox-Aktionen wirklich pushen (2026-08-26):** Das Bundle
  laeuft als ein Prozess und startete keinen Outbox-Worker — eine in der UI
  gepushte Aktion erreichte `submitted` und blieb dort fuer immer liegen, sah
  aber gepusht aus. Neu: `ITKFLOW_OUTBOX_PROCESSOR` (`worker` Default, Desktop
  `app`) und `app/outbox_processor.py` draenen die Outbox im API-Prozess.
  Sicherheitsmodell unveraendert: keine deployment-weiten Credentials,
  Approval-Identitaet, `dummy_only`. Details docs/11.
- **Sync-Datenverlust behoben (2026-08-26, gegen echte TUDO-Daten verifiziert):**
  Zwei unabhaengige Fehler liessen die App unvollstaendig aussehen.
  (1) `useOrInLocationSearch` blaettert inkonsistent: 3799 gemeldete
  Komponenten, 3799 Zeilen, aber nur 2539 verschiedene — ~1260 fehlten, darunter
  **alle 92 Jigs/Tools**, weshalb die Tool-Registry leer blieb. Der Fetch stellt
  jetzt zwei getrennte Abfragen (owned / located) und fuehrt sie lokal zusammen:
  3044 Komponenten, 0 Dubletten, 92 Tools. Zusaetzlich bricht eine
  Dublettenpruefung einen lueckenhaften Sync ab, statt ihn zu verschweigen.
  (2) Der Evidence-Sweep committete erst ganz am Ende; ein geschlossenes
  App-Fenster verwarf die komplette Arbeit (real: 29/262 Komponenten, danach
  `test_run_evidence` = 0 Zeilen → alle Pflichttests „missing"). Jetzt
  committet jede Komponente einzeln. Details docs/09.
- **Sync ueberlebt kurze Internet-Ausfaelle (2026-08-26):** Drei Luecken
  machten aus einer Funkloch-Minute dauerhaften Verlust. (1)
  Attachment-Downloads hatten gar keinen Retry — ein realer Sweep endete mit
  `attachments_failed=11` von 363. Transiente Fehler (DNS, Connection Reset,
  TLS-Handshake-Timeout, 408/425/429, 5xx) werden jetzt mit exponentiellem
  Backoff bis `ITKFLOW_SYNC_PAGE_MAX_ATTEMPTS` wiederholt, permanente (4xx,
  HTML-Fehlerseite, zu grosser Body) scheitern sofort; ein Fehlschlag wird nie
  als gespeichert vermerkt und deshalb im naechsten Sweep automatisch
  nachgeholt. (2) Ein transient gescheiterter Sync-Job blieb bis zum
  Menschen-Klick liegen — er plant jetzt **genau einen** automatischen
  Wiederholungslauf nach 60 s; die Obergrenze steckt im dauerhaften
  `requested_by`-Marker „automatic retry (…)", sodass die Kette auch ueber
  Neustarts hinweg bei Original + ein Retry endet. Der Retry laeuft durch die
  normale Lease-Akquise und konvergiert auf einen bereits vorhandenen Job;
  nicht-transiente Fehler (Credentials, Bugs) bekommen keinen. (3) Eine
  Zombie-Lease nach Crash-plus-Sofortneustart blockierte den Single-Flight
  dauerhaft, weil Startup-Recovery ihren frischen Heartbeat sah; die
  Lease-Akquise uebernimmt sie jetzt nach derselben Drei-Minuten-Regel.
  Zusaetzlich schreiben Evidence-Retry und Download-Phase Heartbeats, damit
  eine lange Retry-Leiter nicht als verwaist gilt. Nebenbefund und mitgefixt:
  oeffentliche CERNBox-/Sync&Share-Attachments (Visual Inspection) wurden nie
  gespiegelt, weil der Mirror die HTML-Betrachterseite statt der Datei anfragte
  — jetzt ueber `remote.php/dav/public-files/<token>` bzw. `/s/<token>/download`.
  Details docs/09.
- **Sync: inkrementeller Evidence-Sweep + konfigurierbares Retry-Budget
  (2026-08-26):** Der Institutssweep vergleicht pro Testlauf einen
  Flat-Fingerprint gegen den Mirror und holt `getTestRun`-Detail nur noch fuer
  neue/veraenderte Laeufe (Marker `detail_synced`; Wiederholungs-Sync ~1
  Request pro Komponente statt pro Lauf; Einzelkomponenten-Sync bleibt voller
  Fetch). Seiten-Retries beim Komponenten-Sync sind konfigurierbar
  (`ITKFLOW_SYNC_PAGE_MAX_ATTEMPTS`, Default 3). Details docs/09.
- **PDB: Offline-Default statt toter Testinstanz (2026-08-26):**
  `pdb_instance` kennt nur noch `offline` (Code-Default, erreicht nichts) und
  `production`; `pdb_test_api_url` und die unicorncollege-URLs sind gestrichen.
  Desktop-Bundle und Compose aktivieren Produktions-**Reads** ab Werk
  (Owner-Entscheidung; Env gewinnt weiterhin, Writes bleiben `dummy_only`,
  Traffic erst mit persoenlichen Codes). Der Account-Screen zeigt fuer eine
  Offline-Instanz die ehrliche Server-Meldung statt „check your network".
  Harte Regel 2 in CLAUDE.md neu gefasst; Details docs/09 + ADR-003-Ergänzung.
- **Logistik & Betrieb (Phase-4-Kickoff, 2026-08-26):** Die drei
  Phase-4-Kernmodule sind implementiert (Vertrag/Details:
  `docs/11-logistics-operations.md`): **Glue-Batch-Registry** (lokale Batches
  mit Lebenszyklus new→in_use→expired/empty, Topfzeit-Timer ab `mixed_at` mit
  Profil-Default `glue_pot_life_minutes[glue_type]`, Verbrauchslog je
  Komponente, Scan nach PDB-SN/Batch-Nr.; keine PDB-Registrierung von GLUE —
  nur Referenz); **Shipment-Mirror + Empfangspruefung** (read-only Sync ueber
  `listShipmentsByInstitution` in beide Richtungen + `listShipmentItems`,
  Dedupe per Id, 503 statt Null-Erfolg; lokal fuehrende `reception_*`-Felder
  mit Checklisten-Template aus `shipment_reception_checklist`, die kein
  Re-Sync ueberschreibt); **Reminder + Notification-Adapter**
  (`once|daily|weekly|monthly` mit Catch-up, Feuern im Worker-Poll-Loop;
  Kanaele als `notification_channels` im Institutsprofil — Mattermost-/
  generischer Webhook via stdlib-urllib, Webhook-URLs werden in allen
  API-Antworten als `***` maskiert und tauchen nie in Fehlern/Logs auf;
  kanallose Reminder feuern nur ins Audit). Drei neue Screens (Glue Batches,
  Shipments, Reminders) ersetzen die P4-Platzhalter in der Rail. Als dritter
  Kanaltyp kam **Telegram** dazu (eigener `kind`, weil Telegram `chat_id` im
  Body braucht und die generische Webhook-Form ignoriert; Bot-Token steckt in
  der URL und faellt damit unter dieselbe Maskierung) — der Alt-Kanal des
  zFlow ist damit abgedeckt. Der Assembly-Wizard-Quick-Select ist inzwischen
  umgesetzt; offen bleiben E-Mail/SMTP-Adapter und Eskalation
  (docs/11 „Remaining Phase 4 scope").
- **Shipment -> Reception Tests (Phase 4, 2026-08-26):** Das je Institut
  gepflegte `shipment_reception_tests`-Mapping ordnet Komponententypen ihre
  erforderlichen Testtypen zu. Shipment-Responses projizieren je Item und
  aggregiert `missing|pending|passed|failed` aus lokalem `TestRunEvidence` und
  `upload_test_run`-Actions; pending gilt ausdruecklich nicht als bestanden.
  Fehlende/fehlgeschlagene Nachweise verlinken in die auf SN und exakten
  Testtyp gepinnte Testerfassung. `done` wird serverseitig bis zum Pass aller
  konfigurierten Nachweise blockiert. Nur Admins koennen mit explizitem Grund
  uebersteuern; dafuer entsteht ein eigenes Audit-Event. Die UI weist getrennt
  aus, ob ein DUMMY spaeter gepusht werden darf oder ein Produktionsbauteil nur
  staged bleibt. Mapping, Projektion, Re-Sync-Erhalt, Rollen/Scope, Gate,
  Deep-Link und strukturierte Settings sind offline getestet; kein Testpfad
  ruft die Live-PDB auf.
- **Reminder feuern in jeder Deployment-Form (2026-08-26, Nachzug):** Der erste
  Wurf haengte das Ticken allein am Outbox-Worker — den es weder im
  Desktop-Bundle (ein einziger Prozess) noch beim Dev-Launcher gibt. Ein
  geplanter Reminder waere dort **nie** gefeuert. `ITKFLOW_REMINDER_SCHEDULER`
  (`worker` = Default/Compose, `app`, `off`) waehlt jetzt den tickenden
  Prozess; `create_app` startet dafuer einen `ReminderScheduler` als
  Hintergrund-Task (Tick im Worker-Thread, da DB und Webhook blockieren),
  Desktop-Bundle und `start-itkflow.ps1` setzen `app`. Zustellung ist dabei
  **at most once**: eine Faelligkeit wird per guarded UPDATE in eigener
  Transaktion beansprucht, bevor gesendet wird — zwei Scheduler koennen
  denselben Termin nicht doppelt verschicken. Reminder bleiben PDB-inert.
- **Operations Health (Phase 4, 2026-08-26):** Persistente Heartbeats fuer
  Outbox-Worker und Reminder-Scheduler sowie `GET /api/ops/health` aggregieren
  ausschliesslich lokale Telemetrie: aktive/letzte Sync-Jobs, Staged-Backlog,
  Fehler und Retry-Limit, offene Reminder-Tasks und Parser-/Triage-Probleme.
  Der admin-only Screen zeigt Fresh/Stale/Missing textuell, ist fuer
  Institutsadmins mandantengefiltert und verlinkt nach Staged, Ingest log und
  Reminders. Kein Refresh fuehrt einen Live-PDB-Aufruf aus.
- **First-Run-Setup in der UI (2026-08-25):** `GET /api/setup` +
  `POST /api/setup/admin` legen den allerersten Admin ohne CLI an (nur solange
  die User-Tabelle leer ist, danach dauerhaft 409; AuditEvent
  `setup.admin_created`, Auto-Login). Frontend zeigt dafuer den `SetupScreen`
  (Auth-Status `setup`). Der `create_admin`-Schritt entfaellt fuer Desktop wie
  Compose (docs/06, deploy/README). Ausserdem baut `npm run build` in
  `desktop/` jetzt die komplette Tauri-App in einem Schritt:
  `build-sidecar.py --bundle` haengt `tauri build --target <host triple>` an,
  womit das Triple-Problem aus ADR 005 automatisch geloest ist.
- **Desktop-Paketierung (2026-08-25):** `desktop/` enthaelt eine Tauri-Shell,
  die den als PyInstaller-Onefile gepackten Backend-Sidecar startet, auf
  `/health` wartet und den Webview darauf zeigt. Das Backend kann die gebaute
  SPA selbst ausliefern (`app/static_spa.py`, Setting `static_dir`), damit UI
  und API auf einer Origin liegen und Session-Cookie/CSRF unveraendert
  funktionieren. Zustand (DB, Credential-Key, Logs) liegt im
  Anwendungsdatenverzeichnis, dasselbe wie beim Windows-Launcher. Die
  Das Endnutzer-Bundle waehlt Production-Reads ab Werk; PDB-Verkehr beginnt
  erst nach dem Verbinden persoenlicher Access-Codes. Der Schreibbereich bleibt
  `dummy_only`. Details: `docs/adr/005-desktop-packaging.md`.
- **PDB-Request-Timeout griff nie (2026-08-25, Bugfix):** `requests` waehlt den
  Adapter mit dem *laengsten* Prefix, und itkdb mountet einen eigenen fuer die
  PDB-Basis-URL. Der generische `https://`-Adapter war damit fuer jeden echten
  API-Call verschattet — Reads liefen unbegrenzt. Ein haengender Request hat
  reproduzierbar den Evidence-Sync bei 60/263 Komponenten eingefroren.
  `app/pdb_gateway.py` bindet den Timeout jetzt an *jeden* gemounteten Adapter
  (Instanz-Wrapping, damit itkdbs Cache erhalten bleibt). Danach lief derselbe
  Sync in 97 s durch: 713 Testlaeufe ueber 222 Module.
- **Testlauf-Detail statt nur pass/fail (2026-08-25):** `fetch_test_run_evidence`
  kennt jetzt `with_detail` und spiegelt Messwerte, Properties und
  Attachment-Metadaten (`getTestRun` pro Lauf). Der Institutssweep bleibt
  flach/billig, die Einzelkomponente holt Detail. Damit stehen Klebegewichte,
  Metrologie und IV-Kurven lokal zur Verfuegung; neue Endpunkte
  `GET /api/components/{sn}/tests` und `GET /api/components/thumbnails`.
- **Attachments lokal (2026-08-25):** `app/attachment_store.py` spiegelt
  Bilder/Plots in einen Ordner (`attachment_dir`), fuer neue Downloads unter
  `<Seriennummer>/<source>/<Attachment-Code><Extension>`. PDB-Dateinamen
  wandern nie in einen Pfad; die Extension stammt aus einer Allowlist.
  Bestehende flache `relative_path`-Eintraege bleiben lesbar und werden beim
  Reuse nicht umgeschrieben. Die UI zeigt Messwerte, IV-Kurven und Thumbnails
  (Detailseite und Komponentenliste).
- **`sync-evidence` antwortet 503 statt „0 gespiegelt" (2026-08-25):** eine
  nicht erreichbare PDB sah bisher aus wie „diese Komponente hat keine Tests" —
  genau die Verwechslung, die eine ganze Instituts-Ansicht wie lauter fehlende
  Pflichttests aussehen laesst.
- **Staged-first + Auto-Mirror (ADR 006, M1–M4 umgesetzt,
  2026-08-26):** Der zusammenhaengende Produktschnitt liegt im Arbeitsbaum;
  die abschliessende gemeinsame Regression und Abnahme laeuft getrennt davon.

  - **M1 Auto-Mirror:** Binary-Store, EOS mit frisch bezogener URL und
    credential-freie Share-Links verwenden denselben abgesicherten lokalen
    Attachment-Store. Nach einem erfolgreichen persistenten Komponentenjob
    startet automatisch ein ebenfalls persistenter Evidence-/Attachment-Job.
    Topbar und Components-Screen verfolgen beide Jobs ueber Navigation und
    Reload hinweg. Detailgalerie, Testlaufkarten und Thumbnails lesen nur noch
    lokal gespiegelte Dateien; Metrologie-Bilder brauchen deshalb nach dem
    Mirror keinen direkten PDB-/EOS-Zugriff mehr.
  - **M2 Preview + Ghost:** `GET /api/components/{sn}/preview` projiziert den
    aktuellen Mirror mit offenen Actions serverseitig. Die Detailseite bietet
    `Current`/`Staged`-Tabs, Inline- oder Off-Modus; die browserlokale
    Preference aendert weder Status noch Berechtigung. Ghost-Tests zeigen ihre
    servergebundene Ingest-Evidenz inklusive lokaler Attachments und zaehlen
    bis zur Bestaetigung nur als `pending`.
  - **M3 Testerfassung:** `GET /api/test-types` und
    `POST /api/test-types/sync` spiegeln Testtyp-Schemata read-only ueber die
    persoenliche PDB-Verbindung. `Add test result` auf der
    Komponentendetailseite bietet Datei-Drop sowie ein schemaerzeugtes Formular;
    beide erzeugen einen an `component_sn` gepinnten `IngestFile`, durchlaufen
    denselben Dry-Run und legen erst danach eine Staged-Action an. Abweichende
    Payload-SNs blockieren statt still umgeschrieben zu werden.
  - **M4 Staged + Ingest log:** `Staged` ersetzt die generische Outbox-Ansicht
    als gruppierter Arbeitsvorrat mit Komponentenbild, Stage, lesbarer Summary,
    `Push to PDB`/`Discard` und separater History. Das `Ingest log` ist ein
    read-only Verlauf mit Dry-Run und Komponentenlinks; Upload und manuelle
    Erfassung liegen ausschliesslich auf der Detailseite. ADR, UI-Referenz und
    Offline-Mockup sind auf diesen Zuschnitt nachgezogen.

  Kein M-Punkt hebt `dummy_only`, Outbox/Audit oder persoenliche
  Credential-Bindung auf. Zielvertrag und Abnahmekriterien stehen in
  [`superpowers/specs/2026-08-25-staged-first-module-page-design.md`](superpowers/specs/2026-08-25-staged-first-module-page-design.md).
- **Admin Settings fuer operative Institutsprofile (2026-08-26):** Ein
  strukturierter, admin-only Settings-Screen verwaltet Stammdaten sowie
  Mattermost-/Webhook-Kanaele, Shipment-Empfangscheckliste,
  typabhaengige Shipment-Reception-Tests, Glue-Topfzeiten und den
  Evidence-Mirror-Scope ohne Raw-JSON. Die API
  validiert diese Profilwerte zentral, erhaelt ein bereits gespeichertes
  Channel-Secret bei Rueckgabe des Maskenwerts `***` und auditiert nur
  geaenderte Schluessel/Kanalnamen — nie URLs oder sonstige Secret-Werte.
  Institutgebundene Admins bleiben auf ihr eigenes Profil beschraenkt; globale
  Admins koennen das Zielinstitut waehlen. Die gemeinsame UI-/API-Verifikation
  ist Teil der noch laufenden Gesamtabnahme.
- Harte Sicherheitsregeln sind dokumentiert: keine produktive PDB in Dev/Tests,
  `references/zeuthenflow` nur lesen, keine Secrets, kein Institut-Hardcoding.
- Backend-Basis: FastAPI-App, SQLAlchemy-Modelle fuer Institute, Komponenten,
  Outbox und Audit; Pydantic-Schemas; Health-, Institute-, Component-, Outbox-
  und Audit-Endpunkte; Outbox-Statusvertrag als Backend-Quelle der Wahrheit.
- Read-only PDB-Mirror ist im Aufbau: Komponentensync, PDB-Gateway (seit
  2026-07-08 produktionsfaehig hinter doppeltem Opt-in — es gibt keine
  Testinstanz mehr, siehe docs/09 + ADR 003), Mapping von PDB-Komponenten in
  lokale Mirror-Records, Demo-Fixtures und ein API-Endpunkt zum Starten eines
  Institute-Komponentensyncs.
- Frontend-Basis: Vite/React-Shell mit Navigation, Health-Anzeige,
  Komponentenliste mit Such-/Scan-Ergonomie, Detail-/Familienansicht und
  persistentem Component-/Evidence-Sync-Control, gruppiertem Staged-Screen,
  read-only Ingest-Log und Dashboard-Summary.
- Ingestion-Basis: lokale Inbox fuer Instrument-JSONs mit Hash und Auditspur.
  Datei-Drop und schemaerzeugte manuelle Erfassung auf der Komponentendetailseite
  koennen nach komponentengebundenem Dry-Run einen `upload_test_run`-Draft
  stagen; das separate Ingest-Log bleibt read-only und kein Pfad schreibt
  direkt in die PDB.
- Ingestion-Parser: Registry in `app/ingestion.py` (`glue-weight-v1`,
  `iv-curve-v1`, `pull-test-v1`, `pdb-test-run-v1`, generischer Fallback)
  normalisiert Payloads zu einem Preview mit blockierenden Issues und
  Warnungen; lokale Namen im `component`-Feld werden gegen den Mirror
  aufgeloest. Testtyp-spezifische Dry-Run-Checks fangen abgeschnittene
  Instrument-Ausgaben (gepaarte VOLTAGE/CURRENT- bzw.
  PULL_STRENGTH/PULL_GRADE-Arrays, NUMBER_WIRES-Abgleich). `GET
  /api/ingest/files/{id}/preview` liefert den Dry-Run auf der Detailseite und
  im read-only Ingest-Log; `propose-outbox` blockt bei Dry-Run-Issues mit 409.
- PDB-Upload-Converter (Phase-2/Worker-Schnitt): `app/pdb_upload.py` baut aus
  dem geprueften Ingest-Payload einen kanonischen `uploadTestRunResults`-Body.
  Der Worker revalidiert mit demselben Converter direkt vor dem Submit; der
  reale Submitter postet nie mehr das rohe Instrument-JSON, sondern die
  normalisierte SN/TestType/Results-Form (lokale Namen werden zur Mirror-SN).
- Test-Run-Evidence-Mirror (Phase-1/3-Basis): `TestRunEvidence` +
  `app/test_run_evidence.py` koennen externe/PDB-Testlaufresultate lokal
  idempotent spiegeln. `stage_service.satisfied_test_results` mischt diese
  Evidence mit confirmed itkFlow-Uploads; Stage-Suggestions und Dashboard-Gaps
  koennen damit bereits aus Mirror-Evidence gespeist werden.
- Stage-Move-Suggestion-Engine (Phase-3-Kickoff): reine Domain-Logik in
  `app/domain/stages.py` (Pflicht-Tests je Stage, institutsneutral via
  `InstituteProfile.settings`, Seed-Default aus der UI-Design-Referenz).
  `GET /api/components/{sn}/stage-suggestion` wertet bestaetigte Uploads
  (confirmed `upload_test_run`) zu passed/failed/missing aus und schlaegt den
  naechsten Stage-Move nur vor, wenn alle angezeigten Pflicht-Tests bis
  einschliesslich der aktuellen Stage passen; fehlende/fruehere Tests blocken
  konservativ; der PDB-Test-Run-Mirror wird als zusaetzliche Evidenzquelle herangezogen.
  Das Detail-UI zeigt die Pflicht-Tests-Tabelle + Vorschlag-Callout, und
  „Propose stage move" legt einen auditierten `stage_move`-Draft in die Outbox.
- Async-Outbox-Worker: eigenstaendiger Prozess (`app/run_worker.py`,
  `worker`-Service in Compose) beansprucht `approved`/`submitted`-Aktionen,
  wiederholt den Dry-Run gegen den aktuellen Mirror, ruft einen injizierten
  Submitter und setzt `confirmed` (mit `external_ref`) oder `failed`. Realer
  Submitter schreibt `uploadTestRunResults`/`setComponentStage`, verlangt die
  beim Approve gebundene persoenliche Credential und lehnt jedes Ziel ab, das keine eigene
  DUMMY-Testkomponente ist (`pdb_write_scope=dummy_only`, ADR 003).
  Idempotenz ueber `external_ref`; transiente `PdbSubmitUnavailable`-Fehler
  werden nach exponentiellem Backoff automatisch bis `worker_max_attempts`
  erneut versucht. Details: ADR 002.
- Watched-Folder-Agent ist bisher nur als Phase-2-Platzhalter dokumentiert.
- **Gegen echte Produktions-PDB validiert (2026-07-08):** Voller TUDO-Sync
  laeuft (read-only), reale Mapping-/Pagination-/Schema-Bugs gefixt, Prune
  (`stale`) fuer verschwundene Komponenten. Erstes DUMMY-Modul registriert
  (`20USEM00000435`). `is_dummy` leitet sich aus DUMMY-**Batch**-Mitgliedschaft
  ab (nicht dem `dummy`-Flag).
- **Navigationstoleranter Komponenten-Sync (2026-08-24):** Der lange
  Produktions-Read laeuft jetzt als persistenter, globaler Single-Flight-Job
  mit Poll-API und atomarem Mirror-Commit. Topbar und Components-Screen zeigen
  Phase, echten Zaehler, Fortschrittsbalken, Laufzeit und letztes Update; ein
  Screen-Wechsel oder Reload verliert den laufenden Job nicht. Der PDB-Fetch
  filtert serverseitig auf `state=ready`, liest feste 50er-Seiten seriell mit
  Timeout/Retry (einschliesslich Auth/JWKS) und verweigert metadatafreie
  Nutzdaten sowie Total-/Page-Drift. Jeder Retry aktualisiert den persistenten
  Job-Heartbeat, damit das UI trotz wartendem PDB-Read ein aktuelles
  Lebenszeichen zeigt. Alter synchroner und neuer Background-Endpunkt teilen
  denselben DB-Lease; parallele Mirror-Prunes sind damit ausgeschlossen. Lokale
  Komponenten werden blockweise vorgeladen, Stage-Events gebuendelt geschrieben.
  Ein Server-Neustart markiert den Job als `interrupted`; Teilstaende werden
  nie committed.
- **Statistik/Verlauf (Phase-1-Dashboard-Ausbau):** `StageEvent`-Historie wird
  beim Sync aus dem PDB-`stages[]`-Log rekonstruiert; `app/stats.py` +
  `/api/stats/production` liefern Throughput, Lead-Time, Stage-Dwell und Rework;
  eigener **Statistics-Screen** im Frontend. Kein separater Zeitreihen-Speicher
  noetig — alles aus einem Fetch.
- **Stage-Farbsystem:** geordneter Ramp kuehl→gruen (Fortschritt); Gruen nur
  FINISHED, Rot nur FAILED/TRASHED (CVD-sicher, `ui.ts`/`app.css`).

- **Jig-/Tool-Registry + Assembly-Wizard (Phase 3/4, 2026-08-26):** Die lokale
  Registry besitzt auditiertes strukturiertes CRUD, RFID/Code-Scan und
  `active|flagged|blacklisted`-Verwaltung. `POST /api/sync/tools/{institute}` spiegelt bereits gesyncte
  PDB-`TOOLS`-Komponenten read-only in die Registry (Code=SN, Label=lokaler
  Name, kompatible Typen aus Profil-Regeln oder generischem R-Type-Parsing).
  Komponenten-Sync triggert diesen Registry-Refresh automatisch; lokale
  RFID-/Blacklist-Informationen werden nicht durch normale Syncs
  heruntergestuft. Der scanner-first Assembly-Wizard loest Parent/Child exakt
  aus dem Mirror auf, bietet aktive typkompatible Tools und benutzbare
  Glue-Batches als Quick-Select/Scan, zeigt den kanonischen Server-Dry-run und
  staged `assemble_component`. Worker und Submitter revalidieren Zustand,
  Snapshots, Glue-Ablauf/Topfzeit und beide Teilnehmer. Der PDB-Guard laeuft vor
  Client-Aufbau: nur registrierte DUMMY-`MODULE|HYBRID`, nie Sensor/ASIC. Die
  fokussierten Offline-Suites enthalten keine Live-PDB-Aufrufe.

- **Phase-4-Backend fuer Glue-Batches, Shipments und Reminder (2026-08-26):**
  lokale Glue-Batch-Registry mit profilbasierter Topfzeit und auditiertem
  Komponentenverbrauch; read-only PDB-Shipment-Mirror fuer beide Richtungen
  mit lokal fuehrender Empfangscheckliste; sowie wiederkehrende Reminder im
  bestehenden Worker inklusive Mattermost-/generischem HTTPS-Webhook-Adapter
  stehen. Webhook-URLs werden in Institute-Antworten immer redigiert und aus
  Fehlern/Logs ferngehalten. Der fokussierte Offline-Schnitt ist mit 33 Tests
  verifiziert. Nutzer-/Entwicklervertrag: `docs/11-logistics-operations.md`.
  Die drei Produktscreens sind verdrahtet. Operative Profilwerte sind
  zusaetzlich ueber den strukturierten Admin-Settings-Screen pflegbar;
  Assembly-Quick-Select und Shipment-Reception-Test-Integration sind im
  nachfolgenden Ausbau inzwischen umgesetzt.

- **Auth End-to-End (docs/06, 2026-07-10):** Lokale Konten `viewer/operator/admin`
  vollstaendig — Login/Session/`create_admin`, serverseitige `user_id`-
  Attribution (statt Client-Actor), `require_operator`-Enforcement auf
  Sync/Outbox/Ingest, Double-Submit-CSRF (`itkflow_csrf`/`X-CSRF-Token`) +
  konfigurierbares `Secure`-Cookie, und das Frontend (Login-Screen, User-Rail,
  Rollen-Gating, Demo-Fallback) plus **Admin-`Users`-Screen** (Konten anlegen,
  Rolle/aktiv setzen, Passwort-Reset). Verifiziert: 211 Backend-Tests +
  Frontend-`tsc` gruen. Offen: Demo-User-Seed, 4-Augen-Approve, OIDC. Details docs/06.
- **Persoenliche Plus4U/PDB-Verbindung (Phase 6 vorgezogen, 2026-08-24):**
  Jedes lokale Konto verwaltet im neuen Account-Screen sein eigenes
  Access-Code-Paar. Das Backend verifiziert vor dem Speichern, erzwingt
  eindeutige PDB-Identitaeten und gleiche Institutsmitgliedschaft und legt nur
  AES-256-GCM-Ciphertext mit usergebundener AAD ab. Web-Reads haben keinen
  globalen Fallback; Background-Syncs laden ueber `SyncJob.user_id`. Beim
  Approve bindet `OutboxPdbPrincipal` Worker und Retries an die PDB-Identity
  des Freigebenden. API/Browser/Audit/Jobs/Logs bleiben secret-frei; der
  Windows-Launcher verwaltet einen stabilen Master-Key ausserhalb des Repos.
  Details: docs/06, docs/09, ADR 004.
- **Doku-Disziplin & -Waechter (2026-07-10):** CLAUDE.md-Regel #6 macht
  Doku-Updates verbindlich; `docs/00-doc-map.md` haelt die Ownership fest. Zwei
  Haiku-Subagenten pflegen die Doku — `yatagarasu` (Drift-Audit, read-only) und
  `tenjin` (Doku-Sync) — plus der `Stop`-Hook `.claude/hooks/doc-guard.ps1`
  (erinnert bei Code-Change ohne Doku-Update, fail-open/loop-sicher) und der
  `/sync-docs`-Command. Siehe `docs/00-doc-map.md`, `docs/03-agent-team.md`.
- **Komponenten-Typ-Decodierung (2026-07-10):** `frontend/src/ui.ts` uebersetzt
  die kodierten PDB-`type_code`s (`R5M0`, `ATLAS18R5`, `PBR5`) institutsneutral
  in lesbare Kurzform („Module · Endcap R5, pos 0"); verdrahtet in
  Komponentenliste, Detail, Family-Tree und Board. Volle Taxonomie/Legende in
  `docs/10-itk-domain-reference.md`.
- **Create-Module (2026-07-10):** DUMMY-Modul/Hybrid-Registrierung als
  Outbox-Flow — `POST /api/components/register` (operator-gated, Typ-Guard nur
  MODULE/HYBRID → 400 sonst) legt einen `register_component`-Draft an;
  Worker-Revalidate + `register_dummy_component` schreiben (dummy-only,
  Access-Codes). Frontend: `RegisterModuleForm` (`canWrite`). 220 Backend-Tests
  und Frontend-`tsc` gruen. Siehe `docs/10`.
- **Jig-/Pflicht-Property-Pruefung (2026-07-10):** institutskonfigurierbare
  Pflicht-Properties pro Testtyp (`InstituteProfile.settings['required_properties']`,
  z. B. `{"GLUE_WEIGHT": ["JIG"]}`); der Ingest-Dry-Run (`preview` +
  `propose-outbox`) blockt, wenn das benutzte Jig fehlt. Regel-#4-safe, Default
  leer. `ingestion.missing_required_properties` + 227 Backend-Tests gruen. Siehe
  `docs/07`.
- **Metrologie-Parser (2026-07-10):** `module-metrology-v1` validiert die
  `MODULE_METROLOGY`-Result-Groups. Wichtiger Befund: die Messprogramm-/zFlow-JSON
  ist bereits die Standard-PDB-`uploadTestRunResults`-Form → itkFlow ingestet
  Metrologie direkt. Offen: der Roh-`.txt`→JSON-Converter (Nominal-Tabellen).
  Siehe `docs/10`.
- **Auth-Login-Fix (2026-07-10):** Alt-/Legacy-Session-Cookies liessen Login
  (403) und `/api/auth/me` (500) crashen — gefixt (`whoami` mintet fehlende
  CSRF-Token, `csrf_protect` nimmt Login aus), 3 Regressionstests. 240 Tests gruen.
- **Dev-Server-Login-Fix (2026-07-10):** Das hartnaeckige „kann mich nicht
  einloggen" war letztlich **kein Auth-Code-Problem** (Login funktioniert
  end-to-end durch den Proxy, per Cookie-Jar-Probe verifiziert), sondern ein
  Fleet aus veralteten Dev-Servern (ein IPv6-only `:5173`, Streuner auf `:5192`,
  Vite-Drift auf `:5174`), der den Browser auf einem toten/veralteten Tab
  stranden liess. `frontend/vite.config.ts` pinnt jetzt `host:127.0.0.1`,
  `port:5173`, `strictPort:true` (faellt laut aus statt zu driften) und proxyt
  auf explizit `http://127.0.0.1:8000` (nie `localhost` — Windows/modernes Node
  loest zuerst `::1` auf und verfehlt das IPv4-only-Backend).
- **Windows-Dev-Neustart (2026-08-24):** Das Root-Skript
  `start-itkflow.ps1` raeumt erkannte laufende itkFlow-Listener auf den fest
  konfigurierten Dev-Ports `8000`/`5173` auf und startet FastAPI und Vite
  reproduzierbar auf `127.0.0.1` neu. Unbekannte Portbesitzer werden ohne
  explizites `-ForcePortCleanup` nicht beendet; das Skript setzt Anwendungsdaten
  und Konten nicht zurueck. Der Default bleibt PDB-inert; der explizite Schalter
  `-EnableProductionReads` aktiviert den produktiven Read-Pfad fuer Component-
  Syncs, ohne den Outbox-Worker zu starten (`dummy_only`, Write-Test-Opt-in aus).
  Browserzugriff: `http://127.0.0.1:5173`.
- **UI: Label-Humanisierung & Workflow-Klarheit (2026-07-10):** `stageLabel()`
  (`ui.ts`) humanisiert `SNAKE_CASE`-Stages (`HV_TAB_ATTACHED` → „HV Tab
  Attached"), institutsneutral, ITk-Akronyme (HV/QC/PWB…) bleiben gross;
  verdrahtet in Board-Spaltenkoepfe (Klartext + Rohcode-Unterzeile), Stage-Chips
  (Rohcode im `title`), Stage-Vorschlaege, Legende, Dashboard- und
  Statistik-Balken sowie den Komponententyp-Filter (`roleLabel`). Der damalige
  Triage/Outbox-Schnitt benannte den Zwei-Schritt-Flow explizit; seit ADR 006
  liegen Erfassung/Dry-Run auf der Detailseite und Review/Submit im
  komponentengruppierten `Staged`-Screen. Rohcodes bleiben ueberall als
  kanonische Referenz (Hover / Stammdaten-Feld). Siehe `docs/10`.

## Naechste Arbeitspakete

1. **Stage-Move-Strecke schliessen** (`domain-modeler`, `backend-dev`,
   `pdb-gateway-dev`): Suggestion-Engine, `stage_move`-Draft und realer
   Submitter (setComponentStage, DUMMY-Scope) stehen (2026-07-08). Erledigt
   (2026-07-10): PDB-Test-Run-Fetcher (`POST /api/components/{sn}/sync-evidence`,
   `POST /api/sync/evidence/{institute_code}`) an den lokalen
   `TestRunEvidence`-Mirror angebunden.
2. **Dashboard ausbauen** (`frontend-dev`, `backend-dev`): Summary erweitert
   (2026-07-08): `/api/dashboard/summary` liefert Required-Test-Gaps fuer
   aktive Module, Sync-Alter (neueste/aelteste Mirror-Zeile), stale/trashed
   Mirror-Zeilen sowie Review-/Approved-/Submitted-/Failed-Outbox-Zaehler; das
   Dashboard zeigt diese als kompakte KPI-Tiles und die Institutsverteilung mit
   profilbasierten Logos bzw. generischen Code-Icons. Required-Test-Gaps nutzen
   denselben Evidence-Service wie Stage-Suggestions und arbeiten mit dem
   Mirrored PDB-Test-Run-Evidence.
3. **Outbox-Worker haerten** (`backend-dev`, `pdb-gateway-dev`, `qa-engineer`):
   Async-Worker steht (2026-07-08, ADR 002); automatischer Retry mit Backoff
   fuer transiente Fehler und `worker_max_attempts` sind durchgesetzt. Offen:
   die reale Idempotenz-Pruefung gegen die Produktions-PDB im strikt
   DUMMY-gescopeten E2E, bevor der `submitted`-Recovery-Pfad scharf geschaltet wird.
4. **Upload-Converter und Worker-Schnitt** (`ingestion-dev`, `architect`,
   `backend-dev`): Registry, Preview und Dry-Run-Gate stehen inkl. Glue-Weight-,
   IV-, Pulltest- und generischem Parser (2026-07-08). Der Uebergang
   `ParsedTestRun`/Ingest-Payload -> PDB-Uploadcall ist ueber den reinen
   Converter `app/pdb_upload.py` definiert; Worker-Revalidierung und realer
   Submitter nutzen denselben kanonischen Payload-Build. Offen: optional
   Metrologie-Rohformat-Parser und weitere instrumentspezifische Converter.
5. **Produktions-Reads + DUMMY-Write-E2E validieren** (`pdb-gateway-dev`,
   `qa-engineer`): Read-Smoke gegen Produktion und **voller TUDO-Sync
   validiert** (2026-07-08): 3628 Payloads → ~2655 Mirror-Zeilen. Dabei mehrere
   reale Bugs gefunden+gefixt (Parent-ObjectId-Crash, Pagination-Check,
   `institute_code`-Overflow auf 32, `is_dummy` aus DUMMY-**Batch** statt
   `dummy`-Flag, Prune/`stale`). **Erstes echtes Dummy-Modul registriert**
   (`20USEM00000435`, `DUMMY_TUDO`). Offen: der volle `pytest -m pdb_write`
   (Upload + Stage-Move-Kreis auf der Dummy-SN) noch scharf durchziehen.
   Erledigt (2026-08-24): sichtbarer Background-Sync, navigationstolerantes
   Polling, explizites serielles Paging mit Timeout/Retry (auch fuer die vom
   Client intern ausgefuehrte Authentifizierung), Retry-Heartbeat, gemeinsamer
   Single-Flight-Lease fuer beide API-Pfade sowie Bulk-Mirror-Optimierung.
   Reale Messung: Die erste `full`-100er-Seite brauchte ohne State-Filter ca.
   14,0 s, mit `state=ready` ca. 3,6 s. Am problematischen Offset 300 lief
   `pageSize=100` (`pageIndex=3`) in einen Read-Timeout von mehr als 60 s;
   dieselben Datenbereiche kamen mit den festen 50er-Seiten (`pageIndex=6/7`)
   in 4,49 s beziehungsweise 2,24 s. Deshalb ist 50 die feste Seitengroesse;
   erschoepfte Retries markieren den Job als fehlgeschlagen, ohne den
   bestehenden Mirror zu veraendern.

## Geplant / verbleibende Ausbaustufen

Details im jeweiligen Dokument:

- **Nutzer, Rollen & Audit-Zuordnung** — [`06-users-roles-audit.md`](06-users-roles-audit.md).
  Lokale Accounts, Rollen, Attribution, Frontend, CSRF und persoenliche
  PDB-Verbindungen sind umgesetzt. Offen bleiben optionales OIDC/CERN-SSO,
  Demo-User-Policy und konfigurierbares 4-Augen-Prinzip.
- **Jig-/Tool-Registry + typ-gefilterter Quick-Select** —
  [`07-jig-tool-quickselect.md`](07-jig-tool-quickselect.md). Registry, auditiertes CRUD/Statuspflege,
  PDB-`TOOLS`-Mirror, Glue-Batch-Auswahl und direkte Einbindung in den
  scanner-first Assembly-Wizard sind umgesetzt (2026-08-26). Verbleibend ist
  nur die fachliche Bestaetigung exakter PDB-Property-Codes je Institut/Typ;
  sie werden danach per `assembly_property_keys` konfiguriert.
- **Logistik, Glue und Reminder** — [`11-logistics-operations.md`](11-logistics-operations.md).
  Backend-Modelle, API, Audit, Shipment-Read-Sync, Worker-Notifier und die
  drei Produktscreens (Glue Batches, Shipments, Reminders; 2026-08-26) stehen.
  Die profilgesteuerte Reception-Test-Verknuepfung samt Deep-Link, Done-Gate
  und auditiertem Admin-Override ist umgesetzt. Die lokale admin-only
  Betriebsansicht samt persistenten Worker-/Scheduler-Heartbeats, Queue-,
  Reminder-, Sync- und Parser-Signalen steht ebenfalls. Offen bleiben weitere
  Notification-Adapter/Eskalationen sowie das Phase-6-Row-/Query-Scoping.
  Shipment-Erstellung und GLUE-Registrierung in der PDB bleiben ausserhalb des
  aktuellen sicheren Schreibumfangs.
- **Remote-Zugriff / Tunneling** — [`08-remote-access.md`](08-remote-access.md). Zugriff von
  zuhause; Empfehlung Tailscale/WireGuard (spaeter Cloudflare Tunnel).
  **Abhaengigkeit:** erst nach dem Auth-Fundament scharf schalten.

## Meilensteine

### Phase 0 - Fundament stabilisieren

**Ziel:** Ein sicherer, reproduzierbarer Entwicklungsstand, auf dem alle
weiteren Features ohne PDB-Produktionsrisiko entstehen.

**Epics:**

- Dev- und CI-Kommandos dokumentieren und gruene Offline-Tests erhalten.
- PDB-inerten Default sowie produktive Reads hinter doppeltem Opt-in absichern.
- Institute-Profil, Component-Mirror, Outbox und Audit als Kernmodell
  konsolidieren.
- Agentenvertrag und Roadmap-Pflege verbindlich in Repo-Dokumente schreiben.

**Done-Kriterien:**

- Standardtestlauf braucht keine PDB-Tokens und keine Netzwerkverbindung.
- Jede PDB-nahe Arbeit ist entweder gemockt oder als Sandbox-Test markiert.
- Neue Agenten finden `CLAUDE.md` und diese Roadmap ohne Rueckfrage.
- Kein neuer Code hardcodiert Institutscodes, lokale Prefixe oder PDB-IDs.

**Owner-Agenten:** `architect`, `backend-dev`, `pdb-gateway-dev`,
`qa-engineer`, `docs-writer`.

**Abhaengigkeiten:** Produktive PDB-Reads nur mit doppeltem Opt-in und fuer
markierte Integrationschecks; anonymisierte Referenz bleibt read-only.

### Phase 1 - Read-only-Cockpit

**Ziel:** itkFlow liefert taeglichen Nutzen ohne PDB-Schreibrisiko:
Komponenten suchen, Status verstehen, Familien sehen, Dashboards lesen.

**Epics:**

- Komponenten-/Test-/Shipment-Sync aus der produktiven PDB hinter Read-Opt-in in lokale
  Mirror-Tabellen.
- Komponentenbrowser mit Scanner-first-Suche, Filtern, Detailseite und
  Familienbaum.
- Erste Dashboards fuer Durchsatz, offene Tests, Stage-Verteilung und
  auffaellige Abweichungen.
- Reconciliation-Report zwischen lokalem Mirror, erwarteten Workflowdaten und
  zFlow/PDB-Zustand vorbereiten.

**Done-Kriterien:**

- Ein Institut kann einen Read-only-Sync starten und danach Komponenten ohne
  Netzwerk-Latenz durchsuchen.
- Detailseiten zeigen Parent/Children, Stage, Typ, Location, lokale Namen und
  Sync-Zeitpunkt verlaesslich.
- UI bleibt produkt-facing Englisch und i18n-faehig; interne Planungsdoku
  bleibt Deutsch.
- Keine PDB-Schreiboperation existiert ausserhalb der Outbox-Grenze.

**Owner-Agenten:** `pdb-gateway-dev`, `backend-dev`, `frontend-dev`,
`qa-engineer`.

**Abhaengigkeiten:** Stabile Component-Mirror-Semantik aus Phase 0; genuegend
anonymisierte Demo-/Testdaten.

### Phase 2 - Test-Ingestion und Upload-Queue

**Ziel:** Instrument-JSONs landen nachvollziehbar in itkFlow, werden
serverseitig geparst und validiert und auf der Komponentendetailseite als
gepruefte Staged-Action fuer die PDB vorbereitet.

**Epics:**

- Inbox-Modell fuer Dateien, Parserstatus, erkannte Komponente und Testtyp.
- Parser-Plugins fuer die wichtigsten Testtypen mit anonymisierten Fixtures.
- Watched-Folder-Agent als duenner Client: beobachten, hochladen, Status
  melden; kein Fachparsing auf Instrument-PCs.
- Komponentengebundene Datei-/Formularerfassung mit Vorschau,
  Validierungsfehlern, Pass/Fail-Signalen und Freigabe nach Staged.
- Read-only Ingest-Log sowie Staged-Review/Audit und Retry-Regeln fuer
  Test-Uploads.

**Done-Kriterien:**

- Parser laufen deterministisch gegen Fixture-Sets und schreiben keine PDB.
- Jede Upload-Absicht wird als Outbox-Aktion mit Auditspur erzeugt.
- Operatoren koennen fehlerhafte Dateien korrigieren, zurueckstellen oder
  begruendet verwerfen.
- Netzwerk- und PDB-Ausfaelle verlieren keine Dateien und erzeugen sichtbare
  Statusmeldungen.

**Owner-Agenten:** `ingestion-dev`, `backend-dev`, `frontend-dev`,
`qa-engineer`, `code-reviewer`.

**Abhaengigkeiten:** Outbox-Kontrakt aus Phase 0/1; Fixture-Inventar aus
`references/zeuthenflow` nur lesend.

### Phase 3 - Assembly-Workflows

**Ziel:** Registrierung, Assemblierung und Stage-Vorschlaege ersetzen die
fehleranfaelligen Sheet-Pfade schrittweise, waehrend zFlow parallel weiter
abgeglichen wird.

**Epics:**

- Wizards fuer Hybrid- und Modul-Bau mit Scanner-first Eingaben.
- Registrierung/Assemblierung als validierte Outbox-Aktionen mit Preview.
- Attachment-Properties fuer Jigs, Pickup-Tools, Glue-Samples und Panels.
- Stage-Vorschlaege aus PDB-Stages, Pflichttests und Institute-Profil.
- Taeglicher Abgleichreport fuer Parallelbetrieb und Cutover-Vorbereitung.

**Done-Kriterien:**

- Keine direkte PDB-Schreibroute aus Request-Handlern oder UI-Actions.
- Coordinator kann Vorschlaege pruefen, bestaetigen oder begruendet ablehnen.
- Workflows enthalten keine hartcodierten DESY/Zeuthen-Spezifika.
- Parallelbetrieb zeigt Abweichungen zwischen zFlow, PDB und itkFlow sichtbar an.

**Owner-Agenten:** `architect`, `domain-modeler`, `backend-dev`,
`frontend-dev`, `pdb-gateway-dev`, `qa-engineer`.

**Abhaengigkeiten:** Read-only Mirror und Outbox aus Phase 1/2; validierte
Stage-/Test-Mappings im Institute-Profil.

### Phase 4 - Logistik und Betrieb

**Ziel:** Operative Nebenprozesse wandern aus Sheets/Skripten in nachvollziehbare
itkFlow-Module.

**Epics:**

- Shipments mit Empfangspruefung, Checklisten und PDB-Abgleich.
- Glue-Batch-Registry mit Topfzeit, Verbrauch, Warnungen und PDB-Bezug.
- Tool-/Jig-Registry inklusive RFID-Mapping und Blacklist/Flag-Verwaltung.
- Reminder und Notification-Adapter fuer E-Mail, Mattermost/Telegram oder
  institutspezifische Kanaele.
- Health-/Betriebsansicht fuer Sync, Outbox, Agenten und Parser.

**Teilstand (2026-08-26):** Glue-Batch-Registry und Produktscreen, read-only
Shipment-Mirror mit lokalem Empfang, profilgesteuerten Reception-Tests und
Produktscreen sowie Reminder/HTTPS-Notifier mit Produktscreen stehen. Der
admin-only Settings-Screen pflegt Notification-Kanaele, Empfangscheckliste,
Reception-Test-Mapping, Glue-Topfzeiten und Evidence-Scope strukturiert im
Institutsprofil. Tool-CRUD/Statuspflege und die direkte Tool-/Glue-Integration
im Assembly-Wizard samt Dry-run/Outbox/Worker-Revalidierung stehen ebenfalls.
Die lokale Operations-Health-Ansicht samt Heartbeats und Deep-Links steht.
Offen sind weitere Notification-Adapter/Eskalationen und das vollstaendige
Mandanten-Scoping. Details in
[`11-logistics-operations.md`](11-logistics-operations.md).

**Done-Kriterien:**

- Operative Aktionen sind auditiert und rollenfaehig.
- Reminder/Notifications sind konfigurierbar und nicht institutsspezifisch im
  Code verdrahtet.
- Glue-/Tool-/Shipment-Daten sind mit Komponenten und Outbox-Aktionen
  verknuepfbar.

**Owner-Agenten:** `backend-dev`, `frontend-dev`, `domain-modeler`, `devops`,
`qa-engineer`.

**Abhaengigkeiten:** Institute-Profil-Konfiguration; Auth/Rollenmodell.

### Phase 5 - Visual Inspection und Kollaboration

**Ziel:** VI-Bilder, Annotationen, Berichte und externe Leseansichten ersetzen
CERNBox-HTML und manuelle Share-Flows.

**Epics:**

- Bild-/Anhangspeicher ueber lokales Dateisystem oder S3-kompatiblen Store.
- VI-Galerie mit Defekt-Annotation und komponentenbezogener Historie.
- Bericht-/Export-Generierung fuer Koordinatoren und Review-Runden.
- Read-only Share-Links mit Ablauf, Audit und Zugriffsbeschraenkung.

**Done-Kriterien:**

- Rohbilder, Annotationen und PDB-relevante JSONs bleiben nachvollziehbar
  verknuepft.
- Externe Links geben nur freigegebene, read-only Inhalte preis.
- Speicherbackend ist deploybar ohne CERN-spezifische Dienste.

**Owner-Agenten:** `frontend-dev`, `backend-dev`, `devops`, `docs-writer`,
`qa-engineer`.

**Abhaengigkeiten:** Objektstore-/Dateisystem-Entscheidung; Auth/Share-Link
Policy.

### Phase 6 - Multi-Institut-Haertung und v1.0

**Ziel:** Ein zweites Institut kann itkFlow mit minimaler Sonderarbeit pilotieren;
v1.0 ist installierbar, dokumentiert und betreibbar.

**Epics:**

- Onboarding-Assistent "neues Institut in 30 Minuten".
- Mandantentrennung, Rollen, Credential-Ablage und Audit fuer mehrere
  Institute. Persoenliche verschluesselte PDB-Credentials und gebundene
  Worker-Identitaet sind seit 2026-08-24 umgesetzt (ADR 004); vollstaendiges
  Row-/Query-Scoping aller lokalen Read-Modelle bleibt offen.
- Beispielprofile fuer Endcap/Barrel und konfigurierbare Workflows.
- i18n-Grundlage fuer EN/DE, mit Englisch als Produkt-Default.
- Release-/Upgrade-Doku, Backup/Restore, Monitoring und Pilot-Checkliste.

**Done-Kriterien:**

- Neues Institut braucht keine Codeaenderung fuer Namensschema, Workflows,
  Stage-/Test-Mappings oder Notifications.
- Deployment funktioniert per dokumentiertem `docker compose up`.
- Kein Web-/Worker-PDB-Pfad faellt auf globale oder fremde Credentials zurueck;
  Backup/Restore umfasst DB und getrennten Master-Key.
- v1.0-Pilot hat dokumentierte Akzeptanzkriterien, bekannte Risiken und
  Rollback-Pfad.

**Owner-Agenten:** `architect`, `devops`, `docs-writer`, `backend-dev`,
`frontend-dev`, `qa-engineer`.

**Abhaengigkeiten:** Reife Phase-1-bis-5-Workflows; echte Pilot-Rueckmeldungen.

## Pflege

- Diese Roadmap wird aktualisiert, wenn sich Reihenfolge, Scope oder
  Done-Kriterien eines Meilensteins aendern.
- Abgeschlossene Punkte werden nicht geloescht, sondern kurz als erledigt oder
  ersetzt markiert, sobald ein entsprechender Arbeitsabschnitt committet ist.
- Neue Ideen gehoeren zuerst in den passenden Meilenstein oder in
  [`02-revamp-plan.md`](02-revamp-plan.md), falls sie die Produktvision statt
  die Ausfuehrung betreffen.

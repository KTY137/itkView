# Attachments und Bilder: Speicherwege, lokaler Spiegel, Fehlersuche

> Warum es dieses Dokument gibt: „Warum sehe ich keine Bilder?" wurde mehrfach
> gestellt und jedes Mal von vorne untersucht. ITk-Bilder liegen in **drei**
> verschiedenen Speichersystemen, und itkFlow zeigt sie **nur** aus dem lokalen
> Spiegel an. Diese beiden Sätze zusammen erklären fast jeden Befund. Der Rest
> dieses Dokuments macht sie nachvollziehbar.
>
> Stand: 2026-08-27 auf `main`. Dokumentiert ist der Stand **mit**
> Drei-Phasen-Split (plan/fetch/commit), `.part`-Staging,
> `OutageCircuitBreaker` und getrenntem Blob-/Association-Index.
>
> Zuständigkeit laut `docs/00-doc-map.md`: dieses Dokument (Zeile seit
> 2026-08-27 eingetragen). Die Metrologie ist bewusst ausgelagert:
> [`13-metrology-artifacts.md`](13-metrology-artifacts.md) misst diese Mechanik
> am realen Metrologie-Bestand und leitet die Schlüsselregeln daraus ab.

## 1. Kurzfassung

1. Ein Attachment kommt aus einer von drei Quellen: **PDB-Binary-Store**,
   **EOS**, oder **öffentlicher Share-Link in einem Result-Feld**. Welche es
   ist, steht im gespiegelten Evidence-Payload (`type` / `source`).
   Sonderfall seit 2026-08-27: eine **Ordner**-Freigabe antwortet mit einem
   **Tar-Archiv** statt mit der Datei (live gemessen). itkFlow packt genau
   **ein vollständiges** Mitglied im Speicher aus, nach einer festen
   Auswahlregel und hinter einem vollständigen Satz Schutzregeln — Abschnitt
   2.3a. Beim Vergleich mit dem bisher besten Mitglied überlappt höchstens das
   feste 512-Byte-Sniff-Präfix des nächsten Kandidaten. `extractall` gibt es
   nirgends, und kein Mitglied wird je unter seinem eigenen Namen geschrieben.
2. Der Sync lädt die Bytes in einen **lokalen Ordner** (`attachment_dir`), ein
   Unterverzeichnis je Seriennummer. Die Datenbankzeile ist nur der Index.
3. Die UI rendert Bilder **ausschließlich** aus diesem Ordner. Kein Bild wird
   beim Öffnen eines Screens aus der PDB oder von EOS geholt.
4. Damit ein Bild sichtbar wird, müssen **fünf** Dinge stimmen: Evidence
   gespiegelt → Deskriptor mit der Komponente/dem Lauf verknüpft → Blob
   heruntergeladen → Datei liegt im konfigurierten Spiegel →
   `content_type` beginnt mit `image/`. Ein Blob darf dabei von vielen
   Komponenten und Läufen referenziert werden; seine Bytes liegen trotzdem nur
   einmal auf der Platte.
5. Häufigster praktischer Befund in der Entwicklungsumgebung: es gibt **zwei**
   Attachment-Wurzeln, weil `attachment_dir` unkonfiguriert relativ zum
   Arbeitsverzeichnis des Serverprozesses aufgelöst wird (Abschnitt 4.1).
6. **Ein Bild kann gespiegelt und trotzdem unerreichbar sein.** Vier Ursachen
   dieser Art sind am 2026-08-27 behoben worden, alle vier am Live-Spiegel
   gemessen: das Listen-Limit zählte Attachment-**Zeilen** statt Komponenten
   (83 statt 279 Kacheln, Abschnitt 5.3), die Galerie einer Komponente kannte
   die Bilder ihrer **Kinder** nicht (3 von 432 Bildern liegen auf Modulen,
   241 auf deren direkten Kindern, Abschnitt 5.1), und eine zweite
   CERNBox-URL-Form wurde nie umgeschrieben (20 Zeilen, Abschnitt 2.3).
   Zusätzlich hatte ein wiederverwendeter Share-Code nur **eine**
   `component_sn`/`test_run_ref`-Kombination: ein Download blieb zwar
   dedupliziert, aber alle weiteren Zuordnungen verschwanden. Der additive
   Referenzindex in Abschnitt 3.2 trennt deshalb Blob- von
   Association-Identität.
7. **Metrologie ist der Sonderfall, an dem diese Mechanik am wenigsten hilft:**
   104 Läufe, 104 Anhänge, **0 Bilder**, 80× derselbe Dateiname, 102 von 104
   mit demselben Titel und ein einziger Content-Type für alle. Gemessen und mit
   den Code-Regeln, die daraus folgen, in
   [`13-metrology-artifacts.md`](13-metrology-artifacts.md).

## 2. Die drei Speicherwege

Empirische Grundlage: Live-Validierung 2026-08-25 in
`docs/superpowers/specs/2026-08-25-staged-first-module-page-design.md` §F
(„Empirische Grundlage") sowie ADR 006, Punkt 6.

### 2.1 PDB-Binary-Store (`type: "file"`)

Der Normalfall. Die Datei liegt in der PDB selbst; das Attachment-Objekt trägt
einen `code` (Hex-Handle) und gehört zu genau einem Testlauf.

- **Erkennung:** Deskriptor mit `source == "pdb"` und `type != "eos"`
  (`attachment_store._fetch_bytes`). Die Metadaten entstehen in
  `pdb_test_evidence._attachment_summaries` aus `getTestRun.attachments[]`.
- **Abruf:** `getTestRunAttachment` mit `{code, testRun}` — **zuerst und nur,
  wenn der Deskriptor eine Test-Run-Referenz trägt**. Danach als Fallback
  `uu-app-binarystore/getBinaryData` mit `{code}`
  (`attachment_store._fetch_pdb_bytes`).
- **Warum die Reihenfolge:** Die Live-Validierung 2026-08-25 hat gezeigt, dass
  der Binary-Store-Weg **eine HTML-Seite mit Status 200** zurückgeben kann.
  Diese Seite hat eine plausible Größe und einen plausiblen Namen und würde
  als „Bild" gespeichert — sichtbar wird der Fehler erst als kaputtes
  Vorschaubild. Deshalb ist `getTestRunAttachment` der bevorzugte Weg und
  jede Antwort läuft durch `looks_like_html()`.
- **Was schiefgehen kann:**
  - Kein `test_run_ref` im Deskriptor → nur der Fallback-Weg bleibt, und der
    liefert häufiger HTML.
  - HTML-Antwort → Datei wird **nicht** gespeichert, `failed`-Zähler steigt,
    nächster Sweep versucht es erneut.
  - 4xx (404/403) → sofortiger, endgültiger Fehlschlag für diese Datei.
  - Netzwerkartige Fehler (DNS, Reset, TLS-Timeout, 408/425/429, 5xx) →
    Wiederholung mit exponentiellem Backoff bis `sync_page_max_attempts`.
- **Wie es sich für den Nutzer anfühlt:** In der aufgeklappten Lauf-Ansicht
  steht statt des Vorschaubilds ein Platzhalter „Not downloaded yet"; in der
  Bildergalerie fehlt die Kachel ersatzlos; ein direkter Aufruf der
  Attachment-URL antwortet mit 404 und dem Text „This attachment is not
  mirrored locally yet. Sync attachments first."

### 2.2 EOS (`type: "eos"`)

Die Datei liegt auf dem CERN-EOS-Speicher. Die PDB liefert dafür auf Wunsch
eine **vorsignierte URL** auf `eosatlas.cern.ch`, die kurz gültig ist.

- **Erkennung:** `type == "eos"` im gespiegelten Deskriptor.
- **Wichtig — es wird nie ein Token gespeichert:** Der Evidence-Mirror ruft
  `getTestRun` bewusst mit `noEosToken: True` auf
  (`pdb_test_evidence._run_detail_payload`), und
  `_attachment_summaries` **entfernt zusätzlich defensiv den Query-Teil** einer
  `eos`-URL, damit auch ein geändertes Upstream-Default niemals eine Signatur
  in die lokale Datenbank schreiben kann.
- **Abruf:** Unmittelbar vor jedem einzelnen Download holt
  `attachment_store._fresh_eos_url` eine **frische** URL über
  `getTestRun {testRun, noEosToken: False}`, sucht darin den Eintrag mit
  demselben `code` und prüft die URL mit `_safe_http_url(url, eos=True)` —
  erlaubt ist ausschließlich `https` auf exakt den Host `eosatlas.cern.ch`.
  Erst dann `client.get(url)`.
- **Warum nie cachen:** Die Signatur läuft schnell ab. Eine gespeicherte oder
  auch nur eine Minute alte URL liefert später einen Fehler statt der Datei;
  eine an den Browser durchgereichte URL wäre außerdem ein weitergegebenes
  Zugriffstoken in Browserverlauf und Proxy-Logs.
- **Was schiefgehen kann:**
  - Deskriptor ohne `test_run_ref` → keine frische URL beschaffbar → kein
    Download (`_fresh_eos_url` gibt `None` zurück).
  - Der Lauf listet den `code` nicht mehr → kein Download.
  - URL zeigt nicht auf `eosatlas.cern.ch` → abgelehnt, ohne Request.
  - Transiente Fehler beim Nachholen der URL zählen als transient und lösen
    den normalen Retry aus.
- **Praxisstand (korrigiert 2026-08-27, gemessen am Live-Spiegel
  `%LOCALAPPDATA%\itkflow\itkflow.db`, nur lesend geöffnet):** EOS ist bei
  TUDO **der Hauptweg für Bilder**, kein theoretischer Fall. Von 3772
  Attachment-Zeilen zeigen **425 Deskriptoren** auf `eosatlas.cern.ch`, und
  über sie kommen **422 der 432** gespiegelten Bilddateien — fast alles
  Sichtprüfungsfotos, weit überwiegend auf **Sensoren**.
- **Die alte Aussage an dieser Stelle war falsch** („bei TUDO existieren keine
  EOS-Attachments"). Sie stammte aus Spec §F, wo 360 Attachments einer
  **kleineren, älteren Arbeitskopie** gescannt wurden, und war die
  folgenschwerste Fehlannahme dieses Dokuments: sie hat jede Bildersuche von
  genau dem Weg weggeführt, auf dem praktisch alle Bilder liegen. Wer eine
  Zahl aus einem Teilbestand liest, muss den Bestand mitschreiben.

### 2.3 Öffentliche Share-Links in Result-Feldern (CERNBox / Sync&Share)

Das zFlow-Erbe. Bei DESYZ liegen Visual-Inspection-Bilder **nicht** als
Attachments, sondern als öffentliche Links **im Wert eines Result-Feldes**.

- **Herkunft (Legacy-Workflow):** `references/zeuthenflow` (nur lesen, nie
  ausführen — CLAUDE.md, harte Regel 1) lädt die Bilder per Hand auf eine
  öffentliche Webseite bzw. CERNBox/DESY-Sync&Share und schreibt die
  entstehenden URLs in die Test-Run-JSON:
  `modules/processVisualInspection.py` baut in `find_images()` (Zeilen ~399-402)
  aus `public_webpage` + Dateiname die URL und legt sie in `printJson()`
  (Zeilen ~759-778) unter `results.URLSCRATCHPAD` ab; pro Schadensbefund
  kommen `URLS1` … `URLS6` dazu (Zeilen ~55-60 und ~92). Der Wert kann ein
  String **oder eine Liste** sein, und der Sentinel `"failed"` steht dort, wo
  ein Upload nicht geklappt hat.
- **Erkennung in itkFlow:** `pdb_test_evidence._share_link_summaries` scannt
  beim Evidence-Detail-Fetch **alle** Result-Werte über `_http_urls()`:
  Strings und (rekursiv) Listen/Tupel, akzeptiert wird nur, was `http`/`https`
  mit Hostname ist. `"failed"` fällt dadurch automatisch heraus — es ist keine
  URL. Es gibt **keine** Liste bekannter Feldnamen: erkannt wird an der Form
  des Werts, nicht am Code `URLSCRATCHPAD`. Das ist Absicht (kein
  Institut-Hardcoding, Regel 4).
- **Deskriptor:** `code` = SHA-256-Hexdigest der URL (deterministisch, damit
  ein Re-Sync dieselbe Datei wiedererkennt), `filename` = Basename aus dem
  URL-Pfad, `title` = Name des Result-Felds, `type`/`source` = `share_link`,
  `content_type` = `None`.
- **Abruf — und der Kernpunkt, der wiederholt Zeit gekostet hat:** Die
  `/s/<token>`-URL eines ownCloud-/Reva-Systems (CERNBox, DESY Sync&Share, …)
  ist **nicht die Datei**, sondern eine HTML-Betrachterseite. Sie antwortet
  mit 200 und `text/html`. `attachment_store._share_link_candidates` erzeugt
  deshalb aus der Form `/s/<token>` in dieser Reihenfolge:
  1. `https://<host>/remote.php/dav/public-files/<token>` (DAV-Route,
     liefert zusätzlich eine Content-Length),
  2. `https://<host>/s/<token>/download`,
  3. die Original-URL als letzte Möglichkeit.

  `/index.php/s/<token>/download` wird **bewusst nie** erzeugt — diese Form ist
  bei der Live-Validierung an der Namensauflösung gescheitert. Endet der Pfad
  bereits auf `/download`, wird nichts umgeschrieben.
- **Zweite Form derselben Freigabe (neu 2026-08-27):** die Weboberfläche von
  CERNBox adressiert dieselbe öffentliche Freigabe als
  `/files/link/public/<token>[/<Pfad in der Freigabe>]`, und aus dem Browser
  kopierte Links tragen genau diese Form. Im Live-Spiegel sind das **20
  Attachment-Zeilen** (87 Deskriptoren auf 76 `PWB`-Komponenten, Titel „Link
  to Picture", **ein einziger Share-Token**). Sie wurden bisher **nicht**
  umgeschrieben, bekamen die Single-Page-App als HTML, wurden von der
  HTML-Abwehr korrekt abgelehnt und waren deshalb **nie** gespeichert. Regel:
  1. `https://<host>/remote.php/dav/public-files/<token>[/<Pfad>]`,
  2. bei nicht-leerem Pfad `https://<host>/s/<token>/download?files=<Pfad>`
     (Archiv-Route, siehe 2.3a), bei leerem Pfad
     `https://<host>/s/<token>/download`,
  3. die Original-URL als letzte Möglichkeit.

  Ein **nacktes** `/s/<token>/download` wird bei nicht-leerem Pfad bewusst nie
  erzeugt: es liefert die **ganze Freigabe**, und ein beliebiger Teil davon
  unter dem Code eines Bildes ist genau der Fehler, gegen den eine fehlende
  Datei vorzuziehen ist.

### 2.3a Ordner-Freigaben antworten mit einem Archiv (2026-08-27)

Am 2026-08-27 **live und anonym** gegen die Share-Links des Owners gemessen
(keine Zugangsdaten, nur GET, nur Lesen). Für den Ordner-Token der 87
Deskriptoren:

| Route | Antwort |
|---|---|
| `/files/link/public/<token>/<Eintrag>` | 200 `text/html`, 9566 B (die Single-Page-App) |
| `/remote.php/dav/public-files/<token>/<Eintrag>` | **501 Not Implemented** |
| `/remote.php/dav/public-files/<token>` | **501 Not Implemented** |
| `/s/<token>/download?files=<Eintrag>` | 200 `application/octet-stream`, chunked, **POSIX-`ustar`-Tar** |
| `/s/<token>/download?path=%2F&files=<Eintrag>` | **500 Internal Server Error** |
| `/s/<token>/download?path=%2F<Eintrag>` | 200, aber das Archiv der **ganzen Freigabe** |
| `/s/<token>/download` | 200, die ganze Freigabe (Minuten, nie benutzt) |

Zum Vergleich, dieselbe Messung an den funktionierenden Datei-Freigaben:
`/remote.php/dav/public-files/<token>` antwortet 200 `image/jpeg` mit
Content-Length, `/s/<token>/download` 200 `image/jpeg` chunked, `/s/<token>`
dieselbe HTML-Seite. **Diese Routen bleiben unverändert** — die 501 ist eine
Aussage über die *Ordner*-Freigabe, nicht über die Route.

Drei Befunde, die die Planung korrigieren:

1. **Es ist kein ZIP, sondern ein Tar** (`ustar` an Byte 257). Die frühere
   Notiz in 2.3 war falsch.
2. **Der „Dateiname" des Deskriptors ist ein Ordner.** `filename` ist z. B.
   `20USED50000029` — ohne Endung, und im Archiv ein Verzeichnis:

   ```text
   20USED50000029/                                        (Verzeichnis)
   20USED50000029/20USED50000029_2.JPG                     8 845 759 B
   20USED50000029/20USED50000029_4.JPG                     6 951 643 B
   20USED50000029/20USED50000029_2025_09_08_pics1-4.txt          104 B
   20USED50000029/20USED50000029_1.CR2                    32 642 645 B
   20USED50000029/20USED50000029_3.CR2                    30 617 214 B
   ```

   Es gibt also **kein** „das eine Mitglied": mehrere Dateien kommen infrage.
3. **Das Archiv ist groß.** 79 063 040 Byte für ein 8,8-MB-Bild, ~25 s. Der
   Erstabruf der 20 Zeilen kostet einmalig rund 1,5 GB Netzverkehr.

**Auswahlregel (deterministisch, dokumentiert, geloggt).** Betrachtet werden
ausschließlich Mitglieder, die *reguläre Dateien* sind, deren Name jede
Prüfung besteht und die **innerhalb des benannten Eintrags** liegen
(`name == Eintrag` oder `name.startswith(Eintrag + "/")`). Unter diesen
gewinnt der kleinste Schlüssel `(Rang, Pfad)`:

| Rang | Bedeutung |
|---:|---|
| 0 | genau der benannte Eintrag |
| 1 | Bytes, die als browserdarstellbares Bildformat gesnifft wurden |
| 2 | Bytes, die als anderes echtes Bildformat gesnifft wurden (z. B. TIFF) |
| 3 | ein anderes Format, für das der Spiegel eine Endung schreibt |
| 4 | alles übrige (landet endungslos, also unbenutzbar) |

Bildränge kommen aus den Magic Bytes, nicht aus der vom Host gewählten Endung:
eine `.jpg` mit TIFF-Bytes bleibt Rang 2, eine `.tiff` mit JPEG-Bytes ist Rang
1. Gleichstand wird über den normalisierten Pfad gebrochen. Für **verschiedene**
Pfade ist die Auswahl damit unabhängig von der Streaming-Reihenfolge. Tar
erlaubt jedoch denselben normalisierten Pfad mehrfach; dort gilt bewusst
**first wins** und jede spätere Dublette wird ignoriert. Für das Beispiel oben
gewinnt `20USED50000029_2.JPG`: die `.CR2` sind Rang 4, die `.txt` Rang 3, und
von den beiden tatsächlich als JPEG gesnifften Mitgliedern sortiert `_2` vor
`_4`. Ein lexikografisch früheres TIFF könnte eine browserfähige JPEG-/PNG-
Auswahl nicht verdrängen.
**Live nachgemessen** mit dem
echten Code gegen das echte Archiv: ausgewählt `20USED50000029_2.JPG`,
8 845 759 B, gesnifft `image/jpeg`, Ablage
`<SN>/share_link/<code>.jpg` (generisch: `<SN>/<source>/<code>.<ext>`).

Nennt die URL **keinen** Eintrag (`/s/<token>` ohne Pfad), wird nur ein Archiv
mit **genau einem** infrage kommenden Mitglied akzeptiert; sonst wird
abgelehnt. Raten ist genau der Weg, auf dem eine falsche Datei unter einem
richtigen Code landet.

**Sicherheitsregeln beim Auspacken** — der gefährlichste Vorgang im ganzen
Modul, weil hier Bytes eines fremden Hosts auf der Platte eines Operators
landen. Alle in `backend/app/attachment_store.py`, jede mit einem Test, dessen
Rotwerden bei Entfernen der Regel nachgewiesen wurde:

- **Nie `extractall`, nie `extract`.** Genau ein Mitglied wird ausgewählt und
  **im Speicher** gelesen; die Bytes gehen anschließend durch denselben
  Ablageweg wie jede andere Datei, dessen Dateiname aus dem PDB-Code plus
  Endungs-Allowlist entsteht. Ein Testfall prüft den **geparsten** Modulbaum
  auf diese Aufrufe.
- **Nur reguläre, nicht-sparse Dateien.** Symlinks, Hardlinks,
  Zeichen-/Blockgeräte, FIFOs und Verzeichnisse werden am **Typ** abgelehnt.
  Zusätzlich wird jedes `TarInfo.issparse()` abgelehnt: PAX-Sparse kann sich
  nämlich als normaler `REGTYPE`/`isreg()` präsentieren und würde eine reine
  Typprüfung umgehen.
- **Namensprüfung.** Abgelehnt werden `..` in jeder Position, führendes `/`,
  Backslash (Windows-Trenner), Doppelpunkt (Laufwerksbuchstabe, NTFS-Stream),
  NUL und jedes weitere Steuerzeichen. `./`-Präfixe werden normalisiert.
- **Zwei Größenprüfungen.** Die **deklarierte** Größe im Header entscheidet,
  ob ein Mitglied überhaupt gelesen wird (`> attachment_max_bytes` → nie
  gelesen); die tatsächlich gelesenen Bytes müssen der Deklaration
  entsprechen. Ein abgeschnittenes oder widersprüchliches Archiv wird als
  Verdikt abgelehnt, nicht als Netzwerkfehler durchgereicht.
- **Vier Deckel gegen Bomben.** (a) die komprimierten Bytes **vom Draht**,
  (b) bei gzip zusätzlich der komplette **dekomprimierte Tar-Strom** inklusive
  Headern, Padding sowie GNU-longname-/PAX-Metadaten, (c) die Summe der
  **deklarierten** Mitgliedsgrößen und (d) die **Mitgliederzahl**
  (`ARCHIVE_MEMBER_LIMIT = 2048`). (a), (b) und (c) sind
  `ARCHIVE_SIZE_BUDGET_FACTOR = 4` mal `attachment_max_bytes`: bewusst
  abgeleitet, damit ein Institut, das sein Attachment-Limit senkt, auch senkt,
  was ein fremder Host ihm schicken oder dekomprimieren lassen darf. Die
  getrennte Dekompressionsgrenze ist nötig, weil `tarfile` GNU-/PAX-Metadaten
  verarbeitet, bevor sie als normale Mitglieder sichtbar würden.
- **Streamen statt Materialisieren.** Das Archiv wird in einem Vorwärtsdurchlauf
  direkt vom Socket gelesen; im Speicher liegt nie mehr als **ein vollständiges**
  Mitglied plus das feste 512-Byte-Sniff-Präfix eines möglichen Nachfolgers.
  Erst dieses Präfix bestimmt den echten MIME-Rang; der bisher beste Kandidat
  wird freigegeben, *bevor* der restliche Körper eines besseren gelesen wird.
- **Nur Tar und gzip-Tar.** bzip2 und xz sind durch Weglassen abgelehnt (nie
  beobachtet, und die extremsten Kompressionsraten). Ein gzip-Strom wird erst
  akzeptiert, wenn die `ustar`-Magic im **dekomprimierten** Präfix steht —
  sonst würde eine gzip-komprimierte *einzelne Datei* fälschlich als Archiv
  gelesen und verloren gehen. Optionale gzip-Felder (Extra/Dateiname/Kommentar)
  dürfen dabei länger als das 512-Byte-Tar-Sniff-Fenster sein. Nur bei
  erkannter gzip-Magic gelten zwei getrennte feste Deckel: bis zu 128 KiB für
  den vollständigen gzip-Header und danach bis zu weitere 128 KiB komprimierte
  Deflate-Daten, aus denen höchstens die ersten 262 Klarbytes entstehen. So
  bleibt auch ein legaler Header, der exakt am ersten Deckel endet,
  klassifizierbar. Ein dort nicht abgeschlossener Header oder ein danach noch
  immer nicht entscheidbarer Strom wird abgelehnt, nie unbegrenzt gelesen oder
  als opake Datei gespeichert. Eine gültige kurze gzip-Datei darf dagegen EOF
  erreichen, eine längere liefert 262 Klarbytes ohne `ustar`; beide bleiben
  bytegleich auf dem normalen Dateipfad. ZIP wird nicht versucht: CERNBox
  liefert keines.
- **Dieselben Prüfungen wie zuvor.** HTML-Abwehr, Größenlimit und
  Content-Sniffing laufen auf den **extrahierten** Bytes weiter. Ein Archiv ist
  ein neuer Transportweg, keine neue Vertrauensstufe.
- **Content-Type aus den Bytes.** Der `content_type` kommt zuerst aus den
  Magic Bytes des Mitglieds und erst danach aus seiner Endung — der Name
  stammt vom fremden Host, die Bytes sind das, was gespeichert wird. Ohne
  diesen Schritt landete die Datei endungslos mit `is_image = false` und
  bliebe in der Galerie genauso unsichtbar wie vorher.
- **Logs.** Geloggt werden nur der Attachment-Code, Größe, Content-Type und ein
  statischer Ablehnungsgrund. **Weder Mitgliedsname noch URL** gelangen ins
  Log: beide stammen aus der fremden Freigabe und können personenbezogene
  Angaben bzw. einen unauthentifizierten Zugriffsweg enthalten.

**Python-Hinweis:** Die Extraktions-*Filter* von `tarfile`
(`tarfile.data_filter`) werden **nicht** verwendet. Sie bereinigen einen Baum,
der auf die Platte geschrieben wird — dieser Code schreibt keinen Baum —, und
das Laufzeit-Python dieses Repos ist 3.10.11, wo es sie gar nicht gibt
(eingeführt in 3.10.12/3.11.4/3.12). Die äquivalenten Prüfungen stehen oben
und sind einzeln getestet.

**Restrisiko, bewusst benannt:** Ein Header, der die Länge einer echten Datei
*überschätzt*, ist von keinem Tar-Leser erkennbar — der Überhang ist die
Polsterung des Archivs selbst. Die Folge wären angehängte Nullbytes an einer
sonst gültigen Datei; deshalb laufen HTML-Abwehr, Größenlimit und Sniffing
weiterhin über die extrahierten Bytes.
- **Keine öffentliche Freigabe → gar kein Request:** Pfade der Form
  `[index.php/]apps/files/…` und `files/spaces/…` sind die **Dateibrowser**
  einer angemeldeten Sitzung, kein Share. `_share_link_candidates` liefert
  dafür eine **leere Liste**, `_fetch_share_link` bricht ohne einen einzigen
  HTTP-Request ab und schreibt eine `INFO`-Zeile (nur der Code, nie die URL).
  Der Spiegel enthält genau **eine** solche Zeile (`20USES50000771`, ein
  persönlicher CERNBox-Bereich). Sie ist per Konstruktion unerreichbar —
  ein öffentliches Share-Passwort ist dafür kein Ersatz; ein künftiger
  Zugriff bräuchte einen echten CERN-OAuth-/Account-Flow. itkFlow fragt
  deshalb niemals nach dem CERN-Account-Passwort. Die Formprüfung ist der
  Grund, warum die URL **nicht in jedem Sweep erneut** eine Login-Seite
  abholt. Ein persistentes „permanent gescheitert"-Flag in der
  Datenbank wäre die naheliegende Alternative und wurde **verworfen**: es
  hätte genau die 20 Bilder oben eingefroren, die dieselbe Runde repariert
  hat. Ein Code-Fix muss alte Fehlschläge wieder in Reichweite bringen.
- **Sicherheitsrahmen (ADR 006, Punkt 6):** Anonyme Freigaben laufen ohne
  Authentifizierung. Fuer eine passwortgeschuetzte **oeffentliche** Freigabe
  darf ausschliesslich das persoenlich gespeicherte Share-Passwort als
  ownCloud-Basic-Auth (`public:<Passwort>`) mitgehen; PDB-Codes werden nie an
  einen fremden Host geschickt. `_safe_http_url` lehnt URLs mit eingebautem
  Benutzer/Passwort, `localhost` und nicht-globale IP-Adressen ab.
  `_SafeShareRedirects` prueft jede Weiterleitung erneut und verlangt mit
  Share-Auth dieselbe HTTPS-Origin (Host und effektiver Port); Host-/Portwechsel
  sowie ein HTTPS-Downgrade werden verweigert. Gespeicherte Public-Share-
  Identitaeten akzeptieren nur den HTTPS-Standardport. Die finale URL wird
  nochmals geprueft.
- **Was schiefgehen kann:**
  - Alle Kandidaten liefern HTML (abgelaufener Share, gelöschte Datei,
    Login-Zwang, Nextcloud-Störung) → nichts wird gespeichert, und es gibt
    genau **eine** Log-Warnung: „Share-link attachment `<code>` only served
    HTML pages; the share may be expired or require sign-in. Nothing was
    stored." **Die URL steht bewusst nicht im Log** (sie ist ein
    unauthentifizierter Zugriffsweg auf fremde Daten).
  - Antwort > `attachment_max_bytes` → verworfen.
  - Netzwerkfehler bei mindestens einem Kandidaten → gilt als transient,
    Retry-Leiter greift.
- **Wie es sich für den Nutzer anfühlt:** Die Kachel bleibt bei einem nicht
  erreichbaren Share ehrlich leer. Der Sync meldet `skipped` und davon
  `authentication_required` separat; ein fehlendes oder falsches Passwort
  wird damit nicht als Netzwerkfehler oder erfolgreicher Download kaschiert.
- **Historischer Nebenbefund:** Bis 2026-08-26 wurden diese Bilder **nie**
  gespiegelt, weil der Mirror die Betrachterseite angefragt hat und die
  HTML-Abwehr korrekt zugeschlagen hat (docs/04, „Sync ueberlebt kurze
  Internet-Ausfaelle"). Der Fix war der Kandidatenweg oben.

### 2.3b Passwortgeschuetzte oeffentliche Shares und manuelle URLs (2026-08-27)

Der Account-Screen hat einen eigenen Bereich `Public share passwords`. Ein
Nutzer gibt dort eine unterstuetzte HTTPS-Freigabe (`/s/<token>`,
`/files/link/public/<token>` oder `/remote.php/dav/public-files/<token>`) und
deren **Share-Passwort** ein. Der Speicher-Request validiert nur lokal die
sichere Public-Link-Form und sendet **keinen** Request an den angegebenen Host.
Das schliesst den unmittelbar nutzergesteuerten SSRF-Pfad; erst ein spaeterer,
an eine tatsaechlich gespiegelte Evidence-URL gebundener Sync prueft den
Zugriff. Der Browser bekommt nach dem Speichern nur Host, Token-Ende und
Aenderungszeit zurueck, nie das Secret. Ein falsches Passwort kann deshalb
bewusst gespeichert werden und wird beim Sync ehrlich als `skipped` und
`authentication_required` gemeldet.

Die Ablage ist nutzergebunden: der Lookup-Key ist SHA-256 aus Host und Token,
der Ciphertext AES-256-GCM mit usergebundener AAD und dem bereits fuer
persoenliche PDB-Codes konfigurierten Master-Key. Ein von Nutzer A gespeichertes
Passwort kann weder von Nutzer B gelesen noch fuer dessen Sync benutzt werden.
Ein Background-Sync laedt den Resolver ueber `SyncJob.user_id`. Ein
beschaedigter optionaler Credential-Datensatz blockiert nicht den gesamten
Evidence-Sweep; die betroffene Freigabe wird als authentifizierungspflichtig
uebersprungen.

Nach dem ersten 401/403-/Login-HTML-Befund merkt sich der laufende Sweep nur
die gehashte Share-Identitaet und fordert denselben geschuetzten Share nicht
fuer jede Komponente erneut an. Abgelaufene, private oder weiterhin
geschuetzte Links zaehlen als `skipped`; `authentication_required` ist deren
erklaerbarer Teil. Beides steht im Job-Ergebnis und in der Sync-Anzeige.

Eine Share-URL kann ausserdem ueber den bestehenden manuellen Test-Flow
(`Record test` -> Dry-run -> `Stage upload`) in itkFlow gelangen, **wenn** das
gespiegelte PDB-Testtyp-Schema dafuer bereits ein kompatibles String-Feld
deklariert. itkFlow erfindet keinen lokalen Result-Code: ohne ein solches
Schema muss zuerst das PDB-Schema abgestimmt werden. Die URL bleibt bis zum
PDB-Submit ein normaler String-Wert; nach dem bestaetigten Upload entdeckt der
Evidence-Sync sie formbasiert und spiegelt die Datei. Fuer `GLUE_WEIGHT`
erzwingt die Ingestion numerische Werte nur im etablierten `GW_*`-Mess- und
Derived-Namespace, damit ein unabhaengiges schema-deklariertes URL-Feld nicht
faelschlich verworfen wird. Das ist **kein** Datei-Upload in CERNBox und kein
Ersatz fuer CERN-OAuth.

### 2.4 Vergleich auf einen Blick

| | Binary-Store | EOS | Share-Link |
|---|---|---|---|
| Marker im Deskriptor | `type: "file"`, `source: "pdb"` | `type: "eos"` | `source: "share_link"` |
| `code` | PDB-Handle (Hex) | PDB-Handle (Hex) | SHA-256 der URL (64 Hex) |
| Braucht `test_run_ref` | für den guten Weg ja | zwingend | nein |
| Authentifizierung | persönliche PDB-Codes | persönliche PDB-Codes | anonym oder persönliches Passwort einer öffentlichen Freigabe |
| URL dauerhaft speicherbar | entfällt | **nein** (Signatur) | ja (aber nie im Read-Model) |
| Typischer Fehlerfall | HTML-Seite statt Datei | abgelaufene Signatur | HTML-Betrachterseite |
| Bei TUDO beobachtet | ja | **ja — 425 Deskriptoren, 422 der 432 Bilder** | ja (29 URLs, siehe 8.) |

## 3. Der lokale Spiegel

### 3.1 Ablageort

```
<attachment_dir>/<seriennummer>/<source>/<code><extension>
```

- `attachment_dir` ist ein Setting (`backend/app/config.py`,
  Env `ITKFLOW_ATTACHMENT_DIR`). **Ist es nicht gesetzt — und das ist der
  ausgelieferte Default —, gilt der relative Pfad `attachments/`**, den
  `attachment_root()` mit `Path.resolve()` gegen das **Arbeitsverzeichnis des
  Serverprozesses** auflöst. Siehe die Falle in Abschnitt 4.1.
- Ein Verzeichnis je Seriennummer und darin je Blob-Quelle, damit man den Ordner öffnen und die Bilder
  mit einem beliebigen Betrachter ansehen kann. Ein **geteilter** Blob liegt
  jedoch bewusst nur einmal unter der Seriennummer seines ersten erfolgreichen
  Downloads; weitere Komponenten sehen ihn über Referenzen in der Datenbank,
  nicht über duplizierte Dateien.
- Die Bytes liegen **nicht** in der Datenbank. Backups müssen deshalb
  Datenbank **und** Attachment-Ordner umfassen (ADR 006, Konsequenzen).

### 3.2 Wie eine Datei adressiert wird

- Neuer Speicherpfad = `source`-Verzeichnis + `pdb_code` + Extension. Damit
  koennen zwei physisch verschiedene Blobs mit demselben Code aus `pdb` und
  `share_link` einander auch bei gleicher Extension nicht ueberschreiben.
  **Der von der PDB gelieferte Dateiname
  wandert niemals in einen Pfad** – er ist untrusted Input und wird nur zur
  Anzeige in der Datenbank gehalten.
- Seriennummer und Code werden sanitisiert: alles außer `A-Za-z0-9_-` wird zu
  `_` (`_SAFE_SN`, `_SAFE_CODE` in `storage_path()`). Der Quellenname wird
  ebenfalls auf dieses Alphabet normalisiert; falls dabei Zeichen ersetzt
  werden, verhindert ein Digest-Suffix, dass zwei verschiedene Quellen auf
  dasselbe Verzeichnis abgebildet werden.
- Die Extension stammt **nur** aus zwei Allowlists: der Content-Type-Tabelle
  `_EXTENSION_BY_CONTENT_TYPE` (jpg/png/gif/webp/bmp/avif/tif/svg/pdf/json/zip/
  txt/csv) oder — wenn der Content-Type nichts hergibt — dem Suffix des
  PDB-Dateinamens, sofern dieses in `_TRUSTED_DATA_SUFFIXES`
  (`.dat .log .xml .root .tsv .md`) steht. Passt nichts, wird **ohne
  Extension** gespeichert. Nichts Ausführbares steht auf einer der Listen.
- `test_run_attachment` (`backend/app/models.py`) ist der **kanonische
  Blob-Index**: eindeutig ist `(source, pdb_code)`; `content_type`,
  `size_bytes`, `relative_path` und `downloaded_at` beschreiben die genau
  einmal gespeicherten Bytes. `component_sn`, `test_type`, `test_run_ref`,
  `filename` und `title` bleiben als repräsentative Legacy-Felder erhalten,
  sind aber nicht mehr die maßgebliche Zuordnung.
- `test_run_attachment_reference` ist der **Association-Index** zum Blob:
  `attachment_id`, `component_sn`, `test_type`, `test_run_ref`,
  `filename`, `title`, `synced_at`. Eindeutig ist
  `(attachment_id, component_sn, test_type, test_run_ref)`. Ein fehlender
  Lauf wird als leerer String gespeichert und im Read-Model wieder zu
  `None`, damit SQLite und PostgreSQL dieselbe Unique-Semantik haben.
- Der Sync upsertet für **jeden** Deskriptor eine Referenz — auch wenn er den
  Blob wiederverwendet oder dessen Download fehlschlägt. Dadurch bedeutet
  Deduplizierung nur noch „ein Netzabruf/eine Datei", nicht „nur eine sichtbare
  Komponente oder ein sichtbarer Lauf".
- Beim **SQLite-/Desktop-Start** wird der neue Index einmalig aus vorhandenen
  `test_run_attachment`-Zeilen **und** allen bereits lokal gespeicherten
  Evidence-`attachments` zurückgefüllt. Das braucht keinen PDB-Kontakt und
  kopiert keine Bytes. Die erste Anweisung einer eigenen Transaktion reserviert
  den Migrationsmarker per `INSERT OR IGNORE`: von zwei parallel startenden
  Sidecars scannt deshalb genau einer die großen Evidence-Payloads. Bei einem
  behandelten Scanfehler wird der Marker in derselben Transaktion wieder
  entfernt; ein Prozessabsturz rollt Claim und Backfill zusammen zurück. Alte
  direkt erzeugte Zeilen bleiben über einen Legacy-Fallback lesbar.
- Der Backfill ist bewusst SQLite-spezifisch. Eine bereits bestehende
  PostgreSQL-/Compose-Datenbank erhält die neue Tabelle durch `create_all`,
  rekonstruiert historische Mehrfachzuordnungen aber erst beim nächsten
  Attachment-Re-Sync; dafür ist eine spätere Alembic-/JSONB-Migration nötig.
- `relative_path` ist relativ zur Wurzel, damit ein Verschieben oder
  Wiederherstellen des Ordners nicht jede Zeile ungültig macht. Bereits
  indizierte Legacy-Zeilen behalten ihren flachen Pfad
  `<seriennummer>/<code><extension>` unveraendert; `resolve_path()` liest
  immer den gespeicherten Wert. Nur neue Downloads verwenden das
  source-qualifizierte Layout.
- Beim Ausliefern prüft `resolve_path()` die Containment-Bedingung **erneut**
  (`Path.is_relative_to(root)` plus `is_file()`), statt der Datenbank zu
  vertrauen: eine von Hand editierte Zeile darf nicht aus dem
  Attachment-Verzeichnis herauslesen können.

### 3.3 Wann gilt ein Attachment als Bild

Genau eine Regel, im Modell (`TestRunAttachment.is_image`):

```python
content_type = (self.content_type or "").split(";", 1)[0].strip().lower()
content_type.startswith("image/")
```

Woher kommt `content_type`? In `_commit_outcomes` wird zuerst der Wert aus den
PDB-Metadaten geschrieben und **bei erfolgreichem Download** durch den
tatsächlich beobachteten Typ ersetzt (`_reported_content_type` für itkdb-
Antworten, `_response_content_type` für Share-Links). Der beobachtete Typ
gewinnt bewusst, weil die Listenmetadaten der PDB oft nur `file` sagen.

Ein SQLite-Start repariert ausserdem den historischen Reuse-Fehler, der einen
bereits beobachteten Typ wieder auf `NULL` setzen konnte. Ausschliesslich fuer
Zeilen mit abgeschlossenem Download und einem **exakten** gespeicherten
Bildsuffix wird der Typ aus dem Ablagevertrag wiederhergestellt: JPEG/PNG,
GIF/WebP/BMP/AVIF, TIFF und SVG. Das ist keine neue Byte-Heuristik: eine
`operator-note.svg.txt`, eine nie geladene `.svg` oder ein bereits gesetzter
Typ werden nicht angefasst. Zweites und jedes weitere Starten ist ein No-op.

Zwei Konsequenzen, die man kennen muss:

1. **Kein Download → kein verlässlicher Content-Type.** Bleibt der Wert der
   Metadaten leer, ist `is_image` falsch, und die Datei taucht in keiner
   Galerie und in keinem Thumbnail auf — auch dann nicht, wenn später eine
   Datei danebenliegt.
2. **Datei auf der Platte, aber `is_image = false` ist möglich.** Liefert die
   Gegenstelle keinen Content-Type (bei Share-Links denkbar), wird die Datei
   ohne Extension gespeichert und gilt nicht als Bild. Ausgeliefert würde sie
   dann als `application/octet-stream`. In der aktuellen Arbeitskopie ist
   dieser Fall nicht beobachtet (alle gespiegelten Share-Link-Bilder tragen
   `.jpg`/`.png`), aber er ist codeseitig möglich — *offen*, ob er in freier
   Wildbahn vorkommt.

`app/pdb_attachments.py` benutzt für den (heute ungenutzten, siehe 4.2)
Direktweg eine **andere, großzügigere** Heuristik: Content-Type beginnt mit
`image/` **oder** Dateiname endet auf eine bekannte Bildendung. Die beiden
Definitionen sind bewusst nicht geteilt, aber sie sind auch nicht identisch —
wer sie angleicht, sollte beide Aufrufer prüfen.

### 3.4 Sicherheitsnetz beim Herunterladen

Alle drei Quellen laufen durch dieselben Schutzmechanismen (ADR 006, Punkt 6):

- **HTML-Abwehr.** `looks_like_html()` prüft die ersten 512 Bytes (getrimmt,
  kleingeschrieben) auf `<!doctype`, `<html`, `<?xml`. Zusätzlich wird bei
  Share-Links der Content-Type-Header ausgewertet. Begründung im Code: „a
  failure that looks like a success everywhere except the screen".
- **Größenlimit.** `attachment_max_bytes`, Default 100 MiB. Share-Links werden
  mit `read(max_bytes + 1)` gelesen, damit eine endlose Antwort den
  Sync-Worker nicht blockiert; `_valid_payload` verwirft alles darüber.
- **Archiv-Auspacken.** Antwortet eine Freigabe mit einem Tar statt mit der
  Datei, gilt zusätzlich der vollständige Regelsatz aus Abschnitt 2.3a: nie
  `extractall`, nur reguläre Dateien, Namensprüfung gegen Traversal und
  absolute Pfade, Deckel auf komprimierte Draht-Bytes, den dekomprimierten
  Tar-Strom, deklarierte Bytes und Mitgliederzahl sowie ein vollständiges
  Mitglied plus ein festes 512-Byte-Sniff-Präfix im Speicher. Die drei
  Prüfungen oben laufen
  danach unverändert über die extrahierten Bytes.
- **Timeout.** `attachment_download_timeout_seconds`, Default 60 s.
- **Atomarer Abschluss.** Bytes gehen zuerst in eine `.part`-Datei **neben**
  dem Zielnamen (`_write_temp_bytes`), erst in der Commit-Phase folgt
  `os.replace()` (`_finalize_download`). Ein Leser kann also nie eine halb
  geschriebene Datei öffnen. Jeder Fetch erzeugt seinen `.part`-Pfad per
  exklusivem `mkstemp` neu; zwei Prozesse können deshalb weder denselben Rest
  truncaten noch beim Cleanup die Bytes des jeweils anderen löschen. Ein
  harter Prozessabbruch kann einen eindeutig benannten Rest hinterlassen. Ein
  späterer Worker ignoriert ihn; die noch offene Altersbereinigung ist eine
  getrennte Aufgabe und darf nie unbekannte aktive Owner erraten.
- **Überlappende Syncs je Blob serialisiert.** Direkter Refresh und
  Hintergrund-Sweep desselben Sidecars sperren innerhalb eines Prozesses nur
  ihre gemeinsamen
  `(attachment_root, source, code)`-Schlüssel; verschiedene Dateien bleiben
  parallel. Die Sperre reicht bis Commit/Rollback, damit der Wartende den
  kanonischen Blob bereits sehen und wiederverwenden kann. So gibt es auch bei
  zwei gleichzeitigen Aufrufen derselben Komponente in diesem Prozess nur
  einen Netzabruf und eine Datei. Prozessübergreifend sind die eindeutigen
  Temp-Pfade die Dateigrenze, während die Lease-Fence vor `os.replace` die
  Publikationshoheit entscheidet. `force` lädt einen physischen Blob pro
  Aufruf erneut, aber nicht einmal je Lauf-Deskriptor: mehrere Associations
  desselben `(source, code)` teilen auch dann genau einen erfolgreichen Fetch.
- **Pfad-Containment beim Schreiben.** `_write_temp_bytes` verweigert jeden
  Zielpfad außerhalb der Wurzel.
- **Keine Netzwerkarbeit in offener Schreibtransaktion.** Der Download ist in
  drei Phasen zerlegt — `plan` (nur `select`), `fetch` (bekommt gar keine
  `Session`), `commit` (kurz, netzwerkfrei). Grund war ein realer Vorfall:
  Retries innerhalb einer offenen Transaktion hielten die SQLite-Schreibsperre
  minutenlang, und alles andere scheiterte mit „database is locked" (docs/09,
  Abschnitt Attachment-Phase).
- **Outage-Breaker.** Fünf aufeinanderfolgende *transiente* Dateifehler
  (`ATTACHMENT_OUTAGE_BREAKER_THRESHOLD`) beenden die Attachment-Phase, damit
  ein Netzausfall nicht pro Datei die volle Retry-Leiter (Minuten) verbrennt.
  Permanente Einzelfehler (404, HTML, zu groß) setzen den Zähler zurück und
  lösen den Breaker nie aus. Bereits geholte Dateien werden trotzdem committet.
- **Keine Secrets in Fehlern.** `_TransientDownloadFailure` trägt bewusst
  keinen Upstream-Text: itkdb-Exceptions können den gerenderten Request
  (inklusive Zugangscodes) enthalten, urllib-Fehler die vollständige Share-URL.

### 3.5 Was der Sync eigentlich anstößt

- `pending_attachments()` liest die Deskriptoren **aus dem bereits
  gespiegelten Evidence-Payload** (`TestRunEvidence.payload["attachments"]`).
  Ohne Evidence-Detail gibt es also nichts herunterzuladen — das ist die
  Reihenfolge, die in der Fehlersuche zuerst zu prüfen ist.
- Evidence-Detail entsteht nur mit `with_detail=True`
  (`fetch_test_run_evidence`), also beim Einzelkomponenten-Sync und beim
  Evidence-Job — nicht beim billigen Flat-Sweep.
- Nach einem erfolgreichen Komponenten-Job stellt der Job-Manager automatisch
  einen Evidence-Job ein (ADR 006, Punkt 5). Der Umfang steht in
  `evidence_component_types` im Institutsprofil; der Code-Default ist
  `MODULE, SENSOR, SENSOR_S_TEST, HYBRID, HYBRID_ASSEMBLY, HYBRID_FLEX,
  HYBRID_TEST_PANEL, EC_POWERBOARD_FLEX, PWB, HV_TAB_SHEET`
  (`sync_jobs.DEFAULT_EVIDENCE_COMPONENT_TYPES`). Chips (ABC/HCC/AMAC) sind
  bewusst draußen.

## 4. Warum Bilder ausschließlich lokal ausgeliefert werden

Regel: **Kein geöffneter Screen holt jemals ein Bild aus der PDB oder von
EOS.** Der Endpunkt
`GET /api/components/{sn}/attachments/{code}?source={source}` antwortet mit
der exakt durch `(source, code)` bezeichneten Datei von der Platte oder mit
404 – niemals mit einem stillen Netzabruf. Ohne `source` bleibt die Route fuer
alte Bookmarks deterministisch kompatibel; neue Clients senden den Parameter
immer. Die Gründe, in der Reihenfolge ihres Gewichts:

1. **Ein `<img>`-Tag kann sich nicht authentifizieren.** PDB- und
   EOS-Zugriffe hängen an den *persönlichen* Zugangscodes des angemeldeten
   Kontos (ADR 004). Eine URL, die der Browser direkt lädt, müsste ein Token
   tragen — und landete damit in Browserverlauf, Referrern und Proxy-Logs.
2. **Signierte EOS-URLs laufen ab.** Eine Seite, die eine solche URL im
   Markup hält, zeigt nach kurzer Zeit kaputte Bilder — und zwar
   unregelmäßig, was die Fehlersuche vergiftet.
3. **Share-Links dürfen nie PDB-Credentials sehen** und der Browser des
   Nutzers soll nicht ungefragt zu einem fremden Host geschickt werden. Der
   Abruf gehört auf den Server, einmal, zur Mirror-Zeit.
4. **Kosten.** Eine Komponentenliste mit ein paar hundert Modulen würde ein
   paar hundert PDB-Requests auslösen, nur um festzustellen, dass die meisten
   kein Bild haben. Deshalb existiert `GET /api/components/thumbnails`: **ein**
   Request für eine ganze Liste, und er liefert ausschließlich Einträge, deren
   Bytes wirklich auf der Platte liegen.
5. **Die HTML-Abwehr soll einmal laufen, nicht pro Render.** Die Prüfung
   „ist das wirklich eine Datei und keine Login-Seite?" gehört an die eine
   Stelle, an der geschrieben wird.
6. **Offline-Fähigkeit.** Datenbank + Attachment-Ordner sind zusammen der
   wiederherstellbare Offline-Spiegel (ADR 006). Ohne VPN/PDB muss die
   Modulseite trotzdem vollständig aussehen.
7. **Ehrlichkeit.** 404 statt stillem Nachladen heißt: die UI kann „noch nicht
   gespiegelt" *anzeigen* und einen Sync anbieten, statt einen langsamen
   PDB-Call hinter einem Bildplatzhalter zu verstecken (Docstring
   `component_attachment_binary` in `api.py`).

Als direkte Folge enthält das öffentliche Read-Model
(`attachment_read_model`) **weder den Speicherpfad noch irgendeine
Quell-URL** – damit kann ein Share-Link (oder künftig eine signierte URL)
nicht versehentlich über eine Antwort nach außen tropfen. Der harmlose
Quellen-**Marker** `source` ist dagegen Teil der oeffentlichen Blob-Identitaet
und wird zusammen mit `code` ausgeliefert.

### 4.1 Falle: zwei Attachment-Wurzeln

Weil `attachment_dir` ausgeliefert nicht gesetzt ist, entscheidet das
Arbeitsverzeichnis des Serverprozesses, wo der Spiegel liegt. In der
Arbeitskopie existieren deshalb heute **zwei** Wurzeln:

| Wurzel | Dateien (2026-08-26) | entstanden beim Start aus |
|---|---|---|
| `C:\Users\nukei\Desktop\itk_webapp\attachments\` | 3734 | Repo-Wurzel |
| `C:\Users\nukei\Desktop\itk_webapp\backend\attachments\` | 352 | `backend/` |

Beide gehören zu **derselben** Datenbank-Indextabelle. Läuft der Server aus
`backend/`, während die Bilder in der Repo-Wurzel liegen, liefert
`resolve_path()` für jede Zeile `None` → `stored: false` → **die Galerie ist
leer, obwohl 3734 Dateien vorhanden sind**. Das ist der billigste denkbare
Weg, „ich sehe keine Bilder" zu erzeugen, und er hinterlässt keine
Fehlermeldung. Empfehlung: `ITKFLOW_ATTACHMENT_DIR` explizit auf einen
absoluten Pfad setzen (analog zum DB-Pin in der Dev-Umgebung).

### 4.2 Ausnahme: zwei Live-Endpunkte, die die UI nicht benutzt

`api.py` hat zusätzlich `GET /api/components/{sn}/images` und
`GET /api/components/{sn}/images/{attachment_id}`. Diese beiden gehen über
`app/pdb_attachments.py` **direkt und live** an die PDB. Sie sind der
Vorgänger des Spiegels.

Verifiziert: `frontend/src/api.ts` enthält **keinen** Client für diese Routen;
die Komponenten-Detailseite lädt ihre Bilder über
`getComponentAttachments()` + `componentAttachmentUrl()`. Die Routen sind also
aus Produktsicht tot, existieren aber weiter in der API. Ob sie entfernt
werden sollen, ist *offen* und gehört in `docs/02-revamp-plan.md`, nicht
hierher.

## 5. Wo Bilder in der UI auftauchen — und wo nicht

Stand `frontend/src/screens/ComponentsScreen.tsx`, `frontend/src/TestResults.tsx`,
`frontend/src/ModuleWorksheet.tsx`, `frontend/src/ImageLightbox.tsx` (2026-08-26).

### 5.1 Bildergalerie auf der Komponentendetailseite

- Abschnitt **„Metrology & inspection images"** (`ImagesSection`), gerendert
  **immer** und **außerhalb** jedes eingeklappten Bereichs, ganz unten auf der
  Detailseite.
- Quelle: `GET /api/components/{sn}/attachments`. Die Antwortform hat sich in
  der aktuellen Arbeitskopie geändert (`schemas.ComponentAttachmentsOut`):
  statt einer flachen Liste liefert die Route jetzt
  `{component_sn, attachments, children}` — `attachments` ist weiter der
  **gesamte** lokale Attachment-Index der Komponente selbst, unabhängig vom
  Testlauf; `children` gruppiert zusätzlich die **Bild**-Attachments jedes
  verbauten Teils (z. B. Sensor/Hybrid eines Moduls), je Teil mit
  `sn`, `component_type`, `type_code` und `local_name`
  (`attachment_store.child_image_attachments`, ein konstanter Query-Satz für
  die ganze Familie statt N+1, nur Zeilen mit `relative_path` und
  `is_image`). Motivation
  laut Docstring: auf dem Owner-Spiegel liegen nur 3 von 432 Bildern auf einem
  Modul selbst, 241 auf direkten Sensor-Kindern — nach Seriennummer allein
  gefiltert waren diese für eine Modulseite unerreichbar.
- **Zwei Hops, aber nur durch den Stitch (2026-08-28):** Ein Hop reicht für ein
  ungestitchtes Modul. R3–R5-Module sind jedoch gestitcht: das direkte Kind des
  Vollmoduls ist ein **Halbmodul** (`component_type == "MODULE"`), und Sensoren,
  Powerboard und Hybrid-Assemblies mit den Fotos hängen an diesem Halbmodul.
  Bei einem Hop blieben auf dem Owner-Spiegel **22 Modulseiten leer**, obwohl
  ihre Bilder eine Ebene tiefer existierten (Pfad ausnahmslos
  `MODULE > MODULE > SENSOR|PWB|HYBRID_ASSEMBLY`, 67 Bild-Referenzen). Der Walk
  nimmt deshalb einen zweiten Hop — **ausschliesslich durch ein Kind, das
  selbst ein Modul ist**, nie durch die Kinder eines Sensors oder Powerboards.
  Damit steigt die Zahl der Modulseiten mit mindestens einem Bild von 176 auf
  198 (von 265), und der Query-Satz bleibt konstant (eine zusätzliche
  Kind-Abfrage für die ganze Familie). Dieselbe Auswahl benutzt die
  Evidenz-Gruppe des Worksheets (`preview._child_evidence_groups`), sonst
  zeigte eine gestitchte Modulseite die **Fotos** eines Sensors, seine
  **Messungen** aber nicht; dort waren 114 Evidenz-Teile auf 23 Modulen
  verdeckt. Gemeinsame Regel: `attachment_store.assembled_parts`.
- **Listen-Kachel leiht und markiert (2026-08-28):** `GET
  /api/components/thumbnails` blieb auf fast jeder Modulzeile leer — 3 von 432
  Bildern liegen auf einem Modul. Eine Komponente ohne eigenes Bild leiht jetzt
  eines von einem verbauten Teil (`assembled_parts`, also inklusive Stitch).
  Der Locator traegt dafuer zwei zusaetzliche Felder: `sn` ist die Komponente,
  unter deren Seriennummer die Bytes liegen (die Binary-Route mit der
  gelisteten Komponente aufzurufen ergaebe 404), `part` nennt Seriennummer,
  Typ und lokalen Namen des Teils und ist genau dann gesetzt, wenn geliehen
  wurde. Der Client **muss** eine geliehene Kachel markieren: das Foto eines
  Sensors ist kein Bild des Moduls. Das eigene Bild gewinnt; `limit` bindet
  weiter Komponenten, und der Leih-Durchgang fuellt nur Zeilen der bereits
  begrenzten Menge, in einer festen Zahl von Statements.
- Eigene Galerie, Kind-Galerie und Binary-Route lösen die Sichtbarkeit über
  `test_run_attachment_reference.component_sn` auf. Direkt erzeugte alte
  Blob-Zeilen ohne Referenz bleiben additiv über ihr repräsentatives
  `component_sn` sichtbar. Die Galerie dedupliziert anschließend je
  `(source, code)`, damit derselbe Blob bei zwei Läufen derselben Komponente
  nur eine Kachel erzeugt.
- Die Binary-URL enthält Komponente und Code sowie `source` als Queryparameter,
  aber keinen Lauf. Damit bleiben gleiche Codes aus verschiedenen Quellen
  getrennt adressierbar. Trägt derselbe Blob auf einer Komponente je Lauf
  unterschiedliche Anzeige-Dateinamen, nimmt der `Content-Disposition`-Header
  deterministisch die erste Association; Bytes, Content-Type und
  Zugriffsprüfung bleiben identisch. Der Legacy-Aufruf ohne `source` bleibt
  fuer bestehende Bookmarks erhalten.
- Filter (serverseitig für `children`, clientseitig für `attachments`):
  `stored && is_image`. Alles andere (Instrumentdaten, PDFs, nicht geladene
  Dateien) erscheint hier **gar nicht**.
- Leerzustand: „No locally mirrored images yet. Run the institute sync or
  refresh this component's test evidence."
- Klick öffnet die Lightbox (`ImageLightbox`), die dieselbe lokale URL
  benutzt.
- Frontend-Seite verifiziert (2026-08-27): `frontend/src/api.ts`
  (`getComponentAttachments`, Typ `ComponentAttachments`) und `ImagesSection`
  in `ComponentsScreen.tsx` sind bereits auf `{component_sn, attachments,
  children}` verdrahtet — `family.attachments` für die eigene Galerie,
  `family.children` für die Kind-Gruppen. Eigener Contract-Test
  `ComponentsScreen.gallery.test.tsx` deckt beide Fälle ab; `tsc --noEmit` und
  die Test-Suite sind grün.

**Das ist der wichtigste Punkt für die aktuelle Frage:** die Galerie hängt
**nicht** hinter „All mirrored runs". Sind Bilder für eine Komponente
gespiegelt, müssen sie hier ohne jeden Klick sichtbar sein — sobald die
Frontend-Seite der Antwort wieder zur Route passt, gilt das auch für
Kind-Bilder.

### 5.2 Bilder pro Testlauf

- `RunAttachments` (in `TestResults.tsx`) rendert je Lauf die Attachments:
  `stored && is_image` als Vorschaubild, alles andere als Platzhalter mit
  Dateiname oder „Not downloaded yet".
- Die Zuordnung Lauf → Attachment läuft über
  `TestRunAttachmentReference.(test_type, test_run_ref)` gegen
  `TestRunEvidence.(test_type, external_ref)`
  (`api._attachment_rows_by_run`). Der Testtyp gehört zum Schlüssel, weil
  Custom-/Legacy-Evidence auch ohne Laufreferenz vorkommen darf; zwei solche
  Tests dürfen ihre Anhänge nicht gegenseitig erben. Eine Legacy-Blob-Zeile
  ohne Referenz bleibt über dieselben Felder lesbar.
- Worksheet und Child-Worksheet liefern weiterhin nur
  `attachment_count`, zählen jetzt aber denselben Association-Index — getrennt
  nach Komponente, Testtyp und Lauf. Der physisch einmal vorhandene Blob zählt
  daher in jedem Lauf, der ihn tatsächlich referenziert, genau einmal.
- Diese Karten liegen an zwei Stellen, und beide brauchen seit dem
  Worksheet-Umbau (Spec §H) **einen Klick**:
  1. **Worksheet-Zeile aufklappen** — `ModuleWorksheet` lädt
     `GET /api/components/{sn}/tests` erst, wenn eine Zeile expandiert oder
     der Edit-Strip geöffnet wird (`runsRequested`), und rendert dort
     `RunAttachments`.
  2. **„All mirrored runs"** — der frühere Volllauf-Bereich liegt seit dem
     Worksheet-Umbau in einem eingeklappten `<details>`
     (`MirroredRunsSection`); der Inhalt wird erst beim ersten Öffnen geladen.
- Der Umbau war Absicht (>100 Läufe waren als Zahlenwand unlesbar, docs/04),
  hat aber als Nebeneffekt genau diese Vorschaubilder hinter eine
  Nutzeraktion geschoben. Der zugehörige Commit `07a59d9` ist per
  Tag-Nachfahrprüfung in `v0.2.2-alpha` enthalten; damit gilt das Verhalten ab
  Desktop-Bundle 0.2.2. `desktop/package.json` traegt die Bundle-Version und
  wird mit jedem Release gemeinsam mit den Tauri-Metadaten angehoben.

### 5.3 Thumbnails in Listen

- `GET /api/components/thumbnails` liefert eine Abbildung
  Seriennummer → **ein** Attachment-Locator `{source, code}`. Aufgenommen wird nur, was
  `relative_path is not None`, einen vom Browser darstellbaren Content-Type
  und `resolve_path() != None` erfüllt; unter diesen Kandidaten gewinnt der
  Blob mit der kleinsten `id` je Seriennummer. Die Allowlist entspricht
  `frontend/src/ui.ts`: JPEG/JPG, PNG, GIF, WebP, BMP, AVIF und SVG. Wie im
  Frontend wird der Basistyp vor dem ersten `;` abgetrennt, getrimmt und
  kleingeschrieben; fuehrende Leerzeichen und Leerraum vor MIME-Parametern
  koennen ein browserfaehiges Bild deshalb nicht aus der Liste verstecken.
- **`limit` begrenzt seit 2026-08-27 Komponenten, nicht Attachment-Zeilen**
  (1..5000, Default 2000). `thumbnail_attachments` vereinigt im SQL die
  Association-Kandidaten mit dem Legacy-Fallback, gruppiert dann nach
  Seriennummer und wendet erst danach das Komponentenlimit an. Wiederholte
  Lauf-Referenzen werden dadurch nicht vor dem Limit in Python materialisiert.
  Der Filter ist bewusst enger als `is_image_sql()`: Ein älteres TIFF wird vor
  `MIN(id)` ausgeschlossen, sodass eine spätere JPEG-/PNG-Vorschau gewinnt;
  eine TIFF-only-Komponente liefert keine kaputte Listenkachel. In der Galerie
  bleibt dasselbe TIFF dagegen als gespeicherter, nicht darstellbarer
  Platzhalter sichtbar.
- **Warum das ein Fehler war:** 3734 der 3772 Zeilen des Live-Spiegels haben
  eine Datei, und 2671 davon sind Instrument-`.txt`. Die ersten 2000 **Zeilen**
  (nach `component_sn, id`) erreichten nur **460 von 759** Seriennummern und
  ergaben **83** Kacheln, obwohl **279** Komponenten ein gespiegeltes Bild
  haben. Nach der Korrektur: **279**. (Gemessen am Live-Spiegel, nur lesend,
  mit demselben Statement, das der Endpunkt baut.)
- **`UNION ALL` + `GROUP BY`/`MIN(id)` statt Fensterfunktion:** identische
  Auswahlsemantik über neue Referenzen und alte repräsentative Zeilen, aber
  ohne Abhängigkeit von SQLite ≥ 3.25.
- Preis der strengen Ein-Zeile-Regel: fehlt **dieser** Datei die Platte, bleibt
  die Komponente diesmal ohne Kachel, auch wenn ein zweites Bild dort läge.
  Am Live-Spiegel trifft das auf **keine** der 279 Komponenten zu.
- Verwendet in der Komponentenliste (`ComponentsScreen`) und in den
  Gruppenköpfen des `Staged`-Screens. `frontend/src/api.ts` übergibt bewusst
  **kein** Limit: der Default deckt jede gespiegelte Komponente ab, seit er
  Komponenten zählt.
- Der Aufruf ist bewusst „best effort": schlägt er fehl, bleibt die Liste
  unverändert, nur ohne Bilder.

### 5.4 Wo Bilder **nicht** auftauchen

- Nicht in Staged-/Ghost-Einträgen als Messwert — Ghost-Tests zeigen ihre
  Ingest-Evidenz, aber keine PDB-Attachments, die es noch nicht gibt.
- Nicht im Worksheet-Gitter selbst (nur in der aufgeklappten Zeile).
- Nicht als Datei oder vollständiger Lauf in der Preview-Payload:
  `GET /api/components/{sn}/preview` trägt seit dem Review-Nachzug keine
  gespiegelten Läufe mehr (docs/04), wohl aber den association-basierten
  `attachment_count` der jeweils neuesten Worksheet-Läufe.
- Nicht in Exporten/Statistiken.

## 5b. `is_image` beantwortet nicht die Frage der Anzeige (2026-08-27)

`TestRunAttachment.is_image` leitet sich aus dem `content_type` ab und
beantwortet „ist das ein Bild?“. Die Galerie braucht aber die andere Frage:
**„malt ein Browser das?“** Beides fällt auseinander, sobald ein Format im
Spiegel liegt, das Chromium nicht dekodiert.

Konkret: der Spiegel hält zwei 36-MB-TIFFs aus einer Sichtprüfung
(`20USEH40000134`). Die Content-Type-Reparatur schreibt dort wahrheitsgemäß
`image/tiff` zurück — womit `is_image` wahr wird und die WebView2-Shell des
Desktop-Bundles zwei dauerhaft kaputte Kacheln zeigt. Ein behobener Fehler
hätte also einen neuen ausgeliefert, und die nächste Meldung wäre zu Recht
„die Bilder sind wieder kaputt“ gewesen.

Deshalb prüfen beide Renderer (`ImagesSection` in `ComponentsScreen.tsx` und
die Lauf-Thumbnails in `TestResults.tsx`) zusätzlich `isDisplayableImage()`
aus `frontend/src/ui.ts` — eine Allowlist der Formate, auf die sich Browser
einig sind (jpeg, png, gif, webp, bmp, avif, svg). Fällt ein Anhang durch,
zeigen **beide** Renderer Dateiname und den expliziten Produkttext
`Stored locally · preview unavailable`: ehrlich darüber, dass die Datei da und
abrufbar ist, nur nicht inline zeigbar.

**Der `content_type` bleibt dabei wahr.** Ein TIFF ist ein TIFF; der Typ wird
nicht zurückgehalten, um einen Anzeigefehler verschwinden zu lassen. Wer die
Allowlist erweitert, ändert nur die Anzeige, nie die Daten.

Die Thumbnail-Auswahl schließt TIFF bereits **vor** `MIN(id)` aus: ein späteres
JPEG/PNG gewinnt deshalb gegen ein älteres TIFF, und eine TIFF-only-Komponente
liefert keine kaputte Listenkachel. Galerie und Laufkarte behalten das TIFF
als gespeicherten, nicht inline darstellbaren Platzhalter.

## 6. Fehlersuche: „Ich sehe keine Bilder"

In dieser Reihenfolge abarbeiten — jeder Schritt ist ohne Codelektüre
prüfbar. Der erste Schritt, der scheitert, ist die Ursache.

1. **Ist überhaupt Evidence gespiegelt?**
   Detailseite öffnen: steht dort „No test results mirrored yet." bzw. sind
   die Pflichttests alle `missing`? Dann gibt es noch keine
   Attachment-Metadaten, und ein Attachment-Download kann gar nichts finden.
   → „Refresh test evidence" für die Komponente bzw. Institutssync laufen
   lassen. Achtung: der **flache** Sweep ohne Detail erzeugt keine
   Attachment-Deskriptoren.

2. **Hat der Sync Attachments gemeldet?**
   Der Abschluss eines Sync-Jobs nennt `attachments_downloaded / reused /
   failed / total`. Ist `total = 0`, hat diese Komponente laut PDB keine
   Attachments — dann ist nichts kaputt, es gibt schlicht keine Bilder.
   Ist `failed` hoch, siehe Schritt 5.

3. **Liegt die Datei auf der Platte — und im richtigen Ordner?**
   Attachment-Ordner öffnen, Unterordner mit der Seriennummer suchen.
   - Kein Unterordner, obwohl Schritt 2 Downloads meldete → sehr
     wahrscheinlich die Zwei-Wurzeln-Falle aus 4.1. Prüfen, aus welchem
     Verzeichnis der Server gestartet wurde, und ob es einen **zweiten**
     `attachments`-Ordner gibt.
   - `.part`-Dateien im Ordner → ein Prozess wurde hart während des Stagings
     beendet. Der nächste Sync holt die eigentliche Datei nach, ignoriert den
     eindeutig benannten alten Rest aber, bis eine sichere Altersbereinigung
     existiert; er überschreibt oder löscht keine Datei unbekannten Owners.

4. **Ist die Datei ein Bild — im Sinne der App?**
   In der Laufkarte steht „Not downloaded yet" oder es erscheint ein
   Platzhalter mit Dateinamen: dann kennt die App die Datei, hält sie aber
   nicht für ein Bild oder nicht für gespeichert. Dateiendungen im Ordner
   ansehen: `.txt`, `.dat`, `.json` sind Instrumentdaten, **keine Bilder** —
   die zeigt die Galerie nie an. Das ist kein Fehler.

5. **Standen im Log Attachment-Warnungen?**
   - „only served HTML pages; the share may be expired or require sign-in" →
     Share-Link tot (Abschnitt 2.3). Die Datei ist beim Anbieter weg oder
     verlangt Login; itkFlow kann daran nichts reparieren.
   - Viele transiente Fehler / abgebrochene Attachment-Phase → Netz war weg;
     einfach erneut synchronisieren, der nächste Sweep holt alles nach
     (ein Fehlschlag wird nie als „gespeichert" vermerkt).

6. **Ist der Abschnitt zugeklappt?**
   Bilder **pro Testlauf** stehen entweder in einer aufgeklappten
   Worksheet-Zeile oder unter **„All mirrored runs"** — beides muss man
   anklicken (Abschnitt 5.2). Die **Galerie** „Metrology & inspection images"
   ganz unten auf der Detailseite ist dagegen immer sichtbar. Wenn dort
   Bilder stehen und in den Laufkarten keine, ist alles in Ordnung, nur
   zugeklappt.

7. **Erwartet die Komponente überhaupt Bilder?**
   Bei TUDO sind Modul-Attachments fast ausschließlich Instrument-Rohdaten
   (`.txt`), keine Fotos — siehe Abschnitt 8. Wer Fotos sucht, findet sie
   eher an Sensoren und Hybriden.

## 7. Konfiguration in Kürze

| Setting / Env | Default | Wirkung |
|---|---|---|
| `attachment_dir` / `ITKFLOW_ATTACHMENT_DIR` | leer → `attachments/` relativ zum Arbeitsverzeichnis | Wurzel des Spiegels |
| `attachment_max_bytes` | 100 MiB | Obergrenze je Datei |
| `attachment_download_timeout_seconds` | 60 | Timeout je Abruf |
| `sync_page_max_attempts` | 3 | geteiltes Retry-Budget für transiente Downloadfehler |
| `evidence_component_types` (Institutsprofil) | 10 Typen, siehe 3.5 | welche Komponententypen der Sweep überhaupt mit Detail spiegelt |

## 8. Messung an der Arbeitskopie (2026-08-26)

Rein deskriptiv, per Dateisystem-Glob erhoben (kein PDB-Zugriff), zur
Kalibrierung der Erwartung:

- Wurzel `…/itk_webapp/attachments/`: **3734** Dateien — davon **2671**
  `.txt` (Instrument-Rohdaten), **432** Bilddateien (`.jpg`/`.png`/`.tif`),
  2 `.pdf`, Rest sonstige Datenformate. Diese Zahl deckt sich exakt mit den
  vom Owner berichteten „3734 Dateien".
- Wurzel `…/itk_webapp/backend/attachments/`: **352** Dateien — davon 349
  `.txt`, **1** `.jpg`, 1 `.dat`, 1 `.pdf`.
- Bilder verteilen sich fast vollständig auf **Sensoren** (`20USES…`) und
  **Hybride** (`20USEH…`); Module (`20USEM…`) tragen in der Arbeitskopie nur
  eine Handvoll Bilder. Das passt zur Live-Validierung aus Spec §F: die
  TUDO-Modul-Testläufe tragen Rohdatendateien (IV, Metrologie, Bow), keine
  Fotos.
- Mindestens eine gespiegelte Datei trägt einen 64-stelligen Hex-Namen
  (`…/20USE5R0000156/<64 hex>.jpg`), also einen SHA-256-Code — **der
  Share-Link-Pfad funktioniert nachweislich in der Praxis**.
- Keine `.part`-Reste gefunden; die letzten Downloads sind sauber
  abgeschlossen.

### 8.1 Live-Spiegel des Owners (2026-08-27, nur lesend gemessen)

Die Zahlen oben stammen aus dem **Dateisystem** der Arbeitskopie. Die App
liest jedoch `%LOCALAPPDATA%\itkflow\itkflow.db`; dort gemessen
(`file:…?mode=ro`, kein Schreibzugriff, kein PDB-Kontakt):

| Größe | Wert |
|---|---:|
| Attachment-Indexzeilen | 3772 |
| davon mit Datei (`relative_path`) | 3734 |
| Bilddateien (per Magic Bytes bestätigt) | 432 |
| Seriennummern mit mindestens einem Bild | 279 |
| Bildquelle EOS / CERNBox-Share / PDB-Binary | 422 / 8 / 2 |
| Bilder auf `MODULE`-Komponenten | 3 |
| Bilder auf direkten Kindern eines Moduls | 241 (auf 159 Kindern, 156 Modulen) |
| Bild-Seriennummern ohne Elternteil (noch nicht verbaut) | 120 |
| Share-Link-URLs gesamt / davon Weboberflächen-Form / privat | 29 / 20 / 1 |
| Deskriptoren hinter der einen Ordner-Freigabe | 87 auf 76 Komponenten, 20 Codes, **1 Token** |
| Davon vor 2026-08-27 gespeichert | 0 |
| Share-Link-Blobzeilen / darin repräsentierte Komponenten | 29 / 26 |
| Share-Link-Deskriptor-Zuordnungen im Evidence-Mirror | 96 auf 83 Komponenten |
| Bereits gespeicherte Share-Codes → reale Zuordnungen | 16 Blobs → 52 Zuordnungen auf 39 Komponenten |

Die Zeilen zu EOS und Kindbauteilen erklären den Unterschied zwischen „432
Bilder liegen im Spiegel" und „ein Modul zeigt sie": 422 der 432 kommen über
EOS, fast alle auf Sensoren, und **kein** Modul kam vor 2026-08-27 an sie
heran.

Die drei neuen Association-Zeilen messen einen anderen, inzwischen behobenen
Fehler: `(source, code)` ist der richtige Schlüssel für Bytes, aber der falsche
Schlüssel für Sichtbarkeit. Vor der Referenztabelle konnte jede Blobzeile nur
eine `component_sn` halten, und ein späterer Reuse überschrieb zusätzlich ihre
`test_run_ref`. Damit standen 52 reale Zuordnungen der bereits gespeicherten
Share-Blobs nur 16 physischen Zeilen gegenüber; Galerie, Binary-Route und
Laufkarten konnten die übrigen Zuordnungen nicht mehr erreichen.

Diese Zahlen ändern sich mit jedem Sync. Sie sind ein Datenpunkt, keine
Zusicherung.

## 9. Offene Punkte

- **Verifiziert (2026-08-27, ersetzt „nicht verifiziert"):** der EOS-Pfad
  trägt im Live-Spiegel 425 Deskriptoren und 422 der 432 Bilder (Abschnitt 2.2
  und 8.1). Nicht geprüft bleibt allein das Verhalten einer **abgelaufenen**
  Signatur — dafür müsste man eine URL absichtlich altern lassen.
- **Nicht verifiziert:** ob die Share-Link-Erkennung alle zFlow-Feldformen der
  Fremdinstitute abdeckt; erkannt wird an der Wertform, geprüft wurde bisher
  nur gegen `URLSCRATCHPAD`/`URLS1..6` aus der Referenz.
- **Verifiziert (2026-08-27, ersetzt „Nicht verifiziert (Netzwerk)"):** die
  DAV-Route der 20 Weboberflächen-Links liefert **keine** Bytes, sondern
  **501 Not Implemented** — CERNBox ist dafür ohne VPN und ohne Zugangsdaten
  anonym erreichbar, die Messung steht in Abschnitt 2.3a. Die Bytes kommen
  über `/s/<token>/download?files=<Eintrag>` als Tar; die Auswahl ist mit dem
  echten Code gegen das echte Archiv nachgemessen.
- **Nicht verifiziert:** die Archiv-Route für einen **verschachtelten** Pfad
  in der Freigabe (`?files=a/b/c.jpg`). Im Spiegel gibt es keinen solchen
  Link, und das Raten einer fremden Pfadangabe ist kein zulässiger Test. Die
  Kodierung ist an der URL-Form getestet.
- **Bekannt und akzeptiert:** der Erstabruf der 20 Ordner-Zeilen kostet
  einmalig rund 1,5 GB, weil `?files=` den **ganzen** Unterordner packt
  (79 MB für ein 8,8-MB-Bild). Ein Weg, nur die eine Datei anzufordern, würde
  eine Auflistung der Freigabe voraussetzen — und die ist genau das, was die
  DAV-Route mit 501 verweigert. Danach ist es gratis: der natürliche
  **Blob-Schlüssel** `(source, code)` lässt jede weitere Komponente die bereits
  gespiegelte Datei wiederverwenden; ihre eigene
  `test_run_attachment_reference` hält die Sichtbarkeit fest.
- **Bewusst kein Cache.** Ein Archiv wird nie im Speicher gehalten. 87
  Deskriptoren fallen über `(source, code)` auf 20 Abrufe zusammen, und jeder
  Code steht für einen **eigenen** Unterordner — ein LRU-Cache über
  80-MB-Archive würde also hunderte MB kosten und **null** Abrufe sparen.
  Gemerkt wird nur, was ein Verdikt ist: `OutageCircuitBreaker`
  merkt sich pro Sweep die `(source, code)`-Schlüssel mit **endgültigem**
  Fehlschlag (gedeckelt auf 4096 Einträge, ohne Bytes), damit dieselbe
  abgelehnte Freigabe nicht einmal je referenzierender Komponente — im
  Spiegel bis zu neunmal — neu geholt wird. Transiente Fehlschläge werden
  nie gemerkt, und nichts davon überlebt den Sweep: ein dauerhaftes Flag in
  der Datenbank hätte genau die 20 Zeilen eingefroren, die dieser Schnitt
  repariert.
- **Unerreichbar, bewusst nicht repariert:** eine Zeile (`20USES50000771`)
  zeigt auf einen persönlichen CERNBox-Bereich statt auf eine Freigabe. Sie
  wird ohne Request abgelehnt (Abschnitt 2.3); reparierbar wäre sie nur, indem
  jemand die Datei als öffentlichen Share neu verlinkt.
- **Verifiziert:** der Worksheet-Umbau aus `07a59d9`, der die Laufansicht
  hinter „All mirrored runs" verschoben hat, ist in `v0.2.2-alpha` enthalten.
- **Offen:** ob der Fall „Datei gespeichert, aber `content_type` leer →
  unsichtbar" real vorkommt (Abschnitt 3.3).
- **Erledigt/entkräftet (2026-08-27):** ein zuvor hier vermerkter Verdacht auf
  Backend/Frontend-Bruch bei `GET /api/components/{sn}/attachments`
  (`{component_sn, attachments, children}` vs. alte Listenform) hat sich bei
  Gegenprüfung als bereits behoben erwiesen — `frontend/src/api.ts` und
  `ImagesSection` sind auf die neue Form verdrahtet (Abschnitt 5.1).
- **Erledigt (2026-08-27):** Blob- und Association-Identität sind getrennt.
  Der SQLite-Backfill rekonstruiert vorhandene Referenzen rein lokal aus
  Blobzeilen und Evidence-Payloads; ein idempotenter Re-Sync lädt denselben
  Share genau einmal, hält ihn aber auf allen Komponenten und Läufen sichtbar.
- **Offen:** Zukunft der beiden Live-`/images`-Endpunkte (Abschnitt 4.2).
- **Erledigt (2026-08-28):** Gleichzeitige direkte und Background-Syncs eines
  geteilten Attachment-Codes teilen innerhalb eines Prozesses die Blob-Key-
  Sperre. Zwischen Prozessen besitzt jeder Fetch eine eigene exklusiv erzeugte
  `.part`-Datei; Fence-Verlust und Cleanup eines alten Workers können deshalb
  die Staging-Datei des Nachfolgers nicht mehr überschreiben oder löschen.
  `force` bleibt pro Aufruf dedupliziert und darf danach semantisch neu laden.
- **Offen:** Aufräumen verwaister alter `.part`-Dateien und Attachments, die aus
  der PDB verschwunden sind.
- **Erledigt (2026-08-27):** die Doc-Map-Zeile für dieses Dokument steht jetzt
  in `docs/00-doc-map.md`, zusammen mit der für
  [`13-metrology-artifacts.md`](13-metrology-artifacts.md).

## 10. Quellen

Code (Stand 2026-08-27, Arbeitskopie):

- `backend/app/attachment_store.py` — Download-, Prüf- und Ablagepipeline
  (drei Phasen, Retry, Breaker, Share-Link-Kandidaten, EOS-Refresh, seit
  2026-08-27 auch `_CappedStream`, `_archive_stream_mode`,
  `safe_archive_member_name`, `_member_is_in_scope`, `_member_rank`,
  `_archive_member`/`_walk_archive` und der Sweep-Merker
  `OutageCircuitBreaker.note_permanent_miss`)
- `backend/app/pdb_test_evidence.py` — `_attachment_summaries`,
  `_share_link_summaries`, `_http_urls`, `_run_detail_payload`
- `backend/app/pdb_attachments.py` — der ungenutzte Direktweg
- `backend/app/api.py` — `component_thumbnails`, `component_test_details`,
  `component_attachments`, `component_attachments_sync`,
  `component_attachment_binary`, `component_images*`
- `backend/app/models.py` — `TestRunAttachment` (Blob),
  `TestRunAttachmentReference` (Association), `is_image`
- `backend/app/db.py` — einmaliger SQLite-Backfill der Associations aus
  Blobzeilen und Evidence-Payloads
- `backend/app/config.py`, `backend/app/sync_jobs.py`
- `frontend/src/screens/ComponentsScreen.tsx` (`ImagesSection`,
  `MirroredRunsSection`), `frontend/src/TestResults.tsx` (`RunAttachments`),
  `frontend/src/ModuleWorksheet.tsx`, `frontend/src/ImageLightbox.tsx`,
  `frontend/src/api.ts`, `frontend/src/i18n.ts`

Entscheidungen und Vorgeschichte:

- `docs/adr/006-staged-first-ui-auto-mirror.md`, Punkt 6 und Konsequenzen
- `docs/superpowers/specs/2026-08-25-staged-first-module-page-design.md`,
  Abschnitt „Empirische Grundlage" und §F „Auto-Mirror", Nachtrag §H
- `docs/09-pdb-production-strategy.md` (Attachment-Phase, Retry-Budget,
  Sicherheitsmodell), `docs/04-roadmap.md` („Aktueller Stand")
- `references/zeuthenflow/modules/processVisualInspection.py` —
  **nur gelesen**, nie ausgeführt oder importiert (CLAUDE.md, harte Regel 1):
  `find_images()` ~Z. 399-402, `printJson()` ~Z. 759-778, URL-Feldschema
  ~Z. 55-60 und ~Z. 92.

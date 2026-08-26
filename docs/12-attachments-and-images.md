# Attachments und Bilder: Speicherwege, lokaler Spiegel, Fehlersuche

> Warum es dieses Dokument gibt: „Warum sehe ich keine Bilder?" wurde mehrfach
> gestellt und jedes Mal von vorne untersucht. ITk-Bilder liegen in **drei**
> verschiedenen Speichersystemen, und itkFlow zeigt sie **nur** aus dem lokalen
> Spiegel an. Diese beiden Sätze zusammen erklären fast jeden Befund. Der Rest
> dieses Dokuments macht sie nachvollziehbar.
>
> Stand: 2026-08-26, Arbeitskopie auf Branch `feat/real-data-sync-stats-tooling`.
> `backend/app/attachment_store.py` wird parallel in einer anderen Session
> bearbeitet; dokumentiert ist der Stand **mit** Drei-Phasen-Split
> (plan/fetch/commit), `.part`-Staging und `OutageCircuitBreaker`. Wenn diese
> drei Bausteine im Code fehlen oder anders heißen, ist dieses Dokument älter
> als der Code.
>
> Zuständigkeit laut `docs/00-doc-map.md`: dieses Dokument (Zeile ist noch
> nachzutragen, siehe Abschnitt 9).

## 1. Kurzfassung

1. Ein Attachment kommt aus einer von drei Quellen: **PDB-Binary-Store**,
   **EOS**, oder **öffentlicher Share-Link in einem Result-Feld**. Welche es
   ist, steht im gespiegelten Evidence-Payload (`type` / `source`).
2. Der Sync lädt die Bytes in einen **lokalen Ordner** (`attachment_dir`), ein
   Unterverzeichnis je Seriennummer. Die Datenbankzeile ist nur der Index.
3. Die UI rendert Bilder **ausschließlich** aus diesem Ordner. Kein Bild wird
   beim Öffnen eines Screens aus der PDB oder von EOS geholt.
4. Damit ein Bild sichtbar wird, müssen **vier** Dinge stimmen: Evidence
   gespiegelt → Attachment heruntergeladen → Datei liegt im *richtigen* Ordner
   → `content_type` beginnt mit `image/`. Fällt eines aus, ist die Kachel weg,
   ohne dass irgendwo eine Fehlermeldung steht.
5. Häufigster praktischer Befund in der Entwicklungsumgebung: es gibt **zwei**
   Attachment-Wurzeln, weil `attachment_dir` unkonfiguriert relativ zum
   Arbeitsverzeichnis des Serverprozesses aufgelöst wird (Abschnitt 4.1).

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
- **Praxisstand:** Bei TUDO existieren **keine** EOS-Attachments (Spec §F:
  alle 360 gescannten Attachments waren Binary-Store). Der Mechanismus ist
  über die itkdb-Dokumentation belegt und im Code implementiert, aber gegen
  echte EOS-Daten **nicht** verifiziert — *offen*.

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
- **Sicherheitsrahmen (ADR 006, Punkt 6):** Der Abruf läuft **ohne jede
  Authentifizierung** über `urllib` mit eigenem Opener — es werden nie
  PDB-Credentials an einen fremden Host geschickt. `_safe_http_url` lehnt
  URLs mit Benutzer/Passwort, `localhost` und nicht-globale IP-Adressen ab;
  `_SafeShareRedirects` prüft **jede** Weiterleitung erneut, bevor urllib ihr
  folgt; die finale URL nach Redirects wird nochmals geprüft.
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
- **Wie es sich für den Nutzer anfühlt:** identisch zu 2.1 — Kachel fehlt oder
  zeigt „Not downloaded yet". Der Unterschied ist nur im Log sichtbar.
- **Historischer Nebenbefund:** Bis 2026-08-26 wurden diese Bilder **nie**
  gespiegelt, weil der Mirror die Betrachterseite angefragt hat und die
  HTML-Abwehr korrekt zugeschlagen hat (docs/04, „Sync ueberlebt kurze
  Internet-Ausfaelle"). Der Fix war der Kandidatenweg oben.

### 2.4 Vergleich auf einen Blick

| | Binary-Store | EOS | Share-Link |
|---|---|---|---|
| Marker im Deskriptor | `type: "file"`, `source: "pdb"` | `type: "eos"` | `source: "share_link"` |
| `code` | PDB-Handle (Hex) | PDB-Handle (Hex) | SHA-256 der URL (64 Hex) |
| Braucht `test_run_ref` | für den guten Weg ja | zwingend | nein |
| Authentifizierung | persönliche PDB-Codes | persönliche PDB-Codes | keine |
| URL dauerhaft speicherbar | entfällt | **nein** (Signatur) | ja (aber nie im Read-Model) |
| Typischer Fehlerfall | HTML-Seite statt Datei | abgelaufene Signatur | HTML-Betrachterseite |
| Bei TUDO beobachtet | ja (alle 360) | nein | ja (siehe 8.) |

## 3. Der lokale Spiegel

### 3.1 Ablageort

```
<attachment_dir>/<seriennummer>/<code><extension>
```

- `attachment_dir` ist ein Setting (`backend/app/config.py`,
  Env `ITKFLOW_ATTACHMENT_DIR`). **Ist es nicht gesetzt — und das ist der
  ausgelieferte Default —, gilt der relative Pfad `attachments/`**, den
  `attachment_root()` mit `Path.resolve()` gegen das **Arbeitsverzeichnis des
  Serverprozesses** auflöst. Siehe die Falle in Abschnitt 4.1.
- Ein Verzeichnis je Seriennummer, damit man den Ordner öffnen und die Bilder
  mit einem beliebigen Betrachter ansehen kann. Das ist ein ausdrückliches
  Designziel (Modul-Docstring `attachment_store.py`), kein Zufall.
- Die Bytes liegen **nicht** in der Datenbank. Backups müssen deshalb
  Datenbank **und** Attachment-Ordner umfassen (ADR 006, Konsequenzen).

### 3.2 Wie eine Datei adressiert wird

- Dateiname = `pdb_code` + Extension. **Der von der PDB gelieferte Dateiname
  wandert niemals in einen Pfad** — er ist untrusted Input und wird nur zur
  Anzeige in der Datenbank gehalten.
- Seriennummer und Code werden sanitisiert: alles außer `A-Za-z0-9_-` wird zu
  `_` (`_SAFE_SN`, `_SAFE_CODE` in `storage_path()`).
- Die Extension stammt **nur** aus zwei Allowlists: der Content-Type-Tabelle
  `_EXTENSION_BY_CONTENT_TYPE` (jpg/png/gif/webp/bmp/tif/svg/pdf/json/zip/
  txt/csv) oder — wenn der Content-Type nichts hergibt — dem Suffix des
  PDB-Dateinamens, sofern dieses in `_TRUSTED_DATA_SUFFIXES`
  (`.dat .log .xml .root .tsv .md`) steht. Passt nichts, wird **ohne
  Extension** gespeichert. Nichts Ausführbares steht auf einer der Listen.
- Die Datenbankzeile `test_run_attachment` (`backend/app/models.py`) ist der
  Index: `component_sn`, `test_type`, `test_run_ref`, `source`, `pdb_code`,
  `filename`, `content_type`, `title`, `size_bytes`, `relative_path`,
  `downloaded_at`, `synced_at`. Eindeutig ist `(source, pdb_code)` — deshalb
  wird dieselbe Datei, die an zwei Testläufen hängt, nur einmal geladen.
- `relative_path` ist relativ zur Wurzel, damit ein Verschieben oder
  Wiederherstellen des Ordners nicht jede Zeile ungültig macht.
- Beim Ausliefern prüft `resolve_path()` die Containment-Bedingung **erneut**
  (`Path.is_relative_to(root)` plus `is_file()`), statt der Datenbank zu
  vertrauen: eine von Hand editierte Zeile darf nicht aus dem
  Attachment-Verzeichnis herauslesen können.

### 3.3 Wann gilt ein Attachment als Bild

Genau eine Regel, im Modell (`TestRunAttachment.is_image`):

```python
bool(self.content_type and self.content_type.startswith("image/"))
```

Woher kommt `content_type`? In `_commit_outcomes` wird zuerst der Wert aus den
PDB-Metadaten geschrieben und **bei erfolgreichem Download** durch den
tatsächlich beobachteten Typ ersetzt (`_reported_content_type` für itkdb-
Antworten, `_response_content_type` für Share-Links). Der beobachtete Typ
gewinnt bewusst, weil die Listenmetadaten der PDB oft nur `file` sagen.

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
- **Timeout.** `attachment_download_timeout_seconds`, Default 60 s.
- **Atomarer Abschluss.** Bytes gehen zuerst in eine `.part`-Datei **neben**
  dem Zielnamen (`_write_temp_bytes`), erst in der Commit-Phase folgt
  `os.replace()` (`_finalize_download`). Ein Leser kann also nie eine halb
  geschriebene Datei öffnen. Der `.part`-Name ist absichtlich deterministisch,
  damit ein durch Absturz verwaister Rest beim nächsten Versuch einfach
  überschrieben wird.
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
EOS.** Der Endpunkt `GET /api/components/{sn}/attachments/{code}` antwortet
mit der Datei von der Platte oder mit 404 — niemals mit einem stillen
Netzabruf. Die Gründe, in der Reihenfolge ihres Gewichts:

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
Quell-URL** — damit kann ein Share-Link (oder künftig eine signierte URL)
nicht versehentlich über eine Antwort nach außen tropfen.

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
- Quelle: `GET /api/components/{sn}/attachments` — der **gesamte** lokale
  Attachment-Index der Komponente, unabhängig vom Testlauf.
- Filter: `stored && is_image`. Alles andere (Instrumentdaten, PDFs, nicht
  geladene Dateien) erscheint hier **gar nicht**.
- Leerzustand: „No locally mirrored images yet. Run the institute sync or
  refresh this component's test evidence."
- Klick öffnet die Lightbox (`ImageLightbox`), die dieselbe lokale URL
  benutzt.

**Das ist der wichtigste Punkt für die aktuelle Frage:** die Galerie hängt
**nicht** hinter „All mirrored runs". Sind Bilder für eine Komponente
gespiegelt, müssen sie hier ohne jeden Klick sichtbar sein.

### 5.2 Bilder pro Testlauf

- `RunAttachments` (in `TestResults.tsx`) rendert je Lauf die Attachments:
  `stored && is_image` als Vorschaubild, alles andere als Platzhalter mit
  Dateiname oder „Not downloaded yet".
- Die Zuordnung Lauf → Attachment läuft über
  `TestRunAttachment.test_run_ref == TestRunEvidence.external_ref`
  (`api._attachment_rows_by_run`). Ein Attachment **ohne** `test_run_ref`
  erscheint deshalb in keiner Laufkarte — wohl aber in der Galerie (5.1).
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
  Nutzeraktion geschoben. Der Umbau steckt in der Desktop-Bundle-Linie
  0.2.x (`desktop/package.json` steht heute auf `0.2.3`); **welche
  Patch-Version genau die Umstellung enthält, konnte ich nicht verifizieren —
  offen.**

### 5.3 Thumbnails in Listen

- `GET /api/components/thumbnails` liefert eine Abbildung
  Seriennummer → **ein** Attachment-Code. Aufgenommen wird nur, was
  `relative_path is not None`, `is_image` und `resolve_path() != None`
  erfüllt; die erste passende Zeile je Seriennummer gewinnt
  (Sortierung nach `component_sn, id`). Limit 1..5000, Default 2000.
- Verwendet in der Komponentenliste (`ComponentsScreen`) und in den
  Gruppenköpfen des `Staged`-Screens.
- Der Aufruf ist bewusst „best effort": schlägt er fehl, bleibt die Liste
  unverändert, nur ohne Bilder.

### 5.4 Wo Bilder **nicht** auftauchen

- Nicht in Staged-/Ghost-Einträgen als Messwert — Ghost-Tests zeigen ihre
  Ingest-Evidenz, aber keine PDB-Attachments, die es noch nicht gibt.
- Nicht im Worksheet-Gitter selbst (nur in der aufgeklappten Zeile).
- Nicht in der Preview-Payload: `GET /api/components/{sn}/preview` trägt seit
  dem Review-Nachzug keine gespiegelten Läufe mehr (docs/04).
- Nicht in Exporten/Statistiken.

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
   - `.part`-Dateien im Ordner → ein Download wurde unterbrochen; nächster
     Sync holt ihn nach.

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

Diese Zahlen ändern sich mit jedem Sync. Sie sind ein Datenpunkt, keine
Zusicherung.

## 9. Offene Punkte

- **Nicht verifiziert:** EOS-Pfad gegen echte EOS-Attachments (bei TUDO nicht
  vorhanden). Code und Doku beruhen auf der itkdb-Dokumentation.
- **Nicht verifiziert:** ob die Share-Link-Erkennung alle zFlow-Feldformen der
  Fremdinstitute abdeckt; erkannt wird an der Wertform, geprüft wurde bisher
  nur gegen `URLSCRATCHPAD`/`URLS1..6` aus der Referenz.
- **Nicht verifiziert:** exakte Patch-Version (0.2.2 oder 0.2.3), mit der die
  Laufansicht hinter „All mirrored runs" gewandert ist.
- **Offen:** ob der Fall „Datei gespeichert, aber `content_type` leer →
  unsichtbar" real vorkommt (Abschnitt 3.3).
- **Offen:** Zukunft der beiden Live-`/images`-Endpunkte (Abschnitt 4.2).
- **Offen (aus docs/04 übernommen):** `.part`-Dedupe bei `force` mit geteilten
  Attachment-Codes; `.part`-Aufräumen für aus der PDB verschwundene
  Attachments.
- **Nachzutragen von der Doc-Map-Zuständigkeit:** Zeile für dieses Dokument in
  `docs/00-doc-map.md` (dieses Dokument hat sie bewusst nicht selbst gesetzt).

## 10. Quellen

Code (Stand 2026-08-26, Arbeitskopie):

- `backend/app/attachment_store.py` — Download-, Prüf- und Ablagepipeline
  (drei Phasen, Retry, Breaker, Share-Link-Kandidaten, EOS-Refresh)
- `backend/app/pdb_test_evidence.py` — `_attachment_summaries`,
  `_share_link_summaries`, `_http_urls`, `_run_detail_payload`
- `backend/app/pdb_attachments.py` — der ungenutzte Direktweg
- `backend/app/api.py` — `component_thumbnails`, `component_test_details`,
  `component_attachments`, `component_attachments_sync`,
  `component_attachment_binary`, `component_images*`
- `backend/app/models.py` — `TestRunAttachment`, `is_image`
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

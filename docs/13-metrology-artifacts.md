# Metrologie-Artefakte: Wo die „Bilder" liegen, wie sie heißen, und warum beides mehrdeutig ist

> Warum es dieses Dokument gibt: „Zeig mir das Metrologie-Bild" ist eine Bitte,
> die der Spiegel nicht erfüllen kann — und der Grund ist kein Bug, sondern die
> Ablage selbst. Ein Metrologie-Lauf trägt **eine** Datei, die Datei heißt bei
> 80 von 104 Läufen gleich, ihr Titel ist bei **allen** 104 Läufen identisch,
> ihr Content-Type ebenfalls, und ein Bild ist nie dabei. Wer aus Dateiname,
> Titel oder Content-Type Bedeutung ableitet, leitet aus Rauschen ab.
>
> - **Besitzt:** die Befundlage zu Metrologie-Artefakten — Ablageweg,
>   Benennung, Mehrdeutigkeiten und die daraus folgenden Code-Regeln.
> - **Für wen:** jeden, der Metrologie anzeigt, parst, dedupliziert oder
>   hochlädt.
> - **Verwandt:** [`12-attachments-and-images.md`](12-attachments-and-images.md)
>   (Mechanik der drei Speicherwege und des lokalen Spiegels — dieses Dokument
>   erklärt sie nicht neu, es misst sie an der Metrologie),
>   [`10-itk-domain-reference.md`](10-itk-domain-reference.md) (Testtypen),
>   [`04-roadmap.md`](04-roadmap.md) („Aktueller Stand").
>
> **Datengrundlage — und ihre Grenze (korrigiert 2026-08-27):** alle Zahlen
> unten sind aus dem **Entwicklungs-Spiegel `backend/itkflow_tudo.db`**
> gezählt (713 Evidence-Läufe, 362 Attachment-Indexzeilen, davon **104
> `MODULE_METROLOGY`-Läufe** vom 2023-09-25 bis 2026-08-25 — 2023: 8, 2024: 2,
> 2025: 12, 2026: 82). **Das ist nicht der Bestand, den die App liest.** Die
> ausgelieferte App arbeitet auf `%LOCALAPPDATA%\itkflow\itkflow.db`: 14 759
> Evidence-Läufe, 3772 Attachment-Zeilen, **432 Bilder**. Wo dieses Dokument
> „der Spiegel" sagte, meinte es die Entwicklungskopie; jede daraus
> verallgemeinerte Aussage über *alle* Bilder war um 431 daneben (Abschnitt
> 2.1). Die Metrologie-Aussagen selbst halten in **beiden** Beständen — siehe
> dort. Nachrechen-Kommandos für beide in Abschnitt 10.

## 1. Kurzfassung

1. **Es gibt kein Metrologie-Bild.** 104 Metrologie-Läufe, 104 Anhänge,
   **0 Bilder**. Jeder Anhang ist eine `text/plain`-Datei mit den Rohzahlen.
2. **Der Dateiname trägt keine Information.** 24 verschiedene Namen auf 104
   Läufe, davon **80× `result.txt`**. Fünf Module haben zwei Läufe mit
   *identischem* Dateinamen.
3. **Titel und Content-Type sind praktisch Konstanten.** `title` ist bei 102
   von 104 `"resultsFile"`, `content_type` bei allen 104 `text/plain`. Die
   zwei Ausreißer (`title = NULL`) hängen beide am selben Modul
   `20USEM20000056` aus Abschnitt 3 — Felder, die fast nie variieren, können
   fast nichts unterscheiden.
4. **Der Ablagename auf Platte ist ein Hex-Handle**, nicht der Dateiname — und
   die Handles haben **zwei Formen** (32 Hex aus der PDB, 64 Hex von itkFlow
   selbst erzeugt). Der Ordner ist für Menschen unlesbar; die Datenbank ist
   die einzige Karte.
5. **Die Maschine heißt drei Dinge** in denselben 104 Läufen — inklusive eines
   Laufs mit DESY-Gerät und DESY-Skriptversion im TUDO-Bestand.
6. **Eindeutig ist genau ein Paar:** `(test_run_ref, pdb_code)`. Alles andere
   ist Anzeigetext.

## 2. Das Bild, das es nicht gibt

Über den gesamten Spiegel hinweg — 362 Attachment-Zeilen — sind Bilder die
Ausnahme, und keine einzige gehört zur Metrologie:

| Testtyp | Quelle | Content-Type | Anzahl |
|---|---|---|---:|
| `MODULE_IV_PS_V1` | `pdb` | `text/plain` | 216 |
| **`MODULE_METROLOGY`** | **`pdb`** | **`text/plain`** | **104** |
| `MODULE_BOW` | `pdb` | `text/plain` | 28 |
| `MODULE_IV_AMAC` | `pdb` | `text/plain` | 8 |
| `MODULE_IV_PS_V1` | `pdb` | `application/octet-stream` | 2 |
| `VISUAL_INSPECTION` | `share_link` | *(keiner)* | 2 |
| `VISUAL_INSPECTION` | `pdb` | `application/pdf` | 1 |
| `VISUAL_INSPECTION` | `pdb` | `image/jpeg` | 1 |

Ein einziges echtes Bild in **dieser Entwicklungskopie**, und das hängt an
einer Sichtprüfung — die Verallgemeinerung „im Spiegel gibt es ein Bild" ist
falsch, siehe 2.1. Die beiden `share_link`-Zeilen sind CERNBox-Freigaben, die aus
einem *Ergebnisfeld* geborgen wurden (docs/12 §2.3): Titel `"Defect 1 -
Images"`, Dateiname = das Freigabe-Token (`6LPpeXmuIBwS5ST`), Content-Type
`null`.

Was der Metrologie-Lauf stattdessen trägt, ist der Messwertblock selbst
(`HYBRID_GLUE_THICKNESS`, `PB_POSITION`, `CAP_HEIGHT`, `SHIELDBOX_HEIGHT` …)
im Evidence-Payload plus die eine Rohdatei. **Wo die Bilddateien des
Messgeräts bleiben, ist nirgends in diesem Repo verzeichnet** — die Keyence
erzeugt sie, die PDB sieht sie nie. Das ist eine offene Frage an den Ablauf,
kein Fehler im Spiegel (Abschnitt 9).

Praktische Folge: Eine Metrologie-Kachel, die eine Bildvorschau anbietet,
verspricht etwas, das der Bestand nicht hergibt. Sie muss „Daten, kein Bild"
sagen — nicht leer bleiben und den Betrachter raten lassen, ob der Sync kaputt
ist.

### 2.1 Dieselbe Frage am Live-Bestand (2026-08-27, nur lesend)

Der Live-Spiegel ist zehnmal so groß, und er verschiebt die Aussage in genau
eine Richtung — die enge stimmt, die weite nicht:

| Frage | `backend/itkflow_tudo.db` | `%LOCALAPPDATA%\itkflow\itkflow.db` |
|---|---:|---:|
| Attachment-Zeilen | 362 | 3772 |
| Bilder insgesamt | 1 | **432** |
| Metrologie-Anhänge | 104 | **581** |
| Bilder an einem Metrologie-Testtyp | 0 | **0** |

**Die Kernaussage hält, und zwar breiter als gemessen.** Im Live-Bestand
tragen **vier** Testtypen Metrologie-Anhänge — `ATLAS18_SHAPE_METROLOGY_V1`
(364), `ASIC_METROLOGY` (111), `MODULE_METROLOGY` (105), `FLEX_METROLOGY` (1)
— und **kein einziger** davon trägt ein Bild. Alle 432 Bilder hängen an
Sichtprüfungen: `ATLAS18_VIS_INSPECTION_V2` (414), `VISUAL_INSPECTION` (10),
`VIS_INSP_RES_MOD_V2` (8).

**Merksatz für die nächste Suche:** „Metrology images" ist die **Beschriftung
eines UI-Panels** (`Metrology & inspection images`, `i18n.images.title`),
**kein Testtyp**. Wer nach dem Panel-Namen in den Daten sucht, sucht nach
einem Ding, das es nicht gibt. Die Bilder, die das Panel zeigt, kommen
ausnahmslos aus der Sichtprüfung — und zu 422 von 432 über EOS (docs/12 §2.2
und §8.1).

## 3. Der Dateiname sagt nichts

24 verschiedene Dateinamen auf 104 Läufe. Die Verteilung ist der Befund:

| Anzahl | Dateiname |
|---:|---|
| 80 | `result.txt` |
| 2 | `R2_20USEM20000178.txt` |
| je 1 | `R5M1.txt`, `R5M0.txt`, `R2.txt` |
| je 1 | `20USE5L0000031.txt`, `20USEM20000056.txt`, `20USEM20000105.txt`, `20USEM20000175.txt` |
| je 1 | `20USE5L0000704_met.txt`, `20USE5R0000073_met.txt`, `20USEM20000104_met.txt` |
| je 1 | `R5M1_20USE5L0000705.txt`, `R5M0_20USE5R0000032.txt`, `R2_20USEM20000102.txt`, … |
| 1 | `R5M0_20USE5R0000074_7.txt` |
| 1 | `result_20USEM20000056.txt` |
| 1 | `resultR2_20USEM20000056.txt` |
| 1 | `R2_module_result_tryAgain_20USEM20000056_OutputFile.txt` |

Mindestens sechs Benennungsschulen nebeneinander: nur Modultyp, nur
Seriennummer, Seriennummer + `_met`, Modultyp + Seriennummer, Modultyp +
Seriennummer + Zähler — und die Kapitulation `result.txt`.

**Das schärfste Einzelbeispiel** ist das Modul `20USEM20000056`: fünf
Metrologie-Läufe, **fünf verschiedene Schreibweisen** — `R2.txt`,
`20USEM20000056.txt`, `result_20USEM20000056.txt`,
`resultR2_20USEM20000056.txt` und
`R2_module_result_tryAgain_20USEM20000056_OutputFile.txt`. Der letzte Name
protokolliert einen Arbeitstag, keine Messung.

**Und Namen kollidieren.** Fünf Module tragen zwei Läufe mit demselben
Dateinamen: `20USE5L0000760`, `20USE5R0000111`, `20USE5R0000132`,
`20USEM20000189` (je 2× `result.txt`) und `20USEM20000178` (2×
`R2_20USEM20000178.txt`). Wer auf `(Seriennummer, Dateiname)` schlüsselt,
verliert bei diesen fünf Modulen je eine Messung — lautlos.

## 4. Die Metadaten lügen mit

- `title` ist bei **102 von 104** Läufen `"resultsFile"`; die zwei
  Ausnahmen (`NULL`) sind die letzten beiden Läufe von `20USEM20000056`
  (Abschnitt 3) und tragen dieselbe Nachlässigkeit im Namen weiter. Ein
  Anzeigefeld, das fast nie variiert, ist praktisch kein
  Unterscheidungsmerkmal.
- `content_type` ist bei **allen 104** `text/plain`. Für Instrumentenausgabe
  im Allgemeinen ist er noch schlechter: die IV-Rohdaten kommen zweimal als
  `application/octet-stream` an, Share-Links tragen **gar keinen**.
- Deshalb entscheidet der Code über „ist das ein Bild?" **zweigleisig** —
  Content-Type-Präfix `image/` *oder* Dateiendung aus einer Liste
  (`backend/app/pdb_attachments.py`, `_is_image`; docs/12 §3.3). Zwei Quellen
  für eine Frage, weil keine allein trägt.
- Der Binärweg der PDB kann mit **HTTP 200 eine HTML-Seite** liefern, die die
  plausible Größe hat und als Bild ausgeliefert nur ein kaputtes Thumbnail
  ergibt. Er wird deshalb explizit auf `<!DOC`/`<html`/`<?xml` geprüft
  (`looks_like_html`).
- Und die Anhänge hängen **nicht an einer festen Ebene**: `_iter_attachments`
  sammelt sie komponentenweit, testweise *und* laufweise. Nur die laufweise
  Variante trägt die Laufreferenz, die der funktionierende Download-Weg
  (`getTestRunAttachment`) braucht — für die anderen bleibt der Notweg, also
  genau der, der HTML zurückgeben kann.

## 5. Zwei Code-Formen, ein Ablagename

Auf Platte heißt eine Datei `<attachment_dir>/<Seriennummer>/<code><ext>`. Der
`code` ist das Handle, die Endung stammt aus einer Allowlist
(`attachment_store.py`) — der von der PDB gelieferte Dateiname wird **nie** zum
Pfad, weil er nicht vertrauenswürdig ist. Richtig so, und trotzdem der Grund,
warum der Ordner unlesbar ist: `de9e0388694d2ca5479067ab8ca4d789.txt` sagt
einem Menschen nichts.

Die Handles haben zwei Formen:

| Länge | Herkunft | Anzahl im Spiegel |
|---|---|---:|
| 32 Hex | echter PDB-Attachment-Code | 360 |
| 64 Hex | von itkFlow erzeugt für CERNBox-Share-Links | 2 |

Auf Platte ist derselbe Schnitt sichtbar: in `./attachments` 3.659 Namen mit
32 Zeichen, 75 mit 64. **Ein 64-Zeichen-Name ist also kein PDB-Objekt**,
sondern eine geborgene Freigabe — am Namen selbst nicht erkennbar.

Dazu die schon bekannte Falle der **zwei Attachment-Wurzeln** (docs/12 §4.1),
hier gemessen: `./attachments` enthält 3.734 Dateien (3.020 `.txt`, 624
`.dat`, 396 `.jpg`, 35 `.png`, 6 `.csv`, 3 `.pdf`, 2 `.tif`),
`backend/attachments` 352. Von den 362 Indexzeilen lösen **353 in der einen**
und **351 in der anderen** Wurzel auf — beide wurden zu verschiedenen Zeiten
beschrieben, und die große Wurzel trägt zusätzlich rund 3.400 Dateien, die
keine Zeile der kanonischen Datenbank mehr kennt. Bilder sind darin reichlich
(396 JPG), nur eben unter Sensor- und Hybrid-Seriennummern; unter den 93
Modulen mit Metrologie-Läufen liegen genau **zwei** Bilddateien, und beide
sind die CERNBox-Sichtprüfungen aus Abschnitt 2.

## 6. Die Maschine heißt drei Dinge

`properties` derselben 104 Läufe:

| `MACHINE` | `SCRIPT_VERSION` | Anzahl |
|---|---|---:|
| `Keyence VR-3200` | `v0.1` | 98 |
| `Keyence` | `v0.1` | 5 |
| `Flash CNC 300 Smartscope` | `DESYv0` | 1 |

Zwei Schreibweisen für dasselbe Gerät, plus ein Lauf, der mit DESY-Gerät und
DESY-Skriptversion im TUDO-Bestand steht. Gruppieren oder Filtern nach
`MACHINE` als Rohtext zählt hier falsch. Der Kommentar in `ingestion.py`
spricht bis heute vom „OGP Smartscope" als Quelle — historisch korrekt, aber
nicht mehr das, was 98 von 104 Läufen sagen.

## 7. Was in der Rohdatei steht — und was davon nicht ins Repo darf

Der Kopf einer Metrologie-Rohdatei führt: `EC or Barrel`, `Module type`,
`Module ref. Number`, `Date`, `Institute`, **`Operator`**, `Instrument type`,
`Run Number`, `Measurement program version`; danach Positionen und Klebehöhen
als Spaltenblöcke.

Das `Operator`-Feld enthält **Klarnamen echter Personen**. Diese Dateien
dürfen deshalb nicht als Fixture, Beispiel oder Log-Auszug ins Repo wandern —
Beispieldaten werden anonymisiert (CLAUDE.md, harte Regel 3). Wer einen
Metrologie-Parser testet, baut den Kopf synthetisch.

## 8. Was daraus folgt (Regeln für den Code)

1. **Schlüssel ist `(test_run_ref, pdb_code)`.** Nie Dateiname, nie
   `(Seriennummer, Dateiname)`, nie Titel.
2. **Aus Dateinamen keine Semantik ableiten** — weder Modultyp noch
   Seriennummer noch Laufnummer. Alles davon steht im Payload.
3. **`content_type` ist ein Hinweis, kein Vertrag.** Für „Bild?" bleibt es bei
   zwei Kriterien; heruntergeladene Bytes werden auf HTML geprüft.
4. **Die Metrologie-Anzeige verspricht kein Bild.** Sie zeigt Messwerte und
   die Rohdatei zum Herunterladen; wo eine Bildkachel stünde, gehört ein
   ausdrückliches „no image attached" hin.
5. **Mehrere Läufe pro Modul sind normal**, auch mit gleichem Dateinamen.
   Sortiert wird nach Messzeitpunkt, unterschieden nach Lauf-ID.
6. **`MACHINE`/`SCRIPT_VERSION` nur normalisiert auswerten** — und
   institutsfremde Werte nicht als TUDO-Gerät zählen.

## 9. Offene Punkte

- **Offen:** Wo die Bilddateien des Messgeräts (Keyence VR-3200) tatsächlich
  landen — Instrumentenrechner, CERNBox, gar nicht aufgehoben? Bis das geklärt
  ist, kann itkFlow zur Metrologie keine Bilder zeigen, egal wie gut der Sync
  läuft.
- **Offen:** ob die rund 3.400 verwaisten Dateien in der falschen
  Attachment-Wurzel weggeräumt oder in die kanonische Wurzel überführt werden
  (docs/12 §4.1).
- **Nicht verifiziert:** ob Fremdinstitute Bilder an `MODULE_METROLOGY` hängen.
  Der TUDO-Bestand kann das nicht beantworten; der einzige Fremdlauf hier
  (`Flash CNC 300 Smartscope`) trägt ebenfalls nur eine `.txt`.
- **Nicht verifiziert:** ob ein Anhang je auf Komponenten- statt Laufebene
  auftaucht — dann fehlt die Laufreferenz und nur der HTML-anfällige Notweg
  bleibt. Der Code hält den Fall aus, gesehen wurde er noch nicht.
- **Erledigt (2026-08-27):** die Verallgemeinerung „im Spiegel gibt es ein
  Bild" ist gegen den Live-Bestand korrigiert (Abschnitt 2.1). Wer dieses
  Dokument fortschreibt, schreibt die Datenbank dazu, aus der er gezählt hat —
  die beiden unterscheiden sich um den Faktor 10.

## 10. Quellen und Nachrechnen

Code (Stand 2026-08-27, Arbeitskopie):

- `backend/app/attachment_store.py` — Ablagename, Endungs-Allowlist, Download
- `backend/app/pdb_attachments.py` — `_iter_attachments`, `_is_image`,
  `looks_like_html`, Download-Route mit Laufreferenz
- `backend/app/pdb_test_evidence.py` — Attachment- und Share-Link-Summaries
- `backend/app/ingestion.py` — Parser `module-metrology-v1`, Ergebnisgruppen
- `backend/app/api.py` — `component_attachments*`, `component_images*`

Zahlen reproduzieren (aus dem Repo-Wurzelverzeichnis, nur lesend). **Der
Live-Bestand wird ausschließlich read-only geöffnet** — die App schreibt
hinein, während man misst:

```python
import os, sqlite3, collections
live = os.path.expandvars(r"%LOCALAPPDATA%\itkflow\itkflow.db")
c = sqlite3.connect(f"file:{live}?mode=ro", uri=True)   # niemals ohne mode=ro
q = ("select test_type, count(*) from test_run_attachment "
     "where content_type like 'image/%' group by test_type")
print(c.execute(q).fetchall())          # ausschließlich Sichtprüfungs-Testtypen
print(c.execute("select count(*) from test_run_attachment "
                "where upper(test_type) like '%METROLOG%'").fetchone())
```

Und für die Entwicklungskopie:

```python
import sqlite3, collections
c = sqlite3.connect("backend/itkflow_tudo.db")
q = ("select component_sn, filename, pdb_code, title, content_type "
     "from test_run_attachment where test_type='MODULE_METROLOGY'")
rows = c.execute(q).fetchall()
print("Laeufe:", len(rows), "| Dateinamen:", len(set(r[1] for r in rows)))
print(collections.Counter(r[1] for r in rows).most_common(5))
print("Titel:", set(r[3] for r in rows), "| Content-Types:", set(r[4] for r in rows))
coll = collections.Counter((r[0], r[1]) for r in rows)
print("Kollisionen:", [k for k, v in coll.items() if v > 1])
```

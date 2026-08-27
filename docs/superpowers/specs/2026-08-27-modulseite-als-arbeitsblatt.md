# Plan: Die Modulseite als Arbeitsblatt

Datum: 2026-08-27 · Status: **Entwurf, Owner-Entscheidungen offen** ·
Owner: [`docs/00-doc-map.md`](../../00-doc-map.md)

Grundlage — drei Recherchen, alle gegen echte Daten:
[Abschrift der Blätter](../research/2026-08-26-zflow-sheet-transcription.md) ·
[Bedeutung jeder Zeile (zFlow)](../research/2026-08-26-zflow-row-semantics.md) ·
[Blattzeile → PDB](../research/2026-08-26-sheet-to-pdb-map.md) ·
[Ist-Aufnahme itkFlow](../research/2026-08-26-itkflow-coverage-gap.md)

## 0 — Die Frage, die den Plan auslöste

„Kopieren wir das Blatt 1:1?" — **Nein.** Und der Grund ist kein Geschmack:
Die Zeile eines Blattes ist ein **Arbeitsschritt**, die Zeile unseres
Worksheets ein **PDB-Testtyp**. Von 93 Blattzeilen sind 37 sichtbar,
11 anderswo erreichbar, 14 im Backend implementiert **ohne jeden Aufrufer**,
31 gar nicht vorhanden.

Aber die entscheidende Korrektur kam aus der PDB-Kartierung: **Die rohen
Waagenwerte des Blattes sind PDB-Felder.** `GW_SENSOR`, `GW_HYBRID1`,
`GW_PB`, `GW_MODULE_H1PB` existieren als Result-Codes im `GLUE_WEIGHT`-Schema.
Damit braucht die Erfassung **keinen** neuen Speicher — sie passt in den
bestehenden Edit-Streifen. Was fehlt, ist die **Ableitung**: aus Rohwerten das
Klebegewicht, aus Ziel und Toleranz das Urteil.

## 1 — Was zuerst repariert werden muss (Fehler, die heute wirken)

> **Status: Etappe E1 umgesetzt (2026-08-27).** Beide Befunde dieses
> Abschnitts sind behoben; Vertrag und Zahlen stehen in
> [`docs/09`](../../09-pdb-production-strategy.md) („Zurueckgezogene
> Testlaeufe", „Ring-Module") und [`docs/05`](../../05-ui-design-reference.md),
> das Protokoll im Abschnitt „Aktueller Stand" von
> [`docs/04`](../../04-roadmap.md). Zwei Punkte bleiben bewusst offen: das
> Stage-Gate aggregiert **nicht** ueber Kindkomponenten (offene
> Owner-Entscheidung, siehe §6), und die aufgeklappte Lauf-Ansicht
> kennzeichnet einen zurueckgezogenen Lauf noch nicht sichtbar — `run_state`
> liegt dafuer bereits am Wire.

### 1.1 Zurückgezogene Messungen erscheinen als gültig

Der Spiegel hält **102 in der PDB gelöschte Testläufe** ohne Statusspalte —
13 % aller `GLUE_WEIGHT` und 25 % aller `MODULE_BOW`. Ohne Filter auf
`payload.state` zeigt die Modulseite zurückgezogene Messungen als bare Münze,
und sie zählen in die Pflichttest-Prüfung. Das ist kein Schönheitsfehler,
sondern ein falsches Urteil über den Produktionsstand.

**Aufgabe:** `state` in den Spiegel aufnehmen und in `satisfied_test_results`,
`preview.py` und der Statistik filtern. Der Owner-Fund „der 1,859er-Block" ist
zu 14 von 15 genau das: bereits gelöscht.

### 1.2 Die Modulseite sieht 4,9 % der Geschichte

Von 14 759 gespiegelten Läufen hängen **720 am Modul**. Der Rest liegt auf
Sensoren, Hybriden, Powerboards — den Kindern. Dieselbe Ursache wie beim
Stage-Profil-Befund: R5-Ringmodule tragen ihre Nachweise auf den Halbmodulen.

**Aufgabe:** Das Worksheet bekommt die Nachweise der Kindkomponenten, als
eigene Gruppe je Kind, nicht vermischt mit den eigenen. Die Familie ist auf
der Seite bereits da — nur ihre Messungen fehlen.

## 2 — Die Klebegewichts-Erfassung (der eigentliche Auftrag)

### 2.1 Was existiert

`backend/app/domain/glue.py` enthält die Rechnung **zeichengleich mit dem
Blatt**: `(B2*4.2)+(C2*1.5)` als Ziel, `(B2*0.25)+(C2*0.1)` als Toleranz, die
Gewichtsdifferenz mal tausend, das Urteil in drei Stufen. Und **null
Aufrufer.** Die komplette TrueBlue-Zieltabelle steht dort, alle sieben Zeilen.

### 2.2 Was fehlt

1. **Profildaten.** Es gibt kein `glue_targets_from_settings()` als Gegenstück
   zu `stage_model_from_settings`. Nötig: `glue_targets`
   (Verfahren × Modultyp → {hybrids, powerboard} × {target, tolerance}),
   `chip_glue_amounts` (ABC/HCC), und ein Ort für das **Klebeverfahren** —
   heute trägt keine Entität es.
   *Die Chipbestückung braucht keine Tabelle:* sie ist aus der Kindzählung
   exakt ableitbar (R5H0 → 9 ABC/0 HCC, R5H1 → 9/2, je 31 von 31 korrekt).
2. **Der Adapter**, analog `stage_service.py`: reine Mathematik in `domain/`,
   sessiongebundene Beschaffung daneben, Emission über die Worksheet-Payload.
   Vier Präzedenzfälle im Haus (`_status_for`, `StageModel`-Durchreichung,
   `_pdb_properties`, `pot_life_state`) sagen dasselbe: **der Server rechnet,
   das Frontend färbt den Chip.**
3. **Gültigkeitszeiträume.** Das lebende Blatt führt zwei Generationen
   derselben Regel nebeneinander: der neuere Hybrid-Reiter rechnet mit
   **HCC 1,8 mg statt 1,5** und einer Toleranz von **10 % des Ziels**, in einer
   Zeile ausdrücklich beschriftet „only lower bound since 2023-10-24".
   Derselbe Hybridtyp bekommt auf zwei Reitern 43,5 bzw. 43,8. Ein Profil, das
   nur *einen* Satz Konstanten kennt, kann historische Läufe nicht korrekt
   bewerten. **Klebe-Ziele brauchen ein Gültig-ab-Datum.**
4. **POLARIS.** Nur ein Verfahren ist hinterlegt; TUDO fährt ausschließlich
   TrueBlue (die POLARIS-Spalte wird im lebenden Blatt von **keiner** Formel
   referenziert, und ihre R2-Zeile ist ganz leer). Das Profil muss beide
   können, TUDO braucht vorerst nur eines.
5. **Ein Fehler des Blattes, der nicht mitwandern darf.** In der
   TrueBlue-Tabelle steht bei R2 als Gesamt-Toleranz `22`, obwohl
   25 + 11 = 36 ergibt — jede andere Zeile ist konsistent. Offenkundig aus
   R5M1 kopiert. Die Spalte wird von keiner Formel benutzt, aber wer die
   Tabelle ins Institutsprofil überträgt, zementiert den Fehler.

### 2.5 Korrektur: die Ohren-Subtraktion gehört nicht hierher

Eine frühere Fassung dieses Plans nahm an, `(C23-(C22-C21)-C20)*1000` sei die
Modul-Klebeformel und uns fehle die „Ohren-Subtraktion". **Falsch.** Diese
Formel gehört zum **ASIC-Kleben auf den Hybrid** (Zeilen: Leergewicht, leeres
Tray, ASICs mit Tray, Hybrid mit ASICs) und ist am lebenden Blatt exakt
nachgerechnet: `1,5321 − (5,3733 − 5,0349) − 1,1575 = 36,2 mg`.

**TUDO klebt keine ASICs.** Alle Hybrid-Reiter dieser Datei enthalten
ausschließlich Zeuthener Panels — die Datei ist eine Kopie des DESYZ-Blattes.
Die Modul-Kette ist die, die wir rekonstruiert hatten, und sie ist am
lebenden Blatt über alle vollständig gefüllten Spalten bestätigt.

### 2.3 Wie die Erfassung aussieht

Der Edit-Streifen der `GLUE_WEIGHT`-Zeile zeigt die **Rohwerte als
Formularfelder** (sie sind PDB-Result-Codes) und darunter, live berechnet und
nicht editierbar: Klebegewicht, Ziel, Toleranz, **Urteil `OK` / `zu wenig` /
`zu viel`**. Gestaged wird der vollständige Lauf inklusive der abgeleiteten
`GW_GLUE_*`-Felder — genau wie das Blatt es hochlädt.

Die Berechnung passiert **serverseitig im Dry-Run**, nicht im Browser. Sonst
existiert die Formel zweimal und driftet.

### 2.4 Was die PDB dabei nicht tut

**Sie urteilt nicht.** `automaticGrading=false` bei allen 14 Modul-Schemata,
alle Schwellwerte `null`. Das `passed`-Bit reproduziert das Blatt-Urteil nur
zu **80 %** (48 von 60) — und es ist *ein* Bit für *zwei* Urteile
(Hybrid und Powerboard). Ziel, Toleranz und Ampel können also **nur** aus dem
Institutsprofil kommen. Wer das Blatt abschaltet, ohne diese Tabellen zu
portieren, verliert das Urteil ersatzlos.

## 3 — Werte ohne PDB-Heimat

20 Blattzeilen brauchen lokalen Speicher: der Werkzeug-/Klebstoff-Nachweis am
Testlauf und die Urteilslogik. Dazu die betrieblich wertvollen Freitexte —
`Glued by`, `Powerboard Label`, `Comments`, Pack- und Versanddatum.

**Es gibt heute keinen Ort dafür.** `Component` ist ein erklärter
Nur-Lese-Spiegel („Never written by request handlers"); die einzige lokal
geführte Zeile *pro Komponente* im ganzen Schema ist `GlueUsage`.
`OutboxAction.payload` ist per Definition eine PDB-Schreibabsicht und damit
die Umkehrung dessen, was hier gebraucht wird.

**Vorschlag:** eine neue Nachbartabelle nach dem Vertrag von
`Shipment.reception_*` — „lokal führend, wird von keinem Sync überschrieben".
Genau diesen Vertrag verbietet der `Component`-Docstring für `Component`
selbst, weshalb er in eine Nachbartabelle gehört.

## 4 — Werkzeug-Nachweis: eine Lücke, die niemand vermutet hat

Ein Regex-Scan über **alle 14 759** gespiegelten Payloads nach Werkzeug- und
Klebstoff-Seriennummern liefert **null Treffer**. `GLUE_WEIGHT` hat keine
Werkzeug-Property — nur `GW_METHOD` und `GLUE_METHOD_V_*`.

itkFlow schreibt Werkzeug-Codes in Assembly-**Beziehungs**-Properties, und
`pdb_sync.map_pdb_component` spiegelt Properties überhaupt nicht zurück.
Das TUDO-Profil hat zudem `settings = {}` — der Schreibpfad ist unkonfiguriert.

Immerhin: alle sieben Dropdown-Seriennummern des Blattes lösen im Spiegel
sauber auf (`20USERT0510711` = `R5S0_Module_Jig_11`). Das Fundament steht,
die Verdrahtung fehlt. Berührt [`docs/07`](../../07-jig-tool-quickselect.md).

## 5 — Reihenfolge

| Etappe | Inhalt | Warum zuerst |
|---|---|---|
| **E1** ✅ | `state`-Filter für gelöschte Läufe; Kind-Nachweise im Worksheet (umgesetzt 2026-08-27, siehe §1) | Beides verfälschte das Urteil über den Produktionsstand |
| **E2** | `glue_targets`/`chip_glue_amounts` als Profildaten + Adapter + abgeleitete Worksheet-Felder | Der eigentliche Auftrag; die Mathematik existiert bereits |
| **E3** | Rohwert-Erfassung im Edit-Streifen mit Live-Urteil | Setzt E2 voraus |
| **E4** | Lokale Nachbartabelle für Werte ohne PDB-Heimat | Architekturentscheidung, siehe §3 |
| **E5** | Werkzeug-Nachweis am Testlauf verdrahten | Setzt eine Profil-Konfiguration voraus, die TUDO noch nicht hat |

Nicht geplant, bewusst: die `SCRIPT:`-Spalten (das ist unser Spiegel- und
Staged-Zustand, wir haben es besser), die Spalte-pro-Modul-Anordnung, und die
Line-Speed-Rückkopplung — letztere existiert nicht einmal im Referenzcode und
hat **keinerlei Rückverfolgbarkeit**: nirgends steht, mit welcher Liniengeschw
indigkeit ein Modul geklebt wurde.

## 6 — Entscheidungen, die nur der Owner treffen kann

1. **Metrologie als Pflichttest?** Sie scheitert bei 74 von 93 Komponenten,
   bei 16 fertigen Modulen kein einziges Mal bestanden. Als Pflicht-Gate
   sperrt sie 80 % der Produktion. Qualitätsproblem oder falsche Toleranz?
2. ~~`R2H0` fehlt in der „Daten"-Tabelle~~ — **beantwortet, keine
   Entscheidung nötig.** Die ABC/HCC-Tabelle regelt das **ASIC-Kleben auf
   Hybride**, nicht Module; `R2H0` kommt im gesamten lebenden Blatt kein
   einziges Mal vor, und das ist richtig so. Modul-Ziele stammen aus der
   TrueBlue-Tabelle, die eine R2-Zeile **hat** (164/25/70/11/234/22), und jede
   R2-Spalte des Blattes zeigt genau diese Werte.
3. **Sollen Freitexte (`Comments`, `Glued by`) überhaupt lokal gespeichert
   werden?** Sie sind betrieblich wertvoll und gehen sonst verloren — aber sie
   erreichen die PDB nie und existieren dann nur in itkFlow.
   *Randnotiz aus dem lebenden Blatt:* `Glued by - Name` ist bei TUDO in
   **jeder** Spalte leer. Die Namen in der Abschrift stammen aus dem
   DESYZ-Screenshot. Für TUDO ist diese Zeile also womöglich verzichtbar —
   `Comments` dagegen nicht.
4. **Stage-Profil** (offen aus [`docs/10`](../../10-itk-domain-reference.md) §7):
   das Seed-Profil blockiert 226 von 263 Modulen. Der GUI-Editor steht seit
   0.2.2 bereit.

## 8 — Was das lebende Blatt über sich selbst verrät

Gelesen über den Drive-Connector am 2026-08-27, Details in
[`2026-08-27-tudo-sheet-live.md`](../research/2026-08-27-tudo-sheet-live.md).
Drei Beobachtungen ändern die Dringlichkeit, nicht die Richtung:

- **Die Metrologie-Anzeige ist seit dem 2025-03-03 tot.** Alle 21 Module zeigen
  „Messung fehlt!", weil der Nachschlage-Reiter seit jenem Tag nicht mehr
  aktualisiert wurde — er trägt die Notiz „Last time entries were refreshed:
  03.03.2025 15:03:31" — während der zFlow-Reiter direkt daneben echte
  `MODULE_BOW`- und `MODULE_METROLOGY`-Ergebnisse meldet. Das Blatt zeigt seit
  eineinhalb Jahren eine Lücke, die keine ist. **Das ist das stärkste einzelne
  Argument für die Ablösung** — nicht Bequemlichkeit, sondern eine Anzeige,
  der man nicht mehr glauben kann.
- **Der Bestand ist kleiner und schmutziger als angenommen:** 21 Modulspalten,
  davon **9 vollständige Hybrid-Klebesätze und 5 vollständige
  Powerboard-Sätze**. Von 13 Powerboard-Urteilen sind **8 arithmetischer Müll**
  aus leeren Eingaben (die negativen Werte der Abschrift). Sechs lokale
  Modulnamen sind doppelt vergeben, eine PDB-Seriennummer steht in drei
  Spalten.
- **Die zFlow-Ausgabe zeigt noch auf `itkpd-test.unicorncollege.cz`** — die
  Testinstanz, die es nicht mehr gibt. Dieselbe Altlast, die wir gestern aus
  drei eigenen Dokumenten entfernt haben.

## 7 — Eine Korrektur in eigener Sache

Ich hatte dem Owner eine Einheiten-Uneinheitlichkeit in der PDB gemeldet
(`GW_GLUE_H1` mit 0,166 gegen 195). **Das war falsch gerahmt.** Alle 19
`GW_`-Codes sind im Schema als `[g]` deklariert; die PDB ist konsistent. Das
Blatt rechnet in mg, zFlow multipliziert mit `1e-3` — die Diskrepanz sitzt an
der Blattgrenze, nicht in der Datenbank. Von 346 befüllten Zellen lebender
Läufe liegen 11 außerhalb des Plausibilitätsbands, und davon ist **genau eine**
ein echter ×1000-Fehler. Der Rest sind Feldvertauschungen: in 20 Läufen steht
dieselbe Zahl in mehreren Codes.

Die Schlussfolgerung bleibt trotzdem gültig — ein rechnendes Formular hätte
sowohl den einen Faktor-1000-Fehler als auch die Vertauschungen verhindert.
Nur war meine Begründung ungenauer als die Daten.

## 9 — Vertrag für E2/E3 (verbindlich für beide Seiten)

Damit Backend und Frontend nicht auseinanderlaufen, steht der Vertrag hier,
bevor gebaut wird.

### 9.1 Profildaten: `glue_targets`

Eine **Liste** von Regelsätzen. Auswahl: alle Einträge mit passendem `process`,
davon derjenige mit dem größten `valid_from` ≤ Messzeitpunkt des Laufs;
`valid_from: null` gilt immer und dient als Rückfall. Das bildet die zwei
Generationen ab, die im lebenden Blatt nebeneinander stehen.

```json
[
  {
    "process": "TRUEBLUE",
    "label": "True Blue / False Blue",
    "valid_from": null,
    "module_types": {
      "R5M1": {"hybrids": {"target_mg": 151, "tolerance_mg": 22},
               "powerboard": {"target_mg": 0, "tolerance_mg": 0}}
    }
  }
]
```

### 9.2 Profildaten: `glue_weight_inputs` — die Formel als Daten

Welche PDB-Result-Codes welchen Schritt speisen, ist Instituts- und
Schemasache, **nicht** Code. `measured − Σ subtract`, Ergebnis in mg, abgelegt
unter `result_code`:

```json
{
  "hybrids":    {"measured": "GW_MODULE_H1H2",
                 "subtract": ["GW_SENSOR", "GW_HYBRID1", "GW_HYBRID2"],
                 "result_code": "GW_GLUE_H1H2"},
  "powerboard": {"measured": "GW_MODULE_H1H2PB",
                 "subtract": ["GW_MODULE_H1H2", "GW_PB"],
                 "result_code": "GW_GLUE_PB"}
}
```

**Einheiten:** Die PDB führt alle `GW_`-Codes in **Gramm**; Ziel und Toleranz
stehen in **mg**. Die Umrechnung passiert genau einmal, im Adapter, und ist
Teil des Vertrags — nicht Sache der Anzeige.

### 9.3 Payload: `WorksheetRow.derived`

Optional; nur gesetzt, wenn das Profil für diesen Testtyp eine Ableitung kennt.

```
derived: {
  kind: "glue_weight",
  process: string | null,
  process_source: "run" | "profile_default" | "unknown",
  steps: [{
    key: string,                 // "hybrids" | "powerboard", aus dem Profil
    label: string,
    measured_mg: number | null,
    target_mg: number | null,
    tolerance_mg: number | null,
    verdict: "ok" | "too_little" | "too_much" | "unknown",
    reason: string | null,       // "no_target" | "missing_inputs" | "no_run"
    inputs: [{code, name, value}]  // die verwendeten Rohwerte, nachvollziehbar
  }]
}
```

`verdict: "unknown"` mit `reason` ist Pflicht statt einer stillen Lücke — die
8 von 13 Müll-Urteilen des Blattes entstehen genau daraus, dass eine fehlende
Eingabe wie ein Ergebnis aussieht.

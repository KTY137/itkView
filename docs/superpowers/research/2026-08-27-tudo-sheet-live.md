# Das LIVE-Blatt „Production Overview TU Dortmund" (Volltext-Analyse, 2026-08-27)

**Zweck.** Diese Datei ersetzt die Rätselei. Grundlage ist nicht mehr ein
Screenshot, sondern der vollständige Inhalt der Google-Tabelle
„Production Overview TU Dortmund" (Drive-Connector, Stand 2026-08-26,
ca. 197 000 Zeichen, 18 Tabellenblätter).

**Verhältnis zur Screenshot-Abschrift.**
[`2026-08-26-zflow-sheet-transcription.md`](2026-08-26-zflow-sheet-transcription.md)
bleibt unverändert stehen — sie ist das Protokoll dessen, was die Screenshots
gezeigt haben. **Wo dieses Dokument der Abschrift widerspricht, gilt dieses
Dokument.** Jeder Punkt ist markiert:

- **BESTÄTIGT** — die Abschrift stimmt wörtlich/numerisch.
- **KORRIGIERT** — die Abschrift ist falsch, unvollständig oder falsch zugeordnet.
- **ERGÄNZT** — die Screenshots konnten das gar nicht zeigen.

Nachgelagerte Dokumente, die auf der Abschrift aufbauen und deshalb gegen dieses
Dokument geprüft werden müssen:
[`2026-08-26-zflow-row-semantics.md`](2026-08-26-zflow-row-semantics.md),
[`2026-08-26-sheet-to-pdb-map.md`](2026-08-26-sheet-to-pdb-map.md),
[`2026-08-26-itkflow-coverage-gap.md`](2026-08-26-itkflow-coverage-gap.md).

**Datenschutz.** Die Zeile `Glued by - Name` existiert in **allen** Modulblättern
dieser Datei und ist in **allen** Spalten **leer**. In dieser Datei stehen keine
Personennamen. Die in der Abschrift genannten Namen stammen aus dem
DESYZ-Screenshot, nicht aus dieser Datei. Für Beispiele gilt weiterhin das
Anonymisierungsschema `Anna Abel <anna.abel@example.org>`.

---

## 0 — Methodik und Grenzen des Exports

Der Drive-Connector liefert je Tabellenblatt eine Markdown-Tabelle. Daraus folgt:

1. **Blattnamen fehlen.** Der Export enthält nur Zellinhalte. Die Blätter werden
   hier `T1 … T18` in Exportreihenfolge genannt; die Bezeichnung dahinter ist aus
   dem Inhalt erschlossen, **nicht** aus einem Reiter abgelesen.
2. **Formeln fehlen.** Der Export liefert **Werte**, keine Formeln. Wörtlich
   vorhanden sind nur die Formeln, die im Blatt „Daten" als Text dokumentiert
   sind (§4.1). Alles Weitere in §4 ist **numerisch rückgerechnet** und an den
   echten Zellwerten verifiziert — jede Rechnung dort ist an mindestens fünf
   Modulspalten geprüft.
3. **Der Export kappt bei ca. 2 500 Zellen je Blatt.** Betroffen (Zeilen
   abgeschnitten): T3 (91 Spalten → nur 26 Zeilen), T6 (292 Spalten → nur
   7 Zeilen), T7 (43 Spalten → 57 Zeilen), T12 (34 Spalten → 72 Zeilen),
   T15 (106 Spalten → 22 Zeilen). **Nicht** betroffen und damit vollständig:
   das aktive TUDO-Modulblatt T5 (24 × 74 Zellen im Export) und das
   Referenzblatt „Daten" T8.
4. Zusammengeführte Zellen erscheinen als `[merged] <Text>` über alle
   überdeckten Spalten. Zeilennummern in diesem Dokument sind **echte
   Tabellenzeilen** (verifiziert über die Zellbezüge in den dokumentierten
   Formeln, siehe §4.1).

---

## 1 — Tab-Inventar: 18 Blätter, nicht 3 · **ERGÄNZT**

Die Abschrift kannte drei Blätter (TUDO, DESYZ, Daten). Die Datei hat 18.

| # | Inhalt | Größe | Status |
|---|---|---|---|
| T1 | Hybrid-Panel **PPA**, 20 Hybride `DZHU-PPA-…`, Ort `DZHU`, Chip-Klebung 2023 | 31 Sp. × 71 Z. | Zeuthen-Altbestand |
| T2 | Hybrid-Panel **PPB**, 11 Hybride `DZHU-PPB-…`, neuere Zeilenstruktur | 31 Sp. × 43 Z. | Zeuthen-Altbestand |
| T3 | Modulblatt, **komplett leer** (89 Spalten `Bitte Modul auswählen`) | 91 Sp. | Vorlage/Reserve |
| T4 | Modulblatt `Hide Finished`, 4 Module (`TUDO-test`, `TUDO-R2-0059`, `TUDO_PPB_13`, `TUDO_PPB_3`), **alte Zeilenstruktur** | 7 Sp. × 66 Z. | Test-/Restblatt |
| **T5** | **Das aktive TUDO-Modulblatt** (A1 = `at TUDO`), 21 Module | **24 Sp. × 73 Z.** | **produktiv** |
| T6 | Modulblatt `at TUDO` mit **290 Modulspalten**, 263 vorbelegten Sensor-IDs, nur 7 Modulnamen | 292 Sp. | Sensorpool/Planung |
| T7 | **zFlow-Ausgabeblatt**: 41 Spalten Maschinenfelder, 20 Modulzeilen | 43 Sp. × 57 Z. | Integrationspunkt |
| **T8** | **Referenzblatt „Daten"** | 15 Sp. × 38 Z. | vollständig, §3 |
| T9 | „Tool-Kombi-Beispiele, die Metrology passed sind -" | 12 Sp. × 21 Z. | Erfahrungswissen |
| T10 | Werkzeug-RFID-Zuordnung je Hybridtyp (Jig/Tray/Pickup/HV-Tab/Moduljig) | 11 Sp. × 70 Z. | Werkzeugkatalog |
| T11 | Modulblatt `R3`, Modulnamen sind `#REF!` | 10 Sp. × 65 Z. | **kaputt**, alte Struktur |
| T12 | Hilfsblatt: PDB-Property-Namen `GW_*` + Metrologie-Lookup | 34 Sp. × 72 Z. | Integrationspunkt |
| T13 | Doku-/Link-Sammlung (Zeuthen-Hostnamen, Google-Docs) | 3 Sp. × 39 Z. | Zeuthen-Altbestand |
| T14 | Hybridblatt 2023 (13 Hybride, Datumsnamen) | 31 Sp. × 50 Z. | Altbestand |
| T15 | Testbeam-Modulblatt 2023 (`TB1-…`, `TB2-…`, 67 Module, Ort `DESYZ`) | 106 Sp. × 22 Z. | Altbestand |
| T16 | **Werkzeug-Inventar** `For module / Type / Number on tool / Colour / SN` + Regalort | 9 Sp. × 125 Z. | produktiv |
| T17 | Kleber-Chargenblatt `Serial Number (ZFlow) / Stage / Type / Batch Number / #bi-packs used / Manufacturing Date / Opening date (ZFlow) / Note` | 9 Sp. × 5 Z. | leer, nur Kopf |
| T18 | Vorlage Sensor-Sichtprüfung (`Sensor SN`, `Sensor Type`, `Passed`, `Properties`, `Date`, `Upload`, 10× `Damage Number/Location/Description/Type`) | 1 Sp. × 46 Z. | leer |

**Wichtigste Einsicht daraus:** Die TUDO-Datei ist eine **Kopie des
Zeuthen-Blatts**. T1, T2, T13, T14, T15 enthalten unverändert DZHU-/DESYZ-Daten
(bis hin zu Links auf `nbmess.zeuthen.desy.de` und `gumato01`). Was die
Abschrift als „DESYZ-spezifische Zeilen" beschrieb, ist zum Teil schlicht die
**ältere Fassung derselben Zeilenstruktur**, die in TUDOs eigener Datei in T4,
T11 und T15 weiterlebt. **KORRIGIERT.**

---

## 2 — Zeileninventar des aktiven Modulblatts T5 · maßgeblich

Layout wie beschrieben: **Spalte = Modul, Zeile = Arbeitsschritt**. Zeile 1
trägt in A1 `at TUDO`, in B1 `Module Name`. Bänder stehen als verbundene Zellen
in Spalte A. Vollständige Liste, in Blattreihenfolge:

### Band (A1) `at TUDO` — Zeile 1
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 1 | `Module Name` | 22/22 | BESTÄTIGT |

### Band `Auxiliary Info (zusätzliche Informationen)` — Zeilen 2–5
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 2 | `Sensor ID` | 21 | BESTÄTIGT |
| 3 | `Module Type` | 22 | BESTÄTIGT (Dropdown, Leerwert `bitte wählen`) |
| 4 | `SCRIPT: current stage` | 21 | BESTÄTIGT |
| 5 | `Current location` | 22 | BESTÄTIGT |

### Band `HV-TAB ATTACHED` — Zeilen 6–12
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 6 | `Module reception visual inspection + photo` | 0 | BESTÄTIGT |
| 7 | `reception IV, in DB?` | 0 | BESTÄTIGT |
| 8 | `HV tab jig` | 0 | BESTÄTIGT (in T4 dagegen gefüllt: `20USERT0245008`) |
| 9 | `HV tab sheet SN` | 3 | KORRIGIERT — bei TUDO **nicht leer**: `20USEVS0200690`, `20USEVL0200229`, `20USEVS0200690` |
| 10 | `Sensor weight with tab (g)` | 9 | BESTÄTIGT |
| 11 | `IV after tabbing passed?. in DB?` | 22 | BESTÄTIGT (Tippfehler `?.` ist echt) |
| 12 | `SCRIPT: Module registered to DB?` | 22 | BESTÄTIGT |

### Band `Gluing Hybrids with TRUE BLUE - False blue` — Zeilen 13–31
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 13 | `Glued by - Name` | **0** | BESTÄTIGT (leer, siehe Datenschutzhinweis) |
| 14 | `Hybrids SNs (top, bottom)` | 21 | BESTÄTIGT — faktisch **eine** SN je Zelle, TUDO baut nur Einzelhybrid-Module |
| 15 | `top Hybrid weight (g) with ears` | 0 | BESTÄTIGT |
| 16 | `top Hybrid ears weight (g)` | 0 | BESTÄTIGT |
| 17 | `top Hybrid weight without ears (g)` | 21 | BESTÄTIGT |
| 18 | `bottom Hybrid weight (g) with ears` | 0 | BESTÄTIGT |
| 19 | `bottom Hybrid ears weight (g)` | 0 | BESTÄTIGT |
| 20 | `bottom Hybrid weight without ears (g)` | 22 | BESTÄTIGT — durchgängig `0,000` |
| 21 | `Module weight after gluing all hybrids (g)` | 11 | BESTÄTIGT |
| 22 | `Modul Target weight (mg)` | 21 | BESTÄTIGT (Beschriftungs-Tippfehler „Modul" ist echt) |
| 23 | `Tolerance (mg)` | 22 | BESTÄTIGT |
| 24 | `all Hybrid glue weight (mg)` | 22 | BESTÄTIGT |
| 25 | `Adhesive weight result hybrid (Klebegewicht Ergebnis)` | 11 | BESTÄTIGT |
| 26 | `Hybrid glue date` | **1** | BESTÄTIGT als Datum (`2026-06-17`), aber praktisch ungenutzt |
| 27 | `Hybrid glue sample` | 10 | BESTÄTIGT (`20USEGT0000089`, `20USEGT0000098`) — bei TUDO **reiner Code**, kein `TB_<Datum>, <Code>` wie bei DESYZ |
| 28 | `Hybrid glue jigs used, top, bottom` | 20 | **KORRIGIERT** — **ein** Code je Zelle, nicht zwei |
| 29 | `Hybrid pickups used, top, bottom` | 20 | **KORRIGIERT** — dito |
| 30 | `Module jig used` | 14 | BESTÄTIGT |
| 31 | `SCRIPT: Hybrids assembled to module (in DB)` | 22 | BESTÄTIGT |

### Band `Gluing Powerboard with TRUE BLUE - False blue` — Zeilen 32–45
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 32 | `Glued by - Name` | **0** | BESTÄTIGT |
| 33 | `Powerboard Label` | **0** | BESTÄTIGT |
| 34 | `Powerboard SN` | 11 | BESTÄTIGT |
| 35 | `Powerboard weight (g)` | **5** | BESTÄTIGT |
| 36 | `Powerboard glue date` | 0 | BESTÄTIGT |
| 37 | `Powerboard glue sample` | 9 | BESTÄTIGT |
| 38 | `Powerboard glue jig, pickup tool` | 7 | BESTÄTIGT (zwei Codes je Zelle) — Trennung **uneinheitlich**: `…, …` und `…,…`; eine Zelle enthält `20USERT0510211,` (Hybrid-Pickup + Komma, offensichtlicher Fehleintrag) |
| 39 | `SCRIPT: Powerboard assembled to module (in DB)` | 22 | BESTÄTIGT (`OK` / `N/A` / `not correct yet`) |
| 40 | `Module weight after gluing powerboard AND hybrid` | 10 | BESTÄTIGT |
| 41 | `Target weight (mg)` | 22 | BESTÄTIGT |
| 42 | `Tolerance (mg)` | 22 | BESTÄTIGT |
| 43 | `Powerboard glue weight (...mg)` | 21 | BESTÄTIGT (Beschriftung wörtlich mit `(...mg)`) — **eine Zelle ist leer statt berechnet**, dort wurde die Formel gelöscht |
| 44 | `Adhesive weight result powerboard (Klebegewicht Ergebnis)` | 13 | BESTÄTIGT |
| 45 | `SCRIPT: Glue weights uploaded, stage set to GLUED` | 22 | BESTÄTIGT |

### Band `Measure` — Zeilen 46–51
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 46 | `Visual Inspection Photo` | 0 | BESTÄTIGT |
| 47 | `Bow Metrology` | 22 | BESTÄTIGT — **ausnahmslos** `Messung fehlt!` |
| 48 | `Bow Metrology Date` | 22 | BESTÄTIGT — ausnahmslos `---` |
| 49 | `Metrology outcome` | 22 | BESTÄTIGT — ausnahmslos `Messung fehlt!` |
| 50 | `Metrology date` | 22 | BESTÄTIGT — ausnahmslos `---` |
| 51 | `Metrology results uploaded to DB?` | 22 | BESTÄTIGT (21× `not correct yet`, 1× `OK`) |

### Band `Module stitching` — Zeilen 52–53
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 52 | `Half module sibling (only R3-R5)` | 0 | BESTÄTIGT |
| 53 | `SCRIPT: Complete module registered to DB` | 22 | BESTÄTIGT + ERGÄNZT: neben `not ready` / `Module is ring module` kommt auch eine echte SN vor (`20USEM50000336`) |

### Band `BONDED` — Zeilen 54–59 · **Bandgrenze KORRIGIERT**
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 54 | `Visual Inspection Photo` | 0 | BESTÄTIGT |
| 55 | `Module bond date` | 22 | BESTÄTIGT (`-` bzw. `13.01.2026`) |
| 56 | `Visual Inspection FE bonds (officially optional)` | 0 | BESTÄTIGT |
| 57 | `IV after bonding` | 22 | BESTÄTIGT |
| 58 | `DAQ Quick test` | 22 | BESTÄTIGT |
| 59 | `UBC Uploader: quick electrical test passed` | 0 | BESTÄTIGT |

### Band `TESTED` — Zeilen 60–61 · **KORRIGIERT**
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 60 | `DAQ TC test (incl. IV)` | 22 | **KORRIGIERT** — die Abschrift ordnet diese Zeile `BONDED` zu; sie steht in `TESTED` |
| 61 | `UBC Uploader: thermal cycling electrical tests passed` | 0 | BESTÄTIGT |

### Band `FINISHED MODULE` — Zeilen 62–65 · **ERGÄNZT (fehlte für TUDO)**
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 62 | `Visual Inspection photo` | 0 | ERGÄNZT |
| 63 | `Packing date (box, humi, silica, bag)` | 0 | ERGÄNZT |
| 64 | `Shipping date (peli case)` | 0 | ERGÄNZT |
| 65 | `add to this batch by zFlow` | 22 | ERGÄNZT — Dropdown, bei TUDO **durchgängig** `bitte wählen`; kein einziges Modul ist einem Batch zugeordnet |

### Band `FINISHED` — Zeile 66 · **ERGÄNZT**
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 66 | `Finished` | 22 | ERGÄNZT — 19× `not ready yet`, 3× `finished` |

### Band `Shipment status` — Zeile 67 · **ERGÄNZT**
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 67 | `for info` | 2 | ERGÄNZT — Format `2026-05-19, delivered, UNIFREIBURG` |

### Band `zFlow Processing` — Zeilen 68–69 · **ERGÄNZT + KORRIGIERT**
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 68 | `Last update` | **0** | ERGÄNZT — bei TUDO **leer** (bei DESYZ ISO-Zeitstempel) |
| 69 | `Next update` | **0** | ERGÄNZT — dito |

### Band `UBC Uploader` — Zeilen 70–71 · **ERGÄNZT**
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 70 | `UBC Uploader: quick electrical test passed` | 0 | ERGÄNZT — **Dublette** zu Zeile 59 |
| 71 | `UBC Uploader: thermal cycling electrical tests passed` | 0 | ERGÄNZT — **Dublette** zu Zeile 61 |

### Zeilen 72–73
| Z. | Beschriftung | gefüllt | Abgleich |
|---|---|---|---|
| 72 | (leere Trennzeile) | 0 | — |
| 73 | Band `Comments`, keine Beschriftung in B | **0** | ERGÄNZT — das Band existiert auch bei TUDO, ist aber **leer**. Das operative Wissen aus der Abschrift („MASSIVE tilt…") steht im DESYZ-Blatt, **nicht** hier. |

### Zusatz: die **alte** Zeilenstruktur (T4, T11)
Die Blätter T4 (`Hide Finished`) und T11 (`R3`) haben 66 Zeilen und eine
abweichende zweite Blatthälfte. **ERGÄNZT** — das ist exakt die Struktur, die die
Abschrift als „DESYZ-Zusatzzeilen" führt:

- `BONDED` (Z. 54–60): `HV/GND bond & Post-glue IV (officially optional)`,
  `PB-Hy bond date`, `DAQ functional test`, `Hybrid frontend (FE) bond`,
  `Visual Inspection FE bonds (officially optional)`,
  `Bond data (could be e.g. Row Test or something else)`, `DAQ module test`
- `TESTED` (Z. 61–62): `IV after bonding`, `Visual Inspection photo`
- `FINISHED MODULE` (Z. 63–64), `FINISHED` (Z. 65), Kommentarzeile (Z. 66)

In T4 steht in dieser Kommentarzeile wörtlich:
> „Modul wieder auf failed, diesmal aber richtigerweise da subsequent tests
> gefailed sind"

T15 (Testbeam 2023) zeigt eine **dritte** Variante mit den Zeilen
`reception IV` (ohne `, in DB?`), `SCRIPT: Reception`,
`Hybrid panel & position`, `Hybrids SNs` (ohne `(top, bottom)`) und dem Band
`Gluing Hybrids with TRUE BLUE` (ohne `- False blue`).
→ **Die Zeilenstruktur ist historisch gewachsen und existiert in drei Fassungen
gleichzeitig in einer Datei.** Für itkFlow heißt das: die Zeilenliste ist kein
Standard, sondern ein Institutsprofil mit Versionsstand.

---

## 3 — Referenzblatt „Daten" (T8) vollständig, Zelle für Zelle

15 Spalten (A–O), 38 belegte Zeilen. Der Export war hier **nicht** gekappt.

### 3.1 Hybrid → Chipbestückung · A1:C11 · **BESTÄTIGT**

| Zeile | Hybrid | Amount ABC | Amount HCC |
|---|---|---|---|
| 2 | R0H0 | 8 | 1 |
| 3 | R0H1 | 9 | 1 |
| 4 | R1H0 | 10 | 1 |
| 5 | R1H1 | 11 | 1 |
| 6 | R3H0 | 7 | 0 |
| 7 | R3H1 | 7 | 2 |
| 8 | R3H2 | 7 | 0 |
| 9 | R3H3 | 7 | 2 |
| 10 | R5H0 | 9 | 0 |
| 11 | R5H1 | 9 | 2 |

Alle zehn Zeilen stimmen mit der Abschrift überein. **Es gibt keine elfte Zeile.**

### 3.2 Chip → UV-Klebemenge · E1:G3 · **BESTÄTIGT**

| Chip | UV-Klebemenge | Tolerance |
|---|---|---|
| ABC | 0,0042 | 0,00025 |
| HCC | 0,0015 | 0,0001 |

### 3.3 „Module Glueing with POLARIS" · A14:G22 · **KORRIGIERT**

Kopfzeile 15 wörtlich: `Module Type`, `Target weight without PB[mg]`,
`Tolerance[mg]`, `Powerboard Target weight [mg]`, `Tolerance[mg]`,
`Total Glue Target weight [mg]`, `Tolerance[mg]`.

| Zeile | Module Type | Target o. PB | Tol. | PB-Target | Tol. | Total | Tol. |
|---|---|---|---|---|---|---|---|
| 16 | R0M0 | 217 | 33 | 79 | 12 | 296 | 45 |
| 17 | R1M0 | 293 | 44 | 79 | 13 | 372 | 57 |
| 18 | R3M0 | 187 | 28 | 148 | 22 | 335 | 50 |
| 19 | R3M1 | 217 | 33 | 0 | 0 | 217 | 33 |
| 20 | R5M0 | 127 | 19 | 97 | 15 | 224 | 34 |
| 21 | R5M1 | 142 | 21 | 0 | 0 | 142 | 21 |
| **22** | **R2** | *(leer)* | *(leer)* | *(leer)* | *(leer)* | *(leer)* | *(leer)* |

**KORRIGIERT:** Die POLARIS-Tabelle hat **sieben** Zeilen. Zeile 22 trägt in A
den Typ `R2`, die Werte B22:G22 sind **leer**. Die Abschrift kennt diese Zeile
nicht. Bedeutung: **für R2 gibt es keine POLARIS-Zielwerte** — R2 wird
ausschließlich mit TrueBlue/FalseBlue geklebt. Ein Institutsprofil in itkFlow
muss „Zielwert für diese Kombination existiert nicht" abbilden können.

Alle Summen sind konsistent: Total = Target + PB-Target, Tol. = Tol. + Tol.

### 3.4 „Module Glueing with True Blue / False Blue" · A24:G32 · **BESTÄTIGT + 1 Fund**

| Zeile | Module Type | Target o. PB | Tol. | PB-Target | Tol. | Total | Tol. |
|---|---|---|---|---|---|---|---|
| 26 | R0 | 230 | 35 | 84 | 13 | 314 | 48 |
| 27 | R1 | 311 | 46 | 84 | 13 | 395 | 59 |
| 28 | R3M0 | 198 | 30 | 157 | 23 | 355 | 53 |
| 29 | R3M1 | 231 | 35 | 0 | 0 | 231 | 35 |
| 30 | R5M0 | 135 | 20 | 103 | 16 | 238 | 36 |
| 31 | R5M1 | 151 | 22 | 0 | 0 | 151 | 22 |
| 32 | **R2** | **164** | **25** | **70** | **11** | **234** | **22** |

Zahlen exakt wie in der Abschrift. **Neuer Fund:** In allen Zeilen gilt
`Total-Toleranz = Toleranz + PB-Toleranz` (35+13=48, 46+13=59, 30+23=53,
35+0=35, 20+16=36, 22+0=22). **Nur bei R2 nicht:** 25+11 = 36, im Blatt steht
**22** — vermutlich ein Kopierfehler aus der Zeile R5M1 darüber. Der Wert wird
im Modulblatt nicht benutzt (dort werden nur B und C bzw. D und E gelesen), ist
also folgenlos — aber er darf nicht in ein itkFlow-Institutsprofil übernommen
werden.

Die Beobachtung der Abschrift („zwei Klebeverfahren, zwei Zieltabellen") ist
**BESTÄTIGT**; die Zuordnung der Zeilen 26–31 auf `Daten!$B$26 … $B$31` ist
durch die dokumentierte Formel (§3.9) belegt.

### 3.5 Mischungsrechner · zwei Instanzen · **BESTÄTIGT + Formel rekonstruiert**

**Untere Instanz** — Titel `Gluing with TrueBlue/FalseBlue` (I14:M14 verbunden),
Kopf in Zeile 15, Werte in Zeile 16:

| `Hardener TB\FB [g]` | `required Epoxy [g]` | `Total weight [g]` | `Erreichtes Gesamtgewicht [g]` | `Erreichtes Mischungsverhältnis [%]` |
|---|---|---|---|---|
| 0,3 | 1 | 1,3 | 2,1688 | 166,83 |

Zusätzlich steht in **O16** der unbeschriftete Wert **2,0213** — in der Abschrift
nicht enthalten. **ERGÄNZT**; Bedeutung nicht rekonstruierbar.

**Obere Instanz** — Kopf I12:M12, Werte I13:M13:

| `required Epoxy (soll 1,666g)` | `calculated hardener` | `achieved hardener` | `calculated total weight achieved` | `Mixing ratio achieved in %` |
|---|---|---|---|---|
| 0,0894 | 0,0268 | 0,48 | 0,5694 | 489,9329 |

**Rekonstruierte Rechnung** (beide Instanzen, numerisch bestätigt):
```
calculated hardener            = required Epoxy × 0,3
Total weight / calc. total     = required Epoxy × 1,3     (= Epoxy + Hardener)
calculated total weight achieved = required Epoxy + achieved hardener
Mischungsverhältnis [%]        = erreichtes Gesamtgewicht / (required Epoxy × 1,3) × 100
```
Proben: `0,0894 × 0,3 = 0,02682` ✓ · `0,0894 + 0,48 = 0,5694` ✓ ·
`0,5694 / (0,0894 × 1,3) × 100 = 489,93` ✓ · `2,1688 / 1,3 × 100 = 166,83` ✓.
Das Sollmischungsverhältnis Hardener:Epoxy ist damit fest **0,3 : 1**.

### 3.6 „True Blue - Klebemenge (bzgl. Hardener!!): fuer ca 3 Klebungen" · I24:K31 · **BESTÄTIGT**

Titel wörtlich mit Doppelpunkt (die Abschrift lässt ihn weg).

| Module Type | Hybrid | Powerboard |
|---|---|---|
| R0 | 0,3g | 0,2g |
| R1 | 0,36g | 0,2g |
| R3M0 | 0,25g | 0,25g |
| R3M1 | 0,3g | `-------------------` |
| R5M0 | 0,25g | 0,21g |
| R5M1 | 0,25g | `-------------------` |

Kein R2-Eintrag. **ERGÄNZT:** Diese Tabelle ist für TUDOs Hauptprodukt
(R2, R5M0, R5M1) also nur zu zwei Dritteln nutzbar — für R2 fehlt die
Ansatzmenge.

### 3.7 „Klebemengenkorrektur fuer Klebeprogramme." · I19:O21 · **BESTÄTIGT**

Titel wörtlich mit abschließendem Punkt. Kopf in Zeile 20, eine Datenzeile 21:

| Module Type | soll Klebegewicht | IST-Klebegewicht | Line Speed 1 | Line Speed 2 | new Line Speed 1 | new Line Speed 2 |
|---|---|---|---|---|---|---|
| `R1 PB` | 84 | 100 | 17 | 3,5 | 20,23809524 | 4,166666667 |

**Rechnung bestätigt:** `neu = alt × IST / soll`
(`17 × 100/84 = 20,238095…` ✓, `3,5 × 100/84 = 4,1666…` ✓).
Die Abschrift markierte das als „zu bestätigen" — hiermit **bestätigt**.
`Module Type` ist die einzige Eingabe, die als Dropdown gekennzeichnet war; der
gespeicherte Wert `R1 PB` ist ein Beispiel, kein Betriebsstand.

### 3.8 Dropdown-Listen · Zeilen 34–38 · **BESTÄTIGT + ERGÄNZT**

Drei beschriftete Listen (Beschriftung in A34/F34/J34):

| Beschriftung (wörtlich) | Werte |
|---|---|
| `Formel abhängige Dropdownliste für Hybridjig:` | D34:D37 = **4, 5, 7, 8** |
| `Formel abhängige Dropdownliste für Chip Tray:` | I34:I38 = **1, 5, 6, 8, 12** |
| `Formel abhängige Dropdownliste für PickUpTool:` | M34:M37 = **4, 5, 7, 8** |

**BESTÄTIGT** — identisch zur Abschrift.

**ERGÄNZT — drei weitere Listen, die die Abschrift nicht kennt** (Beschriftung in
A36/F36/J36, jeweils einwertig):

| Beschriftung (wörtlich) | Wert |
|---|---|
| `Dropdownliste von D13/21:` | C36 = 5 |
| `Dropdownliste von I13/22:` | H36 = 8 |
| `Dropdownliste von M13/22:` | L36 = 8 |

Die Zellbezüge `D13/21`, `I13/22`, `M13/22` verweisen auf das Blatt T9
(„Tool-Kombi-Beispiele"), dessen Spalten D/I/M `PickUpTool`, `PB-jig` und
`Moduljig` sind. Diese Listen sind also die **Werkzeugauswahl für die
Kombi-Empfehlungen**, nicht für das Modulblatt.

### 3.9 **Die R2H0-Frage — beantwortet**

**Ergebnis: `R2H0` kommt in der gesamten Datei kein einziges Mal vor.**
Volltextsuche über alle 18 Blätter: 0 Treffer für `R2H0`, 0 für `R2H`, 0 für
`R2M`. `R2` erscheint ausschließlich (a) als Wert der Dropdown-Zeile
`Module Type` in den Modulblättern und (b) zweimal im Blatt „Daten": in **A22**
(POLARIS, Werte leer) und **A32** (TrueBlue, Werte gefüllt).

**Es ist kein Übersehen und kein anderer Mechanismus — die Tabelle in §3.1 ist
schlicht nicht für Module zuständig.** Der Nachweis:

1. Die Tabelle §3.1 wird von den **Hybridblättern** gelesen, nicht von den
   Modulblättern. Die Formel im Blatt selbst sagt das wörtlich:
   `WENN(C3="R5H1",Daten!$B$11,…)` — `C3` ist auf einem Hybridblatt die Zeile
   `Hybrid Type`, `Daten!$B$11` ist die Zeile `R5H1` der Chiptabelle.
2. Numerisch verifiziert auf T1 (Panel PPA): `Target weight (mg)` =
   `Amount ABC × 4,2 + Amount HCC × 1,5`. Proben: R0H0 `8×4,2+1×1,5 = 35,1` ✓ ·
   R1H1 `11×4,2+1×1,5 = 47,7` ✓ · R3H1 `7×4,2+2×1,5 = 32,4` ✓ ·
   R5H0 `9×4,2 = 37,8` ✓ · R5H1 `9×4,2+2×1,5 = 40,8` ✓.
   `Tolerance (mg)` = `ABC × 0,25 + HCC × 0,1` (2,1 / 2,85 / 1,95 / 2,25 / 2,45) ✓.
   → Die Tabelle §3.1 beschreibt das **Kleben der ASICs auf den Hybrid**
   (Hybridpanel-Fertigung).
3. **TUDO klebt keine ASICs.** Die Hybridblätter dieser Datei (T1, T2, T14)
   enthalten ausschließlich Zeuthener Panels (`DZHU-PPA-…`, `DZHU-PPB-…`,
   `Current location = DZHU`) mit Klebedaten aus 2023. TUDO kauft fertige
   Hybride zu (`20USEH4…`, `20USEHB…`, `20USEHC…`) und klebt sie auf den Sensor.
4. Die Modul-Zielwerte kommen aus der **TrueBlue-Tabelle** (§3.4), und die
   **hat** eine R2-Zeile. Verifiziert im Livebetrieb: jede R2-Spalte in T5 zeigt
   `Modul Target weight = 164`, `Tolerance = 25`, `Target weight (PB) = 70`,
   `Tolerance = 11` — exakt `Daten!B32:E32`.

**Konsequenz für itkFlow:** Der Spiegel der Produktionsdatenbank (`R2H0`,
12 ABC + 2 HCC) ist korrekt und die „Daten"-Tabelle ist korrekt — sie
beschreiben verschiedene Dinge. Ein Institutsprofil braucht **zwei getrennte
Tabellen**: Chip-Klebeziele je Hybridtyp (nur für Institute mit
Hybrid-Bestückung) und Modul-Klebeziele je Modultyp × Klebeverfahren. TUDO
braucht nur die zweite. Wer die Chiptabelle für TUDO pflegen will, findet dort
korrekterweise keine R2-Zeile.

**Zusatzfund, der die Chiptabelle relativiert:** Das neuere Hybridblatt T2 (PPB)
rechnet **mit anderen Konstanten** als die „Daten"-Tabelle:

| | Daten-Tabelle / T1 (PPA) | T2 (PPB) |
|---|---|---|
| ABC | 4,2 mg | 4,2 mg |
| HCC | **1,5 mg** | **1,8 mg** |
| Toleranz | `ABC×0,25 + HCC×0,1` | **10 % des Zielwerts** |
| Toleranzart | beidseitig | **`Tolerance (mg) (only lower bound since 2023-10-24)`** |

Belegt am selben Hybridtyp: R1H0 (10 ABC, 1 HCC) hat auf T1 ein Ziel von
**43,5** mg (`10×4,2+1×1,5`), auf T2 **43,8** mg (`10×4,2+1×1,8`); die Toleranz
dort ist `4,38` = 10 % von 43,8. Analog R3H1: 32,4 vs. 33,0 (Toleranz 3,3).
→ **Die „Daten"-Tabelle ist nicht die einzige Wahrheit; sie bildet den älteren
Stand ab.** Und: seit 2023-10-24 ist die Chip-Klebetoleranz **einseitig** (nur
Untergrenze) — zu viel Kleber ist zulässig. **ERGÄNZT**, in keinem unserer
Dokumente bisher enthalten.

---

## 4 — Formeln

### 4.1 Wörtlich im Blatt dokumentiert (I1:N1 verbunden: `Formeln bitte nicht löschen!!!!!!!`)

Alle sechs Einträge stimmen **zeichengenau** mit der Abschrift überein —
**BESTÄTIGT**:

```
I3  Beispiel Formel Chipmenge:
J3    WENN(C3="R5H1",Daten!$B$11,WENN(C3="bitte wählen","Hybrid auswählen!"))

I4  Beispiel Formel Modul-Klebegewicht:
J4    WENN(C3="R0",Daten!$B$26,WENN(C3="R1",Daten!$B$27,WENN(C3="R3M0",Daten!$B$28,
      WENN(C3="R3M1",Daten!$B$29,WENN(C3="R5M0",Daten!$B$30,WENN(C3="R5M1",Daten!$B$31,
      WENN(C3="bitte wählen","0"))))))

I5  Beispiel Formel Klebeziel:      J5   (B2*4.2)+(C2*1.5)
I6  Beispiel Formel Tolerance:      J6   (B2*0.25)+(C2*0.1)
I7  Beispiel Klebegewicht:          J7   (C23-(C22-C21)-C20)*1000
I9  Beispiel Dropdown(eng)          J9   84
```

**Neu zugeordnet — und das ist wichtig:**

- **`Beispiel Klebegewicht: (C23-(C22-C21)-C20)*1000` ist NICHT die
  Modul-Klebegewichtsformel.** Sie gehört auf das **Hybridblatt**. Auf T1 sind
  Zeile 20 = `Hybrid Bare weight (g) with ears`, Zeile 21 = `Empty tray weight (g)`,
  Zeile 22 = `Asics with Tray weight (g)`, Zeile 23 =
  `Hybrid with Asics (and ears) weight (g)`. Die Formel lautet damit
  „Hybrid-mit-ASICs − (Tray-mit-ASICs − Leertray) − Hybrid-bare".
  Numerisch geprüft an DZHU-PPA-R0H0-01:
  `1,5321 − (5,3733 − 5,0349) − 1,1575 = 0,0362 g = 36,2 mg` — exakt der
  Blattwert. **KORRIGIERT** gegenüber der Annahme, dies sei die Modulkette.
  (Nebeneffekt: dieser Treffer beweist, dass Grid-Index = echte Blattzeile ist,
  worauf alle Zeilennummern in diesem Dokument beruhen.)
- **`Beispiel Formel Klebeziel` / `… Tolerance`** operieren auf den
  Daten-Spalten B/C der Chiptabelle (`B2=8`, `C2=1` → 35,1 bzw. 2,1), sind also
  ebenfalls **Hybrid**-Formeln.
- **`Beispiel Formel Modul-Klebegewicht`** ist trotz des Namens die
  **Zielwert-Auswahl**, nicht das Klebegewicht: sie liest `Daten!$B$26…$B$31`,
  also Spalte B der TrueBlue-Tabelle.
- **Die dokumentierte Formel hat keinen R2-Zweig.** Sie endet bei `R5M1` und
  fängt sonst nur `"bitte wählen"` ab. Das Livebeispiel ist **veraltet**: das
  aktive Blatt T5 liefert für R2 korrekt 164/25, die dort eingesetzte Formel
  wurde also um einen `WENN(C3="R2";Daten!$B$32;…)`-Zweig erweitert.
  **Beweis, dass es genau diese Kette ist:** im Blatt T4 (`Hide Finished`, alter
  Stand) zeigen die R2-Spalten in `Modul Target weight (mg)` und
  `Target weight (mg)` den Wert **`FALSE`** — genau das Ergebnis einer
  verschachtelten `WENN`-Kette, die durchfällt. **ERGÄNZT.**

### 4.2 Rückgerechnet und an Echtdaten verifiziert

Der Export liefert keine Zellformeln. Die folgenden Beziehungen sind aus den
Livewerten von T5 abgeleitet und an **allen** vollständig gefüllten Spalten
geprüft (Zeilennummern = T5):

**Hybrid-Klebegewicht (Zeile 24)** — die Rekonstruktion aus der Abschrift ist
**BESTÄTIGT**:
```
Z24 = (Z21 − Z10 − Z17 − Z20) × 1000
    = (Module weight after gluing all hybrids
       − Sensor weight with tab
       − top Hybrid weight without ears
       − bottom Hybrid weight without ears) × 1000   [mg]
```
Proben (Sensor / top / Modul → Ergebnis):
`7,0162 / 2,233 / 9,3819 → 133` ✓ · `5,773 / 3,082 / 9,01 → 155` ✓ ·
`5,72 / 3,161 / 9,081 → 200` ✓ · `7,007 / 2,140 / 9,265 → 118` ✓ ·
`7,012 / 2,838 / 9,984 → 134` ✓ · `6,994 / 2,243 / 9,349 → 112` ✓ ·
`6,9901 / 2,202 / 9,3043 → 112` ✓ · `7,0318 / 2,8789 / 10,0475 → 137` ✓.

**Powerboard-Klebegewicht (Zeile 43)** — ebenfalls **BESTÄTIGT**:
```
Z43 = (Z40 − Z21 − Z35) × 1000
    = (Module weight after gluing powerboard AND hybrid
       − Module weight after gluing all hybrids
       − Powerboard weight) × 1000                   [mg]
```
Proben: `12,764 − 9,3819 − 3,286 → 96` ✓ · `11,666 − 9,081 − 2,486 → 99` ✓ ·
`12,5718 − 9,265 − 3,195 → 112` ✓ · `12,736 − 9,349 − 3,2473 → 140` ✓ ·
`12,6803 − 9,3043 − 3,2458 → 130` ✓.

**Kein Schutz gegen leere Eingaben.** Beide Formeln behandeln leere Zellen als 0
und rechnen weiter. Daher die von der Abschrift beobachteten Unsinnswerte:
`−9010`, `−9886`, `−10048`, `11439`, `12789`, `9916`, `9970`. Die Abschrift
deutete sie richtig als „fehlende Eingangsgrößen" — **BESTÄTIGT**, jetzt exakt:
es ist immer `± (fehlende Waagenwerte) × 1000`.

**Zielwerte und Toleranzen** (verifiziert an allen 21 Modulspalten):
```
Z22 (Modul Target weight)   ← Daten!B26:B32, ausgewählt über Z3 (Module Type)
Z23 (Tolerance)             ← Daten!C26:C32
Z41 (Target weight PB)      ← Daten!D26:D32
Z42 (Tolerance PB)          ← Daten!E26:E32
```
Beobachtete Paare: `R5M1 → 151/22` und `0/0`, `R5M0 → 135/20` und `103/16`,
`R2 → 164/25` und `70/11`. **BESTÄTIGT** — das Blatt liest ausschließlich die
**TrueBlue**-Tabelle; die POLARIS-Tabelle wird im TUDO-Betrieb nirgends
referenziert.

**Urteilsformel (Zeilen 25 und 44)** — neu rekonstruiert, **ERGÄNZT**:
```
= WENN(Klebegewicht = 0; "";
    WENN(Klebegewicht > Ziel + Toleranz; "zu viel";
      WENN(Klebegewicht < Ziel − Toleranz; "zu wenig"; "OK")))
```
Belege: `133` gegen `135±20` → `OK` ✓ · `200` gegen `164±25` → `zu viel` ✓ ·
`112` gegen `135±20` → `zu wenig` ✓ · `118` gegen `135±20` → `OK`
(Untergrenze 115) ✓ · `9916` gegen `151±22` → `zu viel` ✓.
Der Nullwert-Wächter ist an allen elf leeren Urteilszellen bestätigt: überall
dort ist das Klebegewicht exakt `0`, während Spalten mit `0`-Ziel und
Klebegewicht ≠ 0 sehr wohl ein Urteil zeigen. **Der Wächter prüft das Ergebnis,
nicht die Eingaben** — deshalb entstehen die Unsinnsurteile in §5.

**Line-Speed-Korrektur** (§3.7): `neu = alt × IST / soll` — **BESTÄTIGT**.

**Mischungsrechner** (§3.5): vier Formeln rekonstruiert — **ERGÄNZT**.

**Nicht rekonstruierbar** (Werte allein reichen nicht):
`Bow Metrology`, `Metrology outcome`, `Metrology date` (alle Werte identisch,
siehe §6), sowie sämtliche `SCRIPT:`-Zeilen — die schreibt zFlow, sie sind keine
Formeln.

---

## 5 — Skalierung: was wirklich benutzt wird

### Modulspalten

| Blatt | Modulspalten | davon benannt | Bemerkung |
|---|---|---|---|
| **T5 (aktiv)** | **22** | **21** | + 1 Platzhalter `Bitte Modul auswählen` |
| T6 | 290 | 7 | aber **263 Sensor-IDs** vorbelegt |
| T3 | 89 | 0 | leere Vorlage |
| T4 | 5 | 4 | Test-/Restblatt |
| T11 | 8 | 0 | `#REF!` |
| T15 | 104 | 67 | Testbeam 2023 |

Das produktive Blatt ist also **klein**: 21 Module. Die 290 Spalten in T6 sind
kein Produktionsstand, sondern ein **Sensorpool**: Spalten 1–265 tragen
Sensor-IDs (263 Stück, 258 verschieden, 4 doppelt), aber nur 7 haben einen
Modulnamen. `Current location` ist dort in 288 Spalten `TUDO` — das ist der
**Standort des Sensors**, nicht des Moduls (die zwei Spalten ohne Sensor zeigen
`-`). Aufteilung der Pool-Sensoren: **86 × `20USES2…`** (R2) und
**177 × `20USES5…`** (R5). Das deckt sich mit der bekannten TUDO-Planzahl von
81 R2-Modulen. **ERGÄNZT.**

### Verteilungen im aktiven Blatt T5 (21 Module)

| Merkmal | Verteilung |
|---|---|
| `Module Type` | R5M1 **8**, R5M0 **8**, R2 **5** |
| `SCRIPT: current stage` | `STITCH_BONDING` 7, `FAILED` 6, `GLUED` 4, `HV_TAB_ATTACHED` 2, `ON_CORE` 1, leer 1 |
| `Current location` | `TUDO` 20, `UNIFREIBURG` 1 |
| `IV after tabbing passed?. in DB?` | `OK` 19, `not tested/passed yet` 2 |
| `SCRIPT: Hybrids assembled…` | `OK` 17, `not correct yet` 4 |
| `SCRIPT: Powerboard assembled…` | `OK` 13, `N/A` 8 |
| `SCRIPT: Glue weights uploaded…` | `OK` 21 |
| `Metrology results uploaded to DB?` | `not correct yet` 20, `OK` 1 |
| `SCRIPT: Complete module registered` | `not ready` 15, `Module is ring module` 5, 1 echte SN |
| `IV after bonding` | `not tested or not passed yet` 19, `OK` 2 |
| `DAQ Quick test` | `not tested or not passed yet` 13, `OK` 8 |
| `DAQ TC test (incl. IV)` | `not tested or not passed yet` 15, `OK` 6 |
| `Finished` | `not ready yet` 18, `finished` **3** (alle drei sind R2-Module) |
| `add to this batch by zFlow` | `bitte wählen` **21/21** |

### Klebeurteile — und wie viele davon Müll sind · **KORRIGIERT/ERGÄNZT**

| | Hybrid (Z. 25) | Powerboard (Z. 44) |
|---|---|---|
| angezeigte Urteile | 11 | 13 |
| davon mit **vollständigen** Eingaben | **9** | **5** |
| davon Artefakte aus leeren Zellen | 2 | **8** |
| gültige Urteile | `OK` 6, `zu wenig` 2, `zu viel` 1 | `OK` 2, `zu viel` 3 |

Die Abschrift zählte die Urteile als Betriebsergebnis. Tatsächlich sind
**8 der 13 Powerboard-Urteile** reine Rechenartefakte (fehlendes
`Module weight after gluing powerboard AND hybrid` oder fehlendes
`Powerboard weight`, siehe §4.2). Belastbar sind:
**9 vollständige Hybrid-Klebeprotokolle und 5 vollständige
Powerboard-Klebeprotokolle bei 21 Modulen.** Das ist die eigentliche
Datenlage — nicht 21.

### Leere Zeilen

Das Blatt hat 73 Zeilen. **26 davon sind in allen 22 Spalten leer** (Z. 6, 7, 8,
13, 15, 16, 18, 19, 32, 33, 36, 46, 52, 54, 56, 59, 61, 62, 63, 64, 68, 69, 70,
71, 72, 73); Z. 72 ist eine reine Trennzeile, Z. 73 trägt nur die Bandüberschrift
`Comments`. Es bleiben **24 beschriftete Zeilen, die nie einen Wert tragen**.
Also: **rund ein Drittel des Blatts ist Dekoration.** Insbesondere sind
**alle** Foto-/Sichtprüfungszeilen leer, **alle** „mit Ohren"-Wiegezeilen leer
(Z. 15/16/18/19 — TUDO wiegt Hybride nur fertig), **alle** Verpackungs- und
Versandzeilen leer, das Kommentarband leer und die `Glued by - Name`-Zeilen
leer. Die Metrologie-Zeilen sind formal gefüllt, tragen aber ausschließlich
Fehlermeldungen (§6).

---

## 6 — Was die Screenshots nicht zeigen konnten

### 6.1 Das zFlow-Ausgabeblatt T7 · **ERGÄNZT — der wichtigste Fund neben §3.9**

Ein eigenes Blatt mit **41 Maschinenfeldern** je Modul, 20 Zeilen (= 20 der 21
Module aus T5; die zweite `TUDO-R5M1-03`-Spalte fehlt und ist genau die Spalte
ohne `SCRIPT: current stage`). Feldnamen wörtlich, in Blattreihenfolge:

```
localName · sn · stage · currentLocation · updatedPropertiesFromDB · ringModuleSN
hybridAssociationStatus · powerboardStatus · addedToModuleBatches · gluedStageTests
metrologyTests · hvTabAttachTests · gluedStageTestsUploadOpt · stitchBondingVI
bondedStageTests · tcIVTest · sensorReceptionPassed · thermalCyclingTests
thermalCyclingNO · pureHalfModulePass · suggestToFailRingModule
suggestToFailHalfModule · url · shipmentInfo · quickElectricalTests
quickElectricalNO · wirebondingTestDate · lastUpdate · nextUpdate
powerboardReceptionTest · ivInfo · ivInfoBonded · bondedStageAndElectricalTestsPassed
<27.08.2026> · thermalCyclingTestsPassed_bareITSDAQ · thermalCyclingTestsPassed_UBCUploader
ubcUploaderResult_thermalCyclingTests · quickElectricalTestsPassed
quickElectricalTestsPassed_bareITSDAQ · quickElectricalTestsPassed_UBCUploader
ubcUploaderResult_quickElectricalTests · ringModuleStage
```

Beobachtungen:

- **Eine Kopfzelle ist zerstört:** an Position 34 steht statt des Feldnamens das
  Datum `27.08.2026`. Aus der Nachbarschaft ergibt sich, dass dort
  `thermalCyclingTestsPassed` stand.
- **Doppelte Modulnamen werden mit `.1` disambiguiert.** T5 enthält sechs
  Modulnamen doppelt (`TUDO-R5M1-01`, `TUDO-R2-01`, `TUDO-R5M1-02`,
  `TUDO-R5M0-01`, `TUDO-R5M1-03`, `TUDO-R5M0-02`); zFlow führt sie als
  `TUDO-R5M0-01.1`, `TUDO-R2-01.1` usw. **Der lokale Name ist im Blatt nicht
  eindeutig** — für itkFlow ein harter Constraint-Hinweis.
- **Eine Modul-SN kommt dreifach vor:** `20USE5R0000128` steht in drei Spalten
  (`TUDO-R5M1-03`, `TUDO-R5M0-02` und einer weiteren `TUDO-R5M1-03`). Ein
  Datenfehler, der im Blatt unentdeckt bleibt.
- **Die Statusfelder sind Fließtext, kein Enum.** Beispiele wörtlich:
  `ERROR! Hybrid 20USEHC0000208 is associated to module in DB, but not present in spreadsheet!` ·
  `Module type is R3M1, R4M1 or R5M1. Do not need to associate powerboard.` ·
  `All required glued-stage tests passed in stage GLUED` ·
  `The test MODULE_METROLOGY was not performed for module 20USE5L0000774!` ·
  `One of the required subtests for the ring-module failed. Suggesting to set stage to FAILED.`
  Die Texte enthalten Tabulatoren (`&#9;`) als Einrückung.
- **IV-Daten kommen als Python-Dict-Literal** in `ivInfo` / `ivInfoBonded`:
  `{'cold': {'index': 21, 'temperatureNTCY': -30.735998153686523, 'breakdownVoltage': 9.990000452351092e+37, 'currentAt200V': 15.34840202331543, 'voltageAt200V': -199.8300018310547}, 'warm': {…}}`.
  Der Wert `9.99e+37` ist der ITSDAQ-Sentinel für „keine Durchbruchspannung".
- `lastUpdate`, `nextUpdate`, `addedToModuleBatches` sind **in allen 20 Zeilen
  leer**, `updatedPropertiesFromDB` ist überall `{}`. Passend dazu sind die
  Zeilen 68/69 in T5 leer. **Das Blatt wird derzeit nicht mehr regelmäßig
  aktualisiert** — anders als bei DESYZ, wo dort Zeitstempel stehen.
- **Alle `url`-Werte zeigen auf `https://itkpd-test.unicorncollege.cz/componentView?code=…`.**
  Dieser Host existiert nicht mehr (siehe `docs/09-pdb-production-strategy.md`).
  **Sämtliche „in der DB öffnen"-Links im Blatt sind tot.** Derselbe Host steht
  auch in den Notizen des Kleber-Chargenblatts T17.
- `shipmentInfo` kommt in zwei Formaten vor:
  `2026-05-19T13:38:49.310Z, delivered, UNIFREIBURG` und `2026-05-19, delivered, UNIFREIBURG`.

### 6.2 Das Property-Hilfsblatt T12 · **ERGÄNZT — direkter PDB-Mapping-Fund**

Zeile 1 dieses Blatts trägt in den Spalten F–AH die **PDB-Property-Namen**, die
zFlow beim Hochladen der Klebegewichte setzt:

```
GW_GLUE_ASICS · GW_HYBRID_HT · GW_HYBRID_HTG · GW_HYBRID_HTGA · GW_ASIC
passed · with problems · date
GW_METHOD (Wert darunter: "dispenser") · GLUE_METHOD_V_H1 · GLUE_METHOD_V_H2 · GLUE_METHOD_V_PB
GW_SENSOR · GW_HYBRID1 · GW_GLUE_PB · GW_HYBRID2 · GW_MODULE_H1H2 · GW_GLUE_H1H2
GW_PB · GW_MODULE_H1H2PB · GW_GLUE_H1H2PB · GW_T1 · GW_T2
OK hybrids · OK PB · passed · with problems · Hybrid glue date
```

Die Namensfolge entspricht exakt der Zeilenfolge des Modulblatts
(`GW_SENSOR` ↔ Z. 10, `GW_HYBRID1` ↔ Z. 17, `GW_HYBRID2` ↔ Z. 20,
`GW_MODULE_H1H2` ↔ Z. 21, `GW_GLUE_H1H2` ↔ Z. 24, `GW_PB` ↔ Z. 35,
`GW_MODULE_H1H2PB` ↔ Z. 40, `GW_GLUE_H1H2PB` ↔ Z. 43). Der erste Block
(`GW_GLUE_ASICS`, `GW_HYBRID_HT/HTG/HTGA`, `GW_ASIC`) gehört zum
Hybrid-Klebetest. **Das ist die Brücke Blattzeile → PDB-Property**, die
`2026-08-26-sheet-to-pdb-map.md` bisher erschließen musste; sie sollte gegen
diese Liste geprüft werden.

Außerdem stehen in A1:C2 dieses Blatts ein Metrologie-Lookup mit den Testnamen
`Metrology_FAILED` / `Metrology_PASSED`, den Spaltenköpfen `test_name` /
`test_date` und **genau einem Datensatz**: `DZHU-PPB-R3M0-21`,
`2025-01-08 17:30:12`. Daneben, wörtlich:
`Last time entries were refreshed:` → **`03.03.2025 15:03:31`**.

**Damit ist erklärt, warum in T5 alle Metrologie-Zeilen `Messung fehlt!` und
`---` zeigen:** die Nachschlagetabelle enthält nur einen Zeuthener Altdatensatz
und wurde seit März 2025 nicht mehr befüllt. Gleichzeitig meldet T7 pro Modul
sehr wohl echte Metrologie-Ergebnisse (`The test MODULE_BOW did not pass for
module 20USEM20000195!`, `The test MODULE_METROLOGY did not pass for module
20USEM20000205!`). **Das Blatt zeigt also seit anderthalb Jahren eine
Fehlinformation an, während die Information danebensteht.** Das ist ein
konkreter, belegter Ausfallgrund für die Ablösung.

### 6.3 Werkzeug-Blätter T9, T10, T16 · **ERGÄNZT**

- **T9 „Tool-Kombi-Beispiele, die Metrology passed sind -"**: pro Hybridtyp
  (R0H0 … R5H1) und pro Powerboard-Typ (R0, R1, R3, R5) je zwei Zeilen mit
  `Hybrid.jig / Chiptray / PickUpTool / Moduljig` als **Nummern**, teils als
  Mengen (`1 & 4 & 9`, `3 & 4`, `2 & 3`), teils mit Unsicherheitsvermerk
  (`1?`, `3?`, `Tool-Kombi noch testen`, `(HCC-Ausschnitt rechts zu klein?)3`,
  `3 inkl. Shimming!!`). Das ist reines, ungesichertes Erfahrungswissen — genau
  die Sorte Information, die in itkFlow einen Platz braucht.
- **T10**: Werkzeug-RFIDs je Hybridtyp, gruppiert nach
  `Hybrid / PB Jig`, `Chip Tray`, `Pickup Tool`, `HV-Tab.jig`, `Modul.jig`,
  jeweils Paar (Nummer, RFID). Enthält auch Typen, die im Modulblatt gar nicht
  vorkommen: `R0SPB`, `R1SPB`, `R3SPB`, `R5SPB` sowie Sammelzeilen
  `R3H0 + R3H2`, `R3H1 + R3H3`, `R5H0 + PB`, `only R5H1`.
- **T16 Werkzeug-Inventar**: 125 Zeilen
  `For module | Type | Number on tool | Colour | SN` plus Regalort
  (`Shelf 0`–`Shelf 4`, `Table`, `In use`) und stellenweise RFID.
  `Type` ∈ {`Module jig`, `Hybrid Tray`, `Hybrid Tray w/ LEDs`,
  `Hybrid pickup tool`, `Powerboard Tray`, `Powerboard pickup`, `HV Tab jig`}.
  `Colour` ∈ {`orange`, `white`, `green`, leer}. Moduljigs für R3 tragen
  Nummern wie `MJR 05`, `MJL 07`.
  **Damit ist die Beobachtung der Abschrift erklärt**, das DESYZ-Blatt trage
  „Farbnamen statt PDB-Codes": Farbe und Nummer sind der **lokale Aufkleber**,
  die SN steht in diesem Inventar daneben. Kopfnotiz wörtlich:
  `Using this https://docs.google.com/spreadsheets/d/1_h4jXYvFp77ax2YceoDx50fQ9ufzK85aTRkqEfmIKgo/edit?gid=0#gid=0`
  → **eine zweite, externe Tabelle als Werkzeugquelle.**

### 6.4 Weitere Integrationspunkte und tote Verweise · **ERGÄNZT**

- **Kleber-Chargenblatt T17** (nur Kopfzeile, keine Daten):
  `Serial Number (ZFlow) | Stage (ZFlow) | Type | Batch Number | #bi-packs used |
  Manufacturing Date | Opening date (ZFlow) | Note`, dazu die Notizen
  `in databse : Batch als [TB] Batch und "Batch"` und
  `Expring data == Manuf. Date + 1y` (Tippfehler im Original).
  → Das Verfallsdatum eines Klebers ist **Herstelldatum + 1 Jahr**; die
  Chargenverwaltung war vorgesehen, wird aber **nicht** benutzt.
- **T18** ist eine unbenutzte Vorlage für Sensor-Sichtprüfungen mit
  **zehn** Schadensblöcken (`Damage Number / Location / Description / Type`).
- **T13** verweist auf eine Zeuthener Infrastruktur, die es bei TUDO nicht gibt:
  `http://gumato01:8080/overview` (generic control interface),
  `http://coldbox01:5555/`, `http://gumato01:5001/` (burnin GUI),
  `http://pidryesd01:8080/` (cleanroom logbook), `http://gumato01:8086/`
  (influxdb), `http://gumato01:3000/…` (coldbox grafana),
  `http://nbmess.zeuthen.desy.de:3000/…`, `http://gumato01.zeuthen.desy.de/IV_status/`,
  `http://pidryesd01.zeuthen.desy.de:8080/dlab/24`, plus Google-Docs-Anleitungen
  zu Powerboard Mass Tester, Hybrid burn-in und Sensor Visual Inspection.
  Die Zusammenfassungszellen unten (`Total passed VIs`, `Total failed VIs`,
  `Total VIs`) sind **`#REF!`**.
- **Datenvalidierung**, die der Export sichtbar macht: `Module Name`
  (Leerwert `Bitte Modul auswählen`), `Module Type` (Leerwert `bitte wählen`),
  `add to this batch by zFlow` (Leerwert `bitte wählen`; die Optionsliste selbst
  ist im Export nicht enthalten), sowie die sechs Werkzeuglisten aus §3.8.
- **Bedingte Formatierung** lässt sich nur indirekt erschließen: die
  Urteilswerte `OK` / `zu viel` / `zu wenig`, die Ampeltexte
  `not correct yet` / `not tested/passed yet` / `not tested or not passed yet` /
  `not ready` / `not ready yet` / `Messung fehlt!` / `N/A` /
  `Module is ring module` / `finished` sind Textwerte; die Farben (grün/orange/
  rot/grau) sind Formatierung darüber. Der Export enthält keine Formate — die
  Farbzuordnung aus der Abschrift bleibt die einzige Quelle und ist plausibel.

---

## 7 — Was sich für die Planung ändert

1. **§3.9 schließt die R2H0-Frage.** Kein Modell-Bug: Chip-Klebeziele
   (Hybridblatt) und Modul-Klebeziele (Modulblatt) sind zwei getrennte
   Tabellen. TUDO braucht nur die zweite. Ein Institutsprofil muss beide
   getrennt führen und „nicht anwendbar" ausdrücken können (POLARIS × R2).
2. **Die Formelkette ist bestätigt** (§4.2) — aber der Wächter sitzt am falschen
   Ende. itkFlow muss auf **Vollständigkeit der Eingaben** prüfen, nicht auf
   „Ergebnis ≠ 0". Sonst reproduziert es die 8 Müll-Urteile.
3. **Der lokale Modulname ist nicht eindeutig** (§6.1). Jede Datenübernahme muss
   über die PDB-SN gehen, nicht über `localName` — und selbst die SN kommt im
   Blatt mehrfach vor.
4. **T12 liefert die PDB-Property-Namen frei Haus** (§6.2).
   `2026-08-26-sheet-to-pdb-map.md` sollte dagegen geprüft werden.
5. **Die Metrologie-Anzeige des Blatts ist seit 2025-03-03 kaputt** (§6.2), die
   Information liegt eine Spalte weiter richtig vor. Das ist das beste einzelne
   Argument für die Ablösung.
6. **Nur 21 Module, 9 vollständige Hybrid- und 5 vollständige
   Powerboard-Klebeprotokolle, ein Drittel leere Zeilen** (§5). Die Migration
   ist klein; die Zeilenliste dagegen ist ein Institutsprofil in drei
   historischen Fassungen (§2) und darf nicht als Standard hartkodiert werden.
7. **Die Chip-Klebekonstanten haben sich geändert** (§3.9, Zusatzfund):
   HCC 1,5 → 1,8 mg, Toleranz absolut → 10 %, beidseitig → nur Untergrenze
   (seit 2023-10-24). Zielwertformeln brauchen einen **Gültigkeitszeitraum**.
8. **Es gibt zwei externe Quellen**, die das Blatt braucht und die itkFlow
   mitdenken muss: die Werkzeugtabelle aus §6.3 und die tote zFlow-URL-Basis
   aus §6.1.

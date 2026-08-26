# Transkription der zFlow-Google-Sheets (Screenshots des Owners, 2026-08-26)

**Zweck.** Die Recherche-Agenten sehen die Screenshots nicht. Diese Datei ist
die wörtliche Abschrift dessen, was der Owner gezeigt hat: das TUDO-Blatt, das
DESYZ-Blatt und das Referenzblatt „Daten" mit den Formeln. Sie ist **Quelle,
nicht Interpretation** — Zeilenbeschriftungen und Beispielwerte stehen hier so,
wie sie im Blatt stehen (inkl. deutscher Beschriftungen und Tippfehler).

Wo diese Quelle weiterverarbeitet ist:
[`docs/10-itk-domain-reference.md`](../../10-itk-domain-reference.md) §7
(Stage-Profil gegen echte Daten),
[`docs/07-jig-tool-quickselect.md`](../../07-jig-tool-quickselect.md)
(Werkzeug-Slots und Dropdowns),
[`docs/11-logistics-operations.md`](../../11-logistics-operations.md)
(Glue-Batches und Empfang) und
[`docs/01-ist-analyse-zeuthenflow.md`](../../01-ist-analyse-zeuthenflow.md)
(der Workflow drumherum).

Layout beider Modulblätter: **Spalte = ein Modul**, **Zeile = ein
Arbeitsschritt**. Die Zeilen sind in Bänder gruppiert, die den PDB-Stages
entsprechen. Farbcodierung: grün = OK, orange = „not correct yet"/offen,
rot = Fehler („zu viel", „zu wenig", „Messung fehlt!"), grau = nicht anwendbar.

---

## 1 — Blatt „at TUDO" (maßgeblich für den Owner)

Kopf je Spalte: `Module Name` (z. B. `TUDO-R5M1-01`, `TUDO-R2-01`).

### Auxiliary Info (zusätzliche Informationen)
| Zeile | Beispielwerte |
|---|---|
| Sensor ID | `20USES50001962`, `20USES20000877` |
| Module Type | `R5M1`, `R2`, `R5M0` (Dropdown) |
| SCRIPT: current stage | `FAILED`, `GLUED`, `STITCH_BONDING`, `ON_CORE` |
| Current location | `TUDO`, `UNIFREIBURG` |

### Band „HV-TAB ATTACHED"
| Zeile | Beispielwerte |
|---|---|
| Module reception visual inspection + photo | (leer) |
| reception IV, in DB? | (leer) |
| HV tab jig | (leer) |
| HV tab sheet SN | (leer) |
| Sensor weight with tab (g) | `7,0162`, `5,773`, `5,72`, `7,007`, `7,012`, `6,994`, `7,0155` |
| IV after tabbing passed?. in DB? | `OK` (grün) / `not tested/passed yet` (orange) |
| SCRIPT: Module registered to DB? | `20USE5L0000751`, `20USEM20000195`, `20USE5R0000106` (grün) |

### Band „Gluing Hybrids with TRUE BLUE - False blue"
| Zeile | Beispielwerte |
|---|---|
| Glued by - Name | (leer im TUDO-Ausschnitt; im DESYZ-Blatt `Carola, Mandy`, `Maik, Carola`, `Martin, Maik`) |
| Hybrids SNs (top, bottom) | `20USEHC0000213`, `20USEH40000219`, `20USEHB0000217` |
| top Hybrid weight (g) with ears | (leer) |
| top Hybrid ears weight (g) | (leer) |
| top Hybrid weight without ears (g) | `0,000`, `2,233`, `3,082`, `3,161`, `2,140`, `2,838`, `2,243`, `2,725` |
| bottom Hybrid weight (g) with ears | (leer) |
| bottom Hybrid ears weight (g) | (leer) |
| bottom Hybrid weight without ears (g) | `0,000` |
| **Module weight after gluing all hybrids (g)** | `9,3819`, `9,01`, `9,081`, `9,265`, `9,984`, `9,349`, `9,886` |
| **Modul Target weight (mg)** | `151`, `164`, `135` |
| **Tolerance (mg)** | `22`, `25`, `20` |
| **all Hybrid glue weight (mg)** | `0`, `133`, `155`, `200`, `118`, `134`, `112`, `145` |
| **Adhesive weight result hybrid (Klebegewicht Ergebnis)** | `OK` (grün) / `zu viel` (rot) / `zu wenig` (rot) |
| Hybrid glue date | (Datum) |
| Hybrid glue sample | `20USEGT0000089` |
| Hybrid glue jigs used, top, bottom | `20USERT0510405`, `20USERT0510211` (Dropdown, zwei Werte je Zeile) |
| Hybrid pickups used, top, bottom | `20USERT0510110`, `20USERT0510310` (Dropdown) |
| Module jig used | `20USERT0510711`, `20USERT0205…` (Dropdown) |
| SCRIPT: Hybrids assembled to module (in DB) | `OK` (grün) / `not correct yet` (orange) |

### Band „Gluing Powerboard with TRUE BLUE - False blue"
| Zeile | Beispielwerte |
|---|---|
| Glued by - Name | (leer) |
| Powerboard Label | (leer im TUDO-Ausschnitt; DESYZ: `1152`, `6621`, `3652`, `1550`, `1464`, `558`, `1574`) |
| Powerboard SN | `20USEP27011595`, `20USEP57011031`, `20USEP57013461` |
| Powerboard weight (g) | `3,286`, `2,486`, `3,195`, `3,2473` |
| Powerboard glue date | (Datum) |
| Powerboard glue sample | `20USEGT0000089` |
| Powerboard glue jig, pickup tool | `20USERT0274006, 20USERT0284004` (zwei Codes, kommagetrennt in einer Zelle) |
| SCRIPT: Powerboard assembled to module (in DB) | `OK` / `N/A` |
| **Module weight after gluing powerboard AND hybrid** | `12,764`, `11,666`, `12,5718`, `12,736` |
| **Target weight (mg)** | `0`, `70`, `103` |
| **Tolerance (mg)** | `11`, `16` |
| **Powerboard glue weight (...mg)** | `96`, `-9010`, `99`, `112`, `140`, `-9886` (negative Werte = fehlende Eingangsgrößen) |
| **Adhesive weight result powerboard** | `OK` / `zu wenig` / `zu viel` |
| SCRIPT: Glue weights uploaded, stage set to GLUED | `OK` (grün) |

### Band „Measure"
| Zeile | Beispielwerte |
|---|---|
| Visual Inspection Photo | (leer) |
| Bow Metrology | `Messung fehlt!` (orange) |
| Bow Metrology Date | `---` |
| Metrology outcome | `Messung fehlt!` (orange) |
| Metrology date | `---` |
| Metrology results uploaded to DB? | `not correct yet` (orange) / `OK` (grün) |

### Band „Module stitching"
| Zeile | Beispielwerte |
|---|---|
| Half module sibling (only R3-R5) | (leer) |
| SCRIPT: Complete module registered to DB | `not ready` / `Module is ring module` |

### Band „BONDED"
| Zeile | Beispielwerte |
|---|---|
| Visual Inspection Photo | (leer) |
| Module bond date | `13.01.2026` |
| Visual Inspection FE bonds (officially optional) | (leer) |
| IV after bonding | `not tested or not passed yet` / `OK` |
| DAQ Quick test | `OK` |
| UBC Uploader: quick electrical test passed | (leer) |
| DAQ TC test (incl. IV) | `OK` / `not tested or not passed yet` |

### Band „TESTED"
| Zeile | Beispielwerte |
|---|---|
| UBC Uploader: thermal cycling electrical tests passed | (leer) |

---

## 2 — Blatt „at DESYZ" (zusätzliche Zeilen, die TUDO nicht zeigt)

Gleiches Layout, teils andere Zeilen. Zusätzlich bzw. abweichend:

- **ATTACHED**: `HV tab sheet SN` gefüllt (`20USEVS0200671`, `20USEVL0200219`),
  `IV after tabbing passed?. in DB?`, `SCRIPT: Module registered to DB?`.
- **Gluing Hybrids**: `Hybrid glue sample` als **Datum+Code**
  (`TB_2025-09-26, 20USEGT0000074`, `TB_2025-11-17_02, 20USEGT0000080`).
  `Hybrid glue jigs used, top, bottom` / `Hybrid pickups used, top, bottom` /
  `Module jig used` sind hier **Farbnamen**: `orange`, `white` (dunkle bzw.
  lachsfarbene Chips) — also ein lokales Benennungsschema statt PDB-Codes.
- **Gluing Powerboard**: `Powerboard Label` (vierstellige Hausnummer),
  `Powerboard glue jig, pickup tool` ebenfalls `white`/`orange`.
- **Measure**: `Visual Inspection Photo` mit Datum (`2025-10-13`),
  `Metrology outcome` als `Metrology_PASSED` (grün) / `Metrology_FAILED` (rot),
  `Metrology date` als Zeitstempel (`30.09.2025 07:57:06`),
  `Metrology results uploaded to DB?`.
- **Module stitching**: `SCRIPT: Complete module registered to DB` mit der SN
  des zusammengesetzten Moduls (`20USEM50000200`, `20USEM50000201`).
- **BONDED**: `HV/GND bond & Post-glue IV (officially optional)`,
  `PB-Hy bond date`, `DAQ functional test`, `Hybrid frontend (FE) bond`,
  `Visual Inspection FE bonds (officially optional)`,
  `Bond data (could be e.g. Row Test or something else)`.
- **TESTED**: `DAQ module test`, `IV after bonding`.
- **FINISHED MODULE**: `Visual Inspection photo`,
  `Packing date (box, humi, silica, bag)`, `Shipping date (peli case)`.
- **FINISHED**: `add to this batch by zFlow`
  (`iPRESERIES_DESYZ`, `iPRODUCTION_DESYZ`), `Finished`
  (`not ready yet` orange / `finished` grün).
- **Shipment status**: `for info`.
- **zFlow Processing**: `Last update` / `Next update` als ISO-Zeitstempel
  (`2026-08-26T13:56:03.995613+02:00`, `On next zFlow run`, `#N/A`).
- **UBC Uploader**: `quick electrical test passed`,
  `thermal cycling electrical tests passed` — Werte wie
  `ITSDAQ run 104: failed`, `ITSDAQ run 1393: failed`.
- **Comments**: Freitext, betrieblich wertvoll. Wörtlich:
  - „Plan UV/irrad recov: FAIL due to 10 consecutive bad strips (more than 8)"
  - „Failed because the PB-shifting spacer was damaged - Sensor slid partially
    below the spacer and thus the powerboard is about 600 microns too close to
    the hybrid."
  - „Failed due to MASSIVE tilt in lower hybrid (+- 1mm!!)"

---

## 3 — Referenzblatt „Daten" (Formeln und Zieltabellen)

Überschrift wörtlich: **„Formeln bitte nicht löschen!!!!!!!"**

### Hybrid → Chipbestückung
| Hybrid | Amount ABC | Amount HCC |
|---|---|---|
| R0H0 | 8 | 1 |
| R0H1 | 9 | 1 |
| R1H0 | 10 | 1 |
| R1H1 | 11 | 1 |
| R3H0 | 7 | 0 |
| R3H1 | 7 | 2 |
| R3H2 | 7 | 0 |
| R3H3 | 7 | 2 |
| R5H0 | 9 | 0 |
| R5H1 | 9 | 2 |

### Chip → UV-Klebemenge
| Chip | UV-Klebemenge | Tolerance |
|---|---|---|
| ABC | 0,0042 | 0,00025 |
| HCC | 0,0015 | 0,0001 |

### Formeln (wörtlich aus dem Blatt)
```
Beispiel Formel Chipmenge:        WENN(C3="R5H1",Daten!$B$11,WENN(C3="bitte wählen","Hybrid auswählen!"))
Beispiel Formel Modul-Klebegewicht: WENN(C3="R0",Daten!$B$26,WENN(C3="R1",Daten!$B$27,WENN(C3="R3M0",Daten!$B$28,
                                    WENN(C3="R3M1",Daten!$B$29,WENN(C3="R5M0",Daten!$B$30,WENN(C3="R5M1",Daten!$B$31,
                                    WENN(C3="bitte wählen","0"))))))
Beispiel Formel Klebeziel:        (B2*4.2)+(C2*1.5)
Beispiel Formel Tolerance:        (B2*0.25)+(C2*0.1)
Beispiel Klebegewicht:            (C23-(C22-C21)-C20)*1000
Beispiel Dropdown(eng):           84
```

### „Module Glueing with POLARIS"
| Module Type | Target weight without PB [mg] | Tolerance [mg] | Powerboard Target weight [mg] | Tolerance [mg] | Total Glue Target weight [mg] | Tolerance [mg] |
|---|---|---|---|---|---|---|
| R0M0 | 217 | 33 | 79 | 12 | 296 | 45 |
| R1M0 | 293 | 44 | 79 | 13 | 372 | 57 |
| R3M0 | 187 | 28 | 148 | 22 | 335 | 50 |
| R3M1 | 217 | 33 | 0 | 0 | 217 | 33 |
| R5M0 | 127 | 19 | 97 | 15 | 224 | 34 |
| R5M1 | 142 | 21 | 0 | 0 | 142 | 21 |

### „Module Glueing with True Blue / False Blue" (grün hinterlegt)
| Module Type | Target weight without PB [mg] | Tolerance [mg] | Powerboard Target weight [mg] | Tolerance [mg] | Total Glue Target weight [mg] | Tolerance [mg] |
|---|---|---|---|---|---|---|
| R0 | 230 | 35 | 84 | 13 | 314 | 48 |
| R1 | 311 | 46 | 84 | 13 | 395 | 59 |
| R3M0 | 198 | 30 | 157 | 23 | 355 | 53 |
| R3M1 | 231 | 35 | 0 | 0 | 231 | 35 |
| R5M0 | 135 | 20 | 103 | 16 | 238 | 36 |
| R5M1 | 151 | 22 | 0 | 0 | 151 | 22 |
| R2 | 164 | 25 | 70 | 11 | 234 | 22 |

**Wichtig:** zwei Klebeverfahren, zwei Zieltabellen, unterschiedliche Zahlen —
das Verfahren bestimmt Ziel und Toleranz.

### „Gluing with TrueBlue/FalseBlue" (Mischungsrechner)
| Feld | Beispiel |
|---|---|
| Hardener TB\FB [g] | 0,3 |
| required Epoxy [g] | 1 |
| Total weight [g] | 1,3 |
| Erreichtes Gesamtgewicht [g] | 2,1688 |
| Erreichtes Mischungsverhältnis [%] | 166,83 |

Zweite Variante desselben Rechners (obere Tabelle):
`required Epoxy (soll 1,666g)` 0,0894 · `calculated hardener` 0,0268 ·
`achieved hardener` 0,48 · `calculated total weight achieved` 0,5694 ·
`Mixing ratio achieved in %` 489,9329.

### „True Blue - Klebemenge (bzgl. Hardener!!) fuer ca 3 Klebungen"
| Module Type | Hybrid | Powerboard |
|---|---|---|
| R0 | 0,3g | 0,2g |
| R1 | 0,36g | 0,2g |
| R3M0 | 0,25g | 0,25g |
| R3M1 | 0,3g | ------- |
| R5M0 | 0,25g | 0,21g |
| R5M1 | 0,25g | ------- |

### „Klebemengenkorrektur fuer Klebeprogramme" (Rückkopplung an den Roboter)
| Module Type | soll Klebegewicht | IST-Klebegewicht | Line Speed 1 | Line Speed 2 | new Line Speed 1 | new Line Speed 2 |
|---|---|---|---|---|---|---|
| R1 PB (Dropdown) | 84 | 100 | 17 | 3,5 | 20,23809524 | 4,166666667 |

Erkennbare Rechnung: `new = alt × (IST / soll)` — 17 × 100/84 = 20,238;
3,5 × 100/84 = 4,1667. **Zu bestätigen**, nicht als gesichert behandeln.

### Dropdown-Listen (Werkzeugnummern, lokal)
| Liste | Werte |
|---|---|
| Hybridjig | 4, 5, 7, 8 |
| Chip Tray | 1, 5, 6, 8, 12 |
| PickUpTool | 4, 5, 7, 8 |

---

## 4 — Was daraus unmittelbar folgt (ohne Interpretation der Agenten vorwegzunehmen)

1. Die Zeile eines Blattes ist ein **Arbeitsschritt**, nicht ein PDB-Testtyp.
   Viele Zeilen sind Eingaben (Waagenwerte), Metadaten (wer, wann, welches
   Werkzeug), abgeleitete Werte (Klebegewicht, Urteil) oder Sync-Ampeln
   (`SCRIPT: …`).
2. Die Kernmechanik ist **Rohwert rein → Rechnung → Urteil**:
   Waagenwerte ⇒ Klebegewicht ⇒ Vergleich gegen Ziel/Toleranz aus einer
   typabhängigen Tabelle ⇒ `OK` / `zu viel` / `zu wenig`.
3. Ziel und Toleranz hängen ab von **Modultyp**, **Klebeverfahren**
   (POLARIS vs. TrueBlue/FalseBlue) und bei Hybriden von der
   **Chipbestückung** (ABC/HCC-Zahl × Menge je Chip).
4. Es gibt eine **Rückkopplung an die Fertigung** (Line-Speed-Korrektur), die
   in itkFlow bisher nirgends existiert.
5. `Comments` trägt betriebliches Wissen, das nirgends sonst steht
   (Ausfallursachen im Klartext).

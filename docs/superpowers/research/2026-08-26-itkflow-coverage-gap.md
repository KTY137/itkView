# itkFlow-Abdeckung der zFlow-Blätter — Ist-Aufnahme (Gap-Matrix)

> **Historischer Snapshot vom 2026-08-26.** Die Glue-Zeilen und ihre
> Klassen zaehlen bewusst den damaligen Stand. E2 wurde am 2026-08-27
> umgesetzt; den aktuellen Vertrag und Status beschreiben
> [`../specs/2026-08-27-modulseite-als-arbeitsblatt.md`](../specs/2026-08-27-modulseite-als-arbeitsblatt.md)
> §9 und [`../../04-roadmap.md`](../../04-roadmap.md). Die damalige Recherche
> wird nicht rueckwirkend umgeschrieben.

**Zweck.** Zeilenweise Antwort auf: *Wo lebt diese Blattzeile heute in itkFlow?*
Quelle der Zeilen:
[`2026-08-26-zflow-sheet-transcription.md`](2026-08-26-zflow-sheet-transcription.md).
Bedeutung der Zeilen:
[`2026-08-26-zflow-row-semantics.md`](2026-08-26-zflow-row-semantics.md).
Dies ist eine **Bestandsaufnahme, kein Entwurf**.

Klassen: **A** = ausgeliefert und auf der Modul-Detailseite sichtbar ·
**B** = ausgeliefert, aber nur woanders erreichbar ·
**C** = im Backend implementiert, an keine UI verdrahtet ·
**D** = gar nicht implementiert.

## 0 — Zählung

| Klasse | Zeilen |
|---|---|
| A | 37 |
| B | 11 |
| C | 14 |
| D | 31 |
| **Summe** | **93** |

## 1 — Blatt „at TUDO"

### Auxiliary Info

| Zeile | Klasse | Wo |
|---|---|---|
| Sensor ID | A | `ComponentsScreen.tsx:1150-1166` (Family-Tree) |
| Module Type | A | `ComponentsScreen.tsx:1123`, `Component.type_code` (`models.py:36`) |
| SCRIPT: current stage | A | Stage-Chip `ComponentsScreen.tsx:1098-1104`, Projektion `:1084-1096` |
| Current location | A | `ComponentsScreen.tsx:1125` |

### Band „HV-TAB ATTACHED"

| Zeile | Klasse | Wo / Notiz |
|---|---|---|
| Module reception visual inspection + photo | A | Worksheet-Zeile `VISUAL_INSPECTION`; Fotos `ImagesSection` `ComponentsScreen.tsx:1525`. Wareneingangs-Variante zusätzlich B (`shipment_reception.py:53,135`) |
| reception IV, in DB? | A | Worksheet-Zeile `MODULE_IV_PS_V1`; auch B über `shipment_reception_tests` |
| HV tab jig | **D** | Tool-Registry existiert, aber Werkzeuge hängen nur an Assembly-Aktionen, und die sind auf MODULE←HYBRID begrenzt (`assembly.py:32`) |
| HV tab sheet SN | **D** | kein Feld, kein Komponententyp |
| Sensor weight with tab (g) | **D** | Rohwert ohne PDB-Heimat |
| IV after tabbing passed?. in DB? | A | Status-Chip `ModuleWorksheet.tsx:265-283`, Regel `preview.py:82-92` — exakt die Ampel des Blattes |
| SCRIPT: Module registered to DB? | A | Spiegel + Staged Action `preview.py:118-123`. Registrierung selbst B (`ComponentsScreen.tsx:568`, Listenansicht) |

### Band „Gluing Hybrids with TRUE BLUE"

| Zeile | Klasse | Wo / Notiz |
|---|---|---|
| Glued by - Name | **D** | nächstes Vorhandenes: `GlueUsage.used_by` (`models.py:437`), batchseitig, am Modul nie gelesen |
| Hybrids SNs (top, bottom) | A | Family-Tree. „top/bottom" ist kein Modellbegriff — der Slot lebt nur in der Assembly-Aktion (`assembly.py:513`) |
| top/bottom Hybrid weight, mit/ohne Ohren (6 Zeilen) | **D** | Rohwerte |
| Module weight after gluing all hybrids (g) | **D** | Rohwert. Ausnahme: deklariert das gespiegelte `GLUE_WEIGHT`-Schema ein passendes Result-Feld, ist die Zeile schon A über die Values-Spalte |
| **Modul Target weight (mg)** | **C** | `domain/glue.py:103-111` — Werte identisch mit der TrueBlue-Tabelle. Null Aufrufer |
| **Tolerance (mg)** | **C** | `domain/glue.py:15-24`. Null Aufrufer |
| **all Hybrid glue weight (mg)** | **C** | `domain/glue.py:38-40`. Null Aufrufer |
| **Adhesive weight result hybrid** | **C** | `domain/glue.py:43-48` → `OK`/`TOO_LITTLE`/`TOO_MUCH`. Null Aufrufer |
| Hybrid glue date | A | Datumsspalte, Quelle `preview.py:305` (`measured_at`) |
| Hybrid glue sample | B | Glue-Batches (`GlueBatchesScreen.tsx`, `api.py:1637 ff.`), Übernahme in PDB-Property `assembly.py:510-511` |
| Hybrid glue jigs used, top, bottom | B | Slot-Picker `AssemblyWizardScreen.tsx:58-86`, Profil `institute_settings.py:521-592`, Server `assembly.py:219-255,502-508` |
| Hybrid pickups used, top, bottom | B | wie oben, eigener Slot mit eigenem `property_key` |
| Module jig used | B | wie oben bzw. Default-Slot `assembly.py:496-500` |
| SCRIPT: Hybrids assembled to module | A | Family-Tree „assembled ✓" `:1163`; offene Aktion `preview.py:124-130`. Aktion selbst B (Wizard) |

### Band „Gluing Powerboard with TRUE BLUE"

| Zeile | Klasse | Wo / Notiz |
|---|---|---|
| Glued by - Name | **D** | — |
| Powerboard Label | **D** | die vierstellige Hausnummer hat nirgends eine Heimat |
| Powerboard SN | A | Family-Tree. **Anlegen** der Verknüpfung nein: `SAFE_ASSEMBLY_RELATIONSHIPS = {("MODULE","HYBRID")}` (`assembly.py:32`) |
| Powerboard weight (g) | **D** | Rohwert |
| Powerboard glue date | A | Datumsspalte |
| Powerboard glue sample | B | Glue-Batches |
| Powerboard glue jig, pickup tool | B | `assembly.py:502-508` — der Docstring `:486-489` nennt genau diese Blattspalte als Vorbild; kommagetrennt 1:1 umgesetzt (0.2.1) |
| SCRIPT: Powerboard assembled | A | Family-Tree, nur Anzeige |
| Module weight after gluing PB AND hybrid | **D** | Rohwert |
| **Target weight / Tolerance / PB glue weight / Verdict** | **C** | `domain/glue.py:104-110`, `:15-24`, `:38-40`, `:43-48`. `0` bei R3M1/R5M1 entspricht `glue.py:101-102`. Null Aufrufer |
| SCRIPT: Glue weights uploaded, stage set to GLUED | A | `StagedActionsPanel` `:1389`, Summary `preview.py:110-116`, Stage-Vorschlag `:1593` |

### Bänder „Measure" / „Module stitching" / „BONDED" / „TESTED"

| Zeile | Klasse | Wo / Notiz |
|---|---|---|
| Visual Inspection Photo | A | `ImagesSection` `:1525-1579`, Anhangzähler `preview.py:310` |
| Bow Metrology (+ Date) | A | Worksheet-Zeile `MODULE_BOW`. „Messung fehlt!" = Status `missing` (`preview.py:88-90`) |
| Metrology outcome (+ Date) | A | Worksheet-Zeile `MODULE_METROLOGY`; `Metrology_PASSED/FAILED` = `passed` |
| Metrology results uploaded to DB? | A | Status-Chip + Ghost-Zeile `ModuleWorksheet.tsx:741-765` |
| Half module sibling (only R3-R5) | **D** | kein Geschwister-/Stitching-Begriff (`models.py` kennt nur `parent_id`) |
| SCRIPT: Complete module registered to DB | **D** | dito |
| Module bond date | A | Worksheet-Zeile `MODULE_WIRE_BONDING`, Datumsspalte |
| Visual Inspection FE bonds / IV after bonding / DAQ Quick test / DAQ TC test | A | über `stage_requirements` konfigurierbar (`institute_settings.py:462`) |
| UBC Uploader (quick / thermal cycling) | **D** | keine ITSDAQ-/UBC-Integration im Code |

## 2 — Zusätzliche Zeilen „at DESYZ"

| Zeile | Klasse | Notiz |
|---|---|---|
| Hybrid glue sample als Datum+Code | B | `GlueBatch.batch_no` + `pdb_sn` (`models.py:397-398`) |
| Jigs als Farbnamen (`orange`, `white`) | B | `Tool.label` (`models.py:370`) — Docstring nennt wörtlich „R5M0 Module jig #3 (orange)" |
| HV/GND bond, PB-Hy bond date, DAQ functional test, FE bond, Bond data, DAQ module test | A | je über `stage_requirements` konfigurierbar |
| Packing date / Shipping date (peli case) | **D** | `Shipment.sent_at` ist die *Sendung*, nicht das Modul |
| add to this batch by zFlow | **D** | PDB-Batch-Mitgliedschaft nirgends modelliert |
| Finished | A | Stage `FINISHED` + Stage-Chip |
| Shipment status | B | `ShipmentsScreen.tsx`; Detailseite verlinkt nicht dorthin |
| zFlow Processing: Last/Next update | B | `OpsHealthScreen.tsx:209-225`, `SyncJob` (`models.py:608-645`) |
| **Comments (Freitext)** | **D** | siehe Frage 2 — das architektonisch teuerste Feld |

## 3 — Referenzblatt „Daten"

| Zeile | Klasse | Notiz |
|---|---|---|
| Hybrid → Amount ABC / HCC | **D** | Tabelle existiert nirgends; `hybrid_chip_glue_target` nimmt die Zahlen entgegen, niemand liefert sie |
| Chip → UV-Klebemenge | **C** | `glue.py:55-58`: `abc_target_mg=4.2, abc_tolerance_mg=0.25, hcc_target_mg=1.5, hcc_tolerance_mg=0.1` — **identische Konstanten**, aber nicht als Profildatum lesbar |
| Formel Klebeziel `(B2*4.2)+(C2*1.5)` | **C** | `glue.py:62` — zeichengleich |
| Formel Tolerance `(B2*0.25)+(C2*0.1)` | **C** | `glue.py:63` — zeichengleich |
| Formel Klebegewicht `(C23-(C22-C21))*1000` | **C** | `glue.py:38-40`. **Teil-Deckung:** die Ohren-Subtraktion ist *nicht* modelliert; die Funktion erwartet das Netto-Teilgewicht. Testbeleg `test_glue.py:16` reproduziert 133 |
| Tabelle POLARIS | **D** | keine Zeile im Code |
| Tabelle True Blue / False Blue | **C** | `glue.py:103-111` — alle sieben Zeilen inkl. Toleranzen identisch; **Total-Spalte fehlt** |
| Mischungsrechner | **D** | verwandt: `pot_life_state` deckt nur die Topfzeit |
| Klebemengenkorrektur / Line Speed | **D** | keinerlei Rückkopplung an die Fertigung |
| Dropdowns Hybridjig / Chip Tray / PickUpTool | B | `Tool.code`/`kind`/`compatible_types`; die Sorte `chip_tray` ist nicht geseedet |

## 4 — Tote und halb verdrahtete Domänenlogik

### 4.1 `backend/app/domain/glue.py` — bestätigt tot

Volltextsuche über `*.py`/`*.ts`/`*.tsx` unter Ausschluss der Datei selbst und
`backend/tests/`: **null Treffer** für `GlueTarget` (`:13-24`), `GlueVerdict`
(`:27-31`), `parse_decimal` (`:33-35`), `glue_weight_mg` (`:38-40`),
`evaluate_glue_weight` (`:43-48`), `hybrid_chip_glue_target` (`:51-64`),
`DEFAULT_MODULE_GLUE_TARGETS` (`:103-111`). Die Symbole rufen sich auch
**untereinander nicht** auf. Einziger lebender Export: `pot_life_state`
(`:77`), importiert in `api.py:33` und `assembly.py:27`.

Das sind **14 C-Zeilen**, die nur ein Adapter (Muster `stage_service.py`) und
vier Payload-Felder vom Fertigsein trennen.

### 4.2 Weitere halb verdrahtete Fundstellen

| Fundstelle | Zustand |
|---|---|
| `required_properties` (`ingestion.py:384-400`, erzwungen `api.py:2919-2942`) | Backend scharf, **kein Editor, kein Validator** |
| `assembly_tool_slots` (`institute_settings.py:521-592`) | Voll funktionsfähig, **kein Admin-Editor** (`docs/07:126` führt es als offen) |
| `assembly_property_keys` (`assembly.py:186-216`) | **Weder Validator noch Editor.** Ohne ihn schreibt der Default-Slot *gar keine* PDB-Property (`assembly.py:499`) |
| `_parse_glue_weight` (`ingestion.py:186-199`) | Lebt, prüft `GW_*` auf Numerik — **berechnet aber nichts**. Die natürliche Andockstelle |

Gegenprobe über neun weitere Backend-Module (`domain/stages.py`,
`stage_service.py`, `measurement_stats.py`, `stats.py`, `tool_sync.py`,
`shipment_reception.py`, `test_run_evidence.py`, `pdb_test_evidence.py`,
`test_type_schemas.py`): überall ≥ 1 Produktivaufrufer. `domain/glue.py` ist
der einzige Ausreißer.

## 5 — Antworten auf die fünf Entwurfsfragen

### Frage 1 — Was kann der In-Row-Edit-Strip erfassen?

**Genau das, was das gespiegelte PDB-Testtyp-Schema deklariert — nicht mehr.**
`TestForm` erzeugt Controls ausschließlich aus `definition.properties` und
`definition.results` (`TestForm.tsx:201-205`) plus `runNumber`/`date`/`passed`
(`:373-375`). Es gibt **keinen Freitext-/Zusatzfeld-Pfad**. Der Absendepfad
(`ModuleWorksheet.tsx:610-633`) ist Ingest → Dry-Run → `upload_test_run`:
**alles Eingegebene ist ein PDB-Schreibvorschlag**, einen „nur lokal"-Modus
gibt es nicht.

Für einen Waagenwert ohne PDB-Result-Feld heißt das: **kein Control rendert**,
und `TestForm.tsx:434` verlangt zusätzlich mindestens einen Result-Wert.
Der Strip ist ein **PDB-Run-Editor, kein Messwertblatt.**

### Frage 2 — Wo lebt ein Wert ohne PDB-Heimat? (die teuerste Frage)

**Nirgends. Es müsste erfunden werden.**

- `Component` ist ein deklarierter Nur-Lese-Spiegel: „Never written by request
  handlers — only by `app.sync.sync_components`" (`models.py:24-29`). Einzige
  lokal führende Spalte: `local_name` (`:42`), bereits als Anzeigealias belegt.
- Kein `ComponentNote`/`ComponentLocalData`-Modell existiert (Grep auf
  `comment` in `models.py`+`schemas.py`: 0 Treffer).
- **Die einzige lokal führende Zeile *pro Komponente* im ganzen Schema ist
  `GlueUsage`** (`models.py:422-443`) — bewusst FK-frei, mit `note` (`:436`),
  `used_by` (`:437`), `amount_mg` (`:435`). Erreichbar aber nur aus der
  Glue-Batch-Ansicht (`api.py:1837-1843`) und auf der Modulseite nie gelesen.
- Falsche Heimaten: `OutboxAction.payload` ist per Definition „intent to write
  to the PDB" (`models.py:84-90`) — die Umkehrung des Zwecks;
  `IngestFile.payload` ebenso; `AuditEvent.detail` ist append-only;
  `InstituteProfile.settings` ist Profilebene.
- Der einzige passende Vertrag im Haus ist `Shipment.reception_*` („lokal
  führend, wird von keinem Sync überschrieben", `models.py:450-453`) bzw.
  `Tool.rfid`/`status` — beide an **Nachbartabellen**, genau weil `Component`
  selbst das nicht darf.
- Zusatzbedingung: `preview.py:8-15` verbietet, Rohwerte in die
  Preview-Antwort zurückzuholen.

**Konsequenz:** entweder `GlueUsage` erweitern (schon pro Komponente, löst
aber `Powerboard Label` und Packdatum nicht) oder eine **neue lokal führende
Per-Komponenten-Tabelle** nach dem `reception_*`-Vertrag.

### Frage 3 — Wohin gehören die abgeleiteten Zeilen?

**Serverseitig in `domain/` gerechnet, über die Worksheet-Payload
ausgeliefert; das Frontend färbt nur den Chip.** Vier Präzedenzfälle:

1. `preview.py:82-92` `_status_for` — eine Statusregel für Checks *und*
   Worksheet, Docstring: „so the two projections … can never disagree".
2. `preview.py:465-468` — `StageModel` einmal gebaut und durchgereicht.
3. `assembly.py:475-514` `_pdb_properties` — Ableitung im Server, beim Push
   neu abgeleitet und verglichen (`:834`, `:951-952`).
4. `pot_life_state` (`glue.py:77`) — Server rechnet, Payload trägt das
   Ergebnis (`schemas.py:964`), Client tickt nur.

Es fehlt also **ausschließlich der Adapter analog `stage_service.py`** und die
Emission als vier abgeleitete Skalare am Worksheet.

### Frage 4 — Profildaten: vorhanden vs. nötig

**Vorhanden, validiert, editierbar:** `stage_order`, `stage_requirements`,
`evidence_component_types`, `shipment_reception_tests`,
`shipment_reception_checklist`, `glue_pot_life_minutes`,
`reminder_escalation`, `notification_channels`.

**Vorhanden und wirksam, aber ohne UI-Pfad:** `assembly_tool_slots`,
`assembly_property_keys`, `required_properties`.

**Neu nötig — genau die Zieltabellen des Blattes:**

1. `glue_targets`: (Klebeverfahren × Modultyp) → {hybrids, powerboard, total}
   × {target_mg, tolerance_mg}. `glue.py:103-111` hat die *Form*, aber nur ein
   Verfahren, keine Total-Spalte, und — entscheidend — **es gibt kein
   `glue_targets_from_settings()`** als Gegenstück zu
   `stage_model_from_settings`. Zusätzlich trägt **keine Entität ein
   „Klebeverfahren"**.
2. `hybrid_chip_counts`: Hybridtyp → {abc, hcc}. Existiert nirgends.
3. `chip_glue_amounts`: ABC/HCC → {target_mg, tolerance_mg}. Heute nur
   Keyword-Defaults.
4. Offen für volle Blattbreite: Mischungsverhältnis-Sollwerte,
   Hardener-Menge je Modultyp, Line-Speed-Korrekturtabelle.

### Frage 5 — Was rendert die Modul-Detailseite heute?

`ComponentDetailPanel` (`ComponentsScreen.tsx:723-1307`), von oben:
Toolbar (`:1049`) → Preview-Tabs (`:1050-1069`) → `detail-head` mit Titel,
Copy-SN, Stage-Chip, Dummy/Trashed (`:1070-1107`) → Preview-Lade-/Fehlerbanner
(`:1108-1116`) → zweispaltiges Raster:
**links** Stammdaten (`:1119-1129`) und Familie (`:1130-1173`);
**rechts** Evidenz-Sync-Toolbar (`:1176-1197`), `AddTestResult`
(`:1198-1231`), einer von drei Zweigen (`:1232-1301`) mit
`StagedActionsPanel`/`StageSuggestionSection` → **`ModuleWorksheet`** →
`MirroredRunsSection` (eingeklappt), zuletzt `ImagesSection` (`:1302`).

**Bemerkenswert abwesend** (per Grep bestätigt): kein Klebebatch, kein
Werkzeug/Jig, kein Assembly-Schritt, kein Bedienername, kein Freitext und
keinerlei abgeleitete Klebezahl. Alles B-Klassifizierte liegt hinter eigenen
Navigationspunkten, zu denen die Detailseite **nicht verlinkt**.

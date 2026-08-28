# ITk-Domain-Referenz: Strip-Modul-Workflow & Komponenten-Taxonomie

> Zweck: die „weird labels" entschluesseln (was ist `component_type`, `type_code`,
> `R5M0`, `ATLAS18R5`), festhalten **welche Komponenten Sensoren/ASICs sind**
> (harte Regel #2 — nie registrieren) und den ITk-Strip-Modul-Produktionsablauf
> von Anfang bis Ende beschreiben, damit Assembly-Features (Create Module,
> Jig-Pflicht, Stage-Vorschlaege) auf einem sauberen Domain-Verstaendnis stehen.
>
> Legende: ✓ = im Repo/Mirror-Daten verifiziert · ⚠ = ITk-Allgemeinwissen, gegen
> Live-PDB zu bestaetigen.
>
> - **Besitzt:** die ITk-Domain-Sprache — Komponentenhierarchie, `component_type`
>   und `type_code`, welche Teile Sensoren/ASICs sind, den Produktionsablauf
>   Ende zu Ende und (§7) den Abgleich des Stage-Profils mit echten Daten.
> - **Fuer wen:** alle, die Labels, Stages, Pflichttests oder Assembly-Regeln
>   anfassen — und jeden, der die „weird labels" im UI zum ersten Mal sieht.
> - **Verwandt:** [`09-pdb-production-strategy.md`](09-pdb-production-strategy.md)
>   (warum Sensoren/ASICs nie registriert werden),
>   [`05-ui-design-reference.md`](05-ui-design-reference.md) (wie diese Begriffe
>   im Produkt erscheinen),
>   [`07-jig-tool-quickselect.md`](07-jig-tool-quickselect.md) (Tools haengen am
>   R-Type), [`../backend/app/domain/stages.py`](../backend/app/domain/stages.py)
>   (der Stage-Vertrag im Code),
>   [`01-ist-analyse-zeuthenflow.md`](01-ist-analyse-zeuthenflow.md) (dieselbe
>   Domaene aus Sheet-Sicht), [`README.md`](README.md) (Lesepfade).

## 1. Woraus ein Modul besteht (Hierarchie)

Ein **Modul** ist die assemblierte Einheit. Es hat als Kinder (`parent_sn` zeigt
aufs Modul) ✓:

```text
MODULE  (das fertige Modul)
├─ SENSOR      — der Silizium-Streifensensor (das aktive Bauteil)
├─ HYBRID(s)   — Front-End-Hybrid(e): Flex-PCB mit den Auslese-ASICs
│   ├─ ABCStar — Auslese-ASIC (ATLAS Binary Chip), 1..n je Hybrid   ⚠
│   └─ HCCStar — Hybrid Controller Chip, steuert die ABCs           ⚠
└─ PWB / POWERBOARD — Powerboard: DC-DC-Wandler, HV-Schalter, Monitoring
    └─ AMAC    — Monitoring-/Control-ASIC auf dem Powerboard         ⚠
```

Der Mirror sieht heute typischerweise nur `MODULE`, `SENSOR`, `HYBRID`, `PWB`
(die ASICs sind Kinder der Hybride/PWB und werden beim Institut-Sync nicht
zwingend mitgezogen). ✓

## 2. Legende: `component_type` + `type_code` → Bedeutung

Der Mirror speichert zwei Felder (`backend/app/pdb_sync.py`) ✓:
- `component_type` ← PDB `componentType.code` — **was** das Bauteil ist.
- `type_code` ← PDB `type.code` (Fallback `UNKNOWN`) — die **Variante/Geometrie**.

| `component_type` | `type_code` (Beispiele) | Was es ist | DUMMY registrierbar? |
|---|---|---|---|
| `MODULE` | `R0M0`…`R5M1`, `R5M0` ✓ | Das assemblierte Modul | **JA** (in `pdb_dummy_component_types`) ✓ |
| `SENSOR` | `ATLAS18R5` ✓, `ATLAS18R0…R5`, `ATLAS18SS/LS` ⚠ | Silizium-Streifensensor (aktiv) | **NEIN — Sensor, NIEMALS** ✗ |
| `HYBRID` / `HYBRID_ASSEMBLY` | `R5H0`, `R5H1` ✓ | Front-End-Hybrid (Flex + ASICs) | **JA** ✓ |
| `HYBRID_FLEX` | — | Nacktes Hybrid-Flex (ohne ASICs) ⚠ | (nicht in Dummy-Liste) |
| `PWB` / `POWERBOARD` | `PBR5` ✓, `PBR0…R5` ⚠ | Powerboard (DC-DC, HV-Mux, AMAC) | nein (nur MODULE/HYBRID) ✓ |
| `ABC` / `ABCStar` | — | Auslese-ASIC | **NEIN — ASIC** ✗ |
| `HCC` / `HCCStar` | — | Hybrid-Controller-ASIC | **NEIN — ASIC** ✗ |
| `AMAC` | — | Powerboard-Monitoring-ASIC | **NEIN — ASIC** ✗ |

**Warum „registrierbar" so wichtig ist:** `pdb_dummy_component_types =
["MODULE", "HYBRID"]` (`backend/app/config.py`) ✓. Sensoren und ASICs haben
keinen Dummy-Mechanismus; sie zu registrieren korrumpiert die
Kollaborations-Seriennummern (harte Regel #2,
[`docs/09`](09-pdb-production-strategy.md),
[ADR 003](adr/003-pdb-dummy-write-scope.md)). Eine
Create-Module-Funktion **muss** den Typ gegen diese Liste pruefen.

### type_code entschluesseln (das eigentliche „weird label")

Die Codes sind kompakt kodiert, nicht kryptisch:

- `R`**`5`**`M`**`0`** → **Endcap-Ring 5**, **Modul-Position 0** auf dem Petal. ⚠
- `R`**`5`**`H`**`1`** → Hybrid fuer Ring 5, Position 1. ⚠
- `ATLAS18R5` → Sensor-Generation **ATLAS18**, Ring 5. ⚠
- `PBR5` → Powerboard fuer Ring 5. ⚠
- `R0…R5` = **Endcap** (Petal-Ringe). `SS`/`LS`/`BS`/`BL` = **Barrel** (short/long
  strip). Die TUDO-Daten sind Endcap-R-Module (`R5M0`, `R5M1`). ✓⚠

**Beobachtetes Seriennummern-Muster** (aus den Mirror-Daten, gegen Live-PDB
bestaetigen ⚠): `20USE` + 2 Zeichen fuer die Art —
`20USE`**`5M`**`…` Modul · `20USE`**`5S`**`…` Sensor · `20USE`**`5H`**`…` Hybrid
· `20USE`**`PB`**`…` Powerboard. ✓ (im Fixture-Datensatz sichtbar)

### ASIC-Bestand: `CATEGORY_A`, `CATEGORY_X`, `BOND_PULLING`

Diese Werte sind **PDB-Stage-Codes von ASICs**, keine `component_type`- oder
`type_code`-Werte und keine Modul-Assembly-Stages. Die read-only zFlow-Referenz
modelliert fuer ABC/HCC unter anderem `ON_WAFER` als Anfang sowie
`CATEGORY_A`, `CATEGORY_X` und `BOND_PULLING` als alternative finale Stages; sie
markiert `CATEGORY_A` als `preferred` und ordnet `PULL_TEST` der Stage
`BOND_PULLING` zu. ✓ (`references/zeuthenflow/modules/dbObjects/dbAsics.py`, nur
gelesen)

| Stage | Belastbare Bedeutung | Konsequenz fuer Anzeige/Bestand |
|---|---|---|
| `CATEGORY_A` | Qualitaetskategorie A nach Wafer-Probing; in der Referenz final und bevorzugt. Oeffentliche ABCStar- und AMACStar-Unterlagen beschreiben A als innerhalb der erwarteten Parameter und fuer Detektorbau vorgesehen. ✓⚠ | Familienneutral nur als `Category A · preferred` erklaeren und den Rohcode sichtbar lassen. `Detector-grade` ist nur zulaessig, wenn die konkrete ASIC-Familie dies belegt. Das ist **keine** Erlaubnis, ASICs zu registrieren oder zu bewegen. |
| `CATEGORY_X` | Finale Nicht-A-Kategorie. Fuer ABCStar bedeutet X fehlgeschlagene Basistests/zu viele defekte Kanaele; solche Dice koennen noch fuer mechanische, Klebe- oder Wirebond-Versuche dienen. Fuer AMACStar bedeutet X mindestens einen vitalen Parameter ausserhalb des Bereichs und laut Quelle keine weitere Verwendung. Die Wiederverwendung ist also ASIC-familienabhaengig. ⚠ | Sicherer gemeinsamer Text: `Category X · family policy required`. Keine automatische Aussage `trash`, `available`, `not detector-grade` oder `usable for tests`, solange Familie und Institutsregel das nicht festlegen. |
| `BOND_PULLING` | In der Referenz finale ASIC-Stage und Zielstage des Testtyps `PULL_TEST`. ✓ | Als `Bond-pull sample` erklaeren; nicht als Qualitaetsrang zwischen A und X sortieren. Ob der Test destruktiv ist und ob der Chip danach Bestand bleibt, muss die aktuelle PDB-/Institutsregel festlegen. ⚠ |

Die Kategorien sind bei ABCStar und AMACStar fachlich belegt, aber fuer HCCStar
ist in den hier verfuegbaren Quellen keine gleich genaue A/X-Definition
gefunden worden. Deshalb muss die UI bei unbekannter ASIC-Familie Rohcode plus
neutralen Hinweis zeigen und darf keine Bestandsentscheidung ableiten.

Primaerquellen fuer die Qualitaetsbedeutung:

- [ABCStar production paper, arXiv:2605.22559](https://arxiv.org/abs/2605.22559)
- [AMACStar grading, CERN CDS ATL-ITK-PROC-2022-024](https://cds.cern.ch/record/2837316/files/ATL-ITK-PROC-2022-024.pdf)

Alle diese ASIC-Pfade bleiben in itkFlow read-only. `CATEGORY_A` ist niemals
ein Schlupfloch in der harten Regel: Sensoren und ASICs werden weder als DUMMY
registriert noch durch itkFlow in eine andere Stage geschrieben.

## 3. Wo die App die Labels herzieht (und warum sie „weird" wirken)

- Mirror: `component_type`, `type_code` wie oben. ✓
- Frontend `frontend/src/ui.ts` `roleLabel()` mappt **nur `component_type`** auf
  freundliche Namen (`MODULE`→„Module", `SENSOR`→„Sensor", `PWB`→„Powerboard"),
  faellt fuer alles andere auf den Rohwert zurueck. ✓
- **Der `type_code` wird nirgends uebersetzt** und roh angezeigt — deshalb sehen
  `R5M0`/`ATLAS18R5`/`PBR5` „weird" aus. Zudem ist `HYBRID_ASSEMBLY` nicht in der
  Map (nur `HYBRID`/`HYBRID_FLEX`), faellt also ebenfalls roh durch. ✓

**Umgesetzt (2026-07-10):** `frontend/src/ui.ts` dekodiert die Codes
institutsneutral (`describeTypeCode` / `describeComponent` / `componentKind`,
pattern-basiert, kein `R5M0 -> "…"`-Hardcoding, Regel #4-konform), verdrahtet in
Komponentenliste, Detail-Stammdaten, Family-Tree und Board-Card-Tooltip.
Beispiel: `R5M0` → „Module · Endcap R5, pos 0", `ATLAS18R5` → „Sensor ATLAS18,
Endcap R5". Unbekannte Codes fallen sauber auf den Rohwert zurueck.

Ebenso **Stage-Codes**: `stageLabel()` humanisiert `SNAKE_CASE`-Stages
(`HV_TAB_ATTACHED` → „HV Tab Attached", `STITCH_BONDING` → „Stitch Bonding") —
nur Unterstrich-Split + Title-Case, ITk-Akronyme (HV/IV/QC/PWB/…) bleiben
gross; kein institutsspezifisches Mapping (Regel #4). Verdrahtet in
Board-Spaltenkoepfe (Klartext + Rohcode als Mono-Unterzeile), Stage-Chips
(Klartext, Rohcode im `title`), Stage-Vorschlag-Texte und Statistik-Balken. Der
Rohcode bleibt ueberall als kanonische technische Referenz sichtbar (z. B. das
Stammdaten-Feld `Stage`). Test-Typ-Codes (`MODULE_IV_PS_V1`) bleiben bewusst roh
(echte technische Identifier).

## 4. Produktionsablauf: Modul von Anfang bis Ende

Grobschritte der Strip-Modul-Assembly, gemappt auf die PDB-Stages und das
Seed-Stage-Modell der App (`backend/app/domain/stages.py`,
`DEFAULT_STAGE_ORDER`, institutsneutral per `InstituteProfile.settings`
ueberschreibbar) ✓:

1. **Wareneingang & Einzelteil-Pruefung** — Sensor, Hybrid(e), Powerboard treffen
   ein; Visual Inspection + Metrologie (Masse, Bow). Hybride/PWB werden vor der
   Assembly elektrisch vorgetestet. ⚠
2. **`HV_TAB_ATTACHED`** — HV-Tab am Sensor; App-Pflichttests hier:
   `VISUAL_INSPECTION`, `MODULE_IV_PS_V1`. ✓
3. **`GLUED` — Kleben (Jig!)** — Hybrid(e) und Powerboard werden **auf einem
   modultyp-spezifischen Jig** auf den Sensor geklebt; Klebegewicht/-hoehe
   kontrolliert. App-Pflichttests: `GLUE_WEIGHT`, `MODULE_BOW`,
   `MODULE_METROLOGY`. ✓
   → **Genau hier braucht der PDB-Upload das benutzte Jig als Attachment-Property,
   sonst blockt er.** Seit 2026-07-10 vom Ingest-Dry-Run erzwungen, sobald das
   Institut es konfiguriert (§5).
4. **`STITCH_BONDING` → `BONDED` — Wire-Bonding** — ASIC-Kanaele auf die
   Sensorstreifen bonden (Stitch-Bonds), Hybrid↔Powerboard. App-Pflichttest bei
   `BONDED`: `MODULE_WIRE_BONDING` (inkl. Pull-Test). ✓
5. **`TESTED` — Modultests** — IV (Leckstrom vs. HV), Metrologie/Bow nach
   Assembly, AMAC/Thermal-Cycling, Response-/Strobe-Tests. App-Pflichttest:
   `MODULE_IV_AMAC_TC`. ✓
6. **`FINISHED`** — Modul fertig. Fehlerpfade: `FAILED` / `TRASHED` (im
   Farbsystem rot, sonst kuehl→gruen-Ramp). ✓

Stage-Reihenfolge & Pflichttests sind Seed-Defaults fuer Endcap; ein Institut
mit anderem Ablauf (Barrel) ueberschreibt sie im Profil — **kein Hardcoding**.

> **Achtung:** Die hier gelisteten Pflichttests sind der *Seed-Default* aus
> `DEFAULT_STAGE_REQUIREMENTS`, nicht der belegte TUDO-Ablauf. Der Abgleich
> gegen den echten lokalen Mirror (§7, 2026-08-26) zeigt, dass dieser Default
> 226 von 263 TUDO-Modulen blockiert. Vor jeder Aussage ueber „Pflichttests bei
> TUDO" bitte §7 lesen.

## 5. Konsequenzen fuer die Assembly-Features

- **Create Module** (`register_component`): **Umgesetzt (2026-07-10).**
  `POST /api/components/register` (operator-gated) validiert den Typ (nur
  MODULE/HYBRID → sonst 400) und legt einen `register_component`-Outbox-Draft an;
  Worker-Revalidate + der Submitter registrieren per
  `register_dummy_component` (harter Typ-Guard erneut, dummy-only + Access-Codes).
  Frontend: `RegisterModuleForm` bei den Komponenten (`canWrite`). Der eigentliche
  PDB-Write passiert nie direkt — nur ueber die genehmigte Outbox-Aktion. **Nie
  SENSOR/ASIC** (Guard an beiden Enden).
- **Jig-Pflicht beim Upload**: **Umgesetzt (2026-07-10).** Institutskonfigurierbare
  Pflicht-Properties pro Testtyp (`InstituteProfile.settings['required_properties']`,
  z. B. `{"GLUE_WEIGHT": ["JIG"]}`, Regel-#4-safe, Default leer);
  `ingestion.missing_required_properties` speist den Ingest-Dry-Run — `preview` +
  `propose-outbox` blocken, wenn das benutzte Jig in `payload['properties']`
  fehlt. Der Quick-Select aus der `Tool`-Registry ist seit 2026-08-26 im
  Assembly-Wizard umgesetzt. Semantische Felder (`tool`, `glue_batch`, `slot`)
  werden ueber `assembly_property_keys` im Institutsprofil auf bestaetigte
  PDB-Property-Codes gemappt; ohne Profil-Mapping wird kein Code erfunden.

- **Assembly-Wizard**: **Umgesetzt (2026-08-26).** Parent und Child werden
  exakt aus dem lokalen Mirror gescannt; aktive, zum Parent-`type_code`
  kompatible Tools und benutzbare Glue-Batches werden schnell ausgewaehlt.
  `POST /api/assembly/preview` und `POST /api/assembly/actions` verwenden
  dieselbe Validierung. Der Worker prueft aktuellen Komponenten-/Tool-/Glue-
  Zustand und Dry-run-Snapshots erneut. Der reale `assembleComponent`-Pfad ist
  vor Client-Aufbau auf DUMMY-`MODULE|HYBRID` fuer **beide** Teilnehmer
  begrenzt; Sensoren/ASICs sind nie zulaessig. Produktionskomponenten koennen
  fuer lokale Nachvollziehbarkeit staged, aber nicht submitted werden.

- **Metrologie-Ingestion**: Die Messprogramm-/zFlow-Ausgabe fuer `MODULE_METROLOGY`
  ist bereits die Standard-PDB-`uploadTestRunResults`-Form (Result-Groups
  `HYBRID_POSITION` / `HYBRID_GLUE_THICKNESS` / `CAP_HEIGHT` / …: Positionen als
  Abweichung vom Nominal, Hoehen in µm). itkFlow ingestet sie **direkt**; der
  Parser `module-metrology-v1` validiert die Group-Struktur (2026-07-10).
  **Offen:** der Roh-`.txt`→JSON-Converter (Glue-Thickness = Bauteil−Sensor,
  mm→µm, Positions-Abweichung), portierbar aus der zFlow-Referenz — braucht die
  Nominal-Positionstabellen je Modultyp.

## 6. Offene Fragen (gegen Live-PDB verifizieren)

- Exaktes `type_code`-Vokabular (alle Ringe/Positionen, Barrel-Codes) und die
  exakten `componentType`-Codes der ASICs (`ABCStar`/`HCCStar`/`AMAC`?).
- Exakte PDB-Property-Keys fuer „benutztes Jig" je Klebeschritt (Testtyp/Stage)
  je Institut bestaetigen und anschliessend im Profil konfigurieren.
- Seriennummern-Schema (§2) offiziell bestaetigen.
- Barrel- vs. Endcap-Stagenamen, falls ein zweites Institut Barrel baut.

## 7. Stage-Profil vs. echte TUDO-Daten (Datenabgleich 2026-08-26)

> Zweck: die Frage „passt das Seed-Stage-Profil zu dem, was TU Dortmund
> tatsaechlich aufzeichnet?" mit Zahlen statt Meinung beantworten. Alle Zahlen
> stammen aus einer **Lesekopie** des lokalen Mirrors
> (`backend/itkflow_tudo.db`, in ein Scratch-Verzeichnis kopiert und dort
> abgefragt). Kein PDB-Zugriff, kein Sync, keine Aenderung an Code oder Profil.

### 7.1 Datenbasis und ihre Grenzen

| Fakt | Wert |
|---|---|
| Letzter Komponenten-Sync | 2026-08-25 23:01, `fetched=3799`, `total=2538` |
| Letzter Evidence-Sweep | 2026-08-26 06:33, `succeeded` |
| **Scope dieses Sweeps** | `component_types: ["MODULE"]` — **nur Module** |
| Im Sweep verarbeitet | 262 Komponenten, 712 Testlaeufe, 362 Attachments (349 geladen, 13 fehlgeschlagen) |
| `component` | 3153 Zeilen, davon 263 `MODULE` (262 TUDO, 1 UT); 3120 mit `location=TUDO` |
| `test_run_evidence` | 713 Zeilen, **alle** `source='pdb'`, **alle** auf `MODULE` |
| `test_type_schema` | **0 Zeilen** (Testtyp-Schema-Mirror ist leer) |
| `institute_profile['TUDO'].settings` | nur `{"logo_url": …}` — **kein** `stage_order`, **kein** `stage_requirements` |

Zwei Konsequenzen, die man kennen muss, bevor man die Tabellen liest:

1. **TUDO faehrt heute vollstaendig auf dem Seed-Default.** Das Profil enthaelt
   keinen einzigen Stage-Override. Alles, was `stage_model_from_settings`
   zurueckgibt, ist `DEFAULT_STAGE_ORDER` / `DEFAULT_STAGE_REQUIREMENTS`. ✓
2. **Zu Hybriden, Sensoren, Flexes und Powerboards gibt es hier keine
   Evidenz-Aussage.** Nicht weil sie keine Testlaeufe haetten, sondern weil der
   einzige erfolgreiche Sweep mit `component_types=["MODULE"]` lief. Der
   Code-Default `DEFAULT_EVIDENCE_COMPONENT_TYPES` (`app/sync_jobs.py`) deckt
   inzwischen 10 Typen ab; er wurde nach diesem Sweep erweitert und ist noch
   nie gelaufen. Alle 1075 ABC, 386 SENSOR, 388 SENSOR_HALFMOONS, 144 HCC,
   119 PWB, 107 AMAC, 98 HYBRID_FLEX, 98 HYBRID_ASSEMBLY, 97 EC_POWERBOARD_FLEX,
   13 HYBRID, 10 HV_TAB_SHEET im Mirror haben **0** Evidence-Zeilen. Der
   Punkt „Evidence-Umfang erweitert" der Roadmap ist im Code umgesetzt, **im
   Datenbestand aber noch nicht wirksam**. Aussagekraeftig wird der
   Nicht-Modul-Teil erst nach einem erneuten Institutssweep. ⚠

### 7.2 Was TUDO auf Modulen wirklich aufzeichnet

Alle 263 Module, „Komponenten" = mit mindestens einem Lauf, Pass/Fail nach der
Last-Run-wins-Regel aus `stage_service.satisfied_test_results`:

| Testtyp | Laeufe | Komponenten | latest pass | latest fail | Abdeckung |
|---|---|---|---|---|---|
| `MODULE_IV_PS_V1` | 219 | 191 | 184 | 7 | 72,6 % |
| `GLUE_WEIGHT` | 132 | 109 | 92 | 17 | 41,4 % |
| `MODULE_METROLOGY` | 104 | 93 | 19 | **74** | 35,4 % |
| `MODULE_IV_AMAC` | 129 | 44 | 41 | 3 | 16,7 % |
| `MODULE_IV_AMAC_TC` | 56 | 40 | 36 | 4 | 15,2 % |
| `VISUAL_INSPECTION` | 25 | 21 | 9 | 12 | **8,0 %** |
| `MODULE_BOW` | 28 | 19 | 16 | 3 | **7,2 %** |
| `MODULE_WIRE_BONDING` | 17 | 14 | 13 | 1 | **5,3 %** |
| `VISUAL_INSPECTION_RECEPTION` | 3 | 1 | 0 | 1 | 0,4 % |

Der entscheidende Schnitt liegt aber nicht auf „Modul", sondern auf der
**Familie** (`type_code`). Halbmodule und Ringmodule zeichnen voellig
verschiedene Dinge auf — Komponenten mit mindestens einem Lauf: ✓

| Testtyp | R2 (n=81) | R5-Ring (n=29) | R5M0 (n=76) | R5M1 (n=74) | R0 (n=3) |
|---|---|---|---|---|---|
| `MODULE_IV_PS_V1` | 75 | **0** | 57 | 59 | 0 |
| `GLUE_WEIGHT` | 40 | **0** | 34 | 35 | 0 |
| `MODULE_METROLOGY` | 36 | **0** | 29 | 28 | 0 |
| `MODULE_BOW` | 12 | **0** | 4 | 3 | 0 |
| `MODULE_WIRE_BONDING` | 10 | 2 | 1 | 1 | 0 |
| `MODULE_IV_AMAC` | 25 | 19 | **0** | **0** | 0 |
| `MODULE_IV_AMAC_TC` | 24 | 16 | **0** | **0** | 0 |
| `VISUAL_INSPECTION` | 10 | 3 | 5 | 2 | 1 |

Und die Stages, auf denen diese Familien stehen: ✓

| Stage | R2 | R5-Ring | R5M0 | R5M1 | R0 |
|---|---|---|---|---|---|
| `HV_TAB_ATTACHED` | 32 | 0 | 31 | 34 | 0 |
| `GLUED` | 4 | 0 | 13 | 12 | 2 |
| `STITCH_BONDING` | 0 | 0 | 25 | 25 | 0 |
| `BONDED` | 7 | 5 | 0 | 0 | 0 |
| `TESTED` | 8 | 5 | 1 | 0 | 0 |
| `FINISHED` | 14 | 8 | 0 | 0 | 0 |
| `AT_LOADING_SITE` | 2 | 3 | 0 | 0 | 0 |
| `ON_CORE` | 2 | 2 | 0 | 0 | 0 |
| `LIMBO` | 0 | 1 | 0 | 0 | 0 |
| `STUFFED` | 0 | 0 | 0 | 0 | 1 |
| `FAILED` | 12 | 5 | 6 | 3 | 0 |

Das deckt sich exakt mit der Referenzstruktur in
`references/zeuthenflow/modules/dbObjects/dbModule.py`: `DBHalfModule` (R3/R4/R5)
endet bei `STITCH_BONDING`, `DBRingModule` (R0/R1/R2) laeuft bis `FINISHED` und
weiter nach `AT_LOADING_SITE`/`ON_CORE`. Die 29 R5-Ringmodule haben im Mirror
jeweils **genau 2** Halbmodul-Kinder; 92 Halbmodule haben noch kein Elternteil
(Sibling/Stitching noch offen). ✓

**Der wichtigste Befund dieser Tabelle:** Ein R5-Ringmodul traegt selbst
*keinen* `MODULE_IV_PS_V1`, *kein* `GLUE_WEIGHT`, *keine* `MODULE_METROLOGY` —
diese Evidenz liegt auf seinen beiden Halbmodulen. Umgekehrt traegt ein
Halbmodul *nie* eine AMAC-IV. Jede Pflichtregel, die eine Komponente gegen
ihre **eigene** Evidenz prueft, kann fuer R5-Ringmodule ausser den AMAC-IVs
nichts fordern, ohne alle 29 dauerhaft zu blockieren.

### 7.3 `MODULE_IV_AMAC` vs. `MODULE_IV_AMAC_TC` — die konkrete Antwort

**Beide existieren im Mirror, beide werden aktiv verwendet.** Es ist kein
Namensproblem und keine Umbenennung, sondern zwei verschiedene Messungen: ✓

| | `MODULE_IV_AMAC` | `MODULE_IV_AMAC_TC` |
|---|---|---|
| Laeufe / Komponenten | 129 / 44 | 56 / 40 |
| Erster Lauf im Mirror | 2024-09-16 | 2025-09-17 |
| Letzter Lauf | 2026-08-19 | 2026-08-25 |
| Result-Struktur `VOLTAGE`/`CURRENT` | 1D-Array (meist 59 Punkte) | **2D**-Array: 24 Zyklen × 59 Punkte (52 von 54 Laeufen; 2 Laeufe mit 22 Zyklen) |
| `VBD`, `I_500V`, `TEMPERATURE`, `HUMIDITY` | Skalare | **Arrays** (ein Wert je Zyklus) |
| Zusatz-`properties` | `AMAC_CURRENT_RANGE`, `AMAC_READINGS` | `itsdaq_test_info` |
| Laeufe je Komponente | 1–28 (Median 2) | 1–3 (29 von 40 haben genau einen) |
| Traeger-Familien | R2 (25), R5-Ring (19), Halbmodule 0 | R2 (24), R5-Ring (16), Halbmodule 0 |
| Ueberlappung | 33 Module haben beide · 11 nur AMAC · 7 nur TC | |

`_TC` ist also die **Thermal-Cycling-IV**: dieselbe AMAC-IV, aber je Kuehlzyklus
einmal aufgenommen und als Zyklen-Array abgelegt. `MODULE_IV_AMAC` ohne Suffix
ist die einzelne „quick electrical" IV bei Raumtemperatur — deshalb wird sie
auch wiederholt (ein Modul hat 28 Laeufe), waehrend `_TC` typischerweise ein
einmaliges Kampagnenergebnis ist.

Das deckt sich mit der zFlow-Referenz, die diese Unterscheidung explizit macht
(`references/zeuthenflow/`, nur gelesen):

- `dbModule.DBRingModule.stageOfTest`: `MODULE_IV_AMAC` → **`BONDED`**,
  `MODULE_IV_AMAC_TC` → **`TESTED`**.
- `dbModule.DBHalfModule.stageOfTest`: **beide** → `STITCH_BONDING`.
- `core/moduleManager.py` prueft am Ringmodul bei `BONDED` hart auf
  `MODULE_IV_AMAC` und bei `TESTED` auf die Gruppe
  `["MODULE_IV_AMAC", "MODULE_IV_AMAC_TC"]` mit `eitherOrTests=True`.
- Kommentar dort: „we always need an MODULE_IV_AMAC, it is either from the
  quick electrical test or from TC (if the date is older than December 2024)" —
  vor 12/2024 zaehlte der eine AMAC-Lauf fuer beides, danach sind es zwei Tests.
  Genau dieser Bruch ist im TUDO-Mirror sichtbar: `_TC` taucht erst ab 09/2025
  ueberhaupt auf.
- Die Either-Or-Semantik in `dbComponent.getTestPassedMsg` lautet: **passed**,
  sobald *ein* Gruppenmitglied besteht; **missing** nur, wenn *alle* fehlen;
  **failed**, wenn keins besteht und mindestens eins vorliegt.

Belastbarkeit in den TUDO-Daten: von den 31 Modulen, die den lokalen Ablauf
nachweislich beendet haben (`FINISHED` + `AT_LOADING_SITE` + `ON_CORE`), tragen
**31/31** mindestens eine AMAC-IV und bei **31/31** besteht mindestens eine
davon. Kein anderer Testtyp erreicht das: `MODULE_IV_PS_V1` 18/31,
`GLUE_WEIGHT` 17/31, `MODULE_METROLOGY` 16/31 (davon **0** bestanden),
`MODULE_BOW` 4/31, `MODULE_WIRE_BONDING` 1/31, `VISUAL_INSPECTION` **0/31**.

**Fazit zur Ausloeserfrage:** Der Seed-Eintrag `TESTED: ("MODULE_IV_AMAC_TC",)`
ist nicht falsch benannt — er ist nur **zu eng**. Er fordert ein
Gruppenmitglied statt der Gruppe und laesst `MODULE_IV_AMAC` ganz aus dem
Modell fallen, weshalb es im Worksheet in „Additional" landet. Fuer das
konkrete Modul `20USEM50000064` (R5, Stage `FAILED`, 28 `MODULE_IV_AMAC`-Laeufe,
davon 27 bestanden, kein `_TC`) waere die Gruppe erfuellt.
Nebenbefund: Da `FAILED` nicht in `stage_order` steht, liefert
`requirements_through('FAILED')` eine **leere** Liste — die
`missing`-Anzeige stammt aus der Worksheet-Projektion in `preview.py`, die
bewusst *alle* Stages des Modells rendert. Der Stage-Vorschlag selbst wird
durch diese Zeile nicht blockiert; die Anzeige ist trotzdem irrefuehrend.

### 7.4 Wirkung des heutigen Seed-Profils (Simulation auf dem Mirror)

Die Seed-Regeln wurden gegen alle 263 Module durchgerechnet (Nachbau der
Semantik von `requirements_through` / `evaluate_stage`, kein Import):

| Profil | Module mit mindestens einem blockierenden Pflichttest |
|---|---|
| **Seed (heute aktiv)** | **226 von 263 (86 %)** |
| Familienbewusster Vorschlag (§7.5) | 67 von 263 (25 %) |

Blockierungsgruende des Seed-Profils, nach Haeufigkeit:

| Grund | Faelle |
|---|---|
| `HV_TAB_ATTACHED` · `VISUAL_INSPECTION` fehlt | 216 |
| `GLUED` · `MODULE_BOW` fehlt | 119 |
| `GLUED` · `MODULE_METROLOGY` **failed** | 65 |
| `HV_TAB_ATTACHED` · `MODULE_IV_PS_V1` fehlt | 54 |
| `GLUED` · `MODULE_METROLOGY` fehlt | 46 |
| `BONDED` · `MODULE_WIRE_BONDING` fehlt | 43 |
| `GLUED` · `GLUE_WEIGHT` fehlt / failed | 35 / 11 |
| `TESTED` · `MODULE_IV_AMAC_TC` fehlt / failed | 8 / 3 |

Damit ist die Ausgangsvermutung bestaetigt **und zugleich relativiert**: die
`_TC`-Zeile ist real ein falscher Blocker, aber mit 11 von 226 Faellen der
*kleinste*. Es gibt kein einziges Modul, das ausschliesslich an `_TC` haengt —
`VISUAL_INSPECTION` und `MODULE_BOW` blockieren vorher.

### 7.5 Empfehlung: konkrete `stage_order` / `stage_requirements`

Zu lesen als Entscheidungsvorlage, nicht als beschlossene Aenderung. Der
Vertrag ist `stage_model_from_settings` (`backend/app/domain/stages.py`):
`settings["stage_order"] = list[str]`, `settings["stage_requirements"] =
{stage: [test_type, …]}`, Ersetzung je Stage (kein Deep-Merge), ungueltige
Formen fallen still auf den Default zurueck.

**Sofort umsetzbar mit dem heutigen Vertrag** (ein Profil je Institut, nur
„required & must pass"-Semantik):

```json
{
  "stage_order": [
    "HV_TAB_ATTACHED",
    "GLUED",
    "STITCH_BONDING",
    "BONDED",
    "TESTED",
    "FINISHED",
    "AT_LOADING_SITE",
    "ON_CORE"
  ],
  "stage_requirements": {
    "HV_TAB_ATTACHED": [],
    "GLUED": [],
    "STITCH_BONDING": [],
    "BONDED": [],
    "TESTED": ["MODULE_IV_AMAC"],
    "FINISHED": [],
    "AT_LOADING_SITE": [],
    "ON_CORE": []
  }
}
```

Bewertung je Zeile:

| Empfehlung | Konfidenz | Evidenz |
|---|---|---|
| `VISUAL_INSPECTION` aus `HV_TAB_ATTACHED` **entfernen** | **hoch** | 21/263 Module haben ihn ueberhaupt, 0/31 der abgeschlossenen Module; zFlow fuehrt ihn ausdruecklich als `optionalTests`. Groesster Einzelblocker (216 Faelle). |
| `MODULE_BOW` aus `GLUED` **entfernen** | **hoch** | 19/263, 4/31 abgeschlossen; zFlow: `ifPresentTests`. 119 Faelle. |
| `MODULE_WIRE_BONDING` aus `BONDED` **entfernen** | **hoch** | 14/263, 1/31 abgeschlossen; zFlow: `ifPresentTests` (zusammen mit VI und BOW). 43 Faelle. |
| `MODULE_METROLOGY` als **Pass-Gate entfernen** | **hoch** fuer „nicht als Pass-Gate", **offen** fuer den Ersatz | 93/263 haben sie, aber nur 19 bestehen; **0 von 16** abgeschlossenen Modulen mit Metrologie hat einen bestandenen letzten Lauf. Als Pass-Gate wuerde sie 80 % der TUDO-Produktion sperren. |
| `MODULE_IV_AMAC` **und** `_TC` als Either-Or-Gruppe bei `TESTED` | **hoch** fachlich, **niedrig** technisch | 31/31 abgeschlossene Module erfuellen die Gruppe; zFlow codiert sie explizit als `eitherOrTests=True`. Der heutige `StageModel` kennt aber **keine Gruppen** — die JSON oben listet als Behelf nur `MODULE_IV_AMAC` (44 Traeger gegenueber 40 bei `_TC`) und laesst damit 7 „nur `_TC`"-Module faelschlich blockiert. Sauber loesbar erst mit §7.6. |
| `MODULE_IV_PS_V1` bei `HV_TAB_ATTACHED` fordern | **mittel — nur familienbewusst** | R2 66/71 und Halbmodule 110/140 der Module ab dieser Stage; **R5-Ring 0/29**. Ohne Familientrennung sperrt diese Zeile alle R5-Ringmodule. |
| `GLUE_WEIGHT` bei `GLUED` fordern | **mittel — nur familienbewusst, und nur „vorhanden"** | R2 33/39 und Halbmodule 64/75 ab `GLUED`; R5-Ring 0/29. Ausserdem haben 3 der 18 abgeschlossenen R2-Module einen **fehlgeschlagenen** letzten Glue-Weight-Lauf — zFlow fuehrt ihn genau deshalb als `mayFailTests` („muss vorliegen, darf durchfallen"). Als Pass-Gate waere er falsch. |
| `AT_LOADING_SITE` und `ON_CORE` an `stage_order` anhaengen | **hoch** | 9 beobachtete Uebergaenge `FINISHED → AT_LOADING_SITE`, 4 `AT_LOADING_SITE → ON_CORE`; 9 Module stehen heute dort. |
| `FAILED`, `LIMBO`, `QA`, `TRASHED`, `STUFFED` **nicht** in `stage_order` | **hoch** | Sie sind Endzustaende, keine Fortschrittsschritte. Ausserhalb der Order liefert `requirements_through` bewusst nur die eigenen (leeren) Requirements — das ist das gewuenschte Verhalten. |

Wenn die Familientrennung kommt (§7.6), waere die evidenzgestuetzte Zielform:

```text
Halbmodul (R5M0/R5M1, in der PDB R3–R5):
  order: HV_TAB_ATTACHED, GLUED, STITCH_BONDING,
         AT_LOADING_SITE, HALFMODULE_FOR_LOADING, ON_CORE
  HV_TAB_ATTACHED: [MODULE_IV_PS_V1]        (110/140 ab Stage, 108 bestanden)
  GLUED:           [GLUE_WEIGHT] (present)   (64/75 ab Stage)
  STITCH_BONDING:  []

Ringmodul R0/R2 (Ringmodul = Modul selbst):
  order: HV_TAB_ATTACHED, GLUED, STITCH_BONDING, BONDED, TESTED,
         FINISHED, AT_LOADING_SITE, ON_CORE
  HV_TAB_ATTACHED: [MODULE_IV_PS_V1]         (26/26 ab TESTED, alle bestanden)
  GLUED:           [GLUE_WEIGHT] (present)    (24/26 ab TESTED)
  BONDED:          []                          (zFlow fordert hier MODULE_IV_AMAC — TUDO-Daten
                                                stuetzen das nicht: nur 20/33 ab BONDED)
  TESTED:          [MODULE_IV_AMAC | MODULE_IV_AMAC_TC]  (25/26 ab TESTED, alle bestanden)

Ringmodul R5 (Eltern zweier Halbmodule):
  order: wie R0/R2
  alles vor TESTED: []   — die Evidenz liegt auf den Kindern
  TESTED: [MODULE_IV_AMAC | MODULE_IV_AMAC_TC]  (16/18 ab TESTED, alle bestanden)
```

Blockierrate dieser Zielform auf den echten Daten: **67 von 263** (Halbmodule
51/150, R0/R2 14/84, R5-Ring 2/29) — und jeder verbleibende Fall ist eine echte
Luecke (fehlender IV_PS bzw. fehlendes/fehlgeschlagenes Glue Weight), kein
Modellartefakt.

### 7.6 Was der heutige Vertrag nicht ausdruecken kann

Vier Luecken zwischen `StageModel` und der belegten Realitaet. Alle vier sind
Vorschlaege an den Owner, keine beschlossenen Aenderungen:

1. **Keine Requirement-Modi.** zFlow kennt vier: `required` (muss bestehen),
   `mayFail` (muss vorliegen, darf durchfallen — `GLUE_WEIGHT`), `optional`
   (darf fehlen — `VISUAL_INSPECTION`, `HVSTABILITY`) und `ifPresent` (nur
   bewerten, wenn vorhanden — `MODULE_BOW`, `MODULE_WIRE_BONDING`).
   `StageModel.required_tests` kennt nur den ersten. Ohne die anderen bleibt
   nur „fordern oder weglassen", und `GLUE_WEIGHT`/`MODULE_METROLOGY` passen in
   keine der beiden Schubladen.
2. **Keine Either-Or-Gruppen.** Siehe §7.3. Vorschlag fuer eine
   abwaertskompatible Form: ein Listenelement darf selbst eine Liste sein
   (`"TESTED": [["MODULE_IV_AMAC", "MODULE_IV_AMAC_TC"]]`), Semantik wie in
   zFlow (passed bei einem Treffer, missing nur bei allen fehlend).
3. **Ein Profil je Institut, aber zwei Bauteilfamilien.** TUDO baut Halbmodule
   *und* Ringmodule mit unterschiedlichen Stage-Listen im selben Institut.
   Vorschlag: `stage_profiles` als Mapping `type_code`-Muster → Modell, mit dem
   heutigen flachen `stage_order`/`stage_requirements` als Fallback.
4. **Keine Kind-Evidenz.** Ein R5-Ringmodul ist erst fertig, wenn *beide*
   Halbmodule fertig sind (zFlow: `bothHalfModulesPass` + `ringModulePass`).
   `evaluate_stage` sieht nur die eigene Komponente. Solange das so ist, darf
   ein R5-Ringmodul ausser den AMAC-IVs nichts gefordert bekommen.

Zusaetzlich ein Datenmodell-Befund: **`TestRunEvidence` speichert nicht, bei
welcher Stage ein Lauf aufgenommen wurde.** zFlow filtert genau darauf
(`stageFilter`), und `MODULE_IV_AMAC` bei `BONDED` ist dort fachlich etwas
anderes als `MODULE_IV_AMAC` bei `TESTED`. Weder Spalte noch Payload
(`state`, `problems`, `results`, `result_meta`, `properties`, `attachments`,
`run_number`) enthalten die Stage. Solange sie fehlt, kann itkFlow den
zFlow-Ablauf nur naeherungsweise nachbilden.

### 7.7 Weitere Abweichungen Seed ↔ Realitaet

**UI-Sicherheitsmarker (2026-08-28):** Board, Komponentenliste und Detailseite
zeigen `Production hold`, wenn eine Modul-Stage nach dem *effektiven
konfigurierten Modell* bereits ueber eine Requirement-Stage hinausgelaufen ist,
deren neueste lebende Evidenz fehlt oder fehlschlaegt. Tests der aktuellen
Arbeitsstage sind noch kein Verstoss. Modellfremde/stale Stages bleiben
`unassessed`; Nicht-Module werden nicht gegen das Modulmodell geprueft. Solange
das effektive Profil nicht explizit mit `stage_policy_approved=true` fachlich
abgenommen ist, nennt jeder Treffer `provisional workflow` und ein unauffaelliger
Befund wird nicht als fachliches `clear` ausgegeben. Der
Marker ist damit eine priorisierte Konfigurationsabweichung, kein Beweis fuer
einen physischen Defekt und kein Ersatz fuer die Profilentscheidung aus §7.6.

- **Stages im Mirror, die es im Seed nicht gibt:** `FAILED` (26 Module),
  `AT_LOADING_SITE` (5), `ON_CORE` (4), `LIMBO` (1), `STUFFED` (1) — zusammen
  37 von 263 (14 %). Aus `stage_event` zusaetzlich als reale Uebergaenge
  belegt: `FINISHED → AT_LOADING_SITE` (9×), `AT_LOADING_SITE → ON_CORE` (4×),
  `TESTED → FAILED` (11×), sowie Rework-Rueckwege wie `FAILED → TESTED` (3×).
  Die zFlow-Stagelisten kennen zudem `QA` und `HALFMODULE_FOR_LOADING`, die im
  TUDO-Mirror (noch) nicht vorkommen. ⚠
- **`STITCH_BONDING` ist fuer Vollmodule ein toter Schritt.** In `stage_event`
  gibt es fuer Vollmodule nur 5 `STITCH_BONDING`-Ereignisse (ueberwiegend
  Rework), gegenueber 57 fuer Halbmodule. Der reale Vollmodulpfad ist
  `HV_TAB_ATTACHED → GLUED → BONDED → TESTED → FINISHED`; `GLUED → BONDED`
  40×, daneben 23× `HV_TAB_ATTACHED → BONDED` (uebersprungenes `GLUED`).
- **Pflichttests, die praktisch niemand aufzeichnet:** `VISUAL_INSPECTION`
  (8,0 %), `MODULE_BOW` (7,2 %), `MODULE_WIRE_BONDING` (5,3 %).
- **Test, den viele aufzeichnen und den nichts fordert:** `MODULE_IV_AMAC`
  (129 Laeufe auf 44 Modulen) — der Ausloeser dieser Analyse. Ebenfalls
  ungefordert: `VISUAL_INSPECTION_RECEPTION` (3 Laeufe, 1 Modul); der gehoert
  fachlich in `shipment_reception_tests`
  ([docs/11](11-logistics-operations.md)), nicht in die Stage-Regeln.
- **`MODULE_METROLOGY` faellt systematisch durch**, aber ungleich verteilt:
  R5M1 15/28 bestanden, R2 3/36, R5M0 1/29. Die Payload-Struktur ist bei
  bestandenen und durchgefallenen Laeufen identisch (`HYBRID_POSITION`,
  `HYBRID_GLUE_THICKNESS`, `PB_POSITION`, `PB_GLUE_THICKNESS`, `CAP_HEIGHT`,
  `SHIELDBOX_HEIGHT`), es ist also ein echtes Analyseurteil der PDB und kein
  Formatproblem. Der `GRADEB`-Mechanismus in zFlow
  (`core/uploadManager.setGradeBFlag`) haengt an einem eigenen Feld der
  Metrologie-JSON, nicht am `passed`-Flag — er erklaert die Quote also nicht.
  **Ungeklaert und nur fachlich zu klaeren:** ob TUDO hier tatsaechlich
  systematisch ausserhalb der Toleranz liegt (dann ist es ein Qualitaetsthema,
  kein Profilthema) oder ob die hochgeladenen Metrologie-Laeufe gegen eine
  falsche Nominal-/Toleranztabelle bewertet werden. ⚠
- **Geloeschte Testlaeufe werden mitgespiegelt.** 33 der 713 Zeilen haben
  `state='deleted'`, eine `requestedToDelete`. Heute harmlos: nur **ein**
  (Komponente, Testtyp)-Paar von 532 hat einen geloeschten Lauf als juengsten,
  und dessen Urteil stimmt mit dem juengsten gueltigen Lauf ueberein. Die
  Last-Run-wins-Regel filtert `state` aber nicht, deshalb kann ein spaeter
  geloeschter Lauf ein Modul kuenftig faelschlich auf `failed` ziehen. ⚠
- **Der Testtyp-Schema-Mirror ist leer** (`test_type_schema` = 0 Zeilen). Die
  PDB ist die Autoritaet fuer die Bedeutung von `MODULE_IV_AMAC` gegenueber
  `MODULE_IV_AMAC_TC`; ihre offiziellen `name`-Felder liegen lokal nicht vor.
  **Was die Restunsicherheit aufloesen wuerde:** ein read-only
  `POST /api/test-types/sync` ueber die persoenliche Verbindung — danach steht
  der offizielle Anzeigename beider Codes im Mirror und die Zuordnung
  „`_TC` = Thermal-Cycling-IV" ist bestaetigt statt aus der Datenstruktur
  erschlossen.

### 7.8 Offene Punkte, die nur der Owner oder ein Sweep klaeren kann

1. Soll `MODULE_METROLOGY` „vorhanden" gefordert werden (zFlow-`mayFail`-Stil)
   oder gar nicht? Als Pass-Gate ist sie mit 19/93 bestanden nicht tragbar.
2. Sind die 74 durchgefallenen Metrologie-Laeufe fachlich korrekt? (§7.7)
3. Ist `MODULE_IV_AMAC` bei `BONDED` fuer TUDO Pflicht wie bei DESYZ? Die Daten
   stuetzen es nicht (20/33 ab `BONDED`), widerlegen es aber auch nicht — die
   fehlende Stage-Angabe je Lauf (§7.6) macht die Frage aus dem Mirror heraus
   unentscheidbar.
4. Der Nicht-Modul-Teil dieser Analyse (Hybride, Sensoren, Flexes, Powerboards)
   braucht zwingend einen erneuten Institutssweep mit dem erweiterten Scope.
   Vorher ist jede Aussage dazu unbelegt.

## Roadmap-Einordnung

Domain-Grundlage fuer **Phase 3** (Assembly-Wizards, Registrierung,
Stage-Vorschlaege) und [`docs/07`](07-jig-tool-quickselect.md)
(Jig-Quick-Select). Siehe [`04-roadmap.md`](04-roadmap.md).
§7 gehoert zum Arbeitspaket „Stage-Move-Strecke schliessen" und ist die
Datengrundlage fuer den Profil-Editor (GUI in
[`05-ui-design-reference.md`](05-ui-design-reference.md), „Admin Settings →
Production stages"); die dort empfohlenen Werte werden vom Owner gesetzt, nicht
vom Code.

# ITk-Domain-Referenz: Strip-Modul-Workflow & Komponenten-Taxonomie

> Zweck: die „weird labels" entschluesseln (was ist `component_type`, `type_code`,
> `R5M0`, `ATLAS18R5`), festhalten **welche Komponenten Sensoren/ASICs sind**
> (harte Regel #2 — nie registrieren) und den ITk-Strip-Modul-Produktionsablauf
> von Anfang bis Ende beschreiben, damit Assembly-Features (Create Module,
> Jig-Pflicht, Stage-Vorschlaege) auf einem sauberen Domain-Verstaendnis stehen.
>
> Legende: ✓ = im Repo/Mirror-Daten verifiziert · ⚠ = ITk-Allgemeinwissen, gegen
> Live-PDB zu bestaetigen.

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
Kollaborations-Seriennummern (harte Regel #2, `docs/09`, ADR 003). Eine
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
   sonst blockt er.** Aktuell nicht erzwungen (siehe §5).
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

## 5. Konsequenzen fuer die offenen Assembly-Features

- **Create Module** (`register_component`): **Umgesetzt (2026-07-10).**
  `POST /api/components/register` (operator-gated) validiert den Typ (nur
  MODULE/HYBRID → sonst 400) und legt einen `register_component`-Outbox-Draft an;
  Worker-Revalidate + der Submitter registrieren per
  `register_dummy_component` (harter Typ-Guard erneut, dummy-only + Access-Codes).
  Frontend: `RegisterModuleForm` bei den Komponenten (`canWrite`). Der eigentliche
  PDB-Write passiert nie direkt — nur ueber die genehmigte Outbox-Aktion. **Nie
  SENSOR/ASIC** (Guard an beiden Enden).
- **Jig-Pflicht beim Upload**: Nicht abgedeckt. `pdb_upload.build_upload_test_run_payload`
  reicht `properties` nur durch ✓; `stages.py` kennt nur `required_tests`, **keine
  required Attachment-Properties**. Loesung: pro Stage/Testtyp konfigurierbare
  Pflicht-Properties (institutsneutral wie `required_tests`), die der Dry-Run
  blockt, wenn das Jig fehlt — plus Quick-Select aus der `Tool`-Registry
  (`docs/07`).

## 6. Offene Fragen (gegen Live-PDB verifizieren)

- Exaktes `type_code`-Vokabular (alle Ringe/Positionen, Barrel-Codes) und die
  exakten `componentType`-Codes der ASICs (`ABCStar`/`HCCStar`/`AMAC`?).
- Exakte PDB-Property-Keys fuer „benutztes Jig" je Klebeschritt (Testtyp/Stage).
- Seriennummern-Schema (§2) offiziell bestaetigen.
- Barrel- vs. Endcap-Stagenamen, falls ein zweites Institut Barrel baut.

## Roadmap-Einordnung

Domain-Grundlage fuer **Phase 3** (Assembly-Wizards, Registrierung,
Stage-Vorschlaege) und `docs/07` (Jig-Quick-Select). Siehe `docs/04-roadmap.md`.

# Plan: Jig-/Tool-Registry und typ-gefilterter Quick-Select

> Planungsdokument mit Umsetzungsstand. Legt fest, wie Attachment-Properties
> (Jigs, Pickup-Tools, Glue-Batches) im Assembly-Wizard **abhaengig vom
> Modultyp per Quick-Select** ausgewaehlt werden statt per Handeingabe.
>
> Stand 2026-07-08: Basis umgesetzt fuer lokale `Tool`-Registry, Tools-Screen,
> Scanner-Aufloesung und read-only Import aus bereits gespiegelten
> PDB-`TOOLS`-Komponenten (`POST /api/sync/tools/{institute}`). Glue-Batches
> und direkte Assembly-Wizard-Integration sind noch offen.

## Problem / Motivation

Beim Erfassen eines Bauschritts (z. B. Hybride kleben) haengen viele Felder vom
**R-Type des Moduls** ab — das HV-Tab-Jig, Pickup-Tools, Klebe-Zielwerte,
Panels. Diese von Hand einzutippen ist fehleranfaellig und langsam. Sie
korrelieren mit dem Modultyp und sollten **gefiltert vorgeschlagen** werden.

Das Muster existiert schon: Klebe-Ziele haengen in
[`backend/app/domain/glue.py`](../backend/app/domain/glue.py)
(`DEFAULT_MODULE_GLUE_TARGETS`) am Modultyp, Pflichttests an der Stage
(`app/domain/stages.py`). Jigs/Tools gehoeren genauso modelliert — als Daten,
nicht als Code (harte Regel #4).

## Datenmodell (additiv)

`Tool` (Jig-/Werkzeug-Registry)
- `id` PK
- `kind`: `jig` | `pickup_tool` | `panel` | … (erweiterbar)
- `code` (lokale/Instituts-Kennung), `rfid` (nullable)
- `compatible_types`: Liste der Modultypen/R-Types, fuer die das Tool passt
  (z. B. `["R5M0", "R5M1"]`) — die eigentliche Korrelation, als **Config/Daten**.
- `institute_id` FK (Registry ist institutsspezifisch)
- `status`: `active` | `flagged` | `blacklisted`
- `created_at`

Optional generisch: eine `attachment_property`-Konfiguration pro Komponententyp
(welche Properties beim Assemblieren erwartet werden), gespeist aus PDB-Schema +
Institut-Profil — statt fixer Felder im Wizard.

## Kompatibilitaets-Logik

- Quelle der Wahrheit fuer „welches Jig passt zu welchem Modultyp" ist die
  `compatible_types`-Liste je Tool (Registry) bzw. das Institut-Profil — **nie
  ein hartkodiertes `R5M0 -> Jig X` im Code**.
- Der Wizard liest den **gescannten Modultyp** und filtert die Registry:
  `GET /api/tools?kind=jig&fits=R5M1&status=active`.

## API (Skizze)

- `GET /api/tools?kind=&fits=<component_type>&status=` — gefilterte Liste fuer
  den Quick-Select.
- `GET /api/tools/by-rfid/{rfid}` — Scanner: RFID -> Tool aufloesen.
- `POST/PATCH /api/tools` (operator/admin) — Registry pflegen, flaggen,
  blacklisten (auditiert ueber die Outbox-/Audit-Spur).

Umgesetzt zusaetzlich: `POST /api/sync/tools/{institute}` aktualisiert die
lokale Registry aus bereits gespiegelten PDB-`TOOLS`-Komponenten, ohne die PDB
erneut anzufragen.

## Frontend (Assembly-Wizard)

- Modul scannen -> Wizard kennt den Typ -> **Dropdowns sind auf kompatible Jigs/
  Tools vorgefiltert** (Quick-Select), statt Freitext.
- Scanner-first: RFID eines Jigs scannen -> Tool wird direkt gesetzt, sofern
  `compatible_types` zum Modul passt (sonst Warnung).
- Glue-Batch analog: aktive Batches per Quick-Select; Klebe-Zielwert kommt aus
  `DEFAULT_MODULE_GLUE_TARGETS`/Profil und wird nur angezeigt/geprueft.
- Ergebnis geht als validierte Aktion in die **Outbox** (nichts direkt in die
  PDB).

## Rule-#4-Check

- Modultyp->Jig-Kompatibilitaet, Zielwerte, Namensschemata: alles Registry/
  Profil, kein Institut-/Typ-Hardcoding im Code.

## Offene Fragen

- Welche Attachment-Properties je Komponententyp kommen aus dem **PDB-Schema**
  (gespiegelt) vs. rein lokaler Registry?
- RFID-Format/Mapping (vgl. zFlow `toolConverter`).
- Blacklist-/Flag-Workflow: rein lokal oder mit PDB-Property gekoppelt?
- Wie viel „Auto-Vorbelegung" (einziges kompatibles Jig automatisch waehlen) vs.
  bewusste Bestaetigung?

## Roadmap-Einordnung

Gehoert zu **Phase 3** (Assembly-Wizards mit Attachment-Properties,
Stage-Vorschlaege) und **Phase 4** (Tool-/Jig-Registry inkl. RFID-Mapping).
Baut auf der bestehenden Domain-Schicht (`glue.py`, `stages.py`) und der Outbox
auf. Siehe `docs/04-roadmap.md`.

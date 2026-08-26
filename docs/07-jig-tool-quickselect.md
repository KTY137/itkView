# Plan: Jig-/Tool-Registry und typ-gefilterter Quick-Select

> Planungsdokument mit Umsetzungsstand. Legt fest, wie Attachment-Properties
> (Jigs, Pickup-Tools, Glue-Batches) im Assembly-Wizard **abhaengig vom
> Modultyp per Quick-Select** ausgewaehlt werden statt per Handeingabe.
>
> Stand 2026-08-26: Vollstaendig umgesetzt. Die lokale `Tool`-Registry besitzt
> auditiertes strukturiertes Create/Edit/Delete und explizite
> `active|flagged|blacklisted`-Pflege; der Tools-Screen bietet Scanner,
> Filter, Mirror-Sync und alle Registry-Aktionen. Der scanner-first
> Assembly-Wizard bindet typgefilterte aktive Tools und benutzbare
> Glue-Batches ein, zeigt den kanonischen Server-Dry-Run und staged danach
> ausschliesslich eine `assemble_component`-Outbox-Aktion.
>
> Stand 2026-07-10: **Pflicht-Property-Pruefung beim Upload** umgesetzt —
> `InstituteProfile.settings['required_properties']` = `{test_type: [key, …]}`
> (z. B. `{"GLUE_WEIGHT": ["JIG"]}`); der Ingest-Dry-Run (`preview` +
> `propose-outbox`) blockt, wenn eine Pflicht-Property (z. B. das benutzte Jig)
> in `payload['properties']` fehlt. Institutskonfiguriert (Regel #4), Default leer,
> setzbar per `PATCH /api/institutes/{code}` (admin).

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

## API (umgesetzt)

- `GET /api/tools?kind=&fits=<component_type>&status=` — gefilterte Liste fuer
  den Quick-Select.
- `GET /api/tools/by-rfid/{rfid}` — Scanner: RFID -> Tool aufloesen.
- `POST /api/tools`, `PATCH /api/tools/{id}` (operator/admin) — alle
  strukturierten Felder pflegen, optionale Werte explizit leeren, Status setzen;
  normalisiert, institutsgebunden, mit eindeutigen Codes/RFIDs und Audit-Events.
- `DELETE /api/tools/{id}` (admin) — Registry-Eintrag entfernen; die Loeschung
  bleibt als `tool.deleted` nachvollziehbar.
- `GET /api/assembly/scan-component`, `POST /api/assembly/preview` und
  `POST /api/assembly/actions` bilden den kanonischen Wizard-Vertrag.

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

Der Worker wiederholt unmittelbar vor einem Submit die Komponenten-,
Instituts-, Location-, Tool-, Kompatibilitaets-, Glue-Status-, Ablauf- und
Topfzeit-Pruefung und vergleicht den aktuellen Zustand mit dem Dry-run-Snapshot.
Der reale Submitter prueft **vor Client-Aufbau** beide Teilnehmer erneut:
nur itkFlow-registrierte DUMMY-Komponenten der sicheren Schnittmenge
`MODULE|HYBRID` sind zulaessig; Sensoren und ASICs sind invariant gesperrt.
Die aus Tool, Glue und Slot abgeleiteten PDB-Property-Keys kommen aus
`InstituteProfile.settings['assembly_property_keys']`, nie aus
institutsspezifischem Anwendungscode.

## Rule-#4-Check

- Modultyp->Jig-Kompatibilitaet, Zielwerte, Namensschemata: alles Registry/
  Profil, kein Institut-/Typ-Hardcoding im Code.

## Kombinierte Tool-Slots (2026-08-26)

`InstituteProfile.settings['assembly_tool_slots']` benennt neben dem
Default-Tool („Module jig used") weitere kombiniert genutzte Tool-Rollen —
exakt die zFlow-Sheet-Spalten „Hybrid glue jigs used, top, bottom" und
„Hybrid pickups used, top, bottom". Jeder Slot: `key`, `label` (Institutsdaten,
unuebersetzt), optional `kinds` (Filter auf `Tool.kind`), `multiple`
(1 oder 1-4 Tools) und `property_key` (eigener PDB-Property-Code; der
Default-Slot nutzt weiter `assembly_property_keys['tool']`).

- Domaene (`app/assembly.py`): `evaluate_assembly`/`canonical_action_payload`/
  `revalidate_assembly_action` akzeptieren `tools: {slot_key: [tool_id,...]}`
  neben dem bisherigen `tool_id`; mehrere/duplizierte Tools werden
  komma-separiert in die PDB-Property geschrieben (`", ".join(codes)`, z. B.
  `JIG_HYBRID_ALIGNMENT = "4, 4"` — das Format der zeuthenflow-Referenz).
  Alt-Aktionen ohne `tools`-Key revalidieren bitgenau wie vorher.
- HTTP: `AssemblyDraftIn` fuehrt `tools` optional; `tool_id` ist nur noch
  Pflicht, wenn kein Slot es ersetzt. `AssemblyPreviewOut.tools` liefert die
  aufgeloesten Tools je Slot. `preview.py` behandelt reine Slot-Aktionen ohne
  Default-Tool korrekt.
- Wizard: liest das Setting, rendert je Slot Quick-Select (typ- und
  `kinds`-gefiltert) plus entfernbare Chips; der gemeinsame Scan ordnet dem
  zuletzt aktiven Slot zu. Ohne Setting bleibt alles beim alten Verhalten
  (ein Tool, Legacy-`tool_id`).
- Offen: strukturierter Editor fuer `assembly_tool_slots` im
  AdminSettingsScreen (bis dahin via `PATCH /api/institutes/{code}`).

## Verbleibende Domaenenklaerungen

- Welche Attachment-Properties je Komponententyp kommen aus dem **PDB-Schema**
  (gespiegelt) vs. rein lokaler Registry?
- RFID-Format/Mapping (vgl. zFlow `toolConverter`).
- Ob Blacklist-/Flag-Zustaende spaeter mit einer PDB-Property gekoppelt werden,
  bleibt eine separate Produktentscheidung; aktuell sind sie bewusst lokal.
- Die exakten instituts-/typspezifischen PDB-Property-Codes muessen vor Nutzung
  je Profil bestaetigt werden. Ohne Mapping sendet der Wizard keine erfundenen
  Property-Keys.

## Offline-Verifikation

`backend/tests/test_tools.py` und `backend/tests/test_assembly.py` pruefen CRUD,
Audit, Eindeutigkeit, Dry-run, Snapshot-Revalidierung, Tool-/Glue-Gates und den
Submitter mit Fakes. `AssemblyWizardScreen.test.tsx` und
`ToolsScreen.test.tsx` pruefen den scanner-first UI-Pfad und strukturierte
Registry-Aktionen. Kein Test ruft die Live-PDB auf.

## Roadmap-Einordnung

Gehoert zu **Phase 3** (Assembly-Wizards mit Attachment-Properties,
Stage-Vorschlaege) und **Phase 4** (Tool-/Jig-Registry inkl. RFID-Mapping).
Baut auf der bestehenden Domain-Schicht (`glue.py`, `stages.py`) und der Outbox
auf. Siehe `docs/04-roadmap.md`.

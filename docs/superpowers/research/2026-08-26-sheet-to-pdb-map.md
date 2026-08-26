# Sheet → PDB: Zeile-für-Zeile-Abgleich gegen den echten Spiegel (2026-08-26)

**Zweck.** `docs/superpowers/research/2026-08-26-zflow-sheet-transcription.md` ist die
wörtliche Abschrift der Owner-Sheets. Dieses Dokument beantwortet für **jede** dort
transkribierte Zeile: Gibt es dafür eine PDB-Heimat, in welcher Form, und wie oft ist sie
bei TUDO tatsächlich befüllt?

**Methode.** Ausschließlich Read-only-Abfragen gegen die lokal gespiegelten Daten. Kein
PDB-Kontakt, kein Gateway, keine Ausführung von `references/zeuthenflow` (nur Read/Grep).

| Quelle | Pfad | Umfang |
|---|---|---|
| Großer Spiegel (maßgeblich) | `C:\Users\nukei\AppData\Local\itkflow\itkflow.db`, geöffnet als `file:...?mode=ro&immutable=1` | 3 046 Komponenten, **14 759 Testläufe**, 3 772 Attachments, 8 657 Stage-Events, 14 Testtyp-Schemata, 121 Shipments |
| Dev-Kopie (Gegenprobe) | Kopie von `backend/itkflow_tudo.db` im Scratch-Verzeichnis | 3 153 Komponenten, nur **713 Testläufe** — für Messwertfragen zu dünn, deshalb nur zur Struktur-Gegenprobe verwendet |

Stand des Spiegels: Komponenten `synced_at = 2026-08-26 21:37`, Evidence
`synced_at` zwischen 2026-08-26 10:08 und 16:16. Alle 14 759 Evidence-Zeilen haben
`source='pdb'`.

**Personenbezug.** In den Payloads stehen reale `OPERATOR`/`USER`-Werte. Sie werden hier
konsequent anonymisiert (Schema `Anna Abel`), nie im Original zitiert.

**Roadmap-Bezug.** Reine Recherche, kein Produktivcode geändert. Die Ergebnisse speisen
den Modul-Worksheet-Ausbau (docs/04 „Modul-Worksheet als Primäransicht", Spec §H) und
berühren `docs/07-jig-tool-quickselect.md` (Befund J1 unten) sowie
`docs/11-logistics-operations.md` (Glue-Batch-Verknüpfung).

---

## 0 — Headline

| Kategorie | Zeilen | Anteil |
|---|---:|---:|
| **A — PDB-Heimat vorhanden und bei TUDO befüllt** | 39 | 53 % |
| **B — PDB-Feld existiert, bei TUDO leer oder fast leer** | 14 | 19 % |
| **C — Objekt existiert in der PDB, aber die Verknüpfung zum Modul fehlt** | 8 | 11 % |
| **D — gar kein PDB-Feld → muss lokal in itkFlow leben** | 12 | 16 % |
| **E — in der PDB vorhanden, aber von unserem Mirror nicht übernommen** | 1 | 1 % |
| **Summe** | **74** | |

74 = 60 Zeilen des TUDO-Blattes + 14 Zeilen, die nur im DESYZ-Blatt vorkommen.
Mehrfach vorkommende Zeilen (`Visual Inspection Photo` in drei Bändern, `Glued by - Name`
in zwei Bändern) sind als separate Zellen gezählt, weil sie im Sheet separate Zellen sind.

**Für den Plan zentral:** 20 Zeilen (C + D) brauchen lokalen Speicher in itkFlow. Darunter
fällt der **komplette Werkzeug- und Klebstoff-Nachweis** (Jigs, Pickups, Glue Sample) und
die **komplette Urteilslogik** (Zielgewicht, Toleranz, `OK`/`zu viel`/`zu wenig`).

---

## 1 — Die Einheitenfrage bei den Klebegewichten (präzise)

### 1.1 Vollständiges Result-Code-Inventar von `GLUE_WEIGHT`

Der Testtyp hat **19** Result-Codes. Alle 19 sind im gespiegelten Schema
(`test_type_schema`, `component_type=MODULE`, `test_code=GLUE_WEIGHT`) mit
`dataType: float`, `valueType: single` definiert, und **jeder Name endet auf `[g]`**.

Quelle: **Q2** (`gw.py`, Scan aller 134 `GLUE_WEIGHT`-Payloads) und **Q6** (Schema-Dump).

| Result-Code | Bedeutung (Schema-Name, Einheit wie deklariert) | Art | Läufe befüllt (alle 134) | davon live (`state=ready`, 116) | Wertebereich [g] |
|---|---|---|---:|---:|---|
| `GW_SENSOR` | Weight of sensor **[g]** | **roh** | 62 | 45 | 5,606 … 7,0207 |
| `GW_HYBRID1` | Weight of hybrid 1 (without tabs) **[g]** | **roh** | 58 | 42 | 0,158 … 3,211 |
| `GW_HYBRID1T` | Weight of hybrid 1 (with tabs) **[g]** | **roh** | 10 | 3 | 1,75 … 1,859 |
| `GW_T1` | Weight of hybrid 1 tabs **[g]** | **roh** | **0** | 0 | — |
| `GW_HYBRID2` | Weight of hybrid 2 (without tabs) **[g]** | **roh** | **0** | 0 | — |
| `GW_HYBRID2T` | Weight of hybrid 2 (with tabs) **[g]** | **roh** | **0** | 0 | — |
| `GW_T2` | Weight of hybrid 2 tabs **[g]** | **roh** | **0** | 0 | — |
| `GW_PB` | Weight of powerboard **[g]** | **roh** | 30 | 29 | 1,95 … 3,409 |
| `GW_MODULE_H1` | Weight of module with only 1 hybrid **[g]** | **roh** | 62 | 53 | 0,144 … 10,0845 |
| `GW_MODULE_H1H2` | Weight of module with hybrid 1 and 2 **[g]** | **roh** | **0** | 0 | — |
| `GW_MODULE_PB` | Weight of module with only a powerboard **[g]** | **roh** | 9 | 8 | 7,768 … 10,166 |
| `GW_MODULE_H1PB` | Weight of module with 1 hybrid and powerboard **[g]** | **roh** | 78 | 77 | 9,8282 … 12,872 |
| `GW_MODULE_H1H2PB` | Weight of module with hybrid 1, 2 and powerboard **[g]** | **roh** | **0** | 0 | — |
| `GW_GLUE_H1` | Weight of glue under hybrid 1 **[g]** | **abgeleitet** | 60 | 43 | 0,102 … 195 |
| `GW_GLUE_H2` | Weight of glue under hybrid 2 **[g]** | **abgeleitet** | **0** | 0 | — |
| `GW_GLUE_H1H2` | Weight of glue under hybrids 1 and 2 combined **[g]** | **abgeleitet** | **0** | 0 | — |
| `GW_GLUE_PB` | Weight of glue under powerboard **[g]** | **abgeleitet** | 32 | 31 | 0,054 … 2,197 |
| `GW_GLUE_H1PB` | Weight of glue under hybrid 1 and powerboard combined **[g]** | **abgeleitet** | 16 | 15 | 0,192 … 0,25 |
| `GW_GLUE_H1H2PB` | Weight of glue under hybrid 1, 2 and powerboard combined **[g]** | **abgeleitet** | **0** | 0 | — |

**Roh vs. abgeleitet:** Die sechs `GW_GLUE_*`-Codes sind die abgeleiteten Klebegewichte;
die übrigen 13 sind Waagenablesungen. Die zwölf Codes mit 0 Befüllung existieren im
Schema und sind bei TUDO schlicht nie geschrieben worden — das ist **„Feld existiert und
ist leer"**, nicht „Feld existiert nicht". Konkreter Grund für sechs davon: TUDO baut
R5-Halbmodule und R2 mit genau **einem** Hybrid, also bleibt die gesamte `H2`-Familie
(`GW_HYBRID2`, `GW_HYBRID2T`, `GW_T2`, `GW_GLUE_H2`, `GW_MODULE_H1H2`,
`GW_GLUE_H1H2`, `GW_MODULE_H1H2PB`, `GW_GLUE_H1H2PB`) systematisch leer. `GW_T1`
(Ohren/Tabs) ist dagegen einfach nicht gemessen worden — im Sheet sind die drei
Ohren-Zeilen ebenfalls leer.

### 1.2 Die Einheit ist eindeutig Gramm — im Sheet Milligramm

Es gibt **keine Einheiten-Uneinheitlichkeit im Schema**: alle 19 Codes sind `[g]`.
Die 1000er-Diskrepanz entsteht an der Sheet-Grenze, nicht in der PDB.

**Beweis 1 — Wertabgleich (Q10, `sheetmatch.py`).** Alle in der Transkription
notierten Beispielwerte wurden gegen die Menge der im Spiegel vorhandenen Werte geprüft:

| Sheet-Zeile | Result-Code | Faktor | Treffer |
|---|---|---|---|
| `Sensor weight with tab (g)` | `GW_SENSOR` | ×1 | **7/7** |
| `top Hybrid weight without ears (g)` | `GW_HYBRID1` | ×1 | **7/7** |
| `Module weight after gluing all hybrids (g)` | `GW_MODULE_H1` | ×1 | **7/7** |
| `Powerboard weight (g)` | `GW_PB` | ×1 | **4/4** |
| `Module weight after gluing powerboard AND hybrid` | `GW_MODULE_H1PB` | ×1 | **4/4** |
| `all Hybrid glue weight (mg)` | `GW_GLUE_H1` | **÷1000** | **7/7** |
| `Powerboard glue weight (...mg)` | `GW_GLUE_PB` | **÷1000** | **4/4** |

40 von 40 transkribierten Werten liegen exakt im Spiegel — die Gramm-Zeilen 1:1, die
mg-Zeilen exakt bei ×1000. Damit ist die Beziehung bewiesen und nicht geraten.

**Beweis 2 — die Referenzimplementierung (nur gelesen).**
`references/zeuthenflow/modules/processGoogleDoc.py:2053` und `:2090`:

```
weightHybridsInGramm = weightGlueHybrids * 1e-3 …
weightGluePowerboardInGramm = weightGluePowerboard * 1e-3
```

zFlow liest die Sheet-Zellen in **mg** und multipliziert vor dem Upload mit `1e-3`. Die
Rohgewichte (`GW_SENSOR`, `GW_HYBRID1`, `GW_PB`, `GW_MODULE_*`) gehen unkonvertiert
durch, weil sie im Sheet schon Gramm sind. Dasselbe Muster bei `GW_GLUE_ASICS` (`:1036`).

**Konsequenz für die UI:** itkFlow muss beim Anzeigen und beim Erfassen **explizit**
zwischen Anzeigeeinheit (mg, wie das Team denkt) und Speichereinheit (g, wie die PDB
verlangt) trennen. Ein ungeprüftes Durchreichen erzeugt genau den Fehler, der schon
einmal passiert ist (siehe 1.3).

### 1.3 Wie viele Läufe sind über ALLE GW-Codes hinweg inkonsistent?

Methode (**Q9**, `units.py`): pro Result-Code ein physikalisch plausibles Band in Gramm
(z. B. Modulgewicht 5–20 g, Klebegewicht 0,02–0,5 g nach den Sheet-Zielen 70–311 mg),
dann jede befüllte Zelle dagegen geprüft. Zusätzlich Prüfung auf identische Zahlen in
mehreren Result-Codes desselben Laufs.

**Wichtige Vorbedingung:** 18 der 134 `GLUE_WEIGHT`-Läufe haben in der PDB
`state='deleted'` (**Q14**). Sie sind fachlich zurückgezogen. Beide Zahlen sind unten
angegeben, weil die Detailseite gelöschte Läufe ohnehin ausfiltern muss.

| Betrachtung | Läufe | befüllte Zahlzellen | Zellen außerhalb des Bands | betroffene Läufe |
|---|---:|---:|---:|---:|
| alle Läufe | 134 | 417 | **27 (6,5 %)** | **17 (12,7 %)** |
| nur `state=ready` | 116 | 346 | **11 (3,2 %)** | **9 (7,8 %)** |

**Aufschlüsselung der 27 Ausreißer nach Ursache:**

| Ursache | Zellen | Erläuterung |
|---|---:|---|
| **echter ×1000-Einheitenfehler** | **1** | `GW_GLUE_H1 = 195` auf `20USEM20000056`, 2023-09-07. 195 g Kleber ist unmöglich; 195 mg passt zum R2-Ziel 164±25 mg. Der einzige saubere Einheitenfehler im ganzen Spiegel. Der Lauf ist `state=ready`, also live. |
| **Feldvertauschung** (Wert steht im falschen Code) | 20 | 10× `GW_MODULE_H1 = 0,144` (das ist das Klebegewicht, nicht das Modulgewicht), 9× `GW_GLUE_H1 = 1,859` (das ist das Hybridgewicht), 1× `GW_HYBRID1 = 0,158`. |
| **unplausibel, aber kein sauberer Faktor** | 6 | `GW_GLUE_PB` = 0,56 / 0,59 / 0,59 / 0,8 / 2,197 und `GW_GLUE_H1` = 0,724. 5–20× über dem PB-Ziel von 70–103 mg. |

**Feldvertauschung ist quantifizierbar (Q9):** In **20** Läufen steht dieselbe Zahl in
mehr als einem Result-Code:

| Code-Paar mit identischem Wert | Läufe |
|---|---:|
| `GW_HYBRID1` == `GW_HYBRID1T` | 10 |
| `GW_GLUE_H1` == `GW_HYBRID1` | 9 |
| `GW_GLUE_PB` == `GW_PB` | 1 |

**Der 1,859-Block ist zu 93 % bereits gelöscht.** Die 15 Läufe vom 2024-11-12 08:20–08:23
liegen alle auf **einer** Seriennummer (`20USE5L0000031`) innerhalb von drei Minuten —
offensichtlich ein Skript-Testlauf. **14 davon haben `state='deleted'`**, nur einer ist
noch live. Wer gelöschte Läufe filtert, sieht von diesem Artefakt genau eine Zelle.

**Die neun verbleibenden auffälligen Live-Läufe** (Q9, vollständig):

| SN | Datum | auffällige Zelle(n) | Einordnung |
|---|---|---|---|
| `20USEM20000057` | 2023-09-07 | `GW_HYBRID1=0,158`, `GW_GLUE_PB=0,59` | Klebegewicht im Hybridfeld |
| `20USEM20000057` | 2023-09-07 | `GW_GLUE_PB=0,59` | zu hoch |
| `20USEM20000056` | 2023-09-07 | `GW_GLUE_H1=195` | **×1000-Einheitenfehler** |
| `20USE5L0000031` | 2024-11-12 | `GW_GLUE_H1=1,859`, `GW_MODULE_H1=0,144` | Feldvertauschung (Rest des Blocks gelöscht) |
| `20USEM20000104` | 2025-04-10 | `GW_GLUE_PB=2,197` | identisch mit `GW_PB` im selben Lauf |
| `20USEM20000186` | 2026-01-21 | `GW_GLUE_PB=0,56` | zu hoch |
| `20USE5R0000143` | 2026-01-21 | `GW_GLUE_PB=0,8` | zu hoch |
| `20USE5L0000751` | 2026-02-13 | `GW_GLUE_H1=0,724` | zu hoch |
| `20USE5L0000767` | 2026-04-02 | `GW_MODULE_H1=2` | zu leicht für ein Modul |

**Antwort auf die Ausgangsbeobachtung des Owners:** `GW_GLUE_H1` ist in 60 Läufen
befüllt; 59 Werte liegen unter 2, einer ist 195. Von den 59 sind 49 physikalisch
plausibel, 9 sind der gelöschte 1,859-Block und einer ist 0,724. Es gibt also **genau
einen** echten Faktor-1000-Fall, nicht ein Einheiten-Chaos. Über alle 19 GW-Codes hinweg
sind es 11 auffällige Zellen in 9 von 116 lebenden Läufen.

### 1.4 `GW_METHOD` und `GLUE_METHOD_V_H1/H2/PB` — nicht das Klebeverfahren

`GLUE_WEIGHT` hat im Schema (Q6) genau **vier** Properties:

| Property | Schema-Name / Beschreibung | required | befüllt (134 Läufe) |
|---|---|---|---:|
| `GW_METHOD` | „Glue application method", Beschreibung wörtlich: `"stencil" or "dispenser"` | **ja** | 134 |
| `GLUE_METHOD_V_H1` | „Version number of stencil or dispenser programme used for Hybrid 1" | nein | **1** |
| `GLUE_METHOD_V_H2` | dito Hybrid 2 | nein | **1** |
| `GLUE_METHOD_V_PB` | dito Powerboard | nein | **1** |

Werte von `GW_METHOD` bei TUDO (Q4): `'Stencil'` ×91, `'stencil'` ×35, `'stencils'` ×5,
`'Stencils'` ×2, `'stensil'` ×1 — **fünf Schreibvarianten desselben Wortes**, freier
String ohne Enum. Die drei `GLUE_METHOD_V_*` sind in 133 von 134 Läufen `null`; ein
einziger Lauf trägt `'001'`/`'001'`/`'002'`.

**Antwort auf die Frage:** **Nein.** Keines dieser vier Felder bildet die beiden
Klebeverfahren des Sheets ab.

* `GW_METHOD` ist die **Auftragsmethode** (Schablone vs. Dispenser), nicht das
  Klebstoffprodukt. Zur Gegenprobe: zFlow schreibt bei DESYZ hart
  `"GW_METHOD": "dispenser"` und `"GLUE_METHOD_V_*": "-"`
  (`processGoogleDoc.py:2066-2069`), TUDO schreibt „Stencil".
* `GLUE_METHOD_V_*` ist die **Programmversion** der Schablone bzw. des Dispensers. Das
  ist inhaltlich der Anknüpfungspunkt für die Sheet-Tabelle „Klebemengenkorrektur für
  Klebeprogramme" (Line-Speed-Rückkopplung) — aber es ist bei TUDO praktisch ungenutzt.
* Die Zeichenketten `POLARIS`, `TRUE_BLUE`, `TrueBlue` oder `FalseBlue` kommen im
  gesamten zFlow-Modulcode **nicht vor** (Grep über `references/zeuthenflow/modules`).
  Das Verfahren wurde also auch von zFlow nie an die PDB übermittelt.

**Wo das Verfahren doch in der PDB steht — aber unverknüpft (Q5):** Es gibt echte
`GLUE`-Komponenten bei TUDO, und ihr `type_code` **ist** das Verfahren:

| `type_code` | Anzahl | Beispiel-Stages |
|---|---:|---|
| `TRUE_BLUE` | 10 | `NEW`, `IN_USE`, `EMPTY`, `EXPIRED` |
| `POLARIS_EPOXY` | 2 | `EXPIRED` |
| `POLARIS_HARDENER` | 2 | `EXPIRED` |
| `LOCTITE_3525` | 1 | `EXPIRED` |

Die im Sheet genannte `Hybrid glue sample`-SN `20USEGT0000089` ist eine dieser
Komponenten (`GLUE / TRUE_BLUE / EMPTY / TUDO`). **Aber:** ein Regex-Scan über **alle
14 759 Payloads** (Q15) nach `20USEG*`, `20USERT*` und `20USEV*` liefert **null Treffer**,
und `GLUE` taucht in keiner Parent-/Child-Beziehung auf (Q5). Die Verknüpfung
Modul ↔ verwendeter Klebstoff existiert in der PDB nicht. Damit ist das Verfahren
**pro Modul nicht aus der PDB ableitbar**, obwohl die Klebstoffdose dort registriert ist.

### 1.5 Zielgewicht, Toleranz und Urteil haben keine PDB-Heimat

Q6 über alle 14 gespiegelten Modul-Testtyp-Schemata:

* `automaticGrading = false` bei **allen 14**.
* `thresholds` (`min`/`max`/`nominal`) sind bei **allen** Parametern `null` — mit genau
  einer Ausnahme: `MODULE_IV_AMAC.VBD`.

Die PDB rechnet also **nichts** und urteilt **nichts**. `passed` ist das, was der
Hochladende behauptet hat.

**Wie weit trägt `passed` als Ersatz für `Adhesive weight result`? (Q12)** Für die 60
Läufe mit `GW_GLUE_H1` und einem Modultyp aus der TrueBlue-Zieltabelle wurde das
Sheet-Urteil nachgerechnet (`|mg − Ziel| ≤ Toleranz`) und mit `passed` verglichen:

| | Sheet sagt OK | Sheet sagt außer Toleranz |
|---|---:|---:|
| `passed = true` | 22 | **4** |
| `passed = false` | **8** | 26 |

**Übereinstimmung 48/60 = 80 %.** In 12 Läufen widerspricht das PDB-Flag der
Sheet-Rechnung. Zudem ist `passed` ein Flag für den **ganzen** Lauf — das Sheet fällt
**zwei** getrennte Urteile (Hybrid und Powerboard), die sich aus einem Bit nicht
rekonstruieren lassen. `problems` hilft nicht: bei `MODULE_METROLOGY` haben 84 Läufe
`passed=false` **und** `problems=false` (Q14), die Felder sind unabhängig.

**Fazit:** Zieltabellen, Toleranzen und die Ampel `OK`/`zu viel`/`zu wenig` müssen in
itkFlow aus dem Institutsprofil gerechnet werden (Regel 4: keine Formel im Code). Das
PDB-`passed` ist ein zusätzliches Signal, keine Quelle der Wahrheit.

---

## 2 — Jig-, Pickup- und Werkzeugzeilen

### Befund J1 (wichtig, korrigiert eine Annahme)

`GLUE_WEIGHT` hat **keine** Werkzeug-Property. Die vier Properties sind vollständig in
1.4 aufgelistet: `GW_METHOD` und drei `GLUE_METHOD_V_*`. Es gibt dort kein `JIG`, kein
`TOOL`, kein `PICKUP`, kein `OPERATOR`.

Der Scan aller 14 759 Payloads (Q15) findet **keine einzige** `20USERT…`-Seriennummer,
in keinem Result und in keiner Property, bei keinem Testtyp.

### Was itkFlow heute tatsächlich tut

`backend/app/assembly.py:475-514` (`_pdb_properties`) baut komma-verbundene Tool-Codes,
aber diese landen laut `backend/app/pdb_submit.py:298-311` im **Assembly-Aufruf**:

```
"children": [{"sn": child_sn, "properties": properties}]
```

Das sind **Properties der Montage-Beziehung**, nicht eines Testlaufs. Drei Einschränkungen:

1. **Unkonfiguriert wirkungslos.** `_profile_property_keys` liest
   `assembly_property_keys` aus dem Institutsprofil und gibt `{}` zurück, wenn nichts
   konfiguriert ist. Das TUDO-Profil im Spiegel hat `settings = {}` (Q17) — also **leer**.
   Es wird derzeit keine einzige Werkzeug-Property geschrieben.
2. **Nicht rücklesbar.** `pdb_sync.map_pdb_component` (`backend/app/pdb_sync.py:157-190`)
   übernimmt aus dem PDB-Payload nur `serialNumber`, `componentType`, `type`,
   `currentStage`, `currentLocation`, `institution`, `alternativeIdentifier`, die
   Parent-Objekt-Id, `trashed` und die Stage-Historie. **Komponenten-Properties und
   Assembly-Beziehungs-Properties werden nicht gespiegelt.** Selbst geschriebene
   Jig-Codes wären für die Detailseite unsichtbar.
3. **Der Schreibpfad ist ohnehin `dummy_only`.** Für reale Produktionsmodule schreibt
   itkFlow bewusst nicht.

### Was in der PDB sehr wohl existiert

92 `TOOLS`-Komponenten bei TUDO, alle mit sprechendem `local_name`, alle in der lokalen
`tool`-Registry (Überlappung 92/92, Q5/Q18). **Alle sieben** in der Transkription
genannten Dropdown-SNs lösen exakt auf:

| Sheet-Zeile | Sheet-Wert | PDB-`local_name` |
|---|---|---|
| `Hybrid glue jigs used, top, bottom` | `20USERT0510405` | `R5H1S_hybrid_jig_05` |
| | `20USERT0510211` | `R5H1S_Pickup_11` |
| `Hybrid pickups used, top, bottom` | `20USERT0510110` | `R5H0S_Pickup_10` |
| | `20USERT0510310` | `R5H0S_hybrid_jig_10` |
| `Module jig used` | `20USERT0510711` | `R5S0_Module_Jig_11` |
| `Powerboard glue jig, pickup tool` | `20USERT0274006` | `R2PBS_R2_Powerboard_Jig_01-006` |
| | `20USERT0284004` | `R2PBS_Pickup_01-004` |

Auch `R5_HV_tab_jig_04` / `_10` existieren — die Zeile `HV tab jig` referenziert also
reale Werkzeuge.

**Die einzige Jig-Property im gesamten Modul-Schemaraum** ist `MODULE_BOW.JIG` (required,
`string`), befüllt in 28/28 Läufen, aber als Freitext: `'Module Assembly Jig'` ×13,
`'Module Metrology Jig'` ×8, `'1'` ×6, `'Module assembly jig'` ×1 — keine
Seriennummern, keine kanonische Form.

### Ergebnis

Alle vier Werkzeugzeilen des Sheets sind **Kategorie C**: Das Werkzeug ist eine echte,
gespiegelte PDB-Komponente, aber die **Verwendungsbeziehung Modul ↔ Werkzeug ↔
Arbeitsschritt** existiert in der PDB nicht und ist im Mirror nicht rücklesbar. itkFlow
muss diese Zuordnung lokal führen (die `tool`-Registry ist dafür bereits da, die
Verwendungs-Tabelle fehlt). Die Nebenbemerkung im Sheet-Transkript, dass DESYZ hier
Farbnamen (`orange`, `white`) statt SNs einträgt, unterstreicht das: das Feld ist
institutslokal, nicht PDB-normiert.

---

## 3 — Metrologie und Bow

| | `MODULE_METROLOGY` | `MODULE_BOW` |
|---|---|---|
| Läufe im Spiegel (Q1) | **105** | **28** |
| davon `state='deleted'` (Q14) | 2 | 7 |
| `passed = true` / `false` | **20 / 85** | 18 / 10 |
| Module mit ≥1 Lauf, von 231 (Q8) | **94 (41 %)** | **19 (8 %)** |
| Module mit ≥1 bestandenem Lauf | **19** | 16 |
| Zeitraum | 2023-09-25 … 2026-08-26 | 2023-12-06 … 2026-03-19 |
| Attachments (Q7) | 105 Dateien / 94 SNs | 28 Dateien / 19 SNs |

**Result-Codes `MODULE_METROLOGY` (Q, `res.py`)** — alle Einheiten `[um]`, fünf der sechs
sind **Maps** (Objekte), nicht Skalare:

| Code | Schema-Name | Typ | befüllt |
|---|---|---|---:|
| `CAP_HEIGHT` | Capacitor heights [um] | map (0–8 Einträge) | 105 |
| `HYBRID_GLUE_THICKNESS` | Hybrid glue thickness [um] | map (12–17), Schlüssel z. B. `ABC_R5H1_0` | 105 |
| `HYBRID_POSITION` | Hybrid position Deviation [um] | map (2), Werte sind Paare `[dx, dy]`, Schlüssel `H_R5H1_P1` | 105 |
| `PB_GLUE_THICKNESS` | Powerboard glue thickness [um] | map (0–5) | 105 |
| `PB_POSITION` | PB position Deviation [um] | map (0–2) | 105 |
| `SHIELDBOX_HEIGHT` | Shield box height [um] | float | 75 |

**Result-Codes `MODULE_BOW`:** `BOW` [um] (float, 28/28) und `TEMPERATURE` [C]
(float, 28/28).

**Woraus kommt das Urteil?** Aus `test_run_evidence.passed`, das
`backend/app/pdb_test_evidence.py:77-84` direkt aus dem PDB-Feld `passed` übernimmt
(Fallback `not problems`). Da `automaticGrading=false` und alle Thresholds `null` sind
(1.5), ist das ein vom Hochladenden gesetztes Bit. Bei `MODULE_METROLOGY` haben 84 Läufe
`passed=false` bei `problems=false` — die hohe Fehlerquote ist also eine echte
Bewertung, kein Datenartefakt.

**Zuordnung zu den Sheet-Zuständen:**

| Sheet-Zustand | Ableitung aus dem Spiegel | Häufigkeit (231 Module) |
|---|---|---|
| `Metrology_PASSED` (grün) | jüngster `MODULE_METROLOGY`-Lauf mit `passed=1` | 19 Module |
| `Metrology_FAILED` (rot) | jüngster Lauf mit `passed=0` | 75 Module |
| `Messung fehlt!` (orange) | **kein** `MODULE_METROLOGY`-Lauf vorhanden | **137 Module** |
| `Metrology date` | `measured_at` des Laufs | — |
| `Metrology results uploaded to DB?` | Existenz des Laufs (identisch zur Zeile darüber) | — |
| `Bow Metrology` / `Bow Metrology Date` | `MODULE_BOW.BOW` bzw. `measured_at` | 19 Module, 212 × `Messung fehlt!` |

**Achtung für die Detailseite:** Die Sheet-Zeile „Metrology outcome" und „Metrology
results uploaded to DB?" sind im PDB-Modell **dieselbe** Information (Existenz + `passed`
eines Laufs). Im Sheet sind sie getrennt, weil dort das lokale Messergebnis und der
Upload-Status auseinanderfallen konnten — in itkFlow fallen sie zusammen, sobald der
staged-first Pfad genutzt wird (staged = noch nicht hochgeladen, confirmed = hochgeladen).

**Kein Metrologie-Bild.** Die 105 `MODULE_METROLOGY`-Attachments sind ausnahmslos
`content_type='text/plain'` mit `title='resultsFile'` und Dateinamen wie `R5M1.txt`,
`20USE5L0000704_met.txt` (Q7). Dasselbe bei `MODULE_BOW` (28× `text/plain`,
`R5M1_bowmeasure_….txt`). **Metrologie-Bilder existieren im TUDO-Spiegel nicht** — die
Anlage ist die Keyence-Rohdatei, nicht ein Foto.

---

## 4 — Die IV-Zeilen: welcher Testtyp, und wie unterscheidet man sie programmatisch?

Die entscheidende Erkenntnis: **Der Testtyp allein reicht nicht.** Das
Unterscheidungsmerkmal ist das Paar **(Testtyp, Stage zum Messzeitpunkt)**.

Q11 rekonstruiert für jeden Lauf die Stage, die laut `stage_event`-Historie zum
`measured_at` galt:

| Testtyp | Komponententyp | Läufe | Stage zum Messzeitpunkt |
|---|---|---:|---|
| `ATLAS18_IV_TEST_V1` | **SENSOR** | 1 064 | `SENS_TEST_STAGE` 710, `READY_FOR_MODULE` 332, ohne Historie 18, `UNHAPPY` 4 |
| `MODULE_IV_PS_V1` | MODULE | 219 | **`HV_TAB_ATTACHED` 209**, ohne Historie 7, `FAILED` 2, `GLUED` 1 |
| `MODULE_IV_AMAC` | MODULE | 133 | **`BONDED` 56**, `FAILED` 29, `TESTED` 20, `FINISHED` 16, `ON_CORE` 8, sonst 4 |
| `MODULE_IV_AMAC_TC` | MODULE | 56 | **`TESTED` 39**, `BONDED` 10, `GLUED` 3, sonst 4 |

**Zweiter, unabhängiger Diskriminator: der Attachment-Dateiname.** Q7a zeigt, dass
**218 von 218** `MODULE_IV_PS_V1`-Anlagen den Stage-Token im Namen tragen, z. B.
`20USE5L0000702_HV_TAB_ATTACHED_001.dat`. Bei `MODULE_IV_AMAC` sind es nur 3 von 8.

**Dritter Diskriminator, im Schema vorgesehen, aber ungenutzt:** `MODULE_IV_PS_V1` und
`MODULE_IV_PS_BONDED` haben beide eine Property `MODULE_STAGE`. Bei TUDO ist sie in
**3 von 219** Läufen befüllt (`'HV tab attach'` ×2, `'Glued'` ×1) — also unbrauchbar.

**Bestätigung durch die Referenz (nur gelesen).**
`references/zeuthenflow/tests/expected_output.txt` protokolliert wörtlich
„The test MODULE_IV_PS_V1 has passed for module … **in stage HV_TAB_ATTACHED**",
„The test GLUE_WEIGHT has passed … **in stage GLUED**",
„The test MODULE_IV_AMAC was not performed … **in stage BONDED**". zFlow wertet also
exakt nach dem Paar (Testtyp, Stage) aus — dieselbe Regel, die die Daten empirisch
hergeben.

### Zuordnung der fünf Sheet-Zeilen

| Sheet-Zeile | Mapping | Module mit Nachweis (von 231) |
|---|---|---:|
| `reception IV, in DB?` | `ATLAS18_IV_TEST_V1` **auf der Sensor-Kindkomponente** (nicht auf dem Modul!) | 205 Module haben ein Sensor-Kind; 364 Sensoren tragen den Test |
| `IV after tabbing passed?. in DB?` | `MODULE_IV_PS_V1` **@ `HV_TAB_ATTACHED`** | **191 (83 %)** |
| `IV after bonding` | `MODULE_IV_AMAC` **@ `BONDED`/`TESTED`/`FINISHED`** | **27 (12 %)** |
| `DAQ Quick test` / `UBC Uploader: quick electrical test passed` | Hybrid-Kind, `*_PPA`-Familie | `RESPONSE_CURVE_PPA` über 96 Module erreichbar |
| `DAQ TC test (incl. IV)` / `UBC Uploader: thermal cycling …` | `MODULE_IV_AMAC_TC` **plus** Hybrid-Kind `*_TC`-Familie | 24 bzw. 32 Module |

**Zwei „Feld existiert, ist aber leer"-Fälle mit hohem Planungswert (Q6):**

| Gespiegeltes Schema | Zweck | Läufe im Spiegel |
|---|---|---:|
| `MODULE_IV_PS_BONDED` („Module IV with PS after bonding") | die **dedizierte** PDB-Heimat für „IV after bonding" | **0** |
| `HYBRID_TESTS_SUMMARY` („Hybrid Tests Summary") | Parameter sind `testRun`-**Referenzen** (`H0-RESPONSE_CURVE_3PG`, `H0-NO`, `H1-OPEN_CHANNEL_SEARCH`, …) — die vorgesehene Rollup-Heimat für „DAQ Quick test" auf Modulebene | **0** |
| `MODULE_TC` („Module Thermal Cycling") | Modul-TC mit `ColdJig_History` | **0** |
| `AMAC_IV_TC`, `HVSTABILITY`, `ATLAS18_RECOVERY` | — | **0** |

Das ist die Unterscheidung, die der Plan braucht: „IV after bonding" hat eine offizielle
PDB-Heimat, die TUDO **nicht benutzt** — die Praxis behilft sich mit `MODULE_IV_AMAC`.
Und die Zeile „DAQ Quick test" hätte auf Modulebene eine saubere Heimat
(`HYBRID_TESTS_SUMMARY`), die ebenfalls leer ist; faktisch liegen die Daten auf dem
Hybrid-Kind.

### Elektrik liegt am Hybrid, nicht am Modul

Q11a: Von den 98 `HYBRID_ASSEMBLY`-Komponenten im Spiegel haben **alle 98** ein
MODULE-Elternteil. Die ITSDAQ-Familien sind darüber erreichbar:

| Testtyp (auf `HYBRID_ASSEMBLY`) | Läufe | über … Module erreichbar | `run_number`-Beispiele |
|---|---:|---:|---|
| `RESPONSE_CURVE_PPA` | 990 | 96 | `189-6`, `196-13` |
| `NO_PPA` | 493 | 96 | `189-19`, `1905-18` |
| `OPEN_CHANNEL_SEARCH_PPA` | 68 | 36 | `1401-150`, `2458-22` |
| `RESPONSE_CURVE_BURNIN` | 160 | 57 | `702`, `2085` |
| `RESPONSE_CURVE_TC` | 128 | 32 | `1013`, `871` |
| `NO_TC` | 64 | 32 | `1013`, `1546` |
| `OPEN_CHANNEL_SEARCH_TC` | 62 | 31 | `1013`, `1699` |

Der Payload-Schlüssel `run_number` ist genau die ITSDAQ-Laufnummer, die das Sheet in
`UBC Uploader: quick electrical test passed` als `ITSDAQ run 104: failed` zeigt. Der
Suffix `_PPA` / `_BURNIN` / `_TC` trennt die Testphasen programmatisch.

**Folgerung für die Modul-Detailseite:** Sie muss die Testläufe der **Kindkomponenten**
(Sensor, Hybrid, Powerboard) mit einbeziehen. Sonst bleiben `reception IV`, alle
DAQ-Zeilen und die gesamte Powerboard-Elektrik (`PB_NOISE`, `LV_ENABLE`, `HV_ENABLE`,
`DCDC_ADJUST`, … auf `PWB`) unsichtbar. Das sind 96 % der Testläufe im Spiegel: nur
592 von 14 759 Läufen hängen direkt an einer MODULE-Komponente.

---

## 5 — Chipbestückung der Hybride: ableitbar, sogar besser als das Sheet

Die Frage war: Hybrid-`type_code`, Kindzählung oder Profildatum?

**Antwort: Kindzählung, und sie ist exakt (Q5, `tree.py`).** Der Spiegel enthält die
Chips als Kindkomponenten der Hybridbaugruppe (`HYBRID_ASSEMBLY → ABC` 966 Kanten,
`HYBRID_ASSEMBLY → HCC` 130 Kanten):

| Hybrid-`type_code` | Baugruppen | gezählte (ABC, HCC) | Sheet-Tabelle „Daten" |
|---|---:|---|---|
| `R5H0` | 31 | **(9, 0)** in 31/31 | R5H0 → 9 / 0 ✓ |
| `R5H1` | 31 | **(9, 2)** in 31/31 | R5H1 → 9 / 2 ✓ |
| `R2H0` | 36 | **(12, 2)** in 34/36, `(0,0)` in 2 | **fehlt im Sheet** |

Drei Konsequenzen:

1. **Die Kindzählung reproduziert die Sheet-Tabelle exakt**, wo beide sie kennen (62/62
   R5-Hybride).
2. **Der Spiegel weiß mehr als das Sheet.** `R2H0` mit 12 ABC + 2 HCC steht in der
   Sheet-Tabelle „Hybrid → Chipbestückung" gar nicht — obwohl TUDO 81 R2-Module baut.
   Eine reine Profiltabelle würde diese Lücke mitschleppen.
3. **Aber nicht verlassen darauf.** In 2 von 36 R2H0 sind die Chip-Kinder nicht
   gespiegelt (Zählung `(0,0)`), und der Chip-Sync ist laut docs/09 optional. Ein Zähler
   von 0 heißt „nicht gespiegelt", nicht „keine Chips".

**Empfehlung:** Kindzählung als Primärquelle, `type_code`-Tabelle im Institutsprofil als
Fallback, und ein sichtbarer Hinweis, wenn gezählt ≠ erwartet. Ein reines Profildatum ist
**nicht** nötig, aber als Rückfallebene sinnvoll.

**Verwandt: `ASIC_GLUE_WEIGHT`** — der Testtyp, zu dem die Sheet-Tabelle
„Chip → UV-Klebemenge" (ABC 0,0042 / HCC 0,0015 mit Formel `(B2*4.2)+(C2*1.5)`) gehört.
93 Läufe, alle auf `HYBRID_ASSEMBLY`, Result-Codes (alle `[g]`):
`GW_ASIC` 93, `GW_HYBRID_HT` 93, `GW_GLUE_ASICS` 91, `GW_HYBRID_HTG` 90,
`GW_HYBRID_HTGA` 90. Auch hier gilt das mg→g-Verhältnis: zFlow schreibt
`"GW_GLUE_ASICS": weightGlueAsics * 1e-3` (`processGoogleDoc.py:1036`). Die Sheet-Formel
liefert mg, die PDB speichert g.

---

## 6 — Die vollständige Zeilentabelle

Legende: **A** = PDB-Heimat, bei TUDO befüllt · **B** = PDB-Feld existiert, leer/fast leer ·
**C** = Objekt in der PDB, Verknüpfung fehlt → lokal · **D** = kein PDB-Feld → lokal ·
**E** = in der PDB, aber nicht gespiegelt.

### 6.1 Auxiliary Info

| # | Sheet-Zeile | Kat. | PDB-Heimat | Belegung |
|---:|---|:--:|---|---|
| 1 | Sensor ID | **A** | Kindkante `MODULE → SENSOR` (`component.parent_id`) | 205/231 Module (89 %) |
| 2 | Module Type | **A** | `component.type_code` | 265/265. Achtung Namensdrift: Sheet `R5M1` ↔ PDB `R5M1_HALFMODULE`; PDB-Werte: `R2` 81, `R5M0_HALFMODULE` 76, `R5M1_HALFMODULE` 74, `R5` 31, `R0` 3 |
| 3 | SCRIPT: current stage | **A** | `component.stage` | 265/265. Verteilung: `HV_TAB_ATTACHED` 97, `STITCH_BONDING` 54, `FAILED` 26, `GLUED` 26, `FINISHED` 22, `TESTED` 17, `BONDED` 12, `AT_LOADING_SITE` 5, `ON_CORE` 4, `STUFFED` 1, `LIMBO` 1 |
| 4 | Current location | **A** | `component.location` | `TUDO` 233, `UNIFREIBURG` 32 |

### 6.2 Band „HV-TAB ATTACHED"

| # | Sheet-Zeile | Kat. | PDB-Heimat | Belegung |
|---:|---|:--:|---|---|
| 5 | Module reception visual inspection + photo | **B** | `VISUAL_INSPECTION_RECEPTION` auf MODULE | nur **3** Läufe insgesamt, **1** Modul von 231. Existiert, praktisch ungenutzt |
| 6 | reception IV, in DB? | **A** | `ATLAS18_IV_TEST_V1` auf der **Sensor-Kindkomponente** | 1 064 Läufe / 364 Sensoren; `passed` 977 |
| 7 | HV tab jig | **C** | `TOOLS`-Komponenten (`R5_HV_tab_jig_04`, `_10`) existieren; **keine** Verwendungsbeziehung in der PDB | 0 Nachweise |
| 8 | HV tab sheet SN | **C** | 10 `HV_TAB_SHEET`-Komponenten bei TUDO (`ENDCAP_SHORT`/`ENDCAP_LONG`, Stage `SHEET_WITH_TABS`); **0 davon haben ein Elternteil**, kein Modul verweist auf sie | Verknüpfung fehlt vollständig |
| 9 | Sensor weight with tab (g) | **A** | `GLUE_WEIGHT.GW_SENSOR` **[g]** | 62 Läufe (45 live) / 42 Module; 7/7 Sheet-Werte bestätigt |
| 10 | IV after tabbing passed?. in DB? | **A** | `MODULE_IV_PS_V1` **@ Stage `HV_TAB_ATTACHED`** | 219 Läufe, 209 auf dieser Stage; **191/231 Module (83 %)** |
| 11 | SCRIPT: Module registered to DB? | **A** | Existenz der Komponente im Mirror + `component.sn` | 265/265 |

### 6.3 Band „Gluing Hybrids with TRUE BLUE - False blue"

| # | Sheet-Zeile | Kat. | PDB-Heimat | Belegung |
|---:|---|:--:|---|---|
| 12 | Glued by - Name | **D** | **Kein Feld.** `GLUE_WEIGHT` hat keine `OPERATOR`-Property (nur `GW_METHOD` + 3× `GLUE_METHOD_V_*`). Andere Testtypen haben eines (`MODULE_METROLOGY`, `MODULE_BOW`, `MODULE_WIRE_BONDING`, `WIRE_BONDING`) — **`GLUE_WEIGHT` nicht** | 0, strukturell unmöglich |
| 13 | Hybrids SNs (top, bottom) | **A** | Kindkante `MODULE → HYBRID_ASSEMBLY` | 98/231 Module (42 %). „top/bottom" ist im Mirror **nicht** abgebildet — TUDO-Halbmodule haben genau 1 Hybrid |
| 14 | top Hybrid weight (g) with ears | **B** | `GW_HYBRID1T` | 10 Läufe (3 live) / **2** Module |
| 15 | top Hybrid ears weight (g) | **B** | `GW_T1` | **0** — Feld existiert, nie geschrieben |
| 16 | top Hybrid weight without ears (g) | **A** | `GW_HYBRID1` **[g]** | 58 Läufe (42 live) / 40 Module; 7/7 Sheet-Werte bestätigt |
| 17 | bottom Hybrid weight (g) with ears | **B** | `GW_HYBRID2T` | **0** (Halbmodul, kein zweiter Hybrid) |
| 18 | bottom Hybrid ears weight (g) | **B** | `GW_T2` | **0** |
| 19 | bottom Hybrid weight without ears (g) | **B** | `GW_HYBRID2` | **0** |
| 20 | Module weight after gluing all hybrids (g) | **A** | `GW_MODULE_H1` (bei zwei Hybriden `GW_MODULE_H1H2`, 0 Läufe) | 62 Läufe (53 live) / 53 Module; 7/7 bestätigt |
| 21 | Modul Target weight (mg) | **D** | **Kein Feld.** `thresholds` sind bei allen `GW_*`-Parametern `null`, `automaticGrading=false` | → Institutsprofil |
| 22 | Tolerance (mg) | **D** | **Kein Feld** (dito) | → Institutsprofil |
| 23 | all Hybrid glue weight (mg) | **A** | `GW_GLUE_H1` **[g] = Sheet-mg ÷ 1000** | 60 Läufe (43 live) / 41 Module; 7/7 bei ×1000 bestätigt |
| 24 | Adhesive weight result hybrid | **D** | Nur indirekt über `test_run_evidence.passed` — **80 % Übereinstimmung** mit der Sheet-Rechnung, und ein Bit für zwei Urteile | → itkFlow rechnet aus Profil |
| 25 | Hybrid glue date | **A** (unscharf) | `GLUE_WEIGHT.measured_at` | 111 Module. Nur **93 von 216** Paaren stimmen tagesgenau mit dem `GLUED`-Stage-Event überein (Ausreißer bis −431 Tage). Separate Hybrid-/PB-Daten sind nicht rekonstruierbar: 82 der 134 Läufe tragen Hybrid **und** PB zusammen |
| 26 | Hybrid glue sample | **C** | `GLUE`-Komponenten existieren (15 bei TUDO, `TRUE_BLUE` 10 / `POLARIS_*` 4 / `LOCTITE_3525` 1); `20USEGT0000089` aus dem Sheet ist real. **Aber:** 0 Treffer für `20USEG*` in allen 14 759 Payloads, keine Parent-/Child-Kante | Verknüpfung fehlt. Lokale `glue_batch`-Tabelle hat derzeit **0 Zeilen** |
| 27 | Hybrid glue jigs used, top, bottom | **C** | siehe §2 | 0 Nachweise |
| 28 | Hybrid pickups used, top, bottom | **C** | siehe §2 | 0 Nachweise |
| 29 | Module jig used | **C** | siehe §2 | 0 Nachweise |
| 30 | SCRIPT: Hybrids assembled to module (in DB) | **A** | Existenz der Kindkante | 98/231 (42 %) |

### 6.4 Band „Gluing Powerboard with TRUE BLUE - False blue"

| # | Sheet-Zeile | Kat. | PDB-Heimat | Belegung |
|---:|---|:--:|---|---|
| 31 | Glued by - Name | **D** | wie #12 | 0 |
| 32 | Powerboard Label | **B** | `component.local_name` (PDB `alternativeIdentifier`) der PWB-Komponente | **0 von 109** PWB haben einen lokalen Namen. Feld existiert, bei TUDO durchgängig leer (DESYZ füllt es mit vierstelligen Hausnummern) |
| 33 | Powerboard SN | **A** | Kindkante `MODULE → PWB` | 69/231 Module (30 %) |
| 34 | Powerboard weight (g) | **A** | `GW_PB` **[g]** | 30 Läufe (29 live) / 28 Module; 4/4 bestätigt |
| 35 | Powerboard glue date | **A** (unscharf) | `GLUE_WEIGHT.measured_at` — derselbe Lauf wie #25 | siehe #25 |
| 36 | Powerboard glue sample | **C** | wie #26 | 0 |
| 37 | Powerboard glue jig, pickup tool | **C** | `20USERT0274006` = `R2PBS_R2_Powerboard_Jig_01-006`, `20USERT0284004` = `R2PBS_Pickup_01-004` — beide real, beide unverknüpft | 0 |
| 38 | SCRIPT: Powerboard assembled to module (in DB) | **A** | Existenz der Kindkante | 69/231 |
| 39 | Module weight after gluing powerboard AND hybrid | **A** | `GW_MODULE_H1PB` **[g]** | 78 Läufe (77 live) / 75 Module; 4/4 bestätigt |
| 40 | Target weight (mg) | **D** | wie #21 | → Profil |
| 41 | Tolerance (mg) | **D** | wie #22 | → Profil |
| 42 | Powerboard glue weight (...mg) | **A** | `GW_GLUE_PB` **[g] = mg ÷ 1000**; kombiniert `GW_GLUE_H1PB` | 32 Läufe (31 live) / 29 Module; 4/4 bei ×1000 bestätigt. **Die negativen Sheet-Werte (`-9010`, `-9886`) existieren in der PDB nicht** — es gibt dort weder negative noch Null-Werte in irgendeinem `GW_`-Code (Q10) |
| 43 | Adhesive weight result powerboard | **D** | wie #24 | → itkFlow rechnet |
| 44 | SCRIPT: Glue weights uploaded, stage set to GLUED | **A** | `GLUE_WEIGHT`-Lauf vorhanden **und** Stage-Event `GLUED` | 111 Module mit Lauf, 125 je `GLUED` erreicht, **111 beides**; 14 sind `GLUED` ohne Lauf, 0 umgekehrt |

### 6.5 Band „Measure"

| # | Sheet-Zeile | Kat. | PDB-Heimat | Belegung |
|---:|---|:--:|---|---|
| 45 | Visual Inspection Photo | **B** | Attachment an einem `VISUAL_INSPECTION`-Lauf. Das Schema hat **keinen** Foto-Parameter — nur `LOCATION1..6`, `DAMAGE_TYPE1..6`, `IMS1..6` (Bildreferenz-Strings) | 160 Läufe, davon **8 mit Attachment**; 11 Dateien über 8 SNs; `LOCATION1` 11×, `DAMAGE_TYPE1` 7×, `IMS1` **2×**. Mechanismus vorhanden, bei TUDO praktisch ungenutzt |
| 46 | Bow Metrology | **A** | `MODULE_BOW.BOW` **[um]** | 28 Läufe (21 live) / **19 Module (8 %)** |
| 47 | Bow Metrology Date | **A** | `MODULE_BOW.measured_at` | dito |
| 48 | Metrology outcome | **A** | `MODULE_METROLOGY` + `passed` | 105 Läufe / 94 Module; `passed` 20 / `failed` 85 |
| 49 | Metrology date | **A** | `MODULE_METROLOGY.measured_at` | dito |
| 50 | Metrology results uploaded to DB? | **A** | Existenz des Laufs — im PDB-Modell **dieselbe** Information wie #48 | 94/231 (41 %); 137 Module → `Messung fehlt!` |

### 6.6 Band „Module stitching"

| # | Sheet-Zeile | Kat. | PDB-Heimat | Belegung |
|---:|---|:--:|---|---|
| 51 | Half module sibling (only R3-R5) | **A** | Geschwister = das andere `MODULE`-Kind desselben Elternteils | **62** Halbmodule, alle mit auflösbarem Geschwister |
| 52 | SCRIPT: Complete module registered to DB | **A** | Elternteil vom Typ `MODULE` (`R5`) vorhanden | 31 `R5`-Vollmodule, je 2 Kinder = 62 Kanten |

### 6.7 Band „BONDED"

| # | Sheet-Zeile | Kat. | PDB-Heimat | Belegung |
|---:|---|:--:|---|---|
| 53 | Visual Inspection Photo | **B** | wie #45 | wie #45 |
| 54 | Module bond date | **A** | `MODULE_WIRE_BONDING.measured_at` **oder** Stage-Event `BONDED` | 17 Läufe / 12 Module vs. **82 Stage-Events / 77 Module** — das Stage-Event ist die deutlich breitere Quelle |
| 55 | Visual Inspection FE bonds (officially optional) | **B** | `VISUAL_INSPECTION` auf MODULE | 25 Läufe / 17 Module, davon 11 mit `LOCATION1` |
| 56 | IV after bonding | **A** + **B** | Praxis: `MODULE_IV_AMAC` @ `BONDED`. Offiziell: `MODULE_IV_PS_BONDED` — **Schema gespiegelt, 0 Läufe** | 27/231 Module (12 %) |
| 57 | DAQ Quick test | **A** + **B** | Praxis: `*_PPA`-Familie am Hybrid-Kind. Offiziell: `HYBRID_TESTS_SUMMARY` auf MODULE — **Schema gespiegelt, 0 Läufe** | 96 Module über `RESPONSE_CURVE_PPA` |
| 58 | UBC Uploader: quick electrical test passed | **A** | dieselben Läufe; `payload.run_number` = ITSDAQ-Laufnummer (`189-6`, `1401-150`) | 96 Module |
| 59 | DAQ TC test (incl. IV) | **A** | `MODULE_IV_AMAC_TC` (Modul) + `*_TC`-Familie (Hybrid-Kind) | 24 bzw. 32 Module |

### 6.8 Band „TESTED"

| # | Sheet-Zeile | Kat. | PDB-Heimat | Belegung |
|---:|---|:--:|---|---|
| 60 | UBC Uploader: thermal cycling electrical tests passed | **A** | `RESPONSE_CURVE_TC` / `NO_TC` / `PEDESTAL_TRIM_TC` / `STROBE_DELAY_TC` / `OPEN_CHANNEL_SEARCH_TC` am Hybrid-Kind, `run_number` | 32 Module |

### 6.9 Zeilen, die nur im DESYZ-Blatt vorkommen

| # | Sheet-Zeile | Kat. | PDB-Heimat | Belegung |
|---:|---|:--:|---|---|
| 61 | HV/GND bond & Post-glue IV (officially optional) | **B** | `MODULE_IV_PS_V1` @ Stage `GLUED` | **1** Lauf bei TUDO |
| 62 | PB-Hy bond date | **D** | **Kein Feld.** `MODULE_WIRE_BONDING` hat zwar `FAILED_HYBRID_TO_PB` / `REPAIRED_HYBRID_TO_PB`, aber kein Datum pro Bondschritt | 0 |
| 63 | DAQ functional test | **A** | Hybrid-Elektrik-Familie (siehe #57) | 96 Module |
| 64 | Hybrid frontend (FE) bond | **A** | `MODULE_WIRE_BONDING.FAILED_FRONTEND_ROW1..4`, `REPAIRED_FRONTEND_ROW1..4`, `MAX_CONT_UNCON_ROW1..4`, `TOTAL_*` (22 Parameter) | 17 Läufe / 12 Module |
| 65 | Bond data (could be e.g. Row Test) | **B** | `MODULE_WIRE_BONDING`-Parameter; `PULL_TEST` (4 Läufe, auf `HYBRID_FLEX`), `SHEAR_TEST` (4, auf `HV_TAB_SHEET`), `HYBRID-WIRE-PULL` (1) | **0 auf MODULE-Ebene** |
| 66 | DAQ module test | **A** | `MODULE_IV_AMAC_TC` + `*_TC`-Familie | 24/32 Module |
| 67 | FINISHED MODULE: Visual Inspection photo | **B** | wie #45 | wie #45 |
| 68 | Packing date (box, humi, silica, bag) | **D** | **Kein Feld.** Weder ein Testtyp noch die `shipment`-Tabelle kennt ein Packdatum | 0 |
| 69 | Shipping date (peli case) | **B** | `shipment.sent_at` (121 Shipments, alle mit `sent_at`) | Nur **18 von 265** Modulen tauchen je als Shipment-Item auf (22 Item-Einträge). Für 93 % der Module nicht ableitbar |
| 70 | add to this batch by zFlow (`iPRESERIES_*`, `iPRODUCTION_*`) | **E** | PDB-Payload enthält `batches[]` (siehe `pdb_sync._is_dummy`), aber der Mirror reduziert das auf das Boolean `is_dummy` | **Mirror-Lücke** — 4 Komponenten als `is_dummy` markiert, sonst keine Batch-Information gespeichert |
| 71 | Finished | **A** | `component.stage == 'FINISHED'` | 22 Module |
| 72 | Shipment status: for info | **A** | `shipment.status` | `delivered` 103, `prepared` 11, `inTransit` 5, `deliveredIncomplete` 2 |
| 73 | zFlow Processing: Last update / Next update | **D** | Kein PDB-Datum. itkFlow hat eigene Äquivalente: `component.synced_at`, `test_run_evidence.synced_at`, `sync_job` | itkFlow-eigen, nicht aus der PDB |
| 74 | Comments | **D** | **Kein modulweiter Freitext.** `GLUE_WEIGHT`, `MODULE_METROLOGY`, `MODULE_BOW` haben **keine** `COMMENTS`-Property. `MODULE_IV_PS_V1` hat eine (219 befüllt), aber **213 davon sind der Leerstring** — verbleiben 6 Läufe mit Inhalt (`'IV'`, `'with_hvtab'`, `'Module glued'`) | Die im Transkript zitierten Ausfallanalysen haben **keine PDB-Heimat** |

---

## 7 — Querschnittsbefunde, die der Plan kennen muss

### 7.1 Der Mirror hält gelöschte PDB-Läufe

Von 14 759 gespiegelten Läufen haben **102 `state='deleted'`** und 1
`state='requestedToDelete'` (Q14). Verteilung der auffälligsten:

| Testtyp | gelöschte Läufe | Anteil am Testtyp |
|---|---:|---:|
| `GLUE_WEIGHT` | **18** | **13,4 %** |
| `MODULE_BOW` | **7** | **25,0 %** |
| `MODULE_IV_PS_V1` | 3 (+1 `requestedToDelete`) | 1,8 % |
| `MODULE_METROLOGY` | 2 | 1,9 % |
| `MODULE_WIRE_BONDING` | 2 | 11,8 % |

`test_run_evidence` hat keine eigene Statusspalte — der Zustand steckt in
`payload.state`. Jede Auswertung („jüngster Lauf", pass/fail, Statistik) muss darauf
filtern, sonst zeigt die Detailseite zurückgezogene Messungen als gültig. Bei
`MODULE_BOW` wäre jeder vierte angezeigte Lauf falsch.

### 7.2 95 % der Testläufe hängen nicht am Modul

Q19 (`LEFT JOIN component` über alle 14 759 Läufe):

| Trägerkomponente | Läufe | Anteil |
|---|---:|---:|
| `PWB` | 5 692 | 38,6 % |
| `SENSOR` | 3 966 | 26,9 % |
| `HYBRID_ASSEMBLY` | 3 764 | 25,5 % |
| **`MODULE`** | **720** | **4,9 %** |
| `EC_POWERBOARD_FLEX` | 298 | 2,0 % |
| `HYBRID_FLEX` | 206 | 1,4 % |
| `SENSOR_S_TEST` | 101 | 0,7 % |
| `HV_TAB_SHEET` / `HYBRID` / `HYBRID_TEST_PANEL` | 12 | 0,1 % |

Eine Modulseite, die nur `test_run_evidence.component_sn = <Modul-SN>` abfragt, sieht
**4,9 %** der relevanten Historie. Das Sheet dagegen zeigt Sensor-Reception-IV,
Hybrid-DAQ und Powerboard-Elektrik in derselben Spalte.

Die 720 MODULE-Läufe verteilen sich auf genau neun Testtypen (Q19):
`MODULE_IV_PS_V1` 219 (191 SNs), `GLUE_WEIGHT` 134 (111), `MODULE_IV_AMAC` 133 (47),
`MODULE_METROLOGY` 105 (94), `MODULE_IV_AMAC_TC` 56 (40), `MODULE_BOW` 28 (19),
`VISUAL_INSPECTION` 25 (21), `MODULE_WIRE_BONDING` 17 (14),
`VISUAL_INSPECTION_RECEPTION` 3 (1). Die SN-Zahlen in §6 sind kleiner, weil sie auf die
231 Halb-/R2-Module eingeschränkt sind; die Differenz sind die R5-Vollmodule.

### 7.3 Komponenten-Properties werden gar nicht gespiegelt

`pdb_sync.map_pdb_component` übernimmt elf Felder und **keine** `properties`. Alles, was
in der PDB an einer Komponente oder an einer Assembly-Beziehung als Property hängt, ist
für itkFlow heute unsichtbar. Das betrifft direkt die Zeilen 7, 8, 26, 27, 28, 29, 36, 37
und 70. Falls sich in der PDB doch eine Werkzeug- oder Klebstoff-Property finden lässt,
wäre eine Mirror-Erweiterung die Voraussetzung — mit dem heutigen Mirror ist die Frage
nicht entscheidbar, und nach dem Payload-Scan (Q15) spricht nichts dafür.

### 7.4 Datenqualität in den Freitext-Properties

Beispiele aus Q4 (Personennamen anonymisiert):

| Property | Testtyp | Varianten desselben Inhalts |
|---|---|---|
| `GW_METHOD` | `GLUE_WEIGHT` | `Stencil`, `stencil`, `stencils`, `Stencils`, `stensil` |
| `JIG` | `MODULE_BOW` | `Module Assembly Jig`, `Module assembly jig`, `Module Metrology Jig`, `1` |
| `USED_SETUP` | `MODULE_BOW` | `Keyence - VR3200`, `Keyence`, `1`, `Flash CNC 300 Smartscope` |
| `MACHINE` | `MODULE_METROLOGY` | `Keyence VR-3200`, `Keyence`, `Flash CNC 300 Smartscope` |
| `OPERATOR` | `MODULE_METROLOGY` | `admin` ×89 sowie Klarnamen und Login-Kürzel derselben Person nebeneinander (z. B. `Anna Abel` und `aabel`) |
| `VBIAS_SMU` | `ATLAS18_IV_TEST_V1` | `Keithley 2410`, `Keitlhey2410`, `Keithley2410`, `None` |

Wenn itkFlow diese Felder künftig schreibt, sollte es sie normalisieren (Auswahl statt
Freitext) — und `OPERATOR` sollte aus dem angemeldeten Konto kommen, nicht aus einem
Textfeld. Das löst nebenbei Zeile #12 (`Glued by - Name`) für alle Testtypen, **die eine
`OPERATOR`-Property haben** — `GLUE_WEIGHT` hat keine, dort bleibt es lokal.

### 7.5 Was itkFlow lokal bereits vorhält, aber nicht nutzt

| Tabelle | Zeilen | Bezug |
|---|---:|---|
| `glue_batch` | **0** | wäre die Heimat für #26/#36 (`Hybrid/Powerboard glue sample`) |
| `glue_usage` (mit `amount_mg`, `component_sn`, `used_by`, `used_at`) | **0** | wäre die Heimat für Verbrauch + #12/#31 (`Glued by`) + #25/#35 (Klebedatum) |
| `tool` | 92 | vollständig, deckungsgleich mit den PDB-`TOOLS`; es fehlt nur eine Verwendungstabelle für #7/#27/#28/#29/#37 |
| `institute_profile.settings` | `{}` | leer — Zieltabellen (#21/#22/#40/#41), `assembly_property_keys` und `assembly_tool_slots` sind unkonfiguriert |

Die lokalen Strukturen für den größten Teil der D/C-Zeilen existieren also schon; es
fehlt die Erfassung und die Anbindung an die Modulseite.

---

## 8 — Abfragenverzeichnis

Alle Zahlen stammen aus diesen tatsächlich ausgeführten Read-only-Abfragen gegen
`itkflow.db` (`mode=ro&immutable=1`). Die Skripte liegen im Scratch-Verzeichnis dieser
Session.

| ID | Skript / SQL | Liefert |
|---|---|---|
| **Q1** | `SELECT test_type, COUNT(*), SUM(passed), MIN/MAX(measured_at) FROM test_run_evidence GROUP BY test_type` | Testtyp-Inventar (58 Typen, 14 759 Läufe) |
| **Q2** | `gw.py` — JSON-Scan aller 134 `GLUE_WEIGHT`-Payloads | GW-Code-Inventar, Befüllung, `result_meta`-Namen, Properties |
| **Q3** | `gw2.py` — sortierte Werteliste je GW-Code | Cluster- und Ausreißererkennung |
| **Q4** | `props.py` — Property-Scan über **alle** 14 759 Payloads | Properties je Testtyp mit pop/null und Werteverteilung |
| **Q5** | `tree.py` — Parent-/Child-Auswertung über 3 046 Komponenten | Kantentypen, Chipzählung je Hybridtyp, Modulzusammensetzung |
| **Q6** | `SELECT schema FROM test_type_schema` + JSON-Auswertung | Parameter, Properties, `required`, `thresholds`, `automaticGrading` der 14 Modul-Testtypen |
| **Q7** | `SELECT test_type, COUNT(*), COUNT(DISTINCT component_sn), SUM(relative_path IS NOT NULL) FROM test_run_attachment GROUP BY test_type` | Attachment-Inventar |
| **Q7a** | Regex über `test_run_attachment.filename` nach Stage-Token | 218/218 `MODULE_IV_PS_V1`-Dateien mit `HV_TAB_ATTACHED` |
| **Q8** | `cover.py` — Abdeckung je Testtyp über die 231 Halb-/R2-Module | Modul-Abdeckungsquoten, GW-Codes je Modul, roh-vs-abgeleitet |
| **Q9** | `units.py` — Plausibilitätsbänder + Duplikaterkennung | 27 bzw. 11 Ausreißerzellen, 20 Läufe mit Feldduplikaten |
| **Q10** | `sheetmatch.py` — Abgleich der transkribierten Werte gegen die Mirror-Wertemengen | 40/40 Treffer, Negativ-/Null-Prüfung |
| **Q11** | `bytype.py` — Join `test_run_evidence` × `component` × `stage_event` | Testtyp→Komponententyp; Stage zum Messzeitpunkt |
| **Q11a** | Hybrid→Modul-Auflösung + `*_PPA`/`*_TC`-Familien | Erreichbarkeit der Elektriktests über Kindkanten, `run_number` |
| **Q12** | `verdict.py` — `passed` vs. nachgerechnetes Sheet-Urteil | 48/60 = 80 % Übereinstimmung |
| **Q13** | `scriptrows.py` — Ableitbarkeit der `SCRIPT:`-Zeilen | Kindkanten-, Geschwister- und `GLUED`-Quoten |
| **Q14** | `payload.state`-Verteilung über alle Läufe; `passed`/`problems`-Kreuztabelle | 102 gelöschte Läufe; Unabhängigkeit von `passed` und `problems` |
| **Q15** | Regex `20USE(G[TPL]\|RT\|VS\|VL)\d+` über alle 14 759 Payloads | **0 Treffer** — keine Glue-, Tool- oder HV-Tab-SN in irgendeinem Testlauf |
| **Q16** | `shipment.items` JSON-Auswertung | 1 332 SNs als Items, davon 18 MODULE |
| **Q17** | `SELECT code, name, settings FROM institute_profile` | TUDO-Profil, `settings = {}` |
| **Q18** | Mengenvergleich `tool.code` ↔ `component.sn WHERE component_type='TOOLS'` | 92/92 Überlappung |
| **Q19** | `SELECT c.component_type, COUNT(*) FROM test_run_evidence e LEFT JOIN component c ON c.sn=e.component_sn GROUP BY 1` | Verteilung der Läufe auf Trägerkomponenten (§7.2) |

Zusätzlich gelesen (nie ausgeführt): `references/zeuthenflow/modules/processGoogleDoc.py`
(Zeilen 1036, 2053–2110) und `references/zeuthenflow/tests/expected_output.txt`;
`backend/app/assembly.py`, `backend/app/pdb_submit.py`, `backend/app/pdb_sync.py`,
`backend/app/pdb_test_evidence.py`.

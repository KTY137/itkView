# Zeilen-Semantik der zFlow-Modulblätter (Recherche, 2026-08-26)

> **Was das ist.** Zu jeder Zeile der Transkription
> `docs/superpowers/research/2026-08-26-zflow-sheet-transcription.md` steht hier:
> woher der Wert kommt, wohin er geht, was er blockiert und was eine
> Neuimplementierung falsch machen würde. Belegt ausschließlich aus
> `references/zeuthenflow` (nur gelesen, nie ausgeführt/importiert),
> `docs/01-ist-analyse-zeuthenflow.md` und `docs/10-itk-domain-reference.md` §7.
> Wo die Referenz schweigt, steht **nicht belegt** — nicht geraten.
>
> **Lesereihenfolge:** §0 (Mechanik) ist Pflicht, danach §1–§4 zeilenweise parallel
> zur Transkription, §5 Klebegewichtskette, §6 Line-Speed, §7 was das System
> sonst noch tut, §8 die Widerspruchsliste, §9 Konsequenzen für itkFlow.
>
> Kurzformen: `pGD` = `references/zeuthenflow/modules/processGoogleDoc.py`,
> `mM` = `references/zeuthenflow/core/moduleManager.py`,
> `dbC` = `references/zeuthenflow/modules/dbObjects/dbComponent.py`,
> `dbM` = `references/zeuthenflow/modules/dbObjects/dbModule.py`,
> `tC` = `references/zeuthenflow/modules/toolConverter.py`,
> `gH` = `references/zeuthenflow/core/glueHandler.py`,
> `uM` = `references/zeuthenflow/core/uploadManager.py`.

---

## 0 — Mechanik: wie zFlow das Blatt liest und „zurückschreibt"

Ohne diese sechs Punkte ist keine einzige Zeile richtig zu deuten.

**0.1 Lesen ist ein TSV-Export, kein API-Zugriff.** `GoogleDocDownloader.getURL`
(pGD:21-25) baut `…/export?format=tsv&gid=<sheetID>` und lädt die Datei
(pGD:27-34). Danach `slimToRelevantContent` (pGD:262-277): erste Spalte weg,
komplett leere Spalten weg, Spalten mit dem Titel „Bitte Modul auswählen" weg,
Zeilen ohne `Module Name` weg. Dann `defineTransposedDF` (pGD:278-312):
transponieren, sodass aus jeder Modulspalte eine Pandas-Zeile wird.

**0.2 Doppelte Zeilenbeschriftungen werden still umbenannt.** Der `renamer` in
`defineTransposedDF` (pGD:297-310) hängt an das zweite Vorkommen `_1` an. Der
Code nennt als Beispiele wörtlich **„Tolerance (mg)"** und **„Glued by - Name"** —
genau die beiden Beschriftungen, die im Blatt zweimal vorkommen (Hybrid- und
Powerboard-Band). Heute harmlos, weil zFlow keine davon liest; für jede
Neuimplementierung, die sie *lesen* will, ist es eine Falle.

**0.3 Jede Zelle ist ein `SpreadsheetEntry` mit exaktem Titel-String,
optionalem Checker und optionalem Processor** (pGD:480-591). `get()` (pGD:501-591):
- Zeilentitel nicht gefunden → `logger.error("Could not find row …")`, **None**;
- Regex/Checker schlägt fehl → `logger.error` **und** `logger.telewarning`
  (Telegram/Mattermost) und **None** (pGD:534-556);
- sonst Processor anwenden.
Fazit: **Ein Tippfehler in der Beschriftung oder im Format deaktiviert die
zugehörige Logik lautlos** (Lauf geht weiter), meldet sich nur im Chat-Kanal.

**0.4 zFlow schreibt nie in das Blatt.** `main_module` sammelt pro Modul ein
Dict (mM:1264-1316) und schreibt am Ende `output/fromModules.tsv`
(mM:1357-1359). Diese Datei wird über einen Public-Share veröffentlicht; das
Apps Script `importPPBModData` (`scripts/macros.gs`:69-84) fügt sie alle 30 min
in ein **verstecktes Tab `PPB_Module_overview`** ein. Die sichtbaren
`SCRIPT:`-Zeilen im Modulblatt sind Nachschlage-Formeln über dieses Tab.
**Die Formeln selbst liegen nicht in der Referenz** → für jede `SCRIPT:`-Zeile
gilt: Quellspalte in `fromModules.tsv` ist belegt, die Blattformel ist
*nicht belegt*.
Der Kommentar mM:1315 („more to come here at the bottom to not upset the
current extraction mechanism in the google sheet!") zeigt: **die Extraktion im
Blatt erfolgt über Spaltenposition**, nicht über Spaltennamen — die Reihenfolge
des Dicts ist Teil des Vertrags.

**0.5 Vier Zellenklassen.** Jede Zeile der Transkription fällt in genau eine:

| Klasse | Herkunft | Beispiele |
|---|---|---|
| **Eingabe** | Mensch tippt/scannt oder Waage → Mensch tippt ab | `Sensor ID`, `Sensor weight with tab (g)`, `Hybrid glue date` |
| **Ableitung** | Blattformel | `all Hybrid glue weight (mg)`, `Modul Target weight (mg)`, `Adhesive weight result …` |
| **Sync-Ampel** | zFlow → TSV → Overview-Tab → Formel | alle `SCRIPT: …`, `Metrology outcome`, `DAQ Quick test`, `Last update` |
| **Nur Blatt** | von zFlow nie gelesen | `Glued by - Name`, `Powerboard Label`, `Comments`, alle Bond-/Packing-Datumszeilen |

**0.6 Der harte Schreib-Gate sitzt in der PDB-Schicht, nicht im Blatt.**
`isOperationPermitted` (dbC:1706-1737) verweigert *jede* Schreiboperation
(Assembly, Stage-Move, Property), wenn das Bauteil nicht am eigenen Institut
steht, der Nutzer keine Executive-Rechte hat, oder das Bauteil `inTransit` ist.
`moveComponentToStage` (dbC:1739-1846) läuft Stages **einzeln** hoch, verweigert
Rückwärtsbewegungen ohne `doRework=True`, springt bei `FAILED` direkt und
**überspringt `AT_LOADING_SITE` bewusst** (dbC:1828-1829).

---

## 1 — Blatt „at TUDO", Zeile für Zeile

### 1.1 Auxiliary Info

#### `Sensor ID`
- **Herkunft:** Mensch (Scan/Tippen). `pGD:1130-1141`. Akzeptiert **entweder**
  eine PDB-SN `20USES[0-5]\d{7}` **oder** eine Herstellerkennung `AAA12345-B123`.
- **Ziel:** PDB-**Assembly-Link** Modul ← Sensor, mit der Attachment-Property
  `HV_TAB_SHEET` (`dbM:111-151`). Eine Nicht-SN wird über
  `findComponentByProperty("SENSOR","ID", …)` aufgelöst
  (`dbSensor.py:41-57`).
- **Gate:** **Härtester Blocker des ganzen Blattes.** Ist die Zelle leer oder
  enthält sie den Text „versehentlich schon registriert", wird die gesamte
  Modulspalte übersprungen (`mM:138-140`). Vor einer Neuregistrierung prüft
  zFlow zusätzlich, ob der Sensor schon an einem anderen Modul hängt — wenn ja,
  Abbruch der Spalte (`mM:341-347`).
- **Semantik:** Der Sensor ist die Identität des Moduls, bevor das Modul eine SN
  hat. Zwei Identifier-Räume in einer Zelle (PDB-SN vs. Hersteller-ID) — eine
  Neuimplementierung braucht beide Auflösungswege.

#### `Module Type`
- **Herkunft:** Mensch (Dropdown). `pGD:1085-1090`, Regex `^(R[01345]M[01])|(R2)$`.
- **Ziel:** **Keine** PDB-Property. Steuert (a) den Registrierungstyp
  `{modType}_HALFMODULE` für R3–R5 bzw. `R{n}` sonst (`mM:353-356`),
  (b) die Werkzeug-Auflösung (`tC:188-305`), (c) `powerboardReqCount`
  (`mM:476`), (d) im **Blatt** die Ziel-/Toleranz-Nachschläge (§5).
- **Gate:** `int(modType[1])` (`mM:270`) — schlägt der Regex fehl, liefert `.get`
  None und der Zugriff wirft `TypeError`, d. h. der **ganze Lauf bricht ab**.
  Die einzige Zelle mit dieser Wirkung.
- **Semantik:** zFlow benutzt für dieselbe Tatsache drei Quellen: den Blatt-Typ
  (`mM:476`), den PDB-`subType` (`mM:1468-1485`) und die SN-Zeichen 5-6
  (`pGD:1725-1757`). Siehe §8.18.

#### `SCRIPT: current stage`
- **Herkunft:** zFlow (Sync-Ampel). Quelle `fromModules.tsv` → `stage`
  (`mM:1267`), Wert = `moduleDBObj.stage` aus der PDB.
- **Ziel:** Anzeige — **und Rücklesekanal für zFlow selbst**: `skipLoopForModule`
  setzt `dummyDBObj.stage` aus dieser Zelle (`mM:1390`), um ohne DB-Abfrage zu
  entscheiden, ob die Spalte in diesem Lauf übersprungen werden darf.
- **Gate:** Mit gesetztem `reprocessFinishedComponentsEveryHours`
  (`default.conf:36`, standardmäßig auskommentiert) gilt `canSkipReprocessing`
  (`dbC:1322-1353`): Stage ≥ `FAILED` (Halbmodul) bzw. ≥ `FINISHED` (Ringmodul)
  oder Standort ≠ Institut → nur alle N Stunden verarbeiten.
  Zusätzlich filtert `macros.gs:143-157` (`HideColumns`) Spalten nach dieser Zeile.
- **Semantik:** Ein aus der PDB gespiegelter Wert, der *zurück in die
  Ablaufsteuerung* fließt. In itkFlow entfällt er ersatzlos.

#### `Current location`
- **Herkunft:** zFlow, `fromModules.tsv` → `currentLocation` (`mM:1268`).
- **Ziel:** Anzeige + Skip-Logik (`mM:1391`).
- **Gate:** Der eigentliche Gate ist `isOperationPermitted` (dbC:1706-1737, §0.6);
  die Zelle ist nur die zwischengespeicherte Kopie.

### 1.2 Band „HV-TAB ATTACHED"

#### `Module reception visual inspection + photo`
- **Herkunft:** Mensch. `pGD:1203-1207`, **kein Checker** (beliebiger Text).
- **Ziel:** **Kein Testlauf.** In `getSensorPassedReception` (`pGD:1498-1533`)
  wird `ok` (case-insensitiv) zu True, jeder andere nicht-leere Wert zu False.
  Zusammen mit `reception IV, in DB?` ergibt das einen Boolean, der als
  **PDB-Component-Flag auf dem *Sensor*** gesetzt wird:
  `PASSED_MODULE_RECEPTION` / `FAILED_MODULE_RECEPTION`
  (`dbSensor.py:117-171`, aufgerufen `mM:426`).
- **Gate:** `sensorPassedReceptionTestsPassed` ist eines von sieben Kriterien für
  `pureHalfModulePass` (`mM:957-965`) — also mittelbar für FINISHED/FAILED.
- **Semantik, die man falsch machen würde:**
  1. Der Übergang FAILED → PASSED wird **verweigert** und verlangt manuelle
     Aktion (`dbSensor.py:139-143`).
  2. Sind *beide* Zellen leer, ist das Ergebnis `None` (`pGD:1529-1531`) —
     „missing", nicht „failed". Missing blockiert FINISHED, setzt aber nicht FAILED.
  3. Ist nur eine leer, ebenfalls `None`. Nur wenn beide gefüllt sind, entsteht
     ein Urteil.

#### `reception IV, in DB?`
- **Herkunft:** Mensch. `pGD:1208-1212`.
- **Ziel/Gate:** wie oben. Sonderwert **`skipped as sensor irradiated`** → `None`,
  also ausdrücklich neutral statt „failed" (`pGD:1517-1521`).
- **Semantik:** Trotz des Zeilennamens „in DB?" **prüft zFlow hier nichts in der
  DB** — es glaubt dem getippten Wort. Die echte DB-Prüfung
  (`DBSensor.receptionTestStatus`, `dbSensor.py:176-185`, Tests
  `VIS_INSP_RES_MOD_V2` + `ATLAS18_IV_TEST_V1`, letzterer *if-present*) wird nur
  vom `overviewMaker` benutzt, nicht vom Modul-Flow.

#### `HV tab jig`
- **Herkunft:** Mensch (Dropdown). `pGD:1196-1201`, `toolRegex` akzeptiert
  PDB-Werkzeug-SN `20USERT\d{7}`, `select`, eine blanke Zahl **oder einen
  Farbnamen** (die Farbliste wird zur Laufzeit aus dem ToolConverter-Blatt in
  den Regex einkompiliert, `pGD:1059-1067`).
- **Ziel:** **Component-Property** `HV_TAB_ASSEMBLY_JIG` am Modul — bei der
  Registrierung gesetzt (`dbM:88-92`) und danach über `comparePropertiesGoogleDB`
  laufend abgeglichen (`mM:396-399`, `dbC:1254-1268`, `dbC:1293-1320`).
- **Gate:** **Hart.** Ohne diesen Wert wird ein neues Modul gar nicht registriert
  (`mM:333-337`).
- **Semantik:** Beim Abgleich wird nur das erste Whitespace-Token verwendet
  (`splitSafe`, `mM:387-394`) — „20USERT0510405 (alt)" wird also normalisiert.
  Umrechnung Farbe/Nummer → SN über `getToolSN(moduleType.split("M")[0],
  "HV tab jig", …)` (`tC:213-220`), also **grober** Typ (R5, nicht R5M1).
  Abgleichsregel: Blatt leer + DB gefüllt → *Blatt* nachziehen; Blatt gefüllt und
  abweichend → *PDB* überschreiben (`dbC:1309-1318`). Beim `LOCALNAME` dagegen
  wirft eine Abweichung eine Exception (`dbC:1301-1308`).

#### `HV tab sheet SN`
- **Herkunft:** Mensch/Scan. `pGD:1309-1314`, Regex `^20USEV[SL]\d{7}$`.
- **Ziel:** **Attachment-Property `HV_TAB_SHEET`** am Link Sensor→Modul
  (`pGD:2116-2129` → `dbM:127-139`).
- **Gate:** **Hart für die Sensor-Assemblierung.** `getSensorAttachmentProps`
  gibt None zurück, wenn leer; `associate_child` bricht dann ab
  (`mM:1629-1632`), und weil ohne Sensor die ganze Spalte per `continue`
  verlassen wird (`mM:439-443`), **blockiert eine leere HV-Tab-Sheet-Zelle das
  komplette Modul**.
- ⚠ Im TUDO-Ausschnitt ist diese Zeile **leer**, im DESYZ-Blatt gefüllt. Wenn das
  die Realität abbildet, kann TUDO mit dieser Codebasis keinen Sensor
  assemblieren. Vom Owner zu klären.

#### `Sensor weight with tab (g)`
- **Herkunft:** Waage → Mensch tippt ab. `pGD:1214-1220`; deutsche Dezimalkomma
  wird konvertiert (`convertGermanNumberToFloat`, `pGD:429-438`,
  aktiviert über `useGermanNumbers = True`, `default.conf:31`).
- **Ziel:** `GLUE_WEIGHT`-Testlauf-**Result `GW_SENSOR`** (`pGD:2072`).
- **Gate:** In `requiredAlways` des *vollständigen* Dicts (`pGD:1953-1960`) —
  ohne diesen Wert entsteht nur der reduzierte („spartanic") Testlauf.
  Für den reduzierten Testlauf ist die Zeile ausdrücklich **auskommentiert**
  (`pGD:1841-1843`).

#### `IV after tabbing passed?. in DB?`
- **Herkunft:** Sync-Ampel, **nicht** als `SpreadsheetEntry` definiert →
  von zFlow **nicht gelesen**.
- **Quelle des angezeigten Werts:** `fromModules.tsv` → `hvTabAttachTests`
  (`mM:1276`), erzeugt aus `getTestPassedMsg(["MODULE_IV_PS_V1",
  "VISUAL_INSPECTION"], stageFilter="HV_TAB_ATTACHED", optionalTests=
  ["VISUAL_INSPECTION"])` (`mM:683-693`). Die konkrete Blattformel ist
  **nicht belegt**.
- **Semantik:** `MODULE_IV_PS_V1` ist hier **Pflicht und muss bestehen**,
  `VISUAL_INSPECTION` ist **optional** (darf fehlen). Genau diese Modus-Trennung
  fehlt itkFlow heute (docs/10 §7.6.1).

#### `SCRIPT: Module registered to DB?`
- **Herkunft:** zFlow. `pGD:1120-1126`; Quelle `fromModules.tsv` → `sn`
  (`mM:1266`).
- **Ziel/Wirkung:** Das Modul wird entweder per SN bzw. per `LOCALNAME` gefunden
  (`mM:299-322`) **oder von zFlow neu registriert** (`dbM:72-109`) mit den
  Properties `LOCALNAME` (= Spaltenüberschrift) und `HV_TAB_ASSEMBLY_JIG`.
  Vor und nach der Registrierung geht eine Telegram-Warnung raus (`mM:363-371`).
- **Gate:** Steht hier eine SN, das DB-Objekt lässt sich aber nicht
  initialisieren, wird die Spalte als „inkonsistent" übersprungen
  (`mM:326-330`). `-` wird zu None normalisiert (`noneIfHyphen`, `pGD:473-477`).
- **Semantik:** Diese Zelle ist **Rückkanal und Primärschlüssel zugleich** —
  ab dem zweiten Lauf sucht zFlow das Modul über sie, nicht über den lokalen
  Namen (`mM:175-177`, `mM:300-302`).

### 1.3 Band „Gluing Hybrids with TRUE BLUE - False blue"

#### `Glued by - Name`
- **Nur Blatt.** Kein `SpreadsheetEntry`; kommt im Blatt zweimal vor und wird
  beim Transponieren zu `Glued by - Name_1` (§0.2, `pGD:297`).
- **Semantik:** Personenbezogene Daten. Die Referenz kennt **keine** PDB-Property
  für den Ausführenden. In itkFlow gehört das in ein Audit-Feld, nicht in die PDB.

#### `Hybrids SNs (top, bottom)`
- **Herkunft:** Mensch/Scan. `pGD:1147-1163`: ein oder zwei Einträge,
  kommasepariert, je Eintrag eine Hybrid-SN `20USEH[0-9A-F]\d{7}` **oder** eine
  24-stellige RFID. Alternativlayout mit zwei Einzelzeilen `top Hybrid SN` /
  `bottom Hybrid SN` (`pGD:1164-1177`), vereinheitlicht in `getUnifiedHybridIDs`
  (`pGD:1568-1592`).
- **Ziel:** PDB-Assembly-Links Modul ← Hybrid, je Link **vier**
  Attachment-Properties (`dbM:167-189`). Beim Assemblieren wird der Hybrid
  gleichzeitig **zwangsweise vom `HYBRID_TEST_PANEL` gelöst**
  (`dbM:186-189`) und auf Stage `ON_MODULE` gezogen (`mM:1461`, `mM:1672-1676`).
- **Gate:** Sollzahl aus dem **PDB-`subType`**: 2 für `R0, R1,
  R3M0_HALFMODULE, R3M1_HALFMODULE`, sonst 1 (`mM:1468-1472`).
  - zu viele Einträge → Assemblierung komplett abgebrochen (`mM:1579-1583`);
  - in der DB hängt ein Hybrid, der im Blatt fehlt → Abbruch mit
    Telegram-Warnung und Aufforderung zur manuellen Disassemblierung
    (`mM:1589-1594`);
  - Blatt-Eintrag nicht in der DB auffindbar → „This is a severe problem!"
    (`mM:1636`), Hybrid übersprungen.
- **Semantik, die man falsch machen würde:** Die Reihenfolge „top, bottom" ist
  für die Assemblierung **irrelevant**, aber für die Jig-/Pickup-Zeilen
  **positionsbedeutend** — und dort wird sie nicht gegen die SNs dieser Zeile
  gematcht, sondern gegen eine aus dem *Modultyp* abgeleitete Liste von
  Hybrid-*Typen* (`tC:256-273`): R0/R1 → [H0,H1], R2 → [H0], R3M0 → [H0,H2],
  R3M1 → [H1,H3], R4M0/R5M0 → [H0], R4M1/R5M1 → [H1]. Siehe §8.17.

#### `top Hybrid weight (g) with ears`, `bottom Hybrid weight (g) with ears`
- **Nicht belegt.** Kein `SpreadsheetEntry`. Von zFlow **nicht gelesen**, geht
  **nicht** in die PDB. Vermutlich Rohwert, aus dem die „without ears"-Zeile
  gebildet wird — die Formel dafür steht nicht in der Transkription.

#### `top Hybrid ears weight (g)` / `bottom Hybrid ears weight (g)`
- **Herkunft:** Waage. `pGD:1278-1284` bzw. `pGD:1271-1277`.
- **Ziel:** `GLUE_WEIGHT`-Results `GW_T1` / `GW_T2` — **mit Vertauschung**,
  siehe unten.
- **Gate:** `top … ears` in `requiredAlways` (`pGD:1953-1960`);
  `bottom … ears` nur bei Zwei-Hybrid-Modulen (`pGD:1962`).

#### `top Hybrid weight without ears (g)` / `bottom Hybrid weight without ears (g)`
- **Herkunft:** Waage. `pGD:1235-1241` / `pGD:1221-1227`.
- **Ziel:** `GW_HYBRID1` / `GW_HYBRID2`.
- ⚠ **Vertauschungsregel** (`pGD:2043-2051`, `pGD:2072-2078`, `pGD:2104-2112`):
  - **Zwei Hybride:** *bottom* → `GW_HYBRID1`/`GW_T1`, *top* → `GW_HYBRID2`/`GW_T2`.
  - **Ein Hybrid:** *top* → `GW_HYBRID1`/`GW_T1`; die **bottom-Zeilen werden
    komplett ignoriert**.
  Für TUDO (R5M0/R5M1, ein Hybrid) heißt das: die `0,000` in den bottom-Zeilen
  landet nie in der PDB — sie geht aber sehr wohl in die **Blattformel** ein (§5).

#### `Module weight after gluing all hybrids (g)`
- **Herkunft:** Waage. `pGD:1242-1248`.
- **Ziel:** `GW_MODULE_H1` bzw. `GW_MODULE_H1H2` (`pGD:2075`). Bei Modulen
  **ohne** Powerboard außerdem Fallback-Gesamtgewicht im reduzierten Dict
  (`pGD:1868-1876`, `pGD:1884-1886`) und Eingang in `evaluateTotalModuleWeight`
  (`pGD:2036`).
- **Gate:** `requiredAlways`.
- **Semantik:** Der Codekommentar `pGD:1248-1249` zeigt, dass dieselbe
  Beschriftung im PPA- und im PPB-Blatt **unterschiedliche Bedeutung** hatte —
  eine der Zeilen wurde beim Blattwechsel umgewidmet.

#### `Modul Target weight (mg)` — **rein Blatt**
- **Herkunft:** Blattformel `WENN(C3="R0";Daten!$B$26; …)` → Spalte
  „Target weight without PB" der Tabelle **„Module Glueing with True Blue /
  False Blue"**.
- **Ziel: nirgends.** ⚠ **Es gibt in der gesamten Referenz keine Ziel- oder
  Toleranztabelle** (verifiziert per Volltextsuche über `*.py` nach
  `target`/`tolerance`/`zu viel`/`zu wenig` — Treffer nur in Stage-Vergleichen
  und in `evaluatePassProblem`). Der Wert existiert ausschließlich im Blatt und
  dient nur der Verdict-Zeile.
- **Beleg der Zuordnung aus der Transkription selbst:** die beobachteten Werte
  `151 / 164 / 135` sind exakt R5M1 / R2 / R5M0 der TrueBlue-Tabelle; die
  Toleranzen `22 / 25 / 20` ebenso. TUDO nutzt also ausschließlich das
  TrueBlue/FalseBlue-Verfahren, nicht POLARIS.

#### `Tolerance (mg)` — **rein Blatt**, doppelte Beschriftung (§0.2)

#### `all Hybrid glue weight (mg)`
- **Herkunft:** Blattformel (Rekonstruktion in §5.1).
- **Gelesen als:** `weightAllHybridGW` (`pGD:1250-1256`), Checker
  `anyNumberRegex` = **nur ganze Zahlen, Vorzeichen erlaubt**, Processor
  `convertGermanNumberToFloat`.
- **Ziel:** Result `GW_GLUE_H1` / `GW_GLUE_H1H2`, **mg → g durch ×1e-3**
  (`pGD:2053-2055`, `pGD:2076`).
- **Gate:** `requiredAlways`.

#### `Adhesive weight result hybrid (Klebegewicht Ergebnis)`
- **Herkunft:** Blattformel/Urteil.
- **Gelesen als:** `weightResultHybrid` (`pGD:1285-1289`), **kein Checker**.
- **Ziel:** die Felder `passed` und `problems` des `GLUE_WEIGHT`-Testlaufs, über
  `evaluatePassProblem` (`pGD:440-453`):

  | Zellwert | `passed` | `problems` |
  |---|---|---|
  | `OK` | **true** | false |
  | `zu viel` | **true** | **true** |
  | `zu wenig` | false | **true** |
  | *alles andere* (inkl. unerwarteter Strings) | **false** | **false** |

- **Semantik, die man falsch machen würde:**
  1. **Zu viel Kleber besteht den Test** — es ist ein „passed with problems",
     kein Fehlschlag.
  2. Der Fallback ist stumm: ein unerwarteter String erzeugt exakt dasselbe
     Ergebnis wie ein echter Fehlschlag (§8.2).
  3. Die deutschen Literale `zu viel` / `zu wenig` sind ein **harter Vertrag**
     zwischen Blatt und Code — der einzige Ort im Modul-Flow, an dem Deutsch
     produktrelevant ist.

#### `Hybrid glue date`
- **Herkunft:** Mensch. `pGD:1296-1301`, Regex `202\d-\d\d-\d\d` — **nur ISO**.
- **Ziel:** `date` des `GLUE_WEIGHT`-Laufs, **aber nur für Module ohne
  Powerboard** (`pGD:2034`); mit Powerboard gewinnt das PB-Datum (`pGD:2028`).
- **Gate — dreifach:**
  1. Ohne Datum entsteht **überhaupt kein** Glue-Weight-Dict (`pGD:1835-1839`,
     `pGD:1947-1951`) → kein `GLUE_WEIGHT`-Lauf.
  2. `getGlueDate` (`pGD:1639-1688`) liefert das **spätere** von Hybrid-/PB-Datum
     und ist der **einzige** Auslöser für den automatischen Stage-Move nach
     `GLUED` (`mM:2025-2026`).
  3. Ein deutsches Datum `13.01.2026` fällt durch den Regex → None + Telegram-Warnung.

#### `Hybrid glue sample`
- **Herkunft:** Mensch. `pGD:1352-1358`, `glueRegex` akzeptiert drei Formen:
  - alt: `DZHU-TB-0X`;
  - zFlow-Name: `TB_2025-09-26` bzw. `TB_2025-11-17_02`;
  - PDB-Glue-SN: `20USEG[A-Z]\d{7}`;
  - oder **Name + SN kommasepariert** (`TB_2025-09-26, 20USEGT0000074`).
  Processor `fixGlueEntry` (`pGD:1605-1637`) normalisiert `TB_2025-12-01-02` →
  `TB_2025-12-01_02`.
- **Ziel 1:** Attachment-Property **`HYBRID_GLUE_SAMPLE`** am Link Hybrid→Modul
  (`pGD:2161-2170` → `dbM:177-179`).
- **Ziel 2 (der eigentliche Zweck):** der **GlueHandler** liest dieselbe Zelle
  ein zweites Mal (`gH:530-576`). `splitGlueSample` (`gH:432-497`) zerlegt sie in
  `{type, date, daily_iteration, sn}` und `checkStages` (`gH:598-649`) bewegt
  daraufhin die **Glue-Komponente in der PDB**:
  `NEW → IN_USE`; `IN_USE`, aber nicht die zuletzt verwendete → `EMPTY`;
  Verfallsdatum überschritten → `EXPIRED` (Stages in `dbGlue.py:9-16`).
- **Gate:** Ohne Wert **keine** Hybrid-Assemblierung (`pGD:2137-2141` →
  `mM:1629-1632`).
- ⚠ **Das ist die Antwort auf die Frage nach `TB_2025-09-26, 20USEGT0000074`:**
  Der Name links ist die *Anmischung des Tages* (Typ + Datum + laufende Nummer),
  die SN rechts ist die *PDB-Glue-Komponente* (die Kartusche/Bipack), aus der
  angemischt wurde. `splitGlueSample` **verlangt beide Teile** und gibt None
  zurück, wenn der `XX_YYYY-MM-DD`-Teil fehlt (`gH:456-478`); alte
  `DZHU`-Notationen werden explizit übersprungen (`gH:448-452`).
  **TUDOs blanke `20USEGT0000089` erfüllt die Assemblierung, aber nicht den
  GlueHandler** — bei TUDO wird der Glue-Verbrauch also nie in der PDB
  nachgeführt. Siehe §8.12.

#### `Hybrid glue jigs used, top, bottom` — **die „zwei Werte, eine Property"-Zeile**
- **Herkunft:** Mensch (Dropdown). `pGD:1359-1365`, `twoToolRegex`, Processor
  `splitCommaIgnoreSelect` (`pGD:342-347`). DESYZ trägt hier **Farbnamen** ein
  (`orange`, `white`), TUDO PDB-Werkzeug-SNs.
- **Umrechnung** (`tC:252-302`), drei Schritte:
  1. Hybrid-Slots aus dem Modultyp ableiten (`tC:256-273`, Liste siehe oben);
  2. `unpackToolIdentifier` (`tC:168-186`): **eine einzelne Farbe wird auf alle
     Slots vervielfältigt**; sonst muss die Listenlänge exakt der Slotzahl
     entsprechen, andernfalls None;
  3. je Slot `getToolSN(f"{R}H{n}", "Hybrid jig", identifier)` (`tC:101-166`) —
     mehrdeutige Treffer → None mit Fehlermeldung (`tC:160-164`).
- **Ziel:** **Eine** Attachment-Property `JIG_HYBRID_ALIGNMENT`, deren Wert die
  mit `", "` **zusammengefügten** SNs beider Jigs ist (`tC:302`, `pGD:2163-2165`).
- ⚠ **Semantik, die man falsch machen würde:**
  1. Zwei Werkzeuge werden zu **einem String in einer Property** — die PDB
     bekommt keine Struktur, sondern eine kommaseparierte Liste.
  2. **Derselbe zusammengefügte String wird an *beide* Hybrid-Links geschrieben**
     (`putHybridOnModule` wird je Hybrid mit demselben Props-Dict aufgerufen,
     `mM:1646-1647`) — die Zuordnung „welcher Jig zu welchem Hybrid" geht in der
     PDB verloren.
  3. Beim Powerboard ist es **anders herum** (zwei getrennte Properties) — die
     Asymmetrie ist real, kein Lesefehler.
- **Gate:** Ohne Wert keine Hybrid-Assemblierung (`pGD:2143-2147`).

#### `Hybrid pickups used, top, bottom`
- Identische Mechanik, Werkzeugtyp `"Hybrid pickup tool"`, Property
  **`PICKUPTOOL_HYBRID`**, ebenfalls kommazusammengefügt (`pGD:2166-2168`).
  Gate `pGD:2149-2153`.

#### `Module jig used`
- **Herkunft:** Mensch (Dropdown, ein Wert). `pGD:1373-1379`, `ignoreSelect`.
- **Umrechnung:** `getToolSN(moduleTypeFromSpreadsheet, "Module jig", …)`
  (`tC:221-229`) — hier der **vollständige** Typ (`R5M1`), nicht der grobe.
  Im ToolConverter-Blatt wird bei Nummern mit „MJ" der letzte Token genommen
  (`tC:68-70`).
- **Ziel:** Attachment-Property `MODULE_ASSEMBLY_JIG` — **sowohl am Hybrid-Link
  als auch am Powerboard-Link** (`pGD:2169`, `pGD:2213`).
- **Gate:** Für beide Assemblierungen hart (`pGD:2155-2159`, `pGD:2192-2196`).

#### `SCRIPT: Hybrids assembled to module (in DB)`
- **Herkunft:** zFlow, `fromModules.tsv` → `hybridAssociationStatus`
  (`mM:1271`), erzeugt als **Freitext** von `associate_child` (`mM:1680-1699`).
- **Semantik:** zFlow entscheidet über `allHybridsAssociated` per **Teilstring**
  `"associated to the module"` (`mM:464-466`). Der Code fügt deshalb eigens die
  Zeile `"All {child}s associated to the module"` an, mit dem Kommentar
  „additional message for spreadsheet legacy parsing" (`mM:1692-1695`).
  Das grüne `OK` im Blatt ist also das Ergebnis eines **String-Matchings über
  Freitext**, nicht eines Booleans.

### 1.4 Band „Gluing Powerboard with TRUE BLUE - False blue"

#### `Glued by - Name` (2. Vorkommen) — **nur Blatt**, wird zu `Glued by - Name_1`.

#### `Powerboard Label`
- **Nicht belegt.** Kein `SpreadsheetEntry`. Lokale vierstellige „Hausnummer",
  reines Blatt-Artefakt.

#### `Powerboard SN`
- **Herkunft:** Mensch/Scan. `pGD:1179-1184`, Regex `20USEP[0-5]\d{7}` oder
  `-`/leer.
- **Ziel:** Assembly-Link Modul ← PWB mit vier Attachment-Properties; das PWB
  wird dabei **zwangsweise von `PWB_CARRIER` / `EC_PWB_CARRIER` gelöst**
  (`dbM:238-242`) und auf Stage `LOADED` gezogen (`mM:1477`).
- **Gate:** Sollzahl **0** für `R3M1/R4M1/R5M1_HALFMODULE` (`mM:1480-1485`);
  diese Typen werden anschließend *virtuell* als assembliert und ihr
  Reception-Test als bestanden gewertet (`mM:495-498`).
- **Semantik:** Der PWB-Reception-Status besteht aus **neun** Tests
  (`HV_ENABLE, LV_ENABLE, OF, PADID, TOGGLEOUTPUT, CONFIG, DCDC_ADJUST,
  TEMPERATURE, BER`), davon `TEMPERATURE` und `HV_ENABLE` optional, plus einer
  R2-Ausnahme, die `TOGGLEOUTPUT` aus der Liste entfernt, falls er fehlt
  (`dbPowerboard.py:25-69`). Fließt in `pureHalfModulePass` ein (`mM:957-965`).

#### `Powerboard weight (g)`
- Waage. `pGD:1257-1263` → Result `GW_PB` (`pGD:2096`). `requiredPowerboard`
  (`pGD:1964-1969`).

#### `Powerboard glue date`
- `pGD:1302-1307`, ISO oder `-`/leer. → `date` des Laufs bei PB-Modulen
  (`pGD:2028`, `pGD:1881`). **Gate:** fehlt es bei einem PB-Modul, entsteht gar
  kein Glue-Weight-Dict (`pGD:1835`, `pGD:1947`) und `getGlueDate` liefert None
  → kein automatischer Move nach `GLUED`.

#### `Powerboard glue sample`
- `pGD:1381-1387`, identische Regex/Normalisierung wie beim Hybrid.
  → Attachment-Property **`POWERBOARD_GLUE_SAMPLE`** (`pGD:2210`).
  Gate: hart für die PB-Assemblierung (`pGD:2186-2190`).
- ⚠ Der GlueHandler überspringt diese Zelle für R3M1/R4M1/R5M1 anhand des
  **lokalen Modulnamens** (`"R3M1" in moduleName` usw., `gH:556-561`) — also
  institutsspezifische Namenskonvention in der Logik (§8.19).

#### `Powerboard glue jig, pickup tool` — **die „zwei Werte, zwei Properties"-Zeile**
- `pGD:1388-1394`, `twoToolRegex` + `splitCommaIgnoreSelect`.
- **Umrechnung** (`tC:230-251`): grober Modultyp (`R5M1` → `R5`); Slot 0 unter
  Werkzeugtyp `"Powerboard jig"`, Slot 1 unter `"Powerboard pickup tool"`; eine
  einzelne Farbe wird auf beide Slots vervielfältigt.
- **Ziel:** **zwei getrennte** Properties `JIG_POWERBOARD_ALIGNMENT` und
  `PICKUPTOOL_POWERBOARD` (`pGD:2200-2212` → `dbM:222-235`).
- **Gate:** Es müssen **genau zwei** Elemente sein, sonst wird die PB-Assemblierung
  verweigert (`pGD:2200-2204`).
- Zusätzlich: `Module jig used for powerboard gluing` (`pGD:1395-1401`) ist als
  Zeile vorgesehen, existiert in den transkribierten Blättern nicht und fällt
  auf `Module jig used` zurück (`pGD:2178-2181`).

#### `SCRIPT: Powerboard assembled to module (in DB)`
- zFlow, `fromModules.tsv` → `powerboardStatus` (`mM:1272`).
  Das `N/A` entspricht dem Early-Exit „…is not required for this module type"
  (`mM:1556-1559`) für R3M1/R4M1/R5M1.

#### `Module weight after gluing powerboard AND hybrid`
- Waage. `pGD:1264-1270`. → `GW_MODULE_H1PB` / `GW_MODULE_H1H2PB` (`pGD:2098`)
  und im reduzierten Dict das **einzige** Result (`pGD:1916`). Eingang in
  `evaluateTotalModuleWeight` (`pGD:2030`).
- **Semantik:** Auch bei Modulen **ohne** PB wird zuerst diese Zeile geprüft und
  erst dann auf „Module weight after gluing all hybrids" zurückgefallen
  (`pGD:1868-1876`) — die Zeile ist also bei R5M1 nicht sinnlos.

#### `Target weight (mg)` / `Tolerance (mg)` (PB) — **rein Blatt**
- Spalten „Powerboard Target weight"/„Tolerance" der TrueBlue-Tabelle.
  Beobachtete Werte `0 / 70 / 103` = R5M1 / R2 / R5M0 ✓, Toleranzen `11 / 16`
  = R2 / R5M0 ✓. Doppelte Beschriftung (§0.2).

#### `Powerboard glue weight (...mg)`
- Blattformel (§5.2). Gelesen als `weightPowerboardGW` (`pGD:1228-1234`),
  Checker `anyNumberOrHyphenRegex` — **erlaubt führendes Minus**.
- **Ziel:** `GW_GLUE_PB` (mg→g) sowie, addiert mit dem Hybrid-Klebegewicht,
  `GW_GLUE_H1PB` / `GW_GLUE_H1H2PB` = `(hybGlue + pbGlue) × 1e-3`
  (`pGD:2082-2099`).
- ⚠ **Die negativen Werte `-9010` / `-9886` sind keine Anzeigefehler, sondern
  gültige Eingaben für den Upload.** Es gibt keinerlei Plausibilitätsprüfung auf
  dieser Zahl (§8.9). Ihr Zustandekommen ist gerade der Beleg für die
  Blattformel — siehe §5.2.

#### `Adhesive weight result powerboard`
- Gelesen als `weightResultPB` — **der Code erwartet den Titel
  `"Adhesive weight result powerboard (Klebegewicht Ergebnis)"`**
  (`pGD:1290-1294`), die Transkription zeigt ihn ohne Klammerzusatz.
  Falls das die echte Beschriftung ist: `.get` protokolliert „Could not find
  row" und liefert None (`pGD:509-513`) → das vollständige Dict wird für
  PB-Module verweigert und still auf das reduzierte heruntergestuft (§8.11).
- **Ziel:** geht in `passed = passedHybrid and passedPowerboard` ein
  (`pGD:2022`), **sein `problems` wird jedoch verworfen** (`pGD:2023`, §8.4).

#### `SCRIPT: Glue weights uploaded, stage set to GLUED`
- **Quelle: nicht direkt belegt.** In `dictPerModuleToReturn` gibt es keine
  gleichnamige Spalte. Die nächstliegenden Quellen sind `gluedStageTests`
  (`mM:696-704`, `mM:1274`) und `stage` (`mM:1267`). Die Blattformel selbst ist
  **nicht belegt**.
- **Was der Text operativ bedeutet — zwei getrennte Schritte:**
  1. `main_module` schreibt am Ende jeder Spalte die Datei
     `jsons/modules/glueWeight_<SN>.json` (`mM:1327-1329` →
     `writeGlueWeightDict`, `pGD:387-421`) — **es wird nichts hochgeladen**.
  2. Erst der **UploadManager** lädt die Datei als Testlauf hoch und bewegt dabei
     die Stage (`uM:496-544`, `uM:633-655`). Test → Stage-Mapping:
     `GLUE_WEIGHT → GLUED` (`dbM:17`, `dbM:479`).
- ⚠ **`writeGlueWeightDict` überschreibt nie.** Existiert die JSON schon, oder
  liegt eine Kopie in `jsons/modules/Uploaded/`, kehrt die Funktion sofort zurück
  (`pGD:396-407`). **Eine Korrektur eines Waagenwerts im Blatt nach dem ersten
  Upload hat damit keinerlei Wirkung mehr** (§8.8).
- Der `gluedStageTests`-Check selbst führt `GLUE_WEIGHT` als **`mayFailTests`**
  (`mM:696-704`): der Lauf muss *vorliegen*, darf aber *durchfallen*. Genau die
  Modus-Semantik, die itkFlow heute nicht ausdrücken kann (docs/10 §7.6.1).

### 1.5 Band „Measure"

Für dieses ganze Band gilt: **keine einzige Zeile ist ein `SpreadsheetEntry`.**
Alles sind Sync-Ampeln über `fromModules.tsv` bzw. über einen zweiten Kanal.

#### `Visual Inspection Photo`
- **Nicht gelesen.** Der zugehörige PDB-Test `VISUAL_INSPECTION` wird an drei
  Stellen ausgewertet: bei `HV_TAB_ATTACHED` als **optional** (`mM:683-693`),
  bei `STITCH_BONDING` als **optional** (`mM:755-766`) und bei `BONDED` als
  **if-present** (`mM:1081-1095`).
- Für **Module** verwaltet die Referenz keine Fotos. Es existiert nur eine
  **Sensor**-VI-Pipeline (`core/visualInspectionManager.py`,
  `modules/processVisualInspection.py`), die Bilder nach CERNBox/SyncAndShare
  lädt und statische HTML-Galerien aus `templates/` erzeugt.

#### `Bow Metrology`, `Bow Metrology Date`, `Metrology outcome`, `Metrology date`
- **Quelle 1 (belegt):** `fromModules.tsv` → `metrologyTests` (`mM:1275`), erzeugt
  aus `getTestPassedMsg(["MODULE_METROLOGY","MODULE_BOW"], instituteFilter=…,
  ifPresentTests=["MODULE_BOW"])` (`mM:718-727`).
  → `MODULE_METROLOGY` ist **Pflicht und muss bestehen**, `MODULE_BOW` wird
  **nur bewertet, wenn vorhanden**. Das ist die Regel, aus der „Messung fehlt!"
  entsteht.
- **Quelle 2 (belegt, zweiter Kanal):** `macros.gs:6-8, 52-67` importiert
  zusätzlich `metro_current.txt` in ein Tab `metrology_status` — erzeugt von
  `scripts/itk_check_new_metrology_results.sh`. Die DESYZ-Werte
  `Metrology_PASSED`/`Metrology_FAILED` mit Zeitstempel `30.09.2025 07:57:06`
  stammen mit hoher Wahrscheinlichkeit von dort; die konkrete Verknüpfung ist
  **nicht belegt**.
- **Ziel:** PDB-Testläufe `MODULE_METROLOGY` / `MODULE_BOW` auf Stage `GLUED`
  (`dbM:18-19`, `dbM:479-480`), hochgeladen aus Instrumenten-JSON durch den
  UploadManager. **Beide verlangen zwingend die `.txt`-Rohdatei als Attachment**
  (`uM:462-474`) — ohne sie wird der Upload mit einer Exception abgebrochen.
- **Nebenwirkung, die im Blatt nicht sichtbar ist:** ein Feld `GradeB` in der
  Metrologie-JSON setzt das PDB-Component-Flag **`GRADEB`** auf dem Halbmodul und
  propagiert es auf das Eltern-Ringmodul (`uM:657-720`; zusätzlich `mM:1210-1227`).

#### `Metrology results uploaded to DB?`
- Sync-Ampel über dieselbe Quelle. **Nicht gelesen.**

### 1.6 Band „Module stitching"

#### `Half module sibling (only R3-R5)` — **die folgenreichste Eingabezelle**
- **Herkunft:** Mensch. `pGD:1403-1408`, Regex `^20USE[3-5][LR]\d{7}$`.
- **Wirkung** (`mM:505-666`) — nur wenn der Blatt-`Module Type` **`M0`** enthält
  (`mM:512-518`); die M1-Spalte tut hier gar nichts außer ihr Elternteil
  nachzuschlagen (`mM:655-666`):
  1. Hat das M0 bereits ein Eltern-Ringmodul → M0 **und** Ringmodul werden auf
     `STITCH_BONDING` gezogen (`mM:530-543`).
  2. Sonst wird **ein neues Ringmodul registriert** (Typ `R{n}`, ohne LocalName,
     ohne HV-Tab-Jig, `mM:549-575`) — aber nur wenn *alle* Bedingungen gelten:
     `not skipRegistrations`, Stage ≠ `ON_CORE`, Modul am Institut,
     **nie** auf Stage `ON_CORE` gewesen, **kein** Eltern-Petal
     (`mM:552-562`, `dbC:826-833`, `dbM:312-323`).
  3. `putHalfModuleOnRingModule` für das M0 (`dbM:566-595`), dann M0 und Ring auf
     `STITCH_BONDING` (`mM:586-593`).
  4. Das Geschwister-M1 wird per SN gesucht, auf ein widersprechendes Elternteil
     geprüft (`mM:615-621`), demselben Ringmodul zugeordnet und ebenfalls auf
     `STITCH_BONDING` gezogen (`mM:629-646`).
- **Semantik:** **Das Eintragen einer einzigen SN registriert eine neue
  PDB-Komponente und bewegt drei Komponenten in der Stage.** Das ist die
  gewichtigste implizite Aktion des ganzen Blattes.
- **Gate:** Ohne Wert wird die Halb→Ring-Zuordnung komplett übersprungen
  (`mM:522-525`).

#### `SCRIPT: Complete module registered to DB`
- **Herkunft:** zFlow, `fromModules.tsv` → `ringModuleSN` (`mM:1270`).
  Gelesen als `parentRingModule` (`pGD:1409-1417`), aber nur, um die
  Bulk-Abfrage zu befüllen (`mM:181`, `mM:192-193`).
- **Werte:** `20USEM[3-5]\d{7}` = das registrierte Ringmodul;
  `Module is ring module` = R0/R1/R2, wo `ringModuleDBObj = moduleDBObj` gilt
  (`mM:667-668`); `not ready` = Geschwister fehlt oder Registrierung war
  gesperrt. Alle drei Sonderwerte werden von `filterNotReady` (`pGD:1487-1491`)
  zu None normalisiert.
- **Wichtig für R3 vs. R4/R5** (deckt sich mit docs/10 §7.2): für **R3**-Halbmodule
  laufen HVSTABILITY, VI und die AMAC-IVs auf dem **Halbmodul** bei
  `STITCH_BONDING` (`mM:743-818`); für **R4/R5** liegen die AMAC-IVs auf dem
  **Ringmodul** (`mM:1101-1143`). Ein R5-Ringmodul trägt selbst weder
  `MODULE_IV_PS_V1` noch `GLUE_WEIGHT` noch `MODULE_METROLOGY`.

### 1.7 Band „BONDED"

#### `Visual Inspection Photo` — nicht gelesen (siehe 1.5).

#### `Module bond date`
- ⚠ **Widerspruch.** Der Code kennt `self.bondingDate` mit dem Zeilentitel
  **`"Bonding (date)"`** und ISO-Regex (`pGD:1434-1439`). Die Transkription zeigt
  `Module bond date` mit dem deutschen Datum `13.01.2026`. **Beides** — anderer
  Titel *und* anderes Format — führt zu `None`.
- **Wirkung, wenn er gelesen würde:** `doAutomaticStageMoving` (`mM:2030-2037`)
  empfiehlt bei gesetztem Bonding-Datum `BONDED` (Ringmodul) bzw.
  `STITCH_BONDING` (Halbmodul, + `BONDED` für das Elternteil). **Es ist der
  einzige Auslöser für diese Stages im automatischen Pfad.**
- **Zusätzlich:** `automaticStageMoving` ist per Default **aus**
  (`default.conf:102`, auskommentiert) — dann läuft der ganze Zweig nie und alle
  Datumszeilen des Blattes sind wirkungslos.
- **Das PDB-seitige „bond date" kommt aus einer ganz anderen Quelle:**
  `getWirebondingTestDate` = Datum des `MODULE_WIRE_BONDING`-Testlaufs bei
  `BONDED` (`dbM:615-619`), exportiert als `wirebondingTestDate` (`mM:1098`,
  `mM:1291`).

#### `Visual Inspection FE bonds (officially optional)`
- Nicht gelesen. Entspricht `VISUAL_INSPECTION` in der **if-present**-Gruppe bei
  `BONDED` (`mM:1081-1095`) — das „officially optional" im Zeilennamen ist genau
  diese Modus-Angabe.

#### `IV after bonding`
- Nicht gelesen. Abgeleitet aus `MODULE_IV_AMAC` bei Stage `BONDED` für
  R0/R1/R2 und R4/R5-Ringmodule (`mM:1102-1110`, **Pflicht**, nicht optional)
  bzw. bei `STITCH_BONDING` für R3-Halbmodule (`mM:769-776`).
  Angezeigt über `bondedStageTests`, `tcIVTest`, `ivInfoBonded`
  (`mM:1279-1280`, `mM:1296`).
- **Zusatzwissen, das das Blatt gar nicht zeigt:** `reportIVInfo`
  (`dbM:325-429`) extrahiert aus dem Lauf die Durchbruchspannung `VBD` und den
  Strom bei −200 V, und trennt bei TC-Läufen die **letzte warme (>15 °C) von der
  letzten kalten (<−15 °C) Messung** anhand von `DCS.AMAC_NTCy`.

#### `DAQ Quick test`
- Nicht gelesen. Aggregat über die **Hybride**:
  `quickElectricalTests = [PEDESTAL_TRIM_PPA, STROBE_DELAY_PPA,
  RESPONSE_CURVE_PPA, NO_PPA]` bei Hybrid-Stage `ON_MODULE`, davon
  `STROBE_DELAY_PPA` und `NO_PPA` als **mayFail** (`dbHybrid.py:198-205`,
  `dbHybrid.py:632-646`). Zusammengeführt in `mM:848-874`, davor wird die
  `MODULE_IV_AMAC`-Zeile des Moduls gestellt (`mM:1157-1166`) → `fromModules.tsv`
  → `quickElectricalTests`.

#### `UBC Uploader: quick electrical test passed`
- **Herkunft: zFlow schreibt sie, zFlow liest sie.** Ein **Memoisierungs-Cache**,
  keine Messung.
- Gelesen als `quickElectricalTestPassedUBCUploader` (`pGD:1454-1460`),
  Regex `^ITSDAQ run (\d*): (passed|failed|missing)$`, Processor
  `parseUBCUploaderTestEntry` (`pGD:1544-1566`) → `(result, runNumber)`.
  Geschrieben als `ubcUploaderResult_quickElectricalTests` (`mM:1305`).
- **Wann sie überhaupt entsteht:** Nur wenn das Hybrid-Aggregat `failed` ist
  (`mM:900-918`). Dann `evaluationWrapper` (`mM:1750-1810`):
  1. aktuelle ITSDAQ-Run-Nummer holen (`getRunNumberOnly=True`);
  2. stimmt sie mit der im Blatt gespeicherten überein → **gespeichertes Urteil
     wiederverwenden**, nichts neu rechnen (`mM:1793-1801`);
  3. sonst `evaluateElectricalTestsModule` (`mM:1813-1975`): alle Hybride des
     Ringmoduls holen, deren letzte Testläufe aus der PDB **herunterladen**, in
     ein Temp-Verzeichnis schreiben und `ubc-lab-tools`
     `Extras.offlineEvaluation.main` darüber laufen lassen.
- **Semantik:** Ein Modul, dessen einzelne Hybride durchfallen, kann als
  **Ringmodul insgesamt bestehen** — das ist der ganze Zweck. `missing` heißt
  „der Uploader konnte sich nicht entscheiden", dann gilt das Hybrid-`failed`
  weiter (`mM:1806-1809`). Der Lauf wird abgebrochen, wenn verschiedene Hybride
  verschiedene Run-Nummern haben (`mM:1917-1929`).
- **Das ist die Antwort auf die Frage nach den UBC-Zeilen:** Sie sind eine
  *zwischengespeicherte Zweitmeinung* plus die Run-Nummer, für die sie gilt —
  ein Cache-Schlüssel im Blatt, damit ein teurer Download+Rechenlauf nicht bei
  jedem Cron-Durchlauf wiederholt wird.

#### `DAQ TC test (incl. IV)`
- Nicht gelesen. Aggregat der Hybrid-Tests
  `thermalCyclingTests = [PEDESTAL_TRIM_TC, STROBE_DELAY_TC, RESPONSE_CURVE_TC,
  NO_TC]` — **ohne Stage-Filter**, mayFail `STROBE_DELAY_TC`, `NO_TC`
  (`dbHybrid.py:216-223`, `dbHybrid.py:664-677`). Davor wird die
  `HVSTABILITY`-Zeile des Moduls gestellt (`mM:1171-1180`) → `fromModules.tsv`
  → `thermalCyclingTests`. `HVSTABILITY` ist seit 2025-10-10 ausdrücklich
  **optional** (`mM:744-753`, `mM:1120-1129`).

### 1.8 Band „TESTED"

#### `UBC Uploader: thermal cycling electrical tests passed`
- `thermalCyclingTestPassedUBCUploader` (`pGD:1461-1467`); identische Mechanik
  wie oben, Modus `ThermalCycling` (`mM:919-936`), Stage-Filter beim
  Datei-Einsammeln = keiner (`mM:1887-1889`).

---

## 2 — DESYZ-Zeilen, die TUDO nicht zeigt

| Zeile | Gelesen? | Beleg / Bedeutung |
|---|---|---|
| `HV/GND bond & Post-glue IV (officially optional)` | **nein** | kein `SpreadsheetEntry` |
| `PB-Hy bond date` | **nein** | — |
| `DAQ functional test` | **nein** | — |
| `Hybrid frontend (FE) bond` | **nein** | — |
| `Bond data (could be e.g. Row Test or something else)` | **nein** | PDB-seitig entspricht dem `MODULE_WIRE_BONDING` (`dbM:481`,`dbM:543`), hochgeladen aus `tests/uploadingTests/bonding/*.json` |
| `DAQ module test` | **nein** | — |
| `IV after bonding` (TESTED) | **nein** | siehe 1.7 |
| `Visual Inspection photo` (FINISHED MODULE) | **nein** | — |
| `Packing date (box, humi, silica, bag)` | **nein** | — |
| `Shipping date (peli case)` | **nein** | Versand kommt aus der PDB, nicht aus dem Blatt (`for info`, unten) |
| `add to this batch by zFlow` | **ja** | `moduleBatch`, `pGD:1441-1446` |
| `Finished` | formal ja, praktisch **nein** | `pGD:1419-1421` mit dem Codekommentar „# Never added to sheet"; einziger Konsument `getConfirmFailedHalfModule` (`pGD:2218-2225`) ist **defekt und wird nirgends aufgerufen** (§8.13) |
| `for info` (Shipment status) | **ja** | `shipmentInfo`, `pGD:1423-1432` |
| `Last update` / `Next update` | **ja** | `pGD:1111-1117` |
| `Comments` | **nein — nirgends** | siehe unten |

#### `add to this batch by zFlow`
- Processor mappt `"bitte wählen"` → None (`pGD:1443`).
- **Ziel:** PDB-**Batch**-Mitgliedschaft über `addToBatchByName` (`dbC:1070-1131`),
  gegen die einmal pro Lauf geholte Batch-Liste des Instituts
  (`DBInstituteBatches(…, "MODULE_BATCH")`, `mM:94-96`) und einen konfigurierbaren
  `moduleBatchExclusionDict` (`default.conf:96-99`). Für M0-Halbmodule wird das
  **Eltern-Ringmodul in denselben Batch** aufgenommen (`mM:1244-1254`).
  Rückmeldung als `addedToModuleBatches` (`mM:1273`).

#### `for info` (Shipment status)
- Muster `YYYY-MM-DD, <9 Buchstaben>, <Code>` oder `-` (`pGD:1423-1425`),
  Processor splittet an `", "` (`pGD:1493-1496`).
- **Round-Trip:** `getShipmentInfo` (`dbC:922-1001`) leitet die Versandinfo
  entweder aus den PDB-Feldern `locations` / `inTransit` /
  `shipmentDestination` ab, oder — wenn im Blatt schon etwas stand — hebt sie
  lediglich `inTransit` → `delivered` an. Zurückgeschrieben als `shipmentInfo`
  (`mM:1288`).
- ⚠ Die „9 Buchstaben" sind keine Absicht, sondern passen zufällig auf
  `inTransit` und `delivered` (§8.20).

#### `zFlow Processing: Last update` / `Next update`
- `lastUpdate` mit `dateTimeRegex` (ISO mit Millisekunden und Zeitzone),
  `nextUpdate` **ohne Checker** (`pGD:1111-1117`).
- **Round-Trip:** gelesen in `skipLoopForModule` (`mM:1398-1399`),
  neu geschrieben (`mM:1292-1293`).
- **Werte:** `On next zFlow run` bedeutet „dieses Modul ist *nicht*
  überspringbar" (`mM:1429`); `#N/A` heißt, die Nachschlage-Formel hat für dieses
  Modul keine Zeile im Overview-Tab gefunden.
- **Gate:** Ist `Last update` jünger als `reprocessFinishedComponentsEveryHours`
  **und** das Modul überspringbar, wird die gesamte Spalte übersprungen und die
  TSV-Zeile des letzten Laufs unverändert erneut ausgegeben (`mM:159-169`).
  Findet sich keine alte Zeile, wird trotzdem verarbeitet (`mM:166-173`).

#### `Comments` — **wird nie maschinell gelesen**
- Es gibt **kein** `SpreadsheetEntry` dafür, und eine Volltextsuche über die
  gesamte Referenz nach `Comment`/`comment` liefert **keinen einzigen**
  Konsumenten der Blattzelle.
- **Die Gegenrichtung existiert:** die *PDB-Kommentare* der Komponente werden
  exportiert — `commentsFromDB` und `ringModuleCommentsFromDB`, mit `;`
  verkettet (`mM:1309-1314`, `dbC:886-891`).
- **Bewertung:** Die drei zitierten Freitexte („10 consecutive bad strips (more
  than 8)", „PB-shifting spacer was damaged … 600 microns too close", „MASSIVE
  tilt in lower hybrid (+- 1mm!!)") sind Ausfallursachen im Klartext, die
  **nirgendwo sonst existieren** und heute niemand auswertet.

---

## 3 — Referenzblatt „Daten"

| Block | In der Referenz? | Befund |
|---|---|---|
| Hybrid → Chipbestückung (`R0H0` 8/1 … `R5H1` 9/2) | **indirekt** | zFlow liest die *Ergebnisse* im **Hybrid**blatt als `amount ABC` / `amount HCC` (`pGD:687-700`) und benutzt sie **nur**, um die Vollständigkeit der Chip-SN-Liste zu prüfen (`checkIfChipsComplete`, `pGD:877-888`), bevor ASICs assembliert werden. **Keine Klebe-Verwendung im Code.** |
| Chip → UV-Klebemenge (ABC 0,0042 g ± 0,00025; HCC 0,0015 g ± 0,0001) | **nein** | rein Blatt |
| `Klebeziel = (B2*4.2)+(C2*1.5)` | **nein** | ABC-Anzahl × 4,2 mg + HCC-Anzahl × 1,5 mg — konsistent mit der Tabelle darüber. Ziel für `ASIC_GLUE_WEIGHT` (Hybridblatt), nicht für das Modul. |
| `Tolerance = (B2*0.25)+(C2*0.1)` | **nein** | konsistent mit 0,25 mg / 0,1 mg |
| `Klebegewicht = (C23-(C22-C21)-C20)*1000` | **strukturell ja** | Das ist die **Hybrid-ASIC**-Formel. Zeilenzuordnung über die Kommentare in `pGD:1011-1015`: C20 = `Hybrid Bare weight (g) with ears`, C21 = `Empty tray weight (g)`, C22 = `Asics with Tray weight (g)`, C23 = `Hybrid with Asics (and ears) weight (g)`. Der Code rechnet dieselbe Kette: `gwAsic = C22 − C21`; `HTG = C23 − gwAsic`; damit ist `HTG − C20` genau der Formelausdruck (`pGD:1017-1023`). **Übereinstimmung ✓** — aber der Code **rechnet den Klebewert nicht nach**, er übernimmt ihn aus der Blattzelle `Hybrid X glue weight (mg)` (`pGD:1011`, `pGD:1036`). Ein Konsistenzcheck wäre trivial und findet nicht statt. |
| Modul-Zieltabellen POLARIS / TrueBlue-FalseBlue | **nein** | ⚠ existiert nirgends im Code (§5, §8.1) |
| Mischungsrechner Hardener/Epoxy | **nein** | rein Blatt |
| „True Blue - Klebemenge für ca. 3 Klebungen" | **nein** | rein Blatt, Materialdisposition |
| „Klebemengenkorrektur fuer Klebeprogramme" (Line Speed) | **nein** | §6 |
| Dropdown-Listen Hybridjig / Chip Tray / PickUpTool (4,5,7,8 …) | **indirekt** | Diese Zahlen sind genau die `number`-Spalte des ToolConverter-Blattes (`tC:42-74`); `getToolSN` löst eine blanke Zahl darüber in eine `20USERT…`-SN auf (`tC:121-144`). |

---

## 4 — Was zFlow aus dem Blatt macht: das PDB-Schreibprofil eines Moduls

Kompakt, weil eine Neuimplementierung genau diese Menge treffen muss.

| Art | Konkret | Beleg |
|---|---|---|
| **Registrierung** | `MODULE`, Typ `R{n}` oder `{R#M#}_HALFMODULE`, Properties `LOCALNAME` + `HV_TAB_ASSEMBLY_JIG` | `dbM:72-109`, `mM:353-371` |
| **Registrierung (implizit)** | Ringmodul `R{n}` ohne LocalName, ausgelöst durch `Half module sibling` | `mM:549-575` |
| **Component-Property** | `HV_TAB_ASSEMBLY_JIG` (laufend abgeglichen) | `mM:396-399`, `dbC:1254-1268` |
| **Component-Flag (Sensor)** | `PASSED_MODULE_RECEPTION` / `FAILED_MODULE_RECEPTION` | `dbSensor.py:117-171` |
| **Component-Flag (Modul)** | `GRADEB`, propagiert Halbmodul → Ringmodul | `uM:657-720`, `mM:1210-1227` |
| **Assembly Sensor→Modul** | Property `HV_TAB_SHEET` | `dbM:111-151` |
| **Assembly Hybrid→Modul** | Properties `JIG_HYBRID_ALIGNMENT`, `PICKUPTOOL_HYBRID`, `HYBRID_GLUE_SAMPLE`, `MODULE_ASSEMBLY_JIG`; Disassembly von `HYBRID_TEST_PANEL` | `dbM:153-201` |
| **Assembly PWB→Modul** | Properties `JIG_POWERBOARD_ALIGNMENT`, `PICKUPTOOL_POWERBOARD`, `POWERBOARD_GLUE_SAMPLE`, `MODULE_ASSEMBLY_JIG`; Disassembly von `PWB_CARRIER`/`EC_PWB_CARRIER` | `dbM:203-254` |
| **Assembly Halbmodul→Ringmodul** | keine Properties | `dbM:566-595` |
| **Testlauf** | `GLUE_WEIGHT` (der einzige, den das Modulblatt selbst erzeugt) | `pGD:1922-2114`, `pGD:1822-1920` |
| **Stage-Moves** | Hybrid → `ON_MODULE`; PWB → `LOADED`; Modul → `GLUED` / `STITCH_BONDING` / `BONDED` / `TESTED` / `FINISHED` / `FAILED`; Glue → `IN_USE`/`EMPTY`/`EXPIRED` | `mM:1461`,`mM:1477`,`mM:1978-2099`,`mM:1188-1208`,`gH:598-649` |
| **Batch** | Modul (und Ringmodul) in `MODULE_BATCH` | `dbC:1070-1131`, `mM:1240-1254` |
| **Attachment** | nur über den UploadManager (`.txt`-Rohdatei zum Testlauf, Titel „RAW file") | `uM:745-773` |

---

## 5 — Die Klebegewichtskette, Ende zu Ende

### 5.1 Hybridschritt (im Blatt)

Waagenwerte: `S` = *Sensor weight with tab*, `H_top` / `H_bot` = *Hybrid weight
without ears*, `M_H` = *Module weight after gluing all hybrids*.

```
all Hybrid glue weight [mg] = (M_H − S − H_top − H_bot) × 1000
```

**Status: rekonstruiert, nicht in der Referenz.** Die Formel steht nicht in der
Transkription (der dortige „Beispiel Klebegewicht" ist die Hybrid-ASIC-Formel,
§3) und es gibt sie im Code nicht. Belegt wird sie durch die Zahlen der
Transkription selbst:

| Rechnung | Ergebnis | in der Zeile enthalten? |
|---|---|---|
| 9,3819 − 7,0162 − 2,2330 − 0 | 0,13270 → **133** | ✓ (`133`) |
| 9,010 − 5,773 − 3,082 − 0 | 0,15500 → **155** | ✓ (`155`) |

Ziel und Toleranz kommen aus der Tabelle **„Module Glueing with True Blue /
False Blue"**, Spalten *Target weight without PB* / *Tolerance*, ausgewählt über
`Module Type`:

| Module Type | Ziel [mg] | Tol [mg] | in der Transkription beobachtet |
|---|---|---|---|
| R5M1 | 151 | 22 | ✓ |
| R2 | 164 | 25 | ✓ |
| R5M0 | 135 | 20 | ✓ |

Urteil: `OK`, wenn `|glue − target| ≤ tolerance`; `zu viel` darüber, `zu wenig`
darunter. **Der Vergleichsoperator selbst ist nicht belegt** — er ist aus den
beiden Beispielen konsistent (155 gegen 164±25 → OK; 133 gegen 151±22 → OK).

Die Spalte **„Total Glue Target weight"** der Tabelle wird von keiner Zeile des
Modulblattes benutzt (es gibt keine Gesamt-Zeile).

### 5.2 Powerboardschritt (im Blatt)

```
Powerboard glue weight [mg] = (M_all − M_H − W_PB) × 1000
```
mit `M_all` = *Module weight after gluing powerboard AND hybrid*,
`W_PB` = *Powerboard weight (g)*.

**Diese Formel ist durch ihren eigenen Fehlermodus belegt:** Die beobachteten
Werte `-9010` und `-9886` sind exakt `−1000 × 9,010` und `−1000 × 9,886`, und
`9,01` sowie `9,886` stehen beide in der Zeile *Module weight after gluing all
hybrids (g)*. Sind also `M_all` und `W_PB` leer (= 0), bleibt genau `−1000 × M_H`
übrig. ✓

Ziel/Toleranz aus derselben Tabelle, Spalten *Powerboard Target weight* /
*Tolerance*: R5M1 0/0, R2 70/11, R5M0 103/16 — exakt die beobachteten Werte ✓.

### 5.3 Was zFlow daraus baut

`getGlueWeightDict` (`pGD:1690-1723`) versucht **zuerst** das vollständige, dann
das reduzierte Dict:

| | **complete** (`pGD:1922-2114`) | **spartanic** (`pGD:1822-1920`) |
|---|---|---|
| Bedingung | alle Pflichtfelder gefüllt | nur Datum(e) + Gesamtgewicht |
| `passed` | **aus dem Blatt-Urteil**: `passedHybrid and passedPowerboard` | **aus einem ±3σ-Fenster** auf das Gesamtgewicht (`evaluateTotalModuleWeight`) |
| `problems` | `problemsHybrid` (PB verworfen, §8.4) | **immer `True`** |
| `properties` | `GW_METHOD="dispenser"`, `GLUE_METHOD_V_H1/H2/PB="-"` | identisch |
| `results` | `GW_SENSOR`, `GW_HYBRID1/2`, `GW_T1/T2`, `GW_MODULE_*`, `GW_GLUE_*`, `GW_PB`, `GW_GLUE_PB` | **nur** `GW_MODULE_H1[H2][PB]` |
| `date` | PB-Datum bei PB-Modulen, sonst Hybrid-Datum | dito |

`evaluateTotalModuleWeight` (`pGD:1759-1820`) prüft das Gesamtgewicht gegen
**hartcodierte** Mittelwerte/Standardabweichungen je SN-Zeichenpaar (M0 13,64 ±
0,07; M1 14,71 ± 0,09; M2 11,55 ± 0,07; 3R 14,46; 3L 10,55; 4R 12,24; 4L 9,39;
5R 12,74; 5L 9,88), Warnung ab 2σ (nur Log + Telegram), Fehlschlag ab 3σ.
Kommentar im Code: „Last updated: 2026-04-14", abgeleitet aus DESYZs eigenen
ersten Modulen.

Danach: `writeGlueWeightDict` → `jsons/modules/glueWeight_<SN>.json` (einmalig,
§8.8) → UploadManager → Testlauf `GLUE_WEIGHT` auf Stage `GLUED`.

### 5.4 Urteil zur Frage „stimmen Blatt und Code überein?"

**Nein — sie überschneiden sich gar nicht.** Das Blatt besitzt die gesamte
Fachlogik (Zielwerte, Toleranzen, Vergleich, Urteil), der Code besitzt keinen
einzigen Zielwert und übernimmt das Urteil als Zeichenkette. Die einzige
Prüfung, die der Code *selbst* anstellt, ist ein davon **unabhängiges**
Gesamtgewichtsfenster, das in einem Zweig sogar das Blatt-Urteil vollständig
**ersetzt**. Die Widersprüche im Detail stehen in §8.1–§8.9.

---

## 6 — Die Line-Speed-Korrektur

**Arithmetik bestätigt** — aus den Zahlen der Transkription:
`17 × 100/84 = 20,238095…` ✓ und `3,5 × 100/84 = 4,166666…` ✓.
Also `neu = alt × (IST / soll)`.

**Physikalisch plausibel und selbsterklärend:** Ein Dispenser legt eine Raupe
entlang einer Bahn; die aufgetragene Menge pro Wegstrecke ist umgekehrt
proportional zur Verfahrgeschwindigkeit. Wurde zu viel Kleber aufgetragen
(IST > soll), muss die Geschwindigkeit im Verhältnis `IST/soll` **erhöht**
werden. Die Formel korrigiert also das Roboterprogramm der nächsten Klebung
anhand der gewogenen letzten.

**In der Referenz nicht belegt.** Eine Volltextsuche über `references/zeuthenflow`
nach `line speed`, `Klebemenge`, `Klebeprogramm`, `dispens` liefert genau zwei
Treffer, beide die Konstante `"GW_METHOD": "dispenser"` (`pGD:1910`, `pGD:2066`).
zFlow kennt die Korrektur nicht, rechnet sie nicht, lädt sie nicht hoch und
liest die zugehörigen Zellen nicht.

**Zwei Zahlen, nicht eine:** Die Zeile hat `Line Speed 1` und `Line Speed 2`
(17 und 3,5), beide mit demselben Faktor skaliert — vermutlich zwei
Bahnabschnitte oder zwei Durchgänge desselben Programms. Welche das sind, ist
**nicht belegt**.

**Der eigentliche Befund:** Es wird **nirgends festgehalten, mit welcher
Line-Speed ein konkretes Modul geklebt wurde.** Weder das Blatt (die
Korrekturtabelle hat eine einzige Zeile mit einem Dropdown) noch die PDB
(`GW_METHOD` ist die Konstante `"dispenser"`, `GLUE_METHOD_V_H1/H2/PB` sind
konstant `"-"`). Die Rückkopplung ist ein **offener Regelkreis ohne
Rückverfolgbarkeit** — das ist die Lücke, die itkFlow schließen könnte, indem
es je Klebung Programm + Parameter mitschreibt.

---

## 7 — Was die Referenz tut, das die Blätter nicht zeigen

Die Blätter sind eine Oberfläche über einem deutlich größeren System.

**Ingestion (UploadManager, `core/uploadManager.py`)** — der zweite, im
Modulblatt unsichtbare Datenpfad:
- Watched-Folder über konfigurierbare Globs (`default.conf:133-148`);
- Komponentenauflösung aus Dateiname *oder* JSON, per SN-Präfix oder lokalem
  Namen (`uM:22-56`, `uM:287-373`), inkl. Umbenennung von `COMPONENT_ID` auf die
  echte SN **in Datei und Inhalt** (`uM:375-419`);
- Attachment-Pflicht für `ATLAS18_IV_TEST_V1`, `MODULE_METROLOGY`, `MODULE_BOW`,
  `PULL_TEST` (`uM:462-474`);
- Duplikatserkennung zweistufig: gleicher Typ+Datum in der DB **und** gleiche
  Datei in `Uploaded/` (`uM:614-631`);
- **retroaktive Uploads**: steht die Komponente schon über der Zielstage, wird
  der Lauf mit `retroactiveStage` hochgeladen statt die Stage zurückzudrehen
  (`uM:520-544`);
- TC-Tests auf Halbmodul/Hybrid ziehen das **Eltern-Ringmodul** nach `TESTED`
  (`uM:546-587`);
- `GRADEB`-Flag aus der Metrologie-JSON (`uM:657-720`);
- verarbeitete Dateien wandern nach `Uploaded/`.

**GlueHandler (`core/glueHandler.py`)** — Verbrauchsmaterialverwaltung:
registriert Kleber aus einem eigenen Blatt als PDB-Komponenten (`gH:325-430`),
legt fehlende `GLUE_BATCH`es an (`gH:361-371`), leitet das Verfallsdatum als
Herstelldatum + 365 Tage ab (`gH:310-323`) und führt die Glue-Stages anhand der
tatsächlichen Nutzung in den Modulblättern nach.

**ShipmentManager**: PDB-Sendungen ein/aus, je Status, als TSV
(`core/shipmentManager.py:36-92`).

**OverviewMaker**: Bestandsübersicht aller Sensoren/Hybride/Powerboards am
Standort mit Reception-Status, Elternmodul und — für Hybride — der Angabe, ob
Kategorie-B-Chips verbaut sind (`core/overviewMaker.py:86-142`).

**Sensor Visual Inspection**: Bild-Upload nach CERNBox/SyncAndShare und
Erzeugung statischer HTML-Galerien aus `templates/`
(`core/visualInspectionManager.py`, `modules/processVisualInspection.py`).

**EmailReminders**: Erinnerungsmails nach einem Wochenplan aus einem weiteren
Blatt (`core/emailReminderManager.py`) — laut `default.conf:195` für den
Reinigungsdienst.

**Hybridseite (`core/hybridManager.py`, `ProcessHybridSheet`)**: ASIC-Zuordnung
über Batch + Basis-SN mit numerischer Expansion (`20USGAAYYYYXXX` →
`…001`, `pGD:930-993`), Panels und Panel-Positionen, `ASIC_GLUE_WEIGHT`.

**Betrieb**: Datei-Cache der PDB (`core/cacheUpdater.py`; im Original ~175 MB,
docs/01 §2), Backups der heruntergeladenen Blätter als Disaster Recovery
(`core/backupManager.py`), Telegram/Mattermost-Alarme über
`logger.telewarning`, Zeitfenster je Sektion (`main.py:20-43`), sowie die
Sicherungsschalter `--skipRegistrations`, `--maxNumberOfEntriesToProcess`,
`--forceProcess`, `--ignoreInstituteCheck` (`main.py:47-66`, `main.py:185-188`).

**Fachliche Prüfungen, die im Blatt nirgends auftauchen**: Eltern-Petal
(`dbM:312-323`), „war je auf `ON_CORE`" (`dbC:826-833`), `inTransit`,
Executive-Rechte, PDB-Kommentare, IV-Kennwerte `VBD` / I@−200 V mit
Warm-Kalt-Trennung (`dbM:325-429`).

---

## 8 — Widersprüche zwischen Blatt und Referenzcode

Nach Tragweite sortiert. Jede Zeile ist ein konkretes Risiko für eine
Neuimplementierung.

1. ⚠⚠⚠ **Die gesamte Klebe-Fachlogik existiert nur im Blatt.** Zielwerte,
   Toleranzen, Verfahrensunterscheidung POLARIS ↔ TrueBlue und der Vergleich
   selbst kommen in `references/zeuthenflow` **nicht vor** (Volltextsuche
   negativ). zFlow liest nur Zahl und Urteilstext. Wer das Blatt abschaltet,
   ohne diese Tabellen zu portieren, verliert das Urteil vollständig.
2. ⚠⚠ **Stummer Fehlerfall im Urteil.** `evaluatePassProblem` (`pGD:440-453`)
   initialisiert `(False, False)` und gibt das für **jeden** nicht erkannten
   String zurück — ununterscheidbar von einem echten `zu wenig`-Fehlschlag,
   nur ohne `problems`-Flag.
3. ⚠⚠ **`zu viel` gilt als bestanden** (`pGD:446-448`): zu viel Kleber wird als
   `passed: true, problems: true` in die PDB geschrieben. Fachlich vertretbar,
   aber für jeden, der „passed" liest, überraschend.
4. ⚠⚠ **Das `problems`-Flag des Powerboards wird verworfen** — mit dem
   Selbstzweifel des Autors im Code: `problems = problemsHybrid  ## soll das
   so????? sollte hier nicht problemHybrid or problemPowerboard stehen …`
   (`pGD:2023-2024`).
5. ⚠⚠ **Zwei völlig verschiedene Pass-Kriterien** je nachdem, wie vollständig
   das Blatt ausgefüllt ist: Blatt-Urteil (complete) vs. ±3σ-Gewichtsfenster
   (spartanic, `pGD:1907`). Das reduzierte Dict setzt zusätzlich **immer**
   `problems: True` (`pGD:1908`).
6. ⚠ **`evaluateTotalModuleWeight` ist institutsspezifisch hartcodiert**
   (`pGD:1759-1799`): neun Mittelwert/Sigma-Paare, Schlüssel = SN-Zeichen 5-6,
   Stand 2026-04-14, gewonnen aus DESYZs ersten Modulen. Verstößt frontal gegen
   itkFlows Regel „kein Institut-Hardcoding" (CLAUDE.md §4).
7. ⚠ **Zwei Datumslogiken für dieselbe Sache.** `getGlueDate` (`pGD:1639-1688`)
   berechnet korrekt das *spätere* von Hybrid- und PB-Datum, wird aber **nur**
   fürs Stage-Moving benutzt (`mM:1338`). Der hochgeladene Testlauf nimmt
   unbedingt das **PB-Datum** — mit Codekommentar „should be latest of either …
   set to powerboard date for now" (`pGD:2026-2028`).
8. ⚠⚠ **Korrekturen nach dem ersten Upload verpuffen.** `writeGlueWeightDict`
   kehrt sofort zurück, wenn `glueWeight_<SN>.json` existiert oder in
   `Uploaded/` liegt (`pGD:396-407`). Ein im Blatt korrigierter Waagenwert
   erzeugt nie eine neue JSON.
9. ⚠ **Keine Plausibilitätsprüfung auf dem PB-Klebegewicht.** `-9010` passiert
   den `anyNumberOrHyphenRegex` (`pGD:1230`) und landet als `GW_GLUE_PB =
   -9,010 g` in der PDB. Das Blatt färbt die Zelle rot, der Code sieht das nicht.
10. ⚠⚠ **`Module bond date` ↔ `Bonding (date)`.** Titel und Datumsformat
    weichen ab (`pGD:1434-1439` erwartet ISO). Wenn die Transkription die echte
    Beschriftung zeigt, wird **nie** automatisch nach `BONDED`/`STITCH_BONDING`
    bewegt (`mM:2030-2037`). **Vom Owner am realen Blatt zu prüfen.**
11. ⚠ **`Adhesive weight result powerboard`**: Der Code erwartet den Zusatz
    `" (Klebegewicht Ergebnis)"` (`pGD:1291`). Fehlt er, wird das vollständige
    Dict für PB-Module still auf das reduzierte heruntergestuft.
12. ⚠⚠ **TUDOs `Hybrid glue sample` ist für den GlueHandler unbrauchbar.**
    Eine blanke `20USEGT0000089` erfüllt die Assemblierung, aber
    `splitGlueSample` verlangt den `XX_YYYY-MM-DD`-Teil und liefert sonst None
    (`gH:456-478`) → bei TUDO wird **kein** Glue-Verbrauch in der PDB
    nachgeführt (Stage bleibt `NEW`).
13. ⚠ **`Finished` ist im Code tot.** Kommentar „# Never added to sheet"
    (`pGD:1421`), obwohl DESYZ die Zeile hat. Der einzige Konsument
    `getConfirmFailedHalfModule` (`pGD:2218-2225`) vergleicht ein
    `SpreadsheetEntry`-**Objekt** mit `row.keys()` (Strings) → **immer False** —
    und wird ohnehin **nirgends aufgerufen** (Volltextsuche). Dasselbe gilt für
    das Hybrid-Pendant (`pGD:811` setzt `hybridFinishedFlag = ""`, `pGD:903`
    ruft `.rowTitle` darauf auf → `AttributeError`). Die FINISHED/FAILED-
    Entscheidung fällt ausschließlich aus PDB-Testergebnissen (`mM:1182-1208`).
14. ⚠ **Doppelte Zeilenbeschriftungen** `Tolerance (mg)` und `Glued by - Name`
    werden still zu `…_1` (`pGD:297-310`). Heute folgenlos, weil beide ungelesen
    sind — aber eine Falle für jeden Importeur.
15. ⚠ **Asymmetrie Jig/Pickup:** Hybrid = **zwei Werte in einer** Property
    (`JIG_HYBRID_ALIGNMENT`, `PICKUPTOOL_HYBRID`, mit `", "` verkettet,
    `pGD:2163-2168`), Powerboard = **zwei getrennte** Properties
    (`JIG_POWERBOARD_ALIGNMENT` + `PICKUPTOOL_POWERBOARD`, `pGD:2209-2214`).
16. ⚠ **Zuordnung Jig ↔ Hybrid geht verloren.** Derselbe verkettete String wird
    an **beide** Hybrid-Links geschrieben (`mM:1646-1647` ruft
    `putHybridOnModule` je Hybrid mit demselben Dict).
17. ⚠ **Die Slots „top, bottom" werden nicht gegen die SN-Zeile gematcht**,
    sondern gegen eine aus dem *Modultyp* abgeleitete Hybrid-*Typen*-Liste
    (`tC:256-273`). Eine einzelne Farbe wird auf alle Slots vervielfältigt
    (`tC:177-178`).
18. ⚠ **Drei Quellen für „hat Powerboard / hat zwei Hybride":** SN-Zeichen 5-6
    (`pGD:1725-1757`), PDB-`subType` (`mM:1468-1485`), Blatt-`Module Type`
    (`mM:476`). Zusätzlich hat `getGlueDate` eine **vierte, eigene** Kopie der
    PB-Logik (`pGD:1649-1652`).
19. ⚠ **Institutsnamen in der Logik:** Der GlueHandler entscheidet „kein
    PB-Kleber" daran, ob der **lokale Modulname** „R3M1"/„R4M1"/„R5M1" enthält
    (`gH:556-561`).
20. **`for info`-Regex verlangt genau 9 Buchstaben** für den Status
    (`pGD:1423-1425`) — passt zufällig auf `inTransit`/`delivered`.
21. **Jeder Formatfehler ist stumm + laut zugleich:** `.get` liefert None
    (Ablauf geht weiter), feuert aber eine Telegram-Warnung (`pGD:540-552`).
    Daten gehen verloren, ohne dass irgendein Gate greift.
22. **Zeilensuche über exakte Beschriftung** (`pGD:509-513`): Umbenennen einer
    Zeile im Blatt deaktiviert die zugehörige Logik lautlos.
23. **`GLUE_WEIGHT` ist bei `dbHybrid.stageOfTest` auf Stage `GLUED` gemappt**
    (`dbHybrid.py:169`) — eine Stage, die es in `DBHybrid.stageList`
    (`dbHybrid.py:150-164`) **nicht gibt**. Für Hybride führt ein
    `GLUE_WEIGHT`-Upload damit in `doesStageExist` → Fehler.

---

## 9 — Konsequenzen für die Modul-Detailseite in itkFlow

Kein Design, nur die Randbedingungen, die aus §1–§8 folgen.

**9.1 Die vier Zellenklassen (§0.5) sind vier verschiedene UI-Elemente.**
Eingaben sind Formularfelder mit Einheit und Format; Ableitungen sind
schreibgeschützte, berechnete Anzeigen mit sichtbarer Formel; Sync-Ampeln sind
Statuszeilen mit Herkunft (welcher Testtyp, welche Stage, welcher Modus); „nur
Blatt" sind Notizfelder. Heute sehen alle vier gleich aus — genau das macht das
Blatt so fehleranfällig.

**9.2 Die Zieltabellen müssen in das Institutsprofil**, nicht in den Code
(CLAUDE.md §4). Nötige Achsen, alle drei belegt: *Modultyp* × *Klebeverfahren*
(POLARIS / TrueBlue-FalseBlue) × *Schritt* (Hybrid / Powerboard). Für Hybride
zusätzlich *Chipbestückung* (ABC/HCC-Anzahl × Menge je Chiptyp). Ebenfalls ins
Profil gehören die `evaluateTotalModuleWeight`-Fenster (§8.6) — als
institutsspezifische Referenzwerte, nicht als Konstanten.

**9.3 Vier Requirement-Modi, nicht einer.** zFlow kennt `required`, `mayFail`
(`GLUE_WEIGHT`), `optional` (`VISUAL_INSPECTION`, `HVSTABILITY`) und `ifPresent`
(`MODULE_BOW`, `MODULE_WIRE_BONDING`), dazu Either-Or-Gruppen
(`MODULE_IV_AMAC | MODULE_IV_AMAC_TC`). Das ist exakt die Lücke, die
docs/10 §7.6 bereits benannt hat — dieses Dokument liefert dafür die
zeilenweisen Belege.

**9.4 Kind-Evidenz ist Pflicht, nicht Kür.** `Half module sibling` (§1.6) zeigt
konkret, warum: ein R5-Ringmodul entsteht als Nebenwirkung einer Eingabe am M0
und ist erst fertig, wenn **beide** Halbmodule fertig sind
(`bothHalfModulesPass` + `ringModulePass`, `mM:1004-1184`).

**9.5 Vier Dinge, die itkFlow besser machen kann als das Blatt:**
- die Klebe-Rechnung serverseitig aus den Rohwerten ableiten **und** den
  Zielwert samt Verfahren mitprotokollieren (statt eine Formel im Blatt);
- Korrekturen erlauben (§8.8: heute unmöglich);
- die Jig-Zuordnung pro Hybrid erhalten (§8.15/§8.16) — die PDB-Property bleibt
  zwar kommaverkettet, aber itkFlow kann intern die richtige Struktur führen;
- die Line-Speed-Rückkopplung schließen (§6): festhalten, mit welchem Programm
  und welcher Geschwindigkeit ein konkretes Modul geklebt wurde.

**9.6 `Comments` verdient ein erstklassiges Feld.** Es ist der einzige Ort, an
dem Ausfallursachen im Klartext stehen, und wird heute von keiner Maschine
gelesen (§2).

---

## 10 — Offene Punkte (nur der Owner oder ein Blick ins echte Blatt klärt sie)

1. Heißt die Zeile im echten Blatt `Module bond date` oder `Bonding (date)`, und
   welches Datumsformat steht darin? Davon hängt ab, ob automatisches
   Stage-Moving nach `BONDED` je funktioniert hat (§8.10).
2. Ist `automaticStageMoving` bei TUDO/DESYZ überhaupt aktiv
   (`default.conf:102`)? Wenn nein, sind sämtliche Datumszeilen wirkungslos.
3. Warum ist `HV tab sheet SN` im TUDO-Ausschnitt leer, obwohl sie die
   Sensor-Assemblierung hart blockiert (§1.2)?
4. Bewusste Entscheidung oder Versehen, dass TUDO im `Hybrid glue sample` nur
   die SN ohne Anmischnamen führt — mit der Folge, dass der Glue-Verbrauch nie
   nachgeführt wird (§8.12)?
5. Was genau sind `Line Speed 1` und `Line Speed 2` (zwei Bahnabschnitte? zwei
   Durchgänge?), und wo wird die korrigierte Zahl eingetragen (§6)?
6. Die exakten Blattformeln der `SCRIPT:`-Zeilen und der `Measure`-Zeilen liegen
   nicht in der Referenz; sie sind nur aus dem Overview-Tab ableitbar. Falls
   nötig, aus dem echten Blatt abschreiben.
7. Verwendet TUDO ausschließlich TrueBlue/FalseBlue (die drei beobachteten
   Zielwerte legen das nahe, §5.1) oder gibt es POLARIS-Module?

---

## Roadmap-Einordnung

Vorarbeit zur **Modul-Detailseite** (docs/02, docs/05) und Ergänzung zu
`docs/10-itk-domain-reference.md` §7: dort wurde das Stage-/Testmodell aus den
**Daten** hergeleitet, hier die Zeilen-Semantik aus dem **Referenzcode**. Beide
zeigen unabhängig voneinander dieselben vier Lücken (Requirement-Modi,
Either-Or-Gruppen, Bauteilfamilien, Kind-Evidenz). Roadmap-Punkt:
„Stage-Move-Strecke schließen" bzw. Phase 3 (Assembly-Wizards) in
`docs/04-roadmap.md`. Reines Recherchedokument — kein Code, kein Vertrag geändert.

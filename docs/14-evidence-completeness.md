# Vollständigkeit des Test-Evidence-Spiegels

> **Besitzt:** den Read-Vertrag dafür, welche Komponenten und Testläufe ein
> vollständiger Sync von itkView umfasst. Stage-Moves und Gate-Entscheidungen
> gehören nicht zu itkView; die PDB bleibt unverändert die Source of Truth.
>
> **Verwandt:** `09-pdb-production-strategy.md` für den PDB-Leseweg,
> `12-attachments-and-images.md` für Attachment-Bytes und
> `10-itk-domain-reference.md` für die Komponentenfamilien.

## Problem

Der Komponenten-Sync spiegelt nicht nur Bauteile, die einem Institut gehören
oder dort stehen. Er holt zusätzlich verbaute Teile nach, weil ein TUDO-Modul
beispielsweise einen CERN-Sensor und einen UT-Hybrid an einem dritten Standort
enthalten kann. Dieser Nachholweg lief bisher jedoch nur **eine Ebene**: Ein
nachgeladener Halbmodul- oder Hybrid-Datensatz wurde nicht erneut auf weitere
Kinder untersucht. Tiefer liegende Bauteile konnten deshalb bereits vor dem
Evidence-Sync vollständig aus dem lokalen Mirror fehlen.

Der Evidence-Sync wiederholte danach zusätzlich den engeren Filter

```text
owner == institute OR location == institute
```

und wandte eine statische Komponenten-Typenliste an. Dadurch konnten selbst
bereits lokal vorhandene, institutsfremde Assembly-Nachfahren erneut aus dem
Evidence-Scope fallen. Besonders sichtbar war das bei gestitchten Modulen,
deren Sensoren, Powerboards und Hybride unter einem Halbmodul liegen. ABC-,
HCC-, AMAC- und künftige PDB-Typen konnten außerdem still aus dem Standard-Sweep
verschwinden.

## Vertrag ab 2026-08-29

Vollständigkeit wird in zwei aufeinanderfolgenden Read-Schritten hergestellt.

### 1. Vollständiger Komponenten-Snapshot

1. Die beiden autoritativen PDB-Listings bleiben unverändert: alle Komponenten,
   die dem Institut gehören, und alle Komponenten, die dort stehen.
2. Von allen darin genannten lebenden Assembly-Kindern wird die PDB-Hierarchie
   **rekursiv und breadth-first** weiterverfolgt, nicht nur einen Hop tief.
3. Eigentümer, Standort und Komponententyp eines Nachfahren begrenzen diesen
   Traversal nicht.
4. Fehlende oder `null` Relationship-States gelten wie im bestehenden
   Parent-Link-Parser als lebend; explizit nicht-`ready` markierte Links werden
   nicht als aktuelle Assembly übernommen.
5. Ein Lookup ohne Objekt-ID wird an die angefragte, bereits bekannte ID
   gebunden. Abweichende IDs, doppelt verwendete Seriennummern oder ein nicht
   `ready` zurückgegebenes Bauteil machen den Snapshot inkonsistent.
6. Kann ein referenziertes Bauteil nicht gelesen werden oder reicht
   `sync_assembled_part_limit` nicht für die vollständige Closure, schlägt der
   Sync **fail-closed** fehl. Der vorherige lokale Snapshot bleibt stehen; ein
   unvollständiger neuer Stand wird weder gemappt noch zum Prunen freigegeben.
7. Alle PDB-Aufrufe dieses Pfads bleiben read-only (`listComponents`,
   `getComponent`, `listInstitutions`).

### 2. Vollständiger Evidence-Scope

1. Wurzeln sind alle nicht gelöschten und nicht veralteten lokalen Komponenten,
   die dem Institut gehören oder dort stehen.
2. Von diesen Wurzeln wird die nun vollständige lokale `parent_id`-Hierarchie
   rekursiv nach unten verfolgt.
3. Verbaute Nachfahren bleiben im Scope, unabhängig von Eigentümer, Standort
   und Komponenten-Typ.
4. Ohne explizite Profilbeschränkung werden alle vorkommenden Typen gespiegelt;
   damit fallen ABC/HCC/AMAC und künftige PDB-Typen nicht mehr still aus dem
   Default.
5. `evidence_component_types` bleibt als bewusste, institutsspezifische
   Whitelist erhalten. Der Filter wird **nach** der Traversierung angewandt,
   damit etwa ein externer Sensor unter einem externen Halbmodul weiterhin
   gefunden wird.
6. Der browserlokale `Lightweight`-Modus bleibt absichtlich auf `MODULE`
   beschränkt und lädt weiterhin keine neuen Attachment-Bytes.
7. `trashed`- und `stale`-Zeilen gelten nicht als belastbare Produktionsquelle
   und werden weder als Wurzel noch als Nachfahre aufgenommen.

Der Abschlussdatensatz eines Evidence-Jobs protokolliert zusätzlich:

- `scope_policy`
- `scope_roots`
- `scope_assembled_descendants`
- `component_type_filter`
- die tatsächlich im Scope vorkommenden `component_types`

Damit ist nachträglich sichtbar, ob ein Lauf vollständig, explizit gefiltert
oder leichtgewichtig war. Der Adapter prüft fail-closed, dass der vollständige
Scope genau einmal an den bestehenden, bereits gegen unvollständige
Indexantworten gehärteten Evidence-Runner übergeben wurde. Bei Vertragsdrift
wird der Job nicht als vollständiger Erfolg ausgegeben.

## Was dieser Fix nicht behauptet

- itkView bewegt keine Produktionskomponente und repariert keine Gate-Verstöße.
- Ein in der PDB fehlender oder auf die falsche Seriennummer hochgeladener Test
  kann von einem Viewer nicht rekonstruiert werden.
- Ein Testlauf wird weiterhin seiner realen Komponente zugeordnet; Child-
  Evidence wird nicht als eigener Testlauf des Parent-Moduls dupliziert.
- Gerätebilder, die nie in die PDB oder einen referenzierten Share gelangt sind,
  können durch einen vollständigen Sync nicht erfunden werden.
- Ein expliziter `Lightweight`-Lauf ist per Definition kein vollständiger
  Evidence-Snapshot und wird in der Job-Provenienz entsprechend ausgewiesen.

## Regressionen

Die fokussierten Tests decken ab:

- rekursives PDB-Nachladen über mehrere Assembly-Ebenen,
- Deduplizierung gemeinsam referenzierter Kinder,
- beide beobachteten Objekt-ID-Formen in Assembly-Members,
- fail-closed bei Read-Fehler, Identitätsdrift, nicht-`ready` und zu kleinem
  `sync_assembled_part_limit`,
- rekursive lokale Assembly `MODULE -> MODULE -> SENSOR`,
- einen bislang vom Default ausgeschlossenen `ABC`-Nachfahren,
- externe Eigentümer und externe Standorte,
- Ausschluss unabhängiger externer Komponenten,
- Ausschluss von `stale` und `trashed`,
- Profil-Whitelist nach der Traversierung,
- `Lightweight` mit externem Halbmodul,
- Übergabe des berechneten Scopes an den bestehenden Evidence-Runner sowie die
  persistierte Scope-Provenienz,
- Verdrahtung beider vollständigen Read-Pfade in der Application Factory.

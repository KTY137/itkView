# Vollständigkeit des Test-Evidence-Spiegels

> **Besitzt:** den Read-Vertrag dafür, welche Komponenten ein Evidence-Sync von
> itkView umfasst. Stage-Moves und Gate-Entscheidungen gehören nicht zu itkView;
> die PDB bleibt unverändert die Source of Truth.
>
> **Verwandt:** `09-pdb-production-strategy.md` für den PDB-Leseweg,
> `12-attachments-and-images.md` für Attachment-Bytes und
> `10-itk-domain-reference.md` für die Komponentenfamilien.

## Problem

Der Komponenten-Sync spiegelt nicht nur Bauteile, die einem Institut gehören
oder dort stehen. Er holt zusätzlich verbaute Teile nach, weil ein TUDO-Modul
beispielsweise einen CERN-Sensor und einen UT-Hybrid an einem dritten Standort
enthalten kann.

Der Evidence-Sync wiederholte danach jedoch den engeren Filter

```text
owner == institute OR location == institute
```

und wandte zusätzlich eine statische Komponenten-Typenliste an. Dadurch waren
die Bauteile zwar im lokalen Komponentenbaum vorhanden, ihre Testläufe und
Attachments wurden aber nicht zwingend gespiegelt. Besonders sichtbar war das
bei gestitchten Modulen, deren Sensoren, Powerboards und Hybride unter einem
Halbmodul liegen. Neue oder bislang unbekannte Komponentenfamilien konnten
außerdem vollständig aus dem Evidence-Sweep fallen.

## Vertrag ab 2026-08-29

Ein Standard-Evidence-Sync bildet die **vollständige lebende lokale
Produktionsclosure** des Instituts:

1. Wurzeln sind alle nicht gelöschten und nicht veralteten Komponenten, die dem
   Institut gehören oder dort stehen.
2. Von diesen Wurzeln wird die lokale `parent_id`-Assembly-Hierarchie rekursiv
   nach unten verfolgt.
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

Der Abschlussdatensatz eines Sync-Jobs protokolliert zusätzlich:

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

## Regressionen

Die fokussierten Tests decken ab:

- rekursive Assembly `MODULE -> MODULE -> SENSOR`,
- einen bislang vom Default ausgeschlossenen `ABC`-Nachfahren,
- externe Eigentümer und externe Standorte,
- Ausschluss unabhängiger externer Komponenten,
- Ausschluss von `stale` und `trashed`,
- Profil-Whitelist nach der Traversierung,
- `Lightweight` mit externem Halbmodul,
- Übergabe des berechneten Scopes an den bestehenden Evidence-Runner sowie die
  persistierte Scope-Provenienz.

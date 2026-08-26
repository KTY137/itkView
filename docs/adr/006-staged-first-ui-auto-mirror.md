# ADR 006: Staged-first UI und automatischer Evidence-Mirror

Status: akzeptiert und in M1–M4 umgesetzt (2026-08-26)

Die Architekturentscheidung und ihr zusammenhaengender Produktschnitt sind im
Arbeitsbaum umgesetzt. Die abschliessende gemeinsame Regression/Abnahme wird
weiterhin separat in `docs/04-roadmap.md` verfolgt; dieser ADR ersetzt keinen
Testnachweis.

## Kontext

Die bisherige Oberflaeche verteilte einen einzigen Operator-Workflow auf drei
Orte: Instrumentdaten wurden in der Triage eingegeben, offene PDB-Aenderungen
in der Outbox verwaltet und deren fachliche Wirkung erst auf der
Komponentendetailseite sichtbar. Gleichzeitig waren Testdetails und Dateien
nur nach getrennten manuellen Sync-Schritten offline verfuegbar. Das machte
den lokalen Spiegel zwar schnell, aber nicht verlaesslich vollstaendig und
liess staged Aenderungen wie Verwaltungsobjekte statt wie eine Vorschau auf
den naechsten Komponentenzustand erscheinen.

## Entscheidung

1. **Die Komponentendetailseite ist der Arbeitsort.** Datei-Upload und
   schemaerzeugte Testformulare legen weiterhin einen `IngestFile` an und
   durchlaufen denselben serverseitigen Dry-Run. Erst danach entsteht eine
   `upload_test_run`-Action. Ein von der Detailseite gesetzter
   `component_sn`-Pin wird serverseitig gegen Mirror und Payload geprueft;
   Widersprueche werden als Issue sichtbar und nie still ueberschrieben. Rohes
   JSON ist kein Produkt-UI.
2. **Staged ist eine Projektion, keine zweite Wahrheit.**
   `GET /api/components/{sn}/preview` berechnet Current und Projected nur aus
   lokalem Mirror plus nicht-terminalen Outbox-Actions. Stage-Moves werden in
   Erstellungsreihenfolge angewandt; offene Test-Uploads erscheinen als
   `pending`, nie als bereits bestandene Evidence. Der Endpunkt schreibt weder
   lokal noch in die PDB.

   Die Darstellung kennt drei rein visuelle Modi: `tabs` (Default, getrennte
   Ansichten `Current` und `Staged (n)`), `inline` (Stage-Pfeil, Ghost-Zeilen
   und Pending-Chips im aktuellen Kontext) und `off` (keine Projektion, aber
   weiterhin die explizite Liste offener Actions). Die Praeferenz liegt
   fehlertolerant unter `itkflow.stagedPreview` im Browser-`localStorage`.
   Alle Modi konsumieren dieselbe Serverprojektion; keiner implementiert
   Stage-Logik im Frontend.
3. **Die Schreibgrenze bleibt sichtbar.** Bei `pdb_write_scope=dummy_only`
   erhalten Actions fuer Nicht-DUMMY-Komponenten `submittable=false` und den
   maschinenlesbaren Grund `not_dummy`. Die UI bietet dann keinen irrefuehrenden
   Push an. ADR 003 und die Worker-Guards bleiben unveraendert.
4. **Outbox und Triage werden auf ihre Rollen reduziert.** Das
   `Staged`-Fenster gruppiert offene Actions komponentenweise und nutzt nur die
   bestehende Statusmaschine. `Push to PDB` fuehrt die erlaubten Transitions
   nacheinander bis zum worker-eigenen `submitted` aus und stoppt am ersten
   Fehler; `Discard` fuehrt in `cancelled`. Terminale Actions stehen getrennt
   in einer eingeklappten History. Das `Ingest log` ist ein read-only Verlauf;
   Eingabe und Freigabe liegen auf der Komponentenseite.
5. **Ein Sync spiegelt den auskunftsfaehigen Zustand.** Nach einem erfolgreichen
   Komponentenjob folgt automatisch ein Evidence-Job. Dieser holt detaillierte
   Testlaeufe und spiegelt deren Dateien best effort. Ein
   `evidence_component_types`-Profilwert bestimmt den Scope; der Seed-Default
   ist `MODULE` und kann institutsspezifisch im strukturierten Admin-Settings-
   Screen ersetzt werden.
6. **Drei Attachment-Quellen werden gleich sicher behandelt.**

   - Binary-Store-Dateien kommen ueber `getTestRunAttachment` mit ihrer
     Test-Run-Referenz.
   - Fuer EOS wird unmittelbar vor jedem Download eine frische vorsignierte URL
     geholt. URL und Token werden weder geloggt noch gespeichert.
   - HTTP(S)-Werte in gespiegelten Result-Feldern koennen als oeffentliche
     Share-Links registriert werden; der Sentinel `failed` wird ignoriert und
     es werden keine PDB-Credentials an den Zielhost gesendet.

   Alle Quellen verwenden denselben Pfadschutz, Groessenrahmen und
   HTML-Abwehr. Ein Dateifehler erhoeht den Fehlerzaehler, bricht aber einen
   institutsweiten Job nicht ab.

7. **Formulare folgen dem PDB-Schema-Mirror.** Testtyp-Schemata werden
   read-only ueber die persoenliche PDB-Verbindung gespiegelt. Bekannte
   skalare/Array-Datentypen erhalten kontrollierte Felder; unbekannte Typen
   werden erklaert und read-only dargestellt, statt still falsch serialisiert
   zu werden.

8. **Operative Konfiguration bleibt Institutsprofil, nicht Frontend-Code.** Der
   Admin-Settings-Screen editiert den Evidence-Scope zusammen mit
   Notification-, Shipment- und Glue-Einstellungen als strukturierte Felder.
   Er bietet keinen Raw-JSON- oder Secret-Readback-Pfad; die API validiert und
   auditiert nur nicht-sensitive Schluessel/Kanalnamen.

## Konsequenzen

- Die lokale Datenbank und der Attachment-Ordner bilden zusammen den
  wiederherstellbaren Offline-Spiegel; Backups muessen beide umfassen.
- Preview und UI duerfen Actions verwerfen oder durch bestehende Transitions
  bis `submitted` fuehren, umgehen aber nie Outbox, Audit, persoenliche
  Credential-Bindung oder DUMMY-Scope.
- Evidence-Syncs koennen deutlich laenger als reine Komponentensyncs dauern.
  Deshalb nutzen sie denselben persistenten Job-/Heartbeat-Mechanismus und
  bleiben bei Navigation, Reload und Server-Interrupt sichtbar.
- Evidence und Attachment-Bytes werden idempotent in getrennten Schritten
  gespiegelt. Ein Interrupt kann daher einen sicheren, aber unvollstaendigen
  Zwischenstand hinterlassen; der Job wird als unterbrochen markiert und ein
  erneuter Lauf konvergiert, statt einen atomaren Dateisystem-Commit
  vorzutäuschen.
- Kurzlebige externe URLs bleiben Metadaten des Upstreams, nicht Teil des
  dauerhaften lokalen Vertrags. Dauerhaft gespeichert werden nur sichere
  Deskriptoren und die heruntergeladenen Bytes.
- Die Preview-Praeferenz ist browser- und geraetlokal, nicht Teil des
  Nutzerkontos. Sie enthaelt keine Secrets und beeinflusst weder Outbox-Status
  noch Berechtigungen.

## Alternativen

- **Separate manuelle Buttons fuer Evidence und Dateien:** leichter zu bauen,
  aber der Nutzer kann nie erkennen, ob "Sync complete" wirklich einen
  offline vollstaendigen Stand bedeutet.
- **Frontend-seitige Projektion:** spart einen Endpunkt, dupliziert jedoch
  Stage-/Outbox-Regeln und kann vom Worker-Vertrag abdriften.
- **Direkter Formular-Upload in die PDB:** kuerzerer Klickpfad, verletzt aber
  Dry-Run, Review, Audit und die einzige zulaessige Schreibgrenze.

# ADR 007: itkView als fail-closed Read-only-Produktvariante

Status: akzeptiert (2026-08-28)

## Kontext

Neben dem Produktionscockpit itkFlow wird eine zweite Anwendung benoetigt, die
denselben lokalen PDB-Spiegel, Bilder, Kurven und Statistiken lesen kann, aber
keine Produktionsdaten erfasst oder zur PDB hochlaedt. Eine Quellcodekopie
waere dafuer die falsche Grenze: Bugfixes an Mirror, Attachments, Evidenz und
Visualisierung wuerden sofort zwischen zwei Repositories driften.

Nur Buttons auszublenden reicht ebenfalls nicht. Bereits gespeicherte
Outbox-Aktionen koennten von einem In-Process- oder Standalone-Worker weiter
abgearbeitet werden, direkte API-Aufrufe blieben moeglich, und ein gemeinsam
genutzter Datenordner koennte Schreibzustand aus itkFlow in den Viewer tragen.

## Entscheidung

1. **Eine Codebasis, zwei Build-Varianten.** `ITKFLOW_PRODUCT_VARIANT` kennt
   `flow` (Default, bisheriges Verhalten) und `view`. Der Frontend-Build erhaelt
   denselben Wert ueber `VITE_ITKFLOW_PRODUCT_VARIANT`. Beide Produkte teilen
   die Core-Version; Name, Capability und Packaging sind Varianten des
   verifizierten Commits, keine Forks.
2. **itkView ist fail-closed.** Die UI entfernt `Staged`/Outbox, `Triage`,
   Assembly, Registrierung, Test-Dateiupload, manuelle Testerfassung,
   Stage-Moves und alle zugehoerigen Edit-/Push-/Discard-Einstiege. Rollen
   koennen diese Produktgrenze nicht wieder einschalten; auch ein Admin hat in
   itkView keine
   Produktions-Schreibfaehigkeit.
3. **Der Server ist die Sicherheitsgrenze.** In `view` werden alle
   Workflow-, Registry-, Shipment-Reception-, Reminder- und Notification-
   Mutationen zentral abgelehnt. Explizit erlaubt bleiben Auth/First-run,
   lokale Benutzer- und Institutsadministration, persoenliche PDB- und
   Public-Share-Credentials sowie die genau klassifizierten Read-Syncs fuer
   Komponenten, Testdefinitionen, Evidenz, Attachments, Tools und Shipments.
   Diese Syncs schreiben den lokalen Spiegel, erzeugen aber keine PDB-Writes.
   Neue unsichere HTTP-Routen sind bis zu einer bewussten Klassifizierung
   standardmaessig gesperrt.
4. **Mehrschichtiger Sink-Guard.** `view` erzwingt
   `pdb_write_scope=disabled`, `allow_pdb_writes=false`,
   `outbox_processor=off` und `reminder_scheduler=off`. Der Standalone-Worker
   beendet sich ohne Drain; der PDB-Submitter und die direkte DUMMY-
   Registrierung verweigern den Aufbau nochmals. Damit bleibt die Garantie
   auch bei einem falsch gestarteten Worker oder einem direkten Python-Aufruf
   erhalten.
5. **Reads und Darstellung bleiben vollwertig.** PDB-Mirror-Sync, lokale
   Attachment-Downloads, Bilder, vorhandene Originalplots, generierte
   Fallback-Plots, IV/CV-Kollektivkurven, Statistics, Production-Hold-Anzeige,
   Suche und Diagnose bleiben erhalten. itkView ist daher nicht filesystem-
   read-only: sein lokaler Mirror und Cache muessen aktualisiert werden koennen.
6. **Seit-an-Seit-Isolation.** Desktop-App-ID, Hauptprogramm, Sidecar,
   Datenverzeichnis, SQLite-Datenbank, Credential-Key, Logs, Attachments und
   Session-/CSRF-Cookies sind zwischen itkFlow und itkView getrennt. Ports
   reichen fuer Cookies nicht aus, weil Browsercookies hostweit gelten.
   Vorgesehen sind `org.itkflow.desktop` / `org.itkflow.view`,
   `%LOCALAPPDATA%\itkflow` / `%LOCALAPPDATA%\itkview` und die Cookie-Paare
   `itkflow_session`/`itkflow_csrf` bzw.
   `itkview_session`/`itkview_csrf`.
7. **Eigener reproduzierbarer Build, kein zweiter Quellbaum.** Der Desktop-
   Builder waehlt `flow|view`, baut Frontend und PyInstaller-Arbeitsverzeichnis
   variantenspezifisch und verwendet fuer itkView ein Tauri-Config-Overlay.
   Alte Installer werden nicht als aktuelles Ergebnis aufgelistet. Web-/Compose-
   Builds geben denselben Variantenschalter an Backend, Worker und Vite weiter.

## Konsequenzen

- itkFlow bleibt ohne gesetzten Variantenschalter funktional unveraendert.
- Der itkView-Sidecar kann aus Wartungsgruenden weiterhin gemeinsamen Python-
  Code fuer Uploads enthalten; die Produktgarantie entsteht aus API-Policy,
  abgeschalteten Prozessoren und dem finalen Sink-Guard, nicht aus der
  zufaelligen Abwesenheit einzelner Bytecode-Module.
- Eine bestehende itkFlow-Datenbank wird nicht von itkView geoeffnet. Das kostet
  einen eigenen ersten Sync, verhindert aber Locks, Cookie-Verwechslungen und
  das Abarbeiten alter Outbox-Zustaende.
- Release-Abnahme prueft beide Varianten: unveraendertes itkFlow, sichtbares
  itkView-Branding, fehlende Authoring-Flows, erlaubte Read-Syncs, abgelehnte
  direkte Mutationen, Worker-/Submitter-Guard sowie getrennte Paket- und
  Zustandsidentitaeten.

## Verworfene Alternativen

- **Repository-Fork:** zu hohes Drift- und Security-Patch-Risiko.
- **Nur CSS/Buttons verstecken:** keine serverseitige oder Worker-Garantie.
- **Alle Nicht-GET-Requests sperren:** wuerde Login, Credentials und die
  ausdruecklich erwuenschten lokalen Mirror-Syncs zerstoeren.
- **Gemeinsame SQLite-Datei im Read-only-Modus:** Sync braucht lokale Writes;
  zudem koennten vorhandene Outbox-Aktionen und Migrationen die Produktgrenze
  unterlaufen.

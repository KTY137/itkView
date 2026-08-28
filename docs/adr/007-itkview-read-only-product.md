# ADR 007: itkView als fail-closed Read-only-Produktvariante

Status: akzeptiert (2026-08-28)

## Kontext

Neben dem Produktionscockpit itkFlow wird eine zweite Anwendung benoetigt, die
PDB-Spiegel, Bilder, Kurven und Statistiken lesen kann, aber keine
Produktionsdaten erfasst oder zur PDB hochlaedt. itkView erhaelt dafuer ein
eigenes Release-Repository und eigene sichere Defaults. Es bleibt trotzdem
eine Produktvariante des gemeinsam geprueften Kerns: Eine unabhaengig
neuimplementierte Quellcodekopie wuerde Sicherheitsfixes an Mirror,
Attachments, Evidenz und Visualisierung sofort driften lassen.

Nur Buttons auszublenden reicht ebenfalls nicht. Bereits gespeicherte
Outbox-Aktionen koennten von einem In-Process- oder Standalone-Worker weiter
abgearbeitet werden, direkte API-Aufrufe blieben moeglich, und ein gemeinsam
genutzter Datenordner koennte Schreibzustand aus itkFlow in den Viewer tragen.

## Entscheidung

1. **Gemeinsamer Kern, View als Repository-Default.**
   `ITKFLOW_PRODUCT_VARIANT` kennt `flow` und `view`; der Frontend-Build
   erhaelt denselben Wert ueber `VITE_ITKFLOW_PRODUCT_VARIANT`. Im dedizierten
   itkView-Repository waehlen fehlende Produktvariablen fail-closed `view`.
   `flow` bleibt nur als expliziter Wartungs-/Regression-Build des gemeinsamen
   Kerns erreichbar. Name, Capability und Packaging muessen aus demselben
   verifizierten Commit stammen.
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
   `itkview_session`/`itkview_csrf`. Compose besitzt zusaetzlich den festen
   Projektnamen `itkview`, eine eigene PostgreSQL-Datenbank sowie getrennte
   Datenbank- und Attachment-Volumes. Seine `.env` und sein Credential-Key
   werden nicht aus einem itkFlow-Deployment uebernommen.
7. **Eigener reproduzierbarer View-Default-Build.** Der Desktop-Builder baut
   ohne weitere Option itkView; Frontend-, PyInstaller-, Cargo- und
   Installer-Ausgaben liegen variantenspezifisch. Die Tauri-Basiskonfiguration
   traegt die View-App-ID, den View-Sidecar und das View-Branding; nur der
   explizite Flow-Regressionsbuild verwendet ein Overlay. Web-/Compose-Builds
   geben `view` gemeinsam an Backend, Worker und Vite weiter. Alte Installer
   werden nicht als aktuelles Ergebnis aufgelistet.

## Konsequenzen

- Das dedizierte itkView-Repository startet, testet und paketiert ohne
  Variantenschalter immer itkView; ein Flow-Regressionslauf ist explizit.
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

- **Unabhaengig neuimplementierter Repository-Fork:** zu hohes Drift- und
  Security-Patch-Risiko. Das eigene Release-Repository aendert den
  Produktdefault, nicht die mehrschichtige Kern-Policy.
- **Nur CSS/Buttons verstecken:** keine serverseitige oder Worker-Garantie.
- **Alle Nicht-GET-Requests sperren:** wuerde Login, Credentials und die
  ausdruecklich erwuenschten lokalen Mirror-Syncs zerstoeren.
- **Gemeinsame SQLite-Datei im Read-only-Modus:** Sync braucht lokale Writes;
  zudem koennten vorhandene Outbox-Aktionen und Migrationen die Produktgrenze
  unterlaufen.

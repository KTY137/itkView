# ADR 005: Desktop-Paketierung (Tauri-Shell + PyInstaller-Sidecar)

Status: akzeptiert (2026-08-25), Linux-Paketmatrix ergänzt (2026-08-31)

## Kontext

itkFlow ist als selbst gehosteter Mehrbenutzer-Server gebaut (Sessions, Rollen,
Audit, persönliche PDB-Credentials, Outbox-Worker). Für ein Institut ist das
richtig. Für den Einzelarbeitsplatz — und für „jemand soll das schnell
ausprobieren können" — ist der Aufsetzpfad aber teuer: Python-venv, Node,
Frontend-Build, Encryption-Key, DB-Pfad. Der Compose-Weg löst das nur für
Leute, die Docker haben und bedienen wollen.

Gesucht war eine doppelklickbare Variante, die **dieselbe** Anwendung startet —
keine reduzierte Zweitfassung, die auseinanderdriftet.

## Entscheidung

1. **Eine Shell, kein zweites Frontend.** Eine Tauri-Anwendung (`desktop/`)
   startet den gepackten Backend-Prozess und zeigt dessen Oberfläche in einem
   Webview. Die Shell hat keine eigene Produkt-UI außer Splash und einem
   lokalen Start-/Ausfallhinweis und stellt der Seite **kein** Tauri-IPC zur
   Verfügung; die Seite bleibt eine gewöhnliche Web-App.
2. **Das Backend serviert die SPA selbst** (`app/static_spa.py`, Setting
   `static_dir`). Damit liegen UI und API auf einer Origin, und der bestehende
   Session-Cookie- plus CSRF-Fluss funktioniert unverändert. Die Alternative —
   Webview auf `tauri://` und API auf `http://127.0.0.1:*` — hätte
   Cross-Origin-Cookies und eine CORS-Konfiguration erzwungen, also genau die
   Auth-Mechanik angefasst, die sonst überall gleich ist.
3. **Backend als PyInstaller-Onefile-Sidecar** (`desktop/itkflow-server.spec`,
   Entry `app/desktop_server.py`), gebaut von `desktop/build-sidecar.py`. Der
   Frontend-Build reist im Bundle mit.
4. **Port-Wahl beim Host.** Die Shell bindet kurz Port 0, liest die Nummer und
   übergibt sie per `--port`; danach pollt sie `/health`, bis das Backend
   wirklich antwortet, und navigiert erst dann. Ein reiner TCP-Connect wäre
   falsch: der Sidecar bindet den Socket, bevor die FastAPI-App steht.
   Scheitert das Binden, endet der Sidecar mit Status 2 statt zu hängen.
5. **Zustand außerhalb des Bundles und pro Produkt getrennt.** Datenbank,
   Attachments, Credential-Key und Logs liegen im jeweiligen
   Anwendungsdatenverzeichnis. itkView verwendet unter Windows
   `%LOCALAPPDATA%\itkview` und unter nativem Linux
   `${XDG_DATA_HOME:-$HOME/.local/share}/itkview`; der explizite Flow-Build
   verwendet jeweils den getrennten `itkflow`-Baum. Flatpak kapselt denselben
   logischen Zustand zusätzlich in seinem App-Datenverzeichnis. Ein
   vorhandener Key wird **nie** ersetzt: das würde jede gespeicherte Verbindung
   unlesbar machen. Die Trennung verhindert zugleich, dass itkView eine
   Flow-Outbox oder Flow-Session erbt.
6. **Keine Abkürzung an den Sicherheitsregeln vorbei.** Der explizite
   itkFlow-Build bleibt auf `pdb_write_scope=dummy_only` beschränkt; itkView
   erzwingt den strengeren Scope `disabled` und startet keinen
   Outbox-Prozessor.

   *Korrektur 2026-08-27:* Dieser Punkt nannte ursprünglich
   `pdb_instance=test`, `allow_production=false` als geerbte Defaults. Beides
   ist überholt. Ein `test`-Wert existiert in der Config nicht mehr (der
   Code-Default ist `offline`), und das Desktop-Bundle schaltet Produktions-
   **Reads** ab Werk selbst ein (Owner-Entscheidung 2026-08-26,
   [docs/09](../09-pdb-production-strategy.md)) — sichtbar in
   `backend/app/desktop_server.py`, das die Overrides nur setzt, wenn die
   Umgebung sie nicht ohnehin vorgibt. PDB-Verkehr entsteht trotzdem erst,
   wenn eine Person ihre persönlichen Access-Codes verbindet
   ([ADR 004](004-personal-pdb-credentials.md)). Im Flow-Build bleiben
   Schreiboperationen auf selbst registrierte DUMMY-Komponenten beschränkt
   ([ADR 003](003-pdb-dummy-write-scope.md)); itkView hat keine
   PDB-Schreibfähigkeit ([ADR 007](007-itkview-read-only-product.md)).
7. **Zwei Produkt-Builds, View als sicherer Repository-Default.** Der Builder
   kennt `view` (Default im dedizierten itkView-Repository) und den nur
   explizit ausgewaehlten `flow`-Regressionsbuild. Die Tauri-
   Basiskonfiguration traegt Product-/Binary-/Installer-Name, App-ID und
   Sidecar von itkView; Flow verwendet ein Overlay. Rust gibt den kompilierten
   Produktmodus an den Python-Sidecar weiter. Frontend-, PyInstaller-Work-,
   Dist- und Cargo-Ausgaben sind variantenspezifisch, damit ein zuvor gebautes
   Flow-Artefakt nie als View-Payload ausgegeben wird. Die Produkte verwenden
   getrennte Datenpfade und Cookie-Namen und koennen deshalb gleichzeitig
   laufen. Die fachliche Read-only-Grenze besitzt
   [ADR 007](007-itkview-read-only-product.md).
8. **Linux wird als Paketmatrix, nicht als unprüfbares „alle Distros"
   geliefert.** Der native Builder erzeugt auf seiner Host-Architektur genau
   ein DEB, RPM und AppImage. Der Release-Workflow baut diese Artefakte auf
   nativen Ubuntu-22.04-Runnern für `x86_64` und `aarch64`, prüft den
   eingefrorenen Sidecar und erzeugt zusätzlich ein Flatpak mit GNOME Runtime
   50. Das Flatpak erhält Netzwerk, IPC, Wayland/Fallback-X11 und DRI, aber
   keinen pauschalen Zugriff auf Home oder Host-Dateisystem. Damit sind die
   verbreiteten glibc-basierten Desktop-Familien abgedeckt; APK, Nix, Guix,
   AUR/Snap, musl und 32-Bit sind keine first-party nativen Ziele. Wo Flatpak
   nicht verfügbar ist, bleibt Compose der portable Serverweg. Bei einem zum
   Bundle passenden Tag wartet ein separater Release-Job auf **beide**
   Architekturen, prüft deren getrennte `SHA256SUMS-<arch>` erneut und
   veröffentlicht DEB, RPM, AppImage, Flatpak und Prüfsummen erst danach
   gemeinsam als GitHub Release. Manuelle Läufe bleiben unveröffentlichte,
   30 Tage aufbewahrte Actions-Artefakte.

## Konsequenzen

- Eine Codebasis mit zwei Produktvarianten und drei Betriebsarten
  (Dev-Launcher, Compose, Desktop). Die Desktop-Variante ist Einzelplatz: sie
  ersetzt das Institutsdeployment nicht, weil Rollen, Audit und gemeinsame
  Mirror-Daten dort serverseitig geteilt werden; nur der explizite Flow-Betrieb
  besitzt zusätzlich eine Outbox-Verarbeitung.
- Der Sidecar ist ein Windowed-Build ohne nutzbares stdout. Ein frozener Lauf
  schreibt deshalb immer in `<datadir>/logs/server.log`; der Tauri-Host
  schreibt getrennt strukturierte Lifecycle-Daten nach `desktop.log` und
  kopiert niemals rohe Sidecar-Ausgabe. Beide Logs rotieren beim naechsten
  Start (`server.log`: 5 MiB, `desktop.log`: 1 MiB, jeweils drei Backups),
  Python-Faulthandler schreibt Thread-Stacks in den Server-Log. Ein
  unerwartetes Sidecar-Ende nach der Navigation ersetzt die Seite durch einen
  lokalen Fehlerhinweis, startet aber keine unkontrollierte Restart-Schleife.
  Globale Admins koennen im paketierten Desktop ein begrenztes Diagnose-ZIP
  aus genau diesen Logs und sanitisierten Sync-Metadaten laden; Webbetrieb und
  Institutsadmins haben diesen Endpoint nicht. Die READY-Zeile enthaelt keinen
  Datenverzeichnispfad.
- Onefile heißt zwei Prozesse: der gestartete Bootstrap re-exekutiert sich als
  eigentlicher Server. Beim normalen Beenden sendet die Linux-Shell deshalb
  zuerst `SIGTERM` an den Bootstrap und wartet höchstens acht Sekunden auf das
  `Terminated`-Event. PyInstaller kann so den Signalweg zum Server abwickeln und
  sein `_MEI*`-Verzeichnis entfernen. Erst wenn das Signal scheitert oder die
  Frist verstreicht, folgt `SIGKILL`; ein PyInstaller-Runtime-Hook setzt dafür
  `PR_SET_PDEATHSIG`, damit der eigentliche Server nicht mit offener SQLite-DB
  und Localhost-Port headless weiterläuft. Dieser Crash-Fallback kann das
  `_MEI*`-Aufräumen nicht garantieren. Unter Windows bleibt der bewährte ganze
  Prozessbaum via `taskkill /T /F` maßgeblich. Der Release-Smoke-Test prüft die
  zwei Linux-Pfade getrennt: `SIGTERM` muss Bootstrap, Child, Port **und** das
  kontrollierte `_MEI*`-Verzeichnis entfernen; nach erzwungenem `SIGKILL`
  dürfen kein laufender Child und kein Port übrig sein. Ein bereits beendeter,
  vom minimalistischen Container-PID-1 noch nicht eingesammelter Zombie gilt
  dabei nicht als lebender Prozess; der Check liest deshalb zusätzlich zum
  PID-Signaltest den Zustand aus `/proc`.
- Startzeit: Onefile entpackt bei jedem Start (~20 MB). Der Splash überbrückt
  das; wird es störend, ist Onedir plus Tauri-Resources der nächste Schritt.
- Signierung ist offen. Ohne Zertifikat zeigt Windows SmartScreen eine Warnung;
  Linux-Artefakte erhalten SHA-256-Prüfsummen und Tag-Builds werden dauerhaft
  an ein GitHub Release gehängt, aber es gibt noch keine Paket-/Binärsignatur
  oder Veröffentlichung in distributionsspezifische Repositories.
- Toolchain: Tauri unter Windows ist offiziell MSVC. Der Build lief hier mit
  der GNU-Toolchain vollstaendig durch — Binary und NSIS-Installer
  (`itkFlow_0.1.0_x64-setup.exe`, 21 MB) —, mit zwei Eigenheiten:
  einer Linker-Warnung (`.rsrc merge failure: multiple non-default manifests`),
  und der Notwendigkeit, `--target x86_64-pc-windows-gnu` explizit zu setzen.
  Ohne das sucht der Bundler den Sidecar unter dem MSVC-Triple, waehrend
  `build-sidecar.py` ihn nach dem Host-Triple benennt. Seit dem
  `--bundle`-Schritt (`npm run build` in `desktop/` ruft
  `build-sidecar.py --bundle`) setzt der Build das Host-Triple selbst — der
  Handgriff entfaellt. Fuer Releases bleibt MSVC die getretene Pfadstrecke.
- Linux-Pakete werden nativ je Architektur gebaut. Die Ubuntu-22.04-Basis hält
  den glibc-Floor niedriger als ein Build auf einer aktuellen Rolling
  Distribution; insbesondere das AppImage ist trotzdem kein Container und
  kann nicht jede beliebige libc-/Desktop-Kombination abstrahieren. Flatpak
  übernimmt diese Rolle mit einer versionierten Runtime. Der Jammy-Archivstand
  von `flatpak-builder` ist zu alt für die AppStream-Komposition der GNOME-
  Runtime 50; der Workflow bezieht deshalb mindestens Version 1.4.4 aus dem
  Stable-PPA des Flatpak-Teams und prüft die Mindestversion vor dem Build. Die
  Paketabnahme kontrolliert außerdem die von Tauri injizierten WebKitGTK-4.1-
  und GTK-3-Laufzeitabhängigkeiten explizit im DEB- und RPM-Metadatensatz; ein
  formal lesbares, aber nicht installierbares Paket darf nicht hochgeladen
  werden.

## Alternativen

- **Electron**: größere Runtime, zweite JS-Laufzeit im Haus, kein Vorteil hier.
- **Nur Compose**: löst den Einzelplatzfall nicht ohne Docker.
- **Thin Client gegen einen Institutsserver**: sinnvoll und mit dieser Shell
  später leicht möglich (nur die Ziel-URL ändert sich), aber es löst nicht das
  Problem „ich will es ohne Server ausprobieren".

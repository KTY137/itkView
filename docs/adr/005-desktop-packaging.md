# ADR 005: Desktop-Paketierung (Tauri-Shell + PyInstaller-Sidecar)

Status: akzeptiert (2026-08-25)

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
   Webview. Die Shell hat keine eigene UI außer einem Splash und stellt der
   Seite **kein** Tauri-IPC zur Verfügung; die Seite bleibt eine gewöhnliche
   Web-App.
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
5. **Zustand außerhalb des Bundles.** Datenbank, Credential-Key und Logs liegen
   im Anwendungsdatenverzeichnis — bewusst dasselbe wie beim Windows-Launcher
   (`%LOCALAPPDATA%\itkflow`), damit eine bereits verbundene PDB-Identität
   erhalten bleibt. Ein vorhandener Key wird **nie** ersetzt: das würde jede
   gespeicherte Verbindung unlesbar machen.
6. **Keine Abkürzung an den Sicherheitsregeln vorbei.** Die Desktop-Variante
   erbt die Defaults: `pdb_instance=test`, `allow_production=false`,
   `pdb_write_scope=dummy_only`. Produktions-Reads brauchen dieselben zwei
   Env-Opt-ins wie jede andere Installation (ADR 003, docs/09).

## Konsequenzen

- Eine Codebasis, drei Betriebsarten (Dev-Launcher, Compose, Desktop). Die
  Desktop-Variante ist Einzelplatz: sie ersetzt das Institutsdeployment nicht,
  weil Rollen, Audit und Outbox-Worker auf einen gemeinsamen Server zielen.
- Der Sidecar ist ein Windowed-Build ohne nutzbares stdout. Ein frozener Lauf
  schreibt deshalb immer in `<datadir>/logs/server.log`; ohne das wäre ein
  Absturz spurlos.
- Startzeit: Onefile entpackt bei jedem Start (~20 MB). Der Splash überbrückt
  das; wird es störend, ist Onedir plus Tauri-Resources der nächste Schritt.
- Signierung ist offen. Ohne Zertifikat zeigt Windows SmartScreen eine Warnung.
- Toolchain: Tauri unter Windows ist offiziell MSVC. Der Build lief hier mit
  der GNU-Toolchain vollstaendig durch — Binary und NSIS-Installer
  (`itkFlow_0.1.0_x64-setup.exe`, 21 MB) —, mit zwei Eigenheiten:
  einer Linker-Warnung (`.rsrc merge failure: multiple non-default manifests`),
  und der Notwendigkeit, `--target x86_64-pc-windows-gnu` explizit zu setzen.
  Ohne das sucht der Bundler den Sidecar unter dem MSVC-Triple, waehrend
  `build-sidecar.py` ihn nach dem Host-Triple benennt. Fuer Releases bleibt
  MSVC die getretene Pfadstrecke.

## Alternativen

- **Electron**: größere Runtime, zweite JS-Laufzeit im Haus, kein Vorteil hier.
- **Nur Compose**: löst den Einzelplatzfall nicht ohne Docker.
- **Thin Client gegen einen Institutsserver**: sinnvoll und mit dieser Shell
  später leicht möglich (nur die Ziel-URL ändert sich), aber es löst nicht das
  Problem „ich will es ohne Server ausprobieren".

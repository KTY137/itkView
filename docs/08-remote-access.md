# Plan: Remote-Zugriff / Tunneling

> Planungsdokument (noch nicht umgesetzt). Wie kommt man **von zuhause** sicher
> an die itkFlow-Instanz, die auf einem Lab-PC/Instituts-VM laeuft.
>
> - **Besitzt:** die Optionen fuer Fernzugriff (Mesh-VPN, Zero-Trust-Tunnel,
>   Instituts-VPN, offener Reverse Proxy), die Empfehlung und die
>   Betriebshinweise dazu.
> - **Fuer wen:** alle, die eine Instanz ueber das Labornetz hinaus erreichbar
>   machen wollen — vorher lesen, nicht nachher.
> - **Verwandt:** [`06-users-roles-audit.md`](06-users-roles-audit.md)
>   (Auth-Fundament, harte Vorbedingung),
>   [`09-pdb-production-strategy.md`](09-pdb-production-strategy.md)
>   (was eine erreichbare Instanz gegenueber der PDB darf),
>   [`../deploy/README.md`](../deploy/README.md) (das Deployment davor),
>   [`04-roadmap.md`](04-roadmap.md) (Einordnung), [`README.md`](README.md)
>   (Lesepfade).

## Sicherheits-Vorbedingung (zuerst!)

Remote-Zugriff wird **erst scharf geschaltet, wenn die Authentifizierung steht**
([`06-users-roles-audit.md`](06-users-roles-audit.md)). Eine App, die
PDB-Writes ausloesen und Konfiguration aendern kann, darf nicht ohne
Login erreichbar sein.

- Transport **immer TLS** (kein Klartext-HTTP nach aussen).
- Der Schreibbereich bleibt **`pdb_write_scope=dummy_only`** (harte Regel #2,
  [`09`](09-pdb-production-strategy.md), [ADR 003](adr/003-pdb-dummy-write-scope.md))
  — Remote aendert daran nichts. Eine PDB-Testinstanz gibt es **nicht mehr**;
  eine aeltere Fassung dieses Abschnitts behauptete das Gegenteil.
- PDB-Verkehr entsteht ohnehin erst, wenn eine Person ihre **persoenlichen**
  Access-Codes verbindet ([ADR 004](adr/004-personal-pdb-credentials.md)) —
  Fernzugriff verschafft niemandem fremde Codes.
- Audit-Spur ([docs/06](06-users-roles-audit.md)) macht Remote-Aktionen
  nachvollziehbar.

## Optionen (mit Empfehlung)

**A. Privates Mesh-VPN — Tailscale / WireGuard (empfohlen fuer den Start).**
Der Lab-PC tritt einem privaten Tailnet bei; dein Heimgeraet ist im selben Netz.
- Kein Port-Forwarding, keine oeffentliche Angriffsflaeche.
- Geraeteauthentifiziert und Ende-zu-Ende verschluesselt.
- Die App bleibt auf `localhost`/privatem Interface gebunden.
- Ideal, solange der Nutzerkreis ueberschaubar ist (eigene Geraete).

**B. Zero-Trust-Tunnel — Cloudflare Tunnel (oder aehnlich).**
Ausgehender Tunnel vom Lab-PC; oeffentlicher Hostname **ohne offene Ports**.
Davor eine Access-Policy (E-Mail-/SSO-basiert).
- Gut, wenn mehrere externe Nutzer **ohne VPN-Client** zugreifen sollen.
- Zusaetzliche Zugangskontrolle vor der App-eigenen Auth.

**C. Instituts-/CERN-VPN + Reverse Proxy.**
Wenn die IT ein VPN bereitstellt: App hinter einen Reverse Proxy (Caddy/nginx,
TLS) im Instituts-Netz, Zugriff nur ueber VPN. Nutzt vorhandene Infrastruktur.

**D. Reverse Proxy + offener Port (am wenigsten empfohlen).**
Caddy/nginx mit TLS und offenem Port nach aussen — nur mit strikter Auth,
Firewall, Rate-Limit und Fail2ban-artigem Schutz. Groesste Angriffsflaeche;
nur wenn A–C nicht moeglich sind.

## Empfehlung

**Start mit Tailscale (A)** — schnell, sicher, kein Port-Forwarding, passt zum
Lab-PC-Betrieb. Wenn ein **oeffentlicher Zugang ohne VPN-Client** noetig wird,
auf **Cloudflare Tunnel (B)** mit Access-Policy wechseln. `deploy/` (Compose,
`nginx.conf`) bleibt unveraendert; der Tunnel/das VPN sitzt davor.

## Betriebshinweise

- App an `127.0.0.1` binden; nur Tunnel/VPN terminiert extern.
- TLS erzwingen; sichere Cookies (`Secure`, `httpOnly`) — greift mit
  [docs/06](06-users-roles-audit.md).
- Rate-Limiting am Proxy/Tunnel.
- Backups/Monitoring unabhaengig vom Zugriffsweg (Phase 4/6).

## Offene Fragen

- Nutzerkreis: nur eigene Geraete (VPN reicht) oder breiter Kreis ohne
  VPN-Client (Tunnel + Access-Policy)?
- Stellt die Instituts-IT bereits ein VPN/Reverse-Proxy-Muster bereit?
- Eigener Hostname/Domain gewuenscht?

## Roadmap-Einordnung

Betriebsthema (Phase 4/6). **Harte Abhaengigkeit:** Auth-Fundament aus
[`06-users-roles-audit.md`](06-users-roles-audit.md) muss zuerst stehen. Siehe
[`04-roadmap.md`](04-roadmap.md).

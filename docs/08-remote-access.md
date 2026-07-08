# Plan: Remote-Zugriff / Tunneling

> Planungsdokument (noch nicht umgesetzt). Wie kommt man **von zuhause** sicher
> an die itkFlow-Instanz, die auf einem Lab-PC/Instituts-VM laeuft.

## Sicherheits-Vorbedingung (zuerst!)

Remote-Zugriff wird **erst scharf geschaltet, wenn die Authentifizierung steht**
(`docs/06-users-roles-audit.md`). Eine App, die (Test-)PDB-Writes ausloesen und
Konfiguration aendern kann, darf nicht ohne Login erreichbar sein.

- Transport **immer TLS** (kein Klartext-HTTP nach aussen).
- Weiterhin **nur PDB-Testinstanz** (harte Regel #2) — Remote aendert daran
  nichts.
- Audit-Spur (docs/06) macht Remote-Aktionen nachvollziehbar.

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
- TLS erzwingen; sichere Cookies (`Secure`, `httpOnly`) — greift mit docs/06.
- Rate-Limiting am Proxy/Tunnel.
- Backups/Monitoring unabhaengig vom Zugriffsweg (Phase 4/6).

## Offene Fragen

- Nutzerkreis: nur eigene Geraete (VPN reicht) oder breiter Kreis ohne
  VPN-Client (Tunnel + Access-Policy)?
- Stellt die Instituts-IT bereits ein VPN/Reverse-Proxy-Muster bereit?
- Eigener Hostname/Domain gewuenscht?

## Roadmap-Einordnung

Betriebsthema (Phase 4/6). **Harte Abhaengigkeit:** Auth-Fundament aus
`docs/06-users-roles-audit.md` muss zuerst stehen. Siehe `docs/04-roadmap.md`.

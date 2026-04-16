---
name: Damian's network setup (Italy FWA + backup)
description: Network context for performance reasoning — FWA cellular + iPhone hotspot + NordVPN
type: reference
originSessionId: 3119cbb0-317f-4497-a688-5bd55c8cf173
---
Damian is in Italy, connecting via Vodafone FWA (Fixed Wireless Access, cellular-based).

- **Router**: ZTE MF289F (4G/LTE Cat 20, outdoor-capable) at `http://vodafone.stationfwa` / `192.168.0.1`
- **Admin password**: on sticker behind router (unique per device)
- **WiFi SSID**: `VF_IT_FWA_{mac}`
- **Signal quality matters a lot**: LTE RSRP ~-101 dBm when router is in the habitacion (good position); was -107 dBm originally (poor, explains old slow speeds)
- **Cell congestion**: nightly hours (20-23) → throttled. Historical peak 200+ Mbps at 2-4 AM, typically 80-100 Mbps during day.
- **Backup**: iPhone Personal Hotspot via USB (Ethernet 3 adapter, 172.20.10.0/24 subnet). Different cellular IP → fresh rate-limit bucket.
- **NordVPN** installed (NordLynx): activating it changes public IP (useful against per-IP throttling, e.g. Cloudflare). When paused, Windows falls back to lowest metric interface.

**Multi-interface caveats:**
- Source IP binding (`socket.bind(src_ip, 0)`) does NOT bypass NordLynx — NordVPN routes everything by default route metric. Must pause VPN or configure split tunneling to actually use different interfaces simultaneously.
- When iPhone is connected via USB while on WiFi, Windows may pick iPhone route by default (lower metric) — check `Find-NetRoute -RemoteIPAddress 8.8.8.8` before assuming route.

**Performance observations for scraping 360cities:**
- Cloudflare throttles per-IP progressively (rate decays 35→11 req/s over 10h)
- Rotating IP (VPN server change, or different ISP) resets the throttle bucket
- 12 workers per process works well; 4 parallel processes across chunks = ~50 req/s combined

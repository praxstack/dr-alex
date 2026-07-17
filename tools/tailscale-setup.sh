#!/usr/bin/env bash
# tailscale-setup.sh — ACTIVATION GUIDE + PREFLIGHT for reaching The Room from your phone.
#
# ⚠️  This script does NOT auto-configure anything network-facing. It only PREFLIGHTS and PRINTS
#     the exact steps. Read it, then run the steps yourself, deliberately. Tailscale is NOT
#     installed on this machine yet — install it first (https://tailscale.com/download/mac).
#
# THE ONLY sanctioned way to reach alexd from the phone (council D3 rider 1):
#     tailscale serve https / 127.0.0.1:8787
# This terminates HTTPS locally and proxies to the loopback bind. alexd itself NEVER binds
# anything but 127.0.0.1 — 0.0.0.0 / LAN / ngrok / cloudflared / any public tunnel is BANNED
# and is not a supported workaround. WireGuard + Tailscale device identity is the perimeter.
#
# REQUIRED at activation (council D3 rider 3): register a WebAuthn / passkey on the phone so a
# picked-up, unlocked phone still cannot open The Room. The PWA nags every open until you do.
# Passkey registration only becomes a REAL ceremony over the Tailscale HTTPS origin (a secure
# context with a real hostname) — on the plain http://127.0.0.1 dev origin it is a stub.

set -euo pipefail

say() { printf '%s\n' "$*"; }
ok()  { printf '  ✓ %s\n' "$*"; }
no()  { printf '  ✗ %s\n' "$*"; }

say "── The Room · Tailscale activation preflight ──────────────────────────────"
say ""

# 1. Tailscale present?
if command -v tailscale >/dev/null 2>&1; then
  ok "tailscale CLI found: $(command -v tailscale)"
  if tailscale status >/dev/null 2>&1; then
    ok "tailscale is up (device is on the tailnet)"
  else
    no "tailscale is installed but not connected — run: tailscale up"
  fi
else
  no "tailscale NOT installed. Install: https://tailscale.com/download/mac  (then: tailscale up)"
fi
say ""

# 2. Is alexd listening on loopback:8787?
if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 http://127.0.0.1:8787/healthz >/dev/null 2>&1; then
  ok "alexd is healthy on http://127.0.0.1:8787/  (start it with: dr-alex serve)"
else
  no "alexd not reachable on 127.0.0.1:8787 — start it first:  dr-alex serve"
fi
say ""

# 3. Loopback-bind sanity: alexd must NOT be reachable on a LAN address (D3 rider 1).
say "Loopback-only check (must NOT be reachable on 0.0.0.0/LAN):"
lan_ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
if [ -n "${lan_ip}" ] && command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 2 "http://${lan_ip}:8787/healthz" >/dev/null 2>&1; then
    no "REACHABLE on ${lan_ip}:8787 — this is a BANNED non-loopback exposure. Stop alexd and"
    no "   ensure nothing is re-binding it to 0.0.0.0. alexd hard-asserts loopback; a proxy on"
    no "   top must not widen it. (council D3 rider 1)"
  else
    ok "not reachable on ${lan_ip}:8787 (correct — loopback only)"
  fi
else
  ok "no LAN IP detected / curl missing — nothing to widen (fine)"
fi
say ""

say "── DO THESE STEPS YOURSELF (not auto-run) ─────────────────────────────────"
say "1) Start alexd:            dr-alex serve"
say "2) Expose over Tailscale:  tailscale serve https / 127.0.0.1:8787"
say "3) On the phone, open:     https://<this-node>.<your-tailnet>.ts.net/"
say "4) Pair the device:        run 'dr-alex pair' and enter the code in the PWA"
say "5) REQUIRED — register a passkey when the PWA nags (real over the HTTPS origin)"
say ""
say "To stop exposing:          tailscale serve https / off"
say "───────────────────────────────────────────────────────────────────────────"

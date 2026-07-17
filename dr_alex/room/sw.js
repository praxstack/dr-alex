/* The Room — service worker. Precaches the app shell + the crisis card so GET /crisis and the
 * crisis UI render OFFLINE (Mac asleep / off-network) — the load-bearing property of the whole
 * design. API calls (turns, sessions, homework) are NEVER cached: they need live data and must
 * never be served stale. The precached crisis assets carry ZERO personal data / session state. */

"use strict";

var CACHE = "the-room-shell-v2";

/* Split by criticality. The offline crisis surface — the "/" shell + the "/crisis" card — is the
 * load-bearing safety property: it is cached ATOMICALLY and install FAILS LOUDLY if it can't be
 * (contract invariant: loud failures). Everything else is best-effort — a single missing or
 * renamed asset must NEVER again silently disable the whole offline shell. That regression shipped
 * once: the precache listed "/index.html" and "/crisis.html", which the service 404s, so the
 * atomic addAll rejected and no service worker ever activated. Only actually-served routes here. */
var CRITICAL = ["/", "/crisis"];
var OPTIONAL = ["/app.css", "/app.js", "/manifest.json"];

/* Requests that must always hit the network (live data; never cached). */
var API_PREFIXES = [
  "/turn", "/session", "/checkin", "/homework", "/continuity",
  "/export", "/pair", "/webauthn", "/healthz"
];

function isApi(path) {
  for (var i = 0; i < API_PREFIXES.length; i++) {
    if (path === API_PREFIXES[i] || path.indexOf(API_PREFIXES[i] + "/") === 0) return true;
  }
  return false;
}

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      // Critical assets are atomic: if the crisis surface can't be cached, install rejects
      // and this worker never activates — a loud failure, exactly as we want for the one
      // property the whole design exists to protect.
      return cache.addAll(CRITICAL).then(function () {
        // Optional assets are best-effort: a single missing/renamed file must not abort install.
        return Promise.all(OPTIONAL.map(function (u) {
          return cache.add(u).catch(function () { return null; });
        }));
      });
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; })
        .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  var req = event.request;
  var url = new URL(req.url);

  // Only handle same-origin GETs; everything else (API POSTs) goes straight to the network.
  if (req.method !== "GET" || url.origin !== self.location.origin || isApi(url.pathname)) {
    return;
  }

  // Cache-first for the shell + crisis so they render offline; refresh the cache in the
  // background when the network is available.
  event.respondWith(
    caches.match(req).then(function (cached) {
      var network = fetch(req).then(function (resp) {
        if (resp && resp.status === 200 && resp.type === "basic") {
          var copy = resp.clone();
          caches.open(CACHE).then(function (cache) { cache.put(req, copy); });
        }
        return resp;
      }).catch(function () {
        // Offline: fall back to the crisis card for a crisis navigation, else the app shell.
        if (url.pathname === "/crisis") return caches.match("/crisis");
        if (req.mode === "navigate") return caches.match("/");
        return cached;
      });
      return cached || network;
    })
  );
});

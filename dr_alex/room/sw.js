/* The Room — service worker. Precaches the app shell + the crisis card so GET /crisis and the
 * crisis UI render OFFLINE (Mac asleep / off-network) — the load-bearing property of the whole
 * design. API calls (turns, sessions, homework) are NEVER cached: they need live data and must
 * never be served stale. The precached crisis assets carry ZERO personal data / session state. */

"use strict";

var CACHE = "the-room-shell-v1";

/* The app shell + the offline crisis surface. crisis.html and app.js both carry the hard-coded
 * India crisis resources (14416 … Shreya), so the crisis card is available with no network. */
var PRECACHE = [
  "/",
  "/index.html",
  "/app.css",
  "/app.js",
  "/crisis",
  "/crisis.html",
  "/manifest.json"
];

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
      return cache.addAll(PRECACHE);
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

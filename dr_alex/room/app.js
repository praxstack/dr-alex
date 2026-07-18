/* The Room — vanilla JS, zero external fetches. Talks only to same-origin alexd.
 *
 * The crisis card content below is baked in (a static constant, no personal data, no session
 * state) so the "I need help right now" button renders INSTANTLY and OFFLINE from the cached
 * app — the load-bearing property. A Python test asserts these numbers stay in sync with the
 * single source of truth (safety/crisis_card.py). */

"use strict";

// --- Crisis card (static; India resources, hard-coded — mirrors safety/crisis_card.py) ---
var CRISIS = {
  header: "You don't have to be alone with this. Help is one call away.",
  lede: "You reached out, and that matters. Let's slow down together for a moment — you don't have to carry this alone right now.",
  resources: [
    { name: "Tele-MANAS", number: "14416", note: "Govt of India, 24x7, free, many languages. (Also 1800-891-4416.)" },
    { name: "iCall (TISS)", number: "9152987821", note: "Mon-Sat, psychosocial counselling." },
    { name: "AASRA", number: "9820466726", note: "24x7 emotional support." },
    { name: "Vandrevala Foundation", number: "1860-2662-345", note: "24x7 mental health helpline." },
    { name: "Emergency", number: "112", note: "Immediate danger — police / ambulance." }
  ],
  therapist: "Shreya",
  therapistLine: "Your therapist: Shreya — reach out to her.",
  draft: "Hi Shreya — I'm having a really hard time right now and could use your support. Can we talk soon?",
  breath: "If you can: feet on the floor, one slow breath in for 4, out for 6. Just this one breath."
};

var TOKEN_KEY = "dralex_device_token";
var THEME_KEY = "dralex_theme";
var PASSKEY_KEY = "dralex_passkey_registered";

var state = { sessionId: null, streaming: false, moodPhase: "open" };

function $(id) { return document.getElementById(id); }
function deviceToken() { try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; } }

function api(path, opts) {
  opts = opts || {};
  var headers = opts.headers || {};
  headers["Content-Type"] = "application/json";
  var t = deviceToken();
  if (t) headers["X-Dr-Alex-Device-Token"] = t;
  opts.headers = headers;
  return fetch(path, opts);
}

// --- Theme -----------------------------------------------------------------
function applyTheme(theme) {
  if (theme === "light" || theme === "dark") {
    document.documentElement.setAttribute("data-theme", theme);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}
function initTheme() {
  var saved = null;
  try { saved = localStorage.getItem(THEME_KEY); } catch (e) {}
  applyTheme(saved);
  $("theme-toggle").addEventListener("click", function () {
    var cur = document.documentElement.getAttribute("data-theme");
    var isDark = cur ? cur === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    var next = isDark ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
  });
}

// --- Crisis overlay (renders from the baked constant — works offline) ------
function renderCrisisCard() {
  var lines = CRISIS.resources.map(function (r) {
    return '<div class="crisis-line"><div><span class="crisis-name">' + esc(r.name) +
      '</span><span class="crisis-note">' + esc(r.note) + '</span></div>' +
      '<a class="crisis-num" href="tel:' + esc(r.number.replace(/[^0-9]/g, "")) + '">' + esc(r.number) + "</a></div>";
  }).join("");
  return '<h1>You are not alone</h1><p class="lede">' + esc(CRISIS.lede) + "</p>" +
    "<p>" + esc(CRISIS.header) + "</p>" + lines +
    '<div class="crisis-shreya"><strong>' + esc(CRISIS.therapistLine) + "</strong>" +
    "<span>A message you could send her (you send it, not the app):</span>" +
    '<div class="crisis-draft">"' + esc(CRISIS.draft) + '"</div></div>' +
    '<p class="crisis-breath">' + esc(CRISIS.breath) + "</p>";
}
function openCrisis() {
  $("crisis-card").innerHTML = renderCrisisCard();
  $("crisis-overlay").hidden = false;
}
function closeCrisis() { $("crisis-overlay").hidden = true; }

// --- Transcript ------------------------------------------------------------
function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function addMsg(kind, text) {
  var el = document.createElement("div");
  el.className = "msg msg-" + kind;
  if (kind === "you" || kind === "alex") {
    var who = document.createElement("span");
    who.className = "who";
    who.textContent = kind === "you" ? "You" : "Alex";
    el.appendChild(who);
  }
  var body = document.createElement("span");
  body.textContent = text || "";
  el.appendChild(body);
  var t = $("transcript");
  t.appendChild(el);
  t.scrollTop = t.scrollHeight;
  return body;
}

// --- Mood chips ------------------------------------------------------------
function buildMoodChips() {
  var wrap = $("mood-chips");
  wrap.innerHTML = "";
  for (var i = 1; i <= 10; i++) {
    (function (n) {
      var b = document.createElement("button");
      b.className = "mood-chip";
      b.type = "button";
      b.textContent = String(n);
      b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", function () { pickMood(n); });
      wrap.appendChild(b);
    })(i);
  }
}
function showMood(phase) {
  state.moodPhase = phase;
  $("mood-label").textContent = phase === "open"
    ? "How are you arriving? (1–10)"
    : "And how are you leaving things? (1–10)";
  $("mood-row").hidden = false;
}
function hideMood() { $("mood-row").hidden = true; }
function pickMood(n) {
  var body = { session_id: state.sessionId, mood: n };
  var path = state.moodPhase === "open" ? "/session/start" : "/session/end";
  // Mood is recorded alongside the lifecycle call; a lone mid-session chip just posts start.
  api(path, { method: "POST", body: JSON.stringify(body) }).catch(function () {});
  addMsg("note", "mood noted — " + n + "/10. thanks for marking it.");
  hideMood();
}

// --- Homework drawer -------------------------------------------------------
function openHomework() {
  $("scrim").hidden = false;
  $("homework-drawer").hidden = false;
  $("homework-list").innerHTML = '<p class="hw-empty">loading…</p>';
  api("/homework").then(function (r) { return r.json(); }).then(function (d) {
    var items = (d && d.homework) || [];
    if (!items.length) { $("homework-list").innerHTML = '<p class="hw-empty">Nothing open right now. That\'s okay.</p>'; return; }
    $("homework-list").innerHTML = "";
    items.forEach(function (h) {
      var row = document.createElement("div");
      row.className = "hw-item";
      var chk = document.createElement("button");
      chk.className = "hw-check"; chk.type = "button"; chk.textContent = "○";
      chk.setAttribute("aria-label", "Mark done");
      chk.addEventListener("click", function () {
        api("/homework/" + encodeURIComponent(h.id) + "/done", { method: "POST" })
          .then(function () { row.style.opacity = "0.5"; chk.textContent = "●"; });
      });
      var info = document.createElement("div");
      var title = document.createElement("div"); title.className = "hw-title"; title.textContent = h.title || "(untitled)";
      var meta = document.createElement("div"); meta.className = "hw-meta"; meta.textContent = "set " + (h.assigned_date || "");
      info.appendChild(title); info.appendChild(meta);
      row.appendChild(chk); row.appendChild(info);
      $("homework-list").appendChild(row);
    });
  }).catch(function () {
    $("homework-list").innerHTML = '<p class="hw-empty">Couldn\'t load homework right now.</p>';
  });
}
function closeHomework() { $("homework-drawer").hidden = true; $("scrim").hidden = true; }

// --- Prep for Shreya (graceful stub) --------------------------------------
function prepForShreya() {
  api("/export/review", { method: "POST", body: JSON.stringify({}) })
    .then(function (r) { return r.json(); })
    .then(function (d) { addMsg("note", (d && d.message) || "Prep for Shreya lands in a later phase."); })
    .catch(function () { addMsg("note", "Prep for Shreya lands in a later phase."); });
}

// --- The turn (SSE over fetch) --------------------------------------------
function sendTurn(text) {
  if (!text.trim() || state.streaming) return;
  addMsg("you", text);
  $("input").value = "";
  autoGrow();
  state.streaming = true;
  $("send").disabled = true;
  var alexBody = addMsg("alex", "");
  alexBody.parentNode.classList.add("typing");
  alexBody.textContent = "…";
  var acc = "";
  var isCrisis = false;

  api("/turn", { method: "POST", body: JSON.stringify({ session_id: state.sessionId, text: text }) })
    .then(function (resp) {
      if (!resp.body) { return resp.text().then(function () {}); }
      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buf = "";
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) return;
          buf += decoder.decode(res.value, { stream: true });
          var parts = buf.split("\n\n");
          buf = parts.pop();
          parts.forEach(function (block) {
            var line = block.replace(/^data:\s?/, "");
            if (!line) return;
            var ev;
            try { ev = JSON.parse(line); } catch (e) { return; }
            if (ev.type === "meta") {
              isCrisis = !!ev.crisis;
              if (isCrisis) { alexBody.parentNode.classList.add("msg-crisis"); }
              alexBody.parentNode.classList.remove("typing");
              alexBody.textContent = "";
            } else if (ev.type === "token") {
              if (alexBody.textContent === "…") alexBody.textContent = "";
              acc += ev.text;
              alexBody.textContent = acc;
              $("transcript").scrollTop = $("transcript").scrollHeight;
            }
          });
          return pump();
        });
      }
      return pump();
    })
    .catch(function () {
      alexBody.parentNode.classList.remove("typing");
      alexBody.textContent = "I couldn't reach my words just now — a hiccup on my end. Try again in a moment.";
    })
    .then(function () {
      state.streaming = false;
      $("send").disabled = false;
      if (!acc) { alexBody.parentNode.classList.remove("typing"); }
    });
}

function autoGrow() {
  var ta = $("input");
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 140) + "px";
}

// --- WebAuthn nag (D3 rider 3) --------------------------------------------
function passkeyRegistered() { try { return localStorage.getItem(PASSKEY_KEY) === "1"; } catch (e) { return false; } }
function maybeShowNag() { $("passkey-nag").hidden = passkeyRegistered(); }
function registerPasskey() {
  var done = function () {
    try { localStorage.setItem(PASSKEY_KEY, "1"); } catch (e) {}
    api("/webauthn/register", { method: "POST", body: "{}" }).catch(function () {});
    $("passkey-nag").hidden = true;
  };
  // On the tailscale HTTPS origin this becomes a real ceremony; on plain loopback we stub it.
  if (window.PublicKeyCredential && window.isSecureContext) {
    try {
      navigator.credentials.create({
        publicKey: {
          challenge: new Uint8Array(16),
          rp: { name: "The Room" },
          user: { id: new Uint8Array(8), name: "prax", displayName: "Prax" },
          pubKeyCredParams: [{ type: "public-key", alg: -7 }],
          timeout: 20000
        }
      }).then(done).catch(done);
    } catch (e) { done(); }
  } else { done(); }
}

// --- Pairing ---------------------------------------------------------------

// Pairing-code alphabet — mirrors safety/pairing.py _CODE_ALPHABET (Crockford base32
// minus the visually ambiguous I/L/O/U/0/1). We format the field the way the code is
// shown on the Mac — uppercase, GROUP-hyphen-GROUP — so phone entry mirrors it exactly
// and you never type the hyphen or reach for Shift. The server canonicalises anyway
// (_canonical_code: upper + drop non-alphabet), so this is ergonomics, never the gate.
var PAIR_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ";
function formatPairCode(raw) {
  var up = (raw || "").toUpperCase();
  var kept = "";
  for (var i = 0; i < up.length && kept.length < 8; i++) {
    if (PAIR_ALPHABET.indexOf(up.charAt(i)) !== -1) { kept += up.charAt(i); }
  }
  return kept.length > 4 ? kept.slice(0, 4) + "-" + kept.slice(4) : kept;
}

function showPairing() { $("pair-screen").hidden = false; $("room").hidden = true; }
function showRoom() { $("pair-screen").hidden = true; $("room").hidden = false; }
function submitPairing() {
  var code = $("pair-code").value.trim();
  $("pair-error").hidden = true;
  api("/pair", { method: "POST", body: JSON.stringify({ code: code, label: "phone" }) })
    .then(function (r) {
      if (!r.ok) { throw new Error(r.status === 429 ? "Too many tries — wait a bit." : "That code didn't work."); }
      return r.json();
    })
    .then(function (d) {
      try { localStorage.setItem(TOKEN_KEY, d.device_token); } catch (e) {}
      startSession();
    })
    .catch(function (err) { $("pair-error").textContent = err.message || "Pairing failed."; $("pair-error").hidden = false; });
}

// --- Session ---------------------------------------------------------------
function startSession() {
  showRoom();
  buildMoodChips();
  api("/session/start", { method: "POST", body: JSON.stringify({}) })
    .then(function (r) { if (r.status === 401) { showPairing(); throw new Error("unpaired"); } return r.json(); })
    .then(function (d) {
      state.sessionId = d.session_id;
      if (d.repair_ack) addMsg("note", d.repair_ack);
      addMsg("alex", d.greeting || "It's good to see you. How are you right now, Prax — honestly, this moment?");
      showMood("open");
      maybeShowNag();
    })
    .catch(function () {});
}

// --- Wire up ---------------------------------------------------------------
function init() {
  initTheme();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }
  $("help-now").addEventListener("click", openCrisis);
  $("crisis-close").addEventListener("click", closeCrisis);
  $("homework-btn").addEventListener("click", openHomework);
  $("homework-close").addEventListener("click", closeHomework);
  $("scrim").addEventListener("click", closeHomework);
  $("shreya-btn").addEventListener("click", prepForShreya);
  $("passkey-register").addEventListener("click", registerPasskey);
  $("passkey-dismiss").addEventListener("click", function () { $("passkey-nag").hidden = true; });
  $("mood-skip").addEventListener("click", hideMood);
  $("pair-submit").addEventListener("click", submitPairing);
  var pairCode = $("pair-code");
  pairCode.addEventListener("input", function () {
    var formatted = formatPairCode(pairCode.value);
    if (pairCode.value !== formatted) { pairCode.value = formatted; }
  });
  pairCode.addEventListener("keydown", function (e) { if (e.key === "Enter") submitPairing(); });

  var form = $("composer-form");
  form.addEventListener("submit", function (e) { e.preventDefault(); sendTurn($("input").value); });
  $("input").addEventListener("input", autoGrow);
  $("input").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendTurn($("input").value); }
  });

  if (deviceToken()) { startSession(); } else { showPairing(); }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else { init(); }

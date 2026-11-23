// DMD Mining's notifications (web push), the same way as the pool's and DMD Stats': the bell in
// the top bar with this device's recent notices, the Notifications card on the home page where it
// chooses the pools it follows, and a bell on each pool (its row, its page) to follow it in one tap.
// The server keeps the choices with the browser's subscription (/push) and sends the notices;
// turning them off removes both. Nothing else is sent anywhere.
(function () {
  "use strict";
  function $(id) { return document.getElementById(id); }
  var box = $("dmd-bellbox"), card = $("notifications");
  var api = window.DMNotify = { available: function () { return false; }, mark: function () {}, setPools: function () {} };
  if (!box) return;
  var full = !!card;
  var bell = $("dmd-bell"), panel = $("dmd-bell-panel");
  var list = panel.querySelector(".dmd-bell-list"), empty = panel.querySelector(".dmd-bell-empty");
  var all = panel.querySelector(".dmd-bell-all"), settings = panel.querySelector(".dmd-bell-settings");
  var actions = panel.querySelector(".dmd-bell-actions"), bellOn = panel.querySelector(".dmd-bell-on");
  var bellOff = panel.querySelector(".dmd-bell-off"), bellTest = panel.querySelector(".dmd-bell-test");
  var form = $("dmd-notify-form"), badge = $("dmd-notify-state"), msg = $("dmd-notify-msg");
  var turnOn = $("dmd-notify-on"), turnOff = $("dmd-notify-off"), test = $("dmd-notify-test");
  var followList = $("mx-follow-list");

  var SEEN = "dmd-mining-seen", PICKED = "dmd-mining-picked";
  var config = null, sub = null, on = false, loaded = false, busy = false, testing = false;
  var items = [], prefs = { pools: [], problems: true, majority: false }, pools = [], note = "", told = "", saveTimer = null;
  var can = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  var iphone = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  var inApp = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  try { var picked = JSON.parse(localStorage.getItem(PICKED) || "null"); if (picked && Array.isArray(picked.pools)) prefs = picked; } catch (e) {}

  function blocked() { return can && Notification.permission === "denied"; }
  function possible() { return loaded && can && !blocked() && config && config.enabled; }
  function say(text, bad) {
    if (!full) { told = text || ""; if (text && panel.hidden) open(true); return; }
    msg.textContent = text || ""; msg.className = "dmd-small" + (bad ? " bad" : "");
  }
  function remember() { try { localStorage.setItem(PICKED, JSON.stringify(prefs)); } catch (e) {} }
  function post(data) {
    return fetch("/push", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) throw new Error(j.error || (r.status === 429 ? "Too many requests: wait a moment." : "The server did not answer. Try again in a moment."));
          return j;
        });
      });
  }
  function nameOf(slug) {
    var p = pools.filter(function (x) { return x.slug === slug; })[0];
    if (p) return p.name;
    var b = document.querySelector('[data-follow="' + slug + '"]');
    return (b && b.getAttribute("data-follow-name")) || slug;
  }

  // ------------------------------------------------------------------ the card: the pools to follow
  function drawFollow() {
    if (!followList) return;
    followList.textContent = "";
    var shown = pools.filter(function (p) { return p.blocks["30d"] > 0 || p.status === "up" || prefs.pools.indexOf(p.slug) >= 0; });
    if (!shown.length) { followList.innerHTML = '<li class="mx-muted">No pool is mining right now.</li>'; return; }
    shown.forEach(function (p) {
      var li = document.createElement("li"), label = document.createElement("label"), input = document.createElement("input");
      input.type = "checkbox"; input.value = p.slug; input.checked = prefs.pools.indexOf(p.slug) >= 0;
      input.addEventListener("change", function () { toggle(p.slug, input.checked); });
      var t = document.createElement("span"); t.className = "t";
      var b = document.createElement("b"); b.textContent = p.name;
      var s = document.createElement("small");
      s.textContent = (p.blocks["24h"] ? p.blocks["24h"] + " blocks in 24h" : p.last_block ? "last block " + window.DM.ago(p.last_block.time) : "no block yet") +
        (p.schemes && p.schemes.length ? " · " + p.schemes.map(function (x) { return x === "SOLO" ? "solo" : x; }).join(", ") : "");
      t.appendChild(b); t.appendChild(s);
      label.appendChild(input);
      if (window.DM) label.appendChild(window.DM.logo(p, 28));
      label.appendChild(t);
      li.appendChild(label);
      followList.appendChild(li);
    });
  }
  function readOptions() {
    if (form) { prefs.problems = form.elements.problems.checked; prefs.majority = form.elements.majority.checked; }
  }
  function fillOptions() {
    if (form) { form.elements.problems.checked = prefs.problems !== false; form.elements.majority.checked = !!prefs.majority; }
  }
  if (form) form.addEventListener("change", function (e) {
    if (e.target.name === "problems" || e.target.name === "majority") { readOptions(); remember(); changed(); }
  });

  // One pool followed or not (a checkbox, or a pool's bell)
  function toggle(slug, yes) {
    var i = prefs.pools.indexOf(slug);
    if (yes && i < 0) {
      if (prefs.pools.length >= ((config && config.max_pools) || 20)) { say("You can follow 20 pools at most.", true); drawButtons(); drawFollow(); return; }
      prefs.pools.push(slug);
    }
    if (!yes && i >= 0) prefs.pools.splice(i, 1);
    remember();
    drawButtons();
    if (full) drawFollow();
    if (on) changed();
  }
  function drawButtons() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-follow]"), mark);
  }
  function mark(b) {
    var slug = b.getAttribute("data-follow"), name = b.getAttribute("data-follow-name") || slug;
    var yes = on && prefs.pools.indexOf(slug) >= 0;
    b.setAttribute("aria-pressed", yes ? "true" : "false");
    b.title = yes ? "You get a notice when " + name + " finds a block: tap to stop" : "Notify me when " + name + " finds a block";
    b.setAttribute("aria-label", b.title);
    b.hidden = !possible() && !(iphone && !inApp && !can);
    var text = b.querySelector("span");
    if (text) text.textContent = yes ? "Following" : "Notify me";
  }
  api.available = function () { return possible() || (iphone && !inApp && !can); };
  api.mark = mark;
  api.setPools = function (list) { pools = list || []; if (full) drawFollow(); drawButtons(); };
  document.addEventListener("click", function (event) {
    var b = event.target.closest && event.target.closest("[data-follow]");
    if (!b) return;
    event.preventDefault();
    event.stopPropagation();
    var slug = b.getAttribute("data-follow");
    if (!can && iphone && !inApp) { say("On an iPhone, notifications come through the app: add DMD Mining to your Home Screen, open it, and turn them on there."); return; }
    if (on) { toggle(slug, prefs.pools.indexOf(slug) < 0); return; }
    if (prefs.pools.indexOf(slug) < 0) prefs.pools.push(slug);
    remember();
    start("Notifications are on: you'll get a notice each time " + nameOf(slug) + " finds a block.");
  });

  function changed() {
    if (!on) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 500);
  }
  function save() {
    if (!sub) return;
    post({ action: "update", endpoint: sub.endpoint, prefs: prefs }).then(function (r) {
      prefs = r.prefs || prefs; remember(); fillOptions(); drawButtons(); if (full) drawFollow();
      say(prefs.pools.length ? "Saved: this device follows " + prefs.pools.map(nameOf).join(", ") + "." : "Saved: you follow no pool for now.");
    }).catch(function (err) { say(err.message, true); });
  }

  // ------------------------------------------------------------------ on and off
  function key() {
    var s = config.key.replace(/-/g, "+").replace(/_/g, "/"); s += "===".slice((s.length + 3) % 4);
    var raw = atob(s), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function sameKey(s) {
    var k = s.options && s.options.applicationServerKey;
    if (!k) return true;
    var a = new Uint8Array(k), b = key();
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }
  function start(done) {
    if (busy || !config || !config.enabled) return;
    readOptions();
    busy = true; note = "Turning on…"; draw();
    Notification.requestPermission().then(function (p) {
      if (p !== "granted") throw new Error(p === "denied" ? "Notifications are blocked for this site in your browser settings." : "Notifications were not allowed.");
      return navigator.serviceWorker.ready;
    }).then(function (reg) {
      return reg.pushManager.getSubscription().then(function (s) {
        if (s && !sameKey(s)) return s.unsubscribe().then(function () { return null; });
        return s;
      }).then(function (s) { return s || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key() }); });
    }).then(function (s) {
      sub = s;
      return post({ action: "subscribe", subscription: s.toJSON(), prefs: prefs });
    }).then(function (r) {
      on = true; note = ""; items = r.items || [];
      prefs = r.prefs || prefs; remember(); fillOptions();
      say(done || (prefs.pools.length ? "Notifications are on for this device. Send yourself a test notice to check."
        : "Notifications are on. Tick the pools you want to hear about, or tap a pool's bell."));
    }).catch(function (err) {
      note = ""; say((err && err.message) || "Something went wrong. Try again in a moment.", true);
    }).then(function () { busy = false; draw(); drawButtons(); if (full) drawFollow(); });
  }
  function stop() {
    if (busy || !sub) return;
    busy = true; draw();
    var s = sub;
    post({ action: "unsubscribe", endpoint: s.endpoint }).then(function () { return s.unsubscribe(); }).then(function () {
      sub = null; on = false; items = [];
      say("Notifications are off on this device.");
    }).catch(function (err) { say((err && err.message) || "Something went wrong. Try again in a moment.", true); })
      .then(function () { busy = false; draw(); drawButtons(); });
  }
  function sendTest() {
    if (!sub || testing) return;
    testing = true; draw();
    post({ action: "test", endpoint: sub.endpoint }).then(function () {
      say("A test notice is on its way: it should arrive within a few seconds.");
    }).catch(function (err) { say(err.message, true); }).then(function () {
      setTimeout(function () { testing = false; draw(); }, 10000);
      draw();
    });
  }

  // ------------------------------------------------------------------ the bell
  function seen() { try { return JSON.parse(localStorage.getItem(SEEN) || "[]"); } catch (e) { return []; } }
  function keepSeen(ids) { try { localStorage.setItem(SEEN, JSON.stringify(ids.slice(-500))); } catch (e) {} }
  function fresh() { var s = seen(); return items.filter(function (i) { return s.indexOf(i.id) < 0; }); }
  function ago(t) {
    var s = Math.max(0, Math.round(Date.now() / 1000 - t));
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    return new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function draw() {
    var news = fresh();
    bell.setAttribute("data-unread", news.length ? "1" : "0");
    bell.title = news.length ? news.length + (news.length > 1 ? " new notifications" : " new notification") : "Notifications";
    bell.setAttribute("aria-label", bell.title);
    list.textContent = "";
    news.forEach(function (item) {
      var li = document.createElement("li"), b = document.createElement("button");
      var head = document.createElement("span"), title = document.createElement("b"), when = document.createElement("time");
      var body = document.createElement("span");
      b.type = "button"; b.title = "Open, and mark as seen";
      title.textContent = item.title;
      when.textContent = ago(item.time);
      when.dateTime = new Date(item.time * 1000).toISOString();
      body.textContent = item.body;
      head.className = "dmd-bell-item-head"; body.className = "dmd-bell-item-body";
      head.appendChild(title); head.appendChild(when);
      b.appendChild(head); b.appendChild(body);
      b.addEventListener("click", function (event) {
        event.stopPropagation();
        keepSeen(seen().concat([item.id]));
        if (item.url && item.url.charAt(0) === "/" && item.url !== location.pathname) location.href = item.url; else draw();
      });
      li.appendChild(b);
      list.appendChild(li);
    });
    empty.hidden = news.length > 0 && !note && !told;
    var why = "";
    if (!can && iphone && !inApp) why = 'On an iPhone, notifications come through the app: <a href="#get-the-app">add it to your Home Screen</a>, open it, and turn them on there.';
    else if (!can) why = "This browser cannot show notifications.";
    else if (blocked()) why = "Notifications are blocked for this site in your browser settings.";
    else if (loaded && config && !config.enabled) why = "Notifications are not available right now.";
    if (note) empty.textContent = note;
    else if (told) empty.textContent = told;
    else if (!loaded) empty.textContent = "Loading…";
    else if (on) empty.textContent = prefs.pools.length ? "You're all caught up." : "You follow no pool yet: tap a pool's bell to follow it.";
    else if (why) empty.innerHTML = why;
    else empty.textContent = "Get a notice on this device each time a pool you follow finds a block, even when this page is closed.";
    all.hidden = news.length < 2;
    actions.hidden = on || !possible();
    bellOn.disabled = busy;
    bellOff.hidden = bellTest.hidden = !on;
    bellOff.disabled = busy;
    bellTest.disabled = busy || testing;
    if (!full) return;
    turnOn.disabled = busy;
    turnOff.hidden = test.hidden = !on;
    turnOff.disabled = busy;
    test.disabled = busy || testing;
    turnOn.hidden = on || !possible();
    badge.textContent = on ? "On" : "Off";
    badge.className = "dmd-badge" + (on ? " on" : "");
    if (loaded && !on && why && !msg.textContent) { msg.innerHTML = why; msg.className = "dmd-small"; }
  }
  function open(yes) {
    panel.hidden = !yes;
    bell.setAttribute("aria-expanded", yes ? "true" : "false");
    if (!yes) told = "";
    if (yes) draw();
  }
  function load() {
    var ready = config ? Promise.resolve(config) : fetch("/push", { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : { enabled: false }; })
      .catch(function () { return { enabled: false }; });
    return ready.then(function (c) {
      config = c;
      box.hidden = false;
      if (!can || !c.enabled) return { on: false };
      return navigator.serviceWorker.ready.then(function (reg) { return reg.pushManager.getSubscription(); }).then(function (s) {
        sub = s;
        if (!s) return { on: false };
        return post({ action: "get", endpoint: s.endpoint }).catch(function () { return { on: false }; });
      });
    }).then(function (r) {
      loaded = true;
      on = !!r.on;
      items = r.items || [];
      if (on && !saveTimer) { prefs = r.prefs || prefs; remember(); }
      fillOptions();
      draw(); drawButtons(); if (full) drawFollow();
    }).catch(function () { loaded = true; draw(); drawButtons(); });
  }

  bell.addEventListener("click", function (event) { event.stopPropagation(); open(panel.hidden); });
  all.addEventListener("click", function (event) { event.stopPropagation(); keepSeen(seen().concat(items.map(function (i) { return i.id; }))); draw(); });
  bellOn.addEventListener("click", function (event) { event.stopPropagation(); start(); });
  bellOff.addEventListener("click", function (event) { event.stopPropagation(); stop(); });
  bellTest.addEventListener("click", function (event) { event.stopPropagation(); sendTest(); });
  if (full) {
    turnOn.addEventListener("click", function () { start(); });
    turnOff.addEventListener("click", stop);
    test.addEventListener("click", sendTest);
  }
  document.addEventListener("click", function (event) { if (!panel.hidden && !box.contains(event.target)) open(false); });
  document.addEventListener("keydown", function (event) { if (event.key === "Escape" && !panel.hidden) { open(false); bell.focus(); } });
  settings.addEventListener("click", function (event) {
    if (!full) return;
    event.preventDefault();
    open(false);
    card.scrollIntoView({ behavior: "smooth", block: "start" });
    card.classList.remove("dmd-flash");
    void card.offsetWidth;
    card.classList.add("dmd-flash");
  });
  if ("serviceWorker" in navigator) navigator.serviceWorker.addEventListener("message", function (event) {
    if (event.data && event.data.type === "dmd-mining-notice") load();
  });
  if (full && location.hash === "#notifications") card.classList.add("dmd-flash");
  fillOptions();
  draw();
  setInterval(function () { if (!document.hidden) load(); }, 60000);
  load();
})();

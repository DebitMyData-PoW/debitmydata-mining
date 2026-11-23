// DMD Mining: what every page shares. The theme switch, the formats (hashrate, ages, DMD), the
// pools' logos and colours, the little charts in the pools' rows, and reading the site's files
// (/api/*.json, written by the server every 20 seconds). Nothing here sends anything.
(function () {
  "use strict";
  var root = document.documentElement;
  var DM = window.DM = {};

  DM.$ = function (id) { return document.getElementById(id); };
  DM.el = function (tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  };
  DM.getJSON = function (path) {
    return fetch(path, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error(path + ": " + r.status);
      return r.json();
    });
  };

  // ------------------------------------------------------------------ formats
  function none(v) { return v === null || v === undefined || (typeof v === "number" && isNaN(v)); }
  DM.none = none;
  DM.hashrate = function (v) {
    if (none(v)) return "–";
    var units = [[1e18, "EH/s"], [1e15, "PH/s"], [1e12, "TH/s"], [1e9, "GH/s"], [1e6, "MH/s"], [1e3, "kH/s"]];
    for (var i = 0; i < units.length; i++) {
      if (v >= units[i][0]) return (v / units[i][0]).toLocaleString("en-US", { maximumFractionDigits: v / units[i][0] >= 100 ? 0 : 2 }) + " " + units[i][1];
    }
    return Math.round(v) + " H/s";
  };
  DM.number = function (v, digits) {
    return none(v) ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: digits === undefined ? 0 : digits });
  };
  DM.big = function (v) {
    if (none(v)) return "–";
    var units = [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]];
    for (var i = 0; i < units.length; i++) {
      if (v >= units[i][0]) return (v / units[i][0]).toLocaleString("en-US", { maximumFractionDigits: 2 }) + units[i][1];
    }
    return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  };
  DM.percent = function (v, digits) {
    return none(v) ? "–" : (v * 100).toLocaleString("en-US", { maximumFractionDigits: digits === undefined ? 1 : digits }) + "%";
  };
  DM.dmd = function (v) { return none(v) ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: 2 }) + " DMD"; };
  DM.fee = function (v) { return none(v) ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: 2 }) + "%"; };
  DM.duration = function (s) {
    if (none(s)) return "–";
    s = Math.max(0, Math.round(s));
    if (s < 60) return s + " s";
    if (s < 3600) { var m = Math.floor(s / 60), r = s % 60; return m + " min" + (r && m < 10 ? " " + r + " s" : ""); }
    if (s < 86400) { var h = Math.floor(s / 3600), mm = Math.round((s % 3600) / 60); return h + " h" + (mm ? " " + mm + " min" : ""); }
    var d = s / 86400;
    d = d >= 10 ? Math.round(d) : Math.round(d * 10) / 10;
    return d + (d === 1 ? " day" : " days");
  };
  DM.ago = function (t) {
    if (none(t)) return "–";
    var s = Math.max(0, Math.round(Date.now() / 1000 - t));
    if (s < 60) return s + " s ago";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    var d = Math.floor(s / 86400);
    return d + (d > 1 ? " days ago" : " day ago");
  };
  DM.date = function (t) {
    return none(t) ? "–" : new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  };

  // ------------------------------------------------------------------ pools: colours and logos
  // Each mining pool keeps its colour everywhere (the server gives it: summary.json's "color").
  DM.colors = {};
  DM.setPools = function (pools) {
    (pools || []).forEach(function (p) { DM.colors[p.slug] = p.color; });
  };
  DM.colorClass = function (slug) {
    var n = slug ? DM.colors[slug] : null;
    return n === null || n === undefined ? "cx" : "c" + n;
  };
  DM.colorHex = function (slug) {
    var name = DM.colorClass(slug).replace("c", "--c");
    return getComputedStyle(root).getPropertyValue(name).trim() || "#a3a0ab";
  };
  DM.logo = function (pool, size) {
    var box = DM.el("span", "mx-logo " + DM.colorClass(pool.slug));
    if (size) box.style.setProperty("--s", size + "px");
    function letter() {
      box.classList.add("letter");
      box.textContent = (pool.name || pool.slug || "?").replace(/^the /i, "").charAt(0).toUpperCase();
    }
    if (pool.logo) {
      var img = new Image();
      img.alt = "";
      img.width = size || 32;
      img.height = size || 32;
      img.decoding = "async";
      img.onerror = function () { img.remove(); letter(); };
      img.src = pool.logo;
      box.appendChild(img);
    } else {
      letter();
    }
    return box;
  };
  DM.status = function (pool) {
    var words = { up: "Answering", down: "Not answering", behind: "Node behind", none: "No API" };
    var s = DM.el("span", "mx-status " + pool.status, words[pool.status] || pool.status);
    if (pool.status === "down" && pool.error) s.title = "Its API: " + pool.error;
    if (pool.status === "none") s.title = "This pool has no public API: its figures come from the chain";
    if (pool.status === "behind") s.title = "Its node is behind the chain: its miners may be working on old blocks";
    return s;
  };
  DM.schemeChips = function (schemes) {
    var frag = document.createDocumentFragment();
    (schemes || []).forEach(function (s) {
      frag.appendChild(DM.el("span", "mx-chip " + (s === "SOLO" ? "solo" : "pplns"), s === "SOLO" ? "Solo" : s));
    });
    return frag;
  };

  // A small chart in a pool's row: its hashrate (a line), or its blocks (bars) for a pool without
  // an API, over the last 24 hours.
  DM.spark = function (values, bars) {
    var ns = "http://www.w3.org/2000/svg", W = 88, H = 28;
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("class", "mx-spark");
    svg.setAttribute("aria-hidden", "true");
    var known = values.filter(function (v) { return v !== null; });
    var max = Math.max.apply(null, known.concat([0]));
    if (!known.length || max <= 0) {
      var flat = document.createElementNS(ns, "path");
      flat.setAttribute("d", "M1 " + (H - 2) + "H" + (W - 1));
      flat.setAttribute("class", "line");
      flat.setAttribute("opacity", ".35");
      svg.appendChild(flat);
      return svg;
    }
    var step = (W - 2) / Math.max(1, values.length - 1);
    if (bars) {
      var w = Math.max(1.5, (W - 2) / values.length - 1.2);
      values.forEach(function (v, i) {
        if (!v) return;
        var h = Math.max(2, (v / max) * (H - 3));
        var r = document.createElementNS(ns, "rect");
        r.setAttribute("x", (1 + i * (W - 2) / values.length).toFixed(1));
        r.setAttribute("y", (H - h).toFixed(1));
        r.setAttribute("width", w.toFixed(1));
        r.setAttribute("height", h.toFixed(1));
        r.setAttribute("rx", "1");
        svg.appendChild(r);
      });
      return svg;
    }
    var d = "", first = null, last = null;
    values.forEach(function (v, i) {
      if (v === null) return;
      var x = 1 + i * step, y = H - 2 - (v / max) * (H - 5);
      d += (first === null ? "M" : "L") + x.toFixed(1) + " " + y.toFixed(1);
      if (first === null) first = x;
      last = x;
    });
    var area = document.createElementNS(ns, "path");
    area.setAttribute("d", d + "L" + last.toFixed(1) + " " + H + "L" + first.toFixed(1) + " " + H + "Z");
    area.setAttribute("class", "area");
    var line = document.createElementNS(ns, "path");
    line.setAttribute("d", d);
    line.setAttribute("class", "line");
    svg.appendChild(area);
    svg.appendChild(line);
    return svg;
  };

  // ------------------------------------------------------------------ charts' colours
  DM.chartTheme = function () {
    var dark = root.getAttribute("data-theme") === "dark";
    return { fore: dark ? "#8f8a9b" : "#6e6a78", grid: dark ? "#25222d" : "#f1eff4", tooltip: dark ? "dark" : "light",
      surface: dark ? "#141318" : "#ffffff", text: dark ? "#f7f5fa" : "#13111a", network: dark ? "#bdb8c8" : "#4a4654" };
  };
  DM.onTheme = [];

  // ------------------------------------------------------------------ the theme switch
  var toggle = DM.$("dmd-theme-toggle");
  function dark() { return root.getAttribute("data-theme") === "dark"; }
  function label() {
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", dark() ? "#0b0a0f" : "#ffffff");
    if (!toggle) return;
    toggle.setAttribute("aria-label", dark() ? "Switch to the light theme" : "Switch to the dark theme");
    toggle.title = dark() ? "Light theme" : "Dark theme";
  }
  if (toggle) toggle.addEventListener("click", function () {
    var t = dark() ? "light" : "dark";
    root.setAttribute("data-theme", t);
    root.style.colorScheme = t;
    try { localStorage.setItem("dmd-theme-mining", t); } catch (e) {}
    var secure = location.protocol === "https:" ? "; secure" : "";
    document.cookie = "dmd-theme-mining=" + t + "; path=/; max-age=31536000; samesite=lax" + secure;
    label();
    DM.onTheme.forEach(function (fn) { fn(); });
  });
  label();
  var year = DM.$("dmd-year");
  if (year) year.textContent = String(new Date().getFullYear());

  // Copy buttons (stratum addresses)
  document.addEventListener("click", function (event) {
    var b = event.target.closest && event.target.closest("[data-copy]");
    if (!b) return;
    var text = b.getAttribute("data-copy"), span = b.querySelector("span") || b;
    function done() {
      b.classList.add("done");
      if (span) span.textContent = "Copied";
      setTimeout(function () { b.classList.remove("done"); if (span) span.textContent = "Copy"; }, 1600);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () {});
    else {
      var area = DM.el("textarea"); area.value = text; document.body.appendChild(area); area.select();
      try { document.execCommand("copy"); done(); } catch (e) {}
      area.remove();
    }
  });

  DM.icon = {
    bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>',
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>',
    out: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M7 17L17 7M9 7h8v8"/></svg>'
  };
  // A pool's "Notify me" bell (js/notify.js makes it work)
  DM.followButton = function (pool) {
    var b = DM.el("button", "mx-follow-btn");
    b.type = "button";
    b.setAttribute("data-follow", pool.slug);
    b.setAttribute("data-follow-name", pool.name);
    b.setAttribute("aria-pressed", "false");
    b.title = "Notify me when " + pool.name + " finds a block";
    b.setAttribute("aria-label", b.title);
    b.innerHTML = DM.icon.bell;
    b.hidden = !window.DMNotify || !window.DMNotify.available();
    if (window.DMNotify) window.DMNotify.mark(b);
    return b;
  };
})();

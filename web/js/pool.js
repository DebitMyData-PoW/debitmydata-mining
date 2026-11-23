// A pool's page (/pool/<slug>): how to connect, its figures, its charts and the blocks it found,
// from /api/pools/<slug>.json (written every 20 seconds); read again every minute.
(function () {
  "use strict";
  var DM = window.DM, $ = DM.$, el = DM.el;
  var match = location.pathname.match(/^\/pool\/([a-z0-9]{1,40})\/?$/);
  var slug = match ? match[1] : new URLSearchParams(location.search).get("pool");
  var state = { pool: null, range: "24h", shown: 25 };
  var chart = null, bars = null;

  function put(id, value, sub) {
    $(id).textContent = value;
    if (sub !== undefined) $(id + "-sub").textContent = sub;
  }
  function row(dl, label, value) {
    var div = el("div"), dt = el("dt", null, label), dd = el("dd");
    if (typeof value === "string") dd.textContent = value; else dd.appendChild(value);
    div.appendChild(dt); div.appendChild(dd); dl.appendChild(div);
  }
  function link(href, text, out) {
    var a = el("a", null, text);
    a.href = href;
    if (out) { a.target = "_blank"; a.rel = "noopener"; }
    return a;
  }

  // ------------------------------------------------------------------ the head
  function showHead(p) {
    document.title = p.name + " · DMD Mining";
    var head = $("mx-head");
    head.textContent = "";
    head.className = "mx-head " + DM.colorClass(p.slug);
    head.appendChild(DM.logo(p, 76));
    var mid = el("div");
    mid.appendChild(el("h1", null, p.name));
    var meta = el("div", "mx-meta");
    if (p.website) meta.appendChild(link(p.website, p.domain || p.website, true));
    if (p.country) meta.appendChild(el("span", null, (p.flag ? p.flag + " " : "") + p.country));
    meta.appendChild(DM.status(p));
    if (p.software) meta.appendChild(el("span", "mx-chip", p.software));
    meta.appendChild(DM.schemeChips(p.schemes));
    mid.appendChild(meta);
    head.appendChild(mid);
    var actions = el("div", "mx-actions");
    var follow = el("button", "dmd-button dmd-ghost");
    follow.type = "button";
    follow.setAttribute("data-follow", p.slug);
    follow.setAttribute("data-follow-name", p.name);
    follow.innerHTML = DM.icon.bell;
    follow.appendChild(el("span", null, "Notify me"));
    if (window.DMNotify) window.DMNotify.mark(follow);
    actions.appendChild(follow);
    if (p.website) {
      var go = el("a", "dmd-button");
      go.href = p.website; go.target = "_blank"; go.rel = "noopener";
      go.appendChild(document.createTextNode("Mine here "));
      go.insertAdjacentHTML("beforeend", DM.icon.out);
      actions.appendChild(go);
    }
    head.appendChild(actions);
  }

  // ------------------------------------------------------------------ the figures
  function showFigures(p) {
    if (p.api && p.hashrate !== null) {
      put("p-rate", DM.hashrate(p.hashrate), (p.hashrate_share ? DM.percent(p.hashrate_share) + " of the network · " : "") + "its API");
    } else {
      put("p-rate", p.hashrate_from_blocks_24h ? "≈ " + DM.hashrate(p.hashrate_from_blocks_24h) : "–",
        p.api ? "its API isn't answering; from its blocks" : "from its blocks (24h): no public API");
    }
    put("p-blocks", DM.number(p.blocks["24h"]), "7 days: " + DM.number(p.blocks["7d"]) + " · 30 days: " + DM.number(p.blocks["30d"]));
    put("p-last", p.last_block ? DM.ago(p.last_block.time) : "–", p.last_block ? "block " + DM.number(p.last_block.height) : "none yet");
    put("p-luck", p.luck_24h === null ? "–" : DM.percent(p.luck_24h, 0),
      p.luck_7d !== null ? "7 days: " + DM.percent(p.luck_7d, 0) : p.api ? "needs 12 hours of its figures" : "needs its API");
    put("p-miners", DM.none(p.miners) ? (DM.none(p.workers) ? "–" : DM.number(p.workers)) : DM.number(p.miners),
      DM.none(p.miners) && !DM.none(p.workers) ? "workers" : p.api ? "connected now" : "not published");
    var fee = p.fee_min === null ? "–" : p.fee_min === p.fee_max ? DM.fee(p.fee_min) : DM.fee(p.fee_min) + "–" + DM.fee(p.fee_max);
    put("p-fee", fee, p.schemes.map(function (s) { return s === "SOLO" ? "solo" : s; }).join(" + ") || "–");
    put("p-ttf", p.seconds_per_block ? DM.duration(p.seconds_per_block) : "–",
      p.seconds_per_block ? "on average, at its hashrate" : "needs its hashrate");
    put("p-total", DM.number(p.blocks_total), p.first_block ? "since block " + DM.number(p.first_block.height) : "");
  }

  // ------------------------------------------------------------------ how to connect
  function difficulty(e) {
    var parts = [];
    if (e.name) parts.push(e.name);
    if (e.vardiff && (e.vardiff.min || e.vardiff.max)) parts.push("difficulty " + DM.big(e.vardiff.min || e.difficulty) + "–" + (e.vardiff.max ? DM.big(e.vardiff.max) : "any"));
    else if (e.difficulty) parts.push("difficulty " + DM.big(e.difficulty));
    if (e.tls) parts.push("TLS");
    return parts.join(" · ");
  }
  function showConnect(p) {
    var box = $("mx-connect");
    box.textContent = "";
    var modes = (p.modes || []).filter(function (m) { return m.listed !== false; });
    if (!modes.length) {
      box.appendChild(el("p", "mx-muted", "Its operator hasn't published how to connect yet: see "));
      if (p.website) box.lastChild.appendChild(link(p.website, p.domain || "its website", true));
      return;
    }
    modes.forEach(function (m) {
      var div = el("div", "mx-mode");
      var head = el("div", "mx-mode-head");
      head.appendChild(el("h3", null, m.label || m.scheme || "Pool"));
      if (m.scheme) head.appendChild(DM.schemeChips([m.scheme]));
      var facts = [];
      if (!DM.none(m.fee)) facts.push(DM.fee(m.fee) + " fee");
      if (!DM.none(m.min_payout) && m.scheme !== "SOLO") facts.push("paid from " + DM.number(m.min_payout, 8) + " DMD");
      if (!DM.none(m.hashrate)) facts.push(DM.hashrate(m.hashrate));
      if (!DM.none(m.miners)) facts.push(m.miners + (m.miners === 1 ? " miner" : " miners"));
      if (facts.length) head.appendChild(el("span", "mx-facts", facts.join(" · ")));
      div.appendChild(head);
      var ul = el("ul", "mx-endpoints");
      (m.endpoints || []).forEach(function (e) {
        var li = el("li");
        li.appendChild(el("code", null, e.url));
        var copy = el("button", "mx-copy");
        copy.type = "button";
        copy.setAttribute("data-copy", e.url);
        copy.innerHTML = DM.icon.copy;
        copy.appendChild(el("span", null, "Copy"));
        copy.setAttribute("aria-label", "Copy " + e.url);
        li.appendChild(copy);
        var d = difficulty(e);
        if (d) li.appendChild(el("small", null, d));
        ul.appendChild(li);
      });
      if (!(m.endpoints || []).length) ul.appendChild(el("li", "mx-muted", "Its stratum address isn't published: see its website."));
      div.appendChild(ul);
      var login = el("dl", "mx-login");
      login.appendChild(el("dt", null, "Username"));
      login.appendChild(el("dd", null, p.username || "Your DMD address, optionally followed by a dot and a worker name"));
      login.appendChild(el("dt", null, "Password"));
      var pw = el("dd"); pw.appendChild(el("code", null, m.password || "x")); login.appendChild(pw);
      if (m.note) { login.appendChild(el("dt", null, "Note")); login.appendChild(el("dd", null, m.note)); }
      div.appendChild(login);
      box.appendChild(div);
    });
    if (p.account) box.appendChild(el("p", "mx-note", "This pool needs an account on its website before you connect."));
    if (p.notes) box.appendChild(el("p", "mx-note", p.notes));
    var guide = el("p", "mx-note");
    guide.appendChild(document.createTextNode("New to mining? "));
    guide.appendChild(link("https://debitmydata.io/#mining", "The step-by-step guide", true));
    guide.appendChild(document.createTextNode(", and a "));
    guide.appendChild(link("https://debitmydata.io/#wallets", "DMD wallet", true));
    guide.appendChild(document.createTextNode(" for your address."));
    box.appendChild(guide);
  }

  // ------------------------------------------------------------------ about it
  function showDetails(p) {
    var dl = $("mx-details");
    dl.textContent = "";
    if (p.website) row(dl, "Website", link(p.website, p.domain || p.website.replace(/^https?:\/\//, ""), true));
    if (p.software) row(dl, "Software", p.software);
    var api;
    if (!p.api) api = "No public API: its figures come from the chain";
    else if (p.status === "down") api = "Not answering" + (p.fail_since ? " since " + DM.ago(p.fail_since).replace(" ago", "") : "") + (p.error ? " (" + p.error + ")" : "");
    else api = "Answering, checked " + DM.ago(p.checked_at);
    row(dl, "Its API", api);
    if (p.api && p.height) {
      var tip = state.tip || p.height;
      row(dl, "Its node", tip - p.height > 1 ? "at block " + DM.number(p.height) + ", " + (tip - p.height) + " blocks behind the chain" : "at block " + DM.number(p.height) + ", up to date");
    }
    if (p.api && (p.uptime_24h !== null || p.uptime_7d !== null)) {
      row(dl, "Answered", DM.percent(p.uptime_24h) + " of the time in 24 hours" + (p.uptime_7d !== null ? ", " + DM.percent(p.uptime_7d) + " in 7 days" : ""));
    }
    if (p.effort !== null && p.effort !== undefined) row(dl, "Current round", DM.percent(p.effort, 0) + " of the work a block takes, on average");
    if (p.effort_30d !== null) row(dl, "Average effort (30 days)", DM.percent(p.effort_30d, 0) + " (under 100%: luckier than average)");
    if (p.mined_dmd !== null) row(dl, "DMD found", DM.dmd(p.mined_dmd) + " in " + DM.number(p.blocks_total) + " blocks");
    if (p.first_block) row(dl, "First block", "block " + DM.number(p.first_block.height) + ", " + DM.date(p.first_block.time));
    if (p.addresses && p.addresses.length) {
      var ul = el("ul", "mx-addresses");
      p.addresses.forEach(function (a) {
        var li = el("li");
        li.appendChild(link(p.explorer + "/address/" + encodeURIComponent(a), a, true));
        ul.appendChild(li);
      });
      row(dl, p.addresses.length > 1 ? "Its addresses" : "Its address", ul);
    }
    if (p.tags && p.tags.length) {
      var tags = el("span");
      p.tags.forEach(function (t, i) { if (i) tags.appendChild(document.createTextNode(", ")); tags.appendChild(el("code", null, t)); });
      row(dl, "Writes in its blocks", tags);
    }
    var edit = el("span");
    edit.appendChild(document.createTextNode("From "));
    edit.appendChild(link("https://github.com/DebitMyData-PoW/mining-pools", "DebitMyData's pool list", true));
    edit.appendChild(document.createTextNode(" (pool " + p.id + "): a mistake? Tell us at "));
    edit.appendChild(link("mailto:info@debitmydata.com", "info@debitmydata.com"));
    row(dl, "Listed", edit);
  }

  // ------------------------------------------------------------------ charts
  function drawCharts() {
    var p = state.pool;
    if (!p || !window.ApexCharts) return;
    var d = p.charts[state.range], c = DM.chartTheme(), color = DM.colorHex(p.slug);
    var times = d.times.map(function (t) { return t * 1000; });
    var fmt = state.range === "24h" ? "HH:mm" : state.range === "7d" ? "ddd HH:mm" : "MMM d";
    var series = [], colors = [], dashes = [], widths = [];
    var hasApi = d.reported.some(function (v) { return v !== null; });
    if (hasApi) { series.push({ name: "Its API", data: times.map(function (t, i) { return [t, d.reported[i]]; }) }); colors.push(color); dashes.push(0); widths.push(2); }
    series.push({ name: "From its blocks", data: times.map(function (t, i) { return [t, d.from_blocks[i]]; }) });
    colors.push(hasApi ? c.network : color); dashes.push(hasApi ? 5 : 0); widths.push(hasApi ? 1.5 : 2);
    var legend = $("mx-legend");
    legend.textContent = "";
    series.forEach(function (s, i) {
      var li = el("li", i === 0 && hasApi ? DM.colorClass(p.slug) : (hasApi ? "dash" : DM.colorClass(p.slug)));
      li.textContent = s.name;
      legend.appendChild(li);
    });
    legend.appendChild(el("li", DM.colorClass(p.slug), "Blocks found (below)"));
    var opts = {
      chart: { type: "line", height: 300, toolbar: { show: false }, zoom: { enabled: false }, animations: { enabled: false },
        fontFamily: "Inter, system-ui, sans-serif", foreColor: c.fore, background: "transparent", group: "pool", id: "rate" },
      series: series, colors: colors, stroke: { width: widths, curve: "straight", dashArray: dashes }, legend: { show: false },
      grid: { borderColor: c.grid, strokeDashArray: 3, padding: { left: 6, right: 10 } },
      xaxis: { type: "datetime", labels: { datetimeUTC: false, format: fmt }, axisBorder: { show: false }, axisTicks: { show: false }, tooltip: { enabled: false } },
      yaxis: { min: 0, forceNiceScale: true, labels: { minWidth: 64, formatter: function (v) { return DM.hashrate(v); } } },
      tooltip: { theme: c.tooltip, shared: true, intersect: false, x: { format: "MMM d, HH:mm" },
        y: { formatter: function (v) { return v === null || v === undefined ? "–" : DM.hashrate(v); } } },
      markers: { size: 0, hover: { size: 4 } }, dataLabels: { enabled: false }
    };
    if (chart) chart.destroy();
    chart = new ApexCharts($("mx-chart"), opts);
    chart.render();
    var bt = d.blocks.times.map(function (t) { return t * 1000; });
    var bopts = {
      chart: { type: "bar", height: 190, toolbar: { show: false }, zoom: { enabled: false }, animations: { enabled: false },
        fontFamily: "Inter, system-ui, sans-serif", foreColor: c.fore, background: "transparent" },
      series: [{ name: "Blocks", data: bt.map(function (t, i) { return [t, d.blocks.values[i]]; }) }],
      colors: [color], plotOptions: { bar: { columnWidth: "72%", borderRadius: 3, borderRadiusApplication: "end" } },
      grid: { borderColor: c.grid, strokeDashArray: 3, padding: { left: 6, right: 10 } },
      xaxis: { type: "datetime", labels: { datetimeUTC: false, format: fmt }, axisBorder: { show: false }, axisTicks: { show: false }, tooltip: { enabled: false } },
      yaxis: { min: 0, forceNiceScale: true, tickAmount: 3, labels: { minWidth: 64, formatter: function (v) { return DM.number(v); } } },
      tooltip: { theme: c.tooltip, x: { format: state.range === "24h" || state.range === "7d" ? "MMM d, HH:mm" : "MMM d, yyyy" },
        y: { formatter: function (v) { return v + (v === 1 ? " block" : " blocks"); } } },
      dataLabels: { enabled: false }, legend: { show: false }
    };
    if (bars) bars.destroy();
    bars = new ApexCharts($("mx-chart-blocks"), bopts);
    bars.render();
    var per = { 3600: "hour", 21600: "6 hours", 86400: "day", 604800: "week" }[d.blocks.step];
    $("mx-chart-note").textContent = (hasApi ? "Its hashrate as its API says it, and dashed, as the work of the blocks it found says it (over " +
      DM.duration(d.window) + "). " : "Its hashrate as the work of the blocks it found says it (over " + DM.duration(d.window) + "). ") +
      "Below, the blocks it found, a bar per " + per + ".";
  }
  $("mx-ranges").addEventListener("click", function (event) {
    var b = event.target.closest("[data-range]");
    if (!b) return;
    state.range = b.getAttribute("data-range");
    Array.prototype.forEach.call(document.querySelectorAll("#mx-ranges [data-range]"), function (x) {
      x.setAttribute("aria-pressed", x === b ? "true" : "false");
    });
    drawCharts();
  });

  // ------------------------------------------------------------------ the blocks it found
  function showFound(p) {
    var t = $("mx-found"), withStatus = p.found.some(function (b) { return b.status || b.effort !== null; });
    var head = t.tHead, body = t.tBodies[0];
    head.textContent = ""; body.textContent = "";
    var hr = el("tr");
    ["Block", "Found", "Reward"].concat(withStatus ? ["Status", "Effort"] : []).forEach(function (h) { hr.appendChild(el("th", null, h)); });
    head.appendChild(hr);
    p.found.slice(0, state.shown).forEach(function (b) {
      var tr = el("tr"), td = el("td");
      td.appendChild(link(p.explorer + "/block/" + b.hash, DM.number(b.height), true));
      tr.appendChild(td);
      var when = el("td", null, DM.ago(b.time)); when.title = DM.date(b.time); tr.appendChild(when);
      tr.appendChild(el("td", "mx-num", DM.none(b.reward) ? "–" : DM.dmd(b.reward)));
      if (withStatus) {
        var words = { confirmed: ["ok", "Confirmed"], pending: ["pending", "Maturing"], orphaned: ["orphan", "Orphaned"] }[b.status] || ["", "–"];
        tr.appendChild(el("td", words[0], words[1]));
        tr.appendChild(el("td", "mx-num", DM.none(b.effort) ? "–" : DM.percent(b.effort, 0)));
      }
      body.appendChild(tr);
    });
    if (!p.found.length) { var none = el("tr"), c = el("td", "mx-muted", "No block found yet."); c.colSpan = 5; none.appendChild(c); body.appendChild(none); }
    $("mx-found-count").textContent = p.blocks_total ? DM.number(p.blocks_total) + " in all" : "";
    $("mx-found-more").hidden = state.shown >= p.found.length;
    var o = $("mx-orphaned");
    o.hidden = !p.orphaned.length;
    if (p.orphaned.length) {
      o.textContent = "Its API also lists " + p.orphaned.length + (p.orphaned.length > 1 ? " orphaned blocks" : " orphaned block") +
        " in the last 30 days (found, then replaced on the chain by another miner's): " +
        p.orphaned.map(function (b) { return DM.number(b.height); }).join(", ") + ".";
    }
  }
  $("mx-found-more").addEventListener("click", function () { state.shown += 25; showFound(state.pool); });

  // ------------------------------------------------------------------ loading, and every minute
  function missing() {
    $("mx-page").innerHTML = "";
    var box = el("section", "dmd-card mx-missing");
    box.appendChild(el("h1", null, "This pool isn't in the list"));
    var p = el("p", "mx-muted");
    p.appendChild(document.createTextNode("It may have a new name. "));
    p.appendChild(link("/", "See every pool"));
    box.appendChild(p);
    $("mx-page").appendChild(box);
    document.title = "Not found · DMD Mining";
  }
  function refresh() {
    if (!slug) { missing(); return; }
    Promise.all([
      DM.getJSON("/api/pools/" + slug + ".json"),
      DM.getJSON("/api/summary.json").catch(function () { return null; })
    ]).then(function (r) {
      var p = r[0], s = r[1];
      if (s) { DM.setPools(s.pools); state.tip = s.network.height; if (window.DMNotify) window.DMNotify.setPools(s.pools); }
      else DM.colors[p.slug] = p.color;
      var first = !state.pool;
      state.pool = p;
      showHead(p); showFigures(p); showConnect(p); showDetails(p); showFound(p);
      if (first || !document.hidden) drawCharts();
    }).catch(function (err) {
      if (/: 404$/.test(err.message)) missing();
    });
  }
  DM.onTheme.push(drawCharts);
  refresh();
  setInterval(function () { if (!document.hidden) refresh(); }, 60000);
})();

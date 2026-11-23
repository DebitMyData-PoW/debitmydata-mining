// DMD Mining's home page: the network, every pool (its API's figures and the blocks it found), the
// charts over time, the latest blocks and who finds them. From the files the server writes every
// 20 seconds (/api/summary.json, blocks.json, distribution.json, chart-<range>.json); read again
// every 30 seconds while the page is in view.
(function () {
  "use strict";
  var DM = window.DM, $ = DM.$, el = DM.el;
  var state = { summary: null, blocks: [], dist: null, charts: {}, filter: "all", sort: "hashrate",
    metric: "hashrate", range: "24h", shareRange: "24h", shown: 12, showIdle: false };
  try {
    var kept = JSON.parse(localStorage.getItem("dmd-mining-home") || "{}");
    if (/^(hashrate|blocks|fee|name|last)$/.test(kept.sort)) state.sort = kept.sort;
    if (/^(all|shared|solo)$/.test(kept.filter)) state.filter = kept.filter;
  } catch (e) {}
  function keep() { try { localStorage.setItem("dmd-mining-home", JSON.stringify({ sort: state.sort, filter: state.filter })); } catch (e) {} }
  var chart = null, donut = null;

  function put(id, value, sub) {
    var e = $(id);
    if (e) e.textContent = value;
    if (sub !== undefined && $(id + "-sub")) $(id + "-sub").textContent = sub;
  }

  // ------------------------------------------------------------------ the figures
  function showSummary(s) {
    var n = s.network, t = s.totals;
    put("s-hashrate", DM.hashrate(n.hashrate_1h), "24h: " + DM.hashrate(n.hashrate_24h));
    var answering = s.pools.filter(function (p) { return p.api && p.status !== "down"; }).length;
    put("s-pools-rate", DM.hashrate(t.reported_hashrate),
      (t.reported_share && t.reported_share <= 1.05 ? DM.percent(t.reported_share, 0) + " of the network, from " : "as said by ") +
      answering + (answering === 1 ? " pool's API" : " pools' APIs"));
    put("s-difficulty", DM.big(n.difficulty), "reward " + DM.number(n.reward_dmd, 4) + " DMD a block");
    put("s-height", DM.number(n.height), n.last_block ? "last block " + DM.ago(n.last_block.time) : "");
    put("s-blocktime", DM.duration(n.block_seconds_24h), DM.number(n.blocks_24h) + " blocks, target 2.5 min");
    put("s-active", String(t.pools_active_24h), t.pools_answering + " answering their API");
    if (t.top_24h) put("s-top", DM.percent(t.top_24h.share, 0), t.top_24h.name);
    if (t.nakamoto_24h) {
      put("s-nakamoto", t.nakamoto_24h === 1 ? "1 miner" : t.nakamoto_24h + " miners",
        t.nakamoto_24h === 1 ? "found more than half of today's blocks" : "together found half of today's blocks");
    }
    var pill = $("dmd-status");
    var stale = !s.chain_read_at || Date.now() / 1000 - s.chain_read_at > 600;
    var mining = s.pools.filter(function (p) { return p.blocks["30d"] > 0 || p.status === "up"; }).length;
    pill.className = "dmd-pill " + (stale ? "alert" : "ok");
    pill.textContent = stale ? "Waiting for the chain's figures" : mining + " pools mining DMD";
    $("dmd-updated").textContent = "Updated " + DM.ago(s.updated);
  }

  // ------------------------------------------------------------------ the pools
  function mining(p) { return p.blocks["30d"] > 0 || p.status === "up" || p.status === "behind"; }
  function fits(p) {
    if (state.filter === "solo") return p.schemes.indexOf("SOLO") >= 0;
    if (state.filter === "shared") return p.schemes.some(function (x) { return x !== "SOLO"; });
    return true;
  }
  function ranked(list) {
    var by = {
      hashrate: function (a, b) { return (b.hashrate || b.hashrate_from_blocks_24h || 0) - (a.hashrate || a.hashrate_from_blocks_24h || 0) || b.blocks["24h"] - a.blocks["24h"]; },
      blocks: function (a, b) { return b.blocks["24h"] - a.blocks["24h"] || b.blocks["7d"] - a.blocks["7d"]; },
      last: function (a, b) { return ((b.last_block && b.last_block.height) || 0) - ((a.last_block && a.last_block.height) || 0); },
      fee: function (a, b) { return (a.fee_min === null ? 99 : a.fee_min) - (b.fee_min === null ? 99 : b.fee_min); },
      name: function (a, b) { return a.name.localeCompare(b.name); }
    }[state.sort];
    return list.slice().sort(by);
  }
  function cell(key, label) {
    var td = el("td", "mx-cell");
    td.setAttribute("data-k", key);
    td.setAttribute("data-label", label);
    return td;
  }
  function poolRow(p, total) {
    var tr = el("tr", DM.colorClass(p.slug) + (mining(p) ? "" : " mx-idle"));
    tr.setAttribute("data-href", "/pool/" + p.slug);
    var td = el("td"); td.setAttribute("data-k", "pool");
    var who = el("div", "mx-pool");
    who.appendChild(DM.logo(p, 38));
    var name = el("div", "mx-name");
    var a = el("a", null, p.name); a.href = "/pool/" + p.slug;
    name.appendChild(a);
    var sub = el("span", "mx-sub");
    if (p.flag) { var f = el("span", "mx-flag", p.flag); f.title = p.country; sub.appendChild(f); }
    if (p.domain) sub.appendChild(el("span", null, p.domain));
    sub.appendChild(DM.status(p));
    name.appendChild(sub);
    who.appendChild(name);
    td.appendChild(who);
    tr.appendChild(td);

    var rate = el("td"); rate.setAttribute("data-k", "rate");
    var box = el("div", "mx-rate");
    var text = el("div");
    if (p.api && p.hashrate !== null) {
      text.appendChild(el("b", "mx-num", DM.hashrate(p.hashrate)));
      if (p.hashrate_share) { text.appendChild(el("br")); text.appendChild(el("small", "mx-muted", DM.percent(p.hashrate_share) + " of the network")); }
      box.appendChild(DM.spark(p.spark, false));
    } else {
      text.appendChild(el("b", "mx-num", p.hashrate_from_blocks_24h ? "≈ " + DM.hashrate(p.hashrate_from_blocks_24h) : "–"));
      text.appendChild(el("br"));
      text.appendChild(el("small", "mx-muted", p.api ? "API not answering" : "from its blocks"));
      box.appendChild(DM.spark(p.spark, true));
    }
    box.insertBefore(text, box.firstChild);
    rate.appendChild(box);
    tr.appendChild(rate);

    var share = cell("share", "Blocks (24h)");
    var wrap = el("div", "mx-share");
    var part = total ? p.blocks["24h"] / total : 0;
    var line = el("span", "mx-num");
    line.appendChild(el("b", null, DM.number(p.blocks["24h"])));
    line.appendChild(document.createTextNode(" · " + DM.percent(part)));
    wrap.appendChild(line);
    var bar = el("span", "bar"), fill = el("i"); fill.style.width = Math.min(100, part * 100).toFixed(1) + "%";
    bar.appendChild(fill); wrap.appendChild(bar);
    share.appendChild(wrap);
    tr.appendChild(share);

    var last = cell("last", "Last block");
    if (p.last_block) {
      last.appendChild(el("b", null, DM.ago(p.last_block.time)));
      last.appendChild(el("br"));
      last.appendChild(el("small", "mx-muted mx-num", "#" + DM.number(p.last_block.height)));
    } else last.textContent = "–";
    tr.appendChild(last);

    var fee = cell("fee", "Fee");
    var feeText = p.fee_min === null ? "–" : p.fee_min === p.fee_max ? DM.fee(p.fee_min) : DM.fee(p.fee_min) + "–" + DM.fee(p.fee_max);
    fee.appendChild(el("b", "mx-num", feeText));
    fee.appendChild(el("br"));
    fee.appendChild(DM.schemeChips(p.schemes));
    tr.appendChild(fee);

    var miners = cell("miners", "Miners");
    miners.appendChild(el("b", "mx-num", DM.none(p.miners) ? (DM.none(p.workers) ? "–" : DM.number(p.workers)) : DM.number(p.miners)));
    if (DM.none(p.miners) && !DM.none(p.workers)) { miners.appendChild(el("br")); miners.appendChild(el("small", "mx-muted", "workers")); }
    tr.appendChild(miners);

    var follow = el("td"); follow.setAttribute("data-k", "follow");
    follow.appendChild(DM.followButton(p));
    tr.appendChild(follow);
    return tr;
  }
  function showPools() {
    var s = state.summary;
    if (!s) return;
    var body = $("mx-pools").tBodies[0];
    body.textContent = "";
    var total = s.network.blocks_24h;
    var shown = ranked(s.pools.filter(fits));
    var active = shown.filter(mining), idle = shown.filter(function (p) { return !mining(p); });
    active.forEach(function (p) { body.appendChild(poolRow(p, total)); });
    if (idle.length) {
      var g = el("tr", "mx-group"), td = el("td");
      var more = el("button", "mx-idle-toggle", state.showIdle ? "Hide the pools with no block in 30 days"
        : "Show " + idle.length + (idle.length > 1 ? " more listed pools" : " more listed pool") + ", with no block in 30 days");
      more.type = "button";
      more.setAttribute("aria-expanded", state.showIdle ? "true" : "false");
      more.addEventListener("click", function () { state.showIdle = !state.showIdle; showPools(); });
      td.colSpan = 7; td.appendChild(more); g.appendChild(td); body.appendChild(g);
      if (state.showIdle) idle.forEach(function (p) { body.appendChild(poolRow(p, total)); });
    }
    if (!shown.length) {
      var none = el("tr"), cellNone = el("td", "mx-muted", "No pool of this kind.");
      cellNone.colSpan = 7; none.appendChild(cellNone); body.appendChild(none);
    }
    var others = $("mx-others"), list = (s.others || []).filter(function (o) { return o.blocks["24h"] > 0; });
    others.hidden = !list.length;
    if (list.length) {
      others.textContent = "";
      others.appendChild(el("b", null, "Other miners today: "));
      others.appendChild(document.createTextNode(list.map(function (o) {
        return o.name + " (" + o.blocks["24h"] + (o.blocks["24h"] > 1 ? " blocks" : " block") + ")";
      }).join(", ") + ". Not in the pool list yet: solo miners, or pools to add."));
    }
  }
  $("mx-pools").addEventListener("click", function (event) {
    if (event.target.closest("a, button")) return;
    var tr = event.target.closest("tr[data-href]");
    if (tr) location.href = tr.getAttribute("data-href");
  });
  function tabs(groupId, attr, value) {
    Array.prototype.forEach.call(document.querySelectorAll("#" + groupId + " [data-" + attr + "]"), function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-" + attr) === value ? "true" : "false");
    });
  }
  $("mx-filter").addEventListener("click", function (event) {
    var b = event.target.closest("[data-filter]");
    if (!b) return;
    state.filter = b.getAttribute("data-filter"); keep();
    tabs("mx-filter", "filter", state.filter);
    showPools();
  });
  $("mx-sort").addEventListener("change", function () { state.sort = this.value; keep(); showPools(); });

  // ------------------------------------------------------------------ the charts over time
  function axisFormat(range) {
    return range === "24h" ? "HH:mm" : range === "7d" ? "ddd HH:mm" : range === "30d" ? "MMM d" : "MMM d, yyyy";
  }
  function legend(items) {
    var ul = $("mx-legend");
    ul.textContent = "";
    items.forEach(function (it) {
      var li = el("li", it.cls);
      li.appendChild(document.createTextNode(it.name + " "));
      if (it.value) li.appendChild(el("b", null, it.value));
      ul.appendChild(li);
    });
  }
  function drawChart() {
    var data = state.charts[state.range];
    if (!data || !window.ApexCharts) return;
    var c = DM.chartTheme(), series = [], colors = [], dashes = [], widths = [], items = [];
    var options;
    if (state.metric === "hashrate") {
      var h = data.hashrate;
      var times = h.times.map(function (t) { return t * 1000; });
      h.pools.forEach(function (p) {
        series.push({ name: p.name, type: "line", data: times.map(function (t, i) { return [t, p.values[i]]; }) });
        colors.push(DM.colorHex(p.slug)); dashes.push(0); widths.push(2);
        var lastValue = p.values.filter(function (v) { return v !== null; }).slice(-1)[0];
        items.push({ name: p.name, value: DM.hashrate(lastValue), cls: DM.colorClass(p.slug) });
      });
      series.push({ name: "The network (from its blocks)", type: "line", data: times.map(function (t, i) { return [t, h.network[i]]; }) });
      colors.push(c.network); dashes.push(6); widths.push(1.5);
      items.push({ name: "The network", value: DM.hashrate(h.network.filter(function (v) { return v !== null; }).slice(-1)[0]), cls: "dash" });
      options = {
        chart: { type: "line", height: 330, toolbar: { show: false }, zoom: { enabled: false }, animations: { enabled: false },
          fontFamily: "Inter, system-ui, sans-serif", foreColor: c.fore, background: "transparent" },
        series: series, colors: colors,
        stroke: { width: widths, curve: "straight", dashArray: dashes },
        legend: { show: false },
        grid: { borderColor: c.grid, strokeDashArray: 3, padding: { left: 6, right: 10 } },
        xaxis: { type: "datetime", labels: { datetimeUTC: false, format: axisFormat(state.range) }, axisBorder: { show: false }, axisTicks: { show: false }, tooltip: { enabled: false } },
        yaxis: { min: 0, forceNiceScale: true, labels: { formatter: function (v) { return DM.hashrate(v); } } },
        tooltip: { theme: c.tooltip, shared: true, intersect: false, x: { format: state.range === "24h" ? "MMM d, HH:mm" : "MMM d, yyyy HH:mm" },
          y: { formatter: function (v) { return v === null || v === undefined ? "–" : DM.hashrate(v); } } },
        markers: { size: 0, hover: { size: 4 } },
        dataLabels: { enabled: false }
      };
      $("mx-chart-note").textContent = "Each pool's hashrate as its API says it (pools without an API aren't drawn), every " +
        (h.step < 3600 ? h.step / 60 + " minutes" : h.step === 3600 ? "hour" : h.step === 86400 ? "day" : h.step / 3600 + " hours") +
        "; the network's, dashed, from the work of the blocks found. The pools' figures start when this site started following them.";
    } else {
      var b = data.blocks;
      var bt = b.times.map(function (t) { return t * 1000; });
      b.series.forEach(function (s) {
        series.push({ name: s.name, data: bt.map(function (t, i) { return [t, s.values[i]]; }) });
        colors.push(DM.colorHex(s.key === "others" ? null : s.slug));
        var sum = s.values.reduce(function (x, y) { return x + y; }, 0);
        items.push({ name: s.name, value: DM.number(sum), cls: s.key === "others" ? "cx" : DM.colorClass(s.slug) });
      });
      options = {
        chart: { type: "bar", stacked: true, height: 330, toolbar: { show: false }, zoom: { enabled: false }, animations: { enabled: false },
          fontFamily: "Inter, system-ui, sans-serif", foreColor: c.fore, background: "transparent" },
        series: series, colors: colors,
        plotOptions: { bar: { columnWidth: "78%", borderRadius: 3, borderRadiusApplication: "end", borderRadiusWhenStacked: "last" } },
        stroke: { show: true, width: 1, colors: [c.surface] },
        legend: { show: false },
        grid: { borderColor: c.grid, strokeDashArray: 3, padding: { left: 6, right: 10 } },
        xaxis: { type: "datetime", labels: { datetimeUTC: false, format: axisFormat(state.range) }, axisBorder: { show: false }, axisTicks: { show: false }, tooltip: { enabled: false } },
        yaxis: { min: 0, forceNiceScale: true, labels: { formatter: function (v) { return DM.number(v); } } },
        tooltip: { theme: c.tooltip, shared: true, intersect: false, x: { format: state.range === "24h" || state.range === "7d" ? "MMM d, HH:mm" : "MMM d, yyyy" },
          y: { formatter: function (v) { return v + (v === 1 ? " block" : " blocks"); } } },
        dataLabels: { enabled: false }
      };
      var per = { 3600: "hour", 21600: "6 hours", 86400: "day", 604800: "week" }[b.step] || (b.step / 3600 + " hours");
      $("mx-chart-note").textContent = "The blocks each pool found, a bar per " + per + ", from the chain since block 1.";
    }
    legend(items);
    if (chart) { chart.destroy(); chart = null; }
    chart = new ApexCharts($("mx-chart"), options);
    chart.render();
  }
  function loadChart() {
    var range = state.range;
    return DM.getJSON("/api/chart-" + range + ".json").then(function (d) { state.charts[range] = d; if (range === state.range) drawChart(); })
      .catch(function () { $("mx-chart-note").textContent = "The chart couldn't be loaded: it tries again in a moment."; });
  }
  $("mx-metrics").addEventListener("click", function (event) {
    var b = event.target.closest("[data-metric]");
    if (!b) return;
    state.metric = b.getAttribute("data-metric");
    tabs("mx-metrics", "metric", state.metric);
    drawChart();
  });
  $("mx-ranges").addEventListener("click", function (event) {
    var b = event.target.closest("[data-range]");
    if (!b) return;
    state.range = b.getAttribute("data-range");
    tabs("mx-ranges", "range", state.range);
    if (state.charts[state.range]) drawChart();
    loadChart();
  });

  // ------------------------------------------------------------------ the latest blocks
  function showBlocks() {
    var ul = $("mx-blocks"), explorer = "https://mempool.debitmydata.io";
    ul.textContent = "";
    state.blocks.slice(0, state.shown).forEach(function (b) {
      var li = el("li");
      var h = el("a", "h", DM.number(b.height));
      h.href = explorer + "/block/" + b.hash; h.target = "_blank"; h.rel = "noopener";
      h.title = "Block " + b.height + " in the explorer";
      li.appendChild(h);
      var who = el("span", "who " + DM.colorClass(b.slug));
      var pool = state.summary && state.summary.pools.filter(function (p) { return p.slug === b.slug; })[0];
      who.appendChild(DM.logo(pool || { slug: b.slug, name: b.miner, logo: null }, 22));
      if (b.slug) { var a = el("a", null, b.miner); a.href = "/pool/" + b.slug; who.appendChild(a); }
      else who.appendChild(el("span", "n", b.miner));
      li.appendChild(who);
      var age = el("span", "age", DM.ago(b.time));
      age.title = DM.date(b.time);
      li.appendChild(age);
      if (b.seconds !== null) {
        var gap = el("span", "gap" + (b.seconds > 450 ? " slow" : "")), bar = el("i");
        bar.style.width = Math.min(100, Math.max(1, b.seconds / 900 * 100)) + "%";
        gap.appendChild(bar);
        gap.appendChild(document.createTextNode(DM.duration(b.seconds) + " after the one before"));
        li.appendChild(gap);
      }
      ul.appendChild(li);
    });
    $("mx-blocks-more").hidden = state.shown >= state.blocks.length;
  }
  $("mx-blocks-more").addEventListener("click", function () { state.shown += 24; showBlocks(); });

  // ------------------------------------------------------------------ who finds the blocks
  function showShare() {
    var d = state.dist && state.dist[state.shareRange];
    if (!d) return;
    var listed = d.miners.filter(function (m) { return m.listed; });
    var others = d.miners.filter(function (m) { return !m.listed; });
    var rows = listed.map(function (m) { return { name: m.name, slug: m.slug, blocks: m.blocks, share: m.share }; });
    if (others.length) {
      var n = others.reduce(function (x, m) { return x + m.blocks; }, 0);
      rows.push({ name: others.length === 1 ? others[0].name : "Other miners (" + others.length + ")", slug: null, blocks: n,
        share: d.blocks ? n / d.blocks : 0, title: others.map(function (m) { return m.name + ": " + m.blocks; }).join(", ") });
    }
    $("mx-donut-n").textContent = DM.number(d.blocks);
    var ul = $("mx-share-list");
    ul.textContent = "";
    rows.forEach(function (r) {
      var li = el("li", DM.colorClass(r.slug));
      if (r.title) li.title = r.title;
      var who = el("span", "who");
      if (r.slug) { var a = el("a", "mx-plain"); a.href = "/pool/" + r.slug; a.appendChild(el("span", null, r.name)); who.appendChild(a); }
      else who.appendChild(el("span", null, r.name));
      li.appendChild(who);
      li.appendChild(el("span", "n", DM.number(r.blocks)));
      li.appendChild(el("span", "p", DM.percent(r.share)));
      ul.appendChild(li);
    });
    var c = DM.chartTheme();
    var options = {
      chart: { type: "donut", width: 200, height: 200, animations: { enabled: false }, fontFamily: "Inter, system-ui, sans-serif", background: "transparent" },
      series: rows.map(function (r) { return r.blocks; }),
      labels: rows.map(function (r) { return r.name; }),
      colors: rows.map(function (r) { return DM.colorHex(r.slug); }),
      stroke: { width: 2, colors: [c.surface] },
      legend: { show: false }, dataLabels: { enabled: false },
      plotOptions: { pie: { donut: { size: "70%" }, expandOnClick: false } },
      tooltip: { theme: c.tooltip, y: { formatter: function (v) { return v + " blocks (" + DM.percent(d.blocks ? v / d.blocks : 0) + ")"; } } },
      states: { active: { filter: { type: "none" } } }
    };
    if (donut) { donut.destroy(); donut = null; }
    if (window.ApexCharts && rows.length) { donut = new ApexCharts($("mx-donut"), options); donut.render(); }
    var top = d.miners[0], share = top ? top.share : 0;
    $("mx-meter-mark").style.left = Math.min(100, share * 100).toFixed(1) + "%";
    var period = { "24h": "in the last 24 hours", "7d": "in the last 7 days", "30d": "in the last 30 days", "1000": "of the last 1,000 blocks" }[state.shareRange];
    var v = $("mx-verdict");
    v.textContent = "";
    if (!top) return;
    v.appendChild(el("b", null, top.name));
    v.appendChild(document.createTextNode(" found " + DM.percent(share) + " of the blocks " + period + ". " +
      (share > 0.5 ? "More than half: one miner could rewrite recent blocks." :
        share > 0.3 ? (d.nakamoto === 2 ? "Two miners together find more than half of them." : "No miner finds half of them, but the biggest is close enough to watch.") :
          "Mining is well spread out.")));
  }
  $("mx-share-ranges").addEventListener("click", function (event) {
    var b = event.target.closest("[data-range]");
    if (!b) return;
    state.shareRange = b.getAttribute("data-range");
    tabs("mx-share-ranges", "range", state.shareRange);
    showShare();
  });

  // ------------------------------------------------------------------ loading, and every 30 seconds
  function refresh() {
    return Promise.all([
      DM.getJSON("/api/summary.json").then(function (s) {
        state.summary = s;
        DM.setPools(s.pools);
        showSummary(s);
        showPools();
        if (window.DMNotify) window.DMNotify.setPools(s.pools);
      }),
      DM.getJSON("/api/blocks.json").then(function (b) { state.blocks = b.blocks || []; }),
      DM.getJSON("/api/distribution.json").then(function (d) { state.dist = d; })
    ]).then(function () { showBlocks(); showShare(); return loadChart(); })
      .catch(function () {
        var pill = $("dmd-status");
        pill.className = "dmd-pill alert";
        pill.textContent = "The figures couldn't be loaded: trying again";
      });
  }
  tabs("mx-filter", "filter", state.filter);
  $("mx-sort").value = state.sort;
  DM.onTheme.push(function () { drawChart(); showShare(); });
  refresh();
  setInterval(function () { if (!document.hidden) refresh(); }, 30000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
  setInterval(function () { if (state.summary && !document.hidden) { $("dmd-updated").textContent = "Updated " + DM.ago(state.summary.updated); } }, 5000);
})();

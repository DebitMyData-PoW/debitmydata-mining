// The API page: "Try it" (the file's start, live; the "Copy" buttons are common.js's).
(function () {
  "use strict";
  // The live file, shortened: long lists show their first items.
  function shorten(data, depth) {
    depth = depth || 0;
    if (Array.isArray(data)) {
      var list = data.length > 4 ? data.slice(0, depth ? 3 : 4).concat(["…"]) : data;
      return list.map(function (x) { return shorten(x, depth + 1); });
    }
    if (data && typeof data === "object") {
      var out = {};
      Object.keys(data).forEach(function (k) { out[k] = shorten(data[k], depth + 1); });
      return out;
    }
    return data;
  }
  Array.prototype.forEach.call(document.querySelectorAll("[data-try]"), function (button) {
    button.addEventListener("click", function () {
      var out = button.closest(".dmd-endpoint").querySelector(".dmd-try-out");
      if (!out.hidden) { out.hidden = true; button.textContent = "Try it"; return; }
      out.hidden = false;
      out.textContent = "Loading…";
      button.textContent = "Hide";
      fetch(button.getAttribute("data-try"), { cache: "no-cache" }).then(function (r) { return r.json(); })
        .then(function (data) { out.textContent = JSON.stringify(shorten(data), null, 1); })
        .catch(function () { out.textContent = "The file could not be read just now."; });
    });
  });
})();

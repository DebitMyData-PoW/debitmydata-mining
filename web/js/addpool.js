// DMD Mining: "Add your pool". The link opens a window saying what to send, with an email
// already filled in. The address is put together here, never written in the page, so robots
// collecting addresses from pages don't find it. Without this script, the link opens the pool
// list's instructions on GitHub.
(function () {
  "use strict";

  var ADDRESS = ["info", "debitmydata.com"].join("@");
  var SUBJECT = "Add my pool to DMD Mining";
  var BODY = [
    "Hello,",
    "",
    "Please add my DMD mining pool:",
    "",
    "Pool name: ",
    "Website: ",
    "Country it runs in: ",
    "Coinbase tag (the text it writes in its blocks): ",
    "Addresses its blocks pay to: ",
    "Stratum addresses and ports: ",
    "Fee: ",
    "Payout scheme (PPLNS, PPS, PROP, SOLO): ",
    "Minimum payout: ",
    "API (MiningCore, YIIMP or other) and its address: ",
    "",
    "Logo: attached (square PNG or SVG, 128 px or more)",
    "",
  ].join("\n");

  var box = document.getElementById("mx-addpool");
  if (!box || typeof box.showModal !== "function") return;

  var mail = document.getElementById("mx-addpool-mail");
  var copy = document.getElementById("mx-addpool-copy");
  var shown = document.getElementById("mx-addpool-address");
  mail.href = "mailto:" + ADDRESS + "?subject=" + encodeURIComponent(SUBJECT) + "&body=" + encodeURIComponent(BODY);
  shown.textContent = ADDRESS;

  if (navigator.clipboard && navigator.clipboard.writeText) {
    copy.hidden = false;
    copy.addEventListener("click", function () {
      navigator.clipboard.writeText(ADDRESS).then(function () {
        copy.textContent = "Copied";
        setTimeout(function () { copy.textContent = "Copy our address"; }, 1600);
      }, function () {});
    });
  }

  document.addEventListener("click", function (event) {
    var open = event.target.closest && event.target.closest("[data-addpool]");
    if (!open) return;
    event.preventDefault();
    box.showModal();
  });
  box.addEventListener("click", function (event) {
    // the close button, or a click on the dimmed page around the window
    if (event.target === box || (event.target.closest && event.target.closest("[data-addpool-close]"))) box.close();
  });
})();

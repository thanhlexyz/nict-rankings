// Sorting, cups and the small controls. No dependencies; the tables work (unsorted) without it.
(function () {
  var root = document.documentElement;
  try { var t = localStorage.getItem("theme"); if (t) root.setAttribute("data-theme", t); } catch (e) {}
  var tb = document.getElementById("theme");
  if (tb) tb.addEventListener("click", function () {
    var dark = root.getAttribute("data-theme") === "dark" ||
      (!root.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
    var next = dark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
  });

  // cups: the top three distinct values of the sorted numeric column; zero gets none; cells marked data-last none.
  function cups(table, col, asc) {
    table.querySelectorAll(".cup").forEach(function (c) { c.remove(); });
    if (col < 0) return;
    var rows = Array.prototype.slice.call(table.tBodies[0].rows).filter(function (r) { return r.style.display !== "none"; });
    var cells = rows.map(function (r) { return r.cells[col]; });
    if (!cells.length || cells[0].classList.contains("l")) return;
    var vals = [];
    cells.forEach(function (c) { if (!c.hasAttribute("data-last")) vals.push(parseFloat(c.dataset.v)); });
    vals = vals.filter(function (v) { return !isNaN(v) && (asc ? true : v > 0); });
    var distinct = Array.from(new Set(vals)).sort(function (a, b) { return asc ? a - b : b - a; }).slice(0, 3);
    var cls = ["g", "s", "b"];
    cells.forEach(function (c) {
      if (c.hasAttribute("data-last")) return;
      var i = distinct.indexOf(parseFloat(c.dataset.v));
      if (i < 0) return;
      var s = document.createElement("span");
      s.className = "cup " + cls[i];
      s.title = ["gold", "silver", "bronze"][i];
      c.insertBefore(s, c.firstChild);
    });
  }
  function renumber(table) {
    var n = 0;
    Array.prototype.forEach.call(table.tBodies[0].rows, function (r) {
      var rk = r.querySelector(".rk");
      if (rk && r.style.display !== "none") rk.textContent = ++n;
    });
  }
  function sortBy(table, col, asc, text) {
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);
    rows.sort(function (a, b) {
      var x = a.cells[col], y = b.cells[col];
      var lx = x.hasAttribute("data-last"), ly = y.hasAttribute("data-last");
      if (lx !== ly) return lx ? 1 : -1;
      var p = x.dataset.v, q = y.dataset.v;
      var r = text ? String(p).localeCompare(String(q)) : parseFloat(p) - parseFloat(q);
      if (r === 0) return 0;
      return asc ? r : -r;
    });
    rows.forEach(function (r) { body.appendChild(r); });
    table.querySelectorAll("thead th").forEach(function (h, i) { h.setAttribute("aria-sort", i === col ? (asc ? "ascending" : "descending") : "none"); });
    renumber(table);
    cups(table, text ? -1 : col, asc);
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var state = { col: -1, asc: false };
    table.querySelectorAll("thead th").forEach(function (th, i) {
      if (th.classList.contains("pin")) return;
      var title = th.getAttribute("data-title");
      if (title) th.title = title;
      th.addEventListener("click", function () {
        var text = th.dataset.type === "text" || th.classList.contains("l");
        var asc = state.col === i ? !state.asc : text;
        state = { col: i, asc: asc };
        sortBy(table, i, asc, text);
      });
    });
    // default: the first numeric column that is a citation count, largest first
    var rank = table.id && table.id.indexOf("rank-") === 0;
    if (rank) { var d = table.querySelector("thead th:nth-child(4)"); if (d) { state = { col: 3, asc: false }; sortBy(table, 3, false, false); } }
    else renumber(table);
  });

  // tabs on the ranking page
  document.querySelectorAll(".tabs button").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll(".tabs button").forEach(function (o) { o.setAttribute("aria-selected", o === b ? "true" : "false"); });
      document.querySelectorAll(".pane").forEach(function (p) { p.hidden = p.dataset.pane !== b.dataset.tab; });
    });
  });

  // paper filters on a person page
  var sf = document.getElementById("status-filter"), yf = document.getElementById("year-filter");
  function filter() {
    var s = sf ? sf.value : "", y = yf ? parseInt(yf.value || "0", 10) : 0;
    document.querySelectorAll("#papers tbody tr").forEach(function (r) {
      var ok = (!s || r.dataset.status === s) && (!y || parseInt(r.dataset.year || "0", 10) >= y);
      r.style.display = ok ? "" : "none";
    });
  }
  if (sf) sf.addEventListener("change", filter);
  if (yf) yf.addEventListener("change", filter);
})();

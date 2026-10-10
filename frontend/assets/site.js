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

  // cups for the top three distinct values of the sorted numeric column, shown in the # column like the template:
  // gold, silver, bronze; ties share a cup and the next value takes the next one; a zero gets none when sorted largest first;
  // sorted by text there are none; cells marked data-last never get one.
  var CUP = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h10v2h3v3a4 4 0 0 1-4 4h-.3A5 5 0 0 1 13 14.9V18h3v2H8v-2h3v-3.1A5 5 0 0 1 8.3 12H8a4 4 0 0 1-4-4V5h3V3zm0 4H6v1a2 2 0 0 0 1 1.7V7zm10 0v2.7A2 2 0 0 0 18 8V7h-1z"/></svg>';
  function slotOf(row) {
    var rk = row.querySelector(".rk");
    if (rk && !rk.querySelector(".n")) rk.innerHTML = '<span class="cup"></span><span class="n"></span>';
    return rk;
  }
  function cups(table, col, asc) {
    Array.prototype.forEach.call(table.tBodies[0].rows, function (r) {
      var rk = slotOf(r);
      if (rk) { var c = rk.querySelector(".cup"); c.className = "cup"; c.innerHTML = ""; c.removeAttribute("title"); }
    });
    if (col < 0) return;
    var rows = Array.prototype.slice.call(table.tBodies[0].rows).filter(function (r) { return r.style.display !== "none"; });
    if (!rows.length || rows[0].cells[col].classList.contains("l")) return;
    var vals = [];
    rows.forEach(function (r) { var c = r.cells[col]; if (!c.hasAttribute("data-last")) vals.push(parseFloat(c.dataset.v)); });
    vals = vals.filter(function (v) { return !isNaN(v) && (asc ? true : v > 0); });
    var distinct = Array.from(new Set(vals)).sort(function (a, b) { return asc ? a - b : b - a; }).slice(0, 3);
    var kinds = ["gold", "silver", "bronze"];
    rows.forEach(function (r) {
      var c = r.cells[col];
      if (c.hasAttribute("data-last")) return;
      var i = distinct.indexOf(parseFloat(c.dataset.v));
      var rk = r.querySelector(".rk");
      if (i < 0 || !rk) return;
      var s = rk.querySelector(".cup");
      s.className = "cup " + kinds[i];
      s.innerHTML = CUP;
      s.title = kinds[i];
    });
  }
  function renumber(table) {
    var n = 0;
    Array.prototype.forEach.call(table.tBodies[0].rows, function (r) {
      var rk = slotOf(r);
      if (rk && r.style.display !== "none") rk.querySelector(".n").textContent = ++n;
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
        var text = th.dataset.type === "text" || (th.classList.contains("l") && th.dataset.type !== "num");
        var asc = state.col === i ? !state.asc : text;
        state = { col: i, asc: asc };
        sortBy(table, i, asc, text);
      });
    });
    // default: the first numeric column that is a citation count, largest first
    var rank = table.id && table.id.indexOf("rank-") === 0;
    // citations (the ranking's third column), largest first
    if (rank) { state = { col: 2, asc: false }; sortBy(table, 2, false, false); }
    else renumber(table);
  });

  // network graphs: hovering a node lights its lines and neighbours
  document.querySelectorAll("svg.net").forEach(function (svg) {
    svg.querySelectorAll(".node").forEach(function (n) {
      n.addEventListener("mouseenter", function () {
        var id = n.getAttribute("data-id"), near = {};
        svg.classList.add("focus");
        svg.querySelectorAll(".edge, .ew").forEach(function (e) {
          var on = e.getAttribute("data-a") === id || e.getAttribute("data-b") === id;
          e.classList.toggle("on", on);
          if (on) { near[e.getAttribute("data-a")] = 1; near[e.getAttribute("data-b")] = 1; }
        });
        svg.querySelectorAll(".node").forEach(function (m) { m.classList.toggle("on", !!near[m.getAttribute("data-id")]); });
      });
      n.addEventListener("mouseleave", function () {
        svg.classList.remove("focus");
        svg.querySelectorAll(".on").forEach(function (e) { e.classList.remove("on"); });
      });
    });
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

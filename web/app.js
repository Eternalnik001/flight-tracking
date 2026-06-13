// Watchlist editor + read-only dashboard, talking straight to Supabase via the
// anon key. The Python job (running as the DB owner) bypasses RLS; this page is
// constrained by the policies in supabase_setup.sql.
(function () {
  const cfg = window.CONFIG;
  const ORIGIN = cfg.ORIGIN || "BLR";
  const byCode = Object.fromEntries(window.AIRPORTS.map((a) => [a.iata, a]));
  const $ = (id) => document.getElementById(id);

  // ---- toast / banner ----
  let toastT;
  function toast(msg) {
    const t = $("toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 2200);
  }
  function showBanner(msg) { const b = $("banner"); b.textContent = msg; b.style.display = "block"; }

  // ---- personalised greeting (independent of the database) ----
  // Share a link like  https://your-site/?name=Nikhil  and the page greets them
  // on click, then remembers it (localStorage) for return visits. Name is read
  // from the URL and rendered via textContent only, so it can't inject HTML.
  const STORE_KEY = "flighttracker_name";
  function greet() {
    const params = new URLSearchParams(location.search);
    let name = params.get("name") || params.get("u");
    if (name) {
      name = name.trim().slice(0, 40);
      localStorage.setItem(STORE_KEY, name);
    } else {
      name = localStorage.getItem(STORE_KEY);
    }
    if (!name) return;
    const pretty = name.charAt(0).toUpperCase() + name.slice(1);
    const hour = new Date().getHours();
    const part = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
    const el = $("greeting");
    el.textContent = `👋 ${part}, ${pretty} — welcome back to your flight tracker.`;
    el.style.display = "block";
  }
  greet();  // run before the Supabase guard, so the welcome shows even pre-config

  if (!cfg.SUPABASE_ANON_KEY || cfg.SUPABASE_ANON_KEY.includes("PASTE_YOUR")) {
    showBanner("Set SUPABASE_ANON_KEY in config.js — see the comment in that file.");
    return;
  }
  const db = window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY);

  let selected = new Set(); // current watchlist (what's saved)
  let draft = new Set();     // edits not yet saved
  const search = $("search"), opts = $("opts"), chips = $("chips"), saveBtn = $("save");

  // ---- watchlist ----
  async function loadWatchlist() {
    const { data, error } = await db.from("watchlist").select("dest")
      .eq("origin", ORIGIN).eq("enabled", true);
    if (error) { showBanner("Could not read watchlist: " + error.message); return; }
    selected = new Set(data.map((r) => r.dest));
    draft = new Set(selected);
    renderChips(); renderOpts();
  }

  function renderChips() {
    const items = [...draft].map((c) => byCode[c]).filter(Boolean)
      .sort((a, b) => a.city.localeCompare(b.city));
    chips.innerHTML = items.length
      ? items.map((a) => `<span class="chip"><b>${a.iata}</b> ${a.city}
          <span data-rm="${a.iata}" title="remove">×</span></span>`).join("")
      : `<span class="empty">No destinations selected yet.</span>`;
    chips.querySelectorAll("[data-rm]").forEach((el) =>
      el.onclick = () => { draft.delete(el.dataset.rm); syncDirty(); renderChips(); renderOpts(); });
  }

  function renderOpts() {
    const q = search.value.trim().toLowerCase();
    const list = window.AIRPORTS
      .filter((a) => a.iata !== ORIGIN)
      .filter((a) => !q || a.city.toLowerCase().includes(q) ||
                     a.state.toLowerCase().includes(q) || a.iata.toLowerCase().includes(q))
      .sort((a, b) => a.city.localeCompare(b.city));
    opts.innerHTML = list.map((a) => `
      <label class="opt">
        <input type="checkbox" data-iata="${a.iata}" ${draft.has(a.iata) ? "checked" : ""} />
        <span class="code">${a.iata}</span> ${a.city}
        <span class="st">${a.state}</span>
      </label>`).join("") || `<div class="opt empty">No matches.</div>`;
    opts.querySelectorAll("input[data-iata]").forEach((cb) =>
      cb.onchange = () => {
        cb.checked ? draft.add(cb.dataset.iata) : draft.delete(cb.dataset.iata);
        syncDirty(); renderChips();
      });
  }

  function syncDirty() {
    const changed = draft.size !== selected.size || [...draft].some((d) => !selected.has(d));
    saveBtn.disabled = !changed;
  }

  async function save() {
    saveBtn.disabled = true;
    const toAdd = [...draft].filter((d) => !selected.has(d));
    const toRemove = [...selected].filter((d) => !draft.has(d));
    try {
      if (toAdd.length) {
        const rows = toAdd.map((d) => ({ origin: ORIGIN, dest: d, enabled: true,
                                         added_at: new Date().toISOString() }));
        const { error } = await db.from("watchlist").upsert(rows, { onConflict: "origin,dest" });
        if (error) throw error;
      }
      if (toRemove.length) {
        const { error } = await db.from("watchlist").delete()
          .eq("origin", ORIGIN).in("dest", toRemove);
        if (error) throw error;
      }
      selected = new Set(draft);
      toast("Watchlist saved — next daily run will use it.");
    } catch (e) {
      toast("Save failed: " + (e.message || e));
      saveBtn.disabled = false;
    }
  }

  // ---- dashboard ----
  // One window per month; rows are filtered by the depart date's month so August
  // and November fares (which share the latest table) render separately.
  function renderMonthSection(allRows, monthNum, containerId) {
    const el = $(containerId);
    const mm = String(monthNum).padStart(2, "0");
    const rows = allRows.filter((r) => r.price != null && r.depart.slice(5, 7) === mm);
    if (!rows.length) {
      el.innerHTML = `<div class="empty">No prices stored for this month yet. The free cache
        only holds fares a few months ahead and fills in closer to travel — the daily job keeps
        trying.</div>`;
      return;
    }
    const best = {};
    for (const r of rows) {
      if (!best[r.dest] || r.price < best[r.dest].price) best[r.dest] = r;
    }
    const body = Object.entries(best).sort((a, b) => a[1].price - b[1].price).map(([dest, r]) => {
      const a = byCode[dest];
      const name = a ? `${a.city} <span class="empty">(${dest})</span>` : dest;
      return `<tr><td>${name}</td><td>${r.depart}</td>
        <td class="price">₹${Math.round(r.price).toLocaleString("en-IN")}</td></tr>`;
    }).join("");
    el.innerHTML = `<table><tr><th>Destination</th><th>Best depart date</th>
      <th>Cheapest round trip</th></tr>${body}</table>`;
  }

  async function loadDashboard() {
    const { data, error } = await db.from("latest").select("dest,depart,price,captured_at")
      .eq("fare_type", "cheapest");
    if (error) {
      const msg = `<div class="empty">Could not read prices: ${error.message}</div>`;
      $("dash-nov").innerHTML = msg; $("dash-aug").innerHTML = msg;
      return;
    }
    renderMonthSection(data, 11, "dash-nov");
    renderMonthSection(data, 8, "dash-aug");
    const t = data.find((r) => r.captured_at)?.captured_at;
    if (t) $("runat").textContent = "· updated " + new Date(t).toLocaleString();
  }

  // ---- wire up ----
  search.oninput = renderOpts;
  saveBtn.onclick = save;
  loadWatchlist();
  loadDashboard();
})();

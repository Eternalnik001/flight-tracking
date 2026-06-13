// Drives the Apple-style frontend: hero stats, month-segmented destination
// cards, and the watchlist editor. Talks straight to Supabase via the anon key;
// the Python job (DB owner) bypasses RLS. Page is constrained by supabase_setup.sql.
(function () {
  const cfg = window.CONFIG;
  const ORIGIN = cfg.ORIGIN || "BLR";
  const byCode = Object.fromEntries(window.AIRPORTS.map((a) => [a.iata, a]));
  const $ = (id) => document.getElementById(id);
  const rupee = (n) => "₹" + Math.round(n).toLocaleString("en-IN");
  const MONTHS = { 8: "August", 11: "November" };

  // ---- toast / banner ----
  let toastT;
  function toast(msg) {
    const t = $("toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 2400);
  }
  function showBanner(msg) { const b = $("banner"); b.textContent = msg; b.style.display = "block"; }

  // ---- personalised greeting (independent of the database) ----
  // Share https://your-site/?name=Nikhil → greets on click, remembered after.
  // Rendered via textContent only, so a name can never inject HTML.
  const STORE_KEY = "flighttracker_name";
  function greet() {
    const p = new URLSearchParams(location.search);
    let name = p.get("name") || p.get("u");
    if (name) { name = name.trim().slice(0, 40); localStorage.setItem(STORE_KEY, name); }
    else name = localStorage.getItem(STORE_KEY);
    if (!name) return;
    const pretty = name.charAt(0).toUpperCase() + name.slice(1);
    const h = new Date().getHours();
    const part = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
    $("greeting").textContent = `${part}, ${pretty} 👋`;
  }
  greet();

  if (!cfg.SUPABASE_ANON_KEY || cfg.SUPABASE_ANON_KEY.includes("PASTE_YOUR")) {
    showBanner("Set SUPABASE_ANON_KEY in config.js — see the comment in that file.");
    return;
  }
  const db = window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY);

  // ===================== DASHBOARD =====================
  let priceRows = [];   // cheapest rows across all months
  let activeMonth = 8;

  async function loadDashboard() {
    // Fetch round-trip ("cheapest") AND one-way ("outbound") fares, so a route
    // with no complete round trip can still show its cheapest one-way.
    const { data, error } = await db.from("latest").select("dest,depart,price,captured_at,fare_type")
      .in("fare_type", ["cheapest", "outbound"]);
    if (error) { showBanner("Could not read prices: " + error.message); return; }
    priceRows = (data || []).filter((r) => r.price != null);

    // default to whichever tracked month actually has data
    const has = (m) => priceRows.some((r) => +r.depart.slice(5, 7) === m);
    activeMonth = has(8) ? 8 : has(11) ? 11 : 8;

    renderStats();
    renderUpdated();
    setupSegments();
    renderCards();
  }

  // Cheapest round trip per dest; if none, cheapest one-way (tagged). Round trips
  // are listed first so the "Best deal" badge always lands on a true round trip.
  function bestPerDest(month) {
    const mm = String(month).padStart(2, "0");
    const rt = {}, ow = {};
    for (const r of priceRows) {
      if (r.depart.slice(5, 7) !== mm) continue;
      const bucket = r.fare_type === "cheapest" ? rt : ow;
      if (!bucket[r.dest] || r.price < bucket[r.dest].price) bucket[r.dest] = r;
    }
    const out = [];
    for (const dest of new Set([...Object.keys(rt), ...Object.keys(ow)])) {
      out.push(rt[dest] ? { dest, ...rt[dest], kind: "round trip" }
                        : { dest, ...ow[dest], kind: "one-way" });
    }
    return out.sort((a, b) =>
      a.kind !== b.kind ? (a.kind === "round trip" ? -1 : 1) : a.price - b.price);
  }

  function renderStats() {
    const el = $("stats");
    if (!priceRows.length) { el.innerHTML = ""; return; }
    // Prefer the cheapest round trip for the headline; fall back to one-way.
    const rt = priceRows.filter((r) => r.fare_type === "cheapest");
    const pool = rt.length ? rt : priceRows;
    const cheapest = pool.reduce((m, r) => (r.price < m.price ? r : m));
    const kind = rt.length ? "round trip" : "one-way";
    const city = byCode[cheapest.dest]?.city || cheapest.dest;
    const routes = new Set(priceRows.map((r) => r.dest)).size;
    el.innerHTML = `
      <div class="stat"><div class="k">Cheapest right now</div>
        <div class="v">${rupee(cheapest.price)}</div>
        <div class="meta" style="font-size:13px;color:var(--text-2)">to ${city} · ${kind}</div></div>
      <div class="stat"><div class="k">Routes with prices</div>
        <div class="v">${routes}</div></div>
      <div class="stat"><div class="k">Cost to run</div>
        <div class="v">₹0 <small>/ forever</small></div></div>`;
  }

  function renderUpdated() {
    const t = priceRows.find((r) => r.captured_at)?.captured_at;
    if (t) $("updated").textContent = "Updated " + new Date(t).toLocaleString();
  }

  function setupSegments() {
    $("seg").querySelectorAll(".seg-btn").forEach((b) => {
      b.classList.toggle("active", +b.dataset.month === activeMonth);
      b.onclick = () => { activeMonth = +b.dataset.month; setupSegments(); renderCards(); };
    });
  }

  function renderCards() {
    const el = $("cards");
    const rows = bestPerDest(activeMonth);
    if (!rows.length) {
      el.innerHTML = `<div class="empty" style="grid-column:1/-1">
        <b>No ${MONTHS[activeMonth]} fares yet.</b><br>The free cache only holds fares a few months
        ahead, so they appear closer to travel. The daily job keeps checking.</div>`;
      return;
    }
    el.innerHTML = rows.map((r, i) => {
      const a = byCode[r.dest];
      const d = new Date(r.depart).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
      const tag = `<span class="kind ${r.kind === "one-way" ? "ow" : ""}">${r.kind}</span>`;
      return `<div class="card" style="animation-delay:${i * 45}ms">
        ${i === 0 && r.kind === "round trip" ? '<span class="badge">Best deal</span>' : ""}
        <div><span class="city">${a ? a.city : r.dest}</span><span class="code">${r.dest}</span></div>
        <div class="price">${rupee(r.price)}</div>
        <div class="meta">${tag} · Depart ${d}${a ? " · " + a.state : ""}</div>
      </div>`;
    }).join("");
  }

  // ===================== WATCHLIST =====================
  let selected = new Set(), draft = new Set();
  const search = $("search"), opts = $("opts"), chips = $("chips");
  const saveBtn = $("save"), clearBtn = $("clear"), wlCount = $("wl-count");

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
    const dirty = draft.size !== selected.size || [...draft].some((d) => !selected.has(d));
    wlCount.innerHTML = items.length
      ? `Tracking <b>${items.length}</b> destination${items.length > 1 ? "s" : ""}` +
        (dirty ? ` · unsaved changes — hit <b>Save watchlist</b>` : ` · scanned every day`)
      : `Nothing selected — pick destinations below to start tracking.`;
    chips.innerHTML = items.map((a) => `<span class="chip"><b>${a.iata}</b> ${a.city}
        <span class="x" data-rm="${a.iata}" title="remove">×</span></span>`).join("");
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
        <span class="c">${a.iata}</span> ${a.city}
        <span class="s">${a.state}</span>
      </label>`).join("") || `<div class="opt">No matches.</div>`;
    opts.querySelectorAll("input[data-iata]").forEach((cb) =>
      cb.onchange = () => {
        cb.checked ? draft.add(cb.dataset.iata) : draft.delete(cb.dataset.iata);
        syncDirty(); renderChips();
      });
  }

  function syncDirty() {
    const changed = draft.size !== selected.size || [...draft].some((d) => !selected.has(d));
    saveBtn.disabled = !changed;
    clearBtn.disabled = draft.size === 0;
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
        const { error } = await db.from("watchlist").delete().eq("origin", ORIGIN).in("dest", toRemove);
        if (error) throw error;
      }
      selected = new Set(draft);
      toast("Watchlist saved — the next daily run will use it.");
    } catch (e) {
      toast("Save failed: " + (e.message || e));
      saveBtn.disabled = false;
    }
  }

  // ---- wire up ----
  search.oninput = renderOpts;
  saveBtn.onclick = save;
  clearBtn.onclick = () => { draft.clear(); syncDirty(); renderChips(); renderOpts(); };
  loadWatchlist();
  loadDashboard();
})();

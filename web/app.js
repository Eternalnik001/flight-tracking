// Drives the frontend: theme toggle, hero stats, month-segmented destination
// cards, and the watchlist editor. Talks straight to Supabase via the anon key;
// the Python job (DB owner) bypasses RLS. Page is constrained by supabase_setup.sql.
(function () {
  const cfg = window.CONFIG;
  const ORIGIN = cfg.ORIGIN || "BLR";
  const byCode = Object.fromEntries(window.AIRPORTS.map((a) => [a.iata, a]));
  const $ = (id) => document.getElementById(id);
  const rupee = (n) => "₹" + Math.round(n).toLocaleString("en-IN");
  // Month number -> name, derived (no hardcoded month list anywhere).
  const monthName = (m) => new Date(2000, m - 1, 1).toLocaleString("en", { month: "long" });

  // ---- theme toggle (persisted; defaults to the OS preference) ----
  const THEME_KEY = "ft_theme";
  const SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  const MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
  const themeBtn = $("theme-toggle");
  const effectiveTheme = () =>
    document.documentElement.dataset.theme ||
    (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  function paintThemeBtn() {
    const dark = effectiveTheme() === "dark";
    themeBtn.innerHTML = dark ? SUN : MOON; // show the icon you'll switch TO
    themeBtn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  }
  themeBtn.onclick = () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
    paintThemeBtn();
  };
  // Track OS changes only while the user hasn't pinned a preference.
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    if (!document.documentElement.dataset.theme) paintThemeBtn();
  });
  paintThemeBtn();

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
  let priceRows = [];     // cheapest / live / outbound rows across all months
  let months = [];        // tracked months present in the data (ascending)
  let activeMonth = null;

  // Show a shimmer while the first fetch is in flight.
  $("cards").innerHTML = Array.from({ length: 6 }, () => '<div class="skeleton"></div>').join("");

  async function loadDashboard() {
    // Fetch cached round trips ("cheapest"), live-confirmed round trips ("live"),
    // and one-way legs ("outbound") so every route shows the best price we have.
    const { data, error } = await db.from("latest").select("dest,depart,price,captured_at,fare_type")
      .in("fare_type", ["cheapest", "live", "outbound"]);
    if (error) { showBanner("Could not read prices: " + error.message); $("cards").innerHTML = ""; return; }
    priceRows = (data || []).filter((r) => r.price != null);

    // Derive the tracked months straight from the data — no hardcoded list.
    months = [...new Set(priceRows.map((r) => +r.depart.slice(5, 7)))].sort((a, b) => a - b);
    activeMonth = months[0] ?? null;

    renderStats();
    renderUpdated();
    setupSegments();
    renderCards();
  }

  // Best price per dest: cached round trip → live round trip → cached one-way.
  // Round-trip-equivalent fares lead so the "Best deal" badge lands on a real round trip.
  function bestPerDest(month) {
    const mm = String(month).padStart(2, "0");
    const rt = {}, live = {}, ow = {};
    for (const r of priceRows) {
      if (r.depart.slice(5, 7) !== mm) continue;
      const b = r.fare_type === "cheapest" ? rt : r.fare_type === "live" ? live : ow;
      if (!b[r.dest] || r.price < b[r.dest].price) b[r.dest] = r;
    }
    const out = [];
    for (const dest of new Set([...Object.keys(rt), ...Object.keys(live), ...Object.keys(ow)])) {
      if (rt[dest]) out.push({ dest, ...rt[dest], kind: "round trip" });
      else if (live[dest]) out.push({ dest, ...live[dest], kind: "live" });
      else out.push({ dest, ...ow[dest], kind: "one-way" });
    }
    const rank = { "round trip": 0, live: 0, "one-way": 1 };
    return out.sort((a, b) => rank[a.kind] !== rank[b.kind] ? rank[a.kind] - rank[b.kind] : a.price - b.price);
  }

  function renderStats() {
    const el = $("stats");
    if (!priceRows.length) { el.innerHTML = ""; return; }
    // Prefer round-trip totals (cached or live) for the headline; fall back to one-way.
    const roundish = priceRows.filter((r) => r.fare_type === "cheapest" || r.fare_type === "live");
    const pool = roundish.length ? roundish : priceRows;
    const cheapest = pool.reduce((m, r) => (r.price < m.price ? r : m));
    const kind = !roundish.length ? "one-way" : cheapest.fare_type === "live" ? "live round trip" : "round trip";
    const city = byCode[cheapest.dest]?.city || cheapest.dest;
    const routes = new Set(priceRows.map((r) => r.dest)).size;
    el.innerHTML = `
      <div class="stat"><div class="k">Cheapest right now</div>
        <div class="v">${rupee(cheapest.price)}</div>
        <div class="meta">to ${city} · ${kind}</div></div>
      <div class="stat"><div class="k">Routes with prices</div>
        <div class="v">${routes}</div>
        <div class="meta">across ${months.length} month${months.length === 1 ? "" : "s"}</div></div>
      <div class="stat"><div class="k">Cost to run</div>
        <div class="v">₹0 <small>/ forever</small></div>
        <div class="meta">free APIs + GitHub Actions</div></div>`;
  }

  function renderUpdated() {
    const t = priceRows.find((r) => r.captured_at)?.captured_at;
    if (t) $("updated").textContent = "Updated " + new Date(t).toLocaleString();
  }

  function setupSegments() {
    const seg = $("seg");
    seg.innerHTML = months
      .map((m) => `<button class="seg-btn${m === activeMonth ? " active" : ""}" data-month="${m}">${monthName(m)}</button>`)
      .join("");
    seg.querySelectorAll(".seg-btn").forEach((b) => {
      b.onclick = () => { activeMonth = +b.dataset.month; setupSegments(); renderCards(); };
    });
  }

  function renderCards() {
    const el = $("cards");
    if (activeMonth == null) {
      el.innerHTML = `<div class="empty" style="grid-column:1/-1">
        <b>No fares yet.</b><br>The free cache only holds fares a few months ahead, so they appear
        closer to travel. The daily job keeps checking — pick destinations below to start tracking.</div>`;
      return;
    }
    const rows = bestPerDest(activeMonth);
    if (!rows.length) {
      el.innerHTML = `<div class="empty" style="grid-column:1/-1">
        <b>No ${monthName(activeMonth)} fares yet.</b><br>The free cache only holds fares a few months
        ahead, so they appear closer to travel. The daily job keeps checking.</div>`;
      return;
    }
    el.innerHTML = rows.map((r, i) => {
      const a = byCode[r.dest];
      const d = new Date(r.depart).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
      const cls = r.kind === "one-way" ? "ow" : r.kind === "live" ? "live" : "";
      const isBest = i === 0 && r.kind === "round trip";
      return `<div class="card" style="animation-delay:${i * 45}ms">
        ${isBest ? '<span class="badge">Best deal</span>' : ""}
        <div class="route">${ORIGIN} → ${r.dest}</div>
        <div><span class="city">${a ? a.city : r.dest}</span><span class="code">${a ? a.state : ""}</span></div>
        <div class="price">${rupee(r.price)}</div>
        <div class="meta"><span class="kind ${cls}">${r.kind}</span> · Depart ${d}</div>
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

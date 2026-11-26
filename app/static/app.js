/* Longview — front end. No frameworks: fetch + canvas. */
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
const tidy = (s) => String(s ?? "").replace(/\s+/g, " ").trim();

/* ---------------- bring-your-own model key ----------------
   The key lives only in this browser (localStorage) and rides as an
   X-Longview-LLM header (base64 JSON) on every request. The app never
   stores it server-side; a server-deployed key is the fallback. */
const LLM = {
  base: "", key: "", model: "",
  load() {
    try {
      const s = JSON.parse(localStorage.getItem("longview-llm") || "{}");
      this.base = s.base || ""; this.key = s.key || ""; this.model = s.model || "";
    } catch { /* private mode: run on the server's key */ }
    return this;
  },
  save() {
    try {
      localStorage.setItem("longview-llm", JSON.stringify({
        base: this.base, key: this.key, model: this.model }));
    } catch { /* private mode */ }
  },
  header() {
    if (!this.key) return null;
    const obj = { key: this.key };
    if (this.base) obj.base = this.base;
    if (this.model) obj.model = this.model;
    return btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
  },
};
LLM.load();

/* ---------------- Your data: one file, mirrored in this browser ----------------
   The app keeps everything the reader owns in one file on its machine.
   The client holds a mirror in local storage; on load the two compare
   and the newer one wins (a newer mirror is pushed up). Any section
   write makes the mirror stale — it refreshes itself. Export is a
   download of the file; import is a file picked back in. */
const VAULT = {
  key: "longview-vault",
  data: null,
  load() {
    try {
      const s = JSON.parse(localStorage.getItem(this.key) || "null");
      this.data = (s && s.v === 1 && s.sections) ? s : null;
    } catch { this.data = null; }   // private mode: run on the server's file
    return this;
  },
  save() {
    try {
      if (this.data) localStorage.setItem(this.key, JSON.stringify(this.data));
      else localStorage.removeItem(this.key);
    } catch { /* private mode */ }
  },
  /* The load sync. The server file and this mirror race on `updated`;
     the newer one wins. A down server leaves the mirror as it is. */
  async sync() {
    try {
      const server = await api("/api/vault");
      const mine = this.data;
      if (mine && mine.updated > (server.updated || 0))
        await api("/api/vault", { method: "PUT", body: mine });
      this.data = await api("/api/vault");
      this.save();
    } catch { /* offline: keep what the mirror held */ }
    return this.data;
  },
  /* A section write landed on the server; the mirror is stale. */
  async refresh() {
    if (!this.data) return;
    try {
      this.data = await api("/api/vault");
      this.save();
    } catch { /* server went away: keep the mirror */ }
  },
  /* Download the mirror as the file it is. */
  export() {
    if (!this.data) return false;
    const blob = new Blob([JSON.stringify(this.data, null, 2)],
                          { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "longview.json";
    a.click();
    URL.revokeObjectURL(a.href);
    return true;
  },
  /* Import: parse locally for a fast plain error, then the server's
     replace is the gate (it accepts a full vault, its sections block,
     or a bare section map — and says so in plain English). */
  async importFile(file) {
    if (file.size > 4_000_000)
      throw new Error("That file is bigger than 4 MB — a Longview data file should not be.");
    let parsed;
    try { parsed = JSON.parse(await file.text()); }
    catch { throw new Error("That file did not parse as JSON."); }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
      throw new Error("That file is not a Longview data file.");
    await api("/api/vault", { method: "PUT", body: parsed });
    this.data = await api("/api/vault");
    this.save();
    return this.data;
  },
};
VAULT.load();

/* The routes whose success means the data file changed on the server.
   (The roster writes live under /api/money/roster — the 13F scan pool
   at /api/funds is read-only.) */
const VAULT_WRITERS = ["/api/portfolio", "/api/notes", "/api/risk",
                       "/api/money/roster", "/api/research", "/api/economy"];

async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  const lh = LLM.header();
  if (lh) headers["X-Longview-LLM"] = lh;
  const res = await fetch(path, {
    method,
    headers: Object.keys(headers).length ? headers : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  if (method !== "GET" && VAULT_WRITERS.some((p) => path.startsWith(p)))
    VAULT.refresh();   // quiet: the mirror catches up in the background
  return data;
}

/* ---------------- formatting ---------------- */
const fmtSign = (x, d = 1) => x == null ? "—" : (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(d) + "%";
const fmtMoney = (x) => x == null ? "—" : "$" + Math.round(x).toLocaleString("en-US");
const fmtBig = (x) => {
  if (x == null) return "—";
  const a = Math.abs(x), s = x < 0 ? "-" : "";
  if (a >= 1e12) return s + "$" + (a / 1e12).toFixed(2) + "T";
  if (a >= 1e9) return s + "$" + (a / 1e9).toFixed(1) + "B";
  if (a >= 1e6) return s + "$" + (a / 1e6).toFixed(1) + "M";
  if (a >= 1e3) return s + "$" + (a / 1e3).toFixed(0) + "K";
  return s + "$" + a.toFixed(0);
};
const cls = (x) => x == null ? "flat" : x > 0.0001 ? "up" : x < -0.0001 ? "down" : "flat";
const STATUS_WORD = { new: "New", increased: "Added", decreased: "Reduced",
                      unchanged: "Unchanged", exited: "Exited" };
const stCls = (s) => s === "new" ? "st-new" : s === "increased" ? "st-up"
  : s === "decreased" ? "st-down" : s === "exited" ? "st-exit" : "st-flat";

/* ---------------- save this: anything -> your notes ---------------- */

const fmtDate = (ts) => ts
  ? new Date(ts * 1000).toLocaleDateString("en-US",
      { month: "short", day: "numeric", year: "numeric" })
  : "";

let _toastT = null;
function toast(msg) {
  let el = $("#toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("on");
  clearTimeout(_toastT);
  _toastT = setTimeout(() => el.classList.remove("on"), 2600);
}

const SAVE_SOURCES = { ask: "Ask", backtest: "Backtest", money: "Smart money",
                       company: "Company", other: "Note" };
const srcChip = (s) => `<span class="src-chip src-${esc(s)}">${SAVE_SOURCES[s] || "Note"}</span>`;

/* The save sheet: a preview of the piece, then "which page" — an existing
   note or a new one. Re-saving the same piece to the same page is a no-op
   (the server knows), so the button can be pressed again while thinking. */
let _sheetBusy = false;
function saveThis(source, title, lines) {
  // One sheet at a time: a second Save click while the sheet is open — or
  // still loading — would otherwise stack a second sheet, and the two
  // sheets' page radios share one group, so a pick could vanish.
  if (_sheetBusy) return;
  _sheetBusy = true;
  document.querySelector(".sheet-backdrop")?.remove();
  api("/api/notes").then((d) => {
    const pages = d.pages || [];
    const sheet = document.createElement("div");
    sheet.className = "sheet-backdrop";
    sheet.innerHTML = `
      <div class="sheet" role="dialog" aria-label="Save to your notes">
        <div class="sheet-head">
          <strong>Save to your notes</strong>
          <button class="sheet-x" type="button" aria-label="Close">×</button>
        </div>
        <div class="sheet-prev snip">
          ${srcChip(source)}
          ${title ? `<div class="snip-title">${esc(title)}</div>` : ""}
          <pre class="snip-lines">${esc(lines.slice(0, 5).join("\n"))}${lines.length > 5 ? "\n…" : ""}</pre>
        </div>
        <label class="sheet-label">Add it to</label>
        <div class="sheet-pages">
          ${pages.map((p, i) => `
            <label class="sheet-page">
              <input type="radio" name="snpage" value="${esc(p.id)}" ${i === 0 ? "checked" : ""}>
              <span>${esc(p.title)}</span>
              <small>${fmtDate(p.updated)}${p.n_snippets ? ` · ${p.n_snippets} saved` : ""}</small>
            </label>`).join("")
          || `<p class="empty">No pages yet — it will make a new one.</p>`}
          <label class="sheet-page">
            <input type="radio" name="snpage" value="__new__" ${pages.length ? "" : "checked"}>
            <span>New page</span>
          </label>
        </div>
        <input id="sheet-newtitle" placeholder="Name the new page" maxlength="120" hidden>
        <div class="sheet-actions">
          <button class="btn ghost" id="sheet-cancel" type="button">Cancel</button>
          <button class="btn primary" id="sheet-save" type="button">Save</button>
        </div>
        <p id="sheet-status" class="status"></p>
      </div>`;
    document.body.appendChild(sheet);
    const close = () => { sheet.remove(); _sheetBusy = false; };
    sheet.addEventListener("click", (e) => { if (e.target === sheet) close(); });
    sheet.querySelector(".sheet-x").addEventListener("click", close);
    sheet.querySelector("#sheet-cancel").addEventListener("click", close);
    const newTitle = sheet.querySelector("#sheet-newtitle");
    sheet.querySelectorAll('input[name="snpage"]').forEach((r) =>
      r.addEventListener("change", () => {
        const isNew = r.checked && r.value === "__new__";
        newTitle.hidden = !isNew;
        if (isNew) newTitle.focus();
      }));
    const save = async () => {
      const s = sheet.querySelector('input[name="snpage"]:checked');
      const stt = sheet.querySelector("#sheet-status");
      stt.className = "status";
      stt.textContent = "Saving…";
      sheet.querySelector("#sheet-save").disabled = true;
      try {
        let pid;
        if (s && s.value === "__new__") {
          const page = await api("/api/notes", { method: "POST",
            body: { title: newTitle.value.trim() || "Untitled" } });
          pid = page.id;
        } else if (s) {
          pid = s.value;
        } else {
          const page = await api("/api/notes", { method: "POST",
            body: { title: "Untitled" } });
          pid = page.id;
        }
        const saved = await api("/api/notes/" + encodeURIComponent(pid) + "/snippets",
          { method: "POST", body: { source, title, lines } });
        toast(`Saved to “${saved.title || "Untitled"}”`);
        close();
        if (document.getElementById("tab-notes").classList.contains("active"))
          showNotesTab();
      } catch (e) {
        stt.className = "status error";
        stt.textContent = e.message;
        sheet.querySelector("#sheet-save").disabled = false;
      }
    };
    sheet.querySelector("#sheet-save").addEventListener("click", save);
    newTitle.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
    if (pages.length) sheet.querySelector('input[name="snpage"]').focus();
  }).catch((e) => { _sheetBusy = false; toast("Couldn't open your notes: " + e.message); });
}

/* ---------------- navigation + tabbed workspaces ---------------- */
const MONEY_SUBS = ["funds", "quarter", "scan", "ask"];
const LAB_STEPS = ["strategy", "setup", "results"];
const HOME_SUBS = ["portfolio", "money"];
const WS_KINDS = ["company", "notes", "money", "lab", "compare"];
const MONEY_TITLE = { funds: "Funds", quarter: "This quarter",
                      scan: "Holdings", ask: "Ask" };
const LAB_DEFAULT = () => ({
  step: "strategy", mode: "my_plan", text: "", tickers: "SPY", years: 10,
  cash: 100000, frequency: "month", triggers: [], onDrop: "hold",
  addPct: 10, exitPct: null, research: false, names: {}, start: null, end: null,
});
const WS_DEFAULT = {
  company: () => ({ symbol: "" }),
  notes: () => ({ pageId: "" }),
  money: () => ({ sub: "funds", secName: "" }),
  lab: LAB_DEFAULT,
  compare: () => ({ picks: [], ai: null, model: null, note: null }),
};
const WS = {};

function wsRestoreAll() {
  WS_KINDS.forEach((kind) => {
    const w = { tabs: [], active: null, seq: 0 };
    WS[kind] = w;
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem("proof-ws-" + kind) || "null"); }
    catch { /* private mode */ }
    if (saved && Array.isArray(saved.tabs)) {
      w.seq = Number(saved.seq) || 0;
      w.tabs = saved.tabs.filter((t) => t && t.id && t.state).slice(0, 12)
        .map((t) => ({
          id: String(t.id), title: String(t.title || ""),
          state: Object.assign(WS_DEFAULT[kind](), t.state),
        }));
    }
    if (!w.tabs.length) w.tabs.push(wsNewTab(kind, WS_DEFAULT[kind]()));
    // Come back to the tab you were on, if it still exists.
    w.active = (saved && w.tabs.some((t) => t.id === String(saved.active)))
      ? String(saved.active) : w.tabs[0].id;
  });
}

function wsSave(kind) {
  try {
    const w = WS[kind];
    localStorage.setItem("proof-ws-" + kind, JSON.stringify({
      seq: w.seq, active: w.active,
      tabs: w.tabs.map((t) => ({ id: t.id, title: t.title, state: t.state })),
    }));
  } catch { /* private mode */ }
}

function wsNewTab(kind, state, title) {
  const w = WS[kind];
  w.seq += 1;
  return {
    id: kind + "-" + w.seq,
    title: title || "",
    state: Object.assign(WS_DEFAULT[kind](), state || {}),
  };
}

function wsAddTab(kind, state, title) {
  const w = WS[kind];
  if (w.tabs.length >= 12) {
    toast("Close a page first.");
    return null;
  }
  const t = wsNewTab(kind, state, title);
  w.tabs.push(t);
  return t;
}

function activeWS(kind) {
  const w = WS[kind];
  return w ? w.tabs.find((t) => t.id === w.active) : null;
}

function wsTitle(kind, tab) {
  const s = tab.state || {};
  if (kind === "company") return s.symbol || tab.title || "Search";
  if (kind === "notes") return s.pageId ? (tab.title || "Note") : "Notes";
  if (kind === "money")
    return s.secName ? "Holdings · " + s.secName : (MONEY_TITLE[s.sub] || "Smart money");
  if (kind === "compare") {
    const names = (s.picks || []).map((p) => p.name || "?");
    if (!names.length) return "Compare";
    const shown = names.slice(0, 2).join(" vs ") + (names.length > 2 ? " +" + (names.length - 2) : "");
    return "Compare · " + shown;
  }
  return tab.title || "Backtest";
}

function wsHash(kind, tab) {
  if (kind === "company") return "company/@" + tab.id;
  if (kind === "notes") return "notes/@" + tab.id;
  if (kind === "money") return "money/@" + tab.id;
  if (kind === "compare") return "compare/@" + tab.id;
  return "lab/@" + tab.id + "/" + (tab.state.step || "strategy");
}

function wsRender(kind) {
  const box = document.getElementById("ws-" + kind);
  const w = WS[kind];
  if (!box || !w) return;
  const titles = w.tabs.map((t) => wsTitle(kind, t));
  const counts = {};
  titles.forEach((x) => (counts[x] = (counts[x] || 0) + 1));
  const used = {};
  const shown = titles.map((x) => {
    if (counts[x] <= 1) return x;
    const n = (used[x] = (used[x] || 0) + 1);
    return n === 1 ? x : x + " · " + n;  // first stays plain, repeats get a number
  });
  box.innerHTML = w.tabs.map((t, i) => `
    <span class="wtab${t.id === w.active ? " active" : ""}" data-id="${esc(t.id)}" draggable="true">
      <button class="wtab-name" type="button" data-id="${esc(t.id)}"
        title="${esc(titles[i])}">${esc(shown[i])}</button>
      <button class="wtab-x" type="button" data-id="${esc(t.id)}" aria-label="Close">×</button>
    </span>`).join("")
    + `<button class="wtab-add" type="button" title="New page" aria-label="New page">+</button>`;
  box.querySelectorAll(".wtab-name").forEach((b) =>
    b.addEventListener("click", () => wsActivate(kind, b.dataset.id, { hash: true })));
  box.querySelectorAll(".wtab-x").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      wsClose(kind, b.dataset.id);
    }));
  box.querySelector(".wtab-add").addEventListener("click", () => wsAddFromStrip(kind));
  let drag = null;
  box.querySelectorAll(".wtab").forEach((el) => {
    el.addEventListener("dragstart", (e) => {
      drag = el.dataset.id;
      el.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
    });
    el.addEventListener("dragend", () => {
      drag = null;
      el.classList.remove("dragging");
    });
    el.addEventListener("dragover", (e) => e.preventDefault());
    el.addEventListener("drop", (e) => {
      e.preventDefault();
      if (drag) wsMove(kind, drag, el.dataset.id);
    });
  });
}

function wsMove(kind, from, to) {
  const w = WS[kind];
  const i = w.tabs.findIndex((t) => t.id === from);
  const j = w.tabs.findIndex((t) => t.id === to);
  if (i < 0 || j < 0 || i === j) return;
  const [t] = w.tabs.splice(i, 1);
  w.tabs.splice(j, 0, t);
  wsSave(kind);
  wsRender(kind);
}

function wsLeave(kind) {
  if (kind === "notes" && NOTES.flush) {
    NOTES.flush();
    NOTES.flush = null;
  }
  if (kind === "lab") {
    const t = activeWS("lab");
    if (t) {
      t.state.text = $("#strategy-text").value;
      t.state.symbol = $("#symbol").value.trim().toUpperCase() || "SPY";
      t.state.years = parseInt($("#years").value, 10) || 10;
    }
  }
}

function wsActivate(kind, id, { hash = false, show = true } = {}) {
  const w = WS[kind];
  const t = w.tabs.find((x) => x.id === id);
  if (!t) return false;
  if (w.active !== id) {
    wsLeave(kind);
    w.active = id;
  }
  wsSave(kind);
  wsRender(kind);
  if (hash) {
    const target = "#" + wsHash(kind, t);
    if (location.hash !== target) { location.hash = target; return true; }
  }
  if (show) wsShow(kind);
  return true;
}

function wsClose(kind, id) {
  const w = WS[kind];
  const i = w.tabs.findIndex((t) => t.id === id);
  if (i < 0) return;
  if (w.active === id) wsLeave(kind);
  w.tabs.splice(i, 1);
  if (!w.tabs.length) w.tabs.push(wsNewTab(kind, WS_DEFAULT[kind]()));
  if (w.active === id)
    w.active = w.tabs[Math.min(i, w.tabs.length - 1)].id;
  wsSave(kind);
  wsRender(kind);
  const t = w.tabs.find((x) => x.id === w.active);
  const target = "#" + wsHash(kind, t);
  if (location.hash !== target) location.hash = target;
  else wsShow(kind);
}

async function wsAddFromStrip(kind) {
  if (kind === "notes") {
    try {
      const p = await api("/api/notes", { method: "POST", body: { title: "" } });
      wsOpen("notes", { pageId: p.id }, "Note");
    } catch (e) {
      toast("Couldn't make a page: " + e.message);
    }
    return;
  }
  if (kind === "company") { wsOpen("company", { symbol: "" }); return; }
  if (kind === "money") {
    const t = activeWS("money");
    wsOpen("money", { sub: t ? t.state.sub : "funds", secName: "" });
    return;
  }
  if (kind === "compare") { wsOpen("compare", WS_DEFAULT.compare()); return; }
  wsOpen("lab", LAB_DEFAULT());
}

function wsOpen(kind, state, title) {
  const t = wsAddTab(kind, state, title);
  if (!t) return null;
  wsActivate(kind, t.id, { hash: true });
  return t;
}

function wsShow(kind) {
  if (kind === "company") showCompanyTab();
  else if (kind === "notes") showNotesTab();
  else if (kind === "money") showMoneyTab();
  else if (kind === "lab") showLabTab();
  else if (kind === "compare") showCompareTab();
}

function showPane(kind) {
  $$(".tabpane").forEach((p) => p.classList.toggle("active", p.id === "tab-" + kind));
}

function syncNav(kind, sub) {
  const route = sub ? kind + "/" + sub : kind;
  $$(".sidebar .nav").forEach((a) => {
    const r = a.dataset.route;
    a.classList.toggle("active", r === route || r === kind);
  });
}

/* A hash can name a tab that is no longer open (you closed it, or another
   window of Longview got here first). Fall back to the current page and quietly
   fix the address — never spawn a ghost tab for a ghost id. */
function wsStaleFallback(kind, t) {
  if (t) return t;
  const w = WS[kind];
  const f = w.tabs.find((x) => x.id === w.active) || w.tabs[0];
  if (!f) return null;
  wsActivate(kind, f.id, { show: false });
  const target = "#" + wsHash(kind, f);
  if (location.hash !== target) history.replaceState(null, "", target);
  return f;
}

function applyHash() {
  const raw = (location.hash || "#home/portfolio").replace(/^#/, "");
  const parts = raw.split("/");
  const kind = parts[0] || "home";
  if (kind === "home") {
    const sub = HOME_SUBS.includes(parts[1]) ? parts[1] : "portfolio";
    showPane("home");
    $$(".subpane").forEach((p) =>
      p.classList.toggle("active", p.id === "sub-" + sub));
    $$(".htab").forEach((b) =>
      b.classList.toggle("active", b.dataset.sub === sub));
    syncNav("home", sub);
    if (sub === "money") loadGlance();
    else loadPortfolio();
    reveal(document.getElementById("sub-" + sub));
    return;
  }
  if (kind === "company") {
    resolveCompany(parts[1]);
    return;
  }
  if (kind === "notes") {
    resolveNotes(parts[1]);
    return;
  }
  if (kind === "money") {
    resolveMoney(parts[1]);
    return;
  }
  if (kind === "risk") {
    resolveRisk();
    return;
  }
  if (kind === "economy") {
    resolveEconomy(parts.slice(1));
    return;
  }
  if (kind === "research") {
    resolveResearch(parts[1]);
    return;
  }
  if (kind === "settings") {
    resolveSettings();
    return;
  }
  if (kind === "docs") {
    resolveDocs();
    return;
  }
  if (kind === "compare") {
    resolveCompare(parts[1]);
    return;
  }
  resolveLab(parts);
}

function resolveCompany(seg) {
  showPane("company");
  let t = null;
  if (!seg) t = WS.company.tabs.find((x) => !x.state.symbol);
  else if (seg.startsWith("@"))
    t = WS.company.tabs.find((x) => x.id === seg.slice(1));
  else {
    const sym = decodeURIComponent(seg).toUpperCase();
    t = WS.company.tabs.find(
      (x) => (x.state.symbol || "").toUpperCase() === sym);
    if (!t) {
      const blank = WS.company.tabs.find((x) => !x.state.symbol);
      if (blank && WS.company.tabs.length === 1) {
        blank.state.symbol = sym;
        t = blank;
      } else {
        t = wsAddTab("company", { symbol: sym });
      }
    }
  }
  t = wsStaleFallback("company", t);
  if (!t) { t = wsAddTab("company", { symbol: "" }); }
  wsActivate("company", t.id, { show: false });
  syncNav("company");
  wsShow("company");
}

function resolveNotes(seg) {
  showPane("notes");
  let t = null;
  if (!seg) t = WS.notes.tabs.find((x) => !x.state.pageId);
  else if (seg.startsWith("@"))
    t = WS.notes.tabs.find((x) => x.id === seg.slice(1));
  else {
    const pid = decodeURIComponent(seg);
    t = WS.notes.tabs.find((x) => x.state.pageId === pid);
    if (!t) t = wsAddTab("notes", { pageId: pid }, "Note");
  }
  if (!t) t = wsStaleFallback("notes", t) || wsAddTab("notes", { pageId: "" }, "Notes");
  wsActivate("notes", t.id, { show: false });
  syncNav("notes");
  wsShow("notes");
}

function resolveMoney(seg) {
  showPane("money");
  let t = null;
  if (seg && seg.startsWith("@"))
    t = WS.money.tabs.find((x) => x.id === seg.slice(1));
  else {
    const sub = MONEY_SUBS.includes(seg) ? seg : "funds";
    t = WS.money.tabs.find((x) => x.state.sub === sub && !x.state.secName);
    if (!t) t = wsAddTab("money", { sub, secName: "" });
  }
  if (!t) t = wsStaleFallback("money", t) || wsAddTab("money", WS_DEFAULT.money());
  wsActivate("money", t.id, { show: false });
  syncNav("money", t.state.sub);
  wsShow("money");
}

function resolveLab(parts) {
  showPane("lab");
  let t = null;
  let step;
  if (parts[1] && parts[1].startsWith("@")) {
    t = WS.lab.tabs.find((x) => x.id === parts[1].slice(1));
    step = LAB_STEPS.includes(parts[2])
      ? parts[2] : (t ? t.state.step : "strategy");
  } else {
    step = LAB_STEPS.includes(parts[1]) ? parts[1] : "strategy";
    t = activeWS("lab") || WS.lab.tabs[0];
  }
  t = wsStaleFallback("lab", t);
  if (!t) t = wsAddTab("lab", LAB_DEFAULT());
  t.state.step = LAB_STEPS.includes(step) ? step : "strategy";
  wsActivate("lab", t.id, { show: false });
  syncNav("lab", t.state.step);
  wsShow("lab");
}

window.addEventListener("hashchange", applyHash);
const go = (route) => { location.hash = route; };

/* ---------------- Research · give it a goal ----------------
    The section the old study centre used to be. The reference notes it
    served are gone from the section; it starts blank. The input is a
    goal — one or two sentences about what the reader wants to
    understand or decide. A run reads the open textbooks and papers on
    it (Wikipedia, Wikibooks, Wikiversity, the arXiv — the hosts are
    fixed), then the model writes one saved report whose final part
    ties the findings to whatever the vault holds. No workspace tabs:
    the goal card, the list, and a report are the whole page.
    ------------------------------------------------------------------------ */

const RESEARCH = { reports: null, meta: null, loading: false, id: null,
                   runBusy: false, runPoll: null, runId: null };

function stopResearchPoll() {
  if (RESEARCH.runPoll) clearInterval(RESEARCH.runPoll);
  RESEARCH.runPoll = null;
}

function researchStatus(msg, isErr) {
  const st = $("#research-status");
  st.className = "status" + (isErr ? " error" : "");
  st.textContent = msg || "";
}

async function loadResearch(force) {
  if (RESEARCH.loading || (RESEARCH.reports !== null && !force)) return;
  RESEARCH.loading = true;
  researchStatus("Opening the section…");
  try {
    const d = await api("/api/research");
    RESEARCH.reports = d.reports || [];
    RESEARCH.meta = d.meta || null;
    researchStatus("");
    if (RESEARCH.id) renderResearchReport(RESEARCH.id);
    else renderResearchList();
  } catch (e) {
    researchStatus(e.message, true);
    $("#research-body").innerHTML = "";
  } finally {
    RESEARCH.loading = false;
  }
}

function researchCard(n) {
  const c = document.createElement("div");
  c.className = "study-card";
  c.setAttribute("role", "button");
  c.tabIndex = 0;
  const top = document.createElement("div");
  top.className = "sc-top";
  const chip = document.createElement("span");
  chip.className = "field-chip";
  chip.textContent = n.field;
  top.appendChild(chip);
  if (n.kind === "ai") {
    const b = document.createElement("span");
    b.className = "ai-badge";
    b.textContent = "AI";
    top.appendChild(b);
  }
  const h = document.createElement("h3");
  h.textContent = n.title;
  const s = document.createElement("p");
  s.className = "sc-sum";
  s.textContent = n.summary;
  const foot = document.createElement("div");
  foot.className = "sc-foot";
  const mins = document.createElement("span");
  mins.className = "mins";
  mins.textContent = n.minutes + " min read";
  foot.appendChild(mins);
  if (n.kind === "ai") {
    const parts = [n.model, n.created].filter(Boolean);
    if (n.sources) parts.push(n.sources + " web source" + (n.sources > 1 ? "s" : ""));
    if (parts.length) {
      const from = document.createElement("span");
      from.className = "mins";
      from.textContent = parts.join(" · ");
      foot.appendChild(from);
    }
  }
  c.append(top, h, s, foot);
  const open = () => go("#research/" + encodeURIComponent(n.id));
  c.addEventListener("click", open);
  c.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
  });
  return c;
}

function renderResearchList() {
  const body = $("#research-body");
  body.innerHTML = "";
  body.appendChild(researchGoalCard());
  if (RESEARCH.reports.length) {
    const grid = document.createElement("div");
    grid.className = "study-grid";
    RESEARCH.reports.forEach((n) => grid.appendChild(researchCard(n)));
    body.appendChild(grid);
  } else {
    const empty = document.createElement("div");
    empty.className = "card";
    empty.textContent = "No reports yet. Give it a goal above to write the first one.";
    body.appendChild(empty);
  }
  reveal(body);
}

/* The goal card: always at the top of the section. Its fine print says
   what a run will tie into, from the section's counts of the vault. */
function researchGoalCard() {
  const card = document.createElement("div");
  card.className = "card study-doc";
  const d = (RESEARCH.meta && RESEARCH.meta.data) || {};
  const bits = [];
  if (d.portfolio) bits.push(d.portfolio + " holding" + (d.portfolio === 1 ? "" : "s"));
  if (d.pages) bits.push(d.pages + " note page" + (d.pages === 1 ? "" : "s"));
  if (d.moves) bits.push(d.moves + " risk move" + (d.moves === 1 ? "" : "s"));
  let ties = bits.length
    ? " When it is written, the report's final part ties the findings to your file — right now that's " + bits.join(", ") + "."
    : " Your file is empty, so the report stands on its own.";
  if (RESEARCH.meta && !RESEARCH.meta.llm)
    ties += " <b>No model key is set</b>: the run will gather the pages, but it cannot write the report until you add one in Settings.";
  card.innerHTML =
    '<h3>Research a goal</h3>' +
    '<p class="desc">Say what you want to understand or decide — a sentence or two. ' +
    'The run reads the open textbooks and papers on it (Wikipedia, Wikibooks, ' +
    'Wikiversity, the arXiv), then the model writes one saved report.' +
    ties + '</p>' +
    '<textarea id="research-goal" maxlength="2000" placeholder="e.g. I hold credit and keep seeing “high yield” — what does that actually cost me?"></textarea>' +
    '<div class="doc-row">' +
    '<button class="btn primary" id="research-goal-btn" type="button">Research it</button>' +
    '</div>' +
    '<p class="doc-hint" id="research-goal-hint"></p>' +
    '<div class="search-progress" id="research-progress" hidden>' +
    '<span class="spinner" aria-hidden="true"></span>' +
    '<span id="research-progress-msg">Starting the research…</span>' +
    '</div>';
  card.querySelector("#research-goal-btn").addEventListener("click", researchSubmit);
  card.querySelector("#research-goal").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) researchSubmit();
  });
  return card;
}

async function researchSubmit() {
  if (RESEARCH.runBusy) return;
  const goal = ($("#research-goal")?.value || "").trim();
  const hint = $("#research-goal-hint");
  const prog = $("#research-progress");
  const msg = $("#research-progress-msg");
  const btn = $("#research-goal-btn");
  if (goal.length < 10) {
    hint.textContent = "That's not much of a goal — a sentence or two at least.";
    return;
  }
  RESEARCH.runBusy = true;
  btn.disabled = true;
  btn.textContent = "Researching…";
  hint.textContent = "";
  prog.hidden = false;
  msg.textContent = "Starting the research…";
  try {
    const job = await api("/api/research/run", { method: "POST", body: { goal } });
    RESEARCH.runId = job.id;
    researchPollRun(job.id);
  } catch (e) {
    prog.hidden = true;
    hint.textContent = e.message;
  } finally {
    RESEARCH.runBusy = false;
    btn.disabled = false;
    btn.textContent = "Research it";
  }
}

function researchPollRun(id) {
  stopResearchPoll();
  const tick = async () => {
    let job;
    try {
      job = await api("/api/research/run/" + encodeURIComponent(id));
    } catch {
      return; // a transient poll failure; the next tick retries
    }
    // The card may be gone if the reader left the pane; work around it.
    const prog = $("#research-progress");
    const msg = $("#research-progress-msg");
    const hint = $("#research-goal-hint");
    const lines = job.progress && job.progress.length ? job.progress : [];
    if (msg) msg.textContent = lines[lines.length - 1] ||
      (job.status === "running" ? "Working…" : job.message || job.status);
    if (job.status === "running") return;
    stopResearchPoll();
    RESEARCH.runId = null;
    if (prog) prog.hidden = true;
    if (job.status === "done" && job.report) {
      RESEARCH.reports = null; // the saved report joins the list on the way back
      VAULT.refresh(); // the worker saved it on the server; the mirror is stale
      if (hint) hint.textContent = "";
      if ((location.hash === "#research"))
        go("#research/" + encodeURIComponent(job.report.id));
      else
        toast("Research report saved: " + job.report.title);
    } else if (hint) {
      const names = (job.sources || []).map((s) => s.title).slice(0, 5).join(" · ");
      hint.textContent = (job.message || "The run finished.") +
        (names ? " What it found: " + names + "." : "");
    }
  };
  tick(); // fire once now, then on the interval
  RESEARCH.runPoll = setInterval(tick, 4000);
}

async function renderResearchReport(id) {
  researchStatus("Reading the report…");
  const body = $("#research-body");
  try {
    const n = await api("/api/research/" + encodeURIComponent(id));
    researchStatus("");
    body.innerHTML = "";
    const back = document.createElement("a");
    back.className = "study-back";
    back.href = "#research";
    back.textContent = "← All reports";
    body.appendChild(back);
    const card = document.createElement("div");
    card.className = "study-note";
    const meta = document.createElement("div");
    meta.className = "sn-meta";
    const chip = document.createElement("span");
    chip.className = "field-chip";
    chip.textContent = n.field;
    meta.appendChild(chip);
    if (n.kind === "ai") {
      const b = document.createElement("span");
      b.className = "ai-badge";
      b.textContent = n.sources && n.sources.length
        ? "AI-written from " + n.sources.length + " web source" + (n.sources.length > 1 ? "s" : "")
        : "AI-written";
      meta.appendChild(b);
    }
    const mins = document.createElement("span");
    mins.className = "mins";
    mins.textContent = n.minutes + " min read";
    meta.appendChild(mins);
    if (n.created) {
      const when = document.createElement("span");
      when.className = "mins";
      when.textContent = n.created;
      meta.appendChild(when);
    }
    const h1 = document.createElement("h1");
    h1.textContent = n.title;
    card.appendChild(meta);
    card.appendChild(h1);
    if (n.goal) {
      const g = document.createElement("p");
      g.className = "sn-goal";
      g.textContent = "Goal: " + n.goal;
      card.appendChild(g);
    }
    if (n.summary) {
      const s = document.createElement("p");
      s.className = "sn-sum";
      s.textContent = n.summary;
      card.appendChild(s);
    }
    if (Array.isArray(n.ties) && n.ties.length) {
      const t = document.createElement("div");
      t.className = "sn-ties";
      const strong = document.createElement("strong");
      strong.textContent = "How this ties into your data";
      t.appendChild(strong);
      const ul = document.createElement("ul");
      n.ties.forEach((line) => {
        const li = document.createElement("li");
        li.textContent = line;
        ul.appendChild(li);
      });
      t.appendChild(ul);
      card.appendChild(t);
    }
    if (Array.isArray(n.sources) && n.sources.length) {
      const anchors = n.sources
        .filter((s) => s.url && /^https?:/.test(s.url))
        .map((s) => {
          const a = document.createElement("a");
          a.href = s.url;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          a.textContent = s.title || s.url;
          return a;
        });
      if (anchors.length) {
        const src = document.createElement("p");
        src.className = "sn-sources";
        src.appendChild(document.createTextNode("Sources: "));
        anchors.forEach((a, i) => {
          if (i) src.appendChild(document.createTextNode(" · "));
          src.appendChild(a);
        });
        card.appendChild(src);
      }
    }
    /* n.html is the server-rendered, escaped body */
    const art = document.createElement("div");
    art.innerHTML = n.html;
    card.appendChild(art);
    if (n.kind === "ai") {
      const d = document.createElement("button");
      d.className = "btn ghost study-delete";
      d.type = "button";
      d.textContent = "Delete this report";
      d.addEventListener("click", () => deleteResearch(n.id));
      card.appendChild(d);
    }
    body.appendChild(card);
    reveal(body);
  } catch (e) {
    researchStatus(e.message, true);
    body.innerHTML = "";
  }
}

async function deleteResearch(id) {
  const btn = $(".study-delete");
  if (btn) { btn.disabled = true; btn.textContent = "Deleting…"; }
  try {
    await api("/api/research/" + encodeURIComponent(id), { method: "DELETE" });
    RESEARCH.reports = null;
    go("#research");
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = "Delete this report"; }
    researchStatus(e.message, true);
  }
}

function resolveResearch(seg) {
  showPane("research");
  const nid = seg ? decodeURIComponent(seg) : null;
  RESEARCH.id = nid;
  syncNav("research", nid);
  $("#research-title").textContent = "Research";
  if (RESEARCH.reports === null) loadResearch();
  else if (nid) renderResearchReport(nid);
  else renderResearchList();
  reveal($("#tab-research"));
}

/* ---------------- Settings · bring your own model key ---------------- */
function setMsg(text, isErr) {
  const el = $("#set-status");
  if (!el) return;
  el.textContent = text || "";
  el.className = "status" + (isErr ? " error" : "");
}

function setEffective() {
  const el = $("#set-effective");
  if (!el) return;
  const y = (s) => { try { return JSON.parse(s || "null"); } catch { return null; } };
  return api("/api/llm").then((d) => {
    const label = d.source === "request" ? "your key (this browser)"
      : d.source === "env" ? "the server's key" : "no model set";
    el.textContent = `Currently answering with: ${label} — ${d.model} at ${d.base}`
      + (d.source === "none" ? ". Add a key above to use the AI features." : ".");
  }).catch(() => { el.textContent = ""; });
}

function resolveSettings() {
  showPane("settings");
  syncNav("settings");
  $("#set-base").value = LLM.base;
  $("#set-key").value = LLM.key;
  $("#set-model").value = LLM.model;
  setMsg(LLM.key ? "Saved in this browser. It is sent with each request and never stored on the server." : "", false);
  setEffective();
  vaultSummary();
  VAULT.refresh().then(vaultSummary);
  reveal($("#tab-settings"));
}

/* ---------------- Settings · your data (the vault, one file) ---------------- */

function vaultSummary() {
  const el = $("#vault-summary");
  if (!el) return;
  const s = (VAULT.data && VAULT.data.sections) || {};
  const count = (v) => Array.isArray(v) ? v.length
    : (v && typeof v === "object") ? Object.keys(v).length : 0;
  const bits = [];
  const add = (n, singular, plural) => {
    if (n) bits.push(n + " " + (n === 1 ? singular : plural));
  };
  add(count(s.portfolio && s.portfolio.positions), "holding", "holdings");
  add(count(s.notes && s.notes.pages), "note page", "note pages");
  add(count(s.risk && s.risk.moves), "risk move", "risk moves");
  add(count(s.roster && s.roster.funds), "followed fund", "followed funds");
  add(count(s.research && s.research.reports), "research report", "research reports");
  if (s.economy) bits.push("the economy tree");
  const when = VAULT.data && VAULT.data.updated
    ? new Date(VAULT.data.updated * 1000).toLocaleDateString("en-US",
        { month: "short", day: "numeric", year: "numeric" }) : "";
  el.textContent = bits.length
    ? "On file: " + bits.join(", ") + (when ? " — updated " + when : "") + "."
    : "Nothing on file yet — add holdings, save notes, or research a goal, and it will appear here.";
}

$("#vault-export").addEventListener("click", () => {
  const st = $("#vault-status");
  if (!VAULT.export()) {
    st.className = "status error";
    st.textContent = "There is no file to download yet — nothing has been saved.";
    return;
  }
  st.className = "status";
  st.textContent = "longview.json is downloading — that is your whole data.";
});

$("#vault-import").addEventListener("click", () => $("#vault-file").click());

$("#vault-file").addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const st = $("#vault-status");
  st.className = "status";
  st.textContent = "Importing…";
  try {
    await VAULT.importFile(file);
    vaultSummary();
    st.textContent = "Imported — that file is the app's data now.";
  } catch (err) {
    st.className = "status error";
    st.textContent = err.message;
  }
});

function settingsForm() {
  return { base: $("#set-base").value.trim(),
            key: $("#set-key").value.trim(),
            model: $("#set-model").value.trim() };
}

$("#set-save").addEventListener("click", () => {
  Object.assign(LLM, settingsForm());
  LLM.save();
  setMsg(LLM.key
    ? "Saved in this browser. Every request now carries it; the app never stores it on the server."
    : "Cleared from this browser. The app runs on the server's own key, if it has one.",
    false);
  setEffective();
});

$("#set-clear").addEventListener("click", () => {
  LLM.base = LLM.key = LLM.model = "";
  LLM.save();
  ["set-base", "set-key", "set-model"].forEach((id) => { $("#set-" + id).value = ""; });
  setMsg("Cleared from this browser. The app runs on the server's own key, if it has one.", false);
  setEffective();
});

function resolveDocs() {
  showPane("docs");
  syncNav("docs");
  reveal($("#tab-docs"));
}

$("#set-test").addEventListener("click", async () => {
  const btn = $("#set-test");
  btn.disabled = true;
  btn.textContent = "Testing…";
  setMsg("");
  try {
    const d = await api("/api/llm/test", { method: "POST", body: settingsForm() });
    setMsg(d.ok
      ? `Connected. The model answers as "${d.model}" in ${d.ms} ms.`
      : (d.error || "the connection failed"), !d.ok);
  } catch (e) {
    setMsg(e.message, true);
  }
  btn.disabled = false;
  btn.textContent = "Test connection";
});

/* motion: re-run the rise-in animation over a container's children, staggered */
function reveal(container) {
  if (!container) return;
  container.classList.remove("reveal");
  void container.offsetWidth;
  container.classList.add("reveal");
  Array.from(container.children).forEach((c, i) =>
    c.style.setProperty("--d", Math.min(i, 10) * 40 + "ms"));
}

/* ---------------- backtest lab (3-step form) ---------------- */

const EXAMPLES = [
  { label: "Buy and hold", text: "buy and hold", tickers: "SPY" },
  { label: "Buy the dip", text: "own these and average down on the dips", tickers: "SPY QQQ", dip: true },
  { label: "Rebalance to equal", text: "keep both weights equal, rebalancing every month", tickers: "TSLA NVDA" },
  { label: "Take the profit", text: "sell everything once it is up 30%", tickers: "SPY" },
  { label: "Let the AI decide", ai: true, tickers: "SPY TSLA",
    text: "I want a steady portfolio of SPY and TSLA. I check every month, and when one of them drops 15% I add 10% more. Once one is up 30% I sell all of it and let the cash sit." },
];
$("#examples").innerHTML = EXAMPLES.map((e, i) =>
  `<button type="button" class="chip" data-i="${i}">${esc(e.label)}</button>`).join("");
$$("#examples .chip").forEach((c) => c.addEventListener("click", () => {
  const e = EXAMPLES[+c.dataset.i];
  $("#strategy-text").value = e.text;
  $("#symbol").value = e.tickers;
  setLabMode(e.ai ? "ai" : "my_plan");
  if (e.dip)
    renderTriggerRows([{ kind: "drop_from_peak", pct: 15, lookback_days: 252, rearm: "recover" }]);
  syncQuote();
  labGo("setup");
}));
$("#strategy-text").addEventListener("input", syncQuote);
function syncQuote() {
  $("#strategy-quote").textContent = $("#strategy-text").value.trim() || "buy and hold";
}

/* the two modes: "my plan" = the form is the plan; "ai" = the model trades it */
let labMode = "my_plan";
function setLabMode(mode) {
  labMode = mode === "ai" ? "ai" : "my_plan";
  $$("#lab-modes .cmode").forEach((b) =>
    b.classList.toggle("active", b.dataset.lmode === labMode));
  $("#lab-text-label").textContent = labMode === "ai"
    ? "Your strategy, in your own words — the AI reads this"
    : "Your strategy, in your own words (optional — the form below is the plan)";
  refreshLabAiNote();
  $("#plan-fields").hidden = labMode !== "my_plan";
  $("#freq-field").hidden = labMode !== "my_plan";
  $("#symbol-label").firstChild.textContent = labMode === "ai"
    ? "Tickers (optional — pins the universe the AI can trade) "
    : "Tickers ";
  $("#run-lab").textContent = labMode === "ai" ? "Let the AI run it" : "Run the plan";
  syncQuote();
}
$$("#lab-modes .cmode").forEach((b) =>
  b.addEventListener("click", () => setLabMode(b.dataset.lmode)));
// The note under the AI chip: truth about the server's model, checked lazily.
function refreshLabAiNote() {
  let has = !!(window._llm || LLM.key);
  if (window._llm === undefined) {
    window._llm = false; // pessimistic until the check lands
    api("/api/health").then((h) => {
      window._llm = !!h.llm_configured;
      refreshLabAiNote();
    }).catch(() => {});
  }
  $("#lab-ai-note").hidden = !(labMode === "ai" && !has);
}

/* drop trigger rows: kind, %, lookback, re-arm — max three, removeable */
function addTriggerRow(t = {}, prefill = true) {
  const box = $("#trigger-rows");
  const row = document.createElement("div");
  row.className = "trigger-row";
  row.innerHTML =
    `<div class="field">
       <label>kind</label>
       <select class="trig-kind">
         <option value="drop_from_cost">drop from what I paid</option>
         <option value="drop_from_peak">drop from its recent high</option>
       </select>
     </div>
     <div class="field">
       <label>fall at least %</label>
       <input class="trig-pct" type="number" min="1" max="90" placeholder="15" inputmode="numeric">
     </div>
     <div class="field">
       <label>lookback, days</label>
       <input class="trig-lookback" type="number" min="5" max="504" placeholder="252" inputmode="numeric">
     </div>
     <div class="field">
       <label>re-arm</label>
       <select class="trig-rearm">
         <option value="recover">when it recovers above the trigger</option>
         <option value="periodic">on the next decision day</option>
       </select>
     </div>
     <button type="button" class="btn ghost trig-rm">Remove</button>`;
  row.querySelector(".trig-kind").value = t.kind || "drop_from_peak";
  if (prefill) {
    row.querySelector(".trig-pct").value = t.pct != null && t.pct !== "" ? t.pct : "";
    row.querySelector(".trig-lookback").value = t.lookback_days || 252;
    row.querySelector(".trig-rearm").value = t.rearm || "recover";
  }
  row.querySelector(".trig-rm").addEventListener("click", () => {
    row.remove();
    if (!$("#trigger-rows").children.length) addTriggerRow();
  });
  box.appendChild(row);
  return row;
}
function renderTriggerRows(list) {
  const box = $("#trigger-rows");
  box.innerHTML = "";
  (list && list.length ? list : [{}]).forEach((t) => addTriggerRow(t));
}
$("#add-trigger").addEventListener("click", () => {
  if ($("#trigger-rows").querySelectorAll(".trigger-row").length < 3)
    addTriggerRow();
});

/* read every lab field into the tab's state */
function readLabFields(t) {
  const s = t.state;
  s.text = $("#strategy-text").value;
  s.mode = labMode;
  s.tickers = $("#symbol").value.trim();
  s.years = parseInt($("#years").value, 10) || 10;
  s.cash = parseFloat($("#cash").value) || 100000;
  s.frequency = $("#frequency").value;
  s.triggers = $$("#trigger-rows .trigger-row").map((r) => {
    const pct = parseFloat(r.querySelector(".trig-pct").value);
    if (!pct || pct < 1 || pct > 90) return null; // a row without a % is no trigger
    const lb = parseFloat(r.querySelector(".trig-lookback").value) || 252;
    return { kind: r.querySelector(".trig-kind").value, pct,
             lookback_days: lb, rearm: r.querySelector(".trig-rearm").value };
  }).filter(Boolean);
  s.onDrop = $("#on-drop").value;
  s.addPct = parseFloat($("#add-weight").value) || 10;
  s.exitPct = parseFloat($("#exit-pct").value) || null;
  s.research = $("#research").checked;
  s.names = {};
  for (const line of $("#names").value.split("\n")) {
    const i = line.indexOf("=");
    if (i < 1) continue;
    const k = line.slice(0, i).trim().toUpperCase(), v = line.slice(i + 1).trim();
    if (k && v) s.names[k] = v;
  }
  s.start = $("#start-date").value || null;
  s.end = $("#end-date").value || null;
}

function labGo(step) {
  const t = activeWS("lab");
  if (!t) return;
  readLabFields(t);
  t.state.step = LAB_STEPS.includes(step) ? step : "strategy";
  go("lab/@" + t.id + "/" + t.state.step);
}

$("#lab-continue").addEventListener("click", () => labGo("setup"));
$("#lab-back-1").addEventListener("click", () => labGo("strategy"));
$("#lab-edit").addEventListener("click", () => labGo("strategy"));
$("#lab-again").addEventListener("click", runLab);
$("#run-lab").addEventListener("click", runLab);
$("#symbol").addEventListener("keydown", (e) => { if (e.key === "Enter" && t_on_setup()) runLab(); });
function t_on_setup() {
  const t = activeWS("lab");
  return t && (t.state.step || "strategy") === "setup";
}

function labStatus(text, err = false) {
  $$(".lab-status").forEach((el) => {
    // Keep the lab-status class: it's the selector we match on next time.
    el.className = "lab-status status" + (err ? " error" : "");
    el.textContent = text || "";
  });
}

let _chartData = null;
function showLabTab() {
  const t = activeWS("lab");
  if (!t) return;
  const step = LAB_STEPS.includes(t.state.step) ? t.state.step : "strategy";
  $$(".steppane").forEach((p) =>
    p.classList.toggle("active", p.id === "lab-" + step));
  const s = t.state;
  if (!s.tickers && s.symbol) s.tickers = s.symbol; // tabs saved by the old lab
  $("#strategy-text").value = s.text || "";
  if (s.mode) setLabMode(s.mode);
  $("#symbol").value = s.tickers || "SPY";
  $("#years").value = String(s.years || 10);
  $("#cash").value = s.cash || 100000;
  $("#frequency").value = s.frequency || "month";
  renderTriggerRows(s.triggers && s.triggers.length ? s.triggers : [{}]);
  $("#on-drop").value = s.onDrop || "hold";
  $("#add-weight").value = s.addPct ?? 10;
  $("#exit-pct").value = s.exitPct || "";
  $("#research").checked = !!s.research;
  $("#names").value = Object.entries(s.names || {}).map(([k, v]) => k + "=" + v).join("\n");
  $("#start-date").value = s.start || "";
  $("#end-date").value = s.end || "";
  $("#plan-what").textContent = labMode === "ai"
    ? "The AI reads your words once, then decides on every decision day."
    : "You decide " + (s.frequency === "week" ? "weekly" : s.frequency === "two_weeks" ? "every two weeks"
      : s.frequency === "quarter" ? "quarterly" : "monthly") +
      "; a drop trigger fires on any day.";
  syncQuote();
  const done = !!t.result;
  const empty = $("#lab-empty");
  empty.hidden = done;
  // Results live in memory only: after a refresh the inputs are saved but
  // the numbers are gone. Say so, and point at the run button.
  empty.innerHTML = done
    ? ""
    : `<p class="lab-empty-title">Nothing to see yet.</p>
       <p class="lab-empty-sub">Results live in memory — they don't survive a refresh. Run the plan in step 2 to see the numbers.</p>
       <div class="lab-empty-actions">
         <a class="btn primary" href="#lab/strategy">Start the strategy</a>
         <a class="btn ghost" href="#lab/setup">Open setup</a>
       </div>`;
  $("#lab-done").hidden = !done;
  if (done) {
    showPlanEcho(t.result);
    renderResult(t.result, t);
    labStatus("Done.");
  } else if (t.running) {
    showPlanEcho(t.result);
    $("#results").hidden = true;
    labStatus(labMode === "ai" ? "The AI is still running it — this takes minutes…" : "Still running…");
  } else {
    $("#understood").hidden = true;
    $("#results").hidden = true;
    labStatus("");
  }
  $("#run-lab").disabled = !!t.running;
  wsRender("lab");
}

const FREQ_WORD = { week: "weekly", two_weeks: "every two weeks", month: "monthly", quarter: "quarterly" };

function showPlanEcho(r) {
  const u = $("#understood");
  const p = r && r.plan;
  if (!p) { u.hidden = true; return; }
  u.hidden = false;
  const trigs = (p.triggers || []).map((t) =>
    (t.kind === "drop_from_cost" ? "a drop from its cost" : "a drop from its recent high") +
    ` of ${t.pct}% → ${p.on_drop === "add" ? "add " + Math.round(p.add_weight * 100) + "%"
      : p.on_drop === "hold" ? "hold" : "sell " + (p.on_drop === "sell_half" ? "half" : "all")}`)
    .join("; ") || "no drop triggers";
  const tail = [
    p.exit_pct ? `sell all at a ${p.exit_pct}% gain` : null,
    p.research ? "researches the web (date-gated)" : null,
  ].filter(Boolean).join("; ");
  u.innerHTML =
    `<strong>${r.mode === "ai" ? "The plan the AI read from your words" : "The plan, as the form set it"}</strong>` +
    (p.text ? `<p>${esc(p.text)}</p>` : "") +
    `<p class="meta">trading ${esc(p.symbols.join(", "))} · ${fmtMoney(p.start_cash)} · deciding ${FREQ_WORD[p.frequency] || p.frequency} · ${trigs}${tail ? " · " + tail : ""} · source: ${esc(r.plan_source || (r.mode === "ai" ? "model" : "form"))}</p>`;
}

let _labPoll = null;
function stopLabPoll() {
  if (_labPoll) { clearInterval(_labPoll); _labPoll = null; }
}

function planBody(s, mode) {
  return {
    mode,
    symbols: s.tickers.split(/[\s,;]+/).filter(Boolean),
    start_cash: s.cash,
    frequency: s.frequency,
    triggers: s.triggers || [],
    targets: {},                          // empty: the engine splits equally
    on_drop: s.onDrop || "hold",
    add_weight: Math.min(0.5, Math.max(0.01, (s.addPct ?? 10) / 100)),
    exit_pct: s.exitPct || null,
    research: !!s.research,
    text: s.text || "",
    names: s.names || {},
    start: s.start || null,
    end: s.end || null,
    years: s.years,
  };
}

async function runLab() {
  const tab = activeWS("lab");
  if (!tab || tab.running) return;
  readLabFields(tab);
  const s = tab.state;
  if (!s.tickers) { labStatus("Name at least one ticker first.", true); return; }
  if (s.mode === "ai" && !s.text.trim()) {
    labStatus("In the AI mode, describe the strategy in your own words first.", true);
    return;
  }
  tab.running = true;
  $("#run-lab").disabled = true;
  stopLabPoll();
  const prog = $("#lab-progress");
  try {
    if (s.mode === "ai") {
      prog.hidden = false;
      $("#lab-progress-msg").textContent = "Starting…";
      labStatus("The AI is running it — a long run takes minutes…");
      const job = await api("/api/backtest/strategy", { method: "POST", body: planBody(s, "ai") });
      await strategyPoll(job.id, tab);
    } else {
      labStatus(`Running ${s.years} years of real history… (new tickers take a few seconds)`);
      const r = await api("/api/backtest/strategy", { method: "POST", body: planBody(s, "my_plan") });
      if (!WS.lab.tabs.includes(tab)) return; // closed mid-run: nothing to show
      finishRun(tab, r);
    }
  } catch (e) {
    if (WS.lab.tabs.includes(tab) && WS.lab.active === tab.id)
      labStatus(e.message, true);
  } finally {
    tab.running = false;
    stopLabPoll();
    prog.hidden = true;
    if (WS.lab.active === tab.id) $("#run-lab").disabled = false;
  }
}

/* the "AI runs it" job: 4 s polls like the research run, then the result */
function strategyPoll(id, tab) {
  return new Promise((resolve) => {
    stopLabPoll();
    const tick = async () => {
      let job;
      try {
        job = await api("/api/backtest/strategy/" + encodeURIComponent(id));
      } catch {
        return; // a transient poll failure; the next tick retries
      }
      if (!WS.lab.tabs.includes(tab)) { stopLabPoll(); resolve(); return; }
      const lines = job.progress && job.progress.length ? job.progress : [];
      const msg = $("#lab-progress-msg");
      if (msg) msg.textContent = lines[lines.length - 1] ||
        (job.status === "running" ? "Working…" : job.message || job.status);
      if (job.status === "running") return;
      stopLabPoll();
      if (job.status === "done" && job.result) {
        finishRun(tab, job.result);
      } else {
        labStatus(job.message || "The backtest didn't finish.", true);
      }
      resolve();
    };
    tick(); // fire once now, then on the interval
    _labPoll = setInterval(tick, 4000);
  });
}

function finishRun(tab, r) {
  tab.result = r;
  tab.title = (r.plan && r.plan.symbols && r.plan.symbols[0]) || tab.title || "SPY";
  tab.state.step = "results";
  wsSave("lab");
  if (WS.lab.active === tab.id) {
    const target = "#lab/@" + tab.id + "/results";
    if (location.hash !== target) location.hash = target;
    else showLabTab();
  } else {
    wsRender("lab");
  }
}

function renderResult(r, tab) {
  $("#results").hidden = false;
  const m = r.metrics, b = r.benchmark_metrics;
  const p = r.plan || {};
  const cell = (k, a, bb, f = fmtSign) => {
    const av = f(a), bv = f(bb);
    return `<div class="metric"><div class="k">${k}</div>
      <div class="v ${a == null ? "flat" : a >= (bb ?? a) ? "up" : "down"}">${av}</div>
      <div class="b">buy &amp; hold: ${bv}</div></div>`;
  };
  // Sharpe is a ratio (mean daily return / its swing, annualized), not a percent.
  const ratio = (x) => x == null ? "—" : (x < 0 ? "−" : "") + Math.abs(x).toFixed(2);
  $("#metric-grid").innerHTML =
    cell("Total return", m.total_return, b.total_return) +
    cell("Per year", m.cagr, b.cagr) +
    (m.max_drawdown != null || b.max_drawdown != null
      ? cell("Worst dip", m.max_drawdown == null ? null : -m.max_drawdown,
             b.max_drawdown == null ? null : -b.max_drawdown) : "") +
    (m.sharpe != null || b.sharpe != null
      ? cell("Sharpe", m.sharpe, b.sharpe, ratio) : "") +
    `<div class="metric"><div class="k">Trades</div><div class="v">${r.trades}</div><div class="b">${r.decisions} decision days</div></div>` +
    `<div class="metric"><div class="k">Costs</div><div class="v">${fmtMoney(r.cost_paid ?? 0)}</div><div class="b">in market ${Math.round((r.time_in_market ?? 0) * 100)}%</div></div>`;
  $("#verdict").textContent = strategyVerdict(r);
  const bs = $("#bt-save");
  bs.hidden = false;
  bs.onclick = () => saveThis("backtest",
    ((p.symbols || []).join(" ") || "strategy") + " strategy backtest", [
      `Strategy: ${$("#strategy-text").value.trim() || "(as set in the form)"}`,
      `${(p.symbols || []).join(", ")} · ${$("#years").value} years · ${r.mode === "ai" ? "the AI ran it" : "my plan"}`,
      `Total: ${fmtSign(m.total_return)} (buy & hold: ${fmtSign(b.total_return)})`,
      `Per year: ${fmtSign(m.cagr)} (buy & hold: ${fmtSign(b.cagr)})`,
      m.max_drawdown != null ? `Worst dip: ${fmtSign(-m.max_drawdown)}` : "",
      `${r.trades} trades · ${r.decisions} decisions · costs ${fmtMoney(r.cost_paid ?? 0)}`,
      $("#verdict").textContent || "",
    ].filter(Boolean));
  reveal($("#understood"));
  reveal($("#metric-grid"));
  _chartData = { dates: r.dates, equity: r.equity, bench: r.benchmark, dollars: true };
  drawChart(_chartData);
  renderDecisionLog(r);
}

function strategyVerdict(r) {
  const m = r.metrics, b = r.benchmark_metrics;
  if (!m || m.total_return == null || !b || b.total_return == null) return "";
  const d = (m.total_return - b.total_return) * 100;
  const n = (r.dates && r.dates.length > 1)
    ? (new Date(r.dates[r.dates.length - 1]) - new Date(r.dates[0])) / (365.25 * 86400 * 1000)
    : null;
  const span = n == null ? ""
    : n < 1.05 ? `Over ${(n * 12).toFixed(0)} months` : `Over ${n.toFixed(1)} years`;
  const head = `${span ? span + ": " : ""}the strategy did ${fmtSign(m.total_return)} vs ${fmtSign(b.total_return)} for buy & hold of the same holdings`;
  const tail = Math.abs(d) < 0.05
    ? " — about even."
    : ` — ${d > 0 ? "ahead" : "behind"} by ${Math.abs(d).toFixed(1)} points.`;
  let v = head + tail;
  if (r.mode === "ai") v += ` The model made ${r.decisions} decisions across ${r.dates.length} days.`;
  return v;
}

function renderDecisionLog(r) {
  const box = $("#decision-log");
  const log = (r.log || []).slice();
  if (!log.length) { box.hidden = true; box.innerHTML = ""; return; }
  box.hidden = false;
  const shown = log.slice(-50).reverse(); // most recent first
  box.innerHTML = `<h3>What it decided</h3><div class="dl-list">` + shown.map((e) => {
    const trades = (e.trades || []).map((t) =>
      `${esc(t.symbol)} ${t.side === "buy" ? "bought" : "sold"} ${Math.round((t.weight ?? 1) * 100)}%`).join(", ");
    const research = e.research || {};
    const nRes = Object.keys(research).filter((k) => k !== "_skips").length;
    const skipped = "_skips" in research && Object.values(research._skips).length > 0;
    return `<div class="dl-row"><span class="dl-date">${esc(e.date)}</span>
      <span class="dl-note">${esc(e.note || "")}</span>` +
      (trades ? `<span class="dl-trades">${trades}</span>` : "") +
      (nRes ? `<span class="dl-res">${nRes} researched${skipped ? ", some skipped" : ""}</span>` : "") +
      `</div>`;
  }).join("") + `</div><p class="fineprint">${log.length > shown.length
    ? "showing the most recent " + shown.length + " of " + log.length + " decision days"
    : log.length + (log.length === 1 ? " decision day" : " decision days")}, most recent first</p>`;
}

function drawChart({ dates, equity, bench, dollars }) {
  const cv = $("#chart");
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return;
  const dpr = window.devicePixelRatio || 1;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);

  const all = [...equity, ...bench];
  const min = Math.min(...all), max = Math.max(...all);
  const span = (max - min) || 1;
  const padL = 56, padR = 10, padT = 14, padB = 26;
  const X = (i) => padL + (i / (dates.length - 1)) * (W - padL - padR);
  const Y = (v) => padT + (1 - (v - min) / span) * (H - padT - padB);
  const f = dollars ? fmtMoney : (v) => fmtSign(v - 1);

  ctx.strokeStyle = "#e4ddcc";
  ctx.fillStyle = "#8b8171";
  ctx.font = "11px sans-serif";
  for (let g = 0; g <= 4; g++) {
    const v = min + (span * g) / 4;
    const y = Y(v);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.fillText(f(v), 6, y + 4);
  }
  for (let g = 0; g <= 4; g++) {
    const i = Math.round((g / 4) * (dates.length - 1));
    ctx.fillText(dates[i] ? dates[i].slice(0, 4) : "", X(i) - 8, H - 8);
  }
  const line = (vals, color, dash) => {
    ctx.beginPath();
    vals.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(0), Y(v))));
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.setLineDash(dash || []); ctx.stroke();
    ctx.setLineDash([]);
  };
  line(bench, "#a79d89", [5, 4]);
  line(equity, "#16120b");

  ctx.font = "12px sans-serif";
  ctx.fillStyle = "#16120b"; ctx.fillText("— your strategy", padL + 8, padT + 4);
  ctx.fillStyle = "#a79d89"; ctx.fillText("-- buy & hold", padL + 130, padT + 4);
}
let _resizeT = null;
window.addEventListener("resize", () => {
  clearTimeout(_resizeT);
  _resizeT = setTimeout(() => {
    const t = activeWS("lab");
    if (_chartData && t && t.result && t.state.step === "results" &&
        $("#lab-results").classList.contains("active") && !$("#lab-done").hidden)
      drawChart(_chartData);
  }, 150);
});

/* ---------------- smart money ---------------- */

const MF = { mode: "include", sort: "value", dir: "desc", limit: 10,
             agg: false, fundNames: {}, scanning: false, total: 0 };

function showMoneyTab() {
  const t = activeWS("money");
  if (!t) return;
  const sub = MONEY_SUBS.includes(t.state.sub) ? t.state.sub : "funds";
  $$(".subpane").forEach((p) =>
    p.classList.toggle("active", p.id === "sub-" + sub));
  const mt = $("#money-title");
  if (mt) mt.textContent = MONEY_TITLE[sub] || "Smart money";
  wsRender("money");
  if (sub === "scan") {
    $("#sec-name").value = t.state.secName || "";
    window._sec = t.sec || null;
  }
  if (!window._moneyLoaded) loadMoney();
  else if (sub === "scan" && t.state.secName) loadSecurity(t);
  else if (sub === "scan") {
    $("#sec-result").hidden = true;
    $("#sec-result").innerHTML = "";
  }
}

async function loadMoney(statusText) {
  if (window._moneyLoading) return;
  window._moneyLoading = true;
  const status = $("#money-status");
  status.className = "status";
  status.textContent = statusText ||
    "Reading the latest 13F filings… (first load can take ~30s)";
  try {
    const ov = await api("/api/money/overview");
    window._money = ov;
    window._moneyLoaded = true;
    MF.total = ov.n_total;
    $("#f-crowd").max = Math.max(2, MF.total);
    status.textContent = `as of ${ov.as_of || "?"} · ${ov.n_ok}/${ov.n_total} funds · `
      + ov.row_count.toLocaleString() + " holdings";
    $("#q-asof").textContent = ov.as_of ? `${ov.as_of} (quarter-end)` : "";
    renderCards(ov);
    paintSideFresh(ov);
    renderRollups(ov);
    buildChips();
    buildAskChips();
    loadScan();
    dirStatus();
  } catch (e) {
    status.className = "status error";
    status.textContent = e.message;
  } finally {
    window._moneyLoading = false;
  }
  if (window._moneyLoaded &&
      document.getElementById("tab-money").classList.contains("active"))
    showMoneyTab();
}

/* one quiet line per fund card: when it filed, what changed this quarter */
function fundFreshMeta(f) {
  const parts = [];
  if (f.filed) {
    const d = new Date(f.filed);
    parts.push("filed " + d.toLocaleDateString("en-US",
      { month: "short", day: "numeric", year: "numeric" }));
  }
  if (f.n_new) parts.push(`<b class="up">${f.n_new} new</b>`);
  if (f.n_exited) parts.push(`<b class="down">${f.n_exited} exited</b>`);
  if (parts.length === 0 && f.as_of) parts.push("held steady");
  return parts.join(" · ");
}

/* fund rows */
/* the one-line freshness story in the Smart-money sidebar: how many
   funds are stale, and how stale. Plain words, no chart. */
function paintSideFresh(ov) {
  const box = $("#side-fresh");
  if (!box) return;
  const funds = (ov && ov.funds) || [];
  const stale = funds.filter((f) => f && f.stale);
  if (!funds.length) { box.hidden = true; box.textContent = ""; return; }
  const meta = [];
  if (ov && ov.as_of) meta.push(`filings as of <b>${esc(ov.as_of)}</b>`);
  if (stale.length) meta.push(`<b>${stale.length}</b> stale`);
  box.hidden = false;
  box.innerHTML = meta.join(" · ");
}

function renderCards(ov) {
  MF.fundNames = {};
  ov.funds.forEach((f) => (MF.fundNames[f.key] = f.name));
  $("#fund-grid").innerHTML = ov.funds.map((f) => f.error
    ? `<div class="fund err-card"><span class="fund-name"><strong>${esc(f.name)}</strong></span>
        <span class="fund-meta err" title="${esc(f.error)}">couldn't read</span></div>`
    : `<div class="fund" data-key="${esc(f.key)}">
        <div class="fund-top">
          <span class="fund-name"><strong>${esc(f.name)}</strong>
            ${f.manager ? `<small>${esc(f.manager)}</small>` : ""}
            ${f.stale ? `<span class="badge-stale" title="No new 13F for a while — old data">old data</span>` : ""}
          </span>
          <button class="fund-remove" data-key="${esc(f.key)}" title="Remove" aria-label="Remove">×</button>
        </div>
        <div class="fund-bottom">
          <span class="fund-meta" title="as of ${esc(String(f.as_of || "").slice(5))}, quarter-end">${fmtBig(f.total_value)} · ${f.n_positions} holdings</span>
          <span class="fund-fresh">${fundFreshMeta(f)}</span>
        </div>
      </div>`).join("");
  $("#f-crowd").max = Math.max(1, MF.total || 11);
  $$("#fund-grid .fund[data-key]").forEach((el) =>
    el.addEventListener("click", () => {
      const key = el.dataset.key;
      const i = MF.funds.indexOf(key);
      MF.funds = i >= 0 ? MF.funds.filter((k) => k !== key) : [...MF.funds, key];
      syncChips();
      loadScan();
      if (!(location.hash || "").includes("money/scan")) location.hash = "money/scan";
      requestAnimationFrame(() => $("#scan-table").scrollIntoView({ behavior: "smooth", block: "start" }));
    }));
  $$("#fund-grid .fund-remove").forEach((b) =>
    b.addEventListener("click", (e) => { e.stopPropagation(); removeFund(b.dataset.key); }));
  MF.funds = [];
  reveal($("#fund-grid"));
}

/* quarter rollups */
function renderRollups(ov) {
  const item = (r) => `<div class="r-item"><span>${esc(tidy(r.issuer))}</span>
      <small>${esc(MF.fundNames[r.fund] || r.fund)}</small>
      <b class="${r.move_value == null ? "flat" : cls(r.move_value)}">${r.status === "new" ? "" : (r.move_value >= 0 ? "+" : "") + fmtBig(r.move_value == null ? 0 : r.move_value)}</b></div>`;
  $("#rollup-new").innerHTML = (ov.new_this_quarter || []).slice(0, 5).map((r) =>
      `<div class="r-item"><span>${esc(tidy(r.issuer))}</span><small>${esc(MF.fundNames[r.fund] || r.fund)}</small>
       <b class="up">${fmtBig(r.value)}</b></div>`).join("")
    || `<p class="empty">Nothing new this quarter.</p>`;
  $("#rollup-moves").innerHTML = (ov.biggest_moves || []).slice(0, 5).map(item).join("")
    || `<p class="empty">No big moves.</p>`;
  $("#rollup-crowd").innerHTML = (ov.crowding_change || []).slice(0, 5).map((c) =>
      `<div class="r-item"><span>${esc(tidy(c.name))}</span>
       <small>${c.funds_then.length} → ${c.funds_now.length} funds</small>
       <b class="${c.delta > 0 ? "up" : "down"}">${c.delta > 0 ? "+" : ""}${c.delta}</b></div>`).join("")
    || `<p class="empty">No shift this quarter.</p>`;
  const exits = (ov.exits_this_quarter || [])
    .filter((r) => (r.prev_value || 0) > 0)
    .slice(0, 5);
  $("#rollup-exits").innerHTML = exits.map((r) =>
      `<div class="r-item"><span>${esc(tidy(r.issuer))}</span><small>${esc(MF.fundNames[r.fund] || r.fund)}</small>
       <b class="down">was ${fmtBig(r.prev_value)}</b></div>`).join("")
    || `<p class="empty">No exits this quarter.</p>`;
  reveal($("#rollup-new"));
  reveal($("#rollup-moves"));
  reveal($("#rollup-crowd"));
  reveal($("#rollup-exits"));
}

/* the scan lede: what a row means (a holding, or a company) */
const SCAN_LEDE = {
  rows: "Every holding in your funds' latest filings.",
  agg: "Every company in your funds' latest filings, counted once.",
};
function setScanLede() {
  $("#sub-scan .lede").textContent = SCAN_LEDE[MF.agg ? "agg" : "rows"];
}

/* scan filters */
function buildChips() {
  MF.funds = MF.funds || [];
  const ov = window._money;
  const keys = (ov ? ov.funds : []).map((f) => f.key);
  const box = $("#fund-chips");
  box.innerHTML = `<span class="chipmode">
      <button class="cmode active" data-mode="include">only</button>
      <button class="cmode" data-mode="exclude">except</button>
    </span>` + keys.map((k) =>
    `<button class="chip fundchip" data-key="${esc(k)}">${esc(MF.fundNames[k] || k)}</button>`).join("");
  box.querySelectorAll(".fundchip").forEach((c) =>
    c.addEventListener("click", () => {
      const key = c.dataset.key;
      const i = MF.funds.indexOf(key);
      MF.funds = i >= 0 ? MF.funds.filter((x) => x !== key) : [...MF.funds, key];
      syncChips();
      loadScan();
    }));
  box.querySelectorAll(".cmode").forEach((b) =>
    b.addEventListener("click", () => {
      MF.mode = b.dataset.mode;
      syncChips();
      loadScan();
    }));
  syncChips();
}

function syncChips() {
  $$("#fund-chips .fundchip").forEach((c) =>
    c.classList.toggle("active", MF.funds.includes(c.dataset.key)));
  $$("#fund-chips .cmode").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === MF.mode));
}

function scanParams() {
  const p = new URLSearchParams();
  const v = (id) => $(id).value.trim();
  const set = (k, val) => { if (val !== "") p.set(k, val); };
  set("q", v("#f-q"));
  set("asset", v("#f-asset"));
  set("status", v("#f-status"));
  set("min_crowding", v("#f-crowd"));
  set("min_value", v("#f-value"));
  set("min_weight", v("#f-weight"));
  set("min_move_value", v("#f-mov"));
  set("min_move_pct", v("#f-movp"));
  if (MF.funds.length) p.set(MF.mode === "exclude" ? "exclude" : "funds", MF.funds.join(","));
  if (MF.agg) p.set("aggregate", "1");
  if ($("#f-surprise").checked) p.set("surprise", "1");
  set("sort", MF.sort);
  set("dir", MF.dir);
  p.set("limit", MF.limit);
  return p;
}

let scanTimer = null;
function scheduleScan() {
  clearTimeout(scanTimer);
  scanTimer = setTimeout(loadScan, 300);
}

async function loadScan() {
  if (MF.scanning) return;
  MF.scanning = true;
  const count = $("#scan-count");
  count.textContent = "…";
  try {
    const d = await api("/api/money/scan?" + scanParams().toString());
    renderScanTable(d);
    count.textContent = d.total === 0 ? "Nothing matches — loosen a filter."
      : MF.agg
        ? `${d.total.toLocaleString()} companies · ${d.shown} shown`
        : `${d.total.toLocaleString()} holdings · ${d.shown} shown`;
  } catch (e) {
    count.textContent = e.message;
  } finally {
    MF.scanning = false;
  }
}

function renderScanTable(d) {
  const tb = $("#scan-table tbody");
  $("#scan-table").classList.toggle("agg", !!MF.agg);
  const statusChip = (s) => `<span class="st ${stCls(s)}">${STATUS_WORD[s] || s}</span>`;
  tb.innerHTML = d.rows.map((r, i) => MF.agg ? `
    <tr class="agg-row ${r.surprise ? "surprise" : ""}" data-i="${i}">
      <td class="co" title="${esc(r.issuer)}"><span class="co-name">${esc(tidy(r.issuer))}</span></td>
      <td>${statusChip(r.status)}</td>
      <td class="num">${r.value > 0 ? fmtBig(r.value) : (r.prev_value ? `<span class="was" title="sold last quarter">was ${fmtBig(r.prev_value)}</span>` : "—")}</td>
      <td class="num ${cls(r.change)}">${r.status === "new" ? "new" : (r.change != null ? fmtSign(r.change, 0) : "—")}</td>
      <td class="num" title="${esc((r.holders || []).map((h) => MF.fundNames[h] || h).join(", "))}">${r.n_funds}</td>
      <td class="act"><button class="snip-save" data-i="${i}" title="Save to your notes">Save</button></td>
    </tr>` : `
    <tr class="${r.surprise ? "surprise" : ""}"${r.surprise ? ` title="A new bet no other tracked fund shares"` : ""}>
      <td class="co" title="${esc(r.issuer)}"><span class="co-name">${esc(tidy(r.issuer))}</span></td>
      <td class="fund-name-cell" title="${esc(MF.fundNames[r.fund] || r.fund)}">${esc(MF.fundNames[r.fund] || r.fund)}</td>
      <td>${statusChip(r.status)}</td>
      <td class="num">${r.status === "exited" && r.prev_value ? `<span class="was" title="they sold this last quarter">was ${fmtBig(r.prev_value)}</span>` : fmtBig(r.value)}</td>
      <td class="num ${cls(r.change)}">${r.status === "new" ? "new" : fmtSign(r.change, 0)}</td>
      <td class="num" title="${esc((r.holders || []).map((h) => MF.fundNames[h] || h).join(", "))}">${r.n_funds}</td>
      <td class="act"><button class="snip-save" data-i="${i}" title="Save to your notes">Save</button></td>
    </tr>`).join("")
    || `<tr><td colspan="${MF.agg ? 6 : 7}" class="empty">Nothing matches those filters.</td></tr>`;
  $$("#scan-table .snip-save").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const r = d.rows[+b.dataset.i];
      const who = MF.fundNames[r.fund] || r.fund;
      if (MF.agg) {
        saveThis("money", tidy(r.issuer), [
          `Held by ${r.n_funds} tracked fund${r.n_funds === 1 ? "" : "s"}`,
          `Total: ${r.value > 0 ? fmtBig(r.value) : (r.prev_value ? "was " + fmtBig(r.prev_value) : "$0")}`,
          r.change != null ? `Change: ${fmtSign(r.change, 0)}` : "New this quarter",
          ...(r.breakdown || []).slice(0, 4).map((x) =>
            `${MF.fundNames[x.fund] || x.fund}: ${x.value > 0 ? fmtBig(x.value) : (x.prev_value ? "was " + fmtBig(x.prev_value) : "")}`),
        ].filter(Boolean));
        return;
      }
      saveThis("money", tidy(r.issuer), [
        `${who}: ${STATUS_WORD[r.status] || r.status}`,
        `Now: ${fmtBig(r.value)}${r.prev_value ? ` (was ${fmtBig(r.prev_value)})` : ""}`,
        r.change != null ? `Change: ${fmtSign(r.change, 0)}` : "",
        `Held by ${r.n_funds} tracked fund${r.n_funds === 1 ? "" : "s"}`,
      ].filter(Boolean));
    }));
  if (MF.agg) {
    $$("#scan-table tr.agg-row").forEach((tr) =>
      tr.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        toggleBreakdown(tr, d);
      }));
  }
  reveal(tb);
}

/* click-into a company: its per-fund breakdown, expanded under the row */
function toggleBreakdown(tr, d) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("scan-break")) {
    next.remove();
    tr.classList.remove("open");
    return;
  }
  const r = d.rows[+tr.dataset.i];
  if (!r || !r.breakdown) return;
  const lines = r.breakdown.map((b) => `
    <div class="bk-row">
      <span class="bk-fund">${esc(MF.fundNames[b.fund] || b.fund)}</span>
      <span class="st ${stCls(b.status)}">${STATUS_WORD[b.status] || b.status}</span>
      <span class="bk-num">${b.value > 0 ? fmtBig(b.value) : (b.prev_value ? `was ${fmtBig(b.prev_value)}` : "")}</span>
      <span class="bk-num ${cls(b.change)}">${b.status === "new" ? "new" : (b.change != null ? fmtSign(b.change, 0) : "")}</span>
    </div>`).join("");
  tr.insertAdjacentHTML("afterend",
    `<tr class="scan-break"><td colspan="${MF.agg ? 6 : 7}" class="bk-box">${lines}</td></tr>`);
  tr.classList.add("open");
}

function wireScan() {
  ["#f-q", "#f-asset", "#f-status", "#f-crowd", "#f-value",
   "#f-weight", "#f-mov", "#f-movp"].forEach((s) =>
    $(s).addEventListener("input", scheduleScan));
  $("#f-surprise").addEventListener("change", scheduleScan);
  $("#f-agg").addEventListener("change", () => { MF.agg = $("#f-agg").checked; setScanLede(); loadScan(); });
  $("#f-limit").addEventListener("change", () => { MF.limit = +$("#f-limit").value; loadScan(); });
  $$("#scan-table th[data-sort]").forEach((th) =>
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      if (MF.sort === col) MF.dir = MF.dir === "desc" ? "asc" : "desc";
      else { MF.sort = col; MF.dir = col === "issuer" ? "asc" : "desc"; }
      paintSortHeads();
      loadScan();
    }));
  paintSortHeads();
  $("#reset-btn").addEventListener("click", () => {
    ["#f-q", "#f-asset", "#f-status", "#f-crowd", "#f-value",
     "#f-weight", "#f-mov", "#f-movp"].forEach((s) => $(s).value = "");
    $("#f-surprise").checked = false;
    $("#f-agg").checked = false;
    $("#f-limit").value = "10";
    MF.limit = 10; MF.sort = "value"; MF.dir = "desc"; MF.funds = []; MF.agg = false;
    setScanLede(); syncChips(); paintSortHeads(); loadScan();
  });
  $("#export-btn").addEventListener("click", () =>
    window.location.href = "/api/money/export?" + scanParams().toString());
}

function paintSortHeads() {
  $$("#scan-table th[data-sort]").forEach((th) => {
    const active = th.dataset.sort === MF.sort;
    th.classList.toggle("sorted", active);
    th.querySelector(".arrow")?.remove();
    if (active) th.insertAdjacentHTML("beforeend",
      ` <span class="arrow">${MF.dir === "desc" ? "↓" : "↑"}</span>`);
  });
}

/* ---------------- the filer directory + roster ---------------- */

async function dirStatus() {
  const el = $("#dir-status");
  try {
    const s = await api("/api/money/directory/status");
    el.className = "status";
    el.textContent = s.ready
      ? s.n_filers.toLocaleString() + " filers"
      : "building the filer directory (first time)…";
    if (!s.ready) setTimeout(dirStatus, 5000);
  } catch (e) {
    el.className = "status error";
    el.textContent = "directory: " + e.message;
  }
}

async function dirSearch() {
  const q = $("#dir-q").value.trim();
  const box = $("#dir-results");
  if (q.length < 2) { box.hidden = true; box.innerHTML = ""; return; }
  box.hidden = false;
  box.innerHTML = `<div class="dir-hit"><span class="status">searching…</span></div>`;
  try {
    const data = await api("/api/money/directory?q=" + encodeURIComponent(q));
    if (!data.results.length) {
      box.innerHTML = `<div class="dir-hit"><span class="status">No filers match “${esc(q)}” — try fewer letters.</span></div>`;
      return;
    }
    box.innerHTML = data.results.map((r) => `
      <div class="dir-hit">
        <div><span class="dir-name">${esc(r.name)}</span>
          <small>${esc(r.form)} · ${esc(r.date)}</small></div>
        ${r.in_roster
          ? `<span class="status">on your list</span>`
          : `<button class="dir-add" data-cik="${esc(r.cik)}" data-name="${esc(r.name)}">Add</button>`}
      </div>`).join("");
    $$(".dir-add", box).forEach((b) =>
      b.addEventListener("click", () => addFund(b.dataset.name, b.dataset.cik, b)));
    reveal(box);
  } catch (e) {
    box.innerHTML = `<div class="dir-hit"><span class="status error">${esc(e.message)}</span></div>`;
  }
}

function moneyStatusFrom(view) {
  $("#money-status").textContent = `as of ${view.as_of || "?"} · ${view.n_ok}/${view.n_total} funds · `
    + view.row_count.toLocaleString() + " holdings";
}

function applyView(view) {
  window._money = view;
  MF.total = view.n_total;
  $("#f-crowd").max = Math.max(2, MF.total);
  renderCards(view);
  renderRollups(view);
  buildChips();
  buildAskChips();
  moneyStatusFrom(view);
  loadScan();
}

async function addFund(name, cik, btn) {
  if (btn) btn.disabled = true;
  try {
    const data = await api("/api/money/roster", { method: "POST", body: { name, cik: String(cik) } });
    applyView(data.view);
    dirSearch();   // refresh the result list (it's on the roster now)
  } catch (e) {
    if (btn) btn.disabled = false;
    $("#dir-results").innerHTML =
      `<div class="dir-hit"><span class="status error">${esc(e.message)}</span></div>`;
  }
}

async function removeFund(key) {
  const name = (window._money?.funds || []).find((f) => f.key === key)?.name || key;
  if (!confirm(`Remove ${name}?`)) return;
  try {
    const data = await api("/api/money/roster/" + encodeURIComponent(key), { method: "DELETE" });
    MF.funds = MF.funds.filter((k) => k !== key);
    applyView(data.view);
    syncChips();
    dirSearch();
  } catch (e) {
    alert("Couldn't remove it: " + e.message);
  }
}

/* one-security view */
async function loadSecurity(tab) {
  const t = tab || activeWS("money");
  const name = (($("#sec-name").value || (t && t.state.secName) || "")).trim();
  const box = $("#sec-result");
  if (!name) {
    box.hidden = true;
    box.innerHTML = "";
    if (t) { t.state.secName = ""; t.sec = null; wsRender("money"); }
    window._sec = null;
    return;
  }
  if (t) {
    t.state.secName = name;
    t.sec = null;
    wsRender("money");
  }
  box.hidden = false;
  box.innerHTML = `<p class="status">Looking…</p>`;
  try {
    const s = await api("/api/money/security?name=" + encodeURIComponent(name));
    if (t && (!WS.money.tabs.includes(t) || WS.money.active !== t.id)) return;
    const combined = s.total_value;
    const prev = s.prev_total_value;
    const pct = prev ? combined / prev - 1 : null;
    const secLines = [
      `${tidy(s.name)}${s.class ? " · " + tidy(s.class) : ""}`,
      `${fmtBig(combined)} across ${s.n_funds} of ${MF.total || "?"} tracked funds`,
      pct != null ? `vs last quarter: ${fmtSign(pct, 0)}` : "",
      ...(s.rows || []).slice(0, 5).map((r) =>
        `${MF.fundNames[r.fund] || r.fund}: ${fmtBig(r.value)} · ${r.status === "new" ? "new" : fmtSign(r.change, 0)}`),
    ].filter(Boolean);
    const sec = { title: tidy(s.name), lines: secLines };
    if (t) t.sec = sec;
    window._sec = sec;
    box.innerHTML = `
      <div class="sec-head">
        <strong>${esc(tidy(s.name))}</strong>
        <span class="dim">${esc(s.class || s.asset)}${s.cusip ? " · " + esc(s.cusip) : ""}</span>
        <b>${fmtBig(combined)}${pct != null ? ` <small class="${cls(pct)}">${fmtSign(pct, 0)} vs last qtr</small>` : ""}
          <small class="dim">${s.n_funds} of ${MF.total || "?"} funds</small></b>
        <span class="sec-acts">
          <button class="btn ghost sec-co" data-name="${esc(tidy(s.name))}">Company page</button>
          <button class="btn ghost sec-save" type="button">Save</button>
        </span>
      </div>
      <table class="sec-table">
        <thead><tr><th>Fund</th><th>Status</th><th class="num">Worth</th><th class="num">% Fund</th><th class="num">Change</th></tr></thead>
        <tbody>${s.rows.map((r) => `<tr>
          <td>${esc(MF.fundNames[r.fund] || r.fund)}</td>
          <td><span class="st ${stCls(r.status)}">${STATUS_WORD[r.status] || r.status}</span></td>
          <td class="num">${fmtBig(r.value)}</td>
          <td class="num">${(r.weight * 100).toFixed(1)}%</td>
          <td class="num ${cls(r.change)}">${r.status === "new" ? "new" : fmtSign(r.change, 0)}</td>
        </tr>`).join("")}</tbody>
      </table>
      ${s.alternatives?.length ? `<p class="empty">Did you mean: ${s.alternatives.map((a) => esc(tidy(a.name))).join(", ")}?</p>` : ""}`;
    reveal(box);
  } catch (e) {
    box.innerHTML = `<p class="status error">${esc(e.message)}</p>`;
  }
}
function secGo() {
  const t = activeWS("money");
  if (t) {
    t.state.secName = $("#sec-name").value.trim();
    t.sec = null;
  }
  loadSecurity(t);
}
$("#sec-go").addEventListener("click", secGo);
$("#sec-name").addEventListener("keydown", (e) => { if (e.key === "Enter") secGo(); });
$("#sec-result").addEventListener("click", (e) => {   // delegation: the box re-renders
  const co = e.target.closest(".sec-co");
  if (co) { coFromName(co.dataset.name, co); return; }
  const sv = e.target.closest(".sec-save");
  if (sv && window._sec) saveThis("money", window._sec.title, window._sec.lines);
});

/* ---------------- ask (a language model over the filings) ---------------- */

const ASK = { mode: "include", funds: [], busy: false };

const ASK_STARTERS = [
  "What are they buying right now?",
  "What did they sell the most of?",
  "Which companies do the most of them hold?",
  "Who made the biggest new bet?",
  "What is the biggest single holding?",
];

function buildAskChips() {
  ASK.funds = ASK.funds || [];
  const ov = window._money;
  const keys = (ov ? ov.funds : []).map((f) => f.key);
  const box = $("#ask-funds");
  box.innerHTML = `<span class="chipmode">
      <button class="cmode" data-mode="include">only</button>
      <button class="cmode" data-mode="exclude">except</button>
    </span>` + keys.map((k) =>
    `<button class="chip fundchip" data-key="${esc(k)}">${esc(MF.fundNames[k] || k)}</button>`).join("");
  box.querySelectorAll(".fundchip").forEach((c) =>
    c.addEventListener("click", () => {
      const key = c.dataset.key;
      const i = ASK.funds.indexOf(key);
      ASK.funds = i >= 0 ? ASK.funds.filter((x) => x !== key) : [...ASK.funds, key];
      syncAskChips();
    }));
  box.querySelectorAll(".cmode").forEach((b) =>
    b.addEventListener("click", () => {
      ASK.mode = b.dataset.mode;
      syncAskChips();
    }));
  syncAskChips();
}

function syncAskChips() {
  $$("#ask-funds .fundchip").forEach((c) =>
    c.classList.toggle("active", ASK.funds.includes(c.dataset.key)));
  $$("#ask-funds .cmode").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === ASK.mode));
}

function askStatus(text, err = false) {
  const el = $("#ask-status");
  el.className = "status" + (err ? " error" : "");
  el.textContent = text || "";
}

async function askNow() {
  const q = $("#ask-q").value.trim();
  if (!q || ASK.busy) return;
  ASK.busy = true;
  const btn = $("#ask-go");
  btn.disabled = true;
  $("#ask-out").innerHTML = "";
  if (window._llm === undefined) {   // boot's health check still in flight
    try {
      const h = await api("/api/health");
      window._llm = !!h.llm_configured;
    } catch {
      window._llm = false;
    }
  }
  if (!window._llm && !LLM.key) {
    askStatus("Ask is off: no model key is set — add one in Settings, " +
      "or deploy the app with its own.", true);
    ASK.busy = false;
    btn.disabled = false;
    return;
  }
  askStatus("Thinking — this can take a minute…");
  const t0 = Date.now();
  try {
    const picked = ASK.funds.join(",");
    const body = {
      q,
      quarters: +$("#ask-qtr").value,
      funds: ASK.mode === "include" ? picked : "",
      exclude: ASK.mode === "exclude" ? picked : "",
    };
    const r = await api("/api/money/ask", { method: "POST", body });
    $("#ask-out").innerHTML = `
      <div class="ask-answer">
        <p class="ask-echo">You asked: “${esc(q)}”</p>
        <p class="ans-text">${esc(r.answer)}</p>
        <div class="ask-foot">
          <small class="dim">${r.n_funds} fund${r.n_funds === 1 ? "" : "s"} ·
          ${r.window && r.window.start === r.window.end
            ? "as of " + esc(String(r.window.start || "?"))
            : esc(String(r.window.start || "?")) + " → " + esc(String(r.window.end || "?"))} ·
          ${Math.round((Date.now() - t0) / 1000)}s</small>
          <button class="btn ghost ask-save" type="button">Save</button>
        </div>
      </div>`;
    reveal($("#ask-out"));
    $("#ask-out .ask-save").addEventListener("click", () =>
      saveThis("ask", q, r.answer.split(/\n+/).filter(Boolean).slice(0, 30)));
    askStatus(r.missing && r.missing.length
      ? `Note: ${r.missing.join(", ")} couldn't be read, so it isn't in the answer.`
      : "");
  } catch (e) {
    $("#ask-out").innerHTML = "";
    askStatus(e.message, true);
  } finally {
    ASK.busy = false;
    btn.disabled = false;
  }
}

$("#ask-go").addEventListener("click", askNow);
$("#ask-q").addEventListener("keydown", (e) => { if (e.key === "Enter") askNow(); });
$("#ask-starters").innerHTML = ASK_STARTERS.map((s, i) =>
  `<button type="button" class="chip" data-i="${i}">${esc(s)}</button>`).join("");
$$("#ask-starters .chip").forEach((c) => c.addEventListener("click", () => {
  $("#ask-q").value = ASK_STARTERS[+c.dataset.i];
  askNow();
}));

/* ---------------- home: your portfolio + smart money highlights ---------------- */

/* The gain windows the portfolio reports. [key, chip label, spoken phrase].
   "cost" is the plain P/L against what you paid — the default. */
const PF_PERIODS = [
  ["cost", "Cost", "since cost"], ["1w", "1W", "over 1 week"],
  ["1m", "1M", "over 1 month"], ["3m", "3M", "over 3 months"],
  ["6m", "6M", "over 6 months"], ["1y", "1Y", "over 1 year"]];
const PF_PERIOD_KEY = PF_PERIODS.map((p) => p[0]);
const PF_PERIOD_WORD = Object.fromEntries(PF_PERIODS.map((p) => [p[0], p[1]]));
const PF_PERIOD_PHRASE = Object.fromEntries(PF_PERIODS.map((p) => [p[0], p[2]]));
const PF_SORT_COLS = ["name", "price", "value", "pl", "date", "smart"];

const PMF = { loading: false, glancing: false, editing: null,
              picked: null, cands: [], seq: 0, data: null,
              mode: "stock",
              cur: (() => { try { return localStorage.getItem("proof-cur") || ""; } catch { return ""; } })(),
              period: (() => { try { const v = localStorage.getItem("proof-pf-period");
                return PF_PERIOD_KEY.includes(v) ? v : "cost"; } catch { return "cost"; } })(),
              sort: null, dir: "desc" };
(() => {   // the remembered column sort, stored as "column:direction"
  try {
    const [c, d] = (localStorage.getItem("proof-pf-sort") || "").split(":");
    if (PF_SORT_COLS.includes(c)) {
      PMF.sort = c;
      PMF.dir = d === "asc" ? "asc" : "desc";
    }
  } catch { /* private mode */ }
})();

const CUR = { USD: "$", EUR: "€", GBP: "£", JPY: "¥", CAD: "C$", AUD: "A$",
              HKD: "HK$", CHF: "CHF ", SGD: "S$", CNY: "CN¥" };
const sym = (cur) => CUR[cur] || (cur ? cur + " " : "$");
const fmtPrice = (x, cur) => x == null ? "—" : sym(cur) + x.toFixed(2);
const fmtMoneyCur = (x, cur) => x == null ? "—" : sym(cur) + Math.round(x).toLocaleString("en-US");
const fmtPl = (x, cur) => x == null ? "—"
  : (x >= 0 ? "+" : "−") + sym(cur) + Math.round(Math.abs(x)).toLocaleString("en-US");
const fmtShares = (x) => x == null ? "—"
  : x.toLocaleString("en-US", { maximumFractionDigits: 2 });
const fmtBigCur = (x, cur) => {
  if (x == null) return "—";
  const a = Math.abs(x), s = x < 0 ? "−" : "";
  const [v, u] = a >= 1e12 ? [a / 1e12, "T"]
    : a >= 1e9 ? [a / 1e9, "B"]
    : a >= 1e6 ? [a / 1e6, "M"]
    : a >= 1e3 ? [a / 1e3, "K"] : [a, ""];
  return s + sym(cur) + (u ? v.toFixed(1) + u : v.toFixed(0));
};

function homeSub() {
  const h = (location.hash || "").replace(/^#/, "").split("/");
  return h[0] === "home" ? (HOME_SUBS.includes(h[1]) ? h[1] : "portfolio") : "portfolio";
}

function refreshHome() {
  if (homeSub() === "money") loadGlance();
  else loadPortfolio();
}

/* --- my portfolio --- */

async function loadPortfolio(refresh = false) {
  if (PMF.loading) return;
  PMF.loading = true;
  const st = $("#pf-status");
  st.className = "status";
  st.textContent = "Reading your portfolio…";
  try {
    const qs = new URLSearchParams();
    if (refresh) qs.set("refresh", "1");
    if (PMF.cur) qs.set("currency", PMF.cur);
    const suffix = qs.toString() ? "?" + qs.toString() : "";
    const d = await api("/api/portfolio" + suffix);
    PMF.data = d;
    renderPortfolio(d);
    const n = d.positions.length;
    st.textContent = n
      ? `${n} holding${n === 1 ? "" : "s"} · ${d.totals.priced}/${n} priced`
        + (d.as_of_13f ? ` · fund filings as of ${d.as_of_13f}` : "")
      : "";
  } catch (e) {
    st.className = "status error";
    st.textContent = e.message;
  } finally {
    PMF.loading = false;
  }
}

function renderPortfolio(d) {
  const has = d.positions.length > 0;
  $("#pf-empty").hidden = has;
  $("#pf-table-card").hidden = !has;
  $("#pf-total").hidden = !has;
  if (!has) { $("#pf-total").innerHTML = ""; return; }
  paintPfTotal(d.totals);
  paintPfPeriods();
  renderPfSpark(d);
  renderPfRows();
  $("#pf-cur-note").textContent = d.totals.n
    ? `${d.totals.priced}/${d.totals.n} priced`
      + (d.totals.missing ? ` · ${d.totals.missing} missing` : "")
    : "";
}

/* A quiet 1-year total-value line under the strip. Honest by
   construction: the server only sends it when every priced holding has
   a year of history, so the line is never a partial slice. */
function renderPfSpark(d) {
  const box = $("#pf-spark");
  if (!box) return;
  const pts = d.spark || [];
  if (!pts.length || pts.length < 2) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  const lo = Math.min(...pts.map((p) => p[1]));
  const hi = Math.max(...pts.map((p) => p[1]));
  const span = hi - lo || 1;
  const W = 680, H = 52, padX = 4, padY = 6;
  const x = (i) => padX + (i / (pts.length - 1)) * (W - 2 * padX);
  const y = (v) => padY + (1 - (v - lo) / span) * (H - 2 * padY);
  const line = pts.map((p, i) => `${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  const tcur = d.totals.currency || (d.totals.currencies.length === 1 ? d.totals.currencies[0] : "");
  const first = pts[0][0], last = pts[pts.length - 1][0];
  const dFmt = (s) => new Date(s + "T00:00:00").toLocaleDateString("en-US",
    { month: "short", year: "2-digit" });
  const up = hi >= lo;
  const color = up ? "var(--up)" : "var(--down)";
  box.hidden = false;
  box.innerHTML = `
    <div class="pf-spark-head">
      <span class="dim">1-year total value</span>
      <span class="dim">${dFmt(first)} → ${dFmt(last)}</span>
    </div>
    <svg class="pf-spark-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <polyline points="${line}" fill="none" stroke="${color}" stroke-width="1.75" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>
    <div class="pf-spark-foot">
      <span>${fmtBigCur(lo, tcur)}</span><span>${fmtBigCur(hi, tcur)}</span>
    </div>`;
}

/* the top strip: what it's all worth, plus the gain for the chosen window */
function paintPfTotal(T) {
  const tcur = T.currency || (T.currencies.length === 1 ? T.currencies[0] : "");
  const mixed = !PMF.cur && T.value == null && T.currencies.length > 1;
  const why = T.value == null
    ? (T.priced ? "Currencies don't add up" : "Nothing could be priced")
    : (T.missing ? `${T.missing} holding${T.missing === 1 ? "" : "s"} without a price` : "");
  const iv = PMF.period === "cost"
    ? { pl: T.pl, pl_pct: T.pl_pct }
    : (T.intervals || {})[PMF.period] || null;
  const pl = iv && iv.pl != null
    ? ` <span class="${cls(iv.pl)}">${fmtPl(iv.pl, tcur)}${iv.pl_pct != null ? " (" + fmtSign(iv.pl_pct) + ")" : ""}</span> ${PF_PERIOD_PHRASE[PMF.period]}`
    : "";
  $("#pf-total").innerHTML =
    `<span title="${esc(why)}">Total <strong>${fmtBigCur(T.value, tcur)}</strong></span>`
    + pl
    + (mixed
        ? ` <span class="dim">your holdings span ${esc(T.currencies.join(" · "))} — pick a currency above to convert</span>`
        : (why ? ` <span class="dim">${T.priced}/${T.n} priced</span>` : ""));
}

/* the window picker: Cost / 1W / 1M / 3M / 6M / 1Y. Client-side only —
   the server always sends every window, so switching never refetches. */
function paintPfPeriods() {
  const box = $("#pf-periods");
  box.innerHTML = PF_PERIODS.map(([k, l]) =>
    `<button type="button" class="chip pf-period${PMF.period === k ? " active" : ""}" data-period="${k}">${l}</button>`).join("");
  box.querySelectorAll(".pf-period").forEach((b) =>
    b.addEventListener("click", () => {
      if (PMF.period === b.dataset.period) return;
      PMF.period = b.dataset.period;
      try { localStorage.setItem("proof-pf-period", PMF.period); } catch { /* private mode */ }
      renderPortfolio(PMF.data);
    }));
  $("#pf-pl-period").textContent = PF_PERIOD_WORD[PMF.period];
}

function pfRowHtml(p, cur) {
  const val = (k) => cur ? p["display_" + k] : p[k];
  const rcur = cur || p.currency;
  const custom = p.kind === "custom";
  const ident = custom
    ? `<span>${esc(p.ticker)}</span>`
    : `<a class="co-link" href="#company/${encodeURIComponent(p.ticker)}" title="Company page">${esc(p.ticker)}</a>`;
  const price = fmtPrice(val("price"), rcur);
  const week = p.week == null ? "" : ` <small class="${cls(p.week)}">${fmtSign(p.week)}</small>`;
  const smart = custom
    ? `<span class="dim">Custom</span>`
    : p.smart
      ? `<span class="sm-chip ${stCls(p.smart.status)}" title="${esc(p.smart.holders.join(", "))}">${p.smart.n_funds} fund${p.smart.n_funds === 1 ? "" : "s"}</span>`
      : `<span class="dim">—</span>`;
  const iv = PMF.period === "cost"
    ? { pl: val("pl"), pct: val("pl_pct") }
    : (cur ? p.display_intervals : p.intervals)?.[PMF.period] || { pl: null, pct: null };
  // stale: Yahoo was blocked, so the price is the last known one — date it.
  const tip = !p.live ? "price unavailable — Yahoo is busy"
    : p.fx_missing ? "no exchange rate"
    : p.price_stale ? `last seen ${p.price_as_of || "?"}` : "live";
  return `
    <tr data-t="${esc(p.ticker)}">
      <td class="co" title="${esc(p.name)}"><span class="co-name">${esc(tidy(p.name))}</span>
        <small class="dim">${ident} · ${fmtShares(p.shares)} sh</small></td>
      <td class="num" title="${tip}">${price}${week}</td>
      <td class="num">${fmtMoneyCur(val("value"), rcur)}</td>
      <td class="num ${cls(iv.pl)}" title="${iv.pct != null ? fmtSign(iv.pct) + " " + PF_PERIOD_PHRASE[PMF.period] : ""}">${fmtPl(iv.pl, rcur)}${iv.pct != null ? ` <small class="${cls(iv.pct)}">${fmtSign(iv.pct)}</small>` : ""}</td>
      <td class="num">${p.purchase_date ? esc(p.purchase_date) : "—"}</td>
      <td>${smart}</td>
      <td class="act"><button class="pf-remove" data-t="${esc(p.ticker)}" title="Remove" aria-label="Remove">×</button></td>
    </tr>`;
}

/* one click on a column header sorts the current rows, no refetch.
   nulls (unpriced rows, missing dates) stay at the bottom either way. */
function pfSortVal(p, cur) {
  const val = (k) => cur ? p["display_" + k] : p[k];
  switch (PMF.sort) {
    case "name": return (p.name || "").toLowerCase();
    case "price": return val("price");
    case "value": return val("value");
    case "pl": return PMF.period === "cost" ? val("pl")
      : (cur ? p.display_intervals : p.intervals)?.[PMF.period]?.pl ?? null;
    case "date": return p.purchase_date || null;
    case "smart": return p.smart ? p.smart.n_funds : null;
    default: return null;
  }
}

function pfSorted(positions) {
  if (!PMF.sort) return positions;
  const cur = PMF.cur;
  const v = (p) => pfSortVal(p, cur);
  const s = [...positions].sort((a, b) => {
    const va = v(a), vb = v(b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    return typeof va === "string" ? va.localeCompare(vb) : va - vb;
  });
  if (PMF.dir === "desc") s.reverse();
  s.sort((a, b) => (v(a) == null ? 1 : 0) - (v(b) == null ? 1 : 0));
  return s;
}

function paintPfSortHeads() {
  $$("#pf-table th[data-sort]").forEach((th) => {
    const active = th.dataset.sort === PMF.sort;
    th.classList.toggle("sorted", active);
    th.querySelector(".arrow")?.remove();
    if (active) th.insertAdjacentHTML("beforeend",
      ` <span class="arrow">${PMF.dir === "desc" ? "↓" : "↑"}</span>`);
  });
}

function renderPfRows() {
  const d = PMF.data;
  if (!d || !d.positions.length) return;
  const tb = $("#pf-table tbody");
  tb.innerHTML = pfSorted(d.positions).map((p) => pfRowHtml(p, PMF.cur)).join("");
  $$("#pf-table .pf-remove").forEach((b) =>
    b.addEventListener("click", (e) => { e.stopPropagation(); pfRemove(b.dataset.t); }));
  $$("#pf-table tr[data-t]").forEach((tr) =>
    tr.addEventListener("click", () => pfEditRow(tr)));
  paintPfSortHeads();
  reveal(tb);
}

/* add-position box: listed search or a custom (unlisted) holding */
const PF_CURRENCIES = ["USD", "GBP", "EUR", "HKD", "CAD", "JPY", "AUD", "CHF"];

function pfSetMode(mode) {
  PMF.mode = mode;
  $$(".pf-mode-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode));
  $("#pf-stock-fields").hidden = mode !== "stock";
  $("#pf-custom-fields").hidden = mode !== "custom";
  $("#pf-cost-label").textContent = mode === "custom" ? "Purchase price" : "Cost per share";
  $("#pf-suggests").hidden = true;
  $("#pf-form-status").textContent = "";
}
$$(".pf-mode-btn").forEach((b) =>
  b.addEventListener("click", () => pfSetMode(b.dataset.mode)));

$("#pf-cur").value = PF_CURRENCIES.includes(PMF.cur) ? PMF.cur : "";
$("#pf-cur").addEventListener("change", () => {
  PMF.cur = $("#pf-cur").value;
  try { localStorage.setItem("proof-cur", PMF.cur); } catch { /* private mode */ }
  loadPortfolio();
});

/* sortable column headers — scoped to the <th>s, so row clicks (which
   open the in-place edit) and the remove buttons keep working */
$$("#pf-table th[data-sort]").forEach((th) =>
  th.addEventListener("click", () => {
    const col = th.dataset.sort;
    if (PMF.sort === col) PMF.dir = PMF.dir === "desc" ? "asc" : "desc";
    else {
      PMF.sort = col;
      PMF.dir = (col === "name" || col === "date") ? "asc" : "desc";
    }
    try { localStorage.setItem("proof-pf-sort", `${PMF.sort}:${PMF.dir}`); } catch { /* private mode */ }
    paintPfSortHeads();
    renderPfRows();
  }));

let _pfT = null;
$("#pf-q").addEventListener("input", () => {
  PMF.picked = null;
  clearTimeout(_pfT);
  _pfT = setTimeout(pfSearch, 300);
});
$("#pf-q").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { clearTimeout(_pfT); pfSearch(); }
  if (e.key === "Escape") $("#pf-suggests").hidden = true;
});

async function pfSearch() {
  const q = $("#pf-q").value.trim();
  const box = $("#pf-suggests");
  if (q.length < 2) { box.hidden = true; box.innerHTML = ""; return; }
  const seq = ++PMF.seq;
  box.hidden = false;
  box.innerHTML = `<div class="dir-hit"><span class="status">Searching Yahoo…</span></div>`;
  let d;
  try {
    d = await api("/api/search?q=" + encodeURIComponent(q));
  } catch (e) {
    if (seq === PMF.seq)
      box.innerHTML = `<div class="dir-hit"><span class="status error">${esc(e.message)}</span></div>`;
    return;
  }
  if (seq !== PMF.seq) return;   // a newer keystroke beat this one
  if (!d.results) {
    box.innerHTML = `<div class="dir-hit"><span class="status">Yahoo is busy — you can still type a ticker and press Add.</span></div>`;
    return;
  }
  if (!d.results.length) {
    box.innerHTML = `<div class="dir-hit"><span class="status">No match for “${esc(q)}” — fewer letters, or type the ticker and press Add.</span></div>`;
    return;
  }
  PMF.cands = d.results;
  box.innerHTML = d.results.map((r, i) => `
    <div class="dir-hit pf-hit" data-i="${i}">
      <div><span class="dir-name">${esc(r.name)}</span>
        <small>${esc(r.symbol)}${r.type ? " · " + esc(r.type) : ""}${r.exchange ? " · " + esc(r.exchange) : ""}</small></div>
      <button class="dir-add">Pick</button>
    </div>`).join("");
  $$("#pf-suggests .pf-hit").forEach((h) =>
    h.addEventListener("click", () => pfPick(+h.dataset.i)));
  reveal(box);
}

function pfPick(i) {
  const c = PMF.cands[i];
  if (!c) return;
  PMF.picked = c;
  $("#pf-q").value = c.name;
  $("#pf-suggests").hidden = true;
  $("#pf-suggests").innerHTML = "";
  $("#pf-shares").focus();
}

async function pfAdd() {
  const fs = $("#pf-form-status");
  const custom = PMF.mode === "custom";
  const body = {
    shares: $("#pf-shares").value,
    cost_basis: $("#pf-cost").value,
    purchase_date: $("#pf-date").value,
    note: $("#pf-note").value,
  };
  if (custom) {
    body.kind = "custom";
    body.name = $("#pf-custom-name").value.trim();
    body.price = $("#pf-price").value;
    body.currency = $("#pf-currency").value;
    if (!body.name) {
      fs.className = "status error";
      fs.textContent = "Give the investment a name first.";
      return;
    }
  } else {
    body.ticker = PMF.picked ? PMF.picked.symbol : $("#pf-q").value.trim();
    body.name = PMF.picked ? PMF.picked.name : "";
    if (!body.ticker) {
      fs.className = "status error";
      fs.textContent = "Type a company or ticker first.";
      return;
    }
  }
  fs.className = "status";
  fs.textContent = "Adding…";
  try {
    await api("/api/portfolio", { method: "POST", body });
    PMF.picked = null;
    PMF.editing = null;
    ["#pf-q", "#pf-shares", "#pf-cost", "#pf-date", "#pf-note",
     "#pf-custom-name", "#pf-price"].forEach((s) => ($(s).value = ""));
    fs.textContent = "";
    loadPortfolio(true);
  } catch (e) {
    fs.className = "status error";
    fs.textContent = e.message;
  }
}
$("#pf-add").addEventListener("click", pfAdd);
$("#pf-cost").addEventListener("keydown", (e) => { if (e.key === "Enter") pfAdd(); });
$("#pf-note").addEventListener("keydown", (e) => { if (e.key === "Enter") pfAdd(); });

/* edit in place, or remove */
function pfEditRow(tr) {
  if (PMF.editing) return;
  const t = tr.dataset.t;
  const p = (PMF.data?.positions || []).find((x) => x.ticker === t);
  if (!p) return;
  const custom = p.kind === "custom";
  const currencies = PF_CURRENCIES.map((c) =>
    `<option${c === p.currency ? " selected" : ""}>${c}</option>`).join("");
  PMF.editing = t;
  tr.classList.add("editing");
  tr.innerHTML = `
    <td colspan="7" class="pf-edit">
      <div class="pf-edit-grid">
        <input data-k="name" value="${esc(p.name)}" maxlength="80" placeholder="name">
        <input data-k="ticker" value="${esc(p.ticker)}" disabled>
        ${custom ? `<input data-k="price" type="number" min="0" step="any" value="${esc(String(p.price ?? ""))}" placeholder="current price">` : ""}
        ${custom ? `<select data-k="currency">${currencies}</select>` : ""}
        <input data-k="shares" type="number" min="0" step="any" value="${esc(String(p.shares))}" title="shares">
        <input data-k="cost_basis" type="number" min="0" step="any" value="${esc(String(p.cost_basis))}" title="${custom ? "purchase price" : "cost per share"}">
        <input data-k="purchase_date" type="date" value="${esc(p.purchase_date || "")}" title="purchase date">
        <input data-k="note" value="${esc(p.note || "")}" maxlength="120" placeholder="note">
        <button class="btn primary pf-save" data-t="${esc(t)}">Save</button>
        <button class="btn ghost pf-cancel" data-t="${esc(t)}">Cancel</button>
        <button class="pf-remove" data-t="${esc(t)}" title="Remove" aria-label="Remove">×</button>
      </div>
    </td>`;
  const val = (k) => {
    const el = tr.querySelector(`[data-k="${k}"]`);
    return el ? el.value : "";
  };
  tr.querySelector(".pf-save").addEventListener("click", async (e) => {
    e.stopPropagation();
    const body = {
      ticker: val("ticker"), name: val("name"), shares: val("shares"),
      cost_basis: val("cost_basis"), purchase_date: val("purchase_date"),
      note: val("note"), kind: p.kind || "stock",
    };
    if (custom) {
      body.price = val("price");
      body.currency = val("currency");
    }
    try {
      await api("/api/portfolio/" + encodeURIComponent(t), { method: "PATCH", body });
      PMF.editing = null;
      loadPortfolio();
    } catch (err) {
      alert("Couldn't save: " + err.message);
    }
  });
  tr.querySelector(".pf-cancel").addEventListener("click", (e) => {
    e.stopPropagation();
    PMF.editing = null;
    loadPortfolio();
  });
  tr.querySelector(".pf-remove").addEventListener("click", (e) => {
    e.stopPropagation();
    pfRemove(t);
  });
}

async function pfRemove(t) {
  if (!confirm(`Remove ${t}?`)) return;
  try {
    await api("/api/portfolio/" + encodeURIComponent(t), { method: "DELETE" });
    PMF.editing = null;
    loadPortfolio();
  } catch (e) {
    alert("Couldn't remove it: " + e.message);
  }
}

/* --- smart money highlights (glance) --- */

async function loadGlance() {
  if (PMF.glancing) return;
  PMF.glancing = true;
  const st = $("#gm-status");
  st.className = "status";
  st.textContent = "Reading the latest 13F filings… (first load can take ~30s)";
  try {
    const g = await api("/api/money/glance");
    renderGlance(g);
    st.textContent = g.as_of ? `as of ${g.as_of} (quarter-end) · ${g.n_funds} funds` : "";
  } catch (e) {
    st.className = "status error";
    st.textContent = e.message;
  } finally {
    PMF.glancing = false;
  }
}

function renderGlance(g) {
  const chip = (s) => s
    ? `<span class="st ${stCls(s)}">${STATUS_WORD[s] || s}</span>`
    : `<span class="dim">—</span>`;
  const saveCell = (i) =>
    `<td class="act"><button class="snip-save" data-i="${i}" title="Save to your notes">Save</button></td>`;
  const glanceLines = (r) => [
    MF.fundNames[r.fund] || r.fund,
    r.status ? (r.status === "new" ? "A new position" : (STATUS_WORD[r.status] || r.status) + " this quarter") : "",
    `Worth: ${fmtBig(r.value)}`,
    r.move_value ? `Moved ${r.move_value >= 0 ? "+" : "−"}${fmtBig(Math.abs(r.move_value))} since last quarter` : "",
    r.change != null ? `Change: ${fmtSign(r.change, 0)}` : "",
  ].filter(Boolean);
  const ctb = $("#gm-crowded tbody");
  ctb.innerHTML = (g.crowded || []).map((c, i) => `
    <tr>
      <td class="co">${esc(tidy(c.name))}</td>
      <td class="num" title="${esc(c.holders.join(", "))}">${c.n_funds}</td>
      <td class="num">${fmtBig(c.value)}</td>
      <td>${chip(c.status)}</td>
      ${saveCell(i)}
    </tr>`).join("")
    || `<tr><td colspan="5" class="empty">No crowded holdings.</td></tr>`;
  const mtb = $("#gm-moves tbody");
  mtb.innerHTML = (g.moves || []).map((r, i) => `
    <tr class="${r.surprise ? "surprise" : ""}">
      <td class="co">${esc(tidy(r.name))}</td>
      <td>${esc(r.fund)}</td>
      <td class="num ${cls(r.change)}">${r.status === "new" ? "new" : fmtSign(r.change, 0)}</td>
      <td class="num">${fmtBig(r.value)}</td>
      ${saveCell(i)}
    </tr>`).join("")
    || `<tr><td colspan="5" class="empty">No big moves.</td></tr>`;
  const ntb = $("#gm-new tbody");
  ntb.innerHTML = (g.new || []).map((r, i) => `
    <tr>
      <td class="co">${esc(tidy(r.name))}</td>
      <td>${esc(r.fund)}</td>
      <td class="num">${fmtBig(r.value)}</td>
      ${saveCell(i)}
    </tr>`).join("")
    || `<tr><td colspan="4" class="empty">Nothing new this quarter.</td></tr>`;
  $$("#gm-crowded .snip-save, #gm-moves .snip-save, #gm-new .snip-save").forEach((b) =>
    b.addEventListener("click", () => {
      const table = b.closest("table");
      const rows = table.id === "gm-crowded" ? g.crowded
        : table.id === "gm-moves" ? g.moves : g.new;
      const r = rows[+b.dataset.i];
      if (r) saveThis("money", tidy(r.name), glanceLines(r));
    }));
  reveal(ctb); reveal(mtb); reveal(ntb);
}

$$(".htab").forEach((b) => b.addEventListener("click", () => go("home/" + b.dataset.sub)));

/* ---------------- notes: your pages, plus anything you saved ---------------- */

const NOTES = { flush: null };

function showNotesTab() {
  const t = activeWS("notes");
  if (!t) return;
  if (t.state.pageId) loadNotePage(t.state.pageId, t);
  else loadNotes(t);
}

async function loadNotes(tab) {
  if (tab) {
    tab.title = "Notes";
    wsRender("notes");
  }
  const box = $("#notes-body");
  box.innerHTML = `<div class="status">Opening your notebook…</div>`;
  let pages = [];
  try {
    pages = (await api("/api/notes")).pages || [];
  } catch (e) {
    box.innerHTML = `<div class="status error">${esc(e.message)}</div>`;
    return;
  }
  box.innerHTML = `
    <div class="pane-head">
      <h1>Notes</h1>
      <button class="btn primary" id="notes-new" type="button">New page</button>
    </div>
    ${pages.length
      ? `<div class="notes-grid">${pages.map((p, i) => `
        <button class="note-card" data-id="${esc(p.id)}" style="--d:${Math.min(i, 10) * 40}ms">
          <span class="note-title">${esc(p.title)}</span>
          <span class="note-preview">${esc(p.preview || "An empty page")}</span>
          <span class="note-meta">${fmtDate(p.updated)}${p.n_snippets ? ` · ${p.n_snippets} saved` : ""}</span>
        </button>`).join("")}</div>`
      : `<div class="note-empty">
          <p>Nothing here yet.</p>
          <p class="dim">Write a page, or press Save on anything in the app — a backtest, an answer, a holding — and it lands here.</p>
        </div>`}`;
  const g = $("#notes-body .notes-grid");
  if (g) reveal(g);
  $("#notes-new").addEventListener("click", () =>
    api("/api/notes", { method: "POST", body: { title: "" } })
      .then((p) => wsOpen("notes", { pageId: p.id }, "Note"))
      .catch((e) => toast("Couldn't make a page: " + e.message)));
  $$("#notes-body .note-card").forEach((c) =>
    c.addEventListener("click", () => go("notes/" + c.dataset.id)));
}

function renderSnippets(p) {
  const snips = p.snippets || [];
  if (!snips.length)
    return `<p class="dim">Nothing saved here yet — press Save on anything in the app.</p>`;
  return `<div class="snip-list">${snips.map((s, i) => `
    <div class="snip" style="--d:${Math.min(i, 10) * 40}ms">
      <div class="snip-head">
        ${srcChip(s.source)}
        ${s.title ? `<span class="snip-title">${esc(s.title)}</span>` : ""}
        <button class="snip-x" data-sid="${esc(s.id)}" title="Remove this piece" aria-label="Remove">×</button>
      </div>
      <pre class="snip-lines">${esc(s.lines.join("\n"))}</pre>
      <small class="dim">${fmtDate(s.saved_at)}</small>
    </div>`).join("")}</div>`;
}

function wireSnipButtons(p) {
  $$("#note-snip-list .snip-x").forEach((b) =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        const upd = await api(
          `/api/notes/${encodeURIComponent(p.id)}/snippets/${encodeURIComponent(b.dataset.sid)}`,
          { method: "DELETE" });
        Object.assign(p, upd);
        $("#note-snip-list").innerHTML = renderSnippets(p);
        wireSnipButtons(p);
      } catch (err) {
        alert("Couldn't remove that piece: " + err.message);
      }
    }));
}

async function loadNotePage(pid, tab) {
  const box = $("#notes-body");
  box.innerHTML = `<div class="status">Opening the page…</div>`;
  let p;
  try {
    p = await api("/api/notes/" + encodeURIComponent(pid));
  } catch (e) {
    if (e.message === "No note with that id") {
      // The page was deleted, probably in another window. Say so plainly
      // and offer to close the tab rather than showing a raw error.
      box.innerHTML = `
        <div class="pane-head">
          <a class="linklike" href="#notes">← All notes</a>
          <button class="btn ghost" id="note-gone" type="button">Close this page</button>
        </div>
        <p class="status">This page no longer exists. It may have been deleted from another window.</p>`;
      $("#note-gone").addEventListener("click", () =>
        tab ? wsClose("notes", tab.id) : go("notes"));
      return;
    }
    box.innerHTML = `<div class="status error">${esc(e.message)}</div>`;
    return;
  }
  if (tab && !WS.notes.tabs.includes(tab)) return;
  p.id = pid;   // the hash is the source of truth for which page this is
  if (tab) {
    tab.title = p.title || "Note";
    wsRender("notes");
  }
  box.innerHTML = `
    <div class="pane-head">
      <a class="linklike" href="#notes">← All notes</a>
      <button class="btn ghost" id="note-delete" type="button">Delete page</button>
    </div>
    <input id="note-title" class="note-title-in" value="${esc(p.title)}" placeholder="Name this page" maxlength="120">
    <textarea id="note-body" class="note-body-in" rows="8" placeholder="Write it down…"></textarea>
    <p id="note-save-status" class="status"></p>
    <h2 class="snip-h">Saved pieces</h2>
    <div id="note-snip-list">${renderSnippets(p)}</div>`;
  $("#note-body").value = p.body || "";

  const ti = $("#note-title"), bi = $("#note-body");
  const stt = $("#note-save-status");
  let _saveT = null;
  const persist = async () => {
    const t = ti.value, b = bi.value;
    if (t === (p.title || "") && b === (p.body || "")) return;  // nothing new
    stt.className = "status";
    stt.textContent = "Saving…";
    try {
      const upd = await api("/api/notes/" + encodeURIComponent(pid),
        { method: "PATCH", body: { title: t, body: b } });
      Object.assign(p, upd);
      stt.textContent = "Saved";
    } catch (e) {
      stt.className = "status error";
      stt.textContent = e.message;
    }
  };
  // Autosave as they write (a short pause, then save), and save again the
  // moment a field loses focus. Works even in a background window.
  const queue = () => {
    if (ti.value === (p.title || "") && bi.value === (p.body || "")) {
      stt.textContent = "";
      return;
    }
    stt.textContent = "Saving…";
    clearTimeout(_saveT);
    _saveT = setTimeout(persist, 700);
  };
  ti.addEventListener("input", queue);
  ti.addEventListener("input", () => {
    if (!tab) return;
    tab.title = ti.value.trim() || "Note";
    wsRender("notes");
  });
  bi.addEventListener("input", queue);
  ti.addEventListener("blur", persist);
  bi.addEventListener("blur", persist);
  bi.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); clearTimeout(_saveT); persist(); }
  });
  $("#note-delete").addEventListener("click", async () => {
    if (!confirm("Delete this page?")) return;
    try {
      await api("/api/notes/" + encodeURIComponent(pid), { method: "DELETE" });
      if (tab) wsClose("notes", tab.id);
      else go("notes");
    } catch (e) {
      alert("Couldn't delete it: " + e.message);
    }
  });
  NOTES.flush = () => { clearTimeout(_saveT); persist(); };
  wireSnipButtons(p);
  if (!p.title) ti.focus();
  reveal($("#notes-body"));
}

/* ---------------- company: one company, every part of it ---------------- */

const CO = { data: null };
let _coResizeT = null;
const CO_TRY = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN"];

function showCompanyTab() {
  const t = activeWS("company");
  if (!t) return;
  if (t.state.symbol) loadCompany(t.state.symbol, t);
  else renderCoSearch(t);
}

function coOpen(symbol, tab) {
  const sym = String(symbol || "").trim().toUpperCase();
  if (!sym) return;
  if (tab && !tab.state.symbol) {
    tab.state.symbol = sym;
    wsActivate("company", tab.id, { hash: true });
  } else {
    go("company/" + encodeURIComponent(sym));
  }
}

function renderCoSearch(tab) {
  CO.data = null;
  if (tab) { tab.title = ""; wsRender("company"); }
  const box = $("#co-body");
  box.innerHTML = `
    <div class="pane-head"><h1>Company</h1></div>
    <p class="co-intro">Search by name or ticker to see the price, the numbers, and the story.</p>
    <div class="co-search">
      <input id="co-q" placeholder="Company name or ticker" autocomplete="off" spellcheck="false">
      <div id="co-suggests" class="suggests" hidden></div>
    </div>
    <div class="co-try"><span class="dim">or try</span>
      ${CO_TRY.map((t) => `<button class="chip" data-t="${t}">${t}</button>`).join("")}
    </div>`;
  const q = $("#co-q"), sug = $("#co-suggests");
  let t = null, seq = 0;
  const doSearch = async () => {
    const v = q.value.trim();
    if (v.length < 2) { sug.hidden = true; sug.innerHTML = ""; return; }
    const my = ++seq;
    sug.hidden = false;
    sug.innerHTML = `<div class="dir-hit"><span class="status">Searching Yahoo…</span></div>`;
    let d;
    try {
      d = await api("/api/search?q=" + encodeURIComponent(v));
    } catch (e) {
      if (my === seq)
        sug.innerHTML = `<div class="dir-hit"><span class="status error">${esc(e.message)}</span></div>`;
      return;
    }
    if (my !== seq) return;
    if (!d.results) {
      sug.innerHTML = `<div class="dir-hit"><span class="status">Yahoo is busy — type a ticker and press Enter.</span></div>`;
      return;
    }
    if (!d.results.length) {
      sug.innerHTML = `<div class="dir-hit"><span class="status">No match — fewer letters, or the ticker and Enter.</span></div>`;
      return;
    }
    sug.innerHTML = d.results.map((r, i) => `
      <div class="dir-hit" data-i="${i}">
        <div><span class="dir-name">${esc(r.name)}</span>
          <small>${esc(r.symbol)}${r.exchange ? " · " + esc(r.exchange) : ""}</small></div>
      </div>`).join("");
    sug.querySelectorAll(".dir-hit").forEach((h) =>
      h.addEventListener("click", () =>
        coOpen(d.results[+h.dataset.i].symbol, tab)));
    reveal(sug);
  };
  q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(doSearch, 300); });
  q.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && q.value.trim())
      coOpen(q.value.trim(), tab);
    if (e.key === "Escape") sug.hidden = true;
  });
  $$("#co-body .co-try .chip").forEach((c) =>
    c.addEventListener("click", () => coOpen(c.dataset.t, tab)));
  q.focus();
}

async function loadCompany(symbol, tab) {
  const box = $("#co-body");
  box.innerHTML = `
    <div class="pane-head"><h1>${esc(symbol)}</h1>
      <span class="status">Reading the numbers…</span>
    </div>`;
  let c;
  try {
    c = await api("/api/company/" + encodeURIComponent(symbol));
  } catch (e) {
    c = null;   // company() never fails; this is a just-in-case guard
  }
  if (tab && !WS.company.tabs.includes(tab)) return;
  if (!c) c = { symbol };
  c.symbol = c.symbol || symbol;
  if (tab) {
    tab.data = c;
    tab.state.symbol = c.symbol;
    tab.title = c.symbol;
    wsRender("company");
    if (WS.company.active !== tab.id) return;
  }
  CO.data = c;
  renderCompany(c, c.symbol, tab);
}

function rangeBar(lo, hi, val, label, px) {
  if (lo == null || hi == null || lo === hi)
    return `<div class="co-rbar"><span class="k">${label}</span>
      <div class="range-vals"><span>—</span><span>—</span></div></div>`;
  const pos = val != null && hi > lo
    ? Math.max(0, Math.min(1, (val - lo) / (hi - lo))) : null;
  return `<div class="co-rbar">
    <span class="k">${label}</span>
    <div class="range-track"><div class="range-fill"
      style="width:${pos != null ? (pos * 100).toFixed(1) : 50}%"></div>
      ${pos != null ? `<i class="range-dot" style="left:${(pos * 100).toFixed(1)}%"></i>` : ""}</div>
    <div class="range-vals"><span>${px(lo)}</span><span>${px(hi)}</span></div>
  </div>`;
}

function renderCompany(c, sym, tab) {
  const box = $("#co-body");
  const dash = "—";
  // no data at all — no quote, no chart, no name: the symbol doesn't exist
  const nothing =
    !c.name && c.price == null && !c.change && !c.market_cap && !c.pe &&
    !(c.history || []).length && !c.sector && !c.about;
  if (nothing) {
    box.innerHTML = `
      <div class="pane-head"><h1>${esc(sym)}</h1></div>
      <div class="card co-empty">
        <p class="co-empty-title">No company matches &ldquo;${esc(sym)}&rdquo;.</p>
        <p class="co-empty-sub">Check the spelling or ticker — e.g. &#39;AAPL&#39; — or search for the company by name above.</p>
        <a class="btn primary" href="#company">Back to search</a>
      </div>`;
    reveal(box);
    return;
  }
  const cur = c.currency;
  const px = (x) => x == null ? dash : (cur && cur !== "USD" ? cur + " " : "$") + x.toFixed(2);
  const name = c.name || sym;
  const avail = c.price != null || (c.history || []).length > 0;
  const stat = (k, v) =>
    `<div class="co-stat"><span class="k">${k}</span><span class="v">${v}</span></div>`;
  const ret = (k, v) => v == null ? "" :
    `<span class="ret ${cls(v)}"><small>${k}</small>${fmtSign(v)}</span>`;
  const kstat = (k, v) =>
    `<div class="co-kstat"><span class="k">${k}</span><span class="v">${v}</span></div>`;
  const chg = c.change == null ? "" :
    `${(c.change >= 0 ? "+" : "−") + Math.abs(c.change).toFixed(2)}`
    + `${c.change_pct != null ? " · " + fmtSign(c.change_pct) : ""}`;
  const asof = c.market_time
    ? new Date(c.market_time * 1000).toLocaleString("en-US",
        { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
    : "";

  box.innerHTML = `
    <div class="pane-head co-head">
      <div class="co-id">
        <h1>${esc(name)}</h1>
        <div class="co-tags">
          <span class="co-sym">${esc(sym)}</span>
          ${c.sector ? `<span class="dim">${esc(c.sector)}${c.industry ? " · " + esc(c.industry) : ""}</span>` : ""}
          ${c.hometown ? `<span class="dim">${esc(c.hometown)}</span>` : ""}
        </div>
      </div>
      <div class="pane-actions">
        <button class="btn ghost" id="co-save" type="button">Save to notes</button>
        <button class="btn primary" id="co-add" type="button">Add to portfolio</button>
      </div>
    </div>
    ${avail ? "" : `<p class="status">Yahoo is busy right now — some numbers may be missing. Try again in a minute.</p>`}
    <div id="co-extras" class="co-extras" hidden></div>
    <div class="co-hero">
      <div class="co-quote">
        <div class="co-price">${px(c.price)}</div>
        ${chg ? `<div class="co-chg ${cls(c.change)}">${chg}</div>` : ""}
        ${asof ? `<div class="co-asof">As of ${esc(asof)}</div>` : ""}
      </div>
      <div class="co-keystats">
        ${kstat("Market cap", c.market_cap == null ? dash : fmtBig(c.market_cap))}
        ${kstat(`<abbr title="Price compared with yearly profit per share">P/E</abbr>`, c.pe == null ? dash : c.pe.toFixed(1))}
        ${kstat(`<abbr title="Yearly profit per share">EPS</abbr>`, px(c.eps))}
        ${kstat("Dividend", c.div_yield == null ? dash : c.div_yield.toFixed(2) + "%")}
      </div>
    </div>
    <div class="co-chart-card${avail ? "" : " hidden"}">
      <div class="co-chart-head"><h3>Price history</h3><span>1 year</span></div>
      <canvas id="co-chart"></canvas>
      ${c.returns ? `<div class="co-rets">${ret("1 month", c.returns["1m"])}${ret("This year", c.returns.ytd)}${ret("1 year", c.returns["1y"])}</div>` : ""}
    </div>
    <div class="co-grid">
      <div class="co-card">
        <h3>Today's trading</h3>
        ${rangeBar(c.day_range && c.day_range[0], c.day_range && c.day_range[1], c.price, "Day range", px)}
        ${stat("Volume", c.volume == null ? dash : fmtBig(c.volume))}
        ${stat("Usual volume", c.avg_volume == null ? dash : fmtBig(c.avg_volume))}
      </div>
      <div class="co-card">
        <h3>52-week range</h3>
        ${rangeBar(c.week52 && c.week52[0], c.week52 && c.week52[1], c.price, "Low to high", px)}
        ${stat("50-day average", px(c.ma50))}
        ${stat("200-day average", px(c.ma200))}
      </div>
      ${[c.revenue, c.employees, c.next_earnings, c.margins && (c.margins.gross ?? c.margins.operating ?? c.margins.net)].some((v) => v != null) ? `<div class="co-card">
        <h3>The business</h3>
        ${stat("Revenue", c.revenue == null ? dash : fmtBig(c.revenue))}
        ${stat("Gross margin", c.margins && c.margins.gross != null ? c.margins.gross.toFixed(0) + "%" : dash)}
        ${stat("Operating margin", c.margins && c.margins.operating != null ? c.margins.operating.toFixed(0) + "%" : dash)}
        ${stat("Net margin", c.margins && c.margins.net != null ? c.margins.net.toFixed(0) + "%" : dash)}
        ${stat("People", c.employees == null ? dash : Math.round(c.employees).toLocaleString("en-US"))}
        ${stat("Next earnings", c.next_earnings
          ? new Date(c.next_earnings + "T00:00:00").toLocaleDateString("en-US",
              { month: "short", day: "numeric", year: "numeric" })
          : dash)}
      </div>` : ""}
    </div>
    ${(c.free_cash_flow != null && c.shares_outstanding != null ? coDcf(c, tab) : "")}
    ${c.about ? `<div class="co-card co-about">
        <h3>About</h3>
        <p>${esc(c.about)}</p>
        ${c.website ? `<p class="co-web"><a href="${esc(c.website)}" target="_blank" rel="noopener">${esc(String(c.website).replace(/^https?:\/\//, ""))}</a></p>` : ""}
      </div>` : ""}`;

  $("#co-save").addEventListener("click", () => {
    saveThis("company", name, [
      `${name} (${sym})`,
      `Price: ${px(c.price)}${c.change_pct != null ? ` (${fmtSign(c.change_pct)})` : ""}`,
      c.week52 ? `52-week: ${px(c.week52[0])} – ${px(c.week52[1])}` : "",
      c.market_cap != null ? `Market cap: ${fmtBig(c.market_cap)}` : "",
      c.pe != null ? `P/E: ${c.pe.toFixed(1)}` : "",
      c.revenue != null ? `Revenue: ${fmtBig(c.revenue)}` : "",
      c.next_earnings ? `Next earnings: ${c.next_earnings}` : "",
    ].filter((s) => s && !/—$/.test(s.trim())));
  });
  if (avail) drawCoChart(c);
  initDcf(c, tab);
  wireCompanyFace(c, sym, name);
  reveal($("#co-body"));
}

/* ── Add to portfolio: a one-click form that reuses the same POST the
      portfolio page uses. The cost prefills with the live price; the
      rest is the user's to set. ── */
function openCompanyAddForm(c, sym) {
  closeCompanyAddForm();
  const box = $("#co-body");
  const pxPrice = c.price != null ? c.price.toFixed(2) : "";
  const form = document.createElement("div");
  form.id = "co-add-form";
  form.className = "card co-add-form";
  form.innerHTML = `
    <div class="co-add-head"><strong>Add ${esc(sym)} to your portfolio</strong>
      <button class="sheet-x" id="co-add-x" type="button" aria-label="Close">×</button></div>
    <div class="co-add-row">
      <label>Shares <input id="co-add-shares" type="number" min="0" step="any" placeholder="10" inputmode="decimal"></label>
      <label>Cost per share <input id="co-add-cost" type="number" min="0" step="any" value="${esc(pxPrice)}" inputmode="decimal"></label>
      <label>Bought <input id="co-add-date" type="date"></label>
    </div>
    <div class="co-add-row">
      <label class="grow">Note <input id="co-add-note" maxlength="120" placeholder="optional"></label>
    </div>
    <div class="co-add-actions">
      <button class="btn primary" id="co-add-go" type="button">Add</button>
      <span class="dim co-add-hint">lands in <a href="#home/portfolio">My portfolio</a></span>
    </div>
    <p id="co-add-status" class="status"></p>`;
  const head = box.querySelector(".pane-head");
  head.insertAdjacentElement("afterend", form);
  reveal(form);
  const close = () => { form.remove(); };
  $("#co-add-x").addEventListener("click", close);
  $("#co-add-go").addEventListener("click", async () => {
    const st = $("#co-add-status");
    const shares = parseFloat($("#co-add-shares").value);
    if (!isFinite(shares) || shares <= 0) {
      st.className = "status error";
      st.textContent = "Enter the number of shares.";
      return;
    }
    const body = {
      ticker: sym,
      shares: shares,
      cost_basis: parseFloat($("#co-add-cost").value) || 0,
      purchase_date: $("#co-add-date").value || "",
      note: $("#co-add-note").value.trim(),
    };
    st.className = "status";
    st.textContent = "Adding…";
    $("#co-add-go").disabled = true;
    try {
      await api("/api/portfolio", { method: "POST", body });
      toast(`Added ${esc(sym)} to your portfolio`);
      close();
      loadCoExtras(c, sym, c.name || sym);
    } catch (e) {
      st.className = "status error";
      st.textContent = e.message;
      $("#co-add-go").disabled = false;
    }
  });
  $("#co-add-shares").focus();
}
function closeCompanyAddForm() {
  const f = $("#co-add-form");
  if (f) f.remove();
}

/* ── The two quiet strips: who already holds this (smart money), and
      how much of the portfolio it already is (the reader's own). ── */
let _coExtrasSeq = 0;
async function loadCoExtras(c, sym, name) {
  const box = $("#co-extras");
  if (!box) return;
  const my = ++_coExtrasSeq;
  const alive = () => my === _coExtrasSeq && box.isConnected;
  const strip = document.createElement("div");
  strip.className = "co-strip";
  strip.innerHTML = `<span class="co-strip-k">Smart money</span>
    <span class="co-strip-v dim">Reading the funds…</span>`;
  box.hidden = false;
  box.innerHTML = "";
  box.appendChild(strip);
  let fundsStrip = null;
  try {
    let s = null;
    try {
      s = await api("/api/money/security?name=" + encodeURIComponent(name));
    } catch (e) {
      // truncated filings often spell the issuer differently; try the symbol
      if (sym && String(sym).toUpperCase() !== "?") {
        s = await api("/api/money/security?name=" + encodeURIComponent(sym));
      } else { throw e; }
    }
    let ovNames = Object.fromEntries(
      (window._money && window._money.funds || []).map((f) => [f.key, f.name]));
    if (!Object.keys(ovNames).length) {
      try {
        const ov = await api("/api/funds");
        ovNames = Object.fromEntries((ov.funds || []).map((f) => [f.key, f.name]));
      } catch { /* raw keys are a fine fallback */ }
    }
    if (!alive()) return;
    const names = s.funds.map((k) => ovNames[k] || k);
    const list = names.slice(0, 4).join(" · ") + (names.length > 4 ? ` +${names.length - 4} more` : "");
    fundsStrip = `<h3>Smart money</h3>
      <p class="co-strip-v"><b>${s.n_funds}</b> fund${s.n_funds === 1 ? "" : "s"} hold this — ${esc(list)}${s.total_value ? ` · <b>${fmtBig(s.total_value)}</b> combined` : ""}</p>
      <a class="linklike" href="#money/scan">Open the scan →</a>`;
  } catch {
    fundsStrip = `<h3>Smart money</h3><p class="co-strip-v dim">None of the tracked funds report a position in this.</p>`;
  }
  if (!alive()) return;
  strip.innerHTML = fundsStrip;
  // the reader's own position — with the chosen display currency so a
  // mixed-currency portfolio still yields one percentage
  try {
    const cur = (function () { try { return localStorage.getItem("proof-cur") || ""; } catch { return ""; } })();
    const d = await api("/api/portfolio" + (cur ? "?currency=" + encodeURIComponent(cur) : ""));
    const held = (d.positions || []).filter((p) => {
      const t = (p.ticker || "").toUpperCase();
      const n = tidy(p.name || "").toLowerCase();
      return t === String(sym).toUpperCase()
        || (name && tidy(name).toLowerCase() === n);
    });
    if (held.length) {
      const shares = held.reduce((a, p) => a + (p.shares || 0), 0);
      const value = held.reduce((a, p) => a + ((cur ? p.display_value : p.value) || 0), 0);
      const total = d.totals.value;
      const share = total ? (value / total) : null;
      const curShown = cur || held[0].currency || "";
      const own = document.createElement("div");
      own.className = "co-strip co-own";
      own.innerHTML = `<h3>You own this</h3>
        <p class="co-strip-v">${fmtShares(shares)} sh · <b>${fmtMoneyCur(value, curShown)}</b>${share != null ? ` · <b>${(share * 100).toFixed(1)}%</b> of your portfolio` : ""}</p>`;
      if (alive()) box.appendChild(own);
    } else {
      const own = document.createElement("div");
      own.className = "co-strip co-own dim";
      own.innerHTML = `<h3>You own this</h3><p class="co-strip-v">Nothing yet — the <a href="#home/portfolio">Add to portfolio</a> button above drops it in.</p>`;
      if (alive()) box.appendChild(own);
    }
  } catch { /* the strip stays quiet */ }
}

function wireCompanyFace(c, sym, name) {
  const addBtn = $("#co-add");
  if (addBtn) addBtn.addEventListener("click", () => openCompanyAddForm(c, sym));
  loadCoExtras(c, sym, name);
}

function coDcf(c, tab) {
  const g = c.revenue_growth;
  const growth = g != null && g > -20 && g < 30 ? Math.max(0, Math.min(15, g)) : 5;
  const st = (tab && tab.state.dcf) || {};
  const mode = st.mode === "implied" ? "implied" : "value";
  const rate = Number.isFinite(st.rate) ? st.rate : 8;
  const years = Number.isFinite(st.years) ? st.years : 5;
  const gv = Number.isFinite(st.growth) ? st.growth : growth;
  return `
    <div class="co-card co-dcf">
      <h3>Value it</h3>
      <div class="dcf-mode" role="group" aria-label="Valuation mode">
        <button type="button" class="dcf-mode-btn${mode === "value" ? " active" : ""}" data-mode="value">Value</button>
        <button type="button" class="dcf-mode-btn${mode === "implied" ? " active" : ""}" data-mode="implied">Implied growth</button>
      </div>
      <div class="dcf-inputs">
        <label class="dcf-growth-label">Growth <input id="dcf-growth" type="number" min="-50" max="100" step="0.5" value="${gv.toFixed(1)}"></label>
        <label>Discount <input id="dcf-rate" type="number" min="3" max="30" step="0.5" value="${rate}"></label>
        <label>Years <input id="dcf-years" type="number" min="1" max="15" step="1" value="${years}"></label>
      </div>
      <div id="dcf-out" class="dcf-out"></div>
      <p id="dcf-note" class="fineprint">Rough estimate. Not advice.</p>
    </div>`;
}

function initDcf(c, tab) {
  const out = $("#dcf-out");
  if (!out) return;
  const gEl = $("#dcf-growth"), rEl = $("#dcf-rate"), yEl = $("#dcf-years");
  const note = $("#dcf-note");
  const st = tab ? (tab.state.dcf = tab.state.dcf || {}) : {};
  const cur = c.financial_currency || c.currency;
  const money = (x) => sym(cur) + x.toFixed(2);
  const pct1 = (x) => (x < 0 ? "−" : "") + Math.abs(x).toFixed(1) + "%";

  const draw = () => {
    const years = Math.max(1, Math.min(15, Math.round(Number(yEl.value) || 5)));
    const r = Number(rEl.value);
    st.growth = Number(gEl.value);
    st.rate = r;
    st.years = years;
    if (!(r > 2.5)) {
      out.innerHTML = `<span class="status error">Discount must be above 2.5%.</span>`;
      return;
    }
    const base = {
      fcf: c.free_cash_flow, shares: c.shares_outstanding,
      cash: c.total_cash, debt: c.total_debt, discount: r, years,
    };
    if (st.mode === "implied") {
      if (c.price == null) {
        out.innerHTML = `<span class="dim">Need a price to solve.</span>`;
        return;
      }
      if (c.currency && cur && c.currency !== cur) {
        out.innerHTML = `<span class="dim">Price and cash flow use different currencies.</span>`;
        return;
      }
      const res = DCF.impliedGrowth(Object.assign({}, base, { price: c.price }));
      if (!res) {
        out.innerHTML = `<span class="dim">Need free cash flow and shares.</span>`;
        return;
      }
      const label = res.bounded === "low" ? "Below −99% a year"
        : res.bounded === "high" ? "Above 500% a year"
        : pct1(res.growth) + " a year";
      out.innerHTML = `
        <div class="dcf-row"><span class="k">Implied growth</span><span class="v">${label}</span></div>
        <div class="dcf-row"><span class="k">At today's price</span><span class="v">${fmtPrice(c.price, c.currency)}</span></div>`;
      return;
    }
    const per = DCF.valuePerShare(Object.assign({}, base, { growth: Number(gEl.value) }));
    if (per == null) {
      out.innerHTML = `<span class="dim">No free cash flow data.</span>`;
      return;
    }
    const equity = per * c.shares_outstanding;
    const sameCur = !c.currency || !cur || c.currency === cur;
    const up = sameCur && c.price ? per / c.price - 1 : null;
    out.innerHTML = `
      <div class="dcf-row"><span class="k">Per share</span><span class="v">${money(per)}</span></div>
      <div class="dcf-row"><span class="k">Total</span><span class="v">${fmtBigCur(equity, cur)}</span></div>
      ${up != null ? `<div class="dcf-row"><span class="k">vs price</span><span class="v ${cls(up)}">${fmtSign(up)}</span></div>` : ""}`;
  };

  const setMode = (mode) => {
    st.mode = mode;
    $$(".dcf-mode-btn").forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === mode));
    const gl = $(".dcf-growth-label");
    if (gl) gl.hidden = mode === "implied";
    if (note) note.textContent = mode === "implied"
      ? "Solves for the growth that matches today's price. Rough estimate. Not advice."
      : "Rough estimate. Not advice.";
    draw();
  };

  $$(".dcf-mode-btn").forEach((b) =>
    b.addEventListener("click", () => setMode(b.dataset.mode)));
  [gEl, rEl, yEl].forEach((el) => el.addEventListener("input", draw));
  setMode(st.mode === "implied" ? "implied" : "value");
}

function drawCoChart(c) {
  const cv = $("#co-chart");
  if (!cv) return;
  const pts = (c.history || []).filter((h) => h.c > 0);
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H || pts.length < 5) return;
  const dpr = window.devicePixelRatio || 1;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  const vals = pts.map((h) => h.c);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = (max - min) || min || 1;
  const n = pts.length;
  const padL = 56, padR = 10, padT = 14, padB = 22;
  const X = (i) => padL + (i / (n - 1)) * (W - padL - padR);
  const Y = (v) => padT + (1 - (v - min) / span) * (H - padT - padB);
  const cur = c.currency;
  const f = (v) => (cur && cur !== "USD" ? cur + " " : "$")
    + (v >= 1000 ? (v / 1000).toFixed(1) + "k" : v.toFixed(v >= 100 ? 0 : 1));
  ctx.strokeStyle = "#e4ddcc";
  ctx.fillStyle = "#8b8171";
  ctx.font = "11px sans-serif";
  for (let g = 0; g <= 4; g++) {
    const v = min + (span * g) / 4, y = Y(v);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.fillText(f(v), 6, y + 4);
  }
  const years = [];
  pts.forEach((h) => { const y = h.d.slice(0, 4); if (!years.includes(y)) years.push(y); });
  years.forEach((y) => {
    const i = pts.findIndex((h) => h.d.slice(0, 4) === y);
    if (i >= 0) ctx.fillText(y, X(i) - 8, H - 6);
  });
  ctx.beginPath();
  pts.forEach((h, i) => (i ? ctx.lineTo(X(i), Y(h.c)) : ctx.moveTo(X(i), Y(h.c))));
  ctx.strokeStyle = "#16120b"; ctx.lineWidth = 2; ctx.stroke();
  ctx.lineTo(X(n - 1), H - padB); ctx.lineTo(X(0), H - padB); ctx.closePath();
  ctx.fillStyle = "rgba(22, 18, 11, 0.06)"; ctx.fill();
}

window.addEventListener("resize", () => {
  clearTimeout(_coResizeT);
  _coResizeT = setTimeout(() => {
    if (CO.data && CO.data.history.length &&
        $("#tab-company").classList.contains("active"))
      drawCoChart(CO.data);
  }, 150);
});

/* smart-money rows carry a name, not a ticker: look the symbol up, then go */
async function coFromName(name, btn) {
  if (btn) btn.disabled = true;
  try {
    const d = await api("/api/search?q=" + encodeURIComponent(name));
    const r = (d.results || [])[0];
    if (!r) throw new Error("no match");
    go("company/" + encodeURIComponent(r.symbol));
  } catch (e) {
    toast("Couldn't find a company by that name");
    if (btn) btn.disabled = false;
  }
}

/* ---------------- landing ---------------- */
function enterApp() {
  if (!document.body.classList.contains("at-landing")) return;
  document.body.classList.remove("at-landing");
  $("#landing").classList.add("gone");
  setTimeout(() => $("#landing")?.remove(), 700);
  if (!location.hash) go("home/portfolio");
}
$("#l-enter").addEventListener("click", enterApp);
/* Landing links that point into the app: the anchor already changed the
   hash (which switched the pane beneath the overlay); just enter. */
$$("[data-l]").forEach((a) => a.addEventListener("click", enterApp));
/* Jumping straight at the portfolio CTA focuses the ticker field on arrival. */
$$(".l-start-btn").forEach((a) => a.addEventListener("click", () => {
  const hash = a.getAttribute("href") || "";
  if (hash !== "#home/portfolio") return;
  setTimeout(() => {
    const q = document.getElementById("pf-q");
    if (q && document.getElementById("sub-portfolio").classList.contains("active")) {
      q.focus();
      q.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, 1200);
}));
window.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !document.body.classList.contains("at-landing")) return;
  const tag = (document.activeElement || {}).tagName || "";
  if (/^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(tag)) return;
  enterApp();
});

/* ---------------- risk: what the portfolio becomes if each holding moves ---------------- */

const RM = {
  loading: false, filling: false, data: null, cur: PMF.cur,
  pendingFill: false, saveT: null,
};

const round2 = (x) => Math.round(x * 100) / 100;

async function loadRisk(refresh = false) {
  if (RM.loading) return;
  RM.loading = true;
  const st = $("#rm-status");
  st.className = "status";
  st.textContent = "Reading your portfolio…";
  try {
    const qs = new URLSearchParams();
    if (refresh) qs.set("refresh", "1");
    if (RM.cur) qs.set("currency", RM.cur);
    const suffix = qs.toString() ? "?" + qs.toString() : "";
    RM.data = await api("/api/risk" + suffix);
    renderRisk(RM.data);
    const n = RM.data.positions.length;
    st.textContent = n
      ? `${n} holding${n === 1 ? "" : "s"} · ${RM.data.n_live}/${n} priced`
      : "";
    if (RM.pendingFill) {
      RM.pendingFill = false;
      rmFillAi();
    }
  } catch (e) {
    st.className = "status error";
    st.textContent = e.message;
  } finally {
    RM.loading = false;
  }
}

function resolveRisk() {
  showPane("risk");
  syncNav("risk");
  loadRisk();
  reveal($("#tab-risk"));
}

function renderRisk(d) {
  RM.data = d;
  const has = d.positions.length > 0;
  $("#rm-empty").hidden = has;
  $("#rm-table-card").hidden = !has;
  $("#rm-total").hidden = !has;
  if (!has) { $("#rm-total").innerHTML = ""; const n = $("#rm-note"); if (n) { n.hidden = true; n.textContent = ""; } return; }
  $("#rm-cur").value = PF_CURRENCIES.includes(RM.cur) ? RM.cur : "";
  renderRmRows();
  paintRmStrip();
  const n = d.positions.length;
  $("#rm-cur-note").textContent = d.n_live !== n
    ? `${d.n_live}/${n} priced`
    : "";
}

/* One row's value and scenario, recomputed from the current move.
   Mirrors risk._row: the native number first, then the converted
   copy (same FX rate, same two decimals), so edits never refetch. */
function rmRowValues(p) {
  const m = p.move ?? 0;
  const value = RM.cur ? p.display_value : p.value;
  let scenario = null;
  if (p.value != null) {
    const native = round2(p.value * (1 + m / 100));
    scenario = RM.cur
      ? (p.fx != null ? round2(native * p.fx) : null)
      : native;
  }
  return { value, scenario };
}

/* the strip: scenario total + change vs today + typical swing.
   Same mixed-currency rule as the portfolio's strip. */
function rmTotals() {
  const positions = RM.data.positions;
  const rows = positions.filter((p) => rmRowValues(p).value != null);
  const curs = [...new Set(rows.map((p) => p.currency).filter(Boolean))].sort();
  const single = RM.cur || curs.length <= 1;
  const sum = (f) => {
    const xs = rows.map(f).filter((x) => x != null);
    return xs.length ? round2(xs.reduce((a, b) => a + b, 0)) : null;
  };
  const value = sum((p) => rmRowValues(p).value);
  const scenario = sum((p) => rmRowValues(p).scenario);
  let delta = null, delta_pct = null;
  if (single && value != null && scenario != null) {
    delta = round2(scenario - value);
    if (value > 0) delta_pct = delta / value;
  }
  let wsum = 0, vw = 0;
  if (single) {
    for (const p of rows) {
      const v = rmRowValues(p).value;
      if (p.vol == null || v == null || v <= 0) continue;
      wsum += v;
      vw += v * p.vol;
    }
  }
  return {
    value: single ? value : null,
    scenario: single ? scenario : null,
    delta, delta_pct,
    currencies: curs,
    currency: RM.cur || (curs.length === 1 ? curs[0] : null),
    vol: wsum > 0 ? vw / wsum : null,
    priced: rows.length,
    missing: positions.length - rows.length,
    n: positions.length,
  };
}

function paintRmStrip() {
  const T = rmTotals();
  const cur = T.currency || "";
  const mixed = !RM.cur && T.scenario == null && T.currencies.length > 1;
  const why = T.scenario == null
    ? (T.priced ? "Currencies don't add up — pick one above"
                : "Nothing could be priced")
    : (T.missing ? `${T.missing} holding${T.missing === 1 ? "" : "s"} without a price` : "");
  const del = T.delta != null
    ? ` <span class="${cls(T.delta)}">${fmtPl(T.delta, cur)}${T.delta_pct != null ? ` (${fmtSign(T.delta_pct)})` : ""}</span>`
    : "";
  $("#rm-total").innerHTML =
    `<span title="${esc(why)}">After the moves, <strong>${fmtBigCur(T.value, cur)}</strong> becomes <strong>${fmtBigCur(T.scenario, cur)}</strong></span>`
    + del
    + (T.vol != null ? ` <span class="dim">· typical swing ${fmtSign(T.vol)}</span>` : "")
    + (mixed ? ` <span class="dim">your holdings span ${esc(T.currencies.join(" · "))} — pick a currency above to convert</span>`
              : (why ? ` <span class="dim">${T.priced}/${T.n} priced</span>` : ""));
  paintRmNote();
}

/* One quiet line when one holding dominates: the concentration is the
   most important risk the desk can flag in a glance. */
function paintRmNote() {
  const box = $("#rm-note");
  if (!box) return;
  const positions = RM.data && RM.data.positions ? RM.data.positions : [];
  const rows = positions.filter((p) => rmRowValues(p).value != null);
  const total = rows.reduce((a, p) => a + rmRowValues(p).value, 0);
  if (!rows.length || total <= 0) { box.hidden = true; box.textContent = ""; return; }
  let top = rows[0], topVal = rmRowValues(rows[0]).value;
  for (const p of rows) {
    const v = rmRowValues(p).value;
    if (v > topVal) { top = p; topVal = v; }
  }
  const share = topVal / total;
  if (share < 0.4) { box.hidden = true; box.textContent = ""; return; }
  const tick = top.ticker || "that holding";
  box.hidden = false;
  box.innerHTML = `<b>Concentrated.</b> ${esc(tidy(top.name || tick))} is <b>${(share * 100).toFixed(1)}%</b> of this portfolio — a 10% move in it moves the whole thing ~${(share * 10).toFixed(1)}%.`;
}

function rmTip(p) {
  return !p.live ? "price unavailable — Yahoo is busy"
    : p.fx_missing ? "no exchange rate"
    : p.price_stale ? `last seen ${p.price_as_of || "?"}` : "live";
}

function rmRowHtml(p, i) {
  const val = (k) => (RM.cur ? p["display_" + k] : p[k]);
  const rcur = RM.cur || p.currency || "";
  const week = p.week == null ? "" : ` <small class="${cls(p.week)}">${fmtSign(p.week)}</small>`;
  return `
    <tr data-t="${esc(p.ticker)}" data-i="${i}">
      <td class="co" title="${esc(p.name)}"><span class="co-name">${esc(tidy(p.name))}</span>
        <small class="dim">${esc(p.ticker)}${p.kind === "custom" ? " · custom" : ""}</small></td>
      <td class="num" title="${esc(rmTip(p))}">${fmtPrice(val("price"), rcur)}${week}</td>
      <td class="num">${fmtMoneyCur(val("value"), rcur)}</td>
      <td class="num rm-movecell"><input class="rm-move" type="number" step="1"
        min="-99" max="999" value="${p.move ?? 0}"></td>
      <td class="num" title="the holding's own typical annual swing">${p.vol != null ? fmtSign(p.vol) : "—"}</td>
      <td class="num rm-after"></td>
    </tr>`;
}

/* the "after move" cell, repainted in place — the input keeps focus */
function rmPaintAfter(td) {
  const tr = td.closest("tr");
  const p = RM.data.positions[+tr.dataset.i];
  if (!p) return;
  const { value, scenario } = rmRowValues(p);
  const rcur = RM.cur || p.currency || "";
  if (value == null || scenario == null) { td.textContent = "—"; return; }
  const d = round2(scenario - value);
  td.innerHTML = `${fmtMoneyCur(scenario, rcur)}`
    + `<small class="${cls(d)}">${fmtPl(d, rcur)}</small>`;
}

function wireRmMove(inp) {
  inp.addEventListener("input", () => {
    const tr = inp.closest("tr");
    const i = +tr.dataset.i;
    let m = parseFloat(inp.value);
    if (!isFinite(m)) m = 0;
    RM.data.positions[i].move = Math.max(-99, Math.min(999, m));
    rmPaintAfter(tr.querySelector(".rm-after"));
    paintRmStrip();
    rmScheduleSave();
  });
}

function renderRmRows() {
  const d = RM.data;
  if (!d || !d.positions.length) return;
  const tb = $("#rm-table tbody");
  tb.innerHTML = d.positions.map((p, i) => rmRowHtml(p, i)).join("");
  $$("#rm-table .rm-move").forEach((inp) => wireRmMove(inp));
  $$("#rm-table .rm-after").forEach((td) => rmPaintAfter(td));
  reveal(tb);
}

function rmScheduleSave() {
  clearTimeout(RM.saveT);
  RM.saveT = setTimeout(rmSaveNow, 700);
}

async function rmSaveNow() {
  clearTimeout(RM.saveT);
  if (!RM.data || !RM.data.positions.length) return;
  const moves = {};
  for (const p of RM.data.positions) moves[p.ticker] = p.move ?? 0;
  try {
    await api("/api/risk", { method: "POST", body: { moves } });
  } catch {
    const st = $("#rm-status");
    st.className = "status error";
    st.textContent = "Could not save the moves — they will not survive a reload.";
  }
}

async function rmFillAi() {
  if (RM.filling || !RM.data || !RM.data.positions.length) return;
  RM.filling = true;
  const btn = $("#rm-fill");
  btn.disabled = true;
  btn.textContent = "Thinking…";
  try {
    const d = await api("/api/risk/fill", {
      method: "POST",
      body: { positions: RM.data.positions },
    });
    let n = 0;
    for (const p of RM.data.positions) {
      const m = d.moves[p.ticker];
      if (m != null) { p.move = m; n++; }
    }
    renderRmRows();
    paintRmStrip();
    rmSaveNow();
    const st = $("#rm-status");
    st.className = "status";
    st.textContent = `The model picked moves for ${n} of ${RM.data.positions.length} holdings — edit anything you don't agree with.`;
  } catch (e) {
    const st = $("#rm-status");
    st.className = "status error";
    st.textContent = e.message;
  } finally {
    RM.filling = false;
    btn.disabled = false;
    btn.textContent = "Fill with AI";
  }
}

$("#rm-cur").addEventListener("change", () => {
  RM.cur = $("#rm-cur").value;
  loadRisk();
});
$("#rm-zero").addEventListener("click", () => {
  if (!RM.data) return;
  for (const p of RM.data.positions) p.move = 0;
  renderRmRows();
  paintRmStrip();
  rmSaveNow();
});
$("#rm-fill").addEventListener("click", rmFillAi);
window.addEventListener("beforeunload", () => {
  if (RM.saveT) rmSaveNow();
});

/* ---------------- economy: where the world's wealth is held ----------------
   A static, global tree fetched once and drilled locally: six authored
   levels of detail plus geography. Each level is a donut: an annulus of
   one path per child, a share bar and the dollar amount beside it. The
   growth rates are assumptions a reader can move; projections are the
   only arithmetic that follows. No prices, no live sources. */

const ECO = { path: [], node: null, tree: null, loading: false, baseG: null };
const ECO_MAX_DEPTH = 7; /* seven levels deep: the root, six authored, then geography */
const ECO_HORIZONS = [5, 10, 15, 20];
const ECO_UI = { horizon: 10, tune: false, balance: true };
let ECO_META = null;

/* One colour per sibling position. Index 5 is gold, so the gold slice at
   the top level lands on its own metal. */
const ECO_COLORS = [
  "#b0672f", "#8d9b6a", "#b0492f", "#7d8fa3", "#6f8f83",
  "#c9a227", "#9a7bb0", "#b5836d", "#7f9b62", "#c47a5a",
];

const ecoHash = (path) => "#economy" + (path.length ? "/" + path.join("/") : "");

/* Same thresholds as the server's _fmt_usd, so the projected column lines
   up with the "today" one. */
function ecoUsd(v) {
  if (v == null || !isFinite(v)) return "—";
  if (v >= 1e12) {
    const t = v / 1e12;
    return "$" + (t >= 9.95 ? t.toFixed(0) : t.toFixed(1)) + "T";
  }
  if (v >= 1e9) return "$" + Math.round(v / 1e9) + "B";
  if (v >= 1e6) return "$" + Math.round(v / 1e6) + "M";
  return "$" + Math.round(v).toLocaleString("en-US");
}

const ecoProj = (v, g, h) => v * Math.pow(1 + g / 100, h);

/* ---------------- the decade: ten years behind every node ----------------
   The server's meta carries the report's shapes — the world and the four
   regions, 2015-2024 (see economy_series). The page rebuilds each node's
   own line locally from those shapes, so tuning a rate or letting the AI
   rewrite a level re-shapes every history chart without a round trip.
   Mirrors the server's economy_series.node_values, point for point. */
function ecoShape(node) {
  const S = ECO_META && ECO_META.series;
  if (!S || !S.years || S.years.length < 2) return null;
  if (node.level <= 1) return S.world || null;   /* world, and its seven slices: flat shares */
  if (node.level >= ECO_MAX_DEPTH) {             /* geography leaves: their region's record */
    const r = S.regions && S.regions[node.name];
    if (r && r.length === S.years.length) return r;
  }
  const rate = (node.g || 0) / 100;              /* everything deeper: its own growth */
  return S.years.map((y) => 1 / Math.pow(1 + rate, S.last_year - y));
}

/* One node's ten points, USD billions, oldest first. Always ends on the
   node's displayed value, whatever the tree's edits have done. */
function ecoSeries(node) {
  const S = ECO_META && ECO_META.series;
  const shape = ecoShape(node);
  if (!S || !shape || !isFinite(node.value_usd)) return null;
  const last = shape[shape.length - 1];
  return S.years.map((y, i) => node.value_usd * shape[i] / last / 1e9);
}

/* How honest a node's history is — the page says so in plain words. */
function ecoBasis(node) {
  if (node.level === 0)
    return "the world's own record, 2015-2024 (UBS Global Wealth Report)";
  if (node.level === 1)
    return "assumed: the world's shape with a flat share back to 2015";
  if (node.level >= ECO_MAX_DEPTH)
    return "geography: " + node.name + "'s measured record where the reports publish it, modelled in between";
  return "assumed: walked back at the node's own growth rate";
}

/* The per-year rate a ten-point line implies, first to last. */
function ecoCagr10(series) {
  if (!series || series.length < 2) return null;
  const a = series[0], b = series[series.length - 1];
  if (!(a > 0) || !isFinite(b)) return null;
  return (Math.pow(b / a, 1 / (series.length - 1)) - 1) * 100;
}

/* A hand-built line chart (no libraries). years: 2015..2024.
   lines: [{ color, values }] with values in USD bn, or pre-indexed if
   indexed is set. Returns an <svg> element. */
function ecoLineChart(years, lines, { indexed = false, w = 640, h = 220 } = {}) {
  const NS = "http://www.w3.org/2000/svg";
  const W = w, H = h;
  const P = { l: 8, r: 8, t: 14, b: 20 };
  const iw = W - P.l - P.r, ih = H - P.t - P.b;
  let lo = Infinity, hi = -Infinity;
  for (const L of lines) for (const v of L.values) {
    if (!isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!isFinite(lo) || hi - lo < 1e-9) { lo = 0; hi = 1; }
  const pad = (hi - lo) * 0.09;
  lo -= pad; hi += pad;
  const n = years.length;
  const X = (i) => P.l + (n < 2 ? iw / 2 : iw * i / (n - 1));
  const Y = (v) => P.t + ih * (1 - (v - lo) / (hi - lo));
  const fmtY = indexed ? (v) => v.toFixed(0) : (v) => ecoUsd(v * 1e9);
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.classList.add("eco-line");
  svg.setAttribute("role", "img");
  for (let g = 0; g <= 3; g++) {
    const v = lo + (hi - lo) * g / 3;
    const y = Y(v);
    const gl = document.createElementNS(NS, "line");
    gl.setAttribute("x1", P.l); gl.setAttribute("x2", W - P.r);
    gl.setAttribute("y1", y); gl.setAttribute("y2", y);
    gl.setAttribute("class", "eco-line-grid");
    svg.appendChild(gl);
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", P.l + 3); t.setAttribute("y", y - 3);
    t.setAttribute("class", "eco-line-tick");
    t.textContent = fmtY(v);
    svg.appendChild(t);
  }
  [0, Math.floor((n - 1) / 2), n - 1].filter((v, i, a) => a.indexOf(v) === i)
    .forEach((i) => {
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", X(i)); t.setAttribute("y", H - 6);
      t.setAttribute("text-anchor", i === 0 ? "start" : (i === n - 1 ? "end" : "middle"));
      t.setAttribute("class", "eco-line-tick");
      t.textContent = years[i];
      svg.appendChild(t);
    });
  for (const L of lines) {
    const pts = [];
    L.values.forEach((v, i) => { if (isFinite(v)) pts.push([X(i), Y(v)]); });
    if (!pts.length) continue;
    if (!indexed) {
      const area = document.createElementNS(NS, "path");
      area.setAttribute("d",
        `M ${pts[0][0].toFixed(1)} ${(P.t + ih).toFixed(1)} ` +
        pts.map((p) => `L ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ") +
        ` L ${pts[pts.length - 1][0].toFixed(1)} ${(P.t + ih).toFixed(1)} Z`);
      area.setAttribute("fill", L.color);
      area.setAttribute("fill-opacity", "0.07");
      svg.appendChild(area);
    }
    const pl = document.createElementNS(NS, "polyline");
    pl.setAttribute("points", pts.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" "));
    pl.setAttribute("fill", "none");
    pl.setAttribute("stroke", L.color);
    pl.setAttribute("stroke-width", "2");
    pl.setAttribute("stroke-linejoin", "round");
    svg.appendChild(pl);
    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", pts[pts.length - 1][0].toFixed(1));
    dot.setAttribute("cy", pts[pts.length - 1][1].toFixed(1));
    dot.setAttribute("r", "2.6");
    dot.setAttribute("fill", L.color);
    svg.appendChild(dot);
  }
  return svg;
}

/* A row's ten points as a tiny sparkline. */
function ecoSparkline(node, color) {
  const s = ecoSeries(node);
  if (!s || s.length < 2) return `<span class="dim">—</span>`;
  const W = 64, H = 18;
  let lo = Math.min(...s), hi = Math.max(...s);
  if (hi - lo < 1e-9) hi = lo + 1e-9;
  const pts = s.map((v, i) =>
    (2 + (W - 4) * i / (s.length - 1)).toFixed(1) + "," +
    (H - 2 - (H - 4) * (v - lo) / (hi - lo)).toFixed(1)).join(" ");
  return `<svg class="eco-spark" viewBox="0 0 ${W} ${H}" aria-hidden="true">
    <polyline points="${pts}" style="stroke:${color || "var(--sub)"}"></polyline></svg>`;
}

/* Growth is blended bottom-up: an internal node grows at the share-weighted
   rate of its parts. Rounding to one decimal keeps the page honest — the
   last digit is not meaningful. */
function ecoRecompute(node) {
  for (const c of node.children) ecoRecompute(c);
  if (node.children.length) {
    let total = 0;
    for (const c of node.children) total += c.share * c.g;
    node.g = Math.round((total / 100) * 10) / 10;
  }
}

/* Add a rate to one whole branch: the node and everything under it. */
function ecoShift(node, delta) {
  node.g = Math.round((node.g + delta) * 10) / 10;
  for (const c of node.children) ecoShift(c, delta);
}

function ecoSnapshot(tree) {
  const out = new Map();
  (function walk(n, path) {
    out.set(path.join("/"), n.g);
    for (const c of n.children) walk(c, path.concat(c.key));
  })(tree, []);
  return out;
}

function ecoResetRates() {
  if (!ECO.tree || !ECO.baseG) return;
  (function walk(n, path) {
    const g = ECO.baseG.get(path.join("/"));
    if (g != null) n.g = g;
    for (const c of n.children) walk(c, path.concat(c.key));
  })(ECO.tree, []);
  ECO.node = ecoFind(ECO.tree, ECO.path);
  renderEconomy();
}

/* Move one child's rate, and — when balancing is on — spread the exact
   counter-change across its siblings, so this level's blended rate does
   not move. At the root that is world growth held steady. */
function ecoSetRate(i, target) {
  const node = ECO.node;
  if (!node || !node.children[i] || !isFinite(target)) return;
  target = Math.max(-5, Math.min(25, target));
  const kid = node.children[i];
  const delta = target - kid.g;
  if (Math.abs(delta) < 0.049) return;
  ecoShift(kid, delta);
  if (ECO_UI.balance) {
    const others = node.children.filter((_, j) => j !== i);
    const sumShare = others.reduce((a, c) => a + c.share, 0);
    if (sumShare > 0) {
      const offset = -delta * kid.share / sumShare;
      for (const c of others) ecoShift(c, offset);
    }
  }
  ecoRecompute(ECO.tree);
  renderEconomy();
}

/* Donut geometry: an annulus inside a 240×240 viewBox. */
const ECO_R = 88;      /* outer radius */
const ECO_RI = 54;     /* inner radius */
const ECO_C = 120;     /* centre */
const ECO_HOVER = 6;   /* how far a hovered slice grows outward */

let ECO_T = null;      /* the live animation state for the current chart */

function ecoPt(r, ang) {
  const a = (ang - 90) * Math.PI / 180;
  return [ECO_C + r * Math.cos(a), ECO_C + r * Math.sin(a)];
}

function ecoSlicePath(a0, a1, R, r) {
  const sweep = a1 - a0;
  if (sweep <= 0.01) return "M 0 0";             /* collapsed: draw nothing */
  if (sweep >= 359.9) {                           /* a full ring */
    const [x0, y0] = ecoPt(R, 0), [x1, y1] = ecoPt(R, 180);
    const [u0, v0] = ecoPt(r, 0), [u1, v1] = ecoPt(r, 180);
    return `M ${x0} ${y0} A ${R} ${R} 0 1 1 ${x1} ${y1} A ${R} ${R} 0 1 1 ${x0} ${y0} `
         + `M ${u0} ${v0} A ${r} ${r} 0 1 0 ${u1} ${v1} A ${r} ${r} 0 1 0 ${u0} ${v0} Z`;
  }
  const large = sweep > 180 ? 1 : 0;
  const [x0, y0] = ecoPt(R, a0), [x1, y1] = ecoPt(R, a1);
  const [x2, y2] = ecoPt(r, a1), [x3, y3] = ecoPt(r, a0);
  return `M ${x0} ${y0} A ${R} ${R} 0 ${large} 1 ${x1} ${y1} `
       + `L ${x2} ${y2} A ${r} ${r} 0 ${large} 0 ${x3} ${y3} Z`;
}

function ecoStopAnim() {
  if (ECO_T) { cancelAnimationFrame(ECO_T.raf); ECO_T = null; }
}

function ecoKick() {
  if (ECO_T && !ECO_T.raf) ECO_T.raf = requestAnimationFrame(ECO_T.step);
}

/* Walk the already-fetched tree down a path of node keys. */
function ecoFind(node, path) {
  let cur = node;
  for (const seg of path) {
    cur = cur.children.find((c) => c.key === seg);
    if (!cur) return null;
  }
  return cur;
}

function resolveEconomy(pathParts) {
  showPane("economy");
  let path = (pathParts || []).map(decodeURIComponent).filter(Boolean);
  if (path.length > ECO_MAX_DEPTH) {
    path = path.slice(0, ECO_MAX_DEPTH);
    history.replaceState(null, "", ecoHash(path));
  }
  ECO.path = path;
  syncNav("economy", path.length ? path.join("/") : null);
  if (!ECO.tree) {
    loadEconomyTree();
    reveal($("#tab-economy"));
    return;
  }
  ECO.node = ecoFind(ECO.tree, path);
  if (!ECO.node) {
    ECO.path = [];
    history.replaceState(null, "", ecoHash([]));
    ECO.node = ECO.tree;
  }
  renderEconomy();
  reveal($("#tab-economy"));
}

async function loadEconomyTree() {
  if (ECO.loading) return;
  ECO.loading = true;
  const st = $("#eco-status");
  st.className = "status";
  st.textContent = "Reading the wealth tree…";
  try {
    const data = await api("/api/economy");
    ECO_META = data.meta || null;
    ECO.tree = data;
    ECO.baseG = ecoSnapshot(data);
    st.textContent = "";
    ECO.node = ecoFind(ECO.tree, ECO.path);
    if (!ECO.node) {
      /* a deep link that no longer matches the tree: go home quietly */
      ECO.path = [];
      history.replaceState(null, "", ecoHash([]));
      ECO.node = ECO.tree;
    }
    renderEconomy();
  } catch (e) {
    st.className = "status error";
    st.textContent = e.message;
  } finally {
    ECO.loading = false;
  }
}

async function ecoAiUpdate() {
  const st = $("#eco-status");
  const btn = $("#eco-ai");
  if (btn) { btn.disabled = true; btn.textContent = "Asking the model…"; }
  st.className = "status";
  st.textContent = "Rethinking this level…";
  try {
    const r = await api("/api/economy/update", {
      method: "POST", body: { path: ECO.path },
    });
    ECO.tree = null;
    ECO.node = null;
    await loadEconomyTree();
    st.className = "status ok";
    st.textContent = `Rewrote this level with ${r.children.length} parts`
      + (r.model ? ` (${r.model})` : "") + ".";
  } catch (e) {
    st.className = "status error";
    st.textContent = e.message;
    if (btn) { btn.disabled = false; btn.textContent = "Finish this list with AI"; }
  }
}

async function ecoResetTree() {
  const st = $("#eco-status");
  st.className = "status";
  st.textContent = "Restoring the authored tree…";
  try {
    await api("/api/economy/reset", { method: "POST" });
    ECO.tree = null;
    ECO.node = null;
    await loadEconomyTree();
    st.className = "status ok";
    st.textContent = "Back to the authored tree.";
  } catch (e) {
    st.className = "status error";
    st.textContent = e.message;
  }
}

function renderEconomy() {
  const node = ECO.node;
  if (!node) return;
  ecoStopAnim();
  $("#eco-title").textContent = node.name;

  /* breadcrumbs, walked from the local tree */
  let crumb = `<a class="eco-crumb" href="${ecoHash([])}">World</a>`;
  let cur = ECO.tree;
  let parentName = "";
  ECO.path.forEach((seg, i) => {
    const nxt = cur ? cur.children.find((c) => c.key === seg) : null;
    if (!nxt) return;
    const last = i === ECO.path.length - 1;
    if (last) parentName = cur ? cur.name : "";
    crumb += ` <span class="eco-crumbsep">›</span> ` + (last
      ? `<span class="dim">${esc(nxt.name)}</span>`
      : `<a class="eco-crumb" href="${ecoHash(ECO.path.slice(0, i + 1))}">${esc(nxt.name)}</a>`);
    cur = nxt;
  });
  /* deep nodes carry no written note; say where they sit instead of
     leaving a blank line */
  $("#eco-lede").textContent =
    node.note || (parentName ? `One part of ${parentName}.` : "");

  /* the way back up, once drilled */
  let back = "";
  if (node.level > 0) {
    let p = ECO.tree;
    for (const seg of ECO.path.slice(0, -1)) p = p.children.find((c) => c.key === seg);
    back = `<div class="eco-backwrap"><a class="btn ghost" href="${ecoHash(ECO.path.slice(0, -1))}">‹ ${esc(p ? p.name : "Up one level")}</a></div>`;
  }

  const kids = node.children;
  const H = ECO_UI.horizon;
  const projected = ecoProj(node.value_usd, node.g, H);
  const gainPct = (Math.pow(1 + node.g / 100, H) - 1) * 100;
  const chips = ECO_HORIZONS.map((h) =>
    `<button class="chip${h === H ? " active" : ""}" data-h="${h}">${h}y</button>`
  ).join("");

  const head = `<div class="eco-head">
      <span></span><span>Part</span><span></span>
      <span class="num">Share</span><span class="num">Today</span>
      <span class="num">Decade</span><span class="num">Growth</span>
      <span class="num">In ${H}y</span><span class="num">vs</span>
    </div>`;

  const rows = kids.map((c, i) => {
    const color = ECO_COLORS[i % ECO_COLORS.length];
    const growth = ECO_UI.tune
      ? `<input class="eco-rate" data-i="${i}" type="number" step="0.1"
           min="-5" max="25" value="${c.g.toFixed(1)}"
           aria-label="Growth rate for ${esc(c.name)}">`
      : `<span class="num eco-g">${c.g.toFixed(1)}%</span>`;
    return `<div class="eco-row${c.n_subs ? " eco-clickable" : " eco-leaf"}" data-i="${i}">
      <span class="eco-dot" style="background:${color}"></span>
      <span class="eco-name">${esc(c.name)}${c.n_subs
        ? `<small class="dim"> · ${c.n_subs} parts</small>` : ""}</span>
      <span class="eco-bar"><span style="width:${Math.max(2, c.share)}%;background:${color}"></span></span>
      <span class="num">${c.share}%</span>
      <span class="num">${esc(c.value_label)}</span>
      ${ecoSparkline(c, color)}
      ${growth}
      <span class="num dim">${ecoUsd(ecoProj(c.value_usd, c.g, H))}</span>
      <button class="eco-vsb${ECO_CMP.some((p) => p.sig === nodeSig(c)) ? " on" : ""}" data-vs="${i}" type="button"
        aria-pressed="${ECO_CMP.some((p) => p.sig === nodeSig(c))}"
        title="Put ${esc(c.name)} in the comparison">${ECO_CMP.some((p) => p.sig === nodeSig(c)) ? "✓" : "vs"}</button>
    </div>`;
  }).join("");

  /* the decade behind the current part: ten years of this node, with the
     honesty of the line stated plainly */
  let decade = "";
  if (ECO_META && ECO_META.series && ECO_META.series.years.length > 1) {
    const ser = ecoSeries(node);
    if (ser) {
      const cagr = ecoCagr10(ser);
      const picked = ECO_CMP.some((p) => p.sig === nodeSig(node));
      decade = `<div class="eco-decade">
        <div class="eco-decade-head">
          <span class="eco-decade-title">The decade behind ${node.level === 0 ? "the world" : "this part"}</span>
          <span class="dim">${ecoUsd(ser[0] * 1e9)} in ${ECO_META.series.years[0]} → ${esc(node.value_label)} in ${ECO_META.series.last_year}${cagr != null ? ` · ${(cagr >= 0 ? "+" : "−") + Math.abs(cagr).toFixed(1)}%/yr over the decade` : ""}</span>
          <button class="btn ghost tiny eco-vsb${picked ? " on" : ""}" id="eco-decade-vsb" type="button"
            aria-pressed="${picked}" title="Put this part in the comparison">${picked ? "✓" : "vs"}</button>
        </div>
        <div class="eco-decade-chart" id="eco-decade-chart"></div>
        <p class="dim eco-decade-basis">${esc(ecoBasis(node))}</p>
      </div>`;
    }
  }

  const tools = `<div class="eco-tools">
      ${kids.length ? `<label class="eco-check"><input type="checkbox" id="eco-tune" ${ECO_UI.tune ? "checked" : ""}> Tune rates</label>
      <label class="eco-check"><input type="checkbox" id="eco-balance" ${ECO_UI.balance ? "checked" : ""}> Hold this level's growth</label>
      <span class="dim eco-blend">This level grows <strong>${node.g.toFixed(1)}%/yr</strong>${ECO_UI.balance ? " — move one rate and the others absorb it" : ""}</span>
      <button class="btn ghost tiny" id="eco-reset-rates">Reset rates</button>` : ""}
      ${node.level === 5 && ECO_META && ECO_META.llm
        ? `<button class="btn tiny" id="eco-ai">Finish this list with AI</button>` : ""}
      ${ECO_META && ECO_META.edited
        ? `<button class="btn ghost tiny" id="eco-undo">Undo saved AI edits</button>` : ""}
    </div>`;

  const body = $("#eco-body");
  body.innerHTML = `
    <div class="eco-crumbs">${crumb}</div>
    ${back}
    ${decade}
    <div class="eco-proj">
      <span class="dim">Projected value</span>
      <span class="pf-periods eco-chips">${chips}</span>
      <strong>${ecoUsd(projected)}</strong>
      <span class="dim">in ${H} years · ${gainPct >= 0 ? "+" : ""}${gainPct.toFixed(0)}% total · at ${node.g.toFixed(1)}%/yr</span>
    </div>
    ${kids.length ? `<div class="eco-chartwrap">
      <div class="eco-donut-col">
        <div class="eco-donut">
        <svg class="eco-donutsvg" viewBox="0 0 240 240" aria-hidden="true"></svg>
        <div class="eco-center">
          <div class="eco-center-big">${esc(node.value_label)}</div>
          <div class="eco-center-small">${node.level === 0
            ? "global household wealth" : node.share_of_total + "% of all"}</div>
        </div>
        </div>
      </div>
      <div class="eco-legend">${head}${rows}</div>
    </div>` : `<p class="eco-end">The tree stops here — this is as fine as the
      picture goes. In this view it grows at ${node.g.toFixed(1)}%/yr.</p>`}
    ${tools}`;
  reveal(body);

  /* the horizon chips, the rate switches and the model button */
  $$("#eco-body .eco-chips .chip").forEach((el) => {
    el.addEventListener("click", () => {
      ECO_UI.horizon = Number(el.dataset.h);
      renderEconomy();
    });
  });
  const tune = $("#eco-tune");
  if (tune) tune.addEventListener("change", () => {
    ECO_UI.tune = tune.checked;
    renderEconomy();
  });
  const bal = $("#eco-balance");
  if (bal) bal.addEventListener("change", () => {
    ECO_UI.balance = bal.checked;
    renderEconomy();
  });
  const resetRates = $("#eco-reset-rates");
  if (resetRates) resetRates.addEventListener("click", ecoResetRates);
  const ai = $("#eco-ai");
  if (ai) ai.addEventListener("click", ecoAiUpdate);
  const undo = $("#eco-undo");
  if (undo) undo.addEventListener("click", ecoResetTree);
  $$("#eco-body .eco-rate").forEach((el) => {
    el.addEventListener("click", (e) => e.stopPropagation());
    el.addEventListener("change", () => {
      ecoSetRate(Number(el.dataset.i), Number(el.value));
    });
  });

  /* the decade chart, rebuilt from the live node (it follows tuned rates) */
  const dchart = $("#eco-decade-chart");
  if (dchart && ECO_META && ECO_META.series && ECO_META.series.years.length > 1) {
    const ser = ecoSeries(node);
    if (ser) dchart.appendChild(
      ecoLineChart(ECO_META.series.years, [{ color: "#b0672f", values: ser }]));
  }

  /* the vs on each row, and on the current part, feeds the compare tray */
  $$("#eco-body .eco-vsb[data-vs]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      const c = node.children[Number(el.dataset.vs)];
      if (c) cmpToggle(c.path, c.name);
    });
  });
  const dv = $("#eco-decade-vsb");
  if (dv) dv.addEventListener("click", () => cmpToggle(node.path, node.name));

  /* the compare page lives in this section too; a tree render is the tree */
  body.hidden = false;
  const cmpBody = $("#cmp-body");
  if (cmpBody) cmpBody.hidden = true;
  const cmpBar = $("#ws-compare");
  if (cmpBar) cmpBar.hidden = !WS.compare.tabs.length;
  const tray = $("#eco-cmp");
  if (tray) tray.hidden = false;
  ecoCmpTray();

  if (!kids.length) return;

  /* the slices, one per child, swept in with a slight stagger */
  const svg = body.querySelector(".eco-donutsvg");
  const NS = "http://www.w3.org/2000/svg";
  let ang = 0;
  const now = performance.now();
  const slices = kids.map((c, i) => {
    const a0 = ang;
    ang += c.share * 3.6;
    const el = document.createElementNS(NS, "path");
    el.setAttribute("fill", ECO_COLORS[i % ECO_COLORS.length]);
    el.setAttribute("fill-rule", "evenodd");
    el.setAttribute("d", "M 0 0");
    svg.appendChild(el);
    return { child: c, i, a0, a1: ang, p: 0, t0: now + i * 90,
             f: 0, h: 0, hover: false, el };
  });

  const center = body.querySelector(".eco-center");
  const big = center.querySelector(".eco-center-big");
  const small = center.querySelector(".eco-center-small");
  const centerText = (s) => {
    big.textContent = (s ? s.child : node).value_label;
    small.textContent = s
      ? s.child.name + " · " + s.child.share + "%"
      : (node.level === 0 ? "global household wealth" : node.share_of_total + "% of all");
  };
  centerText(null);

  const T = { slices, focus: null, raf: 0, step: null };
  ECO_T = T;
  T.step = (now) => {
    let busy = false;
    for (const s of T.slices) {
      if (now >= s.t0) s.p = Math.min(1, (now - s.t0) / 700);
      s.h += ((s.hover ? 1 : 0) - s.h) * 0.3;
      if (T.focus !== null) s.f = Math.min(1, s.f + 1 / 26);
      const e = 1 - Math.pow(1 - s.p, 3);
      let a0 = s.a0;
      let a1 = s.a0 + (s.a1 - s.a0) * e;
      if (T.focus !== null) {
        const fe = 1 - Math.pow(1 - s.f, 3);
        a1 = T.focus === s.i
          ? a1 + (s.a0 + 360 - a1) * fe   /* this slice becomes the ring */
          : a1 + (s.a0 - a1) * fe;        /* the others fold away */
      }
      s.el.setAttribute("d", ecoSlicePath(a0, a1, ECO_R + ECO_HOVER * s.h, ECO_RI));
      if ((now < s.t0 + 700 && s.p < 1)
          || Math.abs(s.h - (s.hover ? 1 : 0)) > 0.01
          || (T.focus !== null && s.f < 1)) busy = true;
      if (s.hover) centerText(s);
    }
    if (!T.slices.some((s) => s.hover)) centerText(null);
    T.raf = 0;
    /* Idle: stop drawing but keep the engine, so a hover or a click
       after the sweep still has something to talk to. */
    if (busy) T.raf = requestAnimationFrame(T.step);
  };
  T.raf = requestAnimationFrame(T.step);

  /* the rows and the slices glow together */
  const rowEls = $$("#eco-body .eco-row");
  const wire = (el, i) => {
    const s = slices[i];
    el.addEventListener("mouseenter", () => {
      s.hover = true;
      rowEls[i].classList.add("eco-hot");
      centerText(s);
      ecoKick();
    });
    el.addEventListener("mouseleave", () => {
      s.hover = false;
      rowEls[i].classList.remove("eco-hot");
      centerText(null);
      ecoKick();
    });
    if (s.child.n_subs) {
      el.addEventListener("click", (e) => {
        if (e.target.closest && e.target.closest(".eco-rate")) return;
        ecoFocus(i);
      });
      /* the rows are the keyboard's way down; the donut is not */
      if (el.tagName !== "path") {
        el.tabIndex = 0;
        el.setAttribute("role", "button");
        el.setAttribute("aria-label",
          `Open ${s.child.name}: ${s.child.share}% of ${node.name}`);
        el.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            ecoFocus(i);
          }
        });
      }
    }
  };
  rowEls.forEach((el, i) => wire(el, i));
  $$("#eco-body .eco-donutsvg path").forEach((el, i) => wire(el, i));
}

/* Click: grow the chosen slice into a full ring, then drill into it. */
function ecoFocus(i) {
  const T = ECO_T;
  if (!T || T.focus !== null) return;
  T.focus = i;
  T.slices[i].el.parentNode.appendChild(T.slices[i].el); /* paint on top */
  const c = T.slices[i].child;
  ecoKick();
  setTimeout(() => {
    if (ECO_T === T && c.n_subs) go(ecoHash([...ECO.path, c.key]));
  }, 560);
}

/* ---------------- compare: two to five things, a decade each -----------
   A tray in the tree collects picks (any level, via the vs on each row or
   on the current part); "Compare" opens a page with their histories
   indexed 2015=100, "Ask the AI" opens the same page with the model's
   read of them. The page recomputes the series locally from the live
   tree, so it follows the reader's tuned rates. */
let ECO_CMP = [];   /* the tray: [{ name, path, sig }] */

const nodeSig = (n) => (n.path ? n.path.join("/") : "");
const nodePick = (n) => ({ name: n.name, level: n.level, path: [...n.path] });

/* Resolve the tray against the live tree, in case edits renamed things. */
function cmpResolve() {
  if (!ECO.tree) return [];
  const out = [];
  for (const p of ECO_CMP) {
    const n = ecoFind(ECO.tree, p.path);
    if (n) out.push(nodePick(n));
  }
  return out;
}

function cmpToggle(path, name) {
  const sig = path.join("/");
  const i = ECO_CMP.findIndex((p) => p.sig === sig);
  if (i >= 0) ECO_CMP.splice(i, 1);
  else {
    if (ECO_CMP.length >= 5) {
      toast("A comparison holds at most five things.");
      return;
    }
    ECO_CMP.push({ name, path: [...path], sig });
  }
  syncCmp();
}

function syncCmp() {
  ecoCmpTray();
  const picked = new Set(ECO_CMP.map((p) => p.sig));
  const setBtn = (b, sig) => {
    const on = picked.has(sig);
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
    b.textContent = on ? "✓" : "vs";
  };
  $$("#eco-body .eco-vsb[data-vs]").forEach((b) => {
    const c = ECO.node && ECO.node.children[Number(b.dataset.vs)];
    if (c) setBtn(b, nodeSig(c));
  });
  const d = $("#eco-decade-vsb");
  if (d && ECO.node) setBtn(d, nodeSig(ECO.node));
}

/* The slim card under the tree: what's picked, and the two doors out. */
function ecoCmpTray() {
  const box = $("#eco-cmp");
  if (!box) return;
  const n = ECO_CMP.length;
  const aiOn = !!(ECO_META && ECO_META.llm);
  const chips = ECO_CMP.map((p, i) =>
    `<span class="chip eco-cmpchip">${esc(p.name)}
      <button class="chip-x" data-cmp="${i}" type="button"
        aria-label="Remove ${esc(p.name)} from the comparison">×</button></span>`).join(" ");
  box.innerHTML = `
    <div class="eco-cmpt">
      <span class="dim eco-cmpt-hint">${n ? "In the comparison:"
        : "Pick 2-5 things to compare a decade of growth — the vs on each row, or the current part above."}</span>
      ${chips}
      <button class="btn tiny" id="eco-cmp-go" type="button" ${n >= 2 ? "" : "disabled"}
        title="${n >= 2 ? "" : "Pick at least two things"}">Compare →</button>
      <button class="btn ghost tiny" id="eco-cmp-ai" type="button"
        ${n >= 2 && aiOn ? "" : "disabled"}
        title="${n < 2 ? "Pick at least two things" : (aiOn ? "" : "The AI read needs a language model")}">Ask the AI →</button>
    </div>`;
  box.querySelectorAll(".chip-x").forEach((b) =>
    b.addEventListener("click", () => {
      ECO_CMP.splice(Number(b.dataset.cmp), 1);
      syncCmp();
    }));
  const go = $("#eco-cmp-go");
  if (go) go.addEventListener("click", () => openCompareTab(cmpResolve(), false));
  const ai = $("#eco-cmp-ai");
  if (ai) ai.addEventListener("click", () => openCompareTab(cmpResolve(), true));
}

/* Open (or return to) a comparison as a workspace tab in the economy
   section, and — asked — let the model read it. */
function openCompareTab(picks, ai) {
  if (!picks.length) return;
  const title = picks.map((p) => p.name || "?")
    .slice(0, 2).join(" vs ") + (picks.length > 2 ? " +" + (picks.length - 2) : "");
  const t = wsAddTab("compare", { picks, ai: null, model: null, note: null }, title);
  if (!t) return;
  ECO_CMP = [];
  syncCmp();
  showPane("economy");
  syncNav("economy");
  wsActivate("compare", t.id, { hash: true, show: false });
  showCompareTab();
  if (ai) cmpAskAi();
}

function resolveCompare(seg) {
  showPane("economy");
  let t = null;
  if (seg && seg.startsWith("@"))
    t = WS.compare.tabs.find((x) => x.id === seg.slice(1)) || null;
  else
    t = WS.compare.tabs.find((x) => x.state.picks.length) || null;
  if (!t) t = wsStaleFallback("compare", t);
  if (!t) t = wsAddTab("compare", WS_DEFAULT.compare());
  wsActivate("compare", t.id, { show: false });
  syncNav("economy");
  showCompareTab();
  /* a fresh deep link never visited the tree: fetch it. The load's own
     completion re-asserts the tree view, so put this one back on top */
  if (!ECO.tree) loadEconomyTree().then(() => showCompareTab());
}

function showCompareTab() {
  const bar = $("#ws-compare"), main = $("#eco-body"),
        tray = $("#eco-cmp"), cmp = $("#cmp-body");
  if (!bar || !main || !cmp) return;
  const t = activeWS("compare");
  const hasPicks = !!(t && t.state.picks.length);
  if (!hasPicks) {
    /* no comparison in view: the tree, with its tray */
    bar.hidden = !WS.compare.tabs.length;
    main.hidden = false;
    tray.hidden = false;
    cmp.hidden = true;
    if (ECO.node) {
      $("#eco-title").textContent = ECO.node.name;
      $("#eco-lede").textContent = ECO.node.note || "";
      $("#eco-status").className = "status";
      $("#eco-status").textContent = "";
    }
    return;
  }
  bar.hidden = false;
  wsRender("compare");
  main.hidden = true;
  tray.hidden = true;
  cmp.hidden = false;
  $("#eco-title").textContent = "Comparing a decade";
  $("#eco-lede").textContent =
    "Two to five parts of the wealth tree, 2015 to 2024 — the world's shape, or each one's own growth.";
  $("#eco-status").className = "status";
  $("#eco-status").textContent = "";
  renderCompare();
}

function renderCompare() {
  const t = activeWS("compare");
  const body = $("#cmp-body");
  if (!t || !body) return;
  if (!ECO.tree) {
    /* the tree is still loading: the chart and the rows are its
       arithmetic, so say so instead of pretending the picks vanished */
    body.innerHTML = `
      <div class="cmp-backwrap"><a class="btn ghost"
        href="${ecoHash(ECO.path)}">‹ Back to the tree</a></div>
      <p class="status" style="padding: 24px 16px;">Reading the wealth tree…</p>`;
    reveal(body);
    return;
  }
  const S = ECO_META && ECO_META.series;
  const years = (S && S.years) || [];
  const picks = t.state.picks || [];
  const rows = [];
  const lines = [];
  picks.forEach((p, i) => {
    const color = ECO_COLORS[i % ECO_COLORS.length];
    const n = ECO.tree ? ecoFind(ECO.tree, p.path) : null;
    if (!n) {
      rows.push(`<div class="cmp-row"><span class="eco-dot" style="background:${color}"></span>
        <span class="cmp-name">${esc(p.name)}
          <small class="dim">no longer in the tree after the edits</small></span>
        <span class="num dim">—</span><span class="num dim">—</span>
        <span class="num dim">—</span><span class="num dim">—</span>
        <span class="num dim">—</span></div>`);
      return;
    }
    const ser = ecoSeries(n) || [];
    lines.push({ color, values: ser.length > 1 && ser[0] > 0
      ? ser.map((v) => v / ser[0] * 100)   /* indexed 2015=100 */
      : ser });
    const cagr = ecoCagr10(ser);
    rows.push(`<div class="cmp-row"><span class="eco-dot" style="background:${color}"></span>
      <span class="cmp-name">${esc(n.name)}
        <small class="dim">${n.path.length ? esc(n.path.join(" › ")) : "the world"} · ${esc(ecoBasis(n))}</small></span>
      <span class="num">${n.share_of_total}%</span>
      <span class="num">${esc(n.value_label)}</span>
      <span class="num">${(n.g || 0).toFixed(1)}%</span>
      <span class="num">${cagr == null ? "—" : (cagr >= 0 ? "+" : "−") + Math.abs(cagr).toFixed(1) + "%/yr"}</span>
      <span class="num">${ecoUsd(ser.length ? ser[ser.length - 1] * 1e9 : n.value_usd)}</span></div>`);
  });

  body.innerHTML = `
    <div class="cmp-backwrap"><a class="btn ghost" href="${ecoHash(ECO.path)}">‹ Back to the tree</a></div>
    <div class="cmp-head">
      <span class="dim">indexed ${years[0] || 2015} = 100 · USD, ${years[0] || 2015}–${S ? S.last_year : 2024}</span>
      ${ECO_META && ECO_META.llm
        ? `<button class="btn tiny" id="cmp-ai" type="button">${t.state.ai ? "Re-ask the AI" : "Ask the AI to read this"}</button>`
        : `<span class="dim">The AI read needs a language model — set one in Settings.</span>`}
    </div>
    <div class="cmp-chart" id="cmp-chart"></div>
    ${t.state.ai ? `<div class="cmp-ai">
      <p>${esc(t.state.ai)}</p>
      <p class="dim cmp-ai-meta">Read by ${esc(t.state.model || "the model")} · ${picks.length} things, ${years[0] || 2015}–${S ? S.last_year : 2024}</p>
    </div>` : ""}
    ${t.state.note && !t.state.ai
      ? `<p class="status error">${esc(t.state.note)} — the chart stands on its own.</p>` : ""}
    ${rows.length ? `<div class="cmp-rows">
      <div class="cmp-row cmp-head-row">
        <span></span><span>Part</span><span class="num">Share of all</span>
        <span class="num">Today</span><span class="num">Growth</span>
        <span class="num">2015–24</span><span class="num">End 2024</span>
      </div>${rows.join("")}</div>` : ""}
    <p class="cmp-fine">${esc((ECO_META && ECO_META.series_note) || "")}</p>`;
  const chart = $("#cmp-chart");
  if (chart) chart.appendChild(ecoLineChart(years, lines, { indexed: true, w: 720, h: 250 }));
  const btn = $("#cmp-ai");
  if (btn) btn.addEventListener("click", cmpAskAi);
  reveal(body);
}

async function cmpAskAi() {
  const t = activeWS("compare");
  if (!t || !t.state.picks.length) return;
  const btn = $("#cmp-ai");
  if (btn) { btn.disabled = true; btn.textContent = "Reading…"; }
  t.state.note = null;
  try {
    const r = await api("/api/economy/compare", {
      method: "POST",
      body: { paths: t.state.picks.map((p) => p.path.join("/")), ai: true },
    });
    t.state.ai = r.ai || null;
    t.state.model = r.model || null;
  } catch (e) {
    t.state.ai = null;
    t.state.note = e.message;   /* 503 or a bad answer: the chart remains */
  }
  wsSave("compare");
  renderCompare();
}

/* ---------------- boot ---------------- */
wireScan();
let _dirT;
$("#dir-q").addEventListener("input", () => {
  clearTimeout(_dirT);
  _dirT = setTimeout(dirSearch, 250);
});
$("#dir-q").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { clearTimeout(_dirT); dirSearch(); }
});
/* the empty-portfolio CTA focuses the ticker field and scrolls it into view */
$("#pf-add-first").addEventListener("click", () => {
  const q = $("#pf-q");
  if (q) { q.focus(); q.scrollIntoView({ block: "center", behavior: "smooth" }); }
});
wsRestoreAll();
applyHash();
VAULT.sync();   // the newer of the server file and this mirror wins
(async () => {
  try {
    await api("/api/strategies"); // warm cache
  } catch { /* ignore */ }
  try {
    const h = await api("/api/health");
    window._llm = !!h.llm_configured;
  } catch {
    window._llm = false;
  }
  const lt = activeWS("lab");
  if (lt && !lt.state.text) lt.state.text = EXAMPLES[0].text;
  if (document.getElementById("tab-lab").classList.contains("active")) showLabTab();
})();

/* ---------------- portfolio chat bubble ---------------- */
const CHAT = { history: [], busy: false, greeted: false };

function chatPush(role, text) {
  const log = $("#chat-log");
  const div = document.createElement("div");
  div.className = "chat-msg " + role;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function chatOpen(open) {
  $("#chat-panel").hidden = !open;
  if (open) {
    if (!CHAT.greeted) {
      CHAT.greeted = true;
      chatPush("assistant", "Ask about your holdings, the risk fill, Smart Money, or a backtest.");
    }
    $("#chat-q").focus();
  }
}

$("#chat-fab").addEventListener("click", () => chatOpen($("#chat-panel").hidden));
$("#chat-close").addEventListener("click", () => chatOpen(false));

function runChatAction(a) {
  if (!a) return;
  if (a.type === "risk_fill") {
    // navigate (or stay), then run the same fill the button runs
    RM.pendingFill = true;
    if ((location.hash || "").replace(/^#/, "") !== "risk") go("risk");
    else loadRisk();
    return;
  }
  if (a.type === "smart_money") {
    wsOpen("money", { sub: "scan", secName: a.query || "" });
    showMoneyTab();
    return;
  }
  if (a.type === "backtest") {
    const t = wsAddTab("lab", {
      step: "setup", text: a.text || "buy and hold",
      symbol: a.symbol || "SPY", years: a.years || 10,
    });
    if (t) {
      wsActivate("lab", t.id, { hash: false });
      history.replaceState(null, "", "#" + wsHash("lab", t));
      runLab();
    }
  }
}

// A brief of the page the user is looking at, so the bubble can answer
// questions about it ("what does this company do?", "explain that result").
function chatPageBrief() {
  const parts = (location.hash || "").replace(/^#/, "").split("/");
  const kind = parts[0] || "home";
  const brief = { kind };
  if (kind === "company") {
    const c = CO.data;
    if (c) Object.assign(brief, {
      symbol: c.symbol, name: c.name, price: c.price, currency: c.currency,
      change_pct: c.change_pct, market_cap: c.market_cap, pe: c.pe,
      about: c.about || "", dcf: $("#dcf-out") ? $("#dcf-out").textContent : "",
    });
  } else if (kind === "lab") {
    const t = activeWS("lab");
    if (t) {
      brief.text = t.state.text || "";
      brief.symbol = t.state.symbol || "SPY";
      brief.years = t.state.years || 10;
      if (t.spec) brief.summary = t.spec.summary;
      const v = $("#verdict");
      if (v && v.textContent) brief.verdict = v.textContent;
    }
  } else if (kind === "money") {
    const t = activeWS("money");
    brief.sub = (t && t.state.sub) || (MONEY_SUBS.includes(parts[1]) ? parts[1] : "funds");
  } else if (kind === "risk") {
    if (RM.data) {
      const T = rmTotals();
      brief.n = RM.data.positions.length;
      brief.n_live = RM.data.n_live;
      brief.value = T.value ?? null;
      brief.scenario = T.scenario ?? null;
      brief.currency = T.currency ?? null;
    }
  } else if (kind === "economy") {
    brief.sub = (ECO.node && ECO.node.name) || "";
  } else if (kind === "compare") {
    const t = activeWS("compare");
    brief.sub = "compare";
    brief.names = (t && t.state.picks || []).map((p) => p.name);
  }
  return brief;
}

$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (CHAT.busy) return;
  const q = $("#chat-q").value.trim();
  if (!q) return;
  CHAT.busy = true;
  $("#chat-q").value = "";
  chatPush("user", q);
  CHAT.history.push({ role: "user", content: q });
  const pending = chatPush("assistant", "Thinking…");
  pending.classList.add("pending");
  try {
    const d = await api("/api/chat", {
      method: "POST",
      body: { q, history: CHAT.history.slice(-8), currency: PMF.cur,
              page: chatPageBrief() },
    });
    pending.classList.remove("pending");
    pending.textContent = d.answer;
    CHAT.history.push({ role: "assistant", content: d.answer });
    if (d.action) runChatAction(d.action);
  } catch (err) {
    pending.classList.remove("pending");
    pending.textContent = err.message;
  } finally {
    CHAT.busy = false;
    $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  }
});

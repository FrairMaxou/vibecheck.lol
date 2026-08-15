# App Shell — Flush Sidebar & Slim Header Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the floating, rounded `#tabs` nav card with a `position: fixed`, 100vh-flush left sidebar (Firefox-style), shrink the header to a slim page-title bar, and fold Settings + Profile into the sidebar's pinned bottom section — fixing the "hideous" look the maintainer flagged, using only the CSS custom properties and assets that already exist.

**Architecture:** Pure CSS/HTML restructure of the existing single-page vanilla-JS dashboard — no new components, no build step, no framework. The notification drawer, pending-badge, sync-status line, and profile-menu (Settings/Version/Feedback/Uninstall) already exist and already do almost everything the spec asks for; this plan relocates them into a fixed sidebar rather than rebuilding them. `#tabs`' 4 nav buttons, their `data-tab` wiring, and `switchTab()` are untouched — only their container moves.

**Tech Stack:** Vanilla HTML/CSS/JS (`vibecheck/web/index.html`, `style.css`, `app.js`), served by FastAPI (`vibecheck/dashboard.py`) with live-reload-on-request (`FileResponse` re-reads the file every request — no build step, no cache-busting needed beyond a hard browser refresh).

**Spec:** The maintainer's shell blueprint (pasted in chat, not a file) — flush 100vh sidebar (56px collapsed / 220px expanded), slim header (page title + Filters + Notification Bell only), and a consolidated notification drawer. Two open questions from that spec were resolved with the maintainer before this plan was written:
- Tagline ("Winrate is temporary. The vibes are forever.") → **stays visible, inline in the header subtitle** (e.g. "The Vibe Check — Winrate is temporary...").
- Content width on wide monitors → **keep the existing ~1400px cap**, now left-anchored flush against the sidebar instead of centered on the full viewport (previously `.page-container` centered via `margin: 0 auto`; the sidebar occupying the true left edge makes that both unnecessary and wrong).

## Global Constraints

- **No new colors, fonts, or design tokens.** `.claude/brand identity/BRAND.md` §8 explicitly marks the "official" Hextech palette/font adoption as **not yet done** (tracked separately as issue #57, unscheduled). This plan uses only the CSS custom properties already in `style.css` `:root` (`--bg`, `--surface`, `--surface-2`, `--line`, `--ink`, `--ink-2`, `--ink-3`, `--gold`, `--teal`) and the existing `Segoe UI` system font stack. Mixing in #57's colors here would make half the UI look "rebranded" and half not — worse than doing nothing.
- **No fabricated data.** The spec's example drawer copy says "🟢 Squad Sync Active (3 friends online)" — the app has no live presence tracking, only a mutual-friend **sync** count (`/api/squad/status` → `mutual_count`). Keep the existing, accurate `renderSyncStatus()` wording ("Squad Sync active — N friends synced"). Do not invent an "online" claim the data can't back up.
- **`vibecheck/PRD.md` §6a (Vanguard safety) and §6b (lightweight/localhost-only) are unaffected** — this is a static-asset/CSS change, no new endpoints, no new LCU calls.
- **Existing element IDs are load-bearing.** `#tabs`, `#profile-btn`, `#profile-menu`, `#notif-bell`, `#notif-panel`, `#nav-collapse-toggle` are all referenced by ID in `app.js`. Every task below preserves these IDs so existing `addEventListener` wiring keeps working without changes, and only adds the minimum new wiring needed.

---

## File Structure

- **Modify `vibecheck/web/index.html`** — wrap the 4 nav buttons + brand mark + profile/settings/collapse in a new `<aside id="sidebar">`; shrink `<header>` to page-title + filters + notif bell; delete the now-empty `.app-shell` wrapper div (its only children, `#tabs` and `<main>`, move to `#sidebar` and directly under `.page-container` respectively).
- **Modify `vibecheck/web/style.css`** — new `.sidebar`/`.sidebar-top`/`.sidebar-bottom`/`.sidebar-brand` rules (replacing `#tabs`' old card styling), header/`.page-container`/`main` repositioning, `.profile-menu` reposition (opens upward-right from the sidebar instead of downward-left from the header), a small `.notif-version` rule, and recomputed zero-scroll grid constants.
- **Modify `vibecheck/web/app.js`** — `switchTab()` gains a one-line page-title update; a new `#settings-btn` click handler (opens the same `#profile-menu` popover `#profile-btn` already does); `checkUpdate()` moves to also fire at boot (like `renderSyncStatus()` already does) so the drawer's new version line has data by the time it's opened; a new `renderNotifVersion()`; `initNavRail()` toggles a class on the new content wrapper alongside its existing `#sidebar` toggle.

---

### Task 1: Sidebar shell — HTML restructure

**Files:**
- Modify: `vibecheck/web/index.html:11-148` (header) and `:177-186` (`.app-shell` open, `#tabs`, `<main>` open)

**Interfaces:**
- Produces: `#sidebar` (new `<aside>`, `position: fixed`), `.sidebar-top`, `.sidebar-nav` (wraps the existing `#tabs`), `.sidebar-bottom`, `#settings-btn` (new button, no existing JS listener yet — added in Task 3).
- Consumes: nothing new — `#tabs`, its 4 `<button data-tab="...">` children, `#nav-collapse-toggle`, `#profile-btn`, `#profile-menu` all keep their exact existing markup, just relocated.

- [ ] **Step 1: Restructure `index.html`'s top-level layout**

Replace the header-block-plus-app-shell region (lines 11–186, from `<body ...>` through the `<main>` opening) with:

```html
<body data-palette="#b28328,#2f9ac0" data-mode="dark">
<aside id="sidebar" class="sidebar">
  <div class="sidebar-top">
    <a class="sidebar-brand" href="#" aria-label="VibeCheck.lol">
      <img src="/assets/logo.png" alt="" width="28" height="28">
      <span class="sidebar-brand-word">VibeCheck.lol</span>
    </a>
    <nav id="tabs" class="sidebar-nav">
      <button data-tab="overview" class="active"><span class="nav-icon">🎯</span><span class="nav-label">The Vibe Check</span></button>
      <button data-tab="champions"><span class="nav-icon">🏆</span><span class="nav-label">Champions</span></button>
      <button data-tab="squad"><span class="nav-icon">👥</span><span class="nav-label">The Squad</span></button>
      <button data-tab="patterns"><span class="nav-icon">📈</span><span class="nav-label">Patterns & Tags</span></button>
    </nav>
  </div>
  <div class="sidebar-bottom">
    <div class="profile">
      <button id="profile-btn" class="sidebar-item" aria-haspopup="true">
        <span class="profile-avatar">🤩</span>
        <span class="profile-id nav-label">
          <span id="profile-name">Summoner</span>
          <span id="profile-vibe" class="profile-vibe"></span>
        </span>
        <span id="profile-dot" class="profile-dot hidden" title="An update is available"></span>
      </button>
      <div id="profile-menu" class="profile-menu hidden">
        <div class="pm-head">
          <div class="pm-name" id="pm-name">Summoner</div>
          <div class="pm-stats" id="pm-stats"></div>
        </div>

        <div class="pm-section">
          <div class="pm-title">Version</div>
          <div id="update-body" class="pm-muted">Checking for updates…</div>
          <button id="pm-update-btn" class="primary-btn hidden">Update now</button>
          <div id="update-progress" class="update-progress hidden"><div id="update-bar"></div></div>
          <div id="update-msg" class="squad-msg"></div>
        </div>

        <div class="pm-section">
          <div class="pm-title">Settings</div>
          <div class="setting-row">
            <div class="setting-text">
              <div class="setting-title">Start with Windows</div>
              <div class="setting-desc">Launch automatically at login so no game is missed.</div>
            </div>
            <label class="switch"><input type="checkbox" id="set-autostart"><span class="slider"></span></label>
          </div>
          <div class="setting-row">
            <div class="setting-text">
              <div class="setting-title">Pause rating popups</div>
              <div class="setting-desc">Keep capturing games, but hide the "How was that game?" popup. Rate later from To Rate.</div>
            </div>
            <label class="switch"><input type="checkbox" id="set-paused"><span class="slider"></span></label>
          </div>
          <div class="setting-row">
            <div class="setting-text">
              <div class="setting-title">When you close the window</div>
              <div class="setting-desc">"Ask" prompts each time. Minimize keeps VibeCheck in the tray; Quit shuts it down.</div>
            </div>
            <select id="set-close-action" class="setting-select">
              <option value="ask">Ask every time</option>
              <option value="minimize">Minimize to tray</option>
              <option value="quit">Quit the app</option>
            </select>
          </div>
          <div class="setting-row">
            <div class="setting-text">
              <div class="setting-title">Anonymous usage stats</div>
              <div class="setting-desc">Helps me see how many people use VibeCheck and which version to
                support. Anonymous — no personal data.</div>
            </div>
            <label class="switch"><input type="checkbox" id="set-telemetry"><span class="slider"></span></label>
          </div>
          <div id="settings-msg" class="squad-msg"></div>
        </div>

        <div class="pm-section">
          <div class="pm-title">Feedback</div>
          <p class="pm-muted">Found a bug, or want something added? Tell me — it genuinely shapes what gets built.</p>
          <div class="pm-links">
            <a id="pm-discord" class="pm-link" href="#" target="_blank" rel="noopener">💬 Join the Discord</a>
            <a id="pm-feedback" class="pm-link hidden" href="#" target="_blank" rel="noopener">📝 Send feedback</a>
          </div>
        </div>

        <div class="pm-section">
          <div class="pm-title">Your data</div>
          <p class="pm-muted">Games live in <code>%LOCALAPPDATA%\VibeCheck</code>. Only rated games
            sync, and only your mutual League friends can see them.</p>
          <button id="pm-uninstall" class="danger-btn">Uninstall VibeCheck…</button>
          <div id="uninstall-msg" class="squad-msg"></div>
        </div>
      </div>
    </div>
    <button id="settings-btn" class="sidebar-item" aria-haspopup="true" title="Settings">
      <span class="nav-icon">⚙️</span><span class="nav-label">Settings</span>
    </button>
    <button id="nav-collapse-toggle" class="sidebar-item nav-collapse-btn" aria-label="Collapse navigation" title="Collapse navigation">
      <span class="nav-icon">«</span><span class="nav-label">Collapse</span>
    </button>
  </div>
</aside>

<div class="app-content">
<div class="page-container">
<header>
  <div class="title-block">
    <h1 id="page-title">The Vibe Check</h1>
    <p class="subtitle" id="page-subtitle">Winrate is temporary. The vibes are forever.</p>
  </div>
  <div class="header-actions">
    <section id="filters" class="filters">
      <button id="filters-toggle" class="filters-toggle-btn" aria-haspopup="true">
        <span class="filters-burger">☰</span> Filters <span id="f-count" class="filter-count"></span>
      </button>
      <div id="filters-panel" class="filters-panel hidden">
        <div class="filter-group">
          <label>From</label>
          <input type="date" id="f-from">
        </div>
        <div class="filter-group">
          <label>To</label>
          <input type="date" id="f-to">
        </div>
        <div class="filter-group"><label>Queue</label><div id="f-queue"></div></div>
        <div class="filter-group"><label>Mode</label><div id="f-mode"></div></div>
        <div class="filter-group"><label>Champion</label><div id="f-champion"></div></div>
        <div class="filter-group"><label>Role</label><div id="f-role"></div></div>
        <div class="filter-group"><label>Teammate</label><div id="f-teammate"></div></div>
        <div class="filter-group"><label>Result</label><div id="f-result"></div></div>
        <button id="f-clear" class="ghost-btn">Clear filters</button>
      </div>
    </section>
    <div class="notif">
      <button id="notif-bell" class="notif-bell-btn" aria-haspopup="true" title="Notifications">
        🔔<span id="pending-badge" class="badge hidden"></span>
      </button>
      <div id="notif-panel" class="notif-panel hidden">
        <div class="notif-section">
          <div class="notif-title">Action required</div>
          <button id="notif-pending-row" class="notif-row hidden">
            <span id="notif-pending-text"></span>
            <span class="notif-row-arrow">Rate now →</span>
          </button>
          <div id="notif-pending-empty" class="notif-empty hidden">All caught up — nothing to rate.</div>
        </div>
        <div class="notif-section">
          <div class="notif-title">Status</div>
          <div id="notif-sync" class="notif-sync"></div>
          <div id="notif-version" class="notif-sync"></div>
        </div>
      </div>
    </div>
  </div>
</header>

<div id="whatsnew" class="modal-backdrop hidden">
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="whatsnew-title">
    <h2 id="whatsnew-title">What's new ✨</h2>
    <p class="modal-sub" id="whatsnew-version"></p>
    <ul id="whatsnew-list"></ul>
    <button id="whatsnew-ok" class="primary-btn">Got it</button>
  </div>
</div>

<div id="onboarding" class="modal-backdrop hidden">
  <div class="modal onboarding-modal" role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
    <h2 id="onboarding-title">Let's get you started 👋</h2>
    <p class="modal-sub">We grabbed your last few games. Rate them and your dashboard
      starts with something in it — otherwise you're staring at empty charts until
      your next match.</p>
    <div id="onboarding-list" class="onboarding-list"></div>
    <div class="onboarding-foot">
      <span id="onboarding-progress" class="pm-muted"></span>
      <button id="onboarding-skip" class="link-btn">Skip for now</button>
    </div>
  </div>
</div>

<div id="offline-banner" class="banner banner-err hidden"></div>
<div id="update-banner" class="banner banner-update hidden"></div>
<div id="low-data-banner" class="banner hidden"></div>

<main>
```

Everything from the original `<main>`'s opening tag through the original closing `</main></div></div>` (the 6 `.tab` divs — lines 187–313) stays **byte-for-byte identical**, just re-close with:

```html
</main>
</div>
</div>

<footer id="legal-footer">
  VibeCheck.lol isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot
  Games or anyone officially involved in producing or managing Riot Games properties. Riot Games,
  and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
</footer>
</div>

<script src="/static/chart.umd.js?v=__VERSION__"></script>
<script src="/static/app.js?v=__VERSION__"></script>
</body>
</html>
```

Note the net structural change: `.app-shell` (the old flex-row wrapper of `#tabs` + `<main>`) is **deleted** — `#tabs` moved into `#sidebar`, and `<main>` is now a direct child of `.page-container`, which is itself inside the new `.app-content` wrapper. `#legal-footer` moves from a body-level sibling to inside `.page-container` (so its existing `max-width: 90ch; margin: auto` centers within the sidebar-offset content area instead of the full body width — the correct behavior now that the sidebar occupies real screen space).

- [ ] **Step 2: Verify no orphaned references**

Run: `grep -n "app-shell" vibecheck/web/index.html vibecheck/web/style.css vibecheck/web/app.js`
Expected: no matches (confirms the class was fully removed, not left half-referenced).

- [ ] **Step 3: Commit**

```bash
git add vibecheck/web/index.html
git commit -m "feat(web): restructure shell HTML for a fixed left sidebar"
```

---

### Task 2: Sidebar, header, and content-offset CSS

**Files:**
- Modify: `vibecheck/web/style.css:1-47` (`:root`, `body`, `.page-container`, `header`, `.app-logo`, `.subtitle`)
- Modify: `vibecheck/web/style.css:287-324` (delete `.app-shell`, `#tabs`, `.nav-collapse-btn`, `#tabs.collapsed` — replaced by sidebar rules)

**Interfaces:**
- Consumes: `#sidebar`, `.sidebar-top`, `.sidebar-bottom`, `.sidebar-brand`, `.sidebar-nav`, `.sidebar-item`, `#tabs`, `.nav-icon`, `.nav-label` from Task 1's HTML.
- Produces: `--sidebar-w`, `--sidebar-w-collapsed`, `--header-h` custom properties other tasks (3, 4, 5) read.

- [ ] **Step 1: Add sizing tokens to `:root`**

In `style.css:1-12`, add three lines to the existing `:root` block (do not touch the existing 10 declarations):

```css
:root {
  --bg: #10141a;
  --surface: #1e2328;
  --surface-2: #282e36;
  --line: #3c434d;
  --ink: #f0e6d2;
  --ink-2: #a09b8c;
  --ink-3: #6b7280;
  --gold: #c8aa6e;
  --teal: #3fa7c4;
  --muted-bar: #4a5058;
  --sidebar-w: 220px;
  --sidebar-w-collapsed: 56px;
  --header-h: 56px;
}
```

- [ ] **Step 2: Replace `body`/`.page-container`/`header` rules**

Replace `style.css:14-47` (from `* { box-sizing... }` through `.subtitle { ... }`) with:

```css
* { box-sizing: border-box; margin: 0; }
body {
  background: var(--bg);
  color: var(--ink);
  font: 14px/1.5 "Segoe UI", system-ui, sans-serif;
}

/* Content area to the right of the fixed sidebar. margin-left (not padding)
   so .app-content's own box starts exactly at the sidebar's right edge —
   .page-container inside it then caps at 1400px and does NOT auto-center,
   so on a wide monitor the content hugs the sidebar and any leftover space
   falls on the right, never as a gap next to the sidebar. */
.app-content {
  margin-left: var(--sidebar-w);
  min-height: 100vh;
  transition: margin-left .18s ease;
}
.app-content.nav-collapsed { margin-left: var(--sidebar-w-collapsed); }

.page-container {
  max-width: 1400px; width: 100%;
  padding: 20px clamp(12px, 4vw, 48px) 60px;
}

/* Slim page-title bar — replaces the old hero brand banner, which now lives
   (as an icon only) at the top of the sidebar. Sticky rather than fixed:
   nothing above it scrolls independently, so top:0 is enough to keep it in
   place without also having to track the sidebar's width in a right/left
   calc() here. */
header {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;
  height: var(--header-h); margin-bottom: 14px;
  position: sticky; top: 0; z-index: 25; background: var(--bg);
}
.header-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
/* Title + tagline share one line at this size — the tagline was the hero
   header's flourish; demoted to an inline dash-suffix rather than dropped,
   per the maintainer's call. */
h1 {
  display: inline; font-size: 18px; font-weight: 700; letter-spacing: .3px; color: var(--gold);
}
.subtitle { display: inline; color: var(--ink-2); font-size: 13px; margin-left: 8px; }
.subtitle::before { content: "— "; }
```

(`.app-logo` and `.visually-hidden` rules at the old lines 40–46 are deleted — the horizontal wordmark image no longer appears in the header; Task 1 already dropped its `<img>`/`<h1 class="visually-hidden">` combo in favor of a plain visible `<h1 id="page-title">`.)

- [ ] **Step 2: Delete the old rail rules, add sidebar rules**

Replace `style.css:287-324` (`.app-shell` through the `.badge` rule right after `#tabs.collapsed`) with:

```css
main {
  height: calc(100vh - var(--header-h) - 14px);
  overflow-y: auto;
}

/* ---------- fixed left sidebar ---------- */
.sidebar {
  position: fixed; top: 0; left: 0; bottom: 0; z-index: 50;
  width: var(--sidebar-w);
  display: flex; flex-direction: column; justify-content: space-between;
  background: var(--surface); border-right: 1px solid var(--line);
  transition: width .18s ease;
}
.sidebar.collapsed { width: var(--sidebar-w-collapsed); }
.sidebar.collapsed .nav-label,
.sidebar.collapsed .sidebar-brand-word { display: none; }

.sidebar-top { display: flex; flex-direction: column; min-height: 0; overflow-y: auto; }
.sidebar-brand {
  display: flex; align-items: center; gap: 10px; padding: 16px 14px;
  color: var(--ink); text-decoration: none; flex: none;
}
.sidebar-brand img { width: 28px; height: 28px; flex: none; border-radius: 6px; }
.sidebar-brand-word { font-size: 15px; font-weight: 700; color: var(--gold); white-space: nowrap; }

.sidebar-nav { display: flex; flex-direction: column; gap: 2px; padding: 4px 8px; }
.sidebar-nav button {
  display: flex; align-items: center; gap: 10px;
  background: none; border: none; border-left: 2px solid transparent; border-radius: 6px;
  color: var(--ink-2); padding: 9px 10px; cursor: pointer; font: inherit; font-size: 14px;
  text-align: left; white-space: nowrap;
}
.sidebar-nav button:hover { color: var(--ink); background: var(--surface-2); }
.sidebar-nav button.active { color: var(--gold); border-left-color: var(--gold); background: var(--surface-2); }
.nav-icon { font-size: 15px; flex: none; width: 18px; text-align: center; }

.sidebar-bottom {
  display: flex; flex-direction: column; gap: 2px; padding: 8px; flex: none;
  border-top: 1px solid var(--line);
}
.sidebar-item {
  display: flex; align-items: center; gap: 10px; width: 100%;
  background: none; border: none; border-radius: 6px;
  color: var(--ink-2); padding: 9px 10px; cursor: pointer; font: inherit; font-size: 14px;
  text-align: left; white-space: nowrap;
}
.sidebar-item:hover { color: var(--ink); background: var(--surface-2); }
.sidebar.collapsed .nav-collapse-btn .nav-icon { transform: scaleX(-1); display: inline-block; }
.badge {
  background: var(--gold); color: #1e2328; border-radius: 10px;
  font-size: 11px; font-weight: 700; padding: 1px 7px; margin-left: 4px;
}
```

- [ ] **Step 3: Rewire `.profile-btn`/`.profile-avatar`/`.profile-id` for sidebar context**

The existing rules at `style.css:50-64` (`.profile`, `.profile-btn`, `.profile-avatar`, `.profile-id`, `#profile-name`, `.profile-vibe`, `.profile-btn .chev`) assumed a pill-shaped header button. Replace them with:

```css
.profile { position: relative; }
.profile-avatar {
  width: 26px; height: 26px; border-radius: 50%; background: var(--surface-2);
  display: grid; place-items: center; font-size: 15px; flex: none;
}
.profile-id { display: flex; flex-direction: column; align-items: flex-start; line-height: 1.15; min-width: 0; }
#profile-name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; max-width: 130px; }
.profile-vibe { font-size: 11.5px; color: var(--ink-2); }
```

(`#profile-btn` itself now uses `.sidebar-item` from Step 2 for its padding/hover/layout — no separate `.profile-btn` rule needed. `.chev` is dropped: the sidebar row no longer has room for a dropdown chevron next to a name that can already run up to 130px wide.)

- [ ] **Step 4: Reposition `.profile-menu` to open upward from the sidebar**

Replace `style.css:66-71` (`.profile-menu { position: absolute; top: calc(100% + 8px); right: 0; ... }`) with:

```css
.profile-menu {
  position: absolute; bottom: calc(100% + 8px); left: 0; z-index: 51; width: 340px;
  max-height: 70vh; overflow-y: auto;
  background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0,0,0,.55);
}
```

(`bottom`/`left` instead of `top`/`right` — the trigger now sits near the bottom of a fixed sidebar, so the panel must open upward or it would be clipped by the viewport edge. `z-index: 51` — one above `.sidebar`'s `50` — since the panel is meant to spill out past the sidebar's own right edge over the main content, not sit behind it. `max-height` drops from `78vh` to `70vh` to leave clearance above the trigger at the 900×600 minimum window size, verified in Task 6.)

- [ ] **Step 5: Run a diff sanity check**

Run: `grep -n "\.app-shell\|#tabs {" vibecheck/web/style.css`
Expected: no matches — confirms the old rail card styling and `.app-shell` rule are gone, not merely shadowed.

- [ ] **Step 6: Commit**

```bash
git add vibecheck/web/style.css
git commit -m "feat(web): flush fixed sidebar and slim header CSS"
```

---

### Task 3: Settings button, page title on tab switch, collapse-state wiring

**Files:**
- Modify: `vibecheck/web/app.js:1886-1935` (`switchTab`, nav button wiring, profile menu open/close, `initNavRail`)

**Interfaces:**
- Consumes: `#settings-btn`, `#sidebar` (renamed target — was `#tabs`), `.app-content` from Tasks 1–2.
- Produces: nothing new consumed elsewhere — this task's additions are leaf-level event wiring.

- [ ] **Step 1: Give `switchTab` a page-title update**

The 4 nav buttons already carry the exact display name in their `.nav-label` span (e.g. `<span class="nav-label">The Vibe Check</span>`) — reuse that text instead of a second lookup table, so the two can never drift.

In `app.js`, replace the `switchTab` function (currently at line 1886-1892):

```javascript
function switchTab(tabId) {
  document.querySelectorAll("#tabs button[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === tabId));
  state.tab = tabId;
  document.querySelectorAll(".tab").forEach((el) => el.classList.add("hidden"));
  document.getElementById(`tab-${tabId}`).classList.remove("hidden");
  const activeBtn = document.querySelector(`#tabs button[data-tab="${tabId}"]`);
  if (activeBtn) document.getElementById("page-title").textContent = activeBtn.querySelector(".nav-label").textContent;
  renderAll();
}
```

(`"pending"` has no rail button — per the existing comment right above this function, that's expected; the page title simply stays whatever it last was, same as the rail's own now-unhighlighted state.)

- [ ] **Step 2: Wire `#settings-btn` to open the same profile menu**

Immediately after the existing profile-menu wiring block (`app.js:1939-1947`), add:

```javascript
// Settings (sidebar bottom): opens the same profile-menu popover the
// Profile row does — one panel, two entry points, since Settings already
// lives inside it (pm-section "Settings") rather than needing its own.
document.getElementById("settings-btn").addEventListener("click", (e) => {
  e.stopPropagation(); // must match #profile-btn's own handler — without this,
                        // the document-level outside-click dismiss (below,
                        // checks .closest(".profile")) would immediately
                        // close the menu this same click just opened, since
                        // #settings-btn sits outside the .profile wrapper.
  toggleProfileMenu();
});
```

- [ ] **Step 3: Rename the collapse target from `#tabs` to `#sidebar`, and toggle `.app-content` alongside it**

Replace `initNavRail` (currently `app.js:1925-1935`):

```javascript
// Sidebar: manual collapse persisted per-device, defaulting to collapsed
// near the 900px window minimum so the rail doesn't crowd content. Toggles
// two elements in lockstep: #sidebar (its own width) and .app-content
// (its margin-left offset) — see the CSS comment on .app-content.nav-collapsed.
(function initNavRail() {
  const sidebar = document.getElementById("sidebar");
  const content = document.querySelector(".app-content");
  const stored = localStorage.getItem("navCollapsed");
  const collapsed = stored === null ? window.innerWidth < 1000 : stored === "1";
  sidebar.classList.toggle("collapsed", collapsed);
  content.classList.toggle("nav-collapsed", collapsed);
  document.getElementById("nav-collapse-toggle").addEventListener("click", () => {
    const next = !sidebar.classList.contains("collapsed");
    sidebar.classList.toggle("collapsed", next);
    content.classList.toggle("nav-collapsed", next);
    localStorage.setItem("navCollapsed", next ? "1" : "0");
  });
})();
```

- [ ] **Step 4: Commit**

```bash
git add vibecheck/web/app.js
git commit -m "feat(web): wire settings button, page title, and sidebar collapse offset"
```

---

### Task 4: Passive version line in the notification drawer

**Files:**
- Modify: `vibecheck/web/app.js:1244-1325` (`toggleProfileMenu`, `checkUpdate`) and `:2040-2057` (boot sequence)

**Interfaces:**
- Consumes: `#notif-version` (from Task 1's HTML), the existing `UPDATE` global and `/api/update` shape (`{current, latest, update_available, ...}`).
- Produces: `renderNotifVersion()`, callable from anywhere `UPDATE` might have changed.

- [ ] **Step 1: Add `renderNotifVersion`, call it from `checkUpdate`**

`checkUpdate()` (currently `app.js:1298-1325`) already fetches `/api/update` and sets the module-level `UPDATE`. Add a render call at the end of it, and the function itself right after:

In `checkUpdate()`, right after `UPDATE = u;` (line 1303), add one line:

```javascript
    UPDATE = u;
    renderNotifVersion();
```

And after `checkUpdate`'s closing brace (after line 1325), add:

```javascript
/* Passive "Status" line in the notification drawer, mirroring the same
   /api/update read the profile menu's Version section already does —
   independent read, same pattern as renderSyncStatus() above it, so the
   drawer has something to show without the user ever opening the profile
   menu first. */
function renderNotifVersion() {
  const el = document.getElementById("notif-version");
  if (!UPDATE) { el.textContent = ""; return; }
  el.innerHTML = UPDATE.update_available
    ? `<span class="notif-sync-dot"></span> v${escapeAttr(UPDATE.current)} — update available`
    : `<span class="notif-sync-dot is-synced"></span> v${escapeAttr(UPDATE.current)} — up to date`;
}
```

- [ ] **Step 2: Call `checkUpdate()` at boot, not only on profile-menu open**

Find the boot sequence near the bottom of `app.js` where `renderSyncStatus()` is called at top level (line 2052). Add `checkUpdate();` on the line right after it:

```javascript
renderSyncStatus();
checkUpdate();
```

`toggleProfileMenu()` (`app.js:1246-1251`) still calls `checkUpdate()` on every open too — harmless, it's just a re-fetch of the same cheap endpoint, and keeps the profile menu's own Version section fresh if it's been open a while.

- [ ] **Step 3: Verify the drawer shows a version line without opening the profile menu**

This needs the running dev server (`.venv\Scripts\python -m vibecheck`) and a browser — see Task 6's verification pass, which checks this alongside everything else. No isolated check here; the two are cheaper to verify together once the whole shell is in place.

- [ ] **Step 4: Commit**

```bash
git add vibecheck/web/app.js
git commit -m "feat(web): show app version passively in the notification drawer"
```

---

### Task 5: Recompute the Overview zero-scroll grid for the new header height

**Files:**
- Modify: `vibecheck/web/style.css:710-780` (the `@media (min-width: 1400px) and (min-height: 850px)` zero-scroll block from the earlier #88 follow-up, already committed on `fix/zero-scroll-grid-polish`)

**Interfaces:**
- Consumes: `--header-h` (now `56px`, was locally `88px` inside this block) from Task 2.

This grid's own `max-height`/row-height numbers were tuned live in Chrome for the *old* ~88px hero header. The new header is 56px, and `.page-container`'s own top padding/structure changed in Task 2 — the two magic numbers this block depends on (container `max-height` formula, row 1's `242px`) need re-measuring against the real DOM, not hand-adjusted. This mirrors exactly how they were originally derived (see the `fix/zero-scroll-grid-polish` branch, already committed): live-measure `scrollHeight` vs `clientHeight` in Chrome, adjust, repeat until `needsScroll` is `false`.

- [ ] **Step 1: Start the dev server**

Run: `.venv\Scripts\python -m vibecheck` (background) — or reuse an already-running instance; the dashboard re-reads `style.css`/`app.js` from disk on every request, no restart needed after edits, only a browser refresh.

- [ ] **Step 2: Load the dashboard at 1920×889 and measure**

Navigate to `http://127.0.0.1:8577`, resize the browser window to 1920×889 (the same "1080p after browser chrome" case used originally), then in the page console:

```javascript
const grid = document.querySelector('.ov-grid12');
JSON.stringify({
  scrollHeight: grid.scrollHeight, clientHeight: grid.clientHeight,
  needsScroll: grid.scrollHeight > grid.clientHeight,
  computedMaxHeight: getComputedStyle(grid).maxHeight
});
```

Expected right after Task 2's CSS lands (before this task's own fix): `needsScroll: true` — the container's `max-height: calc(100vh - var(--header-h))` formula still references the *old* structure (`20px` body padding that no longer exists the same way, now folded into `.page-container`'s own padding inside `.app-content`).

- [ ] **Step 3: Update the zero-scroll block's `max-height` formula and re-measure**

In the `@media (min-width: 1400px) and (min-height: 850px)` block, the `.ov-grid12` rule currently reads (from the `fix/zero-scroll-grid-polish` branch):

```css
  .ov-grid12 {
    --header-h: 88px;
    /* 20px = body's own top padding (line ~19), same on every page —
       not part of the header, but part of the fixed budget above the grid. */
    max-height: calc(100vh - 20px - var(--header-h));
    overflow-y: auto; margin-bottom: 0;
    grid-template-rows: 242px 183px 305px;
    ...
```

Replace the `--header-h`/`max-height` lines and the comment above them with:

```css
  .ov-grid12 {
    /* --header-h (56px, :root) plus header's own 14px margin-bottom, plus
       .page-container's 20px top padding — all three sit above the grid
       under the new fixed-sidebar shell. Re-measured live in Chrome at
       1920x889 after the Task 2 restructure; adjust here (and the row
       heights below) if either changes, then re-run this task's Step 2. */
    max-height: calc(100vh - var(--header-h) - 14px - 20px);
    overflow-y: auto; margin-bottom: 0;
    grid-template-rows: 242px 183px 305px;
    ...
```

Re-run Step 2's measurement. If `needsScroll` is still `true`, trim `grid-template-rows`' third value (currently `305px`) downward in 5px steps and re-measure — this was the tightest-fitting row last time (see the comment already in that media query block about the trend chart's `--ov-trend-chart-h`) and is the correct one to trim first, matching the original tuning session's approach.

- [ ] **Step 4: Confirm visually, not just via the DOM numbers**

Screenshot the loaded page at 1920×889. Confirm: no visible scrollbar on the Overview tab's hero grid, the Spotlight tiles are still legible (not so compressed the champion name/score is unreadable), and the trend chart's dots/legend are still readable. This is the same visual bar the original zero-scroll tuning session held itself to.

- [ ] **Step 5: Commit**

```bash
git add vibecheck/web/style.css
git commit -m "fix(web): recompute zero-scroll grid budget for the new slim header"
```

---

### Task 6: Cross-viewport verification pass

**Files:** none (verification only — no code changes expected; if this step finds a bug, fix it in the relevant file from Tasks 1-5 and note it in the PR body per CLAUDE.md's pre-PR review gate)

**Interfaces:** none.

- [ ] **Step 1: 900×600 (the window minimum, per `vibecheck/window.py`)**

Resize to 900×600. Verify:
- Sidebar auto-collapses (width 56px) per the existing `<1000px` default in `initNavRail`.
- All 4 nav icons are visible and clickable icon-only.
- Clicking the Profile row opens `#profile-menu` fully **within the viewport** — no part of the 340px-wide, `max-height: 70vh` panel clipped above the top edge or off the right edge. This is the scenario Task 2 Step 4's `max-height` reduction (78vh → 70vh) exists for — confirm it actually worked at the real minimum, not just in theory.
- Header row doesn't wrap or overlap Filters/Notification Bell.

- [ ] **Step 2: 1920×889 (already covered by Task 5, re-confirm here as part of the full pass)**

Re-run Task 5 Step 2's DOM check + screenshot with all of Tasks 1–4's changes in place (Task 5 was verified in isolation; this step catches any interaction between it and the sidebar/header changes from other tasks).

- [ ] **Step 3: Sidebar expand/collapse — no jitter or overlap**

Toggle the collapse button 3-4 times in a row at 1920×889. Verify: `.app-content`'s `margin-left` transition (`.18s ease`) and `.sidebar`'s own `width` transition stay in sync — no frame where content is either overlapped by the sidebar or has a visible gap. Screenshot mid-transition if the two ever visually desync (would indicate the `.18s` durations need to match exactly, or a `transition-timing-function` mismatch).

- [ ] **Step 4: Click through all 4 nav tabs**

Verify `#page-title` updates to match each tab's `.nav-label` text exactly (Task 3 Step 1), and the corresponding `.tab` panel shows/hides correctly (unchanged `switchTab` logic, but confirm the visual result under the new shell).

- [ ] **Step 5: Notification drawer**

Open it without ever having opened the profile menu first. Verify `#notif-version` shows real text (not blank) — confirms Task 4's boot-time `checkUpdate()` call actually landed before the drawer was opened.

- [ ] **Step 6: `pre-commit` full run**

Run: `.venv\Scripts\pre-commit run --all-files`
Expected: all hooks pass (ruff doesn't touch `.html`/`.css`/`.js`, but this also re-confirms nothing in `vibecheck/*.py` was accidentally touched).

---

## Self-Review

**Spec coverage:**
- Flush 100vh sidebar, zero outer margin — Task 2 Step 2 (`.sidebar { position: fixed; top:0; left:0; bottom:0 }`, no margin/padding on the element itself).
- 56px / 220px collapsed/expanded — Task 2 Step 1 (`:root` tokens), Step 2 (`.sidebar`/`.sidebar.collapsed`).
- Brand icon + nav top, Profile/Settings/Collapse bottom — Task 1 Step 1 (HTML order), Task 2 Steps 2-4 (CSS).
- Slim header, page title left, Filters + Bell right — Task 1 Step 1, Task 2 Step 2, Task 3 Step 1.
- SyncedStatusPill/ToRateButton removed from header — already true before this plan (done in #86; verified via the `style.css:234-235` comment found during investigation). No task needed.
- Notification drawer consolidating pending + sync status — already existed (this plan only adds the version line and "Rate now →" copy tweak: Task 1 Step 1, Task 4).
- Main content offset, no overlap — Task 2 Steps 1-2 (`.app-content` margin-left), Task 3 Step 3 (JS keeps both in lockstep).
- Zero-scroll height constraint on `<main>` — Task 2 Step 2 (`main { height: calc(100vh - var(--header-h) - 14px); overflow-y: auto }`).

**Placeholder scan:** none found — every step above has literal code, not a description of code.

**Type/name consistency:** `#sidebar` (not `#tabs`) is the collapse-toggle target throughout Tasks 2–3; `#settings-btn`/`#notif-version`/`#page-title` are introduced once (Task 1) and consumed with matching IDs in Tasks 3–4. `renderNotifVersion()` is defined and called within Task 4; no other task references it.

**Gap found and added:** the original spec didn't say what happens to `#legal-footer` (outside the ASCII blueprint entirely) — Task 1 Step 1 makes an explicit, stated choice (moves it inside `.page-container`, preserving its existing independent `max-width: 90ch` centering, now relative to the sidebar-offset content area) rather than leaving it unaddressed.

---

## Product risk, most severe first

1. **Popover clipped or unreachable at the 900×600 minimum window** — the profile-menu now opens *upward* from a bottom-pinned trigger instead of downward from a header; if `max-height`/positioning is wrong, Settings/Update/Uninstall become unreachable on the smallest supported window. Mitigated: Task 2 Step 4's `70vh` cap plus Task 6 Step 1's explicit at-the-minimum check.
2. **Zero-scroll Overview grid silently regresses** — Task 2 changes the exact header height/padding numbers the already-shipped grid tuning (`fix/zero-scroll-grid-polish`) depends on. Mitigated: Task 5 re-derives and re-verifies those numbers live rather than assuming they still hold, plus Task 6 Step 2 re-confirms after all other tasks land.
3. **Outside-click dismiss breaks for the new Settings trigger**, leaving the profile menu unable to close (or closing itself immediately on open). Mitigated: Task 3 Step 2 explicitly matches the existing `e.stopPropagation()` pattern and documents *why* in a comment, so it isn't silently dropped in a future edit.
4. **Sidebar collapse/expand desyncs from the content offset** (sidebar width and `.app-content`'s margin-left animate independently, one uses `width`, the other `margin-left`) — a brief visual overlap or gap during the `.18s` transition. Mitigated: both use the same duration/easing (Task 2 Step 2), and Task 6 Step 3 checks it visually rather than assuming matching CSS values guarantee matching visual timing.

---

## Definition of Done (from the original spec, restated as checks)

- [ ] Sidebar sits 100% flush against top, left, and bottom window edges with zero outer margin (Task 2, verified Task 6 Step 1/2).
- [ ] Profile, Settings, and Collapse toggle pinned to the sidebar bottom (Task 1 Step 1).
- [ ] Header contains only page title (+ inline tagline), Filters, and Notification Bell (Task 1 Step 1, Task 2 Step 2).
- [ ] Squad Sync status and pending-rating access live only in the notification drawer, not duplicated elsewhere in the header (already true pre-plan; confirmed, not changed).
- [ ] Sidebar expand/collapse shifts main content cleanly, no jitter/overlap (Task 3 Step 3, verified Task 6 Step 3).

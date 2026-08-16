# Overview Page Redesign (Vibe-First Tiles) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Overview tab around four vibe-first sections — lifetime
totals, a 5-tile category-leader "spotlight," a compact ARAM God widget, and
a re-skinned vibe trend with real champion portraits — replacing the current
generic fun-facts cards and Copium Tracking chart.

**Architecture:** Pure frontend page (new aggregation + render functions in
`vibecheck/web/app.js`, new markup in `vibecheck/web/index.html`, new scoped
CSS in `vibecheck/web/style.css`), plus one small backend addition: a
loading-screen splash-art cache mirroring the existing champion-icon cache
(`vibecheck/ddragon.py` + a new `/api/champ-splash/{name}` route in
`vibecheck/dashboard.py`), since the design needs full splash art that no
endpoint serves today. No schema changes.

**Tech Stack:** FastAPI (existing `dashboard.py`), vanilla JS (existing
`app.js`, no framework/build step), plain CSS. Backend tests via
`fastapi.testclient.TestClient`, following `tests/achievement_test.py`'s
standalone-script pattern (no pytest dependency).

## Global Constraints

- No schema or SQL changes — every value this page shows already exists on
  `games` or comes from the already-shipped `/api/aram-god`.
- Dashboard stays localhost-only and must not fail if offline: splash art is
  served **only from the local cache** (never fetched on the request path),
  exactly like the existing `/api/champ-icon/{name}` route — a cache miss is
  a 404, and the frontend must tolerate a missing image without breaking
  layout.
- No 3D transforms / flip / `backdrop-filter` anywhere on this page — the
  design explicitly moved away from a flip interaction because a live-blurred
  background on a 3D-transformed element was the cause of a real perf
  regression during design review. Hover effects here use only `filter` and
  `opacity` transitions on non-transformed (or 2D-`scale`-only) elements.
- New CSS variables for the BRAND.md palette are scoped to `#tab-overview`
  only (prefixed `--vc-*`), not written into the shared `:root` block —
  every other tab still uses the existing `--gold`/`--surface`/etc. tokens
  until #57 does the full palette migration. Don't touch those tokens here.
- This plan does not touch the Champions tab's existing full ARAM God grid
  (`#aram-god` inside `#tab-champions`) or the champion tier list/scatter —
  those are out of scope; a *second*, compact ARAM God widget is added to
  Overview, reusing the same cached fetch.
- Conventional Commits on every commit (enforced by a local hook).
- `.venv\Scripts\ruff check . --fix` and `.venv\Scripts\ruff format .` must
  be clean before each Python commit.
- This project has **no JavaScript test harness** — `web/app.js` has zero
  automated tests today. Frontend tasks below are verified by hand (dev
  server + browser devtools), exactly as documented in
  `docs/superpowers/specs/2026-08-10-overview-redesign-design.md`'s own
  Testing section. Don't invent a JS test framework as part of this plan.

---

### Task 1: Champion splash-art caching (backend)

**Files:**
- Modify: `vibecheck/ddragon.py` (add `SPLASH_DIR`, `splash_path`,
  `fetch_splash`, `warm_splash`, alongside the existing icon functions)
- Test: `tests/ddragon_splash_test.py` (new)

**Interfaces:**
- Consumes: `ddragon._key_for(man, name, classic)`, `ddragon.manifest()`,
  `ddragon._get(url)` — all already exist, reused verbatim.
- Produces: `ddragon.splash_path(name: str, classic: bool = False) -> Path | None`,
  `ddragon.fetch_splash(name: str, classic: bool = False) -> Path | None`,
  `ddragon.warm_splash(picks) -> int` — same signatures as the existing
  `icon_path`/`fetch_icon`/`warm`, so Task 2 can call them identically.

- [ ] **Step 1: Add the splash-art functions to `ddragon.py`**

Add `SPLASH_DIR = CACHE_DIR / "splash"` next to the existing `ICON_DIR = CACHE_DIR / "icons"` (around line 41).

Add these three functions after `fetch_icon` (after line 202), before `warm`:

```python
def splash_path(name: str, classic: bool = False) -> Path | None:
    """The on-disk loading-screen splash for a champion, or None if it isn't
    cached yet. Same disk-only contract as icon_path — safe to call per tile
    while rendering; downloading is fetch_splash's job, off the request path.
    """
    man = manifest(refresh=False)
    if not man:
        return None
    key = _key_for(man, name, classic)
    if not key:
        return None
    path = SPLASH_DIR / f"{key}_0.jpg"
    return path if path.exists() else None


def fetch_splash(name: str, classic: bool = False) -> Path | None:
    """Download one champion's loading-screen splash if it isn't cached.

    Unlike the square icon, loading art lives under a version-independent
    CDN path (no /cdn/{version}/ segment) — Data Dragon serves the current
    splash for every champion at the same URL regardless of patch.
    """
    man = manifest()
    if not man:
        return None
    key = _key_for(man, name, classic)
    if not key or key in _missing_splash:
        return None
    path = SPLASH_DIR / f"{key}_0.jpg"
    if path.exists():
        return path

    url = f"https://{ALLOWED_HOST}/cdn/img/champion/loading/{key}_0.jpg"
    try:
        with _get(url) as resp:
            data = resp.read()
        SPLASH_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path
    except Exception as exc:
        _missing_splash.add(key)
        log.debug("Could not fetch splash for %s: %s", name, exc)
        return None


def warm_splash(picks) -> int:
    """Pre-download splash art for the champions someone actually plays.

    Mirrors warm() exactly — see its docstring for why picks is (name,
    classic) pairs and why this runs off the request path.
    """
    added = 0
    try:
        for name, classic in {(n, bool(c)) for n, c in picks if n}:
            if splash_path(name, classic):
                continue
            if fetch_splash(name, classic):
                added += 1
        if added:
            log.info("Cached %d champion splash(es)", added)
    except Exception:
        log.debug("Champion splash warm-up stopped early", exc_info=True)
    return added
```

Add `_missing_splash: set[str] = set()` next to the existing `_missing: set[str] = set()` (around line 55) — a separate set, since a champion can fail the splash fetch independently of the icon fetch (they're different CDN paths).

- [ ] **Step 2: Write the test**

Create `tests/ddragon_splash_test.py`:

```python
"""Verify champion splash-art caching (loading-screen crops), mirroring the
existing icon cache. No network: manifest and cache dir are injected directly,
same approach as the rest of this test suite avoids hitting Data Dragon.

Run: .venv\\Scripts\\python tests\\ddragon_splash_test.py
"""

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from vibecheck import ddragon  # noqa: E402

FAKE_MANIFEST = {
    "version": "14.24.1",
    "fetched_at": 1e12,
    "names": {"jinx": "Jinx", "drmundo": "DrMundo"},
}


def _reset(tmp_path: Path):
    ddragon._manifest = dict(FAKE_MANIFEST)
    ddragon._failed_at = 0.0
    ddragon._missing_splash = set()
    ddragon.CACHE_DIR = tmp_path
    ddragon.SPLASH_DIR = tmp_path / "splash"
    ddragon.MANIFEST_PATH = tmp_path / "manifest.json"


def test_splash_path_is_none_when_not_cached(root):
    _reset(root)
    assert ddragon.splash_path("Jinx") is None


def test_splash_path_finds_a_pre_cached_file(root):
    _reset(root)
    ddragon.SPLASH_DIR.mkdir(parents=True)
    (ddragon.SPLASH_DIR / "Jinx_0.jpg").write_bytes(b"fake-jpeg-bytes")
    path = ddragon.splash_path("Jinx")
    assert path is not None and path.name == "Jinx_0.jpg", path


def test_splash_path_handles_display_name_punctuation(root):
    """'Dr. Mundo' must resolve the same DrMundo key the icon cache uses."""
    _reset(root)
    ddragon.SPLASH_DIR.mkdir(parents=True)
    (ddragon.SPLASH_DIR / "DrMundo_0.jpg").write_bytes(b"fake-jpeg-bytes")
    path = ddragon.splash_path("Dr. Mundo")
    assert path is not None and path.name == "DrMundo_0.jpg", path


def test_splash_path_is_none_for_unknown_champion(root):
    _reset(root)
    assert ddragon.splash_path("NotAChampion") is None


def test_fetch_splash_refuses_when_no_manifest(root):
    _reset(root)
    ddragon._manifest = None
    ddragon._failed_at = 1e12  # inside the failure cooldown, so no network attempt
    assert ddragon.fetch_splash("Jinx") is None


def test_warm_splash_skips_already_cached_champions(root):
    _reset(root)
    ddragon.SPLASH_DIR.mkdir(parents=True)
    (ddragon.SPLASH_DIR / "Jinx_0.jpg").write_bytes(b"fake-jpeg-bytes")
    # DrMundo isn't cached and there's no network here (cooldown forces
    # fetch_splash's internal fetch to no-op via manifest(refresh=True)
    # failing fast — accept either 0 or a network attempt is skipped by CI
    # having no network), so this only asserts the *cached* one is skipped.
    added = ddragon.warm_splash([("Jinx", False)])
    assert added == 0, "already-cached champion must not count as newly added"


TESTS = [
    test_splash_path_is_none_when_not_cached,
    test_splash_path_finds_a_pre_cached_file,
    test_splash_path_handles_display_name_punctuation,
    test_splash_path_is_none_for_unknown_champion,
    test_fetch_splash_refuses_when_no_manifest,
    test_warm_splash_skips_already_cached_champions,
]


def main():
    for test in TESTS:
        root = Path(tempfile.mkdtemp(prefix="vibecheck-splash-"))
        try:
            test(root)
            print(f"  ok  {test.__name__}")
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)
    print("ddragon splash test OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv\Scripts\python tests\ddragon_splash_test.py`
Expected: `AttributeError: module 'vibecheck.ddragon' has no attribute 'SPLASH_DIR'` (or `splash_path`) — the functions don't exist yet.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv\Scripts\python tests\ddragon_splash_test.py`
Expected: all six tests print `ok` and the script prints `ddragon splash test OK`.

- [ ] **Step 5: Lint and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
git add vibecheck/ddragon.py tests/ddragon_splash_test.py
git commit -m "feat(ddragon): cache champion loading-screen splash art"
```

---

### Task 2: `/api/champ-splash/{name}` endpoint

**Files:**
- Modify: `vibecheck/dashboard.py` (new route + background warm helper, near the existing `champ_icon`/`_warm_icons`)
- Test: `tests/dashboard_splash_test.py` (new)

**Interfaces:**
- Consumes: `ddragon.splash_path`, `ddragon.warm_splash` (Task 1)
- Produces: `GET /api/champ-splash/{name}?classic=` — 200 with the cached
  JPEG, or 404 if not cached (never blocks on network, matching
  `/api/champ-icon`).

- [ ] **Step 1: Write the failing test**

Create `tests/dashboard_splash_test.py`:

```python
"""Verify /api/champ-splash never blocks on network — served from cache only,
404 on a miss, exactly like /api/champ-icon.

Run: .venv\\Scripts\\python tests\\dashboard_splash_test.py
"""

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from vibecheck import ddragon  # noqa: E402
from vibecheck.dashboard import create_app  # noqa: E402
from vibecheck.store import GameStore  # noqa: E402


def api_for(store: GameStore) -> TestClient:
    return TestClient(create_app(store), base_url="http://127.0.0.1")


def test_missing_splash_404s_without_blocking(root):
    store = GameStore(root / "t.sqlite3")
    ddragon._manifest = None  # no manifest cached — splash_path returns None fast
    r = api_for(store).get("/api/champ-splash/Jinx")
    assert r.status_code == 404, r.status_code
    store.close()


def test_cached_splash_is_served(root):
    store = GameStore(root / "t2.sqlite3")
    ddragon._manifest = {"version": "14.24.1", "fetched_at": 1e12, "names": {"jinx": "Jinx"}}
    ddragon.CACHE_DIR = root / "ddcache"
    ddragon.SPLASH_DIR = ddragon.CACHE_DIR / "splash"
    ddragon.SPLASH_DIR.mkdir(parents=True)
    (ddragon.SPLASH_DIR / "Jinx_0.jpg").write_bytes(b"fake-jpeg-bytes")

    r = api_for(store).get("/api/champ-splash/Jinx")
    assert r.status_code == 200, r.status_code
    assert r.content == b"fake-jpeg-bytes"
    store.close()


TESTS = [
    test_missing_splash_404s_without_blocking,
    test_cached_splash_is_served,
]


def main():
    for test in TESTS:
        root = Path(tempfile.mkdtemp(prefix="vibecheck-dashsplash-"))
        try:
            test(root)
            print(f"  ok  {test.__name__}")
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)
    print("dashboard splash test OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python tests\dashboard_splash_test.py`
Expected: `404` becomes a connection/route error — `/api/champ-splash/Jinx` doesn't exist yet (test framework reports a 404 from FastAPI's default "no route" handler is actually indistinguishable from ours by status code alone, so instead expect the *second* test to fail: `AssertionError: 404` when 200 was expected, since nothing serves the file yet).

- [ ] **Step 3: Add the route to `dashboard.py`**

Add immediately after the existing `champ_icon` route and its `_warm_icons` helper (after line 236, before `@app.get("/api/aram-god")`):

```python
@app.get("/api/champ-splash/{name}")
def champ_splash(name: str, classic: bool = False):
    """A champion's loading-screen splash, served from the local cache
    only — same never-block-on-network contract as champ_icon."""
    path = ddragon.splash_path(name, classic=classic)
    if not path:
        _warm_splashes()
        raise HTTPException(404)
    return FileResponse(path)


def _warm_splashes() -> None:
    """Download any splash art the store needs but the cache doesn't have.

    Mirrors _warm_icons exactly, including the same guard-flag caveat:
    it clears when the pass finishes rather than latching permanently.
    """
    nonlocal _warming_splash
    with _warm_lock:
        if _warming_splash:
            return
        _warming_splash = True

    def worker():
        nonlocal _warming_splash
        try:
            ddragon.warm_splash(
                (g["champion"], capture.is_classic(g.get("queue_id"), g.get("queue_type")))
                for g in store.games_with_details()
            )
        finally:
            with _warm_lock:
                _warming_splash = False

    threading.Thread(target=worker, name="champ-splashes", daemon=True).start()
```

Add `_warming_splash = False` next to the existing `_warming = False` declaration (search for where `_warming` is initialized near the top of `create_app`, alongside `_warm_lock`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv\Scripts\python tests\dashboard_splash_test.py`
Expected: both tests print `ok` and the script prints `dashboard splash test OK`.

- [ ] **Step 5: Run the existing suites to check for regressions**

```powershell
.venv\Scripts\python tests\smoke_test.py
.venv\Scripts\python tests\achievement_test.py
```
Expected: both print their `OK` line.

- [ ] **Step 6: Lint and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
git add vibecheck/dashboard.py tests/dashboard_splash_test.py
git commit -m "feat(dashboard): serve champion splash art from the local cache"
```

---

### Task 3: Per-champion totals + category-leader aggregation (frontend logic)

**Files:**
- Modify: `vibecheck/web/app.js` (new pure functions, no rendering yet)

**Interfaces:**
- Consumes: the enriched game objects already produced by `enrich()`
  (`champion_key`, `kills`, `deaths`, `assists`, `duration_seconds`,
  `fun_score`, `rated`, `champion`, `classic`) and the existing `MIN_N`.
- Produces:
  - `championTotals(games) -> Array<{key, name, classic, games, n, kills, deaths, assists, seconds, avgFun}>`
  - `categoryLeaders(rows) -> {vibe, kills, deaths, assists, hours}` where
    each value is one row from `championTotals` (or `null` if no row
    qualifies — `vibe` requires `n >= MIN_N`, the others just need `rows.length`).
  - `lifetimeTotals(games) -> {kills, deaths, assists, seconds, since}` where
    `since` is the earliest `g.day` in `games` (or `null` if `games` is empty).

- [ ] **Step 1: Add the functions to `app.js`**

Add directly after the existing `aggregate()` function (after line 192, before the `/* ---------------- chart helpers ---------------- */` comment):

```javascript
/* Per-champion career totals (raw sums, not averages) — feeds the Overview
   lifetime strip and spotlight tiles. Separate from aggregate() rather than
   extending it: aggregate() is shared by every tab's fun/winrate charts and
   deliberately stays narrow, while these sums (kills/deaths/assists/seconds)
   are Overview-specific. */
function championTotals(games) {
  const acc = new Map();
  for (const g of games) {
    const key = g.champion_key;
    if (!key) continue;
    const a = acc.get(key) || {
      key, name: g.champion, classic: g.classic, games: 0, n: 0,
      kills: 0, deaths: 0, assists: 0, seconds: 0, funSum: 0, funN: 0,
    };
    a.games += 1;
    a.kills += g.kills || 0;
    a.deaths += g.deaths || 0;
    a.assists += g.assists || 0;
    a.seconds += g.duration_seconds || 0;
    if (g.rated) { a.funSum += g.fun_score; a.funN += 1; }
    acc.set(key, a);
  }
  return [...acc.values()].map((a) => ({
    key: a.key, name: a.name, classic: a.classic, games: a.games, n: a.funN,
    kills: a.kills, deaths: a.deaths, assists: a.assists, seconds: a.seconds,
    avgFun: a.funN ? a.funSum / a.funN : null,
  }));
}

/* One champion per category — "spotlight" tiles pick the max, "kills"/etc.
   need no MIN_N gate (a raw total, not an average), but "vibe" does: an
   average from one lucky game isn't a career highlight, it's noise. Matches
   the MIN_N threshold the existing "Certified Banger" card already uses. */
function categoryLeaders(rows) {
  const top = (fn) => rows.length ? rows.reduce((best, r) => (fn(r) > fn(best) ? r : best)) : null;
  const vibeRows = rows.filter((r) => r.avgFun != null && r.n >= MIN_N);
  return {
    vibe: vibeRows.length ? vibeRows.reduce((best, r) => (r.avgFun > best.avgFun ? r : best)) : null,
    kills: top((r) => r.kills),
    deaths: top((r) => r.deaths),
    assists: top((r) => r.assists),
    hours: top((r) => r.seconds),
  };
}

/* Career sums across every champion, plus the earliest game's day for the
   "since <date>" caption. Deliberately computed from whatever `games` this
   is called with (the filtered set, same as the rest of Overview) rather
   than always ALL — consistent with how "Certified Banger" et al. already
   respond to the filter bar; only ARAM God is the documented exception. */
function lifetimeTotals(games) {
  if (!games.length) return { kills: 0, deaths: 0, assists: 0, seconds: 0, since: null };
  let kills = 0, deaths = 0, assists = 0, seconds = 0, since = games[0].day;
  for (const g of games) {
    kills += g.kills || 0;
    deaths += g.deaths || 0;
    assists += g.assists || 0;
    seconds += g.duration_seconds || 0;
    if (g.day < since) since = g.day;
  }
  return { kills, deaths, assists, seconds, since };
}

function champSplashUrl(name, classic) {
  if (!name) return null;
  return `/api/champ-splash/${encodeURIComponent(name)}${classic ? "?classic=1" : ""}`;
}

function formatHours(seconds) {
  return `${Math.round(seconds / 3600)}h`;
}

function formatSince(day) {
  if (!day) return "no games yet";
  const d = new Date(day);
  return `since ${d.toLocaleString("en-US", { month: "short", year: "numeric" })}`;
}
```

- [ ] **Step 2: Verify manually in the browser console**

Run: `.venv\Scripts\python -m vibecheck`, open the dashboard, open devtools
console on the Overview tab, and run:

```javascript
championTotals(ALL).slice(0, 3)
```

Expected: an array of objects each with `key`, `kills`, `deaths`, `assists`,
`seconds`, `avgFun` populated with real numbers matching what you'd hand-sum
from a couple of known games. Then run:

```javascript
categoryLeaders(championTotals(ALL))
```

Expected: an object with `vibe`, `kills`, `deaths`, `assists`, `hours` keys,
each either `null` (fresh install / under `MIN_N`) or a row from the first
call. Then run:

```javascript
lifetimeTotals(ALL)
```

Expected: `{kills, deaths, assists, seconds, since}` with `since` a
`YYYY-MM-DD` string matching your earliest captured game.

- [ ] **Step 3: Commit**

```powershell
git add vibecheck/web/app.js
git commit -m "feat(web): add per-champion career totals and category-leader aggregation"
```

---

### Task 4: Lifetime totals strip

**Files:**
- Modify: `vibecheck/web/index.html` (replace `#fun-facts` block inside `#tab-overview`)
- Modify: `vibecheck/web/app.js` (new `renderLifetimeTotals`, wired into `renderOverview`)
- Modify: `vibecheck/web/style.css` (new `.ov-*` rules + scoped `--vc-*` tokens)

**Interfaces:**
- Consumes: `lifetimeTotals`, `champSplashUrl`, `formatHours`, `formatSince`
  (Task 3), and a `leaders` object (`categoryLeaders`'s return shape)
  computed once by `renderOverview` and passed in — Task 5's spotlight needs
  the exact same `categoryLeaders(championTotals(games))` result, so it's
  computed once per render and shared rather than duplicated.
- Produces: `renderLifetimeTotals(games, leaders)`, called from `renderOverview`

- [ ] **Step 1: Replace the Overview tab markup shell in `index.html`**

Replace lines 163–169 (the whole `#tab-overview` div) with:

```html
  <div id="tab-overview" class="tab">
    <div id="ov-totals" class="ov-totals"></div>
    <div class="ov-section-label">Spotlight</div>
    <div id="ov-spotlight" class="ov-spotlight"></div>
    <div id="ov-aram" class="ov-aram"></div>
    <div class="panel">
      <h2>Vibe trend <span class="hint">who's been driving the swings</span></h2>
      <div id="ov-trend" class="ov-trend"></div>
    </div>
  </div>
```

(The old `#fun-facts` cards and `#chart-trend` canvas are gone — the trend is
rebuilt in Task 7, not as a Chart.js canvas.)

- [ ] **Step 2: Add the CSS tokens and totals-strip styles to `style.css`**

Append to the end of `style.css`:

```css
/* ---------- Overview redesign: scoped BRAND.md tokens (§57 hasn't landed
   globally yet, so these stay local to #tab-overview rather than touching
   the shared :root palette every other tab still uses) ---------- */
#tab-overview {
  --vc-bg-surface: #161B22;
  --vc-bg-surface-hover: #1F242D;
  --vc-border: #2A303C;
  --vc-gold: #E5A93C;
  --vc-gold-hl: #F3BA52;
  --vc-text-main: #F3F4F6;
  --vc-text-muted: #8B949E;
  --vc-t1: #EF4444; --vc-t2: #F97316; --vc-t3: #EAB308; --vc-t4: #10B981; --vc-t5: #8B5CF6;
}

.ov-section-label {
  font-size: 12px; letter-spacing: 1.5px; color: var(--vc-text-muted);
  text-transform: uppercase; margin: 26px 0 12px;
}

.ov-totals { display: flex; gap: 14px; flex-wrap: wrap; }
.ov-tcard {
  flex: 1 1 160px; position: relative; height: 96px; border-radius: 12px;
  overflow: hidden; border: 1px solid var(--vc-border); background: var(--vc-bg-surface);
}
.ov-tcard .ov-splash-img {
  position: absolute; inset: -10px; width: calc(100% + 20px); height: calc(100% + 20px);
  object-fit: cover; object-position: center 20%;
  filter: blur(6px) brightness(.4) saturate(1.1); transform: scale(1.15);
}
.ov-tcard .ov-scrim {
  position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(13,16,23,.55), rgba(13,16,23,.85));
}
.ov-tcard .ov-content {
  position: relative; padding: 11px 13px; height: 100%;
  display: flex; flex-direction: column; justify-content: space-between;
}
.ov-tcard svg { color: var(--vc-gold-hl); }
.ov-tcard .ov-label {
  font-size: 10px; color: var(--vc-text-muted); text-transform: uppercase; letter-spacing: .5px;
}
.ov-tcard .ov-value { font-family: "JetBrains Mono", "Consolas", monospace; font-size: 21px; color: var(--vc-text-main); }
.ov-tcard .ov-since { font-size: 10px; color: var(--vc-text-muted); }
```

- [ ] **Step 3: Add `renderLifetimeTotals` to `app.js`**

Add after the new Task 3 functions, before `/* ---------------- chart helpers ---------------- */`:

```javascript
const OV_ICONS = {
  kills: '<path d="M4 20L14 10M14 10L11 7M14 10L17 13M20 4L10 14M10 14L13 17M10 14L7 11"/>',
  deaths: '<path d="M7 21V13a5 5 0 0110 0v8M4 21h16"/>',
  assists: '<circle cx="8" cy="12" r="4"/><circle cx="16" cy="12" r="4"/>',
  hours: '<path d="M12 3a9 9 0 100 18 9 9 0 000-18z"/><path d="M12 7v5l4 2"/>',
};

function ovIcon(kind) {
  return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${OV_ICONS[kind]}</svg>`;
}

function ovSplashImg(leaderRow) {
  if (!leaderRow) return "";
  const url = champSplashUrl(leaderRow.name, leaderRow.classic);
  return `<img class="ov-splash-img" src="${escapeAttr(url)}" alt="" loading="lazy" data-on-error="remove">`;
}

function renderLifetimeTotals(games, leaders) {
  const totals = lifetimeTotals(games);
  const since = formatSince(totals.since);
  const card = (kind, label, value, leaderRow) => `
    <div class="ov-tcard">
      ${ovSplashImg(leaderRow)}
      <div class="ov-scrim"></div>
      <div class="ov-content">
        <div>${ovIcon(kind)}<span class="ov-label">${label}</span></div>
        <div><div class="ov-value">${value}</div><div class="ov-since">${since}</div></div>
      </div>
    </div>`;
  document.getElementById("ov-totals").innerHTML =
    card("kills", "Kills", totals.kills.toLocaleString(), leaders.kills) +
    card("deaths", "Deaths", totals.deaths.toLocaleString(), leaders.deaths) +
    card("assists", "Assists", totals.assists.toLocaleString(), leaders.assists) +
    card("hours", "Time played", formatHours(totals.seconds), leaders.hours);
}
```

- [ ] **Step 4: Wire it into `renderOverview` and delete the old fun-facts code**

In `renderOverview(games)` (starting line 398), delete the entire body (the
`facts`/`card()` block, the `champs`/`bigChamps` block, the squad-buff
`card()` call, the coverage `card()` call, and the old rolling-average
`chart-trend` block — everything from `const rated = games.filter(...)`
through the end of the `Chart(document.getElementById("chart-trend")...)`
call) and replace the whole function body with:

```javascript
function renderOverview(games) {
  // Computed once and shared: Task 5's spotlight needs this exact same
  // result, and championTotals()/categoryLeaders() aren't free to redo
  // twice on every filter-bar keystroke.
  const leaders = categoryLeaders(championTotals(games));
  renderLifetimeTotals(games, leaders);
  // renderSpotlight(games, leaders) — Task 5
  // renderAramGodCompact() — Task 6
  // renderVibeTrend(games) — Task 7
}
```

(The `card()` helper function itself, defined just above `renderOverview`,
is no longer called by anything after this edit — leave it in place for now;
Task 8's final pass removes it if nothing else uses it.)

- [ ] **Step 5: Verify manually**

Run: `.venv\Scripts\python -m vibecheck`, open the dashboard on the Overview
tab.

Expected: four cards in a row — Kills, Deaths, Assists, Time played — each
with a big number and a "since `<Mon YYYY>`" caption. On a fresh install
with zero games, all four show `0` / `0h` and "no games yet" without
throwing a console error. Background art may be blank (no splash cached
yet) — the card must still be fully readable (dark background, no broken-
image icon) per the `data-on-error="remove"` fallback.

- [ ] **Step 6: Commit**

```powershell
git add vibecheck/web/index.html vibecheck/web/app.js vibecheck/web/style.css
git commit -m "feat(web): add the lifetime totals strip to Overview"
```

---

### Task 5: Spotlight (5 category-leader tiles, hover-blur)

**Files:**
- Modify: `vibecheck/web/app.js` (new `renderSpotlight`, wired into `renderOverview`)
- Modify: `vibecheck/web/style.css` (new `.ov-spotlight`/`.ov-stile` rules)

**Interfaces:**
- Consumes: `champSplashUrl`, `formatHours` (Task 3), `GRADES` (existing),
  and the same `leaders` object `renderOverview` now computes once and
  passes to `renderLifetimeTotals` too (Task 4).
- Produces: `renderSpotlight(games, leaders)`, called from `renderOverview`.

- [ ] **Step 1: Add the CSS**

Append to `style.css`:

```css
.ov-spotlight { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; }
.ov-stile {
  aspect-ratio: 3 / 4; position: relative; border-radius: 12px; overflow: hidden;
  border: 1px solid var(--vc-border); background: var(--vc-bg-surface); cursor: default;
}
.ov-stile .ov-splash-img {
  position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: center 15%;
  transition: filter .22s ease-out, transform .22s ease-out;
}
.ov-stile:hover .ov-splash-img { filter: blur(7px) brightness(.42) saturate(1.1); transform: scale(1.06); }
.ov-stile .ov-scrim {
  position: absolute; inset: 0; transition: opacity .22s ease-out;
  background: linear-gradient(180deg, rgba(13,16,23,0) 55%, rgba(13,16,23,.92) 100%);
}
.ov-stile:hover .ov-scrim { opacity: 0; }
.ov-stile .ov-cat-pill {
  position: absolute; top: 8px; left: 8px; display: flex; align-items: center; gap: 5px;
  background: rgba(13,16,23,.6); border-radius: 6px; padding: 3px 7px; font-size: 9px;
  text-transform: uppercase; letter-spacing: .4px; color: var(--vc-gold-hl); z-index: 1;
}
.ov-stile .ov-cat-pill svg { width: 11px; height: 11px; }
.ov-stile .ov-headline {
  position: absolute; left: 0; right: 0; bottom: 0; padding: 10px; transition: opacity .18s;
}
.ov-stile:hover .ov-headline { opacity: 0; }
.ov-stile .ov-headline .ov-champ-name {
  font-size: 14px; font-weight: 700; text-shadow: 0 1px 2px rgba(0,0,0,.6); color: var(--vc-text-main);
}
.ov-stile .ov-headline .ov-stat-big {
  font-family: "JetBrains Mono", "Consolas", monospace; font-size: 18px; color: var(--vc-gold-hl); font-weight: 700;
}
.ov-stile .ov-overlay {
  position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 5px; opacity: 0; transition: opacity .22s ease-out .05s;
  padding: 10px; text-align: center;
}
.ov-stile:hover .ov-overlay { opacity: 1; }
.ov-stile .ov-overlay .ov-name { font-size: 13px; font-weight: 700; color: var(--vc-text-main); margin-bottom: 2px; }
.ov-stile .ov-overlay .ov-games { font-size: 10px; color: var(--vc-text-muted); margin-bottom: 6px; }
.ov-stile .ov-overlay .ov-grow { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 10px; width: 100%; }
.ov-stile .ov-overlay .ov-g { font-size: 11px; color: var(--vc-text-muted); }
.ov-stile .ov-overlay .ov-g b {
  font-family: "JetBrains Mono", "Consolas", monospace; display: block; font-size: 14px; color: var(--vc-text-main); font-weight: 700;
}
.ov-stile .ov-overlay .ov-vibe-row { margin-top: 6px; padding: 3px 12px; border-radius: 14px; font-size: 12px; font-weight: 700; }
.ov-tier5 { background: rgba(139,92,246,.35); color: #c9b3ff; }
.ov-tier4 { background: rgba(16,185,129,.35); color: #7fe3bf; }
.ov-tier3 { background: rgba(234,179,8,.35); color: #f5da85; }
.ov-tier2 { background: rgba(249,115,22,.35); color: #ffcda3; }
.ov-tier1 { background: rgba(239,68,68,.35); color: #ffaba3; }
.ov-empty-note { color: var(--vc-text-muted); font-size: 12.5px; }
```

- [ ] **Step 2: Add `renderSpotlight` to `app.js`**

Add after `renderLifetimeTotals`:

```javascript
const OV_TIER_CLASS = { 1: "ov-tier1", 2: "ov-tier2", 3: "ov-tier3", 4: "ov-tier4", 5: "ov-tier5" };
const OV_CAT_ICON = {
  vibe: '<path d="M12 2l2.5 5.5L20 8l-4.5 4 1.5 6L12 15l-5 3 1.5-6L4 8l5.5-.5z"/>',
  kills: OV_ICONS.kills, deaths: OV_ICONS.deaths, assists: OV_ICONS.assists, hours: OV_ICONS.hours,
};
const OV_CAT_LABEL = { vibe: "Best vibe", kills: "Most kills", deaths: "Most deaths", assists: "Most assists", hours: "Most hours" };
const OV_CAT_HEADLINE = {
  vibe: (r) => r.avgFun.toFixed(1),
  kills: (r) => String(r.kills),
  deaths: (r) => String(r.deaths),
  assists: (r) => String(r.assists),
  hours: (r) => formatHours(r.seconds),
};

function ovSpotlightTile(cat, row) {
  if (!row) {
    return `<div class="ov-stile"><div class="ov-overlay" style="opacity:1"><div class="ov-empty-note">not enough data yet</div></div></div>`;
  }
  const tierRound = row.avgFun != null ? Math.round(row.avgFun) : null;
  const tierClass = tierRound ? OV_TIER_CLASS[tierRound] : "ov-tier3";
  const vibeLabel = tierRound ? `${row.avgFun.toFixed(2)} · ${GRADES[tierRound]}` : "not enough rated games";
  return `
    <div class="ov-stile">
      <img class="ov-splash-img" src="${escapeAttr(champSplashUrl(row.name, row.classic))}" alt="" loading="lazy" data-on-error="remove">
      <div class="ov-scrim"></div>
      <div class="ov-cat-pill"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${OV_CAT_ICON[cat]}</svg>${OV_CAT_LABEL[cat]}</div>
      <div class="ov-headline">
        <div class="ov-champ-name">${escapeAttr(row.key)}</div>
        <div class="ov-stat-big">${OV_CAT_HEADLINE[cat](row)}</div>
      </div>
      <div class="ov-overlay">
        <div class="ov-name">${escapeAttr(row.key)}</div>
        <div class="ov-games">${row.games} game${row.games === 1 ? "" : "s"}</div>
        <div class="ov-grow">
          <div class="ov-g"><b>${row.kills}</b>Kills</div>
          <div class="ov-g"><b>${row.deaths}</b>Deaths</div>
          <div class="ov-g"><b>${row.assists}</b>Assists</div>
          <div class="ov-g"><b>${formatHours(row.seconds)}</b>Played</div>
        </div>
        <div class="ov-vibe-row ${tierClass}">${vibeLabel}</div>
      </div>
    </div>`;
}

function renderSpotlight(games, leaders) {
  document.getElementById("ov-spotlight").innerHTML =
    ["vibe", "kills", "deaths", "assists", "hours"].map((cat) => ovSpotlightTile(cat, leaders[cat])).join("");
}
```

- [ ] **Step 3: Wire it into `renderOverview`**

Replace the `// renderSpotlight(games) — Task 5` comment (added in Task 4,
Step 4) with an actual call:

```javascript
function renderOverview(games) {
  const leaders = categoryLeaders(championTotals(games));
  renderLifetimeTotals(games, leaders);
  renderSpotlight(games, leaders);
  // renderAramGodCompact() — Task 6
  // renderVibeTrend(games) — Task 7
}
```

- [ ] **Step 4: Verify manually**

Run: `.venv\Scripts\python -m vibecheck`, open the Overview tab.

Expected: five tiles — Best vibe, Most kills, Most deaths, Most assists,
Most hours — each showing a champion name and headline number at idle, and
on mouse-hover the art blurs in place (no flip, no layout jump) and a
centered panel fades in showing kills/deaths/assists/played/vibe for that
champion. With fewer than `MIN_N` rated games, the "Best vibe" tile shows
"not enough data yet" instead of a champion. Confirm in devtools that
hovering does **not** trigger any `transform: rotateY` or
`backdrop-filter` — only `filter`/`opacity`/`scale` per the global
constraint.

- [ ] **Step 5: Commit**

```powershell
git add vibecheck/web/app.js vibecheck/web/style.css
git commit -m "feat(web): add the 5-tile spotlight to Overview"
```

---

### Task 6: Compact ARAM God widget on Overview

**Files:**
- Modify: `vibecheck/web/app.js` (refactor `renderAramGod`'s data-fetch out
  from its grid-drawing, add `renderAramGodCompact`)
- Modify: `vibecheck/web/style.css` (new `.ov-aram` rules)

**Interfaces:**
- Consumes: the existing `ARAM_GOD`/`ARAM_GOD_PENDING` module-level cache
  and `/api/aram-god` shape (`tracked`, `completed`, `total`).
- Produces: `fetchAramGod() -> Promise<object>` (extracted from
  `renderAramGod`), `renderAramGodCompact()`, called from `renderOverview`.
  `renderAramGod()` (the full grid on the Champions tab) keeps its existing
  name and behavior, now built on top of `fetchAramGod()`.

- [ ] **Step 1: Extract the fetch from `renderAramGod`**

Replace the fetch block inside `renderAramGod` (lines 475–487) — currently:

```javascript
  if (!ARAM_GOD) {
    try {
      // renderChampions runs on every filter keystroke; without this the same
      // request goes out several times before the first one lands.
      ARAM_GOD_PENDING = ARAM_GOD_PENDING || fetchJSON("/api/aram-god");
      ARAM_GOD = await ARAM_GOD_PENDING;
    } catch {
      host.innerHTML = '<div class="empty-note">Couldn\'t read your ARAM God progress.</div>';
      return;
    } finally {
      ARAM_GOD_PENDING = null;
    }
  }
```

with a call to a new shared helper:

```javascript
  try {
    if (!ARAM_GOD) ARAM_GOD = await fetchAramGod();
  } catch {
    host.innerHTML = '<div class="empty-note">Couldn\'t read your ARAM God progress.</div>';
    return;
  }
```

Add the extracted helper directly above `renderAramGod` (before line 473):

```javascript
/* Shared by the full grid (Champions tab) and the compact widget (Overview)
   — both read the same lifetime figure, so this in-flight-request guard
   must be shared too, or a render of each panel back-to-back fires two
   requests instead of one. */
function fetchAramGod() {
  ARAM_GOD_PENDING = ARAM_GOD_PENDING || fetchJSON("/api/aram-god");
  return ARAM_GOD_PENDING.finally(() => { ARAM_GOD_PENDING = null; });
}
```

- [ ] **Step 2: Add the CSS**

Append to `style.css`:

```css
.ov-aram-card {
  background: var(--vc-bg-surface); border: 1px solid var(--vc-border); border-radius: 12px;
  padding: 14px 18px; margin-top: 26px; display: flex; align-items: center; gap: 16px;
}
.ov-aram-card .ov-aram-badge {
  width: 40px; height: 40px; border-radius: 10px; background: rgba(229,169,60,.15);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; color: var(--vc-gold-hl);
}
.ov-aram-card .ov-aram-body { flex: 1; }
.ov-aram-card .ov-aram-title-row { display: flex; justify-content: space-between; align-items: baseline; }
.ov-aram-card .ov-aram-title { font-size: 14px; font-weight: 600; color: var(--vc-text-main); }
.ov-aram-card .ov-aram-count { font-family: "JetBrains Mono", "Consolas", monospace; font-size: 13px; color: var(--vc-gold-hl); }
.ov-aram-card .ov-aram-hint { font-size: 11px; color: var(--vc-text-muted); margin-top: 2px; }
.ov-aram-card .ov-aram-bar { height: 8px; border-radius: 5px; background: var(--vc-bg-surface-hover); margin-top: 8px; overflow: hidden; }
.ov-aram-card .ov-aram-fill { height: 100%; background: linear-gradient(90deg, var(--vc-gold), var(--vc-gold-hl)); border-radius: 5px; }
```

- [ ] **Step 3: Add `renderAramGodCompact` to `app.js`**

Add after `renderSpotlight`:

```javascript
const ARAM_GOD_ICON = '<path d="M12 2l2.5 5.5L20 8l-4.5 4 1.5 6L12 15l-5 3 1.5-6L4 8l5.5-.5z"/>';

async function renderAramGodCompact() {
  const host = document.getElementById("ov-aram");
  let d;
  try {
    d = ARAM_GOD = ARAM_GOD || (await fetchAramGod());
  } catch {
    host.innerHTML = "";
    return;
  }
  const badge = `<div class="ov-aram-badge"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${ARAM_GOD_ICON}</svg></div>`;
  if (!d.tracked || !d.total) {
    host.innerHTML = `
      <div class="ov-aram-card">${badge}
        <div class="ov-aram-body">
          <div class="ov-aram-title-row"><div class="ov-aram-title">ARAM God run</div><div class="ov-aram-count">not tracked yet</div></div>
          <div class="ov-aram-hint">Open the League client once with VibeCheck running to start tracking this</div>
          <div class="ov-aram-bar"><div class="ov-aram-fill" style="width:0%"></div></div>
        </div>
      </div>`;
    return;
  }
  const pct = d.total ? Math.round((d.completed / d.total) * 100) : 0;
  host.innerHTML = `
    <div class="ov-aram-card">${badge}
      <div class="ov-aram-body">
        <div class="ov-aram-title-row"><div class="ov-aram-title">ARAM God run</div><div class="ov-aram-count">${d.completed} / ${d.total}</div></div>
        <div class="ov-aram-hint">S- or better on every ARAM champion — the long one</div>
        <div class="ov-aram-bar"><div class="ov-aram-fill" style="width:${pct}%"></div></div>
      </div>
    </div>`;
}
```

- [ ] **Step 4: Wire it into `renderOverview`**

```javascript
function renderOverview(games) {
  const leaders = categoryLeaders(championTotals(games));
  renderLifetimeTotals(games, leaders);
  renderSpotlight(games, leaders);
  renderAramGodCompact();
  // renderVibeTrend(games) — Task 7
}
```

- [ ] **Step 5: Verify manually**

Run: `.venv\Scripts\python -m vibecheck`. On a profile with the League
client never opened (or a fresh install), Overview shows "not tracked yet"
with an explainer, and the Champions tab's full grid independently shows the
same "not tracked yet" state (no duplicate network request — check the
Network tab for exactly one `/api/aram-god` call when switching between the
two tabs without new data arriving). Once tracked, both panels agree on the
`completed/total` count.

- [ ] **Step 6: Commit**

```powershell
git add vibecheck/web/app.js vibecheck/web/style.css
git commit -m "feat(web): add a compact ARAM God widget to Overview"
```

---

### Task 7: Vibe trend (real portraits over a crisp HTML/SVG line)

**Files:**
- Modify: `vibecheck/web/app.js` (new `renderVibeTrend`, replaces the old
  Chart.js rolling-average block removed in Task 4)
- Modify: `vibecheck/web/style.css` (new `.ov-trend*` rules)

**Interfaces:**
- Consumes: `champIcon`'s underlying `/api/champ-icon/{name}` route
  (existing — square icons, not the new splash endpoint), `GRADES`, `EMOJI`
  tier colors (reuse the `ov-tier*` classes' colors via a small standalone
  palette constant, since those classes are backgrounds, not raw hex).
- Produces: `renderVibeTrend(games)`, called from `renderOverview`.

- [ ] **Step 1: Add the CSS**

Append to `style.css`:

```css
.ov-trend-chart { position: relative; height: 130px; margin-top: 6px; }
.ov-trend-chart svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.ov-trend-point { position: absolute; transform: translate(-50%, -50%); width: 30px; height: 30px; }
.ov-trend-point img {
  width: 100%; height: 100%; border-radius: 50%; object-fit: cover; display: block;
  box-shadow: 0 2px 6px rgba(0,0,0,.5);
}
.ov-trend-point .ov-ring { position: absolute; inset: -3px; border-radius: 50%; border: 2.5px solid var(--ring); pointer-events: none; }
.ov-trend-legend { display: flex; gap: 16px; margin-top: 14px; flex-wrap: wrap; }
.ov-trend-legend span { font-size: 10px; color: var(--vc-text-muted); display: flex; align-items: center; gap: 5px; }
.ov-trend-legend i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.ov-trend-empty { color: var(--vc-text-muted); font-size: 12.5px; padding: 20px 0; text-align: center; }
```

- [ ] **Step 2: Add `renderVibeTrend` to `app.js`**

Add after `renderAramGodCompact`. Points plot the **raw per-game fun score**
(not a rolling average) precisely so each portrait can be read as "this
specific game caused this specific point" — a smoothed average would blur
which champion actually drove a swing, which defeats the point of putting a
portrait on it:

```javascript
const OV_TIER_HEX = { 1: "#EF4444", 2: "#F97316", 3: "#EAB308", 4: "#10B981", 5: "#8B5CF6" };

function renderVibeTrend(games) {
  const host = document.getElementById("ov-trend");
  const rated = games.filter((g) => g.rated).slice().sort((a, b) => a.date - b.date);
  if (!rated.length) {
    host.innerHTML = '<div class="ov-trend-empty">Rate a few games and your vibe trend shows up here.</div>';
    return;
  }
  const n = rated.length;
  const points = rated.map((g, i) => ({
    x: n > 1 ? (100 * i) / (n - 1) : 50,
    // Plot 1–5 into the 8–92% band, inverted (SVG y grows downward, and a
    // high score should sit near the top of the chart).
    y: 92 - ((g.fun_score - 1) / 4) * 84,
    g,
  }));
  const line = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const dots = points.map((p) => `
    <div class="ov-trend-point" style="left:${p.x.toFixed(1)}%;top:${p.y.toFixed(1)}%;--ring:${OV_TIER_HEX[p.g.fun_score]}"
         title="${escapeAttr(p.g.champion_key || "?")} — ${escapeAttr(p.g.day)} — ${GRADES[p.g.fun_score]}">
      <div class="ov-ring"></div>
      <img src="/api/champ-icon/${encodeURIComponent(p.g.champion || "")}${p.g.classic ? "?classic=1" : ""}"
           alt="" loading="lazy" data-on-error="remove">
    </div>`).join("");
  host.innerHTML = `
    <div class="ov-trend-chart">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline fill="none" stroke="${OV_TIER_HEX[3]}22" stroke-width="1.2" vector-effect="non-scaling-stroke" points="${line}"/>
      </svg>
      ${dots}
    </div>
    <div class="ov-trend-legend">${[1, 2, 3, 4, 5].map((t) => `<span><i style="background:${OV_TIER_HEX[t]}"></i>${GRADES[t]}</span>`).join("")}</div>`;
}
```

(This intentionally does not use Chart.js — the whole point of the redesign
was moving off canvas bar/line charts for this page, and a scaled-SVG line
with raster points baked in is exactly the "compressed icons" bug the
design session already hit and fixed once; keeping the line as pure vector
and the icons as real `<img>` elements avoids reintroducing it.)

- [ ] **Step 3: Wire it into `renderOverview` and remove the dead `card()` helper**

```javascript
function renderOverview(games) {
  const leaders = categoryLeaders(championTotals(games));
  renderLifetimeTotals(games, leaders);
  renderSpotlight(games, leaders);
  renderAramGodCompact();
  renderVibeTrend(games);
}
```

Delete the `card(k, v, d, gold = false)` function (just above the old
`renderOverview`, around line 394–396) — after this task, nothing calls it
(`renderLifetimeTotals` and `renderSpotlight` build their own markup
directly).

- [ ] **Step 4: Verify manually**

Run: `.venv\Scripts\python -m vibecheck`. Overview's "Vibe trend" panel
shows one portrait per rated game, left-to-right chronological, each ringed
in its tier color, with a legend below. Hover a point (native `title`
tooltip) to confirm it names the right champion/date/grade. Resize the
browser window narrower and wider — portraits must stay crisp (not blurry
or squished) at every width, since that was the exact defect fixed earlier
in design review. With zero rated games, the panel shows the empty-state
message instead of a blank chart.

- [ ] **Step 5: Commit**

```powershell
git add vibecheck/web/app.js vibecheck/web/style.css
git commit -m "feat(web): rebuild the vibe trend with real champion portraits"
```

---

### Task 8: Final integration pass

**Files:**
- Modify: `vibecheck/web/app.js` (dead-code sweep)
- Review: `vibecheck/web/index.html`, `vibecheck/web/style.css`

**Interfaces:** none new — this task only removes now-unused code and does
a full manual pass across the whole page in order.

- [ ] **Step 1: Sweep for dead code**

Search `app.js` for any remaining references to the old Overview markup IDs
(`fun-facts`, `chart-trend`) — there should be none left outside comments.
Confirm `destroyChart("chart-trend")` is gone (it was inside the old
`renderOverview` body deleted in Task 4) — a stray call to it would throw
since the canvas no longer exists.

- [ ] **Step 2: Full manual walkthrough**

Run: `.venv\Scripts\python -m vibecheck`, open the dashboard.

1. Overview tab, top to bottom: lifetime totals → spotlight → ARAM God →
   vibe trend, matching the approved order.
2. Apply a filter (e.g., a champion or date range) via the filter bar —
   confirm all four Overview sections update to reflect it (per Task 3's
   decision to keep this page filter-reactive like the rest of the app,
   not a separate "always lifetime" exception).
3. Switch to Champions tab and back to Overview — confirm no console
   errors and no duplicate `/api/aram-god` or `/api/champ-splash/*`
   network calls beyond what's needed to redraw.
4. Resize the window to a narrow width (~700px) — spotlight tiles and
   totals cards should wrap/shrink without any horizontal scrollbar on the
   page body.

- [ ] **Step 3: Run the full existing suite**

```powershell
.venv\Scripts\python tests\smoke_test.py
.venv\Scripts\python tests\migration_test.py
.venv\Scripts\python tests\achievement_test.py
.venv\Scripts\python tests\ddragon_splash_test.py
.venv\Scripts\python tests\dashboard_splash_test.py
```
Expected: every script prints its `OK` line.

- [ ] **Step 4: Lint, pre-commit, and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
.venv\Scripts\pre-commit run --all-files
git add -A
git commit -m "chore(web): remove dead Overview code after the tile redesign"
```

---

## Final check before opening the PR

- [ ] Re-read `docs/superpowers/specs/2026-08-10-overview-redesign-design.md`
  against all eight tasks above — confirm every section (lifetime totals,
  spotlight, ARAM God, vibe trend, no-flip animation constraint) has a
  corresponding task.
- [ ] `.venv\Scripts\pre-commit run --all-files` clean.
- [ ] PR description notes the splash-art cache (Tasks 1–2) is new backend
  surface added *within* this "pure frontend" spec, and why (no endpoint
  existed to serve the approved mockups' loading-screen art).
- [ ] PR description notes this leaves the Champions tab's full-roster
  ranked grid and item/build icons as explicit follow-ups, per the spec's
  "Follow-ups" section — not regressions, never designed here.

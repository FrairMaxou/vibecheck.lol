"""Champion icons from Riot's Data Dragon CDN.

The ONLY module that talks to Data Dragon, mirroring how lcu.py, sync.py and
updater.py each isolate one external surface.

Everything here is decoration. The dashboard is fully usable with no icons at
all, so nothing in this module is allowed to block a request, raise into the
app, or retry hard enough to matter: a miss is a 404 and the frontend simply
drops the <img>.

Why icons are fetched and not bundled
-------------------------------------
Champion art is Riot's, not ours. Data Dragon is the public CDN Riot provides
for community tools, so we pull from it at runtime and cache per machine
instead of shipping the art in the exe (BRAND.md §7: never ship Riot marks as
static assets).

Name mapping
------------
Games store *display* names ("Aurelion Sol", "Dr. Mundo", "Jarvan IV") while
the CDN uses keys ("AurelionSol", "DrMundo", "JarvanIV"). The map is derived
from champion.json, never hand-written — hand-written lists rot the moment
Riot ships a champion, and they get the odd ones wrong anyway (Wukong is
"MonkeyKing", Nunu & Willump is "Nunu").
"""

import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .config import DATA_DIR

log = logging.getLogger(__name__)

CACHE_DIR = DATA_DIR / "ddragon"
ICON_DIR = CACHE_DIR / "icons"
SPLASH_DIR = CACHE_DIR / "splash"
MANIFEST_PATH = CACHE_DIR / "manifest.json"

VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
ALLOWED_HOST = "ddragon.leagueoflegends.com"

MANIFEST_MAX_AGE = 7 * 24 * 3600  # patch cadence is ~2 weeks; weekly is plenty
TIMEOUT = 10
# After a failed refresh, don't hammer the CDN on every dashboard render.
FAILURE_COOLDOWN = 3600

_lock = threading.Lock()
_manifest: dict | None = None
_failed_at = 0.0
_missing: set[str] = set()  # icons the CDN didn't have; don't ask twice
_missing_splash: set[str] = set()  # splash art the CDN didn't have; don't ask twice


def _norm(name: str) -> str:
    """Fold a champion name to a lookup key.

    Display names disagree with CDN keys on punctuation, spacing and case
    ("Kai'Sa" vs "Kaisa", "Dr. Mundo" vs "DrMundo"), and payloads aren't
    consistent about which they carry. Stripping to bare alphanumerics makes
    both sides land on the same key.
    """
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _get(url: str, timeout: int = TIMEOUT):
    """Fetch, refusing any URL that isn't Data Dragon.

    The version string lands in these URLs, so the host is checked rather than
    assumed — same rule as updater.py.
    """
    if urllib.parse.urlparse(url).hostname != ALLOWED_HOST:
        raise ValueError(f"refusing to fetch from unexpected host: {url}")
    return urllib.request.urlopen(url, timeout=timeout)  # noqa: S310 - host checked above


def _load_cached_manifest() -> dict | None:
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if data.get("names") else None


def _fetch_manifest() -> dict:
    """Latest patch version + the display-name→key map, straight from the CDN."""
    with _get(VERSIONS_URL) as resp:
        versions = json.load(resp)
    version = versions[0]
    url = f"https://{ALLOWED_HOST}/cdn/{version}/data/en_US/champion.json"
    with _get(url) as resp:
        champions = json.load(resp)

    names: dict[str, str] = {}
    best_id: dict[str, int] = {}
    for key, champ in (champions.get("data") or {}).items():
        # Display names are NOT unique: League Classic ships alternate versions
        # of 60 champions under the same name ("Dr. Mundo" is both DrMundo and
        # Jade_DrMundo). The variants are offset into the 60000s, so the lowest
        # numeric id is the canonical champion — derived from the data rather
        # than a hardcoded prefix, which would rot the next time Riot does this.
        try:
            champ_id = int(champ.get("key", 0))
        except (TypeError, ValueError):
            champ_id = 0
        display = _norm(champ.get("name", ""))
        if display and champ_id < best_id.get(display, 1 << 30):
            best_id[display] = champ_id
            names[display] = key
        # The key itself always maps to itself, so a payload carrying the raw
        # CDN key (variants included) still resolves.
        names[_norm(key)] = key
    if not names:
        raise ValueError("champion.json had no champions")
    return {"version": version, "fetched_at": time.time(), "names": names}


def manifest(refresh: bool = True) -> dict | None:
    """The cached manifest, refreshed when stale. None if we've never had one.

    Never raises: with no network and no cache, icons simply don't exist.
    """
    global _manifest, _failed_at
    with _lock:
        if _manifest is None:
            _manifest = _load_cached_manifest()
        fresh = _manifest and time.time() - _manifest.get("fetched_at", 0) < MANIFEST_MAX_AGE
        if fresh or not refresh:
            return _manifest
        if time.time() - _failed_at < FAILURE_COOLDOWN:
            return _manifest  # recently failed; serve whatever we have
        try:
            _manifest = _fetch_manifest()
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            MANIFEST_PATH.write_text(json.dumps(_manifest), encoding="utf-8")
            log.info("Data Dragon manifest updated (patch %s)", _manifest["version"])
        except Exception as exc:
            _failed_at = time.time()
            log.debug("Data Dragon manifest refresh failed: %s", exc)
        return _manifest


def _key_for(man: dict, name: str, classic: bool) -> str | None:
    """The CDN key for a champion, preferring its League Classic variant.

    Riot ships separate art for all 60 Classic champions under a `Jade_` key.
    The fallback to base art matters for the ARAM Mayhem Classic-ish pool,
    which can include picks outside the 60.
    """
    names = man.get("names") or {}
    key = names.get(_norm(name))
    if classic and key:
        return names.get(_norm(f"Jade_{key}")) or key
    return key


def _cached_path(cache_dir: Path, filename: str, name: str, classic: bool) -> Path | None:
    """Shared disk-only lookup behind icon_path/splash_path: no network, so
    safe to call per row/tile while rendering. Downloading is the paired
    fetch_*'s job, off the request path. `filename` is a `.format(key=...)`
    template — the one thing that actually differs between icon and splash.
    """
    man = manifest(refresh=False)
    if not man:
        return None
    key = _key_for(man, name, classic)
    if not key:
        return None
    path = cache_dir / filename.format(key=key)
    return path if path.exists() else None


def _fetch_asset(
    cache_dir: Path,
    filename: str,
    url_tpl: str,
    missing: set[str],
    label: str,
    name: str,
    classic: bool,
) -> Path | None:
    """Shared download behind fetch_icon/fetch_splash: manifest lookup,
    cache-hit short circuit, atomic write (so a half-downloaded file is never
    served as valid art), and remembering a permanent miss. `url_tpl` is a
    `.format(version=..., key=...)` template.
    """
    man = manifest()
    if not man:
        return None
    key = _key_for(man, name, classic)
    if not key or key in missing:
        return None
    path = cache_dir / filename.format(key=key)
    if path.exists():
        return path

    url = url_tpl.format(version=man["version"], key=key)
    try:
        with _get(url) as resp:
            data = resp.read()
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path
    except Exception as exc:
        missing.add(key)
        log.debug("Could not fetch %s for %s: %s", label, name, exc)
        return None


def _warm_assets(path_fn, fetch_fn, label: str, picks) -> int:
    """Shared warm-up loop behind warm()/warm_splash(): pre-download whatever
    isn't already cached for the champions someone actually plays, off the
    request path. `picks` yields (champion, classic) pairs, so a player who
    only touches League Classic gets Jade art cached and never pays for the
    modern set.
    """
    added = 0
    try:
        for name, classic in {(n, bool(c)) for n, c in picks if n}:
            if path_fn(name, classic):
                continue
            if fetch_fn(name, classic):
                added += 1
        if added:
            log.info("Cached %d champion %s(s)", added, label)
    except Exception:
        log.debug("Champion %s warm-up stopped early", label, exc_info=True)
    return added


def icon_path(name: str, classic: bool = False) -> Path | None:
    """The on-disk icon for a champion, or None if it isn't cached yet."""
    return _cached_path(ICON_DIR, "{key}.png", name, classic)


def fetch_icon(name: str, classic: bool = False) -> Path | None:
    """Download one champion's icon if it isn't cached. Returns its path."""
    url_tpl = f"https://{ALLOWED_HOST}/cdn/{{version}}/img/champion/{{key}}.png"
    return _fetch_asset(ICON_DIR, "{key}.png", url_tpl, _missing, "icon", name, classic)


def splash_path(name: str, classic: bool = False) -> Path | None:
    """The on-disk loading-screen splash for a champion, or None if it isn't
    cached yet. Same disk-only contract as icon_path.
    """
    return _cached_path(SPLASH_DIR, "{key}_0.jpg", name, classic)


def fetch_splash(name: str, classic: bool = False) -> Path | None:
    """Download one champion's loading-screen splash if it isn't cached.

    Unlike the square icon, loading art lives under a version-independent
    CDN path (no /cdn/{version}/ segment) — Data Dragon serves the current
    splash for every champion at the same URL regardless of patch.
    """
    return _fetch_asset(
        SPLASH_DIR,
        "{key}_0.jpg",
        f"https://{ALLOWED_HOST}/cdn/img/champion/loading/{{key}}_0.jpg",
        _missing_splash,
        "splash",
        name,
        classic,
    )


def warm(picks) -> int:
    """Pre-download icons for the champions someone actually plays.

    Called in the background so the dashboard has icons ready rather than
    404ing its way through the first render. Returns how many were added.
    """
    return _warm_assets(icon_path, fetch_icon, "icon", picks)


def warm_splash(picks) -> int:
    """Pre-download splash art for the champions someone actually plays.
    Mirrors warm() exactly — see its docstring.
    """
    return _warm_assets(splash_path, fetch_splash, "splash", picks)

"""In-app self-update for the frozen single-exe build.

The ONLY module that downloads and swaps the running executable, mirroring how
lcu.py and sync.py isolate their external surfaces. Everything here is
best-effort: any failure leaves the installed app exactly as it was, and the UI
falls back to "download it yourself from the releases page".

How replacing a running .exe works on Windows
---------------------------------------------
You cannot *overwrite* a running executable, but you *can rename* it. So:

    1. rename VibeCheck.exe -> VibeCheck.exe.old   (legal while running)
    2. move the downloaded build into the original path
    3. launch it, then exit
    4. the new process deletes the leftover .old on startup

No installer framework and no helper binary — the app updates itself.

The relaunch passes --updated-from-pid so the new process waits for this one to
die before taking the single-instance mutex; without that it would find the
mutex held and exit immediately, looking exactly like a crash.

Trust
-----
The download URL comes from an API response, so it is never followed blindly:
every hop (including redirects) must resolve to a known GitHub host, and the
build's SHA-256 must match the checksums published alongside the release before
anything is swapped. A release with no SHA256SUMS.txt simply isn't self-updatable.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .config import APP_VERSION, DATA_DIR, FROZEN, RELEASES_LATEST_API, RELEASES_PAGE

log = logging.getLogger(__name__)

ASSET_NAME = "VibeCheck.exe"
CHECKSUM_ASSET = "SHA256SUMS.txt"
STAGING_DIR = DATA_DIR / "update"
TIMEOUT = 30

CACHE_KEY = "update_check"
CACHE_SECONDS = 6 * 3600  # unauthenticated GitHub allows 60 req/h per IP

# Release assets live on github.com but redirect to a CDN host; every hop is
# checked against this set, so a tampered API response can't point us elsewhere.
ALLOWED_HOSTS = {
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


class UpdateError(Exception):
    """Any failure during check/download/apply, safe to show to the user."""


def is_newer(a: str, b: str) -> bool:
    """True if dotted version a is newer than b (e.g. '0.2.0' > '0.1.9')."""

    def parts(v: str) -> list[int]:
        out = []
        for p in v.split("."):
            digits = "".join(ch for ch in p if ch.isdigit())
            out.append(int(digits) if digits else 0)
        return out

    pa, pb = parts(a), parts(b)
    n = max(len(pa), len(pb))
    return pa + [0] * (n - len(pa)) > pb + [0] * (n - len(pb))


def can_self_update() -> bool:
    """Only the frozen Windows build can replace itself.

    Running from source, the 'executable' is python.exe — swapping that would be
    both wrong and destructive, so the UI offers `git pull` instead.
    """
    return bool(FROZEN) and sys.platform == "win32"


def _check_host(url: str) -> None:
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise UpdateError(f"refusing to download from unexpected host: {host or '(none)'}")


class _StrictRedirects(urllib.request.HTTPRedirectHandler):
    """Validate every redirect target, not just the URL we started with."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_StrictRedirects)


def _get(url: str, timeout: int = TIMEOUT):
    _check_host(url)
    req = urllib.request.Request(  # noqa: S310 - host checked against ALLOWED_HOSTS above
        url, headers={"Accept": "application/vnd.github+json"}
    )
    return _opener().open(req, timeout=timeout)


def check(timeout: int = 10) -> dict:
    """Ask GitHub what the latest release is.

    Never raises: on any failure (offline, rate-limited, repo private) it
    reports "no update", so a network hiccup can never nag or block the user.
    """
    result = {
        "current": APP_VERSION,
        "latest": None,
        "update_available": False,
        "url": RELEASES_PAGE,
        "can_self_update": False,
        "asset_url": None,
        "size": None,
        "sha256": None,
    }
    try:
        with _get(RELEASES_LATEST_API, timeout=timeout) as resp:
            release = json.load(resp)
    except Exception as exc:
        log.debug("Update check failed: %s", exc)
        return result

    latest = (release.get("tag_name") or "").lstrip("v")
    if not latest or not is_newer(latest, APP_VERSION):
        result["latest"] = latest or None
        return result

    result["latest"] = latest
    result["update_available"] = True

    assets = {a.get("name"): a for a in release.get("assets") or []}
    exe, sums = assets.get(ASSET_NAME), assets.get(CHECKSUM_ASSET)
    if not exe or not sums:
        # No published checksums means we can't prove what we downloaded, so we
        # don't self-update at all — the user is sent to the releases page.
        log.info("Release %s has no %s; self-update unavailable", latest, CHECKSUM_ASSET)
        return result

    try:
        result["sha256"] = _fetch_expected_sha(sums["browser_download_url"])
    except Exception as exc:
        log.info("Could not read published checksums: %s", exc)
        return result

    result["asset_url"] = exe.get("browser_download_url")
    result["size"] = exe.get("size")
    result["can_self_update"] = can_self_update() and bool(result["asset_url"])
    return result


def _build_id() -> str:
    """Identifies the build asking, not just the version.

    The cache lives in the shared database, so a run from source (which can
    never self-update) and the packaged exe would otherwise hand each other
    their answers — the exe then shows "Download from GitHub" even though it
    could update itself. The version is in here too, so an app that has just
    updated itself doesn't keep reporting the version it replaced.
    """
    return f"{APP_VERSION}|{int(can_self_update())}"


def check_cached(store, force: bool = False) -> dict:
    """`check()` behind a shared 6h cache.

    Both callers — the dashboard's profile menu and the background tray check —
    go through here, so they answer identically and draw on one rate-limit
    budget instead of racing each other for it.
    """
    if not force:
        try:
            cached = json.loads(store.get_meta(CACHE_KEY) or "{}")
            fresh = time.time() - cached.get("at", 0) < CACHE_SECONDS
            if fresh and cached.get("build") == _build_id():
                return cached["info"]
        except (ValueError, KeyError, TypeError):
            pass
    info = check()
    store.set_meta(CACHE_KEY, json.dumps({"at": time.time(), "build": _build_id(), "info": info}))
    return info


def _fetch_expected_sha(sums_url: str) -> str:
    """Pull VibeCheck.exe's hash out of a `sha256sum`-format checksums file."""
    with _get(sums_url) as resp:
        text = resp.read().decode("utf-8", "replace")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*").endswith(ASSET_NAME):
            return parts[0].lower()
    raise UpdateError(f"{ASSET_NAME} not listed in {CHECKSUM_ASSET}")


def download(info: dict, progress_cb=None) -> Path:
    """Stream the new build to a staging file and verify it. Returns its path."""
    url, expected = info.get("asset_url"), (info.get("sha256") or "").lower()
    if not url:
        raise UpdateError("no download available for this release")
    if not expected:
        raise UpdateError("this release publishes no checksum, so it can't be verified")

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    target = STAGING_DIR / f"VibeCheck-{info.get('latest') or 'new'}.exe"
    digest = hashlib.sha256()
    done = 0

    with _get(url) as resp:
        total = int(resp.headers.get("Content-Length") or info.get("size") or 0)
        try:
            with open(target, "wb") as fh:
                while chunk := resp.read(256 * 1024):
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress_cb and total:
                        progress_cb(done, total)
        except OSError as exc:
            # Only the local write is wrapped. urllib raises URLError — itself an
            # OSError — for network trouble, and blaming antivirus for a dropped
            # connection would send people to the wrong place entirely.
            # Defender flags our unsigned PyInstaller build as Wacatac.B!ml often
            # enough that a failed write here really is more likely antivirus
            # than a full disk.
            target.unlink(missing_ok=True)
            raise UpdateError(f"the download could not be saved — antivirus? ({exc})") from exc

    actual = digest.hexdigest()
    if actual != expected:
        # Never keep an unverified binary around.
        target.unlink(missing_ok=True)
        raise UpdateError("the downloaded file failed its integrity check")

    # The digest above came from the stream, so it stays valid even if something
    # removed the file behind us. Antivirus deletes on close, after the last
    # write returned fine — check the bytes actually survived.
    if not target.is_file() or target.stat().st_size != done:
        target.unlink(missing_ok=True)
        raise UpdateError(
            "the download was removed before it could be installed — "
            "your antivirus most likely quarantined it"
        )
    log.info("Update %s downloaded and verified (%d bytes)", info.get("latest"), done)
    return target


# PyInstaller's bootloader passes these to its own second stage to say "the
# archive is already unpacked, reuse this directory". Inherited by any child we
# spawn, they make the NEW build skip extraction and adopt the outgoing build's
# temp directory — which PyInstaller then deletes when the old process exits.
# The relaunched app is left pointing at files that no longer exist and dies
# with "Tcl data directory ... not found" before it can draw anything.
_PYI_ENV_VARS = ("_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL")
_LEGACY_PYI_ENV_VARS = ("_MEIPASS2",)  # pre-6.x bootloaders


def _child_env() -> dict:
    """The parent's environment minus PyInstaller's private bookkeeping.

    The relaunched build has to unpack itself from scratch, exactly as it would
    if the user double-clicked it.
    """
    drop = set(_PYI_ENV_VARS) | set(_LEGACY_PYI_ENV_VARS)
    return {k: v for k, v in os.environ.items() if k not in drop}


def apply(new_exe: Path) -> None:
    """Swap in the new build and relaunch it. The caller then quits the app.

    On any failure the original executable is restored, so a half-applied
    update is not a state this can leave behind.
    """
    if not can_self_update():
        raise UpdateError("self-update only works in the packaged app")

    current = Path(sys.executable).resolve()
    backup = current.with_name(current.name + ".old")
    backup.unlink(missing_ok=True)

    os.replace(current, backup)  # rename the running exe — allowed on Windows
    try:
        shutil.copy2(new_exe, current)
    except Exception as exc:
        os.replace(backup, current)  # put it back exactly as it was
        raise UpdateError(f"could not write the new version: {exc}") from exc

    try:
        subprocess.Popen(  # noqa: S603 - our own executable, fixed argv
            [str(current), "--updated-from-pid", str(os.getpid())],
            close_fds=True,
            env=_child_env(),
        )
    except Exception as exc:
        shutil.copy2(backup, current)  # restore, since the new one won't start
        raise UpdateError(f"the updated app could not be started: {exc}") from exc

    log.info("Update applied; relaunching from %s", current)


def cleanup_old() -> None:
    """Delete the previous build and staged downloads. Called at startup."""
    try:
        if can_self_update():
            current = Path(sys.executable).resolve()
            for leftover in current.parent.glob(f"{current.name}.old"):
                leftover.unlink(missing_ok=True)
                log.info("Removed previous build %s", leftover.name)
        if STAGING_DIR.exists():
            shutil.rmtree(STAGING_DIR, ignore_errors=True)
    except Exception:
        log.debug("Update cleanup skipped", exc_info=True)


def wait_for_pid(pid: int, timeout_ms: int = 30_000) -> None:
    """Block until `pid` exits — the old build handing the mutex over to us.

    Without this the relaunched process would hit the single-instance mutex
    while the outgoing one still holds it and exit without a word.
    """
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not handle:
            return  # already gone — nothing to wait for
        try:
            kernel32.WaitForSingleObject(handle, timeout_ms)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        log.debug("Could not wait for the previous process", exc_info=True)


class UpdateJob:
    """Tracks a single download+apply run so the UI can show progress."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {"state": "idle", "percent": 0, "error": None, "version": None}

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _set(self, **fields) -> None:
        with self._lock:
            self._state.update(fields)

    @property
    def running(self) -> bool:
        return self.snapshot()["state"] in ("downloading", "applying")

    def start(self, info: dict, on_ready) -> None:
        """Download, verify and apply in the background; `on_ready` quits the app."""
        if self.running:
            return
        self._set(state="downloading", percent=0, error=None, version=info.get("latest"))

        def worker():
            try:
                staged = download(info, lambda d, t: self._set(percent=int(100 * d / t)))
                self._set(state="applying", percent=100)
                apply(staged)
                self._set(state="restarting")
                on_ready()
            except Exception as exc:
                log.warning("Update failed: %s", exc)
                self._set(state="error", error=str(exc))

        threading.Thread(target=worker, name="updater", daemon=True).start()

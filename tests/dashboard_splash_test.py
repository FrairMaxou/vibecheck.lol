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

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

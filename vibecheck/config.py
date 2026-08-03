import os
import sys
from pathlib import Path

APP_NAME = "VibeCheck.lol"
TAGLINE = "Winrate is temporary. The vibes are forever."
# Bumped automatically by release-please when the Release PR merges — the
# trailing annotation is what it looks for, so don't drop it. Also the git tag
# (vX.Y.Z) and what the updater compares against.
APP_VERSION = "0.1.10"  # x-release-please-version

# Where the in-app "update available" check looks. Must point at whichever repo
# hosts the PUBLIC releases (this repo if open-sourced, or a separate public
# releases repo). Returns 404 while the repo is private — the check then just
# reports "up to date" and never nags.
RELEASES_LATEST_API = "https://api.github.com/repos/FrairMaxou/vibecheck.lol/releases/latest"
RELEASES_PAGE = "https://github.com/FrairMaxou/vibecheck.lol/releases/latest"

# Where users can reach us. These are baked into each build and can't be changed
# after release, so the Discord invite MUST be set to "never expire" — an
# expiring invite becomes a dead link for everyone still on that version.
DISCORD_INVITE_URL = "https://discord.gg/SnE9Yj8cSh"  # verified: never expires
# Google Form for structured feedback. Empty = the menu entry is simply hidden,
# so shipping before the form exists is safe.
FEEDBACK_FORM_URL = ""
# From the form's "Get pre-filled link" (looks like "entry.123456789"). With it
# set, the running version rides along so every report says which build it came
# from; without it the form still opens, just without the version filled in.
FEEDBACK_FORM_VERSION_ENTRY = ""


def feedback_form_url() -> str:
    """The feedback form, with the running version pre-filled when configured."""
    if not FEEDBACK_FORM_URL or not FEEDBACK_FORM_VERSION_ENTRY:
        return FEEDBACK_FORM_URL
    sep = "&" if "?" in FEEDBACK_FORM_URL else "?"
    return f"{FEEDBACK_FORM_URL}{sep}usp=pp_url&{FEEDBACK_FORM_VERSION_ENTRY}=v{APP_VERSION}"


# Where the package's bundled files (web/, assets/) actually live. PyInstaller
# unpacks them to a temp dir and __file__ no longer points at them, so every
# lookup of bundled data must go through this.
FROZEN = getattr(sys, "frozen", False)
PACKAGE_DIR = Path(sys._MEIPASS) / "vibecheck" if FROZEN else Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
ASSETS_DIR = PACKAGE_DIR / "assets"

# --- on-disk data location, and the migration off the pre-rebrand names -------
#
# Builds up to v0.1.8 stored everything under "LeagueOfKiffance" with
# kiffance.* filenames. Live users have real history there, so the move to the
# VibeCheck names is a *migration*, not a rename, and it runs at import time:
# every module below reads these constants, and one of them is the log file, so
# there is no later moment at which the paths are still safe to change.
#
# The rule that makes it safe: if a move fails for any reason, keep using the
# old location. Falling back to the legacy path shows the user their games with
# a stale folder name; creating a fresh path instead would show them an empty
# app, which reads as "it deleted everything".
_LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))

# Import happens before logging is configured, so the migration can't log.
# app.main() drains this once handlers exist.
DATA_MIGRATION_NOTES: list[str] = []


def _migrate_data_dir(new: Path, legacy: Path) -> Path:
    """Move the pre-rebrand data folder to its new name; return the one in use."""
    if new.exists() or not legacy.exists():
        if new.exists() and legacy.exists():
            DATA_MIGRATION_NOTES.append(
                f"Both {new} and {legacy} exist — using {new}. "
                f"The old folder is left untouched; an older build may have recreated it."
            )
        return new
    try:
        # Same volume (both under LOCALAPPDATA), so this is an atomic rename:
        # the folder is either fully moved or not moved at all, never half.
        os.replace(legacy, new)
    except OSError as exc:
        DATA_MIGRATION_NOTES.append(
            f"Could not move {legacy} to {new} ({exc}); staying on the old folder"
        )
        return legacy
    DATA_MIGRATION_NOTES.append(f"Moved data folder {legacy} -> {new}")
    return new


def _migrate_data_file(new: Path, legacy: Path) -> Path:
    """Rename one pre-rebrand data file; return the name actually in use."""
    if new.exists() or not legacy.exists():
        return new
    # A "-journal"/"-wal" sidecar means the last run died mid-write. SQLite finds
    # that journal by the database's filename, so renaming now would strand it
    # and lose the rollback. Leave the pair alone: this run opens the legacy
    # name, SQLite recovers it, and the next launch migrates a clean file.
    if any(legacy.parent.glob(legacy.name + "-*")):
        DATA_MIGRATION_NOTES.append(f"Deferring rename of {legacy.name}: recovery journal present")
        return legacy
    try:
        os.replace(legacy, new)
    except OSError as exc:
        DATA_MIGRATION_NOTES.append(
            f"Could not rename {legacy.name} to {new.name} ({exc}); keeping the old name"
        )
        return legacy
    DATA_MIGRATION_NOTES.append(f"Renamed {legacy.name} -> {new.name}")
    return new


DATA_DIR = _migrate_data_dir(_LOCAL_APPDATA / "VibeCheck", _LOCAL_APPDATA / "LeagueOfKiffance")
DB_PATH = _migrate_data_file(DATA_DIR / "vibecheck.sqlite3", DATA_DIR / "kiffance.sqlite3")
LOG_PATH = _migrate_data_file(DATA_DIR / "vibecheck.log", DATA_DIR / "kiffance.log")

# PRD F3b: ALL queues are captured. This map only provides friendly labels for
# known queue ids; unknown/rotating modes fall back to the payload's raw
# queueType string, so new modes are captured automatically with no code change.
QUEUE_NAMES = {
    400: "Normal Draft",
    420: "Ranked Solo/Duo",
    430: "Normal Blind",
    440: "Ranked Flex",
    450: "ARAM",
    480: "Swiftplay",
    490: "Quickplay",
    700: "Clash",
    830: "Co-op vs AI (Intro)",
    840: "Co-op vs AI (Beginner)",
    850: "Co-op vs AI (Intermediate)",
    870: "Co-op vs AI (Intro)",
    880: "Co-op vs AI (Beginner)",
    890: "Co-op vs AI (Intermediate)",
    720: "ARAM Clash",
    900: "ARURF",
    1700: "Arena",
    1710: "Arena",
    1900: "URF",
    2400: "ARAM Mayhem",  # gameMode "KIWI"
    # League Classic (patch 26.15, 2026-07-29) — the Season 3 throwback mode.
    # Internally codenamed "Jade": gameMode "JADE" on its own map (453).
    4310: "League Classic",  # the matchmade PvP queue (has its own ranked ladder)
    4320: "League Classic (Co-op vs AI)",
    3260: "League Classic (Custom)",  # blind pick
    3262: "League Classic (Custom)",  # draft pick
    # ARAM: Mayhem Classic-ish — Mayhem augments with the Classic champion pool
    # and items. gameMode "KIWI_JADE", still on the ARAM map (12).
    2450: "ARAM Mayhem Classic-ish",
    3280: "ARAM Mayhem Classic-ish (Custom)",
    2410: "ARAM Mayhem Tournament",
    3270: "ARAM Mayhem (Custom)",
}

# League Classic is a *different game*, not a different queue: Season 3 kits,
# items and map. Its champions share display names with the modern ones but play
# nothing like them, and Riot ships separate art for all 60 — so a vibe score
# that averaged both would describe an experience nobody actually had. These
# drive the "(Classic)" split in the dashboard and the Jade portraits.
CLASSIC_QUEUE_IDS = {4310, 4320, 3260, 3262, 2450, 3280, 2410, 3270}
CLASSIC_GAME_MODES = {"JADE", "KIWI_JADE"}

# Bump whenever QUEUE_NAMES or GAME_MODE_NAMES changes. Labels are stored on the
# game row at capture time, so already-captured games keep whatever name was
# known back then — League Classic games captured before its label existed read
# "JADE". On startup the app re-applies labels once per version bump.
QUEUE_LABELS_VERSION = 2

# Fallback labels by gameMode, used when a queue id isn't in QUEUE_NAMES above.
# Riot ships new queue ids for existing modes regularly (League Classic alone
# added four), so this keeps a brand-new queue readable — "League Classic"
# rather than a raw "JADE" — with no code change. Only add a mode here when the
# raw string would be unhelpful or cryptic to a player.
GAME_MODE_NAMES = {
    "CLASSIC": "Summoner's Rift",
    "ARAM": "ARAM",
    "JADE": "League Classic",
    "KIWI": "ARAM Mayhem",
    "KIWI_JADE": "ARAM Mayhem Classic-ish",
    "CHERRY": "Arena",
    "SWIFTPLAY": "Swiftplay",
    "URF": "URF",
    "BRAWL": "Brawl",
    "NEXUSBLITZ": "Nexus Blitz",
    "ONEFORALL": "One for All",
    "ULTBOOK": "Ultimate Spellbook",
    "STRAWBERRY": "Swarm",
    "PRACTICETOOL": "Practice Tool",
}

# Fallback when the end-of-game payload has no queueId, only a queueType string.
QUEUE_TYPE_TO_ID = {
    "RANKED_SOLO_5x5": 420,
    "RANKED_FLEX_SR": 440,
    "NORMAL": 400,
    "NORMAL_QUICKPLAY": 490,
    "ARAM_UNRANKED_5x5": 450,
    "ARAM": 450,
}

DASHBOARD_HOST = "127.0.0.1"  # PRD §6b N4: localhost only, never 0.0.0.0
# Overridable so a port clash (or a second instance) doesn't need a code change.
DASHBOARD_PORT = int(os.environ.get("VIBECHECK_PORT", "8577"))

# Default quick-tags seeded on first run (F9). User-editable afterwards.
DEFAULT_TAGS = [
    "Hard carried",
    "Int diff",
    "Good vibes only",
    "Clutched it",
    "Griefed",
    "Never again",
    "Certified troll",
]

SESSION_GAP_SECONDS = 3600  # PRD F17: games < 1h apart share a session
CATCHUP_FIRST_RUN_HOURS = 3  # on first ever launch, look this far back for missed games
POPUP_TIMEOUT_SECONDS = 300  # PRD F10
CLIENT_POLL_SECONDS = 10  # how often to look for the League client when it's not running

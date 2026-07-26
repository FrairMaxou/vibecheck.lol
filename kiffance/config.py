import os
import sys
from pathlib import Path

APP_NAME = "VibeCheck.lol"
TAGLINE = "Winrate is temporary. The vibes are forever."

# Where the package's bundled files (web/, assets/) actually live. PyInstaller
# unpacks them to a temp dir and __file__ no longer points at them, so every
# lookup of bundled data must go through this.
FROZEN = getattr(sys, "frozen", False)
PACKAGE_DIR = Path(sys._MEIPASS) / "kiffance" if FROZEN else Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
ASSETS_DIR = PACKAGE_DIR / "assets"

# The on-disk folder/file names are kept as-is through the VibeCheck.lol rebrand
# on purpose: renaming them would orphan every game a user has already captured.
# These paths are internal and effectively invisible to users.
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LeagueOfKiffance"
DB_PATH = DATA_DIR / "kiffance.sqlite3"
LOG_PATH = DATA_DIR / "kiffance.log"

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
DASHBOARD_PORT = int(os.environ.get("KIFFANCE_PORT", "8577"))

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

"""Short release notes, shown once after the app updates itself.

Keep these in plain language: this is read by someone who just wants to play
League, not a changelog reader. A few bullets, no jargon, no issue numbers.
Skip anything internal — if it isn't visible to the user, it doesn't belong.

Add a new entry each release, keyed by the version in config.APP_VERSION.
A version with no entry here simply shows nothing, which is a fine default.
"""

RELEASE_NOTES = {
    "0.1.6": [
        "Champion portraits everywhere — the tier list, the vibes-vs-winrate chart, "
        "To Rate and Tags.",
        "League Classic champions are counted separately from their modern versions. "
        "Season 3 Jax isn't the same pick, so he gets his own row (and his own art).",
        "The tier list shows your top 10 with a button for the rest, instead of "
        "cramming everyone in and hiding half the names.",
        "The dashboard wears the VibeCheck logo now.",
    ],
    "0.1.5": [
        "VibeCheck now tells you when a new version is out, even if you never open "
        "the dashboard — look for the tray icon.",
        "Fixed friends not showing up in your squad.",
        "The Update button installs the update again, instead of sending you to GitHub.",
    ],
    "0.1.4": [
        "League Classic and ARAM Mayhem Classic-ish now show up by name — and your "
        "old games from those modes get renamed too.",
        "Fixed games with friends being counted as solo queue when the app restarted mid-game.",
    ],
    "0.1.3": [
        "Updates install themselves now — one click, no more downloading from GitHub.",
        "The dashboard stopped flickering every minute.",
        "Games you rate in the popup leave To Rate straight away.",
        "Come say hi: there's a Discord link in your profile menu.",
    ],
}


def notes_for(version: str) -> list:
    return RELEASE_NOTES.get(version, [])

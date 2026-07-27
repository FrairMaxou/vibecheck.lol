"""Short release notes, shown once after the app updates itself.

Keep these in plain language: this is read by someone who just wants to play
League, not a changelog reader. A few bullets, no jargon, no issue numbers.
Skip anything internal — if it isn't visible to the user, it doesn't belong.

Add a new entry each release, keyed by the version in config.APP_VERSION.
A version with no entry here simply shows nothing, which is a fine default.
"""

RELEASE_NOTES = {
    "0.1.3": [
        "Updates install themselves now — one click, no more downloading from GitHub.",
        "The dashboard stopped flickering every minute.",
        "Games you rate in the popup leave To Rate straight away.",
        "Come say hi: there's a Discord link in your profile menu.",
    ],
}


def notes_for(version: str) -> list:
    return RELEASE_NOTES.get(version, [])

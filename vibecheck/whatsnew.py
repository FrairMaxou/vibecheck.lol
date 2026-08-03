"""Short release notes, shown once after the app updates itself.

Keep these in plain language: this is read by someone who just wants to play
League, not a changelog reader. A few bullets, no jargon, no issue numbers.
Skip anything internal — if it isn't visible to the user, it doesn't belong.

Add a new entry each release, keyed by the version in config.APP_VERSION.
At runtime a missing version degrades to showing nothing rather than crashing —
but it is no longer an acceptable state to ship: release-please bumps the
version automatically, so a missing entry means it was forgotten, not chosen.
`tests/smoke_test.py` fails the release until one exists.
"""

RELEASE_NOTES = {
    # Nothing in 0.1.9 is visible on screen, which is exactly why it needs
    # saying: one button that never worked (people pressed it and got an error),
    # and a door on the dashboard that should never have been open. "We improved
    # security" with no detail is how you make someone nervous instead of
    # reassured — so each one says plainly what it was and what it means.
    "0.1.9": [
        "Sync now, in Squad Sync, has never actually worked — it just handed you an "
        "error. Fixed. Your rated games were going up on their own after every "
        "rating anyway, so nothing was ever missing.",
        "The dashboard now ignores anything that isn't you. It has only ever run on "
        "your own machine, but a random site open in another tab could still tell it "
        "to do things — like shut VibeCheck down mid-game. That door is closed.",
        "Champion names, summoner names and your own notes are shown as plain text "
        "everywhere, so nothing coming out of a match can mess with the page.",
        # Last on purpose: the move is silent and needs nothing from the user, so
        # it only matters in one situation — going back to an older build, which
        # then looks empty. Someone who hits that is about to think they lost
        # months of games, so the reassurance has to be in the sentence itself.
        "Your games moved to a folder actually named VibeCheck instead of the old "
        "project name — it happens by itself on first launch. If you ever go back to "
        "an older version it'll look empty: that build still checks the old folder. "
        "Nothing is lost, it's just not where the old one looks.",
    ],
    # Whoever reads this card has *just* updated, which is exactly the audience
    # that may have hit the crash — so lead by explaining it rather than
    # burying it under a feature.
    "0.1.8": [
        "If updating threw an error about a missing folder and VibeCheck didn't come "
        "back on its own — sorry, that's the bug this release fixes. Nothing was "
        "damaged, and opening it again was all it needed.",
        "Updates now restart the app properly instead of tripping over themselves.",
    ],
    "0.1.7": [
        "The rating popup is way smaller — a notification instead of a window "
        "taking over a third of your screen.",
        "Fresh installs no longer open on empty charts: VibeCheck grabs your last "
        "5 games and asks how they went, so there's something to look at on day one.",
    ],
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

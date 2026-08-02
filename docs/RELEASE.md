# Releasing VibeCheck.lol

The deployment protocol: how a merged PR becomes an exe on the releases page,
and everything about the backend credentials that build depends on.

## Shipping a version

**You ship by merging a pull request.** There is no manual version bump, no tag
to push, no checklist to run from memory.

### How it works

Every push to `main` runs
[release-please.yml](../.github/workflows/release-please.yml), which reads the
Conventional Commits landed since the last release and keeps a **Release PR**
open — titled `chore(release): vX.Y.Z` — containing:

- the new version in `vibecheck/config.py` and `pyproject.toml`
- a `CHANGELOG.md` entry assembled from the commit subjects

The version it picks comes from the commits: a `fix:` bumps the patch, a `feat:`
bumps the minor, a `!`/`BREAKING CHANGE:` bumps the major. `docs:`, `chore:`,
`ci:` and friends bump nothing, so a week of housekeeping never produces a
release nobody needs.

Merging that PR tags `vX.Y.Z` and calls
[release.yml](../.github/workflows/release.yml), which builds the single-exe
with PyInstaller on a clean Windows runner, smoke-tests it, and attaches it plus
`SHA256SUMS.txt` to the GitHub Release.

> The tag is created with `GITHUB_TOKEN`, and GitHub deliberately does not let
> one workflow trigger another that way. That's why `release-please.yml` *calls*
> `release.yml` as a reusable workflow instead of relying on the tag push — the
> alternative is a long-lived personal access token, which isn't worth it.

### Your part

1. **Before merging the Release PR, edit
   [vibecheck/whatsnew.py](../vibecheck/whatsnew.py) on its branch.** The
   changelog is generated from commit subjects and reads like commit subjects;
   `whatsnew.py` is the plain-language card users actually see after updating.
   It stays hand-written on purpose.
2. If the change touched the backend, run the
   [pre-release checklist](#pre-release-checklist).
3. Merge. Then check the published release has **both** `VibeCheck.exe` and
   `SHA256SUMS.txt`, and that the hash matches — the in-app updater refuses a
   build it can't verify, so a missing checksum file breaks self-update for
   every existing user.

### Cutting one by hand

The tag triggers are still live, so the old path works if automation is stuck:

```bash
git tag v0.1.9 && git push origin v0.1.9
```

Bump `APP_VERSION` and `.release-please-manifest.json` yourself if you do —
otherwise the next Release PR will propose a version that already exists.

## The backend model (PRD §12)

There is **one** Supabase project, owned by the maintainer, shared by everyone.
Players never create an account, never run SQL, never enter a key, and never
share a code. A friend's whole experience is:

1. download the app
2. run it and play

Squad Online populates itself: the app derives identity from the in-game PUUID,
signs in anonymously behind the scenes, and forms the squad from **mutual League
friends** who also run VibeCheck (see PRD §12). The key-entry form only appears
when the app has **no** bundled credentials — i.e. a source checkout or a
self-hoster pointing at their own project. Shipped builds never show it.

> **Project setup (maintainer, once):** in the Supabase dashboard, enable
> **Authentication → Sign In / Providers → Allow anonymous sign-ins**, and run
> `supabase/schema.sql`. Without anonymous sign-ins, Squad Online can't create
> the silent session and will surface a 422 in the tab.

## Baking in the credentials

The release build generates `vibecheck/_bundled.py` (gitignored):

```python
SUPABASE_URL = "https://<project>.supabase.co"
SUPABASE_KEY = "sb_publishable_..."
```

Credential resolution order (`vibecheck/sync.py: load_config`):

1. `%LOCALAPPDATA%\LeagueOfKiffance\supabase.json` — self-host / dev override
2. `vibecheck/_bundled.py` — what shipped builds use
3. `VIBECHECK_SUPABASE_URL` / `VIBECHECK_SUPABASE_KEY` env vars — CI / scripts

In CI, store the two values as GitHub Actions **secrets** and write the module
in the build job:

```yaml
- name: Bake backend credentials
  run: |
    echo "SUPABASE_URL = '${{ secrets.SUPABASE_URL }}'" > vibecheck/_bundled.py
    echo "SUPABASE_KEY = '${{ secrets.SUPABASE_PUBLISHABLE_KEY }}'" >> vibecheck/_bundled.py
```

## Which key — and why this is safe

Ship the **publishable** key (formerly "anon public"). It is designed to be
embedded in client apps; it is visible in the JavaScript of every Supabase web
app in existence. Secrecy is **not** what protects the data — the Row-Level
Security policies in [supabase/schema.sql](../supabase/schema.sql) are. Every
table denies by default and only exposes rows to the owner or their squad-mates.

**Never ship, commit, or share the `service_role` / secret key.** It bypasses
RLS entirely. This app never uses it, and nothing in the codebase reads it.

Assume the publishable key is extractable from any shipped build (a Python exe
is readable). That is fine and expected — treat it as public, never as a
secret. It is kept out of the repo only to avoid bots discovering the endpoint
and burning free-tier quota, not because exposure would breach the data.

## Abuse considerations for a public endpoint

Because anyone with the key can reach the project's API:

- **Keep RLS on for every table.** Re-run `schema.sql` after any schema change;
  it is idempotent and safe to re-run.
- **Anonymous sign-ins are enabled by design** (they're what make onboarding
  zero-config). RLS is the only guard, so every table must deny by default and
  expose rows solely to the owner PUUID and its mutual friends.
- **Watch usage** in the Supabase dashboard; rotate the publishable key if it is
  ever abused (rotation invalidates old builds, so ship a new release with it).
- Visibility is **mutual-friend gated**: a stranger who spins up an anonymous
  session and claims a PUUID still sees nothing unless that PUUID's real owner
  lists them back as a friend. The only thing at stake is fun scores — soft
  security is the accepted trade-off (PRD §12).

## Pre-release checklist

- [ ] `schema.sql` re-run against the production project (idempotent)
- [ ] **Anonymous sign-ins enabled** in the project (Authentication → Sign In / Providers)
- [ ] `_bundled.py` generated from CI secrets, **not** committed
- [ ] `git grep` finds no `sb_secret`, no `service_role`, no JWT in the repo
- [ ] Fresh-machine smoke test: install → capture a game → rate → open dashboard
- [ ] Squad Online shows "start League once" (no key prompt); after a client connect it shows "Synced as …"

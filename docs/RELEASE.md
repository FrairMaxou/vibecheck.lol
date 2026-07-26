# Releasing League of Kiffance

## The backend model (PRD §12)

There is **one** Supabase project, owned by the maintainer, shared by everyone.
Players never create an account, never run SQL, never enter a key, and never
share a code. A friend's whole experience is:

1. download the app
2. run it and play

Squad Online populates itself: the app derives identity from the in-game PUUID,
signs in anonymously behind the scenes, and forms the squad from **mutual League
friends** who also run Kiffance (see PRD §12). The key-entry form only appears
when the app has **no** bundled credentials — i.e. a source checkout or a
self-hoster pointing at their own project. Shipped builds never show it.

> **Project setup (maintainer, once):** in the Supabase dashboard, enable
> **Authentication → Sign In / Providers → Allow anonymous sign-ins**, and run
> `supabase/schema.sql`. Without anonymous sign-ins, Squad Online can't create
> the silent session and will surface a 422 in the tab.

## Baking in the credentials

The release build generates `kiffance/_bundled.py` (gitignored):

```python
SUPABASE_URL = "https://<project>.supabase.co"
SUPABASE_KEY = "sb_publishable_..."
```

Credential resolution order (`kiffance/sync.py: load_config`):

1. `%LOCALAPPDATA%\LeagueOfKiffance\supabase.json` — self-host / dev override
2. `kiffance/_bundled.py` — what shipped builds use
3. `KIFFANCE_SUPABASE_URL` / `KIFFANCE_SUPABASE_KEY` env vars — CI / scripts

In CI, store the two values as GitHub Actions **secrets** and write the module
in the build job:

```yaml
- name: Bake backend credentials
  run: |
    echo "SUPABASE_URL = '${{ secrets.SUPABASE_URL }}'" > kiffance/_bundled.py
    echo "SUPABASE_KEY = '${{ secrets.SUPABASE_PUBLISHABLE_KEY }}'" >> kiffance/_bundled.py
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

<!--
PR title must follow Conventional Commits: <type>(<scope>): <subject>
It is squash-merged, so this title becomes the commit message on main.
CI will fail the `pr-title` check otherwise. See CONTRIBUTING.md.
-->

Closes #

## What changed

<!-- One or two lines. What a user or the next maintainer would notice. -->

## How it was checked

<!-- Delete what doesn't apply. -->

- [ ] `pre-commit run --all-files`
- [ ] `python tests/smoke_test.py`
- [ ] Ran the app and reproduced the fix / used the feature
- [ ] Built the exe (`pyinstaller vibecheck.spec`) — for packaging changes

## Guardrails

- [ ] No new access to the League **game** process (LCU client API only)
- [ ] Supabase schema change, if any, is backward-compatible with shipped clients
- [ ] Visual change follows `.claude/brand identity/BRAND.md`
- [ ] PRD.md / CLAUDE.md / docs updated in this PR if behaviour changed

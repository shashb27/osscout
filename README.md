# osscout

[![CI](https://github.com/shashb27/osscout/actions/workflows/ci.yml/badge.svg)](https://github.com/shashb27/osscout/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Screen upstream repos and issues for open-source contribution viability before you spend a day on a PR that's already taken.

Agent-farm PR bots sweep most viable communities within hours to weeks of an issue being filed. `osscout` automates the screening workflow that keeps your contribution credible: check who actually merges, check who already has a PR open, mine the invitations farms never look at.

Requires the [GitHub CLI](https://cli.github.com/) (`gh`) installed and authenticated.

## Install

```
pip install .
```

## Usage

**Gate one repo — merge culture + staleness:**

```
osscout repo psf/black
```

**Gate one issue — competing PRs (all states), bot-queue signals, hard-stop labels:**

```
osscout issue NousResearch/hermes-agent 100955
osscout issue psf/black 5379 --keywords "drives" "find_project_root"
```

**Mine maintainer invitations (`pull-request wanted` label + `PR welcome` comments):**

```
osscout mine pyinstaller/pyinstaller
```

**Farm-window table + durable niches:**

```
osscout windows
```

**Daily sweep across your repo shortlist (v0.3):**

```
osscout watch
```

Sweeps the newest open issues (default: filed within 7 days, max 15 per repo) across a shortlist and marks each one `TAKEN` (open/recent PR, merged fix, bot-queue marker, hard-stop label, or confirmed soft-claim), `CAUTION` (unconfirmed claim or old closed PR), or `CLEAN`. It ships with a default shortlist of vetted communities; bring your own via `osscout.toml` (checked in the current directory, then `~/.config/osscout/config.toml`) or `--repos`:

```toml
[watch]
repos = ["psf/black", "sphinx-doc/sphinx", "pygments/pygments"]
days = 7
limit = 15
```

```
osscout watch --days 3 --limit 10
osscout watch --repos pypa/pip eslint/eslint
```

A `CLEAN` verdict from `watch` is a first pass, not a gate — run `osscout issue` (full competing-PR sweep by number *and* title keywords, plus the whole comment thread) on anything you're about to spend a day on. Watch searches by issue number only, so PRs that fix without referencing the number can slip past it.

Note: a full sweep makes a couple of hundred `gh` calls (well within authed rate limits) and takes a few minutes when run serially.

## Exit codes (scriptable)

- `0` — GO / PASS
- `1` — NO-GO / SKIP / DEAD / LIKELY FIXED
- `2` — BORDERLINE / CAUTION / NO DATA

## Verdict rules

- **repo**: `SKIP` when one human author is at or above 80% of recent merged PRs (or fewer than two distinct humans), or when dependency bots account for half the merges with a thin human bench; `PASS` when 3+ distinct humans merge and the top human holds at most 60% of human merges; stale (90+ days without a push) overrides PASS to SKIP.
- **issue**: any open PR, or any PR closed within the last 60 days, is a NO-GO (closed-without-merge still counts — someone already attempted the fix). Merged PR means LIKELY FIXED. Dependency-bot false positives are filtered. Bot-queue comments (`clawsweeper:*`, "implementation worker is queued") and `no-new-fix-pr` labels are hard stops. Soft-claim detection: a comment claiming the issue ("I'd like to work on this", "LMK what you think", ...) followed by a later maintainer ("MEMBER"/"OWNER"/"COLLABORATOR") affirmation ("PR is welcome", "go ahead", ...) is a NO-GO even with zero PRs open. A claim without maintainer affirmation keeps the verdict but is recorded and surfaced as a caution line.

## Roadmap

- historical farm-window measurement (issue-created → first-PR timestamps) instead of a static table
- parallelize the `watch` sweep across repos

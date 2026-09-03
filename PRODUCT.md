# osscout — product brief

## Why this exists

Most viable open-source communities are now swept by agent-farm PR bots within
hours to weeks of an issue being filed. A human contributor who finds an issue,
writes a fix, and opens a PR is increasingly racing invisible automation — and
the two failure modes are expensive:

1. **The duplicate PR.** The issue was already claimed by an open PR, a
   closed-without-merge attempt, a triage-bot queue marker, or a
   conversational soft-claim ("may I work on this?" + maintainer "PR is
   welcome"). A duplicate PR burns credibility with the exact maintainers you
   are trying to build a relationship with.
2. **The roting PR.** The community looks healthy — stars, activity — but one
   person merges 85% of PRs and externals don't land. Your PR sits forever.

osscout exists because we hit both, repeatedly, while screening by hand with a
written checklist. Every gate in the tool corresponds to a specific failure we
personally recorded before automating it.

## What it is — and is not

osscout is a **pre-flight gate** for external contributors. It answers
go/no-go before you invest a day:

- `osscout repo OWNER/REPO` — is this community worth your PR? Merge culture
  (distinct humans who actually merge, top-author dominance, dependency-bot
  share) plus staleness.
- `osscout issue OWNER/REPO N` — is this issue already taken? Competing PRs in
  all states (closed-without-merge still counts), bot-queue markers, hard-stop
  labels, and soft-claims read from the comment thread.
- `osscout watch` — a daily board across your shortlist: every fresh issue
  marked TAKEN / CAUTION / CLEAN.
- `osscout mine` — maintainer invitations (`PR welcome`, `pull-request wanted`).
- `osscout discover` — bootstrap a shortlist: run the repo gate over your
  GitHub stars or a list of candidates; get a suggested `osscout.toml`.

It is **not** an issue recommender, dashboard, bounty board, or a bot that
fixes things. Discovery tools already exist; screening is the gap.

## Who it's for

1. **The disciplined external contributor** (1 PR/day-week, credibility is
   their capital) — fully served today. This is who it was built by and for.
2. **The aspiring contributor** ("I keep picking taken issues and gave up") —
   served once they have a shortlist (`discover` removes the cold start).
3. **Maintainers and agent operators** — could use it, not who it's built for.

Honest note on dual use: `watch`'s CLEAN list could feed a farm. Farms already
have better tooling than this; the asymmetry being fixed is that humans don't.

## When you'd use it

- Morning: `osscout watch` → the board.
- A candidate appears: `osscout issue o/r N` → GO / NO-GO before writing code.
- A new community appears: `osscout repo o/r` → PASS / SKIP.
- First run ever: `osscout discover --from-stars <you>` → your first config.
- All verdicts are scriptable via exit codes (0/1/2) — fits humans and agents.

## Why not just look at the repo yourself?

You can — everything here is doable manually. But the taken-signal is
distributed across surfaces a glance never touches (PR search across all
states, bot comments, labels, comment 14 of 40), the culture-signal requires
tabulating ~20 merged PRs by author, and humans skip gates when excited.
Screening one candidate properly costs 15–30 minutes; a daily contributor
screening several candidates compounds that into hours. osscout is a linter
for contribution decisions: deterministic where attention drifts.

## Landscape

- **GitHub `/contribute` + GFI labels** — curated discovery, no taken-check,
  no culture-check; the most farm-swept surface of all.
- **CodeTriage** — daily issue emails from a watchlist; label-driven, no gates.
- **Good First Issue / Up for Grabs** — aggregators; discovery only.
- **OpenSauced** — the serious one: PR-velocity analytics and hot-repo
  dashboards. Measures activity, not whether *your* PR will rot; no
  soft-claim detection; web-platform shape.
- **Bounty platforms (Algora, Polar)** — curated paid issues; different
  economics, small coverage.
- **Farm bots** — find, claim, fix. Not human tools.

Differentiation, in one line: everyone else helps you find issues; osscout
tells you **don't**. No other tool reads comment threads for conversational
claims, flags closed-without-merge attempts as taken, or treats
single-maintainer merge dominance as a hard warning.

## Honest limitations

- One real user so far; phrase lists are English, hand-curated, and tuned on
  our own failures (recall risk on unusual claim phrasings).
- `watch` searches competing PRs by issue number only — a PR that fixes
  without referencing the number can slip past. `osscout issue` (number +
  title keywords + full thread) remains the deep gate.
- Stateless: no history, no "changed since yesterday", no scheduling.
- GitHub-only, via the `gh` CLI; no REST fallback.
- Merge-culture rules are heuristics (≥80% dominance, <2 humans, ≥50% bots)
  — a SKIP is a warning, not a verdict about you.

## Roadmap

- measured farm windows (issue-created → first-PR timestamps computed from
  live data, replacing the static reference table)
- parallelized `watch` sweep
- PyPI release after a dogfooding period

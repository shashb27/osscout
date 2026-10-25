import argparse
import sys
from pathlib import Path

from . import __version__
from .culture import scan_repo
from .data import DURABLE_NICHES, FARM_WINDOWS
from .discover import _toml_block, discover_repos, format_discovery, starred_repos
from .gh import GhError
from .mining import format_mine, mine_invited
from .pounce import format_pounce, run_pounce, send_alerts
from .sweep import scan_issue
from .policy import format_policy, scan_policy
from .track import format_track, run_track
from .watch import format_watch, run_watch

EXIT_CODES = {"GO": 0, "PASS": 0, "OK": 0, "NO-GO": 1, "SKIP": 1, "SKIP (stale)": 1,
              "DEAD": 1, "LIKELY FIXED": 1, "NO DATA": 2, "BORDERLINE": 2, "CAUTION": 2}

VERDICT_LEGEND = """\
verdicts:
  GO / PASS   no blockers found - clear to contribute
  CLEAN       watch first pass only - not a gate; deep-gate with `osscout issue`
  TAKEN       someone already owns it: open/recent PR, merged fix, bot-queue marker, hard-stop label, or confirmed soft-claim
  CAUTION     read first: old closed PR, unconfirmed claim, reporter fix in body, design call, or maintainer-parked label
  SKIP        externals rarely land here: solo-maintainer/bot-heavy merges or a stale repo
  BORDERLINE  merge culture on the edge - verify with a larger sample
  quiet       track: nothing needs a reply, rebase, or cleanup
  pounce      hot-window tripwire (hours not days): exit 1 = fresh CLEAN candidate(s) - deep-gate with `osscout issue` before acting
  policy      AI/contribution policy gate: POSTS_BANNED (exit 2 - a human writes every post) / DISCLOSURE_REQUIRED (include the
              required disclosure) / AGENT_FRIENDLY / CLEAN (exit 0) / UNKNOWN (exit 1 - treat as banned until re-run succeeds)
exit codes: 0 = GO/PASS/quiet, 1 = NO-GO/SKIP/DEAD/LIKELY FIXED/attention, 2 = BORDERLINE/CAUTION/NO DATA/config error/POSTS_BANNED"""


def _force_utf8_stdio():
    # Issue titles may contain any Unicode; Windows consoles default to a
    # legacy code page (cp1252) that crashes printing them.
    for stream in (sys.stdout, sys.stderr):
        if stream.encoding and stream.encoding.lower() not in ("utf-8", "utf8"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _print_repo(report: dict) -> None:
    c = report["culture"]
    print(f"repo: {report['repo']}")
    print(f"  merges analyzed : {c['total']} (bots excluded: {c['bots']})")
    print(f"  distinct humans : {c['distinct_humans']}")
    print(f"  top merger      : {c['top_author']} x{c['top_count']} ({c['top_share']:.0%})")
    if c["repeat_contributors"]:
        names = ", ".join(f"{a} x{n}" for a, n in c["repeat_contributors"])
        print(f"  repeat externals: {names}")
    s = report["staleness"]
    print(f"  last push       : {s['days_since_push']} days ago" + ("  [STALE]" if s["stale"] else ""))
    print(f"  verdict         : {report['verdict']}")


def _print_issue(report: dict) -> None:
    print(f"issue: {report['repo']}#{report['number']} - {report['title']}")
    sig = report["signals"]
    print(f"  state      : {sig['state']}  labels: {', '.join(sig['labels']) or '-'}")
    print(f"  comments   : {sig['comment_count']}")
    if sig["bot_queue_markers"]:
        print(f"  bot-queue  : {', '.join(sig['bot_queue_markers'])}")
    if sig["hard_stop_labels"]:
        print(f"  hard labels: {', '.join(sig['hard_stop_labels'])}")
    if sig.get("assignees"):
        print(f"  assigned   : {', '.join(sig['assignees'])} (someone owns the lane)")
    sc = sig["soft_claim"]
    if sc:
        if sc["affirmed_by"]:
            print(f"  soft-claim : claimed by {sc['claimed_by']}, affirmed by {sc['affirmed_by']} (maintainer)")
        else:
            print(f"  soft-claim : claimed by {sc['claimed_by']} (unconfirmed)")
            print(f"  caution    : unconfirmed claim on record - read the comment thread before opening a PR")
    if sig["reporter_fix"]:
        print("  caution    : reporter-demonstrated fix in body")
    if sig["design_call"]:
        print("  caution    : design-call issue (maintainer decision needed)")
    if sig["parked"]:
        print(f"  caution    : maintainer-parked label: {sig['parked'][0]}")
    prs = report["prs"]
    for label, items in (("merged", prs["merged"]), ("open", prs["open"]),
                         ("closed<=60d", prs["recent_closed"]), ("closed>60d", prs["old_closed"])):
        for p in items:
            author = (p.get("author") or {}).get("login", "?")
            print(f"  PR [{label}] #{p['number']} by {author}: {p['title'][:80]}")
    if prs["noise_filtered"]:
        print(f"  (filtered {len(prs['noise_filtered'])} dependency-bot false positives)")
    print(f"  verdict    : {report['verdict']}")
    searched = sum(len(prs[b]) for b in ("merged", "open", "recent_closed", "old_closed"))
    print(
        f"  searched   : {searched} PRs across all states "
        f"(number + title keywords), {sig['comment_count']} comment(s) read"
    )
    signals = [
        "no competing PRs" if not (prs["open"] or prs["recent_closed"]) else "competing PRs found",
        "no soft-claims" if not sig["soft_claim"] else "soft-claim on record",
        "no bot-queue markers" if not sig["bot_queue_markers"] else "bot-queue markers found",
    ]
    print(f"  signals    : {', '.join(signals)}")


def _print_windows() -> None:
    print("measured farm windows (issue filed -> first competing PR):")
    for repo, window, note in FARM_WINDOWS:
        print(f"  {repo:<55} {window:<12} {note}")
    print("\ndurable niches (farms consistently skip these):")
    for n in DURABLE_NICHES:
        print(f"  - {n}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="osscout",
        description="Screen upstream repos/issues for OSS-contribution viability.",
        epilog=VERDICT_LEGEND,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="osscout " + __version__)
    sub = parser.add_subparsers(dest="cmd", metavar="command", required=True)

    p_repo = sub.add_parser("repo", help="merge-culture + staleness gate for a repo")
    p_repo.add_argument("repo", help="OWNER/REPO")
    p_repo.add_argument("--limit", type=int, default=20, help="merged PRs analyzed (default 20)")

    p_policy = sub.add_parser("policy", help="AI/contribution policy gate - run BEFORE any post in a repo")
    p_policy.add_argument("repo", help="OWNER/REPO")

    p_issue = sub.add_parser("issue", help="competing-PR + bot-signal gate for one issue")
    p_issue.add_argument("repo", help="OWNER/REPO")
    p_issue.add_argument("number", type=int, help="issue number to gate")
    p_issue.add_argument("--keywords", nargs="*", default=[], help="extra search terms")

    p_mine = sub.add_parser("mine", help="mine 'PR welcome' / 'pull-request wanted' invitations")
    p_mine.add_argument("repo", help="OWNER/REPO")

    sub.add_parser("windows", help="measured farm windows + durable niches")

    p_watch = sub.add_parser("watch", help="sweep newest issues across a repo shortlist")
    p_watch.add_argument("--config", default=None, help="path to osscout.toml (default: ./osscout.toml or ~/.config/osscout/config.toml)")
    p_watch.add_argument("--repos", nargs="*", default=[], help="repos to sweep (overrides config)")
    p_watch.add_argument("--days", type=int, default=None, help="only issues created within N days (default 7)")
    p_watch.add_argument("--limit", type=int, default=None, help="max issues per repo (default 15)")

    p_pounce = sub.add_parser("pounce", help="hot-window sweep for fast-burn repos (hours, not days)")
    p_pounce.add_argument("--config", default=None, help="path to osscout.toml ([pounce] table)")
    p_pounce.add_argument("--repos", nargs="*", default=[], help="repos to sweep (default: [pounce] repos)")
    p_pounce.add_argument("--hours", type=float, default=None, help="only issues created within N hours (default 12)")
    p_pounce.add_argument("--limit", type=int, default=None, help="max issues per repo (default 10)")
    p_pounce.add_argument("--alert", nargs="?", const="config", default=None, metavar="OWNER/REPO",
                          help="file one issue per CLEAN candidate in OWNER/REPO (default: [pounce] alert_repo) so GitHub emails you")
    p_pounce.add_argument("--dry-run", action="store_true", help="print alerts instead of filing them")

    p_disc = sub.add_parser("discover", help="bootstrap a watchlist: run the repo gate over candidates")
    p_disc.add_argument("--from-stars", metavar="LOGIN", default=None, help="scan the GitHub stars of LOGIN")
    p_disc.add_argument("--repos", nargs="*", default=[], help="explicit candidate repos (overrides --from-stars)")
    p_disc.add_argument("--limit", type=int, default=40, help="merged PRs analyzed per repo (default 40)")
    p_disc.add_argument("--write", metavar="PATH", default=None, help="write the suggested [watch] block to PATH")

    p_track = sub.add_parser("track", help="board of filed contributions: reviews, replies, competing PRs, blockers")
    p_track.add_argument("--config", default=None, help="path to contributions.toml (default: ./contributions.toml or ~/.config/osscout/contributions.toml)")
    p_track.add_argument("--no-autoseed", action="store_true", help="don't auto-add open PRs authored by @me")
    p_track.add_argument("--policy-audit", action="store_true", help="re-run the AI-policy gate over all ledger repos (weekly; ~8 gh calls per repo)")

    args = parser.parse_args(argv)
    _force_utf8_stdio()
    if args.cmd == "repo":
        report = scan_repo(args.repo, args.limit)
        _print_repo(report)
        code = EXIT_CODES.get(report["verdict"], 2)
    elif args.cmd == "policy":
        report = scan_policy(args.repo)
        print(format_policy(report))
        code = {"POSTS_BANNED": 2, "UNKNOWN": 1}.get(report["verdict"], 0)
    elif args.cmd == "issue":
        report = scan_issue(args.repo, args.number, args.keywords)
        _print_issue(report)
        code = EXIT_CODES.get(report["verdict"], 2)
    elif args.cmd == "mine":
        print(format_mine(args.repo, mine_invited(args.repo)))
        code = 0
    elif args.cmd == "watch":
        try:
            report = run_watch(args.repos, args.days, args.limit, args.config)
        except (FileNotFoundError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            code = 2
        else:
            print(format_watch(report))
            code = 0
    elif args.cmd == "pounce":
        try:
            report = run_pounce(args.repos, args.hours, args.limit, args.config)
        except (FileNotFoundError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            code = 2
        else:
            print(format_pounce(report))
            code = 1 if report["has_candidates"] else 0
            if args.alert and report["has_candidates"]:
                try:
                    alert_repo = None if args.alert == "config" else args.alert
                    sent = send_alerts(report, alert_repo, args.config, args.dry_run)
                except (FileNotFoundError, ValueError) as e:
                    print(f"alert error: {e}", file=sys.stderr)
                    sent = []
                for s in sent:
                    if "url" in s:
                        print(f"alert filed: {s['key']} -> {s['url']}")
                    elif "error" in s:
                        print(f"alert failed: {s['key']}: {s['error']}", file=sys.stderr)
                    else:
                        print(f"alert (dry-run): {s['key']} -> {s['title']}")
    elif args.cmd == "discover":
        if args.repos:
            candidates = args.repos
        elif args.from_stars:
            try:
                candidates = starred_repos(args.from_stars)
            except GhError as e:
                print(f"error: {e}", file=sys.stderr)
                candidates = []
        else:
            candidates = []
        if not candidates:
            print("error: no candidates - pass --repos OWNER/REPO ... or --from-stars LOGIN", file=sys.stderr)
            code = 2
        else:
            report = discover_repos(candidates, args.limit)
            print(format_discovery(report))
            if args.write:
                Path(args.write).write_text(_toml_block(report["suggested"]) + "\n", encoding="utf-8")
                print(f"\nwrote {args.write}")
            code = 0
    elif args.cmd == "track":
        try:
            report = run_track(args.config, not args.no_autoseed, policy_audit=args.policy_audit)
        except (FileNotFoundError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            code = 2
        else:
            print(format_track(report))
            needs = sum(
                1 for i in report["items"]
                if i["status"] in ("ATTENTION", "ERROR")
            )
            needs += (report.get("policy") or {}).get("attention_count", 0)
            code = 1 if needs else 0
    else:
        _print_windows()
        code = 0
    return code


if __name__ == "__main__":
    sys.exit(main())

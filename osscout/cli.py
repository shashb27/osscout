import argparse
import sys

from . import __version__
from .culture import scan_repo
from .data import DURABLE_NICHES, FARM_WINDOWS
from .mining import mine_invited
from .sweep import scan_issue

EXIT_CODES = {"GO": 0, "PASS": 0, "OK": 0, "NO-GO": 1, "SKIP": 1, "SKIP (stale)": 1,
              "DEAD": 1, "LIKELY FIXED": 1, "NO DATA": 2, "BORDERLINE": 2, "CAUTION": 2}


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
    sc = sig["soft_claim"]
    if sc:
        if sc["affirmed_by"]:
            print(f"  soft-claim : claimed by {sc['claimed_by']}, affirmed by {sc['affirmed_by']} (maintainer)")
        else:
            print(f"  soft-claim : claimed by {sc['claimed_by']} (unconfirmed)")
            print(f"  caution    : unconfirmed claim on record - read the comment thread before opening a PR")
    prs = report["prs"]
    for label, items in (("merged", prs["merged"]), ("open", prs["open"]),
                         ("closed<=60d", prs["recent_closed"]), ("closed>60d", prs["old_closed"])):
        for p in items:
            author = (p.get("author") or {}).get("login", "?")
            print(f"  PR [{label}] #{p['number']} by {author}: {p['title'][:80]}")
    if prs["noise_filtered"]:
        print(f"  (filtered {len(prs['noise_filtered'])} dependency-bot false positives)")
    print(f"  verdict    : {report['verdict']}")


def _print_mine(issues: list[dict]) -> None:
    if not issues:
        print("no 'PR welcome' / 'pull-request wanted' invitations found")
        return
    for i in issues:
        print(f"  #{i['number']}  {i['updatedAt'][:10]}  {i['title'][:90]}")


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
    )
    parser.add_argument("--version", action="version", version="osscout " + __version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_repo = sub.add_parser("repo", help="merge-culture + staleness gate for a repo")
    p_repo.add_argument("repo", help="OWNER/REPO")
    p_repo.add_argument("--limit", type=int, default=20)

    p_issue = sub.add_parser("issue", help="competing-PR + bot-signal gate for one issue")
    p_issue.add_argument("repo", help="OWNER/REPO")
    p_issue.add_argument("number", type=int)
    p_issue.add_argument("--keywords", nargs="*", default=[], help="extra search terms")

    p_mine = sub.add_parser("mine", help="mine 'PR welcome' / 'pull-request wanted' invitations")
    p_mine.add_argument("repo", help="OWNER/REPO")

    sub.add_parser("windows", help="measured farm windows + durable niches")

    args = parser.parse_args(argv)
    if args.cmd == "repo":
        report = scan_repo(args.repo, args.limit)
        _print_repo(report)
        code = EXIT_CODES.get(report["verdict"], 2)
    elif args.cmd == "issue":
        report = scan_issue(args.repo, args.number, args.keywords)
        _print_issue(report)
        code = EXIT_CODES.get(report["verdict"], 2)
    elif args.cmd == "mine":
        _print_mine(mine_invited(args.repo))
        code = 0
    else:
        _print_windows()
        code = 0
    return code


if __name__ == "__main__":
    sys.exit(main())

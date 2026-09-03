from datetime import datetime, timedelta, timezone

from .data import BOT_AUTHOR_PREFIXES
from .gh import gh_json


def is_bot(author: str) -> bool:
    a = (author or "").lower()
    if not a:
        return True
    return any(a.startswith(p) for p in BOT_AUTHOR_PREFIXES) or a.endswith("bot")


def analyze_authors(logins: list[str]) -> dict:
    humans = [a for a in logins if not is_bot(a)]
    bots = len(logins) - len(humans)
    counts: dict[str, int] = {}
    for a in humans:
        counts[a] = counts.get(a, 0) + 1
    top, top_n = max(counts.items(), key=lambda kv: kv[1]) if counts else ("-", 0)
    share = top_n / len(logins) if logins else 0.0
    bot_share = bots / len(logins) if logins else 0.0
    human_share = top_n / len(humans) if humans else 0.0
    distinct = len(counts)
    if not logins:
        verdict = "NO DATA"
    elif share >= 0.8 or distinct < 2:
        verdict = "SKIP"
    elif bot_share >= 0.5:
        verdict = "BORDERLINE" if distinct >= 3 else "SKIP"
    elif distinct >= 3 and human_share <= 0.6:
        verdict = "PASS"
    else:
        verdict = "BORDERLINE"
    multi = sorted((a, c) for a, c in counts.items() if c >= 2)
    return {
        "total": len(logins),
        "bots": bots,
        "bot_share": bot_share,
        "human_merges": len(humans),
        "distinct_humans": distinct,
        "top_author": top,
        "top_count": top_n,
        "top_share": share,
        "top_human_share": human_share,
        "repeat_contributors": multi,
        "verdict": verdict,
    }


def repo_staleness(pushed_at: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    days = (now - pushed).days
    return {"days_since_push": days, "stale": days > 90}


def scan_repo(repo: str, limit: int = 20) -> dict:
    prs = gh_json(
        "pr", "list",
        "--repo", repo,
        "--state", "merged",
        "--limit", str(limit),
        "--json", "author",
    )
    logins = [p["author"]["login"] for p in prs if p.get("author")]
    culture = analyze_authors(logins)
    meta = gh_json("repo", "view", repo, "--json", "pushedAt")
    staleness = repo_staleness(meta["pushedAt"])
    stale_override = culture["verdict"] == "PASS" and staleness["stale"]
    verdict = "SKIP (stale)" if stale_override else culture["verdict"]
    return {"repo": repo, "culture": culture, "staleness": staleness, "verdict": verdict}

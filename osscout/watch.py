import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .data import DEFAULT_WATCH_REPOS, HARD_STOP_LABELS, RECENT_CLOSED_DAYS
from .gh import GhError, gh_json
from .sweep import classify_prs, issue_signals


def load_config(path: str | None = None) -> dict:
    if path:
        candidates = [Path(path)]
    else:
        candidates = [
            Path("osscout.toml"),
            Path.home() / ".config" / "osscout" / "config.toml",
        ]
    for p in candidates:
        if p.is_file():
            data = tomllib.loads(p.read_text(encoding="utf-8"))
            watch = data.get("watch", {})
            if not isinstance(watch, dict):
                raise ValueError(f"[watch] table expected in {p}")
            return watch
    if path:
        raise FileNotFoundError(f"config not found: {path}")
    return {}


def _created_at(issue: dict) -> datetime:
    return datetime.fromisoformat(issue["createdAt"].replace("Z", "+00:00"))


def _pr_author(pr: dict) -> str:
    return (pr.get("author") or {}).get("login", "?")


def _issue_verdict(repo: str, issue: dict, fetch, now: datetime) -> dict:
    number = issue["number"]
    title = issue["title"]
    age_days = max((now - _created_at(issue)).days, 0)
    result = {"number": number, "title": title, "age_days": age_days}

    labels = [l["name"] for l in issue.get("labels", [])]
    hard = [l for l in labels if l in HARD_STOP_LABELS]
    if hard:
        result.update(verdict="TAKEN", why=f"hard-stop label: {hard[0]}")
        return result

    prs = fetch(
        "pr", "list", "--repo", repo, "--state", "all",
        "--search", str(number),
        "--json", "number,state,author,title,closedAt",
    )
    cls = classify_prs(prs, now)
    if cls["merged"]:
        result.update(verdict="TAKEN", why=f"merged fix PR #{cls['merged'][0]['number']}")
        return result
    if cls["open"]:
        p = cls["open"][0]
        result.update(verdict="TAKEN", why=f"open PR #{p['number']} by {_pr_author(p)}")
        return result
    if cls["recent_closed"]:
        p = cls["recent_closed"][0]
        result.update(
            verdict="TAKEN",
            why=f"PR #{p['number']} closed within {RECENT_CLOSED_DAYS}d",
        )
        return result

    verdict = "CLEAN"
    reasons = []
    if cls["old_closed"]:
        verdict = "CAUTION"
        reasons.append(f"old closed PR #{cls['old_closed'][0]['number']}")

    comments = []
    if issue.get("comments"):
        data = fetch(
            "issue", "view", str(number), "--repo", repo, "--json", "comments",
        )
        comments = data.get("comments", [])
    signals = issue_signals("OPEN", labels, comments, issue.get("body") or "")
    if signals["bot_queue_markers"]:
        result.update(
            verdict="TAKEN",
            why=f"bot queue: {signals['bot_queue_markers'][0]}",
        )
        return result
    sc = signals["soft_claim"]
    if sc and sc["affirmed_by"]:
        result.update(
            verdict="TAKEN",
            why=f"claimed by {sc['claimed_by']}, affirmed by {sc['affirmed_by']}",
        )
        return result
    if sc:
        verdict = "CAUTION"
        reasons.append(f"unconfirmed claim by {sc['claimed_by']}")
    if signals["reporter_fix"]:
        verdict = "CAUTION"
        reasons.append("reporter-demonstrated fix in body")
    if signals["design_call"]:
        verdict = "CAUTION"
        reasons.append("design-call issue (maintainer decision needed)")

    result.update(verdict=verdict, why="; ".join(reasons) if reasons else "-")
    return result


def sweep_repo(repo: str, days: int, limit: int, fetch=gh_json, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    issues = fetch(
        "issue", "list", "--repo", repo, "--state", "open", "--limit", "100",
        "--json", "number,title,labels,comments,createdAt,body",
    )
    cutoff = now - timedelta(days=days)
    fresh = [i for i in issues if _created_at(i) >= cutoff]
    fresh.sort(key=_created_at, reverse=True)
    return [_issue_verdict(repo, i, fetch, now) for i in fresh[:limit]]


def run_watch(
    repos: list[str] | None,
    days: int | None,
    limit: int | None,
    config_path: str | None = None,
    fetch=gh_json,
    now: datetime | None = None,
) -> dict:
    cfg = load_config(config_path)
    days = days if days is not None else cfg.get("days", 7)
    limit = limit if limit is not None else cfg.get("limit", 15)
    repos = repos or cfg.get("repos") or list(DEFAULT_WATCH_REPOS)
    results: dict[str, list[dict] | dict] = {}
    for repo in repos:
        try:
            results[repo] = sweep_repo(repo, days, limit, fetch, now)
        except GhError as e:
            results[repo] = {"error": str(e)}
    return {"repos": results, "days": days, "limit": limit, "repo_count": len(repos)}


def format_watch(report: dict) -> str:
    lines = [f"osscout watch - {report['repo_count']} repos, issues <= {report['days']}d, max {report['limit']}/repo", ""]
    total = {"TAKEN": 0, "CAUTION": 0, "CLEAN": 0}
    for repo, issues in report["repos"].items():
        if isinstance(issues, dict) and "error" in issues:
            lines.append(f"{repo}  [ERROR] {issues['error']}")
            lines.append("")
            continue
        lines.append(f"{repo}  ({len(issues)} fresh)")
        for i in issues:
            total[i["verdict"]] = total.get(i["verdict"], 0) + 1
            why = "" if i["why"] == "-" else f"  - {i['why']}"
            lines.append(f"  {i['verdict']:<7} #{i['number']:<6} {i['age_days']}d  {i['title'][:60]}{why}")
        lines.append("")
    lines.append(
        f"total: {sum(total.values())} issues - {total['TAKEN']} taken, "
        f"{total['CAUTION']} caution, {total['CLEAN']} clean"
    )
    return "\n".join(lines)

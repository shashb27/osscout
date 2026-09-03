import tomllib
from datetime import datetime, timezone
from pathlib import Path

from .gh import GhError, gh_json
from .sweep import classify_prs

KINDS = ("pr", "issue-comment", "upstream")


def load_ledger(path: str | None = None) -> list[dict]:
    if path:
        candidates = [Path(path)]
    else:
        candidates = [
            Path("contributions.toml"),
            Path.home() / ".config" / "osscout" / "contributions.toml",
        ]
    for p in candidates:
        if p.is_file():
            data = tomllib.loads(p.read_text(encoding="utf-8"))
            entries = data.get("contribution", [])
            if not isinstance(entries, list):
                raise ValueError(f"[[contribution]] entries expected in {p}")
            for e in entries:
                if e.get("kind") not in KINDS:
                    raise ValueError(f"unknown kind {e.get('kind')!r} in {p}")
            return entries
    if path:
        raise FileNotFoundError(f"ledger not found: {path}")
    return []


def autoseed_prs(fetch=None, limit: int = 30) -> list[dict]:
    if fetch is None:
        fetch = gh_json
    try:
        prs = fetch(
            "search", "prs", "--author", "@me", "--state", "open",
            "--limit", str(limit),
            "--json", "repository,number,title",
        )
    except GhError:
        return []
    out = []
    for p in prs:
        repo = ((p.get("repository") or {}).get("nameWithOwner")) or ""
        if repo:
            out.append({
                "repo": repo,
                "number": int(p["number"]),
                "kind": "pr",
                "note": p.get("title", ""),
                "auto": True,
            })
    return out


def merge_entries(ledger: list[dict], seeded: list[dict]) -> list[dict]:
    merged = {(e["repo"], int(e["number"])): e for e in ledger}
    for e in seeded:
        merged.setdefault((e["repo"], e["number"]), e)
    return list(merged.values())


def _events(data: dict) -> list[tuple[str, str]]:
    events = []
    for c in data.get("comments") or []:
        events.append(
            (c.get("createdAt"), (c.get("author") or {}).get("login", "?"))
        )
    for r in data.get("reviews") or []:
        events.append(
            (r.get("submittedAt"), (r.get("author") or {}).get("login", "?"))
        )
    events = [e for e in events if e[0]]
    events.sort()
    return events


def _days_ago(ts: str, now: datetime) -> int:
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return max((now - t).days, 0)


def _ci_summary(rollup: list[dict]) -> str:
    if not rollup:
        return ""
    done = [c for c in rollup if c.get("conclusion")]
    pending = [c for c in rollup if not c.get("conclusion")]
    if pending:
        return f"{len(pending)} pending"
    if not done:
        return ""
    fails = [
        c for c in done
        if c.get("conclusion") not in ("SUCCESS", "SKIPPED", "NEUTRAL")
    ]
    return "pass" if not fails else f"{len(fails)}/{len(done)} failing"


def _competing(repo: str, issue: int, own_number: int, fetch) -> str:
    prs = fetch(
        "pr", "list", "--repo", repo, "--state", "all",
        "--search", str(issue),
        "--json", "number,state,author,title,closedAt",
    )
    cls = classify_prs(prs)
    others = []
    for bucket in ("open", "recent_closed"):
        for p in cls[bucket]:
            if p["number"] != own_number:
                others.append(f"#{p['number']} ({p['state'].lower()})")
    return ", ".join(others[:3])


def check_contribution(entry: dict, me: str, fetch=None, now: datetime | None = None) -> dict:
    if fetch is None:
        fetch = gh_json
    now = now or datetime.now(timezone.utc)
    repo = entry["repo"]
    number = int(entry["number"])
    kind = entry.get("kind", "pr")
    result = dict(entry)
    try:
        if kind == "pr":
            data = fetch(
                "pr", "view", str(number), "--repo", repo, "--json",
                "state,reviewDecision,comments,reviews,statusCheckRollup,updatedAt",
            )
        else:
            data = fetch(
                "issue", "view", str(number), "--repo", repo, "--json",
                "state,comments,updatedAt",
            )
    except GhError as e:
        result.update(status="ERROR", state="?", detail=str(e))
        return result

    state = data.get("state", "?")
    events = _events(data)
    last_ts, last_who = events[-1] if events else (data.get("updatedAt"), None)
    attention = False
    reasons = []
    bits = []

    if kind == "pr" and state == "MERGED":
        result.update(status="DONE", state=state, detail="merged - remove from ledger")
        return result
    if state == "MERGED":
        attention = True
        reasons.append("merged - the thing we waited on happened, act")
    elif state == "CLOSED":
        attention = True
        reasons.append("closed")
    if kind == "pr":
        rd = data.get("reviewDecision") or ""
        if rd == "CHANGES_REQUESTED":
            attention = True
            reasons.append("changes requested")
        elif rd == "APPROVED":
            bits.append("approved")
        ci = _ci_summary(data.get("statusCheckRollup") or [])
        if ci:
            bits.append(f"CI: {ci}")
    if last_ts and last_who and last_who != me:
        attention = True
        reasons.append(f"last: {last_who} {_days_ago(last_ts, now)}d ago")
    elif last_ts:
        bits.append(f"last: me {_days_ago(last_ts, now)}d ago")
    parent = entry.get("issue")
    if parent and kind == "pr" and state == "OPEN":
        comp = _competing(repo, int(parent), number, fetch)
        if comp:
            attention = True
            reasons.append(f"competing on #{parent}: {comp}")

    result.update(
        status="ATTENTION" if attention else "quiet",
        state=state,
        detail="; ".join(reasons + bits) or "-",
    )
    return result


def run_track(
    config_path: str | None = None,
    autoseed: bool = True,
    fetch=None,
    now: datetime | None = None,
) -> dict:
    if fetch is None:
        fetch = gh_json
    now = now or datetime.now(timezone.utc)
    ledger = load_ledger(config_path)
    seeded = autoseed_prs(fetch) if autoseed else []
    entries = merge_entries(ledger, seeded)
    if not entries:
        raise ValueError(
            "no contributions to track - add [[contribution]] entries to "
            "contributions.toml or run with autoseed"
        )
    me = (fetch("api", "user") or {}).get("login", "")
    items = [check_contribution(e, me, fetch, now) for e in entries]
    return {
        "items": items,
        "ledger_count": len(ledger),
        "auto_count": sum(1 for i in items if i.get("auto")),
    }


def format_track(report: dict) -> str:
    lines = [
        f"osscout track - {len(report['items'])} items "
        f"({report['ledger_count']} ledger, {report['auto_count']} auto-seeded)",
        "",
    ]
    attention = []
    for i in report["items"]:
        if i["status"] in ("ATTENTION", "DONE", "ERROR"):
            attention.append(i)
        lines.append(
            f"  {i['status']:<9} {i['repo']}#{i['number']}"
            f" [{i.get('kind', 'pr')}] {i.get('state', '')}"
        )
        lines.append(f"      {i.get('detail', '-')}")
    lines.append("")
    if attention:
        lines.append(
            f"{len(attention)} need attention: "
            + ", ".join(f"{i['repo']}#{i['number']}" for i in attention)
        )
    else:
        lines.append("nothing needs attention")
    return "\n".join(lines)

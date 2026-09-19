import re
from datetime import datetime, timedelta, timezone

from .culture import is_bot
from .data import (
    AFFIRMATIVE_PHRASES,
    BOT_QUEUE_MARKERS,
    CLAIM_PHRASES,
    DEPENDENCY_BOT_TITLE_WORDS,
    DESIGN_CALL_PHRASES,
    HARD_STOP_LABELS,
    MAINTAINER_ASSOCIATIONS,
    PARKED_LABEL_PHRASES,
    PROPOSED_DIRECTION_PHRASE,
    RECENT_CLOSED_DAYS,
    REPORTER_FIX_PHRASES,
)
from .gh import gh_json


def _is_dependency_noise(pr: dict) -> bool:
    author = (pr.get("author") or {}).get("login", "")
    title = (pr.get("title") or "").lower()
    if not is_bot(author):
        return False
    return any(w in title for w in DEPENDENCY_BOT_TITLE_WORDS)


def classify_prs(prs: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    noise = [p for p in prs if _is_dependency_noise(p)]
    real = [p for p in prs if not _is_dependency_noise(p)]
    cutoff = now - timedelta(days=RECENT_CLOSED_DAYS)
    merged, open_prs, recent_closed, old_closed = [], [], [], []
    for p in real:
        state = p.get("state")
        if state == "MERGED":
            merged.append(p)
        elif state == "OPEN":
            open_prs.append(p)
        else:
            closed_at = p.get("closedAt")
            if closed_at:
                closed = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                (recent_closed if closed >= cutoff else old_closed).append(p)
            else:
                recent_closed.append(p)
    if merged:
        verdict = "LIKELY FIXED"
    elif open_prs:
        verdict = "NO-GO"
    elif recent_closed:
        verdict = "NO-GO"
    elif old_closed:
        verdict = "CAUTION"
    else:
        verdict = "GO"
    return {
        "merged": merged,
        "open": open_prs,
        "recent_closed": recent_closed,
        "old_closed": old_closed,
        "noise_filtered": noise,
        "verdict": verdict,
    }


def _match_phrases(body: str, phrases: tuple[str, ...]) -> bool:
    normalized = (body or "").lower().replace("\u2019", "'")
    return any(p in normalized for p in phrases)


def _comment_login(comment: dict) -> str:
    return (comment.get("author") or comment.get("user") or {}).get("login", "?")


def _comment_association(comment: dict) -> str:
    return comment.get("authorAssociation") or comment.get("author_association") or "NONE"


def _is_maintainer(comment: dict) -> bool:
    return _comment_association(comment) in MAINTAINER_ASSOCIATIONS


def _soft_claim(comments: list[dict]) -> dict | None:
    for i, claim in enumerate(comments):
        if not _match_phrases(claim.get("body") or "", CLAIM_PHRASES):
            continue
        claimed_by = _comment_login(claim)
        for c in comments[i + 1:]:
            if _is_maintainer(c) and _match_phrases(c.get("body") or "", AFFIRMATIVE_PHRASES):
                return {"claimed_by": claimed_by, "affirmed_by": _comment_login(c)}
        return {"claimed_by": claimed_by, "affirmed_by": None}
    return None


_MENTION_RE = re.compile(r"(?<![\w.])@\w+")


def _design_call(body: str) -> bool:
    if _match_phrases(body, DESIGN_CALL_PHRASES):
        return True
    normalized = (body or "").lower().replace("\u2019", "'")
    return PROPOSED_DIRECTION_PHRASE in normalized and bool(_MENTION_RE.search(normalized))


def issue_signals(
    state: str,
    labels: list[str],
    comments: list[dict],
    body: str = "",
) -> dict:
    bodies = [c.get("body") or "" for c in comments]
    queued = [m for m in BOT_QUEUE_MARKERS if any(m in b for b in bodies)]
    hard_labels = [l for l in labels if l in HARD_STOP_LABELS]
    parked = [l for l in labels if any(p in l.lower() for p in PARKED_LABEL_PHRASES)]
    soft_claim = _soft_claim(comments)
    reporter_fix = _match_phrases(body, REPORTER_FIX_PHRASES)
    design_call = _design_call(body)
    dead = state != "OPEN"
    if dead:
        verdict = "DEAD"
    elif queued or hard_labels or (soft_claim and soft_claim["affirmed_by"]):
        verdict = "NO-GO"
    elif reporter_fix or design_call or parked:
        verdict = "CAUTION"
    else:
        verdict = "OK"
    return {
        "state": state,
        "labels": labels,
        "comment_count": len(comments),
        "bot_queue_markers": queued,
        "hard_stop_labels": hard_labels,
        "soft_claim": soft_claim,
        "reporter_fix": reporter_fix,
        "design_call": design_call,
        "parked": parked,
        "verdict": verdict,
    }


def scan_issue(repo: str, number: int, extra_terms: list[str] | None = None) -> dict:
    issue = gh_json(
        "issue", "view", str(number),
        "--repo", repo,
        "--json", "state,title,labels,comments,body",
    )
    signals = issue_signals(
        issue["state"],
        [l["name"] for l in issue["labels"]],
        issue["comments"],
        issue.get("body") or "",
    )
    terms = [str(number), '"' + issue["title"] + '"'] + list(extra_terms or [])
    seen: dict[int, dict] = {}
    for term in terms:
        prs = gh_json(
            "pr", "list",
            "--repo", repo,
            "--state", "all",
            "--search", term,
            "--json", "number,state,author,title,closedAt",
        )
        for p in prs:
            seen.setdefault(p["number"], p)
    sweep = classify_prs(list(seen.values()))
    if signals["verdict"] in ("DEAD", "NO-GO"):
        final = signals["verdict"]
    elif sweep["verdict"] == "GO":
        final = "CAUTION" if signals["verdict"] == "CAUTION" else "GO"
    elif sweep["verdict"] == "LIKELY FIXED":
        final = "DEAD"
    else:
        final = sweep["verdict"]
    return {"repo": repo, "number": number, "title": issue["title"], "signals": signals, "prs": sweep, "verdict": final}

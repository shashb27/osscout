"""osscout pounce - hot-window sweep for fast-burn repos.

sglang-class repos get claimed within ~6h of filing; a daily watch
structurally misses that window. Pounce is the tripwire: the same gates
as `watch`, but the cutoff is hours not days, output is CLEAN-only, and
exit code 1 means "fresh candidate on the board right now - go gate it
with `osscout issue`". With --alert it files one issue per candidate in a
private alerts repo so GitHub emails the owner between sessions.
"""
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from .gh import GhError, gh_json
from .watch import sweep_repo

DEFAULTS = {
    "repos": ["sgl-project/sglang"],
    "hours": 12,
    "limit": 10,
    "alert_repo": "shashb27/pounce-alerts",
}


def load_pounce_config(path: str | None = None) -> dict:
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
            cfg = dict(DEFAULTS)
            cfg.update(data.get("pounce", {}))
            return cfg
    if path:
        raise FileNotFoundError(f"config not found: {path}")
    return dict(DEFAULTS)


def run_pounce(
    repos: list[str] | None,
    hours: float | None,
    limit: int | None,
    config_path: str | None = None,
    fetch=gh_json,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    cfg = load_pounce_config(config_path)
    repos = repos or cfg["repos"]
    hours = cfg["hours"] if hours is None else hours
    limit = cfg["limit"] if limit is None else limit

    candidates: list[dict] = []
    repo_stats: dict[str, dict] = {}
    for repo in repos:
        try:
            verdicts = sweep_repo(repo, 0, limit, fetch, now, hours=hours)
        except GhError as e:
            repo_stats[repo] = {"error": str(e)}
            continue
        repo_stats[repo] = {"swept": len(verdicts)}
        for v in verdicts:
            if v["verdict"] == "CLEAN":
                candidates.append({"repo": repo, **v})

    candidates.sort(key=lambda c: c["age_hours"])
    return {
        "repos": repo_stats,
        "candidates": candidates,
        "hours": hours,
        "has_candidates": bool(candidates),
    }


def format_pounce(report: dict) -> str:
    hours = report["hours"]
    if not report["candidates"]:
        lines = [f"osscout pounce - hot window <= {hours}h: no CLEAN candidates", ""]
        for repo, st in report["repos"].items():
            if "error" in st:
                lines.append(f"  {repo}  [ERROR] {st['error']}")
            else:
                lines.append(f"  {repo}  swept {st['swept']} fresh, all claimed/caution")
        return "\n".join(lines)
    lines = [
        f"osscout pounce - hot window <= {hours}h: "
        f"{len(report['candidates'])} CLEAN candidate(s)",
        "",
    ]
    for c in report["candidates"]:
        lines.append(f"  {c['repo']}#{c['number']}  {c['age_hours']}h old  {c['title'][:70]}")
    lines.append("")
    lines.append("CLEAN is a tripwire, not a gate - run `osscout issue <repo> <n>` before any go/no-go.")
    return "\n".join(lines)


def _already_alerted(alert_repo: str, key: str, fetch=gh_json) -> bool:
    try:
        issues = fetch(
            "issue", "list", "--repo", alert_repo, "--state", "open",
            "--limit", "50", "--search", key, "--json", "number,title",
        )
    except GhError:
        return False
    return any(key in i["title"] for i in issues)


def send_alerts(report: dict, alert_repo: str | None, config_path: str | None = None,
                dry_run: bool = False, fetch=gh_json) -> list[dict]:
    """File one issue per candidate in the private alerts repo (deduped by repo#number)."""
    if not report["candidates"]:
        return []
    alert_repo = alert_repo or load_pounce_config(config_path)["alert_repo"]
    sent: list[dict] = []
    for c in report["candidates"]:
        if len(sent) >= 5:
            break
        key = f"{c['repo']}#{c['number']}"
        if _already_alerted(alert_repo, key, fetch):
            continue
        title = f"pounce: {key} - {c['title'][:60]}"
        body = (
            f"{key} is {c['age_hours']}h old and passed the cheap gates "
            f"(no competing PR, no soft-claim, no bot marker).\n\n"
            f"{c['title']}\n\n"
            f"Gate it with `osscout issue {c['repo']} {c['number']}` before any go/no-go.\n"
            f"\n-- \nfiled automatically by `osscout pounce --alert`"
        )
        if dry_run:
            sent.append({"key": key, "title": title, "body": body})
            continue
        proc = subprocess.run(
            ["gh", "issue", "create", "--repo", alert_repo, "--title", title, "--body", body],
            capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            sent.append({"key": key, "error": proc.stderr.strip() or "gh issue create failed"})
        else:
            sent.append({"key": key, "url": proc.stdout.strip()})
    return sent

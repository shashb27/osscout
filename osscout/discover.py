from .culture import scan_repo
from .gh import GhError, gh_json


def starred_repos(login: str) -> list[str]:
    pages = gh_json(
        "api", "--paginate", "--slurp", f"users/{login}/starred?per_page=100"
    )
    if not pages:
        return []
    if isinstance(pages[0], list):
        repos = [r for page in pages for r in page]
    else:
        repos = pages
    return [r["full_name"] for r in repos if r.get("full_name")]


def discover_repos(repos: list[str], limit: int = 20) -> dict:
    results = []
    for repo in repos:
        try:
            results.append(scan_repo(repo, limit))
        except GhError as e:
            results.append({"repo": repo, "verdict": "ERROR", "error": str(e)})
    suggested = [r["repo"] for r in results if r["verdict"] == "PASS"]
    return {"results": results, "suggested": suggested}


def _toml_block(repos: list[str]) -> str:
    lines = ["[watch]", "repos = ["]
    lines += [f'  "{r}",' for r in repos]
    lines.append("]")
    return "\n".join(lines)


def format_discovery(report: dict) -> str:
    lines = [f"osscout discover - {len(report['results'])} candidate repos", ""]
    for r in report["results"]:
        if r["verdict"] == "ERROR":
            lines.append(f"  ERROR        {r['repo']}: {r['error']}")
            continue
        c = r["culture"]
        note = f"{c['distinct_humans']} humans, top {c['top_human_share']:.0%} ({c['top_author']})"
        if r["verdict"] == "SKIP (stale)":
            note += f", stale {r['staleness']['days_since_push']}d"
        lines.append(f"  {r['verdict']:<13} {r['repo']:<40} {note}")
    lines += [
        "",
        f"PASS: {len(report['suggested'])} of {len(report['results'])}"
        " - suggested osscout.toml:",
        "",
        _toml_block(report["suggested"]),
    ]
    return "\n".join(lines)

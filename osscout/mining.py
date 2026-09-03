from .gh import gh_json


def mine_invited(repo: str, limit: int = 20) -> list[dict]:
    wanted = gh_json(
        "issue", "list",
        "--repo", repo,
        "--state", "open",
        "--label", "pull-request wanted",
        "--limit", str(limit),
        "--json", "number,title,updatedAt",
    )
    welcome = gh_json(
        "issue", "list",
        "--repo", repo,
        "--state", "open",
        "-S", '"PR welcome" sort:updated-desc',
        "--limit", str(limit),
        "--json", "number,title,updatedAt",
    )
    seen: dict[int, dict] = {}
    for issue in wanted + welcome:
        seen.setdefault(issue["number"], issue)
    return sorted(seen.values(), key=lambda i: i["updatedAt"], reverse=True)

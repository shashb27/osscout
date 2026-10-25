from .gh import gh_json


def mine_invited(repo: str, limit: int = 20) -> list[dict]:
    wanted = gh_json(
        "issue", "list",
        "--repo", repo,
        "--state", "open",
        "--label", "pull-request wanted",
        "--limit", str(limit),
        "--json", "number,title,updatedAt,assignees",
    )
    welcome = gh_json(
        "issue", "list",
        "--repo", repo,
        "--state", "open",
        "-S", '"PR welcome" sort:updated-desc',
        "--limit", str(limit),
        "--json", "number,title,updatedAt,assignees",
    )
    seen: dict[int, dict] = {}
    for issue in wanted + welcome:
        seen.setdefault(issue["number"], issue)
    return sorted(seen.values(), key=lambda i: i["updatedAt"], reverse=True)


def _assignees(issue: dict) -> list[str]:
    return [a.get("login", "?") for a in issue.get("assignees") or []]


def format_mine(repo: str, issues: list[dict]) -> str:
    lines = [f"osscout mine {repo} - maintainer invitations: {len(issues)}", ""]
    if not issues:
        lines.append("no 'PR welcome' / 'pull-request wanted' invitations found")
        return "\n".join(lines)
    open_items = [i for i in issues if not _assignees(i)]
    assigned_items = [i for i in issues if _assignees(i)]
    for i in open_items:
        lines.append(f"  #{i['number']}  {i['updatedAt'][:10]}  {i['title'][:90]}")
    for i in assigned_items:
        who = ", ".join(_assignees(i))
        lines.append(
            f"  #{i['number']}  {i['updatedAt'][:10]}  "
            f"[assigned to {who}]  {i['title'][:90]}"
        )
    if assigned_items:
        lines.append("")
        lines.append(
            f"{len(assigned_items)} assigned (lane taken) - listed last; "
            "skip unless the assignee stands down"
        )
    first = open_items[0]["number"] if open_items else issues[0]["number"]
    lines += [
        "",
        f"gate any promising one with: osscout issue {repo} {first}",
    ]
    return "\n".join(lines)

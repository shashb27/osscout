import datetime as dt
from pathlib import Path

import pytest

from osscout.watch import (
    format_watch,
    load_config,
    run_watch,
    sweep_repo,
)

NOW = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.timezone.utc)


def _issue(number, title="t", labels=(), comments=0, days_old=1):
    return {
        "number": number,
        "title": title,
        "labels": [{"name": n} for n in labels],
        "comments": comments,
        "createdAt": (NOW - dt.timedelta(days=days_old)).isoformat().replace("+00:00", "Z"),
    }


def _pr(number, state, author="someone", closed_days_ago=None, title="fix"):
    pr = {"number": number, "state": state, "author": {"login": author}, "title": title}
    if closed_days_ago is not None:
        pr["closedAt"] = (NOW - dt.timedelta(days=closed_days_ago)).isoformat().replace("+00:00", "Z")
    return pr


class FakeFetch:
    def __init__(self, issues, prs_by_issue=None, comments_by_issue=None):
        self.issues = issues
        self.prs_by_issue = prs_by_issue or {}
        self.comments_by_issue = comments_by_issue or {}
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == "issue" and args[1] == "list":
            return self.issues
        if args[0] == "pr":
            number = int(args[7])
            return self.prs_by_issue.get(number, [])
        if args[0] == "issue" and args[1] == "view":
            number = int(args[2])
            return {"comments": self.comments_by_issue.get(number, [])}
        raise AssertionError(f"unexpected gh call: {args}")


def _comment(body, login="someone", association="NONE"):
    return {"body": body, "author": {"login": login}, "authorAssociation": association}


def test_hard_stop_label_short_circuits():
    fetch = FakeFetch([_issue(1, labels=["no-new-fix-pr"], comments=5)])
    result = sweep_repo("o/r", days=7, limit=10, fetch=fetch, now=NOW)
    assert result[0]["verdict"] == "TAKEN"
    assert "no-new-fix-pr" in result[0]["why"]
    assert len(fetch.calls) == 1  # no PR search, no comment fetch


def test_open_pr_marks_taken():
    fetch = FakeFetch([_issue(2)], prs_by_issue={2: [_pr(10, "OPEN", author="farm")]})
    result = sweep_repo("o/r", days=7, limit=10, fetch=fetch, now=NOW)
    assert result[0]["verdict"] == "TAKEN"
    assert "open PR #10 by farm" in result[0]["why"]


def test_recent_closed_pr_marks_taken():
    fetch = FakeFetch([_issue(3)], prs_by_issue={3: [_pr(11, "CLOSED", closed_days_ago=10)]})
    result = sweep_repo("o/r", days=7, limit=10, fetch=fetch, now=NOW)
    assert result[0]["verdict"] == "TAKEN"


def test_merged_pr_marks_taken():
    fetch = FakeFetch([_issue(4)], prs_by_issue={4: [_pr(12, "MERGED")]})
    result = sweep_repo("o/r", days=7, limit=10, fetch=fetch, now=NOW)
    assert result[0]["verdict"] == "TAKEN"
    assert "merged fix PR #12" in result[0]["why"]


def test_old_closed_pr_marks_caution():
    fetch = FakeFetch([_issue(5)], prs_by_issue={5: [_pr(13, "CLOSED", closed_days_ago=200)]})
    result = sweep_repo("o/r", days=7, limit=10, fetch=fetch, now=NOW)
    assert result[0]["verdict"] == "CAUTION"
    assert "old closed PR #13" in result[0]["why"]


def test_confirmed_soft_claim_marks_taken():
    fetch = FakeFetch(
        [_issue(6, comments=2)],
        comments_by_issue={
            6: [
                _comment("I'd like to work on this!", login="extern"),
                _comment("a PR is welcome", login="maint", association="MEMBER"),
            ]
        },
    )
    result = sweep_repo("o/r", days=7, limit=10, fetch=fetch, now=NOW)
    assert result[0]["verdict"] == "TAKEN"
    assert "claimed by extern, affirmed by maint" in result[0]["why"]


def test_unconfirmed_claim_marks_caution():
    fetch = FakeFetch(
        [_issue(7, comments=1)],
        comments_by_issue={7: [_comment("may I work on this?", login="curious")]},
    )
    result = sweep_repo("o/r", days=7, limit=10, fetch=fetch, now=NOW)
    assert result[0]["verdict"] == "CAUTION"
    assert "unconfirmed claim by curious" in result[0]["why"]


def test_bot_queue_marker_marks_taken():
    fetch = FakeFetch(
        [_issue(8, comments=1)],
        comments_by_issue={8: [_comment("clawsweeper: implementation worker is queued", login="clawsweeper")]},
    )
    result = sweep_repo("o/r", days=7, limit=10, fetch=fetch, now=NOW)
    assert result[0]["verdict"] == "TAKEN"


def test_clean_issue():
    fetch = FakeFetch([_issue(9, comments=3)], comments_by_issue={9: [_comment("ping?")]})
    result = sweep_repo("o/r", days=7, limit=10, fetch=fetch, now=NOW)
    assert result[0]["verdict"] == "CLEAN"
    assert result[0]["why"] == "-"


def test_days_filter_and_limit():
    issues = [_issue(20, days_old=1), _issue(21, days_old=6), _issue(22, days_old=30), _issue(23, days_old=2)]
    fetch = FakeFetch(issues)
    result = sweep_repo("o/r", days=7, limit=2, fetch=fetch, now=NOW)
    assert [r["number"] for r in result] == [20, 23]


def test_error_repo_is_reported_not_raised():
    class BoomFetch:
        def __call__(self, *args):
            from osscout.gh import GhError
            raise GhError("boom")

    report = run_watch(["o/r"], 7, 10, fetch=BoomFetch(), now=NOW)
    assert report["repos"]["o/r"] == {"error": "boom"}
    out = format_watch(report)
    assert "[ERROR]" in out and "boom" in out


def test_run_watch_summary_counts():
    fetch = FakeFetch(
        [_issue(1), _issue(2, comments=1)],
        prs_by_issue={1: [_pr(30, "OPEN")]},
        comments_by_issue={2: [_comment("nice repro")], },
    )
    report = run_watch(["o/r"], 7, 10, fetch=fetch, now=NOW)
    out = format_watch(report)
    assert "1 taken, 0 caution, 1 clean" in out


def test_load_config_explicit(tmp_path: Path):
    cfg = tmp_path / "osscout.toml"
    cfg.write_text(
        '[watch]\nrepos = ["a/b", "c/d"]\ndays = 3\nlimit = 5\n', encoding="utf-8"
    )
    loaded = load_config(str(cfg))
    assert loaded["repos"] == ["a/b", "c/d"]
    assert loaded["days"] == 3
    assert loaded["limit"] == 5


def test_load_config_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.toml"))


def test_run_watch_uses_config_repos(tmp_path: Path):
    cfg = tmp_path / "osscout.toml"
    cfg.write_text('[watch]\nrepos = ["x/y"]\n', encoding="utf-8")
    fetch = FakeFetch([_issue(50)])
    report = run_watch(None, None, None, config_path=str(cfg), fetch=fetch, now=NOW)
    assert list(report["repos"].keys()) == ["x/y"]


def test_run_watch_cli_repos_override_config(tmp_path: Path):
    cfg = tmp_path / "osscout.toml"
    cfg.write_text('[watch]\nrepos = ["x/y"]\n', encoding="utf-8")
    fetch = FakeFetch([_issue(50)])
    report = run_watch(["z/w"], None, None, config_path=str(cfg), fetch=fetch, now=NOW)
    assert list(report["repos"].keys()) == ["z/w"]

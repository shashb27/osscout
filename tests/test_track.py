import os

import pytest

import osscout.track as track_mod
from osscout.track import (
    autoseed_prs,
    check_contribution,
    format_track,
    load_ledger,
    merge_entries,
    run_track,
)
from osscout.gh import GhError

RECENT = "2026-09-03T00:00:00Z"
OLD = "2026-08-20T00:00:00Z"


def _fake_gh(monkeypatch, prs=None, issues=None, user="shashb27", search=None,
             pr_search=None):
    prs = prs or {}
    issues = issues or {}
    search = search if search is not None else []
    pr_search = pr_search or {}

    def fake(*args):
        if args[0] == "api":
            return {"login": user}
        if args[0] == "search":
            return search
        if args[0] == "pr" and args[1] == "view":
            number = int(args[2])
            if number not in prs:
                raise GhError(f"gh pr view failed for {number}")
            return prs[number]
        if args[0] == "issue" and args[1] == "view":
            number = int(args[2])
            if number not in issues:
                raise GhError(f"gh issue view failed for {number}")
            return issues[number]
        if args[0] == "pr" and args[1] == "list":
            key = int(args[7]) if len(args) > 7 else 0
            return pr_search.get(key, [])
        raise AssertionError(f"unexpected gh call: {args}")

    monkeypatch.setattr(track_mod, "gh_json", fake)
    return fake


def _pr(state="OPEN", comments=None, reviews=None, review_decision="",
        rollup=None, updated=RECENT):
    return {
        "state": state,
        "reviewDecision": review_decision,
        "comments": comments or [],
        "reviews": reviews or [],
        "statusCheckRollup": rollup or [],
        "updatedAt": updated,
    }


def _c(who, when=RECENT):
    return {"createdAt": when, "author": {"login": who}}


def test_pr_quiet_when_we_were_last(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(comments=[_c("shashb27")])})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "quiet"


def test_pr_attention_on_foreign_comment(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(comments=[_c("maintainer1")])})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "ATTENTION"
    assert "maintainer1" in r["detail"]


def test_pr_merged_is_done(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(state="MERGED")})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "DONE"


def test_pr_changes_requested(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(review_decision="CHANGES_REQUESTED",
                                      comments=[_c("shashb27")])})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "ATTENTION"
    assert "changes requested" in r["detail"]


def test_pr_ci_failing_is_shown_not_attention(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(
        rollup=[{"name": "ci", "conclusion": "FAILURE"},
                {"name": "lint", "conclusion": "SUCCESS"}])})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "quiet"
    assert "1/2 failing" in r["detail"]


def test_competing_pr_on_parent_issue(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr()}, pr_search={37: [
        {"number": 5, "state": "OPEN", "author": {"login": "shashb27"}},
        {"number": 9, "state": "OPEN", "author": {"login": "someone"}},
    ]})
    r = check_contribution(
        {"repo": "o/r", "number": 5, "kind": "pr", "issue": 37},
        "shashb27", None, None)
    assert r["status"] == "ATTENTION"
    assert "competing on #37" in r["detail"]


def test_issue_comment_reply_is_attention(monkeypatch):
    _fake_gh(monkeypatch, issues={42: {"state": "OPEN", "comments": [
        _c("shashb27", OLD), _c("royy92")]}})
    r = check_contribution({"repo": "o/r", "number": 42, "kind": "issue-comment"},
                           "shashb27", None, None)
    assert r["status"] == "ATTENTION"
    assert "royy92" in r["detail"]


def test_upstream_merged_is_attention(monkeypatch):
    _fake_gh(monkeypatch, issues={43: {"state": "MERGED", "comments": []}})
    r = check_contribution({"repo": "o/r", "number": 43, "kind": "upstream"},
                           "shashb27", None, None)
    assert r["status"] == "ATTENTION"
    assert "act" in r["detail"]


def test_gh_error_is_error_status(monkeypatch):
    _fake_gh(monkeypatch, prs={})
    r = check_contribution({"repo": "o/r", "number": 99, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "ERROR"


def test_autoseed_parses_search(monkeypatch):
    _fake_gh(monkeypatch, search=[
        {"repository": {"nameWithOwner": "o/r"}, "number": 5, "title": "t"},
        {"number": 6, "title": "no repo"},
    ])
    seeded = autoseed_prs(None)
    assert seeded == [{"repo": "o/r", "number": 5, "kind": "pr",
                       "note": "t", "auto": True}]


def test_merge_entries_ledger_wins(monkeypatch):
    ledger = [{"repo": "o/r", "number": 5, "kind": "pr", "issue": 37}]
    seeded = [{"repo": "o/r", "number": 5, "kind": "pr", "auto": True},
              {"repo": "x/y", "number": 9, "kind": "pr", "auto": True}]
    merged = merge_entries(ledger, seeded)
    assert len(merged) == 2
    assert merged[0] is ledger[0]


def test_run_track_and_format(monkeypatch, tmp_path):
    ledger = tmp_path / "contributions.toml"
    ledger.write_text(
        '[[contribution]]\nrepo = "o/r"\nnumber = 5\nkind = "pr"\n',
        encoding="utf-8",
    )
    _fake_gh(monkeypatch, prs={5: _pr(comments=[_c("shashb27")])})
    report = run_track(str(ledger), autoseed=False, fetch=None)
    assert report["ledger_count"] == 1
    out = format_track(report)
    assert "o/r#5" in out
    assert "nothing needs attention" in out


def test_run_track_no_entries(monkeypatch, tmp_path):
    ledger = tmp_path / "contributions.toml"
    ledger.write_text("", encoding="utf-8")
    _fake_gh(monkeypatch, search=[])
    with pytest.raises(ValueError):
        run_track(str(ledger), autoseed=True, fetch=None)


def test_ledger_missing_explicit_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_ledger(str(tmp_path / "nope.toml"))


def test_ledger_bad_kind(tmp_path):
    p = tmp_path / "contributions.toml"
    p.write_text('[[contribution]]\nrepo = "o/r"\nnumber = 1\nkind = "wat"\n',
                 encoding="utf-8")
    with pytest.raises(ValueError):
        load_ledger(str(p))


def test_cli_exit_code_attention(monkeypatch, capsys, tmp_path):
    from osscout.cli import main

    ledger = tmp_path / "contributions.toml"
    ledger.write_text(
        '[[contribution]]\nrepo = "o/r"\nnumber = 5\nkind = "pr"\n',
        encoding="utf-8",
    )
    _fake_gh(monkeypatch, prs={5: _pr(comments=[_c("reviewer1")])})
    assert main(["track", "--config", str(ledger), "--no-autoseed"]) == 1
    assert "1 need attention" in capsys.readouterr().out

import os

import pytest

import osscout.track as track_mod
from osscout.track import (
    autoseed_prs,
    check_contribution,
    format_track,
    load_ledger,
    merge_entries,
    reconcile_ledger,
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


def _c(who, when=RECENT, body=None):
    c = {"createdAt": when, "author": {"login": who}}
    if body is not None:
        c["body"] = body
    return c


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


def test_bot_comment_not_last_activity(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(comments=[
        _c("shashb27", OLD),
        _c("Enough1122", body="AI code review - automated review for reference, author can ignore or act on any point"),
    ])})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "quiet"
    assert "last: me" in r["detail"]


def test_bot_comment_falls_back_to_previous_human(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(comments=[
        _c("maintainer1", OLD),
        _c("Enough1122", body="generated by AI during triage - flagging for maintainer eyes"),
    ])})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "ATTENTION"
    assert "maintainer1" in r["detail"]


def test_human_comment_after_bot_still_counts(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(comments=[
        _c("reviewbot", OLD, body="AI code review: looks fine to me"),
        _c("maintainer1"),
    ])})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "ATTENTION"
    assert "maintainer1" in r["detail"]


def test_bot_prefix_pattern_filtered(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(comments=[
        _c("shashb27", OLD),
        _c("triager", body="This was generated by AI during triage. No human review yet."),
    ])})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "quiet"


def test_bot_review_body_filtered(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(
        comments=[_c("shashb27", OLD)],
        reviews=[{"submittedAt": RECENT, "author": {"login": "Enough1122"},
                  "body": "AI code review - automated review for reference"}],
    )})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "quiet"
    assert "last: me" in r["detail"]


def test_only_bot_activity_is_quiet(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(
        comments=[_c("reviewbot", OLD, body="AI code review: see above")],
        updated=OLD,
    )})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "quiet"


def test_human_comment_with_body_still_counts(monkeypatch):
    _fake_gh(monkeypatch, prs={5: _pr(comments=[
        _c("maintainer1", body="Thanks, please rebase on main")])})
    r = check_contribution({"repo": "o/r", "number": 5, "kind": "pr"},
                           "shashb27", None, None)
    assert r["status"] == "ATTENTION"


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
    report = run_track(str(ledger), autoseed=False, fetch=None,
                       records_dir=str(tmp_path / "no-records"))
    assert report["ledger_count"] == 1
    assert report["reconcile"] == []
    out = format_track(report)
    assert "o/r#5" in out
    assert "nothing needs attention" in out


def test_run_track_no_entries(monkeypatch, tmp_path):
    ledger = tmp_path / "contributions.toml"
    ledger.write_text("", encoding="utf-8")
    _fake_gh(monkeypatch, search=[])
    with pytest.raises(ValueError):
        run_track(str(ledger), autoseed=True, fetch=None)


LEDGER = [{"repo": "psf/black", "number": 5386, "kind": "pr", "issue": 5379}]


def _records(tmp_path):
    d = tmp_path / "oss-contributions"
    d.mkdir()
    (d / "black-5379-pr.md").write_text(
        "Issue: psf/black#5379. Our PR #5386 follows the maintainer route.\n",
        encoding="utf-8",
    )
    (d / "hermes-100955-comment.md").write_text(
        "# Draft comment - NousResearch/hermes-agent #100955\n",
        encoding="utf-8",
    )
    return d


def test_reconcile_flags_missing_reference(tmp_path):
    d = _records(tmp_path)
    warnings = reconcile_ledger(LEDGER, str(d))
    assert warnings == [
        f"reconcile: hermes-agent#100955 mentioned in "
        f"{d / 'hermes-100955-comment.md'} but missing from ledger"
    ]


def test_reconcile_in_ledger_via_issue_field_is_silent(tmp_path):
    d = _records(tmp_path)
    assert all("black" not in w for w in reconcile_ledger(LEDGER, str(d)))


def test_reconcile_missing_records_dir_is_noop(tmp_path):
    assert reconcile_ledger(LEDGER, str(tmp_path / "nope")) == []


def test_reconcile_bare_repo_form(tmp_path):
    d = tmp_path / "records"
    d.mkdir()
    (d / "notes.md").write_text(
        "stale on tqdm#1743, also covered by black#5379 upstream\n",
        encoding="utf-8",
    )
    warnings = reconcile_ledger(LEDGER, d)
    assert len(warnings) == 1
    assert warnings[0].startswith("reconcile: tqdm#1743 mentioned in ")


def test_reconcile_ignores_non_markdown(tmp_path):
    d = tmp_path / "records"
    d.mkdir()
    (d / "hermes-100955.patch").write_text("diff on NousResearch/hermes-agent #100955\n",
                                           encoding="utf-8")
    assert reconcile_ledger(LEDGER, d) == []


def test_reconcile_dedupes_short_names(tmp_path):
    d = tmp_path / "records"
    d.mkdir()
    (d / "a.md").write_text("NousResearch/hermes-agent #100955 design question\n",
                            encoding="utf-8")
    (d / "b.md").write_text("also hermes-agent#100955\n", encoding="utf-8")
    warnings = reconcile_ledger(LEDGER, d)
    assert len(warnings) == 1
    assert "a.md" in warnings[0]


def test_run_track_reports_reconcile(monkeypatch, tmp_path):
    ledger = tmp_path / "contributions.toml"
    ledger.write_text(
        '[[contribution]]\nrepo = "psf/black"\nnumber = 5386\nkind = "pr"\nissue = 5379\n',
        encoding="utf-8",
    )
    d = _records(tmp_path)
    _fake_gh(monkeypatch, prs={5386: _pr(comments=[_c("shashb27")])})
    report = run_track(str(ledger), autoseed=False, fetch=None, records_dir=str(d))
    assert len(report["reconcile"]) == 1
    assert "hermes-agent#100955" in report["reconcile"][0]
    out = format_track(report)
    assert "reconcile: hermes-agent#100955 mentioned in" in out


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
    monkeypatch.chdir(tmp_path)
    assert main(["track", "--config", str(ledger), "--no-autoseed"]) == 1
    assert "1 need attention" in capsys.readouterr().out

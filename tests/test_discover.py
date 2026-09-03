import pytest

import osscout.culture as culture
import osscout.discover as discover_mod
from osscout.discover import (
    _toml_block,
    discover_repos,
    format_discovery,
    starred_repos,
)
from osscout.gh import GhError

RECENT = "2026-09-01T00:00:00Z"
ANCIENT = "2020-01-01T00:00:00Z"


def _prs(*logins):
    return [{"author": {"login": l}} for l in logins]


def _fake_gh(monkeypatch, prs_by_repo, pushed_by_repo):
    def fake(*args):
        if args[0] == "pr":
            repo = args[3]
            if repo not in prs_by_repo:
                raise GhError(f"gh pr list failed for {repo}")
            return prs_by_repo[repo]
        if args[0] == "repo":
            repo = args[2]
            return {"pushedAt": pushed_by_repo[repo]}
        raise AssertionError(f"unexpected gh call: {args}")

    monkeypatch.setattr(culture, "gh_json", fake)
    return fake


def test_discover_suggests_only_pass(monkeypatch):
    _fake_gh(
        monkeypatch,
        {
            "good/repo": _prs("a", "b", "c", "d"),
            "one/person": _prs("solo", "solo", "solo"),
            "two/humans": _prs("a", "a", "b", "b"),
            "stale/but-good": _prs("a", "b", "c", "d"),
        },
        {
            "good/repo": RECENT,
            "one/person": RECENT,
            "two/humans": RECENT,
            "stale/but-good": ANCIENT,
        },
    )
    report = discover_repos(["good/repo", "one/person", "two/humans", "stale/but-good"])
    assert report["suggested"] == ["good/repo"]
    by_repo = {r["repo"]: r["verdict"] for r in report["results"]}
    assert by_repo["good/repo"] == "PASS"
    assert by_repo["one/person"] == "SKIP"
    assert by_repo["two/humans"] == "BORDERLINE"
    assert by_repo["stale/but-good"] == "SKIP (stale)"


def test_discover_reports_gh_errors(monkeypatch):
    _fake_gh(monkeypatch, {"known/repo": _prs("a", "b", "c")}, {"known/repo": RECENT})
    report = discover_repos(["known/repo", "gone/repo"])
    errors = [r for r in report["results"] if r["verdict"] == "ERROR"]
    assert len(errors) == 1
    assert errors[0]["repo"] == "gone/repo"
    assert report["suggested"] == ["known/repo"]


def test_format_discovery_contains_toml(monkeypatch):
    _fake_gh(
        monkeypatch,
        {"good/repo": _prs("a", "b", "c"), "bad/repo": _prs("solo", "solo")},
        {"good/repo": RECENT, "bad/repo": RECENT},
    )
    report = discover_repos(["good/repo", "bad/repo"])
    out = format_discovery(report)
    assert "[watch]" in out
    assert '"good/repo",' in out
    assert '"bad/repo"' not in out
    assert "PASS: 1 of 2" in out


def test_starred_repos_flattens_pages(monkeypatch):
    pages = [
        [{"full_name": "a/b"}, {"full_name": "c/d"}],
        [{"full_name": "e/f"}],
    ]
    monkeypatch.setattr(discover_mod, "gh_json", lambda *a: pages)
    assert starred_repos("someone") == ["a/b", "c/d", "e/f"]


def test_starred_repos_handles_flat_list(monkeypatch):
    monkeypatch.setattr(
        discover_mod, "gh_json", lambda *a: [{"full_name": "x/y"}]
    )
    assert starred_repos("someone") == ["x/y"]


def test_starred_repos_skips_unnamed(monkeypatch):
    monkeypatch.setattr(
        discover_mod, "gh_json", lambda *a: [{"full_name": "x/y"}, {"id": 5}]
    )
    assert starred_repos("someone") == ["x/y"]


def test_toml_block():
    assert _toml_block(["a/b", "c/d"]) == '[watch]\nrepos = [\n  "a/b",\n  "c/d",\n]'


def test_no_candidates_is_an_error(capsys):
    from osscout.cli import main

    assert main(["discover"]) == 2
    assert "no candidates" in capsys.readouterr().err

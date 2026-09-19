from datetime import datetime, timedelta, timezone

import osscout.sweep as sweep_mod
from osscout.culture import analyze_authors, is_bot, repo_staleness
from osscout.sweep import classify_prs, issue_signals, scan_issue

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def _pr(number, state, author, closed_days=None, title="fix thing"):
    closed_at = None
    if closed_days is not None:
        closed_at = (NOW - timedelta(days=closed_days)).isoformat()
    return {
        "number": number,
        "state": state,
        "author": {"login": author},
        "title": title,
        "closedAt": closed_at,
    }


class TestIsBot:
    def test_app_bots(self):
        assert is_bot("app/dependabot")
        assert is_bot("dependabot[bot]")
        assert is_bot("eslintbot")

    def test_humans(self):
        assert not is_bot("shashb27")
        assert not is_bot("teknium1")

    def test_empty(self):
        assert is_bot("")


class TestAnalyzeAuthors:
    def test_distributed_external_culture_passes(self):
        logins = ["a", "b", "c", "a", "b", "d", "e", "f", "c", "a"]
        r = analyze_authors(logins)
        assert r["verdict"] == "PASS"
        assert r["distinct_humans"] == 6
        assert ("a", 3) in r["repeat_contributors"]

    def test_single_maintainer_dominance_skips(self):
        logins = ["kdeldycke"] * 16 + ["Rowlando13"] * 3 + ["casperdcl"]
        r = analyze_authors(logins)
        assert r["verdict"] == "SKIP"
        assert r["top_share"] >= 0.8

    def test_bots_excluded(self):
        logins = ["app/dependabot"] * 15 + ["nateprewitt"] * 3 + ["a", "b"]
        r = analyze_authors(logins)
        assert r["bots"] == 15
        assert r["verdict"] == "BORDERLINE"

    def test_moderate_dominance_borderline(self):
        logins = ["radoering"] * 12 + list("abcdefg")
        r = analyze_authors(logins)
        assert r["verdict"] == "BORDERLINE"

    def test_empty(self):
        assert analyze_authors([])["verdict"] == "NO DATA"


class TestRepoStaleness:
    def test_stale(self):
        pushed = (NOW - timedelta(days=120)).isoformat()
        assert repo_staleness(pushed, NOW)["stale"] is True

    def test_fresh(self):
        pushed = (NOW - timedelta(days=3)).isoformat()
        assert repo_staleness(pushed, NOW)["stale"] is False


class TestClassifyPrs:
    def test_clean_is_go(self):
        assert classify_prs([], NOW)["verdict"] == "GO"

    def test_open_pr_blocks(self):
        r = classify_prs([_pr(101, "OPEN", "farm-bot")], NOW)
        assert r["verdict"] == "NO-GO"
        assert len(r["open"]) == 1

    def test_recent_closed_blocks(self):
        r = classify_prs([_pr(101, "CLOSED", "someone", closed_days=30)], NOW)
        assert r["verdict"] == "NO-GO"
        assert len(r["recent_closed"]) == 1

    def test_old_closed_is_caution(self):
        r = classify_prs([_pr(101, "CLOSED", "someone", closed_days=400)], NOW)
        assert r["verdict"] == "CAUTION"
        assert len(r["old_closed"]) == 1

    def test_merged_means_likely_fixed(self):
        r = classify_prs([_pr(101, "MERGED", "maintainer", closed_days=1)], NOW)
        assert r["verdict"] == "LIKELY FIXED"

    def test_dependency_bot_noise_filtered(self):
        prs = [
            _pr(1, "CLOSED", "pyup-bot", closed_days=1, title="Tests: Requirements: Update sphinx to 1.7.1"),
            _pr(2, "OPEN", "farm", title="fix the real thing"),
        ]
        r = classify_prs(prs, NOW)
        assert len(r["noise_filtered"]) == 1
        assert r["verdict"] == "NO-GO"

    def test_merged_dominates_open(self):
        r = classify_prs([_pr(1, "MERGED", "m"), _pr(2, "OPEN", "f")], NOW)
        assert r["verdict"] == "LIKELY FIXED"


class TestIssueSignals:
    def _comments(self, *bodies):
        return [{"body": b} for b in bodies]

    def test_open_clean_issue_ok(self):
        r = issue_signals("OPEN", ["type/bug"], [])
        assert r["verdict"] == "OK"
        assert r["comment_count"] == 0

    def test_closed_issue_dead(self):
        assert issue_signals("CLOSED", [], [])["verdict"] == "DEAD"

    def test_bot_queue_marker_blocks(self):
        comments = self._comments("clawsweeper:linked-pr-open on this one")
        r = issue_signals("OPEN", [], comments)
        assert r["verdict"] == "NO-GO"
        assert "clawsweeper:linked-pr-open" in r["bot_queue_markers"]

    def test_hard_stop_label_blocks(self):
        r = issue_signals("OPEN", ["no-new-fix-pr"], [])
        assert r["verdict"] == "NO-GO"
        assert r["hard_stop_labels"] == ["no-new-fix-pr"]


def _comment(body, login="someone", assoc="NONE"):
    return {"author_association": assoc, "user": {"login": login}, "body": body}


class TestSoftClaim:
    def test_confirmed_claim_is_nogo_with_names(self):
        comments = [
            _comment("I'm interested in this issue. Would it be okay if I work on it?", login="uncoolclub", assoc="CONTRIBUTOR"),
            _comment("Thanks, a PR is welcome.", login="fasttime", assoc="MEMBER"),
        ]
        r = issue_signals("OPEN", [], comments)
        assert r["verdict"] == "NO-GO"
        assert r["soft_claim"] == {"claimed_by": "uncoolclub", "affirmed_by": "fasttime"}

    def test_unconfirmed_claim_keeps_verdict_and_records_claim(self):
        comments = [_comment("@casperdcl LMK what you think!", login="korbonits")]
        r = issue_signals("OPEN", [], comments)
        assert r["verdict"] == "OK"
        assert r["soft_claim"] == {"claimed_by": "korbonits", "affirmed_by": None}

    def test_no_claim_phrase_means_no_soft_claim(self):
        comments = [_comment("Confirmed the repro: purge keys reclamation solely on status.", login="shashb27")]
        r = issue_signals("OPEN", [], comments)
        assert r["soft_claim"] is None
        assert r["verdict"] == "OK"

    def test_affirmation_without_claim_is_not_soft_claim(self):
        comments = [_comment("A PR is welcome if anyone wants to pick this up.", login="fasttime", assoc="MEMBER")]
        r = issue_signals("OPEN", [], comments)
        assert r["soft_claim"] is None
        assert r["verdict"] == "OK"

    def test_maintainer_claim_affirmed_by_second_maintainer(self):
        comments = [
            _comment("I'd like to work on this", login="maint-a", assoc="MEMBER"),
            _comment("Go ahead!", login="maint-b", assoc="COLLABORATOR"),
        ]
        r = issue_signals("OPEN", [], comments)
        assert r["verdict"] == "NO-GO"
        assert r["soft_claim"] == {"claimed_by": "maint-a", "affirmed_by": "maint-b"}

    def test_affirmation_must_come_after_claim(self):
        comments = [
            _comment("PR is welcome!", login="fasttime", assoc="MEMBER"),
            _comment("I'd like to work on this", login="uncoolclub"),
        ]
        r = issue_signals("OPEN", [], comments)
        assert r["verdict"] == "OK"
        assert r["soft_claim"] == {"claimed_by": "uncoolclub", "affirmed_by": None}

    def test_non_maintainer_affirmation_does_not_confirm(self):
        comments = [
            _comment("Can I work on this?", login="ext"),
            _comment("Please do!", login="other-ext", assoc="CONTRIBUTOR"),
        ]
        r = issue_signals("OPEN", [], comments)
        assert r["verdict"] == "OK"
        assert r["soft_claim"]["affirmed_by"] is None

    def test_owner_and_collaborator_affirmations_confirm(self):
        comments = [
            _comment("I'll take this", login="ext"),
            _comment("Please do.", login="the-owner", assoc="OWNER"),
        ]
        assert issue_signals("OPEN", [], comments)["soft_claim"]["affirmed_by"] == "the-owner"
        comments[1] = _comment("You can work on it", login="the-collab", assoc="COLLABORATOR")
        assert issue_signals("OPEN", [], comments)["soft_claim"]["affirmed_by"] == "the-collab"

    def test_gh_style_comment_keys_supported(self):
        comments = [
            {"authorAssociation": "CONTRIBUTOR", "author": {"login": "uncoolclub"}, "body": "I'll take this"},
            {"authorAssociation": "MEMBER", "author": {"login": "fasttime"}, "body": "Feel free to open a PR"},
        ]
        r = issue_signals("OPEN", [], comments)
        assert r["verdict"] == "NO-GO"
        assert r["soft_claim"] == {"claimed_by": "uncoolclub", "affirmed_by": "fasttime"}

    def test_curly_apostrophe_claim_matches(self):
        comments = [{"body": "I\u2019d like to investigate this"}]
        r = issue_signals("OPEN", [], comments)
        assert r["soft_claim"] == {"claimed_by": "?", "affirmed_by": None}

    def test_confirmed_claim_does_not_override_dead(self):
        comments = [
            _comment("I'll take this", login="ext"),
            _comment("Assigned to you!", login="maint", assoc="MEMBER"),
        ]
        r = issue_signals("CLOSED", [], comments)
        assert r["verdict"] == "DEAD"
        assert r["soft_claim"]["affirmed_by"] == "maint"


class TestReporterFixBody:
    def test_with_this_change_phrase(self):
        body = "Before: 412 ms. With this change: 388 ms and AVX_VNNI = 1"
        r = issue_signals("OPEN", [], [], body)
        assert r["reporter_fix"] is True
        assert r["verdict"] == "CAUTION"

    def test_my_patch_phrase(self):
        r = issue_signals("OPEN", [], [], "My patch drops the status gate, see the diff")
        assert r["reporter_fix"] is True
        assert r["verdict"] == "CAUTION"

    def test_after_this_change_phrase(self):
        r = issue_signals("OPEN", [], [], "After this change the GC tests go green")
        assert r["reporter_fix"] is True
        assert r["verdict"] == "CAUTION"

    def test_patch_attached_phrase(self):
        body = "Proposed fix (patch attached in our local probe; happy to PR it)"
        r = issue_signals("OPEN", [], [], body)
        assert r["reporter_fix"] is True
        assert r["verdict"] == "CAUTION"

    def test_happy_to_pr_phrase(self):
        r = issue_signals("OPEN", [], [], "Verified locally, happy to PR if maintainers agree")
        assert r["reporter_fix"] is True
        assert r["verdict"] == "CAUTION"

    def test_suggested_fix_for_contributors_stays_ok(self):
        body = "Suggested fix: add a win32 branch in resolve() before the media check"
        r = issue_signals("OPEN", [], [], body)
        assert r["reporter_fix"] is False
        assert r["verdict"] == "OK"

    def test_plain_repro_body_stays_ok(self):
        r = issue_signals("OPEN", [], [], "The build fails on Windows with a ValueError")
        assert r["reporter_fix"] is False
        assert r["design_call"] is False
        assert r["verdict"] == "OK"

    def test_does_not_override_dead(self):
        r = issue_signals("CLOSED", [], [], "With this change it works")
        assert r["verdict"] == "DEAD"

    def test_does_not_override_hard_stops(self):
        r = issue_signals("OPEN", ["no-new-fix-pr"], [], "With this change it works")
        assert r["verdict"] == "NO-GO"


class TestDesignCallBody:
    def test_input_welcome_before_any_code(self):
        body = "@sgugger your input would be welcome before any code is written"
        r = issue_signals("OPEN", [], [], body)
        assert r["design_call"] is True
        assert r["verdict"] == "CAUTION"

    def test_mention_plus_proposed_direction(self):
        body = "@jbrockmendel the proposed direction is to consolidate the owners"
        r = issue_signals("OPEN", [], [], body)
        assert r["design_call"] is True
        assert r["verdict"] == "CAUTION"

    def test_proposed_direction_without_mention_is_not_design_call(self):
        r = issue_signals("OPEN", [], [], "The proposed direction is to refactor the lexer")
        assert r["design_call"] is False
        assert r["verdict"] == "OK"

    def test_mention_without_proposed_direction_is_not_design_call(self):
        r = issue_signals("OPEN", [], [], "@maintainer could you take a look at the repro?")
        assert r["design_call"] is False
        assert r["verdict"] == "OK"

    def test_email_address_is_not_a_mention(self):
        body = "Reported to support@fastmail.com - proposed direction attached"
        r = issue_signals("OPEN", [], [], body)
        assert r["design_call"] is False


class TestParkedLabel:
    def test_parked_label_downgrades_ok_to_caution(self):
        r = issue_signals("OPEN", ["p4-enhancement-future 🧨"], [])
        assert r["verdict"] == "CAUTION"
        assert r["parked"] == ["p4-enhancement-future 🧨"]

    def test_backlog_label_downgrades_ok_to_caution(self):
        r = issue_signals("OPEN", ["community-backlog"], [])
        assert r["verdict"] == "CAUTION"
        assert r["parked"] == ["community-backlog"]

    def test_plain_bug_label_stays_ok(self):
        r = issue_signals("OPEN", ["bug"], [])
        assert r["verdict"] == "OK"
        assert r["parked"] == []

    def test_does_not_override_dead(self):
        r = issue_signals("CLOSED", ["parked"], [])
        assert r["verdict"] == "DEAD"
        assert r["parked"] == ["parked"]

    def test_does_not_override_hard_stop_label(self):
        r = issue_signals("OPEN", ["no-new-fix-pr", "parked"], [])
        assert r["verdict"] == "NO-GO"

    def test_scan_issue_parked_label_downgrades_go_to_caution(self, monkeypatch):
        issue = {"state": "OPEN", "title": "some bug",
                 "labels": [{"name": "p4-enhancement-future 🧨"}],
                 "comments": [], "body": ""}
        _fake_issue_gh(monkeypatch, issue)
        r = scan_issue("o/r", 5)
        assert r["verdict"] == "CAUTION"
        assert r["signals"]["parked"] == ["p4-enhancement-future 🧨"]


def _fake_issue_gh(monkeypatch, issue, prs=None):
    prs = prs or []

    def fake(*args):
        if args[0] == "issue":
            return issue
        if args[0] == "pr":
            return prs
        raise AssertionError(f"unexpected gh call: {args}")

    monkeypatch.setattr(sweep_mod, "gh_json", fake)


def _issue(state="OPEN", body="", comments=None):
    return {"state": state, "title": "some bug", "labels": [],
            "comments": comments or [], "body": body}


class TestScanIssueBodyGate:
    def test_reporter_fix_downgrades_go_to_caution(self, monkeypatch):
        _fake_issue_gh(monkeypatch, _issue(body="With this change AVX_VNNI = 1"))
        r = scan_issue("o/r", 5)
        assert r["verdict"] == "CAUTION"
        assert r["signals"]["reporter_fix"] is True

    def test_design_call_downgrades_go_to_caution(self, monkeypatch):
        _fake_issue_gh(
            monkeypatch,
            _issue(body="@maintainer input would be welcome before any code is written"),
        )
        r = scan_issue("o/r", 5)
        assert r["verdict"] == "CAUTION"
        assert r["signals"]["design_call"] is True

    def test_clean_body_stays_go(self, monkeypatch):
        _fake_issue_gh(monkeypatch, _issue(body="crash on startup, repro inside"))
        assert scan_issue("o/r", 5)["verdict"] == "GO"

    def test_open_pr_still_blocks_over_body_caution(self, monkeypatch):
        _fake_issue_gh(
            monkeypatch,
            _issue(body="My patch fixes this"),
            prs=[{"number": 9, "state": "OPEN", "author": {"login": "farm"},
                  "title": "fix", "closedAt": None}],
        )
        assert scan_issue("o/r", 5)["verdict"] == "NO-GO"

import pytest

from osscout.cli import _print_issue, main


def _prs(open_=(), merged=(), recent_closed=(), old_closed=()):
    def _item(n):
        return {"number": n, "state": "OPEN", "author": {"login": "someone"},
                "title": "fix", "closedAt": None}
    return {
        "merged": [_item(n) for n in merged],
        "open": [_item(n) for n in open_],
        "recent_closed": [_item(n) for n in recent_closed],
        "old_closed": [_item(n) for n in old_closed],
        "noise_filtered": [],
    }


def _report(verdict="GO", comment_count=0, prs=None, parked=()):
    return {
        "repo": "o/r",
        "number": 5,
        "title": "some bug",
        "signals": {
            "state": "OPEN",
            "labels": [],
            "comment_count": comment_count,
            "bot_queue_markers": [],
            "hard_stop_labels": [],
            "soft_claim": None,
            "reporter_fix": False,
            "design_call": False,
            "parked": list(parked),
        },
        "prs": prs or _prs(),
        "verdict": verdict,
    }


class TestIssueEvidence:
    def test_go_prints_evidence_and_signals_lines(self, capsys):
        _print_issue(_report(comment_count=3))
        out = capsys.readouterr().out
        assert ("  searched   : 0 PRs across all states "
                "(number + title keywords), 3 comment(s) read") in out
        assert ("  signals    : no competing PRs, no soft-claims, "
                "no bot-queue markers") in out

    def test_evidence_printed_for_every_verdict(self, capsys):
        _print_issue(_report(verdict="NO-GO", comment_count=2,
                             prs=_prs(open_=(9,), merged=(4,))))
        out = capsys.readouterr().out
        assert ("  searched   : 2 PRs across all states "
                "(number + title keywords), 2 comment(s) read") in out
        assert "  signals    : competing PRs found" in out

    def test_parked_caution_line_prints(self, capsys):
        _print_issue(_report(verdict="CAUTION", parked=["p4-enhancement-future 🧨"]))
        out = capsys.readouterr().out
        assert "  caution    : maintainer-parked label: p4-enhancement-future 🧨" in out


class TestArgparse:
    def test_bare_invocation_error_names_command(self, capsys):
        with pytest.raises(SystemExit) as e:
            main([])
        assert e.value.code == 2
        err = capsys.readouterr().err
        assert "the following arguments are required: command" in err
        assert "cmd" not in err

    def test_help_shows_verdict_legend_and_exit_codes(self, capsys):
        with pytest.raises(SystemExit) as e:
            main(["--help"])
        assert e.value.code == 0
        out = capsys.readouterr().out
        for word in ("GO / PASS", "CLEAN", "TAKEN", "CAUTION", "SKIP",
                     "BORDERLINE", "quiet", "exit codes: 0 = GO/PASS/quiet"):
            assert word in out

    def test_issue_number_help(self, capsys):
        with pytest.raises(SystemExit):
            main(["issue", "--help"])
        assert "issue number to gate" in capsys.readouterr().out

    def test_repo_limit_help_names_sample(self, capsys):
        with pytest.raises(SystemExit):
            main(["repo", "--help"])
        assert "merged PRs analyzed" in capsys.readouterr().out

from datetime import datetime, timedelta, timezone

from osscout.pounce import format_pounce, load_pounce_config, run_pounce, send_alerts
from osscout.watch import sweep_repo


class Fake:
    def __init__(self, issues, prs=None):
        self.issues = issues
        self.prs = prs or []

    def __call__(self, *args):
        if args[0] == "issue" and args[1] == "list":
            return self.issues
        if args[0] == "pr" and args[1] == "list":
            # emulates gh's server-side --search <number> filtering
            number = args[args.index("--search") + 1]
            return [p for p in self.prs if number in p["title"]]
        raise AssertionError(f"unexpected gh call: {args}")


NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def _issue(number, hours_old, title="t", comments=0, body=None):
    return {
        "number": number,
        "title": title,
        "labels": [],
        "comments": comments,
        "createdAt": (NOW - timedelta(hours=hours_old)).isoformat().replace("+00:00", "Z"),
        "body": body or "",
    }


def test_pounce_hours_window_filters_old_issues():
    fetch = Fake([_issue(1, hours_old=3), _issue(2, hours_old=30)])
    verdicts = sweep_repo("o/r", 0, 10, fetch, NOW, hours=12)
    assert [v["number"] for v in verdicts] == [1]
    assert verdicts[0]["age_hours"] == 3.0


def test_pounce_reports_only_clean():
    fetch = Fake(
        [_issue(1, hours_old=2, title="clean bug"), _issue(2, hours_old=4, title="taken")],
        prs=[{"number": 9, "state": "OPEN", "author": {"login": "x"},
              "title": "fix 2", "closedAt": None}],
    )
    # the open PR references every issue search (number search is repo-wide),
    # so issue 2 is TAKEN and issue 1 stays CLEAN
    report = run_pounce(["o/r"], 12, 10, fetch=fetch, now=NOW)
    assert report["has_candidates"]
    assert [c["number"] for c in report["candidates"]] == [1]
    text = format_pounce(report)
    assert "1 CLEAN candidate" in text
    assert "clean bug" in text
    assert "tripwire" in text


def test_pounce_no_candidates_exit_summary():
    fetch = Fake([_issue(1, hours_old=5, title="claimed")],
                 prs=[{"number": 9, "state": "OPEN", "author": {"login": "x"},
                       "title": "fix 1", "closedAt": None}])
    report = run_pounce(["o/r"], 12, 10, fetch=fetch, now=NOW)
    assert not report["has_candidates"]
    text = format_pounce(report)
    assert "no CLEAN candidates" in text
    assert "swept 1 fresh" in text


def test_alert_dedup_skips_already_alerted():
    class AlertFetch(Fake):
        def __init__(self, issues, existing_titles):
            super().__init__(issues)
            self.existing_titles = existing_titles

        def __call__(self, *args):
            if args[0] == "issue" and args[1] == "list" and "--search" in args:
                return [{"number": 50, "title": t} for t in self.existing_titles]
            return super().__call__(*args)

    fetch = AlertFetch([_issue(1, hours_old=2, title="new bug")], ["pounce: o/r#1 - old"])
    report = run_pounce(["o/r"], 12, 10, fetch=fetch, now=NOW)
    sent = send_alerts(report, "me/alerts", dry_run=True, fetch=fetch)
    assert sent == []  # deduped: o/r#1 already has an open alert


def test_defaults_cover_sglang():
    cfg = load_pounce_config()
    assert "sgl-project/sglang" in cfg["repos"]
    assert cfg["hours"] == 12

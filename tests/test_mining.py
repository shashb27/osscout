from osscout.mining import format_mine


def _invited(number, updated="2026-09-01T00:00:00Z", title="some invitation"):
    return {"number": number, "updatedAt": updated, "title": title}


def test_format_mine_header_and_footer():
    out = format_mine("o/r", [_invited(7), _invited(8)])
    assert out.startswith("osscout mine o/r - maintainer invitations: 2")
    assert "  #7  2026-09-01  some invitation" in out
    assert "gate any promising one with: osscout issue o/r 7" in out


def test_format_mine_empty_keeps_message_without_footer():
    out = format_mine("o/r", [])
    assert out.startswith("osscout mine o/r - maintainer invitations: 0")
    assert "no 'PR welcome' / 'pull-request wanted' invitations found" in out
    assert "gate any promising one" not in out


def test_format_mine_lists_assigned_last_with_tag():
    taken = {
        "number": 9, "updatedAt": "2026-10-01T00:00:00Z", "title": "claimed lane",
        "assignees": [{"login": "the-assignee"}],
    }
    out = format_mine("o/r", [_invited(7), taken])
    assert "  #7  2026-09-01  some invitation" in out
    assert "[assigned to the-assignee]  claimed lane" in out
    assert out.index("#7") < out.index("#9")
    assert "1 assigned (lane taken)" in out
    assert "gate any promising one with: osscout issue o/r 7" in out


def test_format_mine_all_assigned_points_footer_at_first_anyway():
    taken = {
        "number": 9, "updatedAt": "2026-10-01T00:00:00Z", "title": "claimed",
        "assignees": [{"login": "someone"}],
    }
    out = format_mine("o/r", [taken])
    assert "gate any promising one with: osscout issue o/r 9" in out

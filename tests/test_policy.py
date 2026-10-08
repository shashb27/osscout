import pytest

import osscout.policy as policy_mod
from osscout.cli import main
from osscout.policy import format_policy, scan_policy

LLAMA_TEXT = """\
# AI Usage Policy

> [!IMPORTANT]
>
> AI-generated code is allowed. You are 100% responsible for every line, however it was produced.
>
> Undisclosed AI usage may result in your account being permanently banned from contributing to the project.

If AI is used to generate any portion of the code, contributors must adhere to the following requirements:

1. Explicitly disclose the manner in which AI was employed.
2. Check for an existing PR addressing the same change.
3. Perform a comprehensive manual review prior to submitting the pull request.
4. Be prepared to explain every line of code you submit when asked about it by a maintainer.
5. It is strictly prohibited to use AI to write your posts for you (bug reports, feature requests, pull request descriptions, Github discussions, responding to humans, ...).
"""

PIP_POLICY_TEXT = """\
# Generative AI / LLM Policy

We appreciate that we can't realistically police how you author your pull
requests, which includes whether you employ large-language model (LLM)-based
development tools.

If you use AI tools, disclose it in the pull request.

No LLM bots in `Co-authored-by:`s.
Absolutely no unsupervised agentic tools like OpenClaw.
"""

PIP_TEMPLATE_TEXT = """\
- [ ] I have read and followed the AI_POLICY.md file, and if any AI tools were used, I have disclosed it below.
<!-- If checked and you have used AI tools, add a line below: Assisted-by: <tool name, e.g. Claude> -->
"""

SPHINX_TEMPLATE_TEXT = """\
## AI Disclosure

If AI was used in the preparation of this pull request, please disclose the
tool(s) used, how they were used, and specify what code or text is AI generated.
"""

GETI_AGENTS_TEXT = """\
# Geti Agent Guide

AGENTS.md is the canonical repo-wide instruction file for agentic tools.
CLAUDE.md imports this file for Claude Code compatibility.
"""

GETI_TEMPLATE_TEXT = """\
Please add a summary of changes. You may use Copilot to auto-generate the PR
description but please consider including any other relevant facts.
"""

NEUTRAL_TEXT = """\
# Contributing

Thanks for your interest in contributing! Please open an issue before
submitting large changes, and make sure the test suite passes.
"""


def _patch(monkeypatch, files, entries=(), fail=False):
    def fake_fetch(repo):
        if fail:
            raise policy_mod.GhError("boom")
        return list(files)

    monkeypatch.setattr(policy_mod, "fetch_policy_files", fake_fetch)
    monkeypatch.setattr(policy_mod, "repo_root_entries", lambda repo: list(entries))


class TestScanPolicy:
    def test_llama_cpp_posts_banned(self, monkeypatch):
        _patch(monkeypatch, [("CONTRIBUTING.md", LLAMA_TEXT)])
        r = scan_policy("ggml-org/llama.cpp")
        assert r["verdict"] == "POSTS_BANNED"
        files = [e["file"] for e in r["evidence"]]
        assert all(f == "CONTRIBUTING.md" or f == "(seed)" for f in files)
        assert not any("AI-generated code is allowed" in e["line"] for e in r["evidence"])

    def test_pip_disclosure_required(self, monkeypatch):
        _patch(
            monkeypatch,
            [("AI_POLICY.md", PIP_POLICY_TEXT), (".github/PULL_REQUEST_TEMPLATE.md", PIP_TEMPLATE_TEXT)],
        )
        r = scan_policy("pypa/pip")
        assert r["verdict"] == "DISCLOSURE_REQUIRED"
        assert r["disclosure_hint"] == "Assisted-by: <tool> line in the PR body"

    def test_sphinx_disclosure_required(self, monkeypatch):
        _patch(monkeypatch, [(".github/PULL_REQUEST_TEMPLATE.md", SPHINX_TEMPLATE_TEXT)])
        r = scan_policy("sphinx-doc/sphinx")
        assert r["verdict"] == "DISCLOSURE_REQUIRED"
        assert r["disclosure_hint"] == "## AI Disclosure section in the PR body"

    def test_geti_agent_friendly(self, monkeypatch):
        _patch(
            monkeypatch,
            [("AGENTS.md", GETI_AGENTS_TEXT), (".github/pull_request_template.md", GETI_TEMPLATE_TEXT)],
            entries=[{"name": ".agents", "type": "dir"}, {"name": ".claude", "type": "dir"},
                     {"name": "src", "type": "dir"}],
        )
        r = scan_policy("open-edge-platform/geti")
        assert r["verdict"] == "AGENT_FRIENDLY"
        assert r["agent_dirs"] == [".agents", ".claude"]

    def test_neutral_repo_clean(self, monkeypatch):
        _patch(monkeypatch, [("CONTRIBUTING.md", NEUTRAL_TEXT)])
        r = scan_policy("some/repo")
        assert r["verdict"] == "CLEAN"
        assert r["disclosure_hint"] is None

    def test_no_policy_files_at_all_is_clean(self, monkeypatch):
        _patch(monkeypatch, [])
        r = scan_policy("some/repo")
        assert r["verdict"] == "CLEAN"

    def test_ai_code_allowed_alone_is_not_a_ban(self, monkeypatch):
        _patch(monkeypatch, [("CONTRIBUTING.md", "AI-generated code is allowed with disclosure.\n")])
        r = scan_policy("some/repo")
        assert r["verdict"] == "DISCLOSURE_REQUIRED"  # disclosure clause, not a post ban

    def test_seed_escalates_over_missed_live_scan(self, monkeypatch):
        # Live scan finds nothing (pattern miss / renamed file) but the
        # seed says POSTS_BANNED: the seed must win.
        _patch(monkeypatch, [("CONTRIBUTING.md", NEUTRAL_TEXT)])
        r = scan_policy("ggml-org/llama.cpp")
        assert r["verdict"] == "POSTS_BANNED"
        assert any(e["file"] == "(seed)" for e in r["evidence"])

    def test_seed_cannot_downgrade_live_ban(self, monkeypatch):
        _patch(monkeypatch, [("CONTRIBUTING.md", LLAMA_TEXT)])
        r = scan_policy("sgl-project/sglang")  # seeded CLEAN
        assert r["verdict"] == "POSTS_BANNED"

    def test_fetch_failure_unknown_without_seed(self, monkeypatch):
        _patch(monkeypatch, [], fail=True)
        r = scan_policy("someone/new")
        assert r["verdict"] == "UNKNOWN"

    def test_fetch_failure_falls_back_to_seed(self, monkeypatch):
        _patch(monkeypatch, [], fail=True)
        r = scan_policy("keras-team/keras")
        assert r["verdict"] == "DISCLOSURE_REQUIRED"


class TestFormatPolicy:
    def test_output_shows_verdict_evidence_action(self, monkeypatch):
        _patch(monkeypatch, [("CONTRIBUTING.md", LLAMA_TEXT)])
        out = format_policy(scan_policy("ggml-org/llama.cpp"))
        assert "POSTS_BANNED" in out
        assert "evidence" in out
        assert "action" in out
        assert "human contributor writes" in out


class TestCliPolicy:
    def test_banned_repo_exits_2(self, monkeypatch, capsys):
        _patch(monkeypatch, [("CONTRIBUTING.md", LLAMA_TEXT)])
        assert main(["policy", "ggml-org/llama.cpp"]) == 2

    def test_clean_repo_exits_0(self, monkeypatch, capsys):
        _patch(monkeypatch, [("CONTRIBUTING.md", NEUTRAL_TEXT)])
        assert main(["policy", "some/repo"]) == 0

    def test_unknown_repo_exits_1(self, monkeypatch, capsys):
        _patch(monkeypatch, [], fail=True)
        assert main(["policy", "someone/new"]) == 1

"""AI/contribution policy gate for upstream repos.

Fetches the repo's policy files (CONTRIBUTING, AGENTS.md, AI_POLICY.md,
CLAUDE.md, PR/issue templates), scans them for AI/LLM clauses, and emits
a hard verdict that must be checked BEFORE any post (comment, PR, issue)
is made in that repo:

  POSTS_BANNED         AI-authored posts (descriptions, comments,
                       replies, reports) are prohibited. Nothing posts
                       unless a human writes it in their own words.
                       Exit code 2.
  DISCLOSURE_REQUIRED  AI use must be disclosed; the required format is
                       extracted and printed. Exit code 0.
  AGENT_FRIENDLY       Repo explicitly embraces agent tooling.
                       Exit code 0.
  CLEAN                Policy files exist, no AI clauses found.
                       Exit code 0.
  UNKNOWN              Policy files could not be fetched. Treat like
                       POSTS_BANNED until re-run succeeds. Exit code 1.

A shipped seed table pins audited verdicts for known repos; the live
scan can only ESCALATE a seeded verdict (CLEAN -> DISCLOSURE_REQUIRED
-> POSTS_BANNED), never downgrade it, so a renamed/moved policy file
cannot silently un-ban a repo. Re-audit seeds when policies change.
"""

import re

from .gh import GhError, gh_json, gh_text

VERDICT_SEVERITY = {"CLEAN": 0, "AGENT_FRIENDLY": 0, "DISCLOSURE_REQUIRED": 1, "POSTS_BANNED": 2}

POLICY_FILES = [
    "CONTRIBUTING.md",
    "docs/CONTRIBUTING.md",
    "AGENTS.md",
    "AI_POLICY.md",
    "CLAUDE.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/pull_request_template.md",
]

# Audited verdicts; live scans may escalate but never downgrade these.
SEED_VERDICTS = {
    "ggml-org/llama.cpp": (
        "POSTS_BANNED",
        "AI-authored posts prohibited; AI-generated code allowed WITH disclosure",
    ),
    "pypa/pip": (
        "DISCLOSURE_REQUIRED",
        "Assisted-by: line in PR checklist; no LLM co-author trailers; no unsupervised agents",
    ),
    "sphinx-doc/sphinx": (
        "DISCLOSURE_REQUIRED",
        "## AI Disclosure section required in PR body",
    ),
    "keras-team/keras": (
        "DISCLOSURE_REQUIRED",
        "AI disclosure + human attestation; PRs need an issue assigned to you",
    ),
    "sgl-project/sglang": ("CLEAN", "no AI-post policy found"),
    "open-edge-platform/geti": ("AGENT_FRIENDLY", "AGENTS.md canonical; agent tooling embraced"),
    "pygments/pygments": ("CLEAN", "no AI clauses found in policy files"),
    "nedbat/coveragepy": ("CLEAN", "no AI clauses found in policy files"),
}

POST_BAN_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"prohibited to use ai\b",
        r"ai[ -](?:written|authored)[ -.]{0,20}(?:post|comment|issue|description|report|discussion|reply)",
        r"(?:post|comment|issue|description|report|discussion|reply)[a-z]{0,3}\b[^.\n]{0,80}?\b(?:must not|may not|cannot|do not|don't)\b[^.\n]{0,40}?\b(?:ai|llm|automated)\b",
        r"(?:must not|may not|do not|don't) use (?:an? )?(?:ai|llm|language model|automated tool)[^.]{0,60}(?:writ|draft|generat|compos)",
        r"no ai[ -](?:written|authored|generated) (?:posts?|comments?|issues?|prs?)",
    )
]

DISCLOSURE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ai disclosure",
        r"assisted[- ]by",
        r"if any ai tools were used",
        r"disclos[a-z]*[^.\n]{0,120}\b(?:ai|llm|machine[- ]generated|generative)\b",
        r"(?:ai|llm|generative)[^.\n]{0,120}\bdisclos[a-z]*",
        r"attestation",
        r"explain every line",
        r"be prepared to explain",
    )
]

AGENT_FRIENDLY_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"can'?t realistically police",
        r"you may use copilot",
        r"agents?\.md is the canonical",
        r"canonical repo[- ]wide instruction file for agentic tools",
    )
]

ACTIONS = {
    "POSTS_BANNED": (
        "AGENT MUST NOT DRAFT ANY POST - the human contributor writes every "
        "comment, PR description and reply in their own words. AI-generated "
        "code may be allowed WITH explicit disclosure; re-read the policy text."
    ),
    "DISCLOSURE_REQUIRED": (
        "Posting allowed, but the required AI disclosure MUST be included "
        "(see disclosure hint above). Show the exact final text to the human "
        "contributor before posting."
    ),
    "AGENT_FRIENDLY": "No AI-post restrictions found; repo embraces agent tooling. Still show final text to the human contributor.",
    "CLEAN": "No AI clauses found. Still show final text to the human contributor.",
    "UNKNOWN": "Could not read policy files - treat as POSTS_BANNED until a re-run succeeds.",
}


def fetch_policy_files(repo: str):
    """Return [(path, text)] for every policy file that exists in the repo.

    Raises GhError if nothing could be fetched (network/auth failure),
    which maps to the UNKNOWN verdict.
    """
    fetched = []
    saw_failure = False
    for path in POLICY_FILES:
        try:
            text = gh_text(
                "api", "-H", "Accept: application/vnd.github.raw",
                f"repos/{repo}/contents/{path}",
            )
        except GhError:
            saw_failure = True
            continue
        if text and "Not Found" not in text[:200]:
            fetched.append((path, text))
    if not fetched and saw_failure:
        raise GhError(f"could not fetch any policy file for {repo}")
    return fetched


def repo_root_entries(repo: str):
    try:
        return gh_json("api", f"repos/{repo}/contents")
    except GhError:
        return []


def _matches(text: str, patterns):
    hits = []
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 8:
            continue
        for pat in patterns:
            if pat.search(line):
                hits.append(line[:220])
                break
    return hits


def scan_policy(repo: str) -> dict:
    seed = SEED_VERDICTS.get(repo)
    report = {
        "repo": repo,
        "verdict": "UNKNOWN",
        "seed": None,
        "files": [],
        "evidence": [],
        "agent_dirs": [],
        "disclosure_hint": None,
        "action": ACTIONS["UNKNOWN"],
    }
    if seed:
        report["seed"] = {"verdict": seed[0], "note": seed[1]}
    try:
        files = fetch_policy_files(repo)
    except GhError:
        if seed:
            report["verdict"] = seed[0]
            report["action"] = ACTIONS[seed[0]]
            report["evidence"].append({"file": "(seed)", "line": seed[1] + " [live fetch failed]"})
        return report
    report["files"] = [p for p, _ in files]

    entries = repo_root_entries(repo)
    if entries:
        names = {e.get("name", "").lower() for e in entries}
        report["agent_dirs"] = sorted(names & {".agents", ".claude"})

    bans, disclosures, friendly = [], [], []
    for path, text in files:
        bans += [{"file": path, "line": ln} for ln in _matches(text, POST_BAN_PATTERNS)]
        disclosures += [{"file": path, "line": ln} for ln in _matches(text, DISCLOSURE_PATTERNS)]
        friendly += [{"file": path, "line": ln} for ln in _matches(text, AGENT_FRIENDLY_PATTERNS)]

    if bans:
        live = "POSTS_BANNED"
    elif disclosures:
        live = "DISCLOSURE_REQUIRED"
    elif friendly or report["agent_dirs"]:
        live = "AGENT_FRIENDLY"
    else:
        live = "CLEAN"

    verdict = live
    if seed and VERDICT_SEVERITY[seed[0]] > VERDICT_SEVERITY[live]:
        # The live scan can only escalate a seeded verdict, never
        # downgrade it: a renamed or moved policy file must not be
        # able to silently un-ban a repo.
        verdict = seed[0]

    report["verdict"] = verdict
    if verdict == "POSTS_BANNED":
        report["evidence"] = bans or [{"file": "(seed)", "line": seed[1]}]
    elif verdict == "DISCLOSURE_REQUIRED":
        report["evidence"] = disclosures or [{"file": "(seed)", "line": seed[1]}]
    else:
        report["evidence"] = (bans + disclosures + friendly)[:6]
    if disclosures:
        for d in disclosures:
            low = d["line"].lower()
            if "assisted" in low:
                report["disclosure_hint"] = "Assisted-by: <tool> line in the PR body"
                break
            if "ai disclosure" in low:
                report["disclosure_hint"] = "## AI Disclosure section in the PR body"
                break
    if verdict == "DISCLOSURE_REQUIRED" and not report["disclosure_hint"]:
        report["disclosure_hint"] = "state the tool, what it was used for, and what is AI-generated"
    report["action"] = ACTIONS[verdict]
    return report


def format_policy(report: dict) -> str:
    out = [f"osscout policy - {report['repo']}", ""]
    out.append(f"  verdict   : {report['verdict']}")
    if report["seed"]:
        s = report["seed"]
        out.append(f"  seeded    : {s['verdict']} ({s['note']})")
    if report["files"]:
        out.append(f"  files     : {', '.join(report['files'])}")
    if report["agent_dirs"]:
        out.append(f"  agent dirs: {', '.join(report['agent_dirs'])} (agent-friendly signals)")
    if report["disclosure_hint"]:
        out.append(f"  disclosure: {report['disclosure_hint']}")
    if report["evidence"]:
        out.append("  evidence  :")
        for e in report["evidence"][:6]:
            out.append(f"    {e['file']}:")
            out.append(f"      \"{e['line']}\"")
    out.append(f"  action    : {report['action']}")
    return "\n".join(out)

FARM_WINDOWS = [
    ("hermes-agent, mcp/python-sdk, pydantic, pydantic-ai", "~6h",
     "sweeper bots, assignment pileups, 'please assign me' spam"),
    ("psf/black", "~24h",
     "maintainers close weak farm PRs without review"),
    ("pytest-dev/pytest", "~2-5 days",
     "maintainers run their own AI agents on triage"),
    ("sphinx-doc/sphinx", "~2-5 days",
     "deep reporter analyses; farms follow"),
    ("pygments/pygments", "~1-2 weeks",
     "no triage bot; slowest penetration found"),
]

DURABLE_NICHES = [
    "Perf/measurement work - needs real benchmarking on real hardware.",
    "Policy/semantics decisions - fixes that flip a test invariant or need a maintainer design call.",
    "Stale 'PR welcome' / 'pull-request wanted' issues - pre-approved, invisible to created-desc farms.",
    "Windows-specific repros - most farm bots live in Linux containers.",
]

BOT_QUEUE_MARKERS = (
    "clawsweeper:linked-pr-open",
    "clawsweeper:no-new-fix-pr",
    "implementation worker is queued",
)

HARD_STOP_LABELS = (
    "no-new-fix-pr",
)

CLAIM_PHRASES = (
    "interested in this issue",
    "may i work on this",
    "would it be okay if i work",
    "i'd like to work on",
    "i would like to work on",
    "i'll take this",
    "can i work on this",
    "i'd like to investigate",
    "i will work on this",
    "i would like to investigate",
    "lmk what you think",
)

AFFIRMATIVE_PHRASES = (
    "pr is welcome",
    "pr welcome",
    "go ahead",
    "feel free to open",
    "please do",
    "assigned to you",
    "you can work on it",
)

MAINTAINER_ASSOCIATIONS = (
    "MEMBER",
    "OWNER",
    "COLLABORATOR",
)

BOT_AUTHOR_PREFIXES = (
    "app/",
    "dependabot",
    "renovate",
    "pre-commit-ci",
    "pyup-bot",
)

DEPENDENCY_BOT_TITLE_WORDS = (
    "bump",
    "requirements: update",
    "update requirement",
    "scheduled monthly",
)

STALE_DAYS = 90

RECENT_CLOSED_DAYS = 60

import json
import subprocess


class GhError(RuntimeError):
    pass


def gh_json(*args: str):
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise GhError(proc.stderr.strip() or "gh " + " ".join(args) + " failed")
    out = proc.stdout.strip()
    if not out:
        return []
    return json.loads(out)

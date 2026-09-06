"""
M1 -- Memory store.

Persists decision + outcome records as a single JSON file in the app's own
GitHub repo, read/written via GitHub's Contents API. No Streamlit dependency
here -- used identically by the app and (later, if wanted) the standalone
agent.

Requires GITHUB_TOKEN (fine-grained, Contents: read/write, scoped to one
repo) and GITHUB_REPO (e.g. "yourname/fpl-dashboard") wherever secrets are
read from (Streamlit Secrets, or a .env for standalone use).
"""

import base64
import json
import requests

GITHUB_API = "https://api.github.com"
MEMORY_PATH = "memory/decisions.json"


class MemoryError(Exception):
    pass


def _headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_file(token, repo):
    """Returns (records: list, sha: str | None). sha is None if the file
    doesn't exist yet (first-ever write will create it)."""
    url = f"{GITHUB_API}/repos/{repo}/contents/{MEMORY_PATH}"
    response = requests.get(url, headers=_headers(token), timeout=15)

    if response.status_code == 404:
        return [], None
    if response.status_code != 200:
        raise MemoryError(f"GitHub returned {response.status_code} reading memory: {response.text[:300]}")

    data = response.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    try:
        records = json.loads(content) if content.strip() else []
    except json.JSONDecodeError:
        raise MemoryError("memory/decisions.json exists but isn't valid JSON -- check it manually.")
    return records, data["sha"]


def _put_file(token, repo, records, sha, message):
    url = f"{GITHUB_API}/repos/{repo}/contents/{MEMORY_PATH}"
    content_b64 = base64.b64encode(json.dumps(records, indent=2).encode("utf-8")).decode("utf-8")
    payload = {"message": message, "content": content_b64}
    if sha:
        payload["sha"] = sha

    response = requests.put(url, headers=_headers(token), json=payload, timeout=15)
    if response.status_code not in (200, 201):
        raise MemoryError(f"GitHub returned {response.status_code} writing memory: {response.text[:300]}")


def get_recent(token, repo, n=6):
    records, _ = _get_file(token, repo)
    return sorted(records, key=lambda r: r["gameweek"], reverse=True)[:n]


def append_decision(token, repo, record):
    """record must include at minimum: gameweek, logged_at, recommendation.
    outcome starts empty and gets filled in later via resolve_outcome."""
    records, sha = _get_file(token, repo)
    records = [r for r in records if r["gameweek"] != record["gameweek"]]  # replace same-GW re-runs
    record.setdefault("outcome", {"resolved": False, "actual_points_gained": None, "notes": None})
    records.append(record)
    _put_file(token, repo, records, sha, f"Log decision for GW{record['gameweek']}")


def resolve_outcome(token, repo, gameweek, outcome):
    """outcome: {"resolved": True, "actual_points_gained": int, "notes": str}"""
    records, sha = _get_file(token, repo)
    found = False
    for r in records:
        if r["gameweek"] == gameweek:
            r["outcome"] = outcome
            found = True
            break
    if not found:
        raise MemoryError(f"No logged decision found for GW{gameweek} to resolve.")
    _put_file(token, repo, records, sha, f"Resolve outcome for GW{gameweek}")

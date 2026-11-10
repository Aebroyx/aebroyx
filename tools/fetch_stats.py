"""Fetch GitHub numbers for the profile card into cache/stats.json.

Runs in the GitHub Action with GITHUB_TOKEN set. Lines of code is the slow
part (it reads every commit you authored), so the per-repo result is cached in
cache/loc.json and only recomputed when a repo's latest commit changes.

GitHub's API times out on big pages of commit history, so history is read in
pages that shrink whenever GitHub gives up, and a repo that still fails is
skipped (keeping its last known count) rather than failing the whole run.

    GITHUB_TOKEN=... python tools/fetch_stats.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
STATS_FILE = CACHE / "stats.json"
LOC_FILE = CACHE / "loc.json"

LOGIN = json.loads((ROOT / "profile.json").read_text())["login"]
TOKEN = os.environ.get("GITHUB_TOKEN")
API = "https://api.github.com/graphql"

http = requests.Session()


class GitHubTimeout(Exception):
    """GitHub gave up on a query (502/504 or a dropped connection)."""


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def gql(query: str, attempts: int = 4, **variables) -> dict:
    problem = ""
    for attempt in range(attempts):
        if attempt:
            time.sleep(min(60, 5 * 2 ** attempt))
        try:
            r = http.post(API, json={"query": query, "variables": variables},
                          headers={"Authorization": f"bearer {TOKEN}"}, timeout=60)
        except requests.RequestException as e:
            problem = f"connection dropped ({type(e).__name__})"
            log(f"  {problem}, retrying")
            continue
        if r.status_code in (502, 503, 504):
            problem = f"GitHub returned {r.status_code}"
            log(f"  {problem}, retrying")
            continue
        if r.status_code in (403, 429):
            wait = int(r.headers.get("Retry-After", 60))
            log(f"  rate limited, waiting {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise SystemExit("GraphQL error: " + json.dumps(body["errors"], indent=2))
        return body["data"]
    raise GitHubTimeout(problem or "rate limited")


USER_Q = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    id
    createdAt
    followers { totalCount }
    repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100, after: $cursor) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        stargazerCount
        defaultBranchRef { target { oid } }
      }
    }
  }
}
"""

COMMITS_Q = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) { totalCommitContributions }
  }
}
"""

HISTORY_Q = """
query($owner: String!, $name: String!, $author: ID!, $cursor: String, $size: Int!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: $size, after: $cursor, author: {id: $author}) {
        pageInfo { hasNextPage endCursor }
        nodes { additions deletions }
      }
    }}}
  }
}
"""


def user_and_repos() -> tuple[dict, list[dict]]:
    repos, cursor, user = [], None, None
    while True:
        u = gql(USER_Q, login=LOGIN, cursor=cursor)["user"]
        user = user or u
        repos += u["repositories"]["nodes"]
        page = u["repositories"]["pageInfo"]
        if not page["hasNextPage"]:
            return user, repos
        cursor = page["endCursor"]


def total_commits(since: str) -> int:
    # GitHub only answers one year at a time here.
    start = datetime.fromisoformat(since.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    total = 0
    while start < now:
        end = min(start.replace(year=start.year + 1, day=min(start.day, 28)), now)
        c = gql(COMMITS_Q, login=LOGIN,
                **{"from": start.isoformat(), "to": end.isoformat()})
        total += c["user"]["contributionsCollection"]["totalCommitContributions"]
        start = end
    return total


def count_repo(name: str, author_id: str) -> tuple[int, int]:
    """Additions/deletions you authored on one repo's default branch."""
    owner, short = name.split("/", 1)
    added = deleted = 0
    cursor, size = None, 50
    while True:
        try:
            ref = gql(HISTORY_Q, attempts=2, owner=owner, name=short, author=author_id,
                      cursor=cursor, size=size)["repository"]["defaultBranchRef"]
        except GitHubTimeout:
            if size == 1:
                raise
            size = max(1, size // 3)
            log(f"  {name}: GitHub timed out, retrying {size} commits at a time")
            continue
        hist = ref["target"]["history"]
        for n in hist["nodes"]:
            added += n["additions"]
            deleted += n["deletions"]
        if not hist["pageInfo"]["hasNextPage"]:
            return added, deleted
        cursor = hist["pageInfo"]["endCursor"]


def lines_of_code(repos: list[dict], author_id: str) -> tuple[int, int, int]:
    # Keys are hashed so the public cache never reveals private repo names.
    cache = json.loads(LOC_FILE.read_text()) if LOC_FILE.exists() else {}
    added = deleted = skipped = 0
    for repo in repos:
        head = ((repo.get("defaultBranchRef") or {}).get("target") or {}).get("oid")
        if not head:
            continue  # empty repo
        name = repo["nameWithOwner"]
        key = hashlib.sha256(name.encode()).hexdigest()[:16]
        hit = cache.get(key)
        if not hit or hit["head"] != head:
            try:
                a, d = count_repo(name, author_id)
            except GitHubTimeout as e:
                skipped += 1
                log(f"  skipped {name}: {e}" + (" (using last count)" if hit else ""))
                if hit:
                    added += hit["added"]
                    deleted += hit["deleted"]
                continue
            hit = cache[key] = {"head": head, "added": a, "deleted": d}
            log(f"  counted {name}: +{a:,} -{d:,}")
            LOC_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))
        added += hit["added"]
        deleted += hit["deleted"]
    LOC_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))
    return added, deleted, skipped


def main() -> None:
    if not TOKEN:
        raise SystemExit("Set GITHUB_TOKEN first")
    CACHE.mkdir(exist_ok=True)
    log(f"Fetching stats for {LOGIN}")

    user, repos = user_and_repos()
    added, deleted, skipped = lines_of_code(repos, user["id"])
    stats = {
        "repos": user["repositories"]["totalCount"],
        "contributed": user["repositoriesContributedTo"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "commits": total_commits(user["createdAt"]),
        "followers": user["followers"]["totalCount"],
        "loc": added - deleted,
        "added": added,
        "deleted": deleted,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    STATS_FILE.write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))
    if skipped:
        log(f"::warning::Lines of code skipped {skipped} repo(s) GitHub kept timing out on")


if __name__ == "__main__":
    main()

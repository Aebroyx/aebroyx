"""Fetch GitHub numbers for the profile card into cache/stats.json.

Runs in the GitHub Action with GITHUB_TOKEN set. Lines of code is the slow
part (it reads every commit you authored), so the per-repo result is cached in
cache/loc.json and only recomputed when a repo's latest commit changes.

    GITHUB_TOKEN=... python tools/fetch_stats.py
"""

from __future__ import annotations

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


def gql(query: str, **variables) -> dict:
    for attempt in range(4):
        r = http.post(API, json={"query": query, "variables": variables},
                      headers={"Authorization": f"bearer {TOKEN}"}, timeout=60)
        if r.status_code in (403, 429, 502) and attempt < 3:
            wait = int(r.headers.get("Retry-After", 30))
            print(f"  GitHub said {r.status_code}, retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise SystemExit("GraphQL error: " + json.dumps(body["errors"], indent=2))
        return body["data"]
    raise SystemExit("GitHub kept rate limiting us")


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
query($owner: String!, $name: String!, $author: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, after: $cursor, author: {id: $author}) {
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


def lines_of_code(repos: list[dict], author_id: str) -> tuple[int, int]:
    cache = json.loads(LOC_FILE.read_text()) if LOC_FILE.exists() else {}
    added = deleted = 0
    for repo in repos:
        head = ((repo.get("defaultBranchRef") or {}).get("target") or {}).get("oid")
        if not head:
            continue  # empty repo
        name = repo["nameWithOwner"]
        hit = cache.get(name)
        if not hit or hit["head"] != head:
            owner, short = name.split("/", 1)
            a = d = 0
            cursor = None
            while True:
                ref = gql(HISTORY_Q, owner=owner, name=short, author=author_id,
                          cursor=cursor)["repository"]["defaultBranchRef"]
                hist = ref["target"]["history"]
                for n in hist["nodes"]:
                    a += n["additions"]
                    d += n["deletions"]
                if not hist["pageInfo"]["hasNextPage"]:
                    break
                cursor = hist["pageInfo"]["endCursor"]
            hit = cache[name] = {"head": head, "added": a, "deleted": d}
            print(f"  counted {name}: +{a:,} -{d:,}")
        added += hit["added"]
        deleted += hit["deleted"]
    LOC_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))
    return added, deleted


def main() -> None:
    if not TOKEN:
        raise SystemExit("Set GITHUB_TOKEN first")
    CACHE.mkdir(exist_ok=True)
    print(f"Fetching stats for {LOGIN}")

    user, repos = user_and_repos()
    added, deleted = lines_of_code(repos, user["id"])
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


if __name__ == "__main__":
    main()

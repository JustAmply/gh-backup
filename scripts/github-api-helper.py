#!/usr/bin/env python3

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


API_URL = "https://api.github.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["list-owner-repos"])
    parser.add_argument("--token", required=True)
    parser.add_argument("--owner", required=True)
    return parser.parse_args()


def list_owner_repos(token: str, owner: str) -> int:
    owner_lower = owner.casefold()
    page = 1

    try:
        while True:
            query = urllib.parse.urlencode(
                {
                    "visibility": "all",
                    "affiliation": "owner",
                    "per_page": 100,
                    "page": page,
                }
            )
            request = urllib.request.Request(
                f"{API_URL}/user/repos?{query}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "gh-backup",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

            with urllib.request.urlopen(request) as response:
                repos = json.loads(response.read().decode("utf-8"))

            if not repos:
                return 0

            for repo in repos:
                repo_owner = repo.get("owner") or {}
                owner_login = repo_owner.get("login")
                repo_name = repo.get("name")
                clone_url = repo.get("clone_url")

                if not isinstance(owner_login, str) or owner_login.casefold() != owner_lower:
                    continue
                if not isinstance(repo_name, str) or not isinstance(clone_url, str):
                    continue

                has_wiki = "true" if bool(repo.get("has_wiki")) else "false"
                print(f"{repo_name}\t{clone_url}\t{has_wiki}")

            page += 1
    except urllib.error.HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(message)
            if isinstance(payload, dict) and payload.get("message"):
                message = str(payload["message"])
        except json.JSONDecodeError:
            pass
        print(f"GitHub repo discovery failed ({error.code}): {message}", file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        print(f"GitHub repo discovery failed: {error.reason}", file=sys.stderr)
        return 1


def main() -> int:
    args = parse_args()
    return list_owner_repos(args.token, args.owner)


if __name__ == "__main__":
    sys.exit(main())

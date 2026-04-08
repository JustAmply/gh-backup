#!/usr/bin/env python3

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_API_URL = "https://api.github.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["list-owner-repos"])
    parser.add_argument("--token", required=True)
    parser.add_argument("--owner", required=True)
    return parser.parse_args()


def request_json(api_url: str, path: str, token: str) -> object:
    request = urllib.request.Request(
        f"{api_url}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "gh-backup",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_api_url() -> str:
    return os.environ.get("GITHUB_API_URL", DEFAULT_API_URL).rstrip("/")


def list_owner_repos(token: str, owner: str) -> int:
    api_url = resolve_api_url()
    owner_lower = owner.casefold()
    page = 1

    try:
        profile = request_json(api_url, "/user", token)
        if not isinstance(profile, dict):
            print("GitHub repo discovery failed: invalid /user response payload", file=sys.stderr)
            return 1

        authenticated_login = profile.get("login")
        if not isinstance(authenticated_login, str) or not authenticated_login:
            print("GitHub repo discovery failed: authenticated user login missing from /user response", file=sys.stderr)
            return 1

        if authenticated_login.casefold() != owner_lower:
            print(
                f"GITHUB_OWNER '{owner}' does not match the authenticated GitHub user '{authenticated_login}'",
                file=sys.stderr,
            )
            return 1

        while True:
            query = urllib.parse.urlencode(
                {
                    "visibility": "all",
                    "affiliation": "owner",
                    "per_page": 100,
                    "page": page,
                }
            )
            repos = request_json(api_url, f"/user/repos?{query}", token)
            if not isinstance(repos, list):
                print("GitHub repo discovery failed: invalid /user/repos response payload", file=sys.stderr)
                return 1

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

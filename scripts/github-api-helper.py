#!/usr/bin/env python3

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-url", required=True)
    common.add_argument("--token", required=True)

    get_user = subparsers.add_parser("get-user-login", parents=[common])
    get_user.set_defaults(handler=handle_get_user_login)

    list_repos = subparsers.add_parser("list-owner-repos", parents=[common])
    list_repos.add_argument("--owner", required=True)
    list_repos.set_defaults(handler=handle_list_owner_repos)

    return parser.parse_args()


def github_request(api_url: str, token: str, path: str, query: dict[str, object] | None = None) -> tuple[dict[str, str], object]:
    base_url = api_url.rstrip("/")
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"

    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "gh-backup",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    except ValueError as error:
        raise RuntimeError(f"GitHub API request failed: {error}") from error

    try:
        with urllib.request.urlopen(request) as response:
            payload = response.read().decode("utf-8")
            headers = {key.lower(): value for key, value in response.info().items()}
            return headers, json.loads(payload)
    except urllib.error.HTTPError as error:
        payload = error.read().decode("utf-8", errors="replace")
        headers = {key.lower(): value for key, value in error.headers.items()}
        raise GithubApiError(error.code, payload, headers) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"GitHub API request failed: {error.reason}") from error


class GithubApiError(RuntimeError):
    def __init__(self, status: int, payload: str, headers: dict[str, str]):
        super().__init__(payload)
        self.status = status
        self.payload = payload
        self.headers = headers


def format_api_error(error: GithubApiError) -> str:
    message = error.payload
    try:
        parsed = json.loads(error.payload)
        if isinstance(parsed, dict) and parsed.get("message"):
            message = str(parsed["message"])
    except json.JSONDecodeError:
        pass

    if error.status == 401:
        return "GitHub API preflight failed (401 Unauthorized). Check that GITHUB_TOKEN is valid."

    if error.status == 403:
        if error.headers.get("x-github-sso"):
            return (
                "GitHub API preflight failed (403 Forbidden). The token needs SSO authorization "
                "for at least one organization. Authorize the token and retry."
            )
        return (
            "GitHub API preflight failed (403 Forbidden). Check token scopes and organization access. "
            f"GitHub said: {message}"
        )

    return f"GitHub API request failed ({error.status}). GitHub said: {message}"


def handle_get_user_login(args: argparse.Namespace) -> int:
    try:
        _, payload = github_request(args.api_url, args.token, "/user")
    except GithubApiError as error:
        print(format_api_error(error), file=sys.stderr)
        return 1
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1

    login = payload.get("login")
    if not isinstance(login, str) or not login:
        print("GitHub API preflight succeeded but the response did not include a login.", file=sys.stderr)
        return 1

    print(login)
    return 0


def handle_list_owner_repos(args: argparse.Namespace) -> int:
    page = 1
    owner_lower = args.owner.casefold()

    while True:
        try:
            _, payload = github_request(
                args.api_url,
                args.token,
                "/user/repos",
                {
                    "visibility": "all",
                    "affiliation": "owner",
                    "per_page": 100,
                    "page": page,
                },
            )
        except GithubApiError as error:
            print(format_api_error(error), file=sys.stderr)
            return 1
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 1

        if not payload:
            return 0

        for repo in payload:
            owner = repo.get("owner") or {}
            owner_login = owner.get("login")
            repo_name = repo.get("name")
            clone_url = repo.get("clone_url")
            has_wiki = repo.get("has_wiki")

            if not isinstance(owner_login, str) or owner_login.casefold() != owner_lower:
                continue
            if not isinstance(repo_name, str) or not isinstance(clone_url, str):
                continue

            print(f"{repo_name}\t{clone_url}\t{'true' if bool(has_wiki) else 'false'}")

        page += 1


def main() -> int:
    args = parse_args()
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


SUCCESS_REPOS = [
    {
        "name": "public-repo",
        "clone_url": "https://github.com/octocat/public-repo.git",
        "has_wiki": True,
        "owner": {"login": "octocat"},
    },
    {
        "name": "private-repo",
        "clone_url": "https://github.com/octocat/private-repo.git",
        "has_wiki": False,
        "owner": {"login": "octocat"},
    },
    {
        "name": "collab-repo",
        "clone_url": "https://github.com/someone/collab-repo.git",
        "has_wiki": False,
        "owner": {"login": "someone"},
    },
    {
        "name": "org-repo",
        "clone_url": "https://github.com/acme/org-repo.git",
        "has_wiki": False,
        "owner": {"login": "acme"},
    },
]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        scenario = os.environ.get("MOCK_GITHUB_SCENARIO", "success")
        parsed = urlparse(self.path)

        if parsed.path == "/user":
            if scenario == "success":
                self.send_json(200, {"login": "octocat"})
                return
            if scenario == "sso":
                self.send_json(
                    403,
                    {"message": "Resource protected by organization SAML enforcement."},
                    extra_headers={"X-GitHub-SSO": "required; url=https://github.com/orgs/acme/sso"},
                )
                return
            if scenario == "unauthorized":
                self.send_json(401, {"message": "Bad credentials"})
                return

        if parsed.path == "/user/repos" and scenario == "success":
            page = parse_qs(parsed.query).get("page", ["1"])[0]
            if page == "1":
                self.send_json(200, SUCCESS_REPOS)
                return
            self.send_json(200, [])
            return

        self.send_json(404, {"message": f"Unhandled path: {parsed.path}"})

    def log_message(self, format: str, *args) -> None:
        return

    def send_json(self, status: int, payload: object, extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(server.server_address[1], flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

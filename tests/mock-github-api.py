#!/usr/bin/env python3

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


SCENARIO = os.environ.get("MOCK_GITHUB_API_SCENARIO", "success")
PORT_FILE = os.environ["MOCK_GITHUB_API_PORT_FILE"]


class Handler(BaseHTTPRequestHandler):
    def _write_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/healthz":
            self._write_json(200, {"ok": True})
            return

        if parsed.path == "/user":
            if SCENARIO == "sso-failure":
                self._write_json(403, {"message": "Resource protected by organization SAML enforcement."})
                return

            login = "octocat"
            if SCENARIO == "owner-mismatch":
                login = "somebody-else"

            self._write_json(200, {"login": login})
            return

        if parsed.path == "/user/repos":
            query = parse_qs(parsed.query)
            page = query.get("page", ["1"])[0]

            if SCENARIO == "sso-failure":
                self._write_json(403, {"message": "Resource protected by organization SAML enforcement."})
                return

            if page != "1":
                self._write_json(200, [])
                return

            self._write_json(
                200,
                [
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
                ],
            )
            return

        self._write_json(404, {"message": "Not Found"})

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with open(PORT_FILE, "w", encoding="utf-8") as file:
        file.write(str(server.server_address[1]))
    server.serve_forever()


if __name__ == "__main__":
    main()

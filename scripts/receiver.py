"""A webhook receiver that records what Alertmanager sent, and nothing else.

    uv run python scripts/receiver.py

It exists so the incident measurement counts what a person would actually receive rather than
what the configuration implies. Reasoning about deduplication, grouping and inhibition from a
config file is how people convince themselves an alert path is quiet.
"""

from __future__ import annotations

import json
import pathlib
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = pathlib.Path(__file__).resolve().parents[1] / "target" / "received.jsonl"


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        payload["route"] = self.path.lstrip("/")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_: object) -> None:
        """Silent. The measurement is the file, and a log here would just be noise about noise."""


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9099), Receiver).serve_forever()

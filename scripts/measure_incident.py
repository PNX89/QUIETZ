"""Replay one incident through a real Alertmanager, and count what a human would receive.

    uv run python scripts/measure_incident.py

WHAT IS MEASURED. A feed breaks and keeps breaking: the same alerts fire on every evaluation for
half an hour, two alerts about the same feed fire together, and a second feed goes with it. That
is 24 alert firings. What a person is told is a different number, and the gap between them is
the whole subject of a notification path.

Three mechanisms produce the gap and they are not the same thing:

    DEDUPLICATION  the same alert firing again is not a second notification
    GROUPING       alerts about one feed arrive as one notification rather than several
    INHIBITION     a completeness alert about a feed that has not delivered AT ALL is suppressed
                   while the freshness alert is firing, because it is the same problem restated

MEASURED AGAINST A REAL ALERTMANAGER rather than reasoned about, because these three interact
and the interaction is where the surprises are. The alerts are posted to its API and the
notifications are counted at a receiver that records what arrives.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "evidence" / "incident"
ALERTMANAGER = "http://127.0.0.1:19093"

#: The incident: two feeds, both broken, alerting repeatedly for half an hour.
FEEDS = ("ecb_exr_daily", "ecb_yield_curve")
EVALUATIONS = 6


def alerts() -> list[dict[str, Any]]:
    """Every firing, as Alertmanager receives them: the same alert, over and over."""
    posted: list[dict[str, Any]] = []
    for _ in range(EVALUATIONS):
        for feed in FEEDS:
            posted.append(
                {
                    "labels": {
                        "alertname": f"{feed}_freshness",
                        "feed": feed,
                        "severity": "page" if feed == FEEDS[0] else "ticket",
                        "route": "oncall" if feed == FEEDS[0] else "data-platform",
                    },
                    "annotations": {"summary": f"{feed} has not delivered"},
                }
            )
            posted.append(
                {
                    "labels": {
                        "alertname": f"{feed}_completeness",
                        "feed": feed,
                        "severity": "ticket",
                        "route": "data-platform",
                    },
                    "annotations": {"summary": f"{feed} is incomplete"},
                }
            )
    return posted


def post(batch: list[dict[str, Any]]) -> None:
    request = urllib.request.Request(
        f"{ALERTMANAGER}/api/v2/alerts",
        data=json.dumps(batch).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status >= 300:
            raise SystemExit(f"alertmanager refused the alerts: {response.status}")


def received() -> list[dict[str, Any]]:
    """What the receiver was actually sent, read from the file it appends to."""
    path = ROOT / "target" / "received.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    firings = alerts()

    try:
        post(firings)
    except urllib.error.URLError as error:
        print(
            f"no Alertmanager at {ALERTMANAGER}: {error}. Start the stack with "
            f"scripts/incident_stack.sh",
            file=sys.stderr,
        )
        return 1

    # The group wait is 10 seconds for the paging route and 30 for the rest, so this waits long
    # enough for both to have flushed rather than guessing.
    time.sleep(45)

    notifications = received()
    if not notifications:
        print("the receiver recorded nothing at all, so nothing was measured", file=sys.stderr)
        return 1

    by_route: dict[str, int] = {}
    alertnames: set[str] = set()
    for notification in notifications:
        route = str(notification.get("route", "unknown"))
        by_route[route] = by_route.get(route, 0) + 1
        for alert in notification.get("alerts", []):
            alertnames.add(str(alert["labels"]["alertname"]))

    summary: dict[str, Any] = {
        "alert_firings_posted": len(firings),
        "notifications_delivered": len(notifications),
        "notifications_by_route": dict(sorted(by_route.items())),
        "distinct_alerts_reaching_a_human": sorted(alertnames),
        "feeds": list(FEEDS),
        "evaluations": EVALUATIONS,
    }

    if summary["notifications_delivered"] >= summary["alert_firings_posted"]:
        print("every firing produced a notification, so the path is doing nothing", file=sys.stderr)
        return 1
    if any(name.endswith("_completeness") and name.startswith(FEEDS[0]) for name in alertnames):
        print(
            f"a completeness alert for {FEEDS[0]} reached a human while its freshness alert was "
            f"firing, so the inhibition rule is not inhibiting",
            file=sys.stderr,
        )
        return 1

    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    with (OUT / "one-incident.txt").open("w", encoding="utf-8") as handle:
        print("$ uv run python scripts/measure_incident.py", file=handle)
        print(file=handle)
        print(
            f"Two feeds break and keep breaking. {EVALUATIONS} evaluations, two alerts each,",
            file=handle,
        )
        print(f"{len(firings)} alert firings in total.", file=handle)
        print(file=handle)
        print(f"  notifications a human receives   {len(notifications)}", file=handle)
        routes: dict[str, int] = summary["notifications_by_route"]
        for route, count in routes.items():
            print(f"    {route:<16} {count}", file=handle)
        print(file=handle)
        print("  distinct alerts that reached anybody:", file=handle)
        names: list[str] = summary["distinct_alerts_reaching_a_human"]
        for name in names:
            print(f"    {name}", file=handle)
        print(file=handle)
        print(
            f"The completeness alert for {FEEDS[0]} is missing from that list on purpose. A feed",
            file=handle,
        )
        print(
            "that has not delivered at all cannot be incomplete in any interesting way, so it is",
            file=handle,
        )
        print(
            "suppressed while the freshness alert is firing: the same problem, restated.",
            file=handle,
        )
    print((OUT / "one-incident.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

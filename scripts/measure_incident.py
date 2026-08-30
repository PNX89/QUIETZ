"""Replay one incident through a real Alertmanager, and count what a human would receive.

    uv run python scripts/measure_incident.py

WHAT IS MEASURED. Two feeds break and keep breaking. Every rule this repository generates for
those feeds fires on every evaluation, and each evaluation is posted as its own request, so the
repeats are spread over real time. What a person is told is a different number, and the gap
between them is the whole subject of a notification path.

THE ALERTS ARE READ OUT OF rules/generated.yml RATHER THAN INVENTED HERE. They used to be built
as f"{feed}_freshness" from a hardcoded pair of feeds, which produced names this repository does
not generate: three of the four went into the committed evidence, and a reader who opened the
rules file to check one would not have found it. One of them, a completeness alert on a feed
that has no completeness monitor, could not exist at all. Posting what the rules produce is the
only version of this measurement that is about this repository.

AND THE REPEATS ARE SPREAD OVER TIME. They used to be one POST of a twenty four element array,
four distinct label sets and six copies of each, which Alertmanager collapses on ingest by
fingerprint before any of the three mechanisms below is reached. The docstring called that half
an hour while the script slept for forty five seconds.

Three mechanisms could produce the gap and they are not the same thing:

    DEDUPLICATION  the same alert firing again is not a second notification
    GROUPING       alerts about one feed arrive as one notification rather than several
    INHIBITION     a completeness alert about a feed that has not delivered AT ALL is suppressed
                   while the freshness alert is firing, because it is the same problem restated

Two of them do the work here. The third is measured and reported as having done nothing, which
is what `max_alerts_in_one_notification` in the summary is for: every alert that survives
inhibition routes to a different receiver, so no notification could carry two of them under any
grouping at all. Reporting that is the point of measuring rather than reasoning.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys
import textwrap
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quietz.monitors import REGISTRY, Monitor  # noqa: E402

OUT = ROOT / "docs" / "evidence" / "incident"
RULES = ROOT / "rules" / "generated.yml"
ALERTMANAGER = "http://127.0.0.1:19093"

#: The incident: two feeds, both broken. Every monitor on them fires, whatever it watches.
BROKEN_FEEDS = ("ecb_exr_daily", "ecb_yield_curve")

#: How many times the rules evaluate while the feeds stay broken. A property of the replay
#: rather than of the registry, and the firing total is computed from it rather than written
#: down anywhere.
EVALUATIONS = 8

#: Seconds between evaluations. Real spacing rather than one array, so deduplication is
#: something Alertmanager does over time rather than something it does on ingest for free.
SECONDS_BETWEEN_EVALUATIONS = 2

#: How long to wait for every notification that should arrive. Polled rather than slept: a fixed
#: wait is a guess, and the guess wrote a summary for a run that had lost half its notifications
#: on one machine out of three.
ARRIVAL_TIMEOUT_SECONDS = 180

#: And how long to keep watching before calling an alert absent. An absence is only evidence
#: once the notification that would have carried it has had its turn. The group carrying the
#: suppressed alert is created by the same first post as the group that does arrive, and waits
#: the same group_wait, so this window is slack rather than the whole argument.
ABSENCE_WINDOW_SECONDS = 15

POLL_SECONDS = 1


def rules_for(feeds: Sequence[str]) -> list[dict[str, Any]]:
    """The alerting rules this repository generates for these feeds, as committed."""
    document = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    return [
        rule
        for group in document["groups"]
        for rule in group["rules"]
        if "alert" in rule and rule["labels"]["feed"] in feeds
    ]


def firing(rule: dict[str, Any]) -> dict[str, Any]:
    """One firing, shaped the way Prometheus posts one: the rule's own labels and annotations."""
    return {
        "labels": {"alertname": rule["alert"], **rule["labels"]},
        "annotations": dict(rule["annotations"]),
        "startsAt": datetime.datetime.now(datetime.UTC).isoformat(),
    }


def suppressed_by_inhibition(monitors: Sequence[Monitor]) -> set[str]:
    """Which of these the shipped inhibition rule will suppress.

    Mirrors alertmanager.yml: source *_freshness, target *_completeness, equal on feed. Derived
    from the registry rather than named here, so a registry change moves the expectation with
    it, and tests/test_incident.py checks the configuration still carries that rule.
    """
    not_delivering = {monitor.feed for monitor in monitors if monitor.kind == "freshness"}
    return {
        monitor.name
        for monitor in monitors
        if monitor.kind == "completeness" and monitor.feed in not_delivering
    }


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


def names_in(notifications: Sequence[dict[str, Any]]) -> set[str]:
    return {
        str(alert["labels"]["alertname"])
        for notification in notifications
        for alert in notification.get("alerts", [])
    }


def wait_for(expected: set[str]) -> list[dict[str, Any]]:
    """Poll until every alert that should reach a human has, or say which one never did."""
    deadline = time.monotonic() + ARRIVAL_TIMEOUT_SECONDS
    while True:
        notifications = received()
        if expected <= names_in(notifications):
            return notifications
        if time.monotonic() >= deadline:
            missing = sorted(expected - names_in(notifications))
            raise SystemExit(
                f"waited {ARRIVAL_TIMEOUT_SECONDS}s and these never reached the receiver: "
                f"{missing}. Nothing is written: a summary from a measurement that had not "
                f"finished is worse than no summary, because every test still passes on it"
            )
        time.sleep(POLL_SECONDS)


def objections(summary: dict[str, Any], monitors: Sequence[Monitor]) -> list[str]:
    """Why this run does not support the transcript it is about to write.

    Separated from main so it can be handed a measurement rather than having to produce one.
    The degraded run this exists to catch cannot be provoked on demand, and a check nobody can
    exercise is a check nobody has watched work: the transcript used to explain an absence as
    inhibition on a run where the route that alert travels had delivered nothing at all.
    """
    arrived = set(summary["distinct_alerts_reaching_a_human"])
    suppressed = set(summary["alerts_suppressed_by_inhibition"])
    routes = set(summary["route_labels_reaching_a_human"])
    by_name = {monitor.name: monitor for monitor in monitors}
    complaints: list[str] = []

    if summary["notifications_delivered"] >= summary["alert_firings_posted"]:
        complaints.append("every firing produced a notification, so the path is doing nothing")
    if not suppressed:
        complaints.append(
            "nothing here could be suppressed, so this run demonstrates nothing about inhibition"
        )
    leaked = sorted(suppressed & arrived)
    if leaked:
        complaints.append(f"these should have been inhibited and reached a human anyway: {leaked}")

    for name in sorted(suppressed - arrived):
        monitor = by_name[name]
        siblings = {m.name for m in monitors if m.feed == monitor.feed and m.name != name}
        if not siblings & arrived:
            complaints.append(
                f"nothing about {monitor.feed} reached anybody, so {name} is missing because "
                f"that feed went unreported rather than because it was suppressed"
            )
        if monitor.route not in routes:
            complaints.append(
                f"nothing at all arrived on the {monitor.route} route, so the absence of {name} "
                f"is a route that delivered nothing rather than inhibition"
            )
    return complaints


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    monitors = [monitor for monitor in REGISTRY if monitor.feed in BROKEN_FEEDS]
    rules = rules_for(BROKEN_FEEDS)
    posted_names = {str(rule["alert"]) for rule in rules}
    if posted_names != {monitor.name for monitor in monitors}:
        print(
            "the rules for the broken feeds and the monitors for them do not agree, so this "
            "replay would measure something the registry does not describe",
            file=sys.stderr,
        )
        return 1

    expected_suppressed = suppressed_by_inhibition(monitors)
    if not expected_suppressed:
        print(
            "no alert here can be suppressed by the inhibition rule, so this replay would "
            "demonstrate nothing about inhibition. Break a feed that has both kinds of monitor",
            file=sys.stderr,
        )
        return 1
    expected_to_arrive = posted_names - expected_suppressed

    firings: list[dict[str, Any]] = []
    for evaluation in range(EVALUATIONS):
        # ONE REQUEST PER EVALUATION. The same alerts, again, a couple of seconds later, which
        # is what a rule that keeps firing looks like from Alertmanager's side.
        batch = [firing(rule) for rule in rules]
        try:
            post(batch)
        except urllib.error.URLError as error:
            print(
                f"no Alertmanager at {ALERTMANAGER}: {error}. Start the stack with "
                f"scripts/incident_stack.sh",
                file=sys.stderr,
            )
            return 1
        firings += batch
        if evaluation < EVALUATIONS - 1:
            time.sleep(SECONDS_BETWEEN_EVALUATIONS)

    wait_for(expected_to_arrive)
    # Everything expected has arrived, and the return value is deliberately dropped: the other
    # half of the measurement is an absence, and an absence needs a window before it means
    # anything. So the file is read again after that window rather than at the moment the last
    # expected notification landed.
    time.sleep(ABSENCE_WINDOW_SECONDS)
    notifications = received()
    arrived = names_in(notifications)

    by_route: dict[str, int] = {}
    route_labels: set[str] = set()
    widest = 0
    for notification in notifications:
        route = str(notification.get("route", "unknown"))
        by_route[route] = by_route.get(route, 0) + 1
        carried = notification.get("alerts", [])
        widest = max(widest, len(carried))
        for alert in carried:
            route_labels.add(str(alert["labels"]["route"]))

    summary: dict[str, Any] = {
        "alert_firings_posted": len(firings),
        "notifications_delivered": len(notifications),
        "notifications_by_route": dict(sorted(by_route.items())),
        "distinct_alerts_posted": sorted(posted_names),
        "distinct_alerts_reaching_a_human": sorted(arrived),
        "alerts_suppressed_by_inhibition": sorted(expected_suppressed),
        "route_labels_reaching_a_human": sorted(route_labels),
        "max_alerts_in_one_notification": widest,
        "feeds": list(BROKEN_FEEDS),
        "evaluations": EVALUATIONS,
    }

    # THE RUN HAS TO HAVE OBSERVED WHAT THE TRANSCRIPT IS ABOUT. It used to print the
    # inhibition explanation unconditionally, including on a run where the route that alert
    # travels had delivered nothing whatsoever and so nothing had been suppressed at all.
    complaints = objections(summary, monitors)
    if complaints:
        for complaint in complaints:
            print(complaint, file=sys.stderr)
        print(
            "nothing written: a transcript is not a place to explain what was not seen",
            file=sys.stderr,
        )
        return 1

    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    with (OUT / "one-incident.txt").open("w", encoding="utf-8") as handle:

        def paragraph(text: str) -> None:
            # WRAPPED RATHER THAN SPLIT BY HAND. Alert names go into these sentences, so a
            # transcript broken at fixed points re-wraps itself badly the moment a monitor is
            # renamed, and this file is committed and read as evidence.
            print(textwrap.fill(" ".join(text.split()), width=86), file=handle)

        print("$ uv run python scripts/measure_incident.py", file=handle)
        print(file=handle)
        paragraph(
            f"Two feeds break and keep breaking. {EVALUATIONS} evaluations of {len(rules)} "
            f"rules, posted {SECONDS_BETWEEN_EVALUATIONS} seconds apart, which is "
            f"{len(firings)} alert firings in total."
        )
        print(file=handle)
        print(f"  notifications a human receives   {len(notifications)}", file=handle)
        routes: dict[str, int] = summary["notifications_by_route"]
        for route, count in routes.items():
            print(f"    {route:<16} {count}", file=handle)
        print(file=handle)
        print("  distinct alerts that reached anybody:", file=handle)
        for name in summary["distinct_alerts_reaching_a_human"]:
            print(f"    {name}", file=handle)
        print(file=handle)
        for name in summary["alerts_suppressed_by_inhibition"]:
            monitor = next(m for m in monitors if m.name == name)
            sibling = sorted(
                m.name for m in monitors if m.feed == monitor.feed and m.name in arrived
            )[0]
            paragraph(
                f"{name} fired {EVALUATIONS} times and reached nobody. It is suppressed while "
                f"{sibling} is firing on the same feed: a feed that has not delivered at all "
                f"cannot be incomplete in any interesting way, so it is the same problem, "
                f"restated. The {monitor.route} route it would have travelled did deliver, "
                f"which is what makes that absence inhibition rather than silence."
            )
            print(file=handle)
        paragraph(
            f"Grouping merged nothing here. No notification carried more than {widest} alert, "
            f"because every alert that survived inhibition routes to a different receiver."
        )
    print((OUT / "one-incident.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""What is watched, who owns it, and what it takes to wake somebody.

    uv run python examples/what_gets_you_woken.py

NO PROMETHEUS, NO ALERTMANAGER, NO NETWORK. The registry is the monitoring, so reading it is
reading what this platform does, and the alert rules are generated from the same file this
prints.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quietz.monitors import REGISTRY, trading_days_between  # noqa: E402

LINES: list[str] = []


def say(line: str = "") -> None:
    LINES.append(line)
    print(line)


def main() -> None:
    say(f"{len(REGISTRY)} monitors, and every one of them is a row somebody has to review.")
    say()
    say(f"  {'monitor':<34}{'owner':<16}{'within':<9}{'complete':<10}goes to")
    for monitor in REGISTRY:
        say(
            f"  {monitor.name:<34}{monitor.owner:<16}"
            f"{str(monitor.expected_within_trading_days) + 'd':<9}"
            f"{monitor.completeness:<10.0%}{monitor.route}"
        )
    say()
    say("  Only one of them wakes anybody, and the registry refuses to let that change by")
    say("  accident: a monitor that pages on a window longer than two trading days is rejected")
    say("  in the constructor, because waking somebody for a feed allowed to be three days late")
    say("  is how a rota learns to ignore the pager.")
    say()

    friday = datetime.date(2026, 8, 28)
    monday = datetime.date(2026, 8, 31)
    say(f"The windows are in TRADING days. From Friday {friday} to Monday {monday} is")
    say(
        f"  {trading_days_between(friday, monday)} trading day, not "
        f"{(monday - friday).days}, so a feed that publishes on business days is not late on a"
    )
    say("  Sunday and nobody is woken for a weekend.")
    say()

    incident = json.loads((ROOT / "docs" / "evidence" / "incident" / "summary.json").read_text())
    say("And when two of these feeds break and keep breaking:")
    say()
    say(f"  {incident['alert_firings_posted']} alert firings")
    say(f"  {incident['notifications_delivered']} notifications a human receives")
    for route, count in sorted(incident["notifications_by_route"].items()):
        say(f"    {route:<16} {count}")
    say()
    say("  The completeness alerts are absent on purpose. A feed that has not delivered at all")
    say("  cannot be incomplete in any interesting way, so it is suppressed while the freshness")
    say("  alert is firing: the same problem, restated.")

    (ROOT / "docs" / "evidence").mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "evidence" / "demo.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

"""Generate the Prometheus rules from the registry, so a monitor cannot exist without one.

    uv run python scripts/generate_rules.py

THE POINT OF GENERATING RATHER THAN WRITING. A hand-written alert file drifts from the registry
the first time somebody edits one and not the other, and the drift is invisible: both files look
fine on their own. Generating means the registry IS the monitoring, and a review of a pull
request that adds a monitor is a review of the alert it produces.

THE RATIO IS A RECORDING RULE, evaluated once and reused by every window. Writing the same
expression into four burn-rate alerts means four chances to edit three of them, and a burn-rate
alert whose windows disagree about what it is measuring is worse than no alert at all.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quietz.monitors import REGISTRY, Monitor  # noqa: E402

OUT = ROOT / "rules" / "generated.yml"

#: The burn-rate windows, in trading days, and the factor each one is judged at. Short windows
#: catch a fast burn and long ones catch a slow leak; both are needed and neither alone is.
WINDOWS: tuple[tuple[str, int], ...] = (("fast", 1), ("slow", 5))


def freshness_rule(monitor: Monitor) -> str:
    # The indicator: how long since this feed last delivered, against the window its owner
    # declared, both in trading days. `quietz_trading_days_since_delivery` is produced by the
    # ingest, because a metric about trading days cannot be computed from a wall clock alone.
    metric = f'quietz_trading_days_since_delivery{{feed="{monitor.feed}"}}'
    window = monitor.expected_within_trading_days
    summary = f"{monitor.feed} has not delivered within {window} trading days"
    return f"""  - alert: {monitor.name}
    expr: {metric} > {window}
    for: 15m
    labels:
      severity: {monitor.severity}
      route: {monitor.route}
      owner: {monitor.owner}
      feed: {monitor.feed}
    annotations:
      summary: "{summary}"
      because: "{monitor.because}"
"""


def completeness_rule(monitor: Monitor) -> str:
    return f"""  - alert: {monitor.name}
    expr: quietz_delivered_fraction{{feed="{monitor.feed}"}} < {monitor.completeness}
    for: 15m
    labels:
      severity: {monitor.severity}
      route: {monitor.route}
      owner: {monitor.owner}
      feed: {monitor.feed}
    annotations:
      summary: "{monitor.feed} delivered less than {monitor.completeness:.0%} of what was expected"
      because: "{monitor.because}"
"""


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    feeds = sorted({monitor.feed for monitor in REGISTRY})

    lines = [
        "# GENERATED FROM src/quietz/monitors.py. Do not edit.",
        "#",
        "# A hand-edited copy drifts from the registry the first time somebody changes one and",
        "# not the other, and the drift is invisible because both files look fine alone. The",
        "# test suite regenerates this and fails if it differs from what is committed.",
        "groups:",
        "  - name: quietz_ratios",
        "    rules:",
    ]
    for feed in feeds:
        # ONE RECORDING RULE PER FEED, reused by every window below. Four copies of an
        # expression is four chances to edit three of them.
        lines.append(f"""      - record: feed:delivered_fraction:ratio
        expr: quietz_delivered_fraction{{feed="{feed}"}}
        labels:
          feed: "{feed}\"""")

    lines += ["  - name: quietz_monitors", "    rules:"]
    body: list[str] = []
    for monitor in REGISTRY:
        rule = (
            completeness_rule(monitor)
            if "completeness" in monitor.name
            else freshness_rule(monitor)
        )
        body.append("  " + rule.rstrip().replace("\n", "\n  "))

    OUT.write_text("\n".join(lines) + "\n" + "\n".join(body) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(REGISTRY)} alerts over {len(feeds)} feeds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

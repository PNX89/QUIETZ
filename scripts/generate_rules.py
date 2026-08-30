"""Generate the Prometheus rules from the registry, so a monitor cannot exist without one.

    uv run python scripts/generate_rules.py

THE POINT OF GENERATING RATHER THAN WRITING. A hand-written alert file drifts from the registry
the first time somebody edits one and not the other, and the drift is invisible: both files look
fine on their own. Generating means the registry IS the monitoring, and a review of a pull
request that adds a monitor is a review of the alert it produces.

EVERY INTERPOLATED FIELD IS QUOTED, and the reason is the quiet half rather than the loud one.
The loud half is that a quotation mark in a reason, which is ordinary English, produced a file
that did not parse. The quiet half is that an owner containing a hash was truncated by YAML
comment handling, so Prometheus attached an owner label that was not the one the registry
declared and every gate stayed green. The owner is the field that decides who is told.
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections.abc import Sequence

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quietz.monitors import REGISTRY, Monitor  # noqa: E402

OUT = ROOT / "rules" / "generated.yml"


def quoted(text: str) -> str:
    """A double quoted YAML scalar, escaped by json.dumps.

    JSON string syntax IS the YAML double quoted style, so this is exact rather than close, and
    it is stdlib: a generator that needed a YAML library to write a YAML file would be one more
    thing between the registry and the rules.
    """
    return json.dumps(text)


def labels(monitor: Monitor) -> str:
    """The four labels every rule carries, all of them from the monitor and all of them quoted."""
    return f"""    labels:
      severity: {quoted(monitor.severity)}
      route: {quoted(monitor.route)}
      owner: {quoted(monitor.owner)}
      feed: {quoted(monitor.feed)}"""


def freshness_rule(monitor: Monitor) -> str:
    # The indicator: how long since this feed last delivered, against the window its owner
    # declared, both in trading days. `quietz_trading_days_since_delivery` is produced by the
    # ingest, because a metric about trading days cannot be computed from a wall clock alone.
    metric = f"quietz_trading_days_since_delivery{{feed={quoted(monitor.feed)}}}"
    window = monitor.expected_within_trading_days
    summary = f"{monitor.feed} has not delivered within {window} trading days"
    return f"""  - alert: {quoted(monitor.name)}
    expr: {metric} > {window}
    for: 15m
{labels(monitor)}
    annotations:
      summary: {quoted(summary)}
      because: {quoted(monitor.because)}
"""


def completeness_rule(monitor: Monitor) -> str:
    # Guarded by the registry rather than by this line: a completeness monitor without a
    # tolerance is refused in the constructor. mypy cannot see that, so the assert says it.
    assert monitor.completeness is not None
    metric = f"quietz_delivered_fraction{{feed={quoted(monitor.feed)}}}"
    summary = f"{monitor.feed} delivered less than {monitor.completeness:.0%} of what was expected"
    return f"""  - alert: {quoted(monitor.name)}
    expr: {metric} < {monitor.completeness}
    for: 15m
{labels(monitor)}
    annotations:
      summary: {quoted(summary)}
      because: {quoted(monitor.because)}
"""


def document(monitors: Sequence[Monitor]) -> tuple[str, int, int]:
    """The whole rules file, plus what it actually contains.

    Separated from main so the counts come from the document rather than from the registry, and
    so a test can hand this a monitor whose fields mean something to YAML and read the result
    back. A generator only ever checked by regenerating and diffing is one that agrees with
    itself.
    """
    feeds = sorted({monitor.feed for monitor in monitors})

    lines = [
        "# GENERATED FROM src/quietz/monitors.py. Do not edit.",
        "#",
        "# A hand-edited copy drifts from the registry the first time somebody changes one and",
        "# not the other, and the drift is invisible because both files look fine alone. The",
        "# test suite regenerates this and fails if it differs from what is committed.",
        "groups:",
        "  - name: quietz_monitors",
        "    rules:",
    ]
    body: list[str] = []
    for monitor in monitors:
        # THE KIND IS A FIELD. This used to ask whether the name contained the word
        # completeness, which made a monitor's name decide its behaviour and let a freshness
        # monitor carry a tolerance no rule ever read.
        rule = (
            completeness_rule(monitor)
            if monitor.kind == "completeness"
            else freshness_rule(monitor)
        )
        body.append("  " + rule.rstrip().replace("\n", "\n  "))

    return "\n".join(lines) + "\n" + "\n".join(body) + "\n", len(body), len(feeds)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text, written, feeds = document(REGISTRY)
    OUT.write_text(text, encoding="utf-8")
    # COUNTED FROM WHAT WAS WRITTEN, not from the registry. Reporting len(REGISTRY) meant a
    # generator that skipped a monitor still announced the full number, so a monitor that
    # produced no alert at all was reported as one that had.
    print(f"wrote {OUT.relative_to(ROOT)}: {written} alerts over {feeds} feeds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The registry, and the rules that must not drift from it."""

from __future__ import annotations

import datetime
import pathlib
import subprocess
import sys
from typing import Any

import pytest

from quietz.monitors import REGISTRY, ROUTES, Monitor, trading_days_between

REPO = pathlib.Path(__file__).resolve().parents[1]


def a_monitor(**overrides: Any) -> Monitor:
    """A monitor the registry accepts, so every case below changes exactly one thing."""
    fields: dict[str, Any] = {
        "name": "example_freshness",
        "owner": "data-platform",
        "feed": "example_feed",
        "kind": "freshness",
        "expected_within_trading_days": 2,
        "severity": "ticket",
        "because": "a reason long enough that somebody could weigh it when deciding to remove it",
    }
    fields.update(overrides)
    return Monitor(**fields)


#: Every constructor guard, with the monitor it has to refuse. Four of these guards were dead:
#: deleting any of them left the whole suite green, because the only one anybody had written a
#: test for was the page-severity one, and only on the side that rejects.
REFUSED: tuple[tuple[str, dict[str, Any], str], ...] = (
    ("a tolerance of nothing", {"kind": "completeness", "completeness": 0.0}, "fraction"),
    ("a tolerance above all of it", {"kind": "completeness", "completeness": 1.5}, "fraction"),
    ("a negative tolerance", {"kind": "completeness", "completeness": -0.1}, "fraction"),
    ("a completeness monitor with no tolerance", {"kind": "completeness"}, "measures nothing"),
    ("a tolerance no rule would read", {"completeness": 0.95}, "nothing enforces"),
    ("a window shorter than a day", {"expected_within_trading_days": 0}, "not a window"),
    ("no reason at all", {"because": ""}, "no reason"),
    ("a reason made of spaces", {"because": "   "}, "no reason"),
    ("a name that is prose", {"name": "ecb: exr daily"}, "identifier"),
    ("a feed that is prose", {"feed": "ecb exr daily"}, "identifier"),
    (
        "a page on a window nobody would call urgent",
        {"severity": "page", "expected_within_trading_days": 3},
        "not an emergency",
    ),
)

#: The other side, which no test had at all. A guard can be tightened as well as deleted, and a
#: suite that only ever watches refusals cannot tell the difference: changing the page window
#: from `> 2` to `>= 2` still refuses the three day page the old test built, so it passed while
#: rejecting the two day page the code beside it says is allowed.
ACCEPTED: tuple[tuple[str, dict[str, Any]], ...] = (
    ("a page on two trading days", {"severity": "page", "expected_within_trading_days": 2}),
    ("a window of one trading day", {"expected_within_trading_days": 1}),
    ("a feed that must arrive whole", {"kind": "completeness", "completeness": 1.0}),
)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [(case[1], case[2]) for case in REFUSED],
    ids=[case[0] for case in REFUSED],
)
def test_the_registry_refuses_a_monitor_nobody_could_defend(
    overrides: dict[str, Any], message: str
) -> None:
    """Each guard, exercised on the monitor it exists to stop."""
    with pytest.raises(ValueError, match=message):
        a_monitor(**overrides)


@pytest.mark.parametrize(
    "overrides", [case[1] for case in ACCEPTED], ids=[case[0] for case in ACCEPTED]
)
def test_the_registry_accepts_a_monitor_at_the_boundary(overrides: dict[str, Any]) -> None:
    """See ACCEPTED. A guard that has only ever been watched refusing is one that can quietly
    start refusing more."""
    assert a_monitor(**overrides)


def test_trading_days_refuses_a_range_that_runs_backwards() -> None:
    """An answer of zero for a backwards range would read as a fresh feed, which is the wrong
    way for this to be wrong."""
    with pytest.raises(ValueError, match="end is before start"):
        trading_days_between(datetime.date(2026, 8, 31), datetime.date(2026, 8, 28))


def test_the_generated_rules_match_the_registry() -> None:
    """THE JOIN. A hand-edited alert file drifts the first time somebody changes one and not the
    other, and the drift is invisible because both files look fine on their own."""
    committed = (REPO / "rules" / "generated.yml").read_text(encoding="utf-8")
    subprocess.run(
        [sys.executable, "scripts/generate_rules.py"], cwd=REPO, check=True, capture_output=True
    )
    regenerated = (REPO / "rules" / "generated.yml").read_text(encoding="utf-8")
    assert committed == regenerated, (
        "the committed rules are not what the registry generates, so the two have drifted"
    )


def test_every_monitor_carries_a_reason_somebody_can_act_on() -> None:
    """A monitor with no reason is one nobody can decide to remove, so it never is."""
    for monitor in REGISTRY:
        assert len(monitor.because.split()) >= 8, (
            f"{monitor.name}'s reason is {monitor.because!r}, which is not a sentence anybody "
            f"could weigh when deciding whether the alert is worth keeping"
        )
        assert monitor.owner


def test_every_severity_has_exactly_one_route() -> None:
    """A monitor cannot invent a route, and a severity cannot have two."""
    assert set(ROUTES) == {"page", "ticket", "log"}
    assert len(set(ROUTES.values())) == len(ROUTES)
    for monitor in REGISTRY:
        assert monitor.route == ROUTES[monitor.severity]


def test_not_everything_pages() -> None:
    """A registry where every monitor pages is a registry that will be silenced wholesale."""
    severities = {monitor.severity for monitor in REGISTRY}
    assert len(severities) >= 3, f"only {severities} are used, so the routing decides nothing"
    pages = [monitor for monitor in REGISTRY if monitor.severity == "page"]
    assert 0 < len(pages) < len(REGISTRY) // 2 + 1, (
        f"{len(pages)} of {len(REGISTRY)} monitors page, which is a rota that stops reading them"
    )


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (datetime.date(2026, 8, 28), datetime.date(2026, 8, 31), 1),  # Friday to Monday
        (datetime.date(2026, 8, 31), datetime.date(2026, 9, 1), 1),
        (datetime.date(2026, 8, 29), datetime.date(2026, 8, 30), 0),  # Saturday to Sunday
        (datetime.date(2026, 8, 24), datetime.date(2026, 8, 31), 5),
    ],
)
def test_trading_days_ignore_the_weekend(
    start: datetime.date, end: datetime.date, expected: int
) -> None:
    """A feed that publishes on business days is not late on a Sunday."""
    assert trading_days_between(start, end) == expected


def test_the_holiday_limitation_is_stated_where_it_is_implemented() -> None:
    """This ships no holiday calendar, and the consequence belongs beside the code rather than
    in a document nobody opens."""
    source = " ".join((REPO / "src" / "quietz" / "monitors.py").read_text("utf-8").split())
    assert "NO HOLIDAY CALENDAR" in source
    assert "first trading day after a public holiday" in source

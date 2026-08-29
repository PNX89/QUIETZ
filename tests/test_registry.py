"""The registry, and the rules that must not drift from it."""

from __future__ import annotations

import datetime
import pathlib
import subprocess
import sys

import pytest

from quietz.monitors import REGISTRY, ROUTES, Monitor, trading_days_between

REPO = pathlib.Path(__file__).resolve().parents[1]


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


def test_a_page_cannot_be_declared_on_a_window_that_is_not_urgent() -> None:
    """Waking somebody for a feed allowed to be three days late is how a rota learns to ignore
    the pager, so the registry refuses it rather than leaving it to review."""
    with pytest.raises(ValueError, match="not an emergency"):
        Monitor(
            name="x",
            owner="y",
            feed="f",
            expected_within_trading_days=3,
            completeness=1.0,
            severity="page",
            because="a reason long enough to pass the other guard in this constructor",
        )


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

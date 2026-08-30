"""What a person is actually told when a feed breaks and keeps breaking."""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

import pytest
import yaml

from quietz.monitors import REGISTRY

REPO = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs" / "evidence" / "incident"
CONFIG = REPO / "alertmanager" / "alertmanager.yml"

sys.path.insert(0, str(REPO / "scripts"))
import measure_incident  # noqa: E402


def summary() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((EVIDENCE / "summary.json").read_text(encoding="utf-8"))
    return loaded


def monitors_in_the_incident() -> list[Any]:
    return [monitor for monitor in REGISTRY if monitor.feed in summary()["feeds"]]


def test_the_notification_path_reduces_a_burst_to_something_readable() -> None:
    """A path that delivers every firing is a path nobody reads by the second incident."""
    numbers = summary()
    assert numbers["alert_firings_posted"] >= 20
    assert numbers["notifications_delivered"] < numbers["alert_firings_posted"] / 4, (
        f"{numbers['notifications_delivered']} notifications from "
        f"{numbers['alert_firings_posted']} firings, which is not a reduction anybody would "
        f"notice"
    )


def test_something_still_reaches_a_human() -> None:
    """The other half. A path that delivers nothing is quieter and useless."""
    numbers = summary()
    assert numbers["notifications_delivered"] > 0
    assert numbers["distinct_alerts_reaching_a_human"], "nobody was told anything at all"
    assert "oncall" in numbers["notifications_by_route"], (
        "nothing reached the paging route, so the severity that exists to wake somebody did not"
    )


def test_the_inhibited_alert_did_not_reach_anybody() -> None:
    """The measurement that separates inhibition from deduplication.

    A feed that has not delivered at all cannot be incomplete in any interesting way, so its
    completeness alert is the same problem restated. Deduplication would not have stopped it:
    it is a different alert with a different name.
    """
    numbers = summary()
    suppressed = set(numbers["alerts_suppressed_by_inhibition"])
    reached = set(numbers["distinct_alerts_reaching_a_human"])
    assert suppressed, "no alert here could be suppressed, so this measures nothing about it"
    assert suppressed <= set(numbers["distinct_alerts_posted"]), (
        "an alert cannot be shown suppressed unless it was fired at in the first place"
    )
    assert suppressed & reached == set(), f"a suppressed alert reached a human: {reached}"


def test_the_measurement_is_arithmetically_possible() -> None:
    """Committed evidence is the one artefact here nobody re-derives when they read it.

    These three lines are the ones a hand edit trips over. More distinct alerts reaching a human
    than the notifications could have carried is not a suspicious number, it is an impossible
    one, and it is what a summary edited to make a claim work looks like.
    """
    numbers = summary()
    by_route: dict[str, int] = numbers["notifications_by_route"]
    assert sum(by_route.values()) == numbers["notifications_delivered"]
    assert len(numbers["distinct_alerts_reaching_a_human"]) <= (
        numbers["notifications_delivered"] * numbers["max_alerts_in_one_notification"]
    ), "more alerts reached a human than the notifications delivered could have carried"
    assert set(numbers["distinct_alerts_reaching_a_human"]) <= set(
        numbers["distinct_alerts_posted"]
    ), "an alert reached a human that this incident never fired"

    # THE TWO LISTS ARE THE SAME NOTIFICATIONS COUNTED TWICE, so they cannot disagree. A route
    # reported as having delivered while no alert that travels it reached anybody is the shape a
    # summary takes when one of its lists has been edited and the other has not, and without
    # this the positive control above passes on exactly that.
    by_name = {monitor.name: monitor for monitor in REGISTRY}
    routes_of_the_arrived = {
        by_name[name].route for name in numbers["distinct_alerts_reaching_a_human"]
    }
    assert routes_of_the_arrived == set(numbers["route_labels_reaching_a_human"]), (
        f"the alerts that arrived travel {sorted(routes_of_the_arrived)} and the summary reports "
        f"{sorted(numbers['route_labels_reaching_a_human'])} as having delivered"
    )


def test_the_absence_is_inhibition_rather_than_a_route_that_delivered_nothing() -> None:
    """THE POSITIVE CONTROL, which is the half that was missing.

    Every assertion in this file used to be satisfied most comfortably by the run that measured
    least. A replay delivering one notification on the paging route passed all six: the
    reduction looked better, something still reached a human, and no completeness alert arrived
    because the route those travel had delivered nothing whatsoever. An absence only proves
    suppression when the thing that would have carried it did arrive.
    """
    numbers = summary()
    complaints = measure_incident.objections(numbers, monitors_in_the_incident())
    assert complaints == [], (
        f"the committed evidence does not support the transcript beside it: {complaints}"
    )
    for name in numbers["alerts_suppressed_by_inhibition"]:
        monitor = next(m for m in REGISTRY if m.name == name)
        assert monitor.route in numbers["route_labels_reaching_a_human"], (
            f"nothing arrived on the {monitor.route} route, so the absence of {name} is a route "
            f"that delivered nothing"
        )


#: A run that measured almost nothing and was written out as though it were the whole thing.
#: Recorded from a real replay rather than imagined: same configuration, same code, one
#: notification instead of two, and the harness committed the inhibition explanation anyway.
DEGRADED_RUN: dict[str, Any] = {
    "alert_firings_posted": 24,
    "notifications_delivered": 1,
    "notifications_by_route": {"oncall": 1},
    "distinct_alerts_posted": [
        "ecb_reference_rate_completeness",
        "ecb_reference_rate_freshness",
        "ecb_yield_curve_freshness",
    ],
    "distinct_alerts_reaching_a_human": ["ecb_reference_rate_freshness"],
    "alerts_suppressed_by_inhibition": ["ecb_reference_rate_completeness"],
    "route_labels_reaching_a_human": ["oncall"],
    "max_alerts_in_one_notification": 1,
    "feeds": ["ecb_exr_daily", "ecb_yield_curve"],
    "evaluations": 8,
}


def test_the_harness_refuses_to_narrate_a_run_that_lost_half_its_notifications() -> None:
    """See DEGRADED_RUN. The check that would have caught it, driven by the run that got past
    it, because a refusal nobody has watched refuse is a refusal nobody has tested."""
    complaints = measure_incident.objections(DEGRADED_RUN, list(REGISTRY))
    assert any("data-platform" in complaint for complaint in complaints), (
        f"the ticket route delivered nothing and this was not one of the objections: {complaints}"
    )


def test_the_harness_refuses_to_write_a_measurement_that_never_finished() -> None:
    """The other half of the same lesson. The settle was `sleep(45)` with a comment calling it
    long enough, and the only completeness check fired when the receiver had recorded nothing at
    all, so a run that captured some of the notifications was written out as the whole thing."""
    measure_incident.ARRIVAL_TIMEOUT_SECONDS = 0
    try:
        with pytest.raises(SystemExit, match="never reached the receiver"):
            measure_incident.wait_for({"an_alert_that_will_never_arrive"})
    finally:
        measure_incident.ARRIVAL_TIMEOUT_SECONDS = 180


def test_the_path_is_configured_to_fail_open_and_says_why() -> None:
    """THE DECISION THAT RUNS AGAINST THE GRAIN OF EVERY OTHER REPOSITORY HERE.

    The others fail closed: when a check cannot run, refuse. That is right when what is refused
    is a promotion or a payment. It is wrong for a notification path, because failing closed
    means suppressing, and a monitoring system that goes quiet when it is confused is silent
    exactly when something is most wrong.
    """
    text = " ".join(CONFIG.read_text(encoding="utf-8").split())
    assert "FAILING OPEN, ON PURPOSE" in text
    assert "most silent exactly when something is most wrong" in text

    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    # An inhibition rule that matched on an ABSENT label would suppress alerts it was never
    # meant to reach, which is the fail-closed failure in miniature.
    for rule in config["inhibit_rules"]:
        assert rule["equal"], "an inhibition rule with no equality suppresses across feeds"
        assert rule["source_matchers"] and rule["target_matchers"]


def test_grouping_merged_nothing_in_this_replay() -> None:
    """THE MECHANISM THE PAGE USED TO CREDIT, MEASURED RATHER THAN ASSERTED.

    Grouping by feed is a sound choice and the reasoning for it holds: two alerts about one
    broken feed arriving separately is two pages for one incident. It is not what produced the
    measured gap here, and the page used to say it was. Inhibition removes the completeness
    alert before grouping sees it, and every alert that survives routes to a different receiver
    from every other, so no notification could carry two under any group_by at all.

    Asserting `group_by == ["feed"]` was a YAML literal compared to a literal: a guard nothing
    exercised. This asserts what was observed instead, so the day a registry change makes
    grouping do something, this goes red and the page's account of it stops being true.
    """
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert config["route"]["group_by"] == ["feed"]
    assert summary()["max_alerts_in_one_notification"] == 1, (
        "a notification carried more than one alert, so grouping did something here and the "
        "page still says it did nothing"
    )


def test_the_inhibition_rule_is_still_the_one_the_harness_mirrors() -> None:
    """The harness works out which alert should be suppressed from the registry, which is only
    right while the shipped rule keeps this shape. Change the rule and the expectation the
    measurement is checked against would silently stop matching the configuration."""
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert [
        (rule["source_matchers"], rule["target_matchers"], rule["equal"])
        for rule in config["inhibit_rules"]
    ] == [(['alertname=~".*_freshness"'], ['alertname=~".*_completeness"'], ["feed"])]


def test_there_is_no_catch_all_silence() -> None:
    """A silence that matches everything is a monitoring system somebody has switched off."""
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert "mute_time_intervals" not in config.get("route", {}), (
        "the root route mutes on a time interval, which is a scheduled blind spot"
    )
    for route in config["route"].get("routes", []):
        assert "mute_time_intervals" not in route

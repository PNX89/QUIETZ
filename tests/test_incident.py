"""What a person is actually told when a feed breaks and keeps breaking."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs" / "evidence" / "incident"
CONFIG = REPO / "alertmanager" / "alertmanager.yml"


def summary() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((EVIDENCE / "summary.json").read_text(encoding="utf-8"))
    return loaded


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
    reached = summary()["distinct_alerts_reaching_a_human"]
    assert any(name.endswith("_freshness") for name in reached)
    assert not any(name.endswith("_completeness") for name in reached), (
        f"a completeness alert reached a human while its feed's freshness alert was firing: "
        f"{reached}"
    )


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


def test_grouping_is_by_feed_rather_than_by_alert_name() -> None:
    """Grouping by alertname puts two alerts about one broken feed in two notifications."""
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert config["route"]["group_by"] == ["feed"]


def test_there_is_no_catch_all_silence() -> None:
    """A silence that matches everything is a monitoring system somebody has switched off."""
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert "mute_time_intervals" not in config.get("route", {}), (
        "the root route mutes on a time interval, which is a scheduled blind spot"
    )
    for route in config["route"].get("routes", []):
        assert "mute_time_intervals" not in route

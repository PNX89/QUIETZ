"""The joins nothing checked: registry to rules, and rules to the tests of those rules.

WHY A SEPARATE FILE. `test_the_generated_rules_match_the_registry` regenerates the rules and
compares them byte for byte, which catches a hand-edited alert file and nothing else. Both sides
of that comparison come out of the same generator, so a generator that skipped a monitor
produced a file that matched itself and every gate stayed green. The checks here read the
committed rules as a document and ask whether they say what the registry declares.

AND THE HEADLINE CLAIM. "The rules are tested in both directions" is a README heading, a CI job
name and a sentence on the published card, and all of it rested on a file nothing opened.
`promtool test rules` reports SUCCESS on an empty test list, and it only checks the alertnames a
test happens to name, so an alert nobody named was an alert nobody tested.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import sys
from typing import Any

import pytest
import yaml

from quietz.monitors import REGISTRY, Monitor

REPO = pathlib.Path(__file__).resolve().parents[1]
RULES = REPO / "rules" / "generated.yml"
RULE_TESTS = REPO / "rules" / "generated_test.yml"

sys.path.insert(0, str(REPO / "scripts"))
import generate_rules  # noqa: E402

#: The registry, pinned by name and by size, because every check below builds its expectation
#: out of REGISTRY. Read from REGISTRY alone they would shrink with it: delete a monitor and the
#: suite covers one case fewer and stays green, which reads exactly like a pass. Adding or
#: removing a monitor is meant to be a pull request somebody reviews, and this is the line that
#: makes the reviewer see it.
PINNED_MONITORS: frozenset[str] = frozenset(
    {
        "ecb_reference_rate_freshness",
        "ecb_reference_rate_completeness",
        "ecb_yield_curve_freshness",
        "ecb_bank_rates_completeness",
    }
)

#: metric{selector} followed by a comparison and a threshold. Parsed rather than rebuilt from
#: the generator's own f-string, which would only prove the template equals itself.
EXPRESSION = re.compile(
    r"^(?P<metric>[a-z_][a-z0-9_]*)\{(?P<selector>[^}]*)\}\s*(?P<op>[<>])\s*(?P<threshold>\S+)$"
)

#: What each kind of monitor is measured with, and which way its comparison points.
INDICATOR: dict[str, tuple[str, str]] = {
    "freshness": ("quietz_trading_days_since_delivery", ">"),
    "completeness": ("quietz_delivered_fraction", "<"),
}


def alerts() -> dict[str, dict[str, Any]]:
    """Every alerting rule in the committed file, by name."""
    document = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    return {
        rule["alert"]: rule
        for group in document["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }


def by_name() -> dict[str, Monitor]:
    return {monitor.name: monitor for monitor in REGISTRY}


def asserted() -> tuple[set[str], set[str]]:
    """Which alertnames the unit tests assert firing, and which they assert silent.

    An assertion with no `exp_alerts`, or an empty one, is promtool's way of saying nothing
    fires. That is the direction the whole file exists for, so it is collected rather than
    skipped.
    """
    document = yaml.safe_load(RULE_TESTS.read_text(encoding="utf-8"))
    firing: set[str] = set()
    quiet: set[str] = set()
    for case in document.get("tests") or []:
        for assertion in case.get("alert_rule_test") or []:
            name = str(assertion["alertname"])
            if assertion.get("exp_alerts"):
                firing.add(name)
            else:
                quiet.add(name)
    return firing, quiet


def test_the_registry_is_the_set_this_suite_pins() -> None:
    """See PINNED_MONITORS. A monitor that leaves without anybody noticing takes its coverage
    with it, and the suite that was watching it reports the same green as before."""
    assert {monitor.name for monitor in REGISTRY} == set(PINNED_MONITORS)
    assert len(REGISTRY) == len(PINNED_MONITORS) == 4


def test_every_monitor_has_exactly_one_generated_rule() -> None:
    """THE JOIN THE BYTE COMPARISON CANNOT MAKE.

    A monitor with an owner, a tolerance and a stated reason used to be able to produce no alert
    at all: the generator's loop was the only thing that put the two together, and the only
    check on it regenerated the file and compared it to itself.
    """
    generated = set(alerts())
    declared = {monitor.name for monitor in REGISTRY}
    assert generated == declared, (
        f"the registry declares {sorted(declared - generated)} with no rule, and the rules "
        f"carry {sorted(generated - declared)} with no monitor"
    )
    assert len(alerts()) == len(REGISTRY)


def test_every_generated_rule_carries_the_fields_its_monitor_declares() -> None:
    """The labels and the threshold, read back out of the document.

    This is what catches a field that was mangled on the way in rather than dropped. An owner
    declared as `research # rates desk` reached Prometheus as `research`, because the generator
    interpolated it into YAML unquoted and the hash opened a comment. Every gate was green, and
    the owner is the field that decides who is told.
    """
    monitors = by_name()
    for name, rule in alerts().items():
        monitor = monitors[name]
        assert rule["labels"] == {
            "severity": monitor.severity,
            "route": monitor.route,
            "owner": monitor.owner,
            "feed": monitor.feed,
        }, f"{name} is labelled with something other than what its monitor declares"
        assert rule["annotations"]["because"] == monitor.because

        match = EXPRESSION.match(str(rule["expr"]))
        assert match, f"{name} has an expression this check cannot read: {rule['expr']!r}"
        metric, operator = INDICATOR[monitor.kind]
        assert match["metric"] == metric
        assert match["op"] == operator
        key, _, value = match["selector"].partition("=")
        assert key == "feed"
        assert json.loads(value) == monitor.feed, f"{name} watches a feed nobody declared"
        expected = (
            monitor.completeness
            if monitor.kind == "completeness"
            else monitor.expected_within_trading_days
        )
        assert float(match["threshold"]) == expected, (
            f"{name} fires at {match['threshold']} and its monitor declares {expected}"
        )


def test_every_alert_is_unit_tested_firing_and_quiet() -> None:
    """THE HEADLINE CLAIM, MADE SELF ENFORCING.

    Deleting every case in generated_test.yml left promtool reporting SUCCESS and the offline
    suite untouched, because nothing outside the file ever opened it. So a quarter of the
    registry had no assertion of any kind and another monitor had never been observed firing,
    under a header saying both directions were exercised for every monitor.
    """
    firing, quiet = asserted()
    generated = set(alerts())
    assert generated - firing == set(), (
        f"these alerts are never asserted firing, so nothing here shows they can: "
        f"{sorted(generated - firing)}"
    )
    assert generated - quiet == set(), (
        f"these alerts are never asserted silent, which is the direction that decides whether "
        f"anybody keeps reading them: {sorted(generated - quiet)}"
    )


def test_the_rule_unit_tests_name_no_alert_that_does_not_exist() -> None:
    """A typed-wrong alertname asserted silent passes for ever and covers nothing.

    promtool does not object: it looks for alerts with that name, finds none, and agrees that
    none fired. The assertion is then permanently true and permanently worthless.
    """
    firing, quiet = asserted()
    unknown = sorted((firing | quiet) - set(alerts()))
    assert unknown == [], f"the unit tests name alerts that no rule produces: {unknown}"


@pytest.mark.parametrize("kind", sorted(INDICATOR))
def test_each_kind_of_monitor_is_actually_present_in_the_registry(kind: str) -> None:
    """Both branches of the generator are exercised by the committed rules.

    Without this a registry could drift to one kind and the other rule builder would go
    untested by every check above while all of them stayed green.
    """
    assert any(monitor.kind == kind for monitor in REGISTRY)


#: The two free-text fields, given values that are ordinary English and hostile YAML. The first
#: is the one that mattered: a hash opens a comment, so an owner carrying one reached Prometheus
#: truncated and nothing anywhere went red. The others are louder, and produced a rules file
#: that did not parse at all. The name and the feed are absent because the registry refuses
#: prose in them: those land in PromQL, where quoting the YAML is not enough.
DANGEROUS_FIELDS: tuple[tuple[str, str], ...] = (
    ("owner", "research # rates desk"),
    (
        "because",
        'the "reference" rate everyone reads, so a gap is one to fill rather than wake for',
    ),
    ("owner", "research: rates"),
    ("because", "late by 09:30, which is when the valuation runs"),
)


@pytest.mark.parametrize(("field", "value"), DANGEROUS_FIELDS)
def test_a_field_that_means_something_to_yaml_survives_the_generator(
    field: str, value: str
) -> None:
    """The generator built YAML by f-string with nothing escaped, so free text was structure.

    Driven through the real generator rather than asserted about the template, because the
    truncation is invisible in the source and only appears once the document is parsed back.
    """
    override: dict[str, Any] = {field: value}
    monitor = dataclasses.replace(REGISTRY[0], **override)
    text, written, _ = generate_rules.document((monitor,))
    assert written == 1
    parsed = yaml.safe_load(text)
    rule = next(r for group in parsed["groups"] for r in group["rules"] if "alert" in r)
    assert rule["alert"] == monitor.name
    assert rule["labels"]["owner"] == monitor.owner
    assert rule["labels"]["feed"] == monitor.feed
    assert rule["annotations"]["because"] == monitor.because

"""Monitors declared as data, so adding one is a pull request rather than a new alert expression.

WHY THIS SHAPE. The usual way a monitoring platform grows is that somebody writes another alert
expression, and six months later nobody can say what is monitored, by whom, or what would have
to be true for an alert to be wrong. A registry answers all three by construction: every monitor
carries its owner, the window it expects data within, the tolerance, the severity and where it
routes, and the alert rules are GENERATED from it.

THE INDICATOR IS FRESHNESS AND COMPLETENESS, NOT AN HTTP STATUS CODE. A feed that returns 200
and yesterday's numbers is the failure this exists to catch, and every status-based check on
earth reports it as healthy. So what is measured is whether the data arrived and whether all of
it arrived, and the window is counted in TRADING DAYS, because a feed that publishes on business
days is not late on a Sunday and an alert that fires every weekend is an alert nobody reads.

WHAT A TOLERANCE IS FOR. A monitor with no tolerance fires on the first late minute of a feed
that is routinely three minutes late, and gets silenced within a week. The tolerance is
declared, per monitor, by the person who owns it, and it is in the registry where a reviewer can
argue with it rather than inside an expression nobody opens.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Literal

Severity = Literal["page", "ticket", "log"]

#: Where each severity goes. Declared once, here, so a monitor cannot invent a route.
ROUTES: dict[Severity, str] = {
    "page": "oncall",
    "ticket": "data-platform",
    "log": "none",
}


@dataclass(frozen=True)
class Monitor:
    """One thing that is watched, and everything a reviewer needs to argue with it."""

    name: str
    owner: str
    #: The feed this monitor is about, as it appears in the metric.
    feed: str
    #: How long after a trading day closes the data is expected, in trading days.
    expected_within_trading_days: int
    #: How much of the expected data must arrive for the feed to count as complete.
    completeness: float
    severity: Severity
    #: Why this monitor exists, in one sentence, from the person who added it.
    because: str

    def __post_init__(self) -> None:
        if not 0 < self.completeness <= 1:
            raise ValueError(f"{self.name}: completeness is a fraction, got {self.completeness}")
        if self.expected_within_trading_days < 1:
            raise ValueError(f"{self.name}: a window shorter than a trading day is not a window")
        if not self.because.strip():
            raise ValueError(
                f"{self.name}: a monitor with no reason is one nobody can decide to remove"
            )
        if self.severity == "page" and self.expected_within_trading_days > 2:
            # A PAGE HAS TO BE URGENT OR IT IS NOT A PAGE. Waking somebody for a feed that is
            # allowed to be three days late is how a rota learns to ignore the pager.
            raise ValueError(
                f"{self.name}: pages on a window of {self.expected_within_trading_days} trading "
                f"days, which is not an emergency. Use a ticket"
            )

    @property
    def route(self) -> str:
        return ROUTES[self.severity]


#: The registry. Adding to this list is the only way to add a monitor.
REGISTRY: tuple[Monitor, ...] = (
    Monitor(
        name="ecb_reference_rate_freshness",
        owner="data-platform",
        feed="ecb_exr_daily",
        expected_within_trading_days=1,
        completeness=1.0,
        severity="page",
        because=(
            "every downstream valuation reads this rate, and a stale one is wrong in a way "
            "nothing downstream can detect"
        ),
    ),
    Monitor(
        name="ecb_reference_rate_completeness",
        owner="data-platform",
        feed="ecb_exr_daily",
        expected_within_trading_days=2,
        completeness=0.98,
        severity="ticket",
        because="a few missing days is a gap to fill, not an emergency to wake somebody for",
    ),
    Monitor(
        name="ecb_yield_curve_freshness",
        owner="research",
        feed="ecb_yield_curve",
        expected_within_trading_days=2,
        completeness=0.95,
        severity="ticket",
        because="research reruns overnight, so a day late is noticed and a day late is not urgent",
    ),
    Monitor(
        name="ecb_bank_rates_completeness",
        owner="research",
        feed="ecb_bank_rates",
        expected_within_trading_days=3,
        completeness=0.9,
        severity="log",
        because=(
            "this feed is genuinely irregular and nobody should be told about it, but a silent "
            "monitor is still better than an undeclared one"
        ),
    ),
)


def trading_days_between(start: datetime.date, end: datetime.date) -> int:
    """Trading days between two dates, weekends excluded.

    NO HOLIDAY CALENDAR, and that is a limitation rather than an oversight: a holiday calendar
    is a per-venue artefact that goes stale, and this repository does not ship one. What it does
    instead is state the consequence, which is that a monitor can fire on the first trading day
    after a public holiday. The alternative is a calendar nobody updates, which fails silently.
    """
    if end < start:
        raise ValueError("end is before start")
    days = 0
    current = start
    while current < end:
        current += datetime.timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return days

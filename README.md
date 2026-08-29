# QUIETZ

**A feed that returns 200 and yesterday's numbers is healthy by every status check ever written.
This watches freshness and completeness instead, declares every monitor as data with an owner
and a tolerance, and generates the alert rules from it.**

[![CI](https://github.com/PNX89/QUIETZ/actions/workflows/ci.yml/badge.svg)](https://github.com/PNX89/QUIETZ/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

<!-- quoted from docs/evidence/demo.txt -->
```text
  monitor                           owner           within   complete  goes to
  ecb_reference_rate_freshness      data-platform   1d       100%      oncall
  ecb_reference_rate_completeness   data-platform   2d       98%       data-platform
  ecb_yield_curve_freshness         research        2d       95%       data-platform
  ecb_bank_rates_completeness       research        3d       90%       none
```

That is the whole registry, and it is the whole monitoring: the Prometheus rules are generated
from it, so adding a monitor is a pull request against data rather than another alert expression
nobody reviews. Six months later somebody can still say what is watched, by whom, and what would
have to be true for an alert to be wrong.

One file to start with: [`src/quietz/monitors.py`](src/quietz/monitors.py).

**Only one of those 4 monitors wakes anybody, and the registry will not let that change by
accident.** A monitor that pages on a window longer than two trading days is rejected in the
constructor, because waking somebody for a feed that is allowed to be three days late is how a
rota learns to ignore the pager. A monitor with no stated reason is rejected too: one nobody can
weigh is one nobody ever removes.

**The windows are in trading days.** A feed that publishes on business days is not late on a
Sunday, and an alert that fires every weekend is one somebody silences on the second weekend. No
holiday calendar ships here, which is a limitation rather than an oversight: a per-venue calendar
goes stale and then fails silently. The consequence is that a monitor can fire on the first
trading day after a public holiday, and it is written beside the code rather than in a document
nobody opens.

## The rules are tested in both directions

`promtool check rules` says a file parses as PromQL. It says nothing about whether an alert fires
when it should, and nothing at all about whether it stays quiet when it should, which is the half
that decides whether anybody keeps reading the alerts. So the generated rules are unit tested:

- a feed a day late pages, with the labels and the annotation its owner wrote
- the same lateness on a feed whose owner allows two days does **not** fire
- a three minute dip does not fire, which is the `for` clause tested rather than assumed
- a healthy feed produces nothing at all

That last one matters most. A rule set nobody has watched staying quiet is one nobody can trust
to stay quiet.

The committed rules are regenerated in CI and compared, so the registry and the alerts cannot
drift apart. Both files look fine on their own, which is exactly why that check exists.

## One incident, and what a human is actually told

<!-- quoted from docs/evidence/demo.txt -->
```text
  24 alert firings
  2 notifications a human receives
```

Two feeds break and keep breaking. Three different mechanisms produce that gap and they are not
interchangeable:

| | what it does |
|---|---|
| deduplication | the same alert firing again is not a second notification |
| grouping | everything about one feed arrives as one notification, grouped by feed rather than by alert name |
| inhibition | the completeness alert for a feed that has not delivered **at all** is suppressed |

The third is the one deduplication could never have caught: it is a different alert with a
different name, and it is the same problem restated. Grouping by alert name instead of by feed
would have put a freshness alert and a completeness alert about one broken feed into two
notifications, which is two pages for one incident.

All of it is measured against a real Alertmanager with the notifications counted at a receiver,
rather than reasoned about from the configuration, because the three interact and the
interaction is where the surprises are.

## This one fails open, and every sibling is right to fail closed

The other repositories in this toolset refuse when a check cannot run. That is correct when what
is being refused is a promotion, a payment or an admission: wrongly proceeding is unbounded and
wrongly stopping is a delay.

A notification path is the other way round. Failing closed means **suppressing**, and a
monitoring system that goes quiet when it is confused is most silent exactly when something is
most wrong. So every rule here is written so that uncertainty produces a notification rather than
removes one: the inhibition rules match on labels that must be present rather than absent, there
is no catch-all silence, and the repeat interval is long enough not to nag and short enough that
one lost notification is not the end of it.

## Run it

```text
uv run python examples/what_gets_you_woken.py
uv run pytest
```

The legs that need Prometheus or Alertmanager have their own CI jobs:

```text
uv run python scripts/generate_rules.py
scripts/incident_stack.sh
```

## What this does not do

It does not monitor anything real. The feeds in the registry are named after public statistical
series and nothing here is connected to them: the subject is the shape of a monitoring platform,
not an operating one.

It has no holiday calendar, so a monitor can fire on the first trading day after a public
holiday.

It is not an on-call rotation, an escalation policy or a paging provider. The routes name where
an alert would go and nothing here delivers to any of them.

## Development

```text
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy .
```

<!-- toolset:start -->
<!-- toolset:end -->

## Licence

MIT.

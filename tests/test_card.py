"""The facts the portfolio card states, checked against the repository rather than the file.

`docs/evidence/facts.json` is the one captured artefact CI does not compare byte for byte,
because it carries a capture date and a byte comparison of a date fails on the second morning.
That exemption is only defensible if its contents are checked another way.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Any

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
FACTS = REPO / "docs" / "evidence" / "facts.json"

sys.path.insert(0, str(REPO / "scripts"))
import check_card  # noqa: E402


def a_copy(tmp_path: pathlib.Path) -> pathlib.Path:
    """The card and the evidence it is checked against, somewhere they can be falsified."""
    root = tmp_path / "repo"
    (root / "site").mkdir(parents=True)
    (root / "docs" / "evidence" / "incident").mkdir(parents=True)
    shutil.copy(REPO / "site" / "index.html", root / "site" / "index.html")
    for name in ("demo.txt", "facts.json"):
        shutil.copy(REPO / "docs" / "evidence" / name, root / "docs" / "evidence" / name)
    shutil.copy(
        REPO / "docs" / "evidence" / "incident" / "summary.json",
        root / "docs" / "evidence" / "incident" / "summary.json",
    )
    return root


def after_changing(root: pathlib.Path, path: str, old: str, new: str) -> list[str]:
    """Falsify one thing and ask the check what it thinks.

    The assertion is not decoration. A replacement that matches nothing leaves a tree that is
    still correct, and a check reporting no problems with it reads exactly like a check that
    missed the falsification.
    """
    target = root / path
    text = target.read_text(encoding="utf-8")
    assert old in text, f"{old!r} is not in {path}, so this falsification changed nothing"
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    problems: list[str] = check_card.problems(root)
    return problems


def facts() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(FACTS.read_text(encoding="utf-8"))
    return loaded


def test_the_stated_test_total_is_the_one_this_suite_collects() -> None:
    """The number on the card, against the number a reader gets by running the suite.

    Collected here rather than read from the capture, so the two have to agree. There is one
    test directory: the docstring that used to be here described a split rig belonging to a
    sibling repository, and the loop under it had one element.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    )
    total = sum(
        int(count) for _, count in re.findall(r"^(\S+): (\d+)$", result.stdout, re.MULTILINE)
    )
    assert total > 0
    assert facts()["tests"] == total, (
        f"the card states {facts()['tests']} tests and the suite collects {total}. Re-run "
        f"scripts/capture_evidence.py"
    )


def test_the_stated_python_range_is_the_one_ci_runs() -> None:
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    versions = re.findall(r'"(\d+\.\d+)"', workflow)
    assert versions
    assert facts()["python"] == f"{min(versions, key=float)} to {max(versions, key=float)}"


def test_the_stated_release_matches_the_package_version() -> None:
    version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assert facts()["release"].startswith(f"v{version}")


def test_the_capture_date_is_not_in_the_future() -> None:
    """Bounded rather than matched, because checking it against today fails tomorrow."""
    import datetime

    assert datetime.date.fromisoformat(facts()["captured"]) <= datetime.date.today()


def test_a_published_card_matches_its_evidence_and_carries_no_banned_dash() -> None:
    """THE CARD IS WHAT A REVIEWER OPENS, and nothing used to compare it to anything.

    The only check was that the first non-blank line of the captured demo appeared somewhere in
    the HTML, and the publish gate did exactly the same one-line grep. Falsifying the test
    total, the Python range, the release, the capture date and every number inside the terminal
    block left both of them green, under a note on the card saying a test fails when it stops
    matching a live run.
    """
    card = REPO / "site" / "index.html"
    if not card.exists():
        return
    assert check_card.problems(REPO) == []
    # ESCAPES RATHER THAN THE CHARACTERS, and the first draft of this line used the characters
    # in the comment directly under a comment saying not to. The linter caught it.
    html = card.read_text(encoding="utf-8")
    for dash in ("\u2014", "\u2013"):
        assert dash not in html, f"the published card contains {dash!r}"


def test_the_card_check_notices_a_falsified_fact(tmp_path: pathlib.Path) -> None:
    """See after_changing. A guard nobody has watched fail is a guard nobody has tested, and the
    thing this one guards against cannot be produced by asking for it."""
    root = a_copy(tmp_path)
    stated = json.loads((root / "docs" / "evidence" / "facts.json").read_text("utf-8"))["tests"]
    problems = after_changing(root, "site/index.html", f"<dd>{stated}</dd>", "<dd>999</dd>")
    assert any("Tests" in problem for problem in problems), problems


def test_the_card_check_notices_a_transcript_that_is_not_the_capture(
    tmp_path: pathlib.Path,
) -> None:
    """A card built from an older capture publishes numbers this repository no longer produces,
    and every line of it below the first one used to be unchecked."""
    root = a_copy(tmp_path)
    demo = (root / "docs" / "evidence" / "demo.txt").read_text("utf-8")
    line = [text for text in demo.splitlines() if text.strip()][2]
    problems = after_changing(root, "site/index.html", line, line.replace(" ", "  ", 1))
    assert any("transcript" in problem for problem in problems), problems


def test_the_card_check_notices_a_stale_capture_date(tmp_path: pathlib.Path) -> None:
    """The date is the one fact CI cannot compare byte for byte, which is why it needs this."""
    root = a_copy(tmp_path)
    facts_file = root / "docs" / "evidence" / "facts.json"
    captured = json.loads(facts_file.read_text("utf-8"))["captured"]
    problems = after_changing(root, "docs/evidence/facts.json", f'"{captured}"', '"2019-01-01"')
    assert any("captured on" in problem for problem in problems), problems


def test_the_card_check_notices_a_headline_that_drifted_from_the_replay(
    tmp_path: pathlib.Path,
) -> None:
    """The paragraph at the top of the card is written outside this repository, so it is the one
    part that cannot notice a measurement changing. That is exactly why it is compared."""
    root = a_copy(tmp_path)
    problems = after_changing(
        root,
        "docs/evidence/incident/summary.json",
        '"alert_firings_posted": 24',
        '"alert_firings_posted": 18',
    )
    assert any("measured" in problem for problem in problems), problems


def test_the_python_range_is_the_gating_matrix_and_orders_as_versions(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two latent defects in the function that publishes this number, neither of them visible.

    The range on the card is correct today. It was produced by a function that matched every
    quoted `x.y` anywhere in the workflow, so a quoted action version or a timeout would have
    landed on a published page, and that ordered with `float`, so `float("3.9") > float("3.13")`
    and a 3.9 leg would have published a range running backwards.

    A correct output from a broken mechanism is the thing this whole portfolio argues against, so
    the mechanism is tested rather than the output.
    """
    import json as _json
    import sys

    import yaml

    sys.path.insert(0, str(REPO / "scripts"))
    import capture_evidence

    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    gating: set[str] = set()
    for job in (workflow.get("jobs") or {}).values():
        if job.get("continue-on-error"):
            continue
        declared = (job.get("with") or {}).get("python-versions")
        if declared is None:
            continue
        gating.update(
            str(v) for v in (_json.loads(declared) if isinstance(declared, str) else declared)
        )

    assert gating, "no job gates on a Python version, so the published range verifies nothing"
    order = sorted(gating, key=lambda v: tuple(int(p) for p in v.split(".")))
    expected = f"{order[0]} to {order[-1]}"

    assert capture_evidence.python_range() == expected
    facts = _json.loads((REPO / "docs" / "evidence" / "facts.json").read_text("utf-8"))
    assert facts["python"] == expected, (
        f"the card says {facts['python']} and CI gates on {expected}"
    )

    # THE ORDERING RULE, DRIVEN THROUGH THE REAL FUNCTION rather than restated beside it.
    #
    # This matters because of how the defect hides. No matrix in this repository contains a 3.9,
    # so float ordering and version ordering agree on every version actually present, and
    # swapping the production line back to `key=float` changes no output and fails nothing. A
    # test that only asserted the rule as arithmetic would pin a fact and let the code revert.
    #
    # So the function is pointed at a workflow that DOES contain a 3.9, by moving its ROOT, and
    # asked what it returns. Under `key=float` that is "3.11 to 3.9", a range running backwards
    # on a published page.
    fake = tmp_path / ".github" / "workflows"
    fake.mkdir(parents=True)
    (fake / "ci.yml").write_text(
        'jobs:\n  checks:\n    with:\n      python-versions: \'["3.11", "3.9", "3.13"]\'\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(capture_evidence, "ROOT", tmp_path)
    assert capture_evidence.python_range() == "3.9 to 3.13", (
        "the version range is not ordered as versions. float('3.9') is greater than "
        "float('3.13'), so this publishes a range running backwards the day a 3.9 leg exists"
    )

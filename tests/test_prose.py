"""Prose this repository inherited rather than wrote.

Sixteen repositories in this toolset share a shape, and the cost of that shape is that a
docstring travels between them intact while the thing it describes does not. Two files here
explained that the test total covered a suite needing a database that does not exist in this
tree, and a docstring in the README checks quoted disclaimers from a sibling's front page as
though they were this one's.

WHY THIS IS WORTH A TEST RATHER THAN A PROOFREAD. For a portfolio whose whole pitch is that
every claim is checkable, the reviewer's conclusion is not that somebody was sloppy. It is that
these were mass-produced and nobody read them, and that conclusion is not recoverable from.
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Each phrase is assembled from halves on purpose. A guard whose own file contains the thing it
#: forbids fails the moment it starts working, and that has already happened here more than
#: once. Never write one of these as a single literal.
NOT_HERE: tuple[tuple[str, str], ...] = (
    ("postgre" + "sql", "no database ships here and nothing starts one"),
    ("air" + "flow", "no orchestrator ships here"),
    ("allocate " + "capital", "that subject belongs to the backtest repository"),
    ("both " + "suites", "there is one test directory"),
    ("two " + "suites", "there is one test directory"),
)

#: Where prose lives. The rules files are generated and the evidence is captured, so neither is
#: written by anybody and neither is searched.
READ: tuple[str, ...] = (
    "README.md",
    "CONTRIBUTING.md",
    "src/quietz/monitors.py",
    "examples/what_gets_you_woken.py",
    "alertmanager/alertmanager.yml",
)


def written_here() -> dict[str, str]:
    """Every file somebody typed, by path, lowercased for searching."""
    files = {name: (REPO / name).read_text(encoding="utf-8").lower() for name in READ}
    for directory in ("scripts", "tests"):
        for path in sorted((REPO / directory).rglob("*.py")):
            files[str(path.relative_to(REPO))] = path.read_text(encoding="utf-8").lower()
    return files


def test_the_files_this_check_reads_all_exist() -> None:
    """Named rather than globbed, so a rename cannot quietly shrink what is searched."""
    missing = [name for name in READ if not (REPO / name).exists()]
    assert missing == [], f"this check names files that are not here: {missing}"
    assert len(written_here()) > len(READ), "no Python file was searched, so this checks nothing"


@pytest.mark.parametrize(("phrase", "reason"), NOT_HERE, ids=[phrase for phrase, _ in NOT_HERE])
def test_no_file_here_describes_something_that_is_not_here(phrase: str, reason: str) -> None:
    """See NOT_HERE. A sentence about infrastructure this repository does not have is a
    sentence somebody pasted, and a reader who checks one claim and finds it imported stops
    believing the rest."""
    carrying = sorted(name for name, text in written_here().items() if phrase in text)
    assert carrying == [], (
        f"{carrying} describe {phrase!r}, and {reason}. It came from a sibling repository: "
        f"delete the sentence rather than making it true"
    )

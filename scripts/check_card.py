"""What the published card claims, against the evidence it was built from.

    python3 scripts/check_card.py

WHY THIS IS A SCRIPT AND NOT ONLY A TEST. The card is what a reviewer opens, and the publish
workflow is the last thing standing between a card that has drifted and a live page. That
workflow used to check one line: that the FIRST line of the captured demo appeared somewhere in
the HTML. Every fact beside it could be false and both gates stayed green. Falsifying the test
total, the Python range, the release, the capture date and every number inside the terminal
block left the suite at forty two passed and the publish gate reporting PASS.

Stdlib only, and no `uv`, because the publish job installs nothing.

THE FIGURES ARE COMPARED WHERE THEY ARE STATED, never searched for. A page this long contains
any small integer somewhere, so a check that looks for one in the whole document passes on a
page that has stopped saying it.
"""

from __future__ import annotations

import html
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The strip at the top of the card, and the key in facts.json each cell has to equal. Named
#: rather than discovered, so a cell that disappears is a failure rather than one check fewer.
FACT_CELLS: dict[str, str] = {"Tests": "tests", "Python": "python", "Release": "release"}

FACTS_BLOCK = re.compile(r'<dl class="facts">(.*?)</dl>', re.S)
FACT_CELL = re.compile(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", re.S)
CLAIM = re.compile(r'<p class="claim">(.*?)</p>', re.S)
TRANSCRIPT = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S)
NOTE = re.compile(r'<p class="note">(.*?)</p>', re.S)
CAPTURED_ON = re.compile(r"captured on (\d{4}-\d{2}-\d{2})")


def problems(root: pathlib.Path) -> list[str]:
    """Everything about the card that its own evidence contradicts."""
    card = (root / "site" / "index.html").read_text(encoding="utf-8")
    facts = json.loads((root / "docs" / "evidence" / "facts.json").read_text(encoding="utf-8"))
    demo = (root / "docs" / "evidence" / "demo.txt").read_text(encoding="utf-8")
    incident = json.loads(
        (root / "docs" / "evidence" / "incident" / "summary.json").read_text(encoding="utf-8")
    )
    found: list[str] = []

    block = FACTS_BLOCK.search(card)
    if not block:
        return ["the card has no facts strip at all, so it states nothing checkable"]
    shown = {label.strip(): value.strip() for label, value in FACT_CELL.findall(block.group(1))}
    if set(shown) != set(FACT_CELLS):
        found.append(f"the facts strip shows {sorted(shown)} and should show {sorted(FACT_CELLS)}")
    for label, key in FACT_CELLS.items():
        if label in shown and shown[label] != str(facts[key]):
            found.append(
                f"the card says {label} is {shown[label]} and the capture says {facts[key]}"
            )

    blocks = TRANSCRIPT.findall(card)
    if len(blocks) != 1:
        found.append(f"the card carries {len(blocks)} transcript blocks and should carry one")
    elif html.unescape(blocks[0]).strip() != demo.strip():
        found.append(
            "the transcript on the card is not the captured demo. It was built from an older "
            "capture, or edited by hand, and only its first line was ever compared"
        )

    note = NOTE.search(card)
    stamped = CAPTURED_ON.search(note.group(1)) if note else None
    if not stamped:
        found.append("the card does not say when its output was captured")
    elif stamped.group(1) != facts["captured"]:
        found.append(
            f"the card was captured on {stamped.group(1)} by its own note and {facts['captured']} "
            f"by the capture beside it"
        )

    # THE HEADLINE, WHERE IT IS STATED. This paragraph is written away from the repository, so
    # it is the one part of the card that cannot notice a measurement changing. Checked only if
    # it makes the claim: dropping a claim is not drift, restating it wrongly is.
    claim = CLAIM.search(card)
    if claim:
        for sentence in re.split(r"(?<=\.)\s+", " ".join(html.unescape(claim.group(1)).split())):
            if "alert firing" not in sentence:
                continue
            stated = {int(number) for number in re.findall(r"\b\d+\b", sentence)}
            measured = {incident["alert_firings_posted"], incident["notifications_delivered"]}
            if stated != measured:
                found.append(
                    f"the card claims {sorted(stated)} where the replay measured "
                    f"{sorted(measured)}: {sentence}"
                )
    return found


def main() -> int:
    found = problems(ROOT)
    for line in found:
        print(line, file=sys.stderr)
    if found:
        print("the card does not match the evidence it was built from", file=sys.stderr)
        return 1
    print("the card matches the evidence it was built from")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

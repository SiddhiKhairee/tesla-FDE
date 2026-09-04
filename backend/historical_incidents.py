"""
A small store of past floor-reported incidents, standing in for whatever
system Tesla's team would actually log "someone noticed a problem" reports
to today — per Astin, there isn't one; it's just a Slack/Teams message that
scrolls away. Lets the human-report path show "this same machine had N
similar issues before, here's what fixed it" instead of diagnosing every
report from a blank slate. Synthetic data, same honesty framing as
data-gen/ — not real Tesla incident history.
"""
import json
from difflib import SequenceMatcher
from pathlib import Path

INCIDENTS_PATH = Path(__file__).parent / "data" / "historical_incidents.json"


def load_incidents(path: Path = INCIDENTS_PATH) -> list[dict]:
    return json.loads(path.read_text())


def _text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def find_similar_incidents(
    machine: str,
    issue: str,
    incidents: list[dict],
    top_n: int = 3,
    min_score: float = 0.3,
) -> list[dict]:
    """Rank past incidents by a blended same-machine + issue-text-similarity
    score. Same-machine match is weighted heavily — a recurring problem on
    one specific piece of equipment is the strongest signal a floor report
    gives us, stronger than two different machines happening to use similar
    words to describe unrelated problems.
    """
    scored = []
    for incident in incidents:
        same_machine = incident["machine"].strip().lower() == machine.strip().lower()
        text_score = _text_similarity(issue, incident["issue"])
        score = (0.6 if same_machine else 0.0) + 0.4 * text_score
        if score >= min_score:
            scored.append({**incident, "match_score": round(score, 3), "same_machine": same_machine})

    scored.sort(key=lambda i: i["match_score"], reverse=True)
    return scored[:top_n]

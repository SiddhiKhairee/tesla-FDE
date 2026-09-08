"""
Minimal ticket persistence: a JSON-file-backed store that both the ERP
pipeline path and Version B's human-report path write diagnosed events
into, so the dashboard has something to list rather than re-triggering a
live Odoo fetch + fresh LLM diagnosis on every page load. Not a database —
matches the JSON-file pattern historical_incidents.py already uses for
synthetic data, sized for a portfolio demo, not production ticket volume.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock

TICKETS_PATH = Path(__file__).parent / "data" / "tickets.json"
# backend/data/tickets.json is gitignored runtime state (see .gitignore),
# excluded from the Docker image on purpose. A deployed container therefore
# starts with no tickets.json at all, so we fall back to this committed
# snapshot of already-verified demo tickets instead of an empty dashboard.
SEED_PATH = Path(__file__).parent / "data" / "tickets.seed.json"
_LOCK = Lock()


def _read_all(path: Path) -> list[dict]:
    if not path.exists():
        if path == TICKETS_PATH and SEED_PATH.exists():
            return json.loads(SEED_PATH.read_text())
        return []
    return json.loads(path.read_text())


def _write_all(tickets: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tickets, indent=2))


def save_ticket(diagnosis: dict, path: Path = TICKETS_PATH) -> dict:
    """Persist one diagnosed event (the {event, context, report} shape
    diagnose_event returns) as a ticket with an id, status, and created_at.
    Every new ticket starts "open" — nothing in this codebase resolves or
    flags a ticket yet, so that's the only status value produced today.
    """
    ticket = {
        "id": str(uuid.uuid4()),
        "status": "open",
        "created_at": datetime.now().isoformat(),
        **diagnosis,
    }
    with _LOCK:
        tickets = _read_all(path)
        tickets.append(ticket)
        _write_all(tickets, path)
    return ticket


def list_tickets(path: Path = TICKETS_PATH) -> list[dict]:
    """Most recently created first — the dashboard's natural default order."""
    with _LOCK:
        tickets = _read_all(path)
    return sorted(tickets, key=lambda t: t["created_at"], reverse=True)

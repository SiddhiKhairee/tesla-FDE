"""
Targeted, additive anomaly injection: pick a handful of already-created,
not-yet-anomalous PO receipts and apply delayed_delivery to them, appending
the resulting events to the existing ground_truth.json rather than
regenerating or overwriting anything else.

Use this when a full run came up short on one anomaly type by chance and a
full regeneration isn't worth it. Only writes date_done on the selected
picking records; touches nothing else.

    python inject_delayed_batch.py [--count 4]
"""
import argparse
import json
from datetime import datetime

import config
from anomalies import inject_delayed_delivery
from odoo_client import OdooClient


def load_ground_truth():
    with open(config.GROUND_TRUTH_PATH) as f:
        return json.load(f)


def referenced_pos(ground_truth):
    """POs already involved in some anomaly (as the flagged record or as a
    duplicate pair) — skip these so we don't stack a second anomaly type on
    top of one already verified."""
    refs = set()
    for e in ground_truth["events"]:
        refs.add(e["entity_id"])
        if e.get("duplicate_of"):
            refs.add(e["duplicate_of"])
    return refs


def find_candidates(client: OdooClient, exclude_refs: set, count: int):
    pickings = client.search_read(
        "stock.picking",
        [["picking_type_id.code", "=", "incoming"], ["state", "=", "done"]],
        ["id", "origin", "scheduled_date"],
    )
    # Prefer earlier-dated receipts so the +5..15 day delay lands safely
    # within the historical window rather than pushing near "today".
    pickings.sort(key=lambda p: p["scheduled_date"])

    candidates = []
    for p in pickings:
        if p["origin"] in exclude_refs:
            continue
        candidates.append(p)
        exclude_refs.add(p["origin"])  # don't pick the same PO twice in this batch
        if len(candidates) >= count:
            break
    return candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=4)
    args = parser.parse_args()

    ground_truth = load_ground_truth()
    exclude = referenced_pos(ground_truth)
    print(f"{len(ground_truth['events'])} existing ground-truth events, {len(exclude)} POs already referenced.")

    client = OdooClient()
    candidates = find_candidates(client, exclude, args.count)
    print(f"Selected {len(candidates)} candidate(s):")
    for c in candidates:
        print(f"  {c['origin']} (picking id={c['id']}, scheduled_date={c['scheduled_date']})")

    new_events = []
    for c in candidates:
        scheduled_date = datetime.strptime(c["scheduled_date"], "%Y-%m-%d %H:%M:%S")
        event = inject_delayed_delivery(client, c["id"], c["origin"], scheduled_date, scheduled_date)
        new_events.append(event)
        print(f"  Applied delayed_delivery to {c['origin']}: "
              f"expected={event.expected_value} actual={event.actual_value}")

    ground_truth["events"].extend(e.to_dict() for e in new_events)
    with open(config.GROUND_TRUTH_PATH, "w") as f:
        json.dump(ground_truth, f, indent=2)

    print(f"\nDone. Ground truth now has {len(ground_truth['events'])} events "
          f"({len(new_events)} new delayed_delivery appended).")


if __name__ == "__main__":
    main()

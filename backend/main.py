from datetime import datetime

from fastapi import FastAPI

from detection import (
    detect_delayed_deliveries,
    detect_duplicate_orders,
    detect_quantity_mismatches,
    detect_stuck_orders,
)
from diagnosis import diagnose_all, diagnose_event
from historical_incidents import find_similar_incidents, load_incidents
from human_report import report_to_event
from notifications import notify_ticket
from odoo_client import OdooClient
from odoo_fetch import (
    fetch_incoming_receipts,
    fetch_internal_locations,
    fetch_manufacturing_orders,
    fetch_outgoing_deliveries,
    fetch_products,
    fetch_purchase_order_lines,
    fetch_purchase_orders,
    fetch_sales_order_lines,
    fetch_sales_orders,
    fetch_stock_moves,
    fetch_stock_quants,
)
from order_lookup import build_order_index
from schemas import FailureReportIn

app = FastAPI(title="Tesla FDE ERP Reconciliation Agent")

odoo = OdooClient()
_HISTORICAL_INCIDENTS = load_incidents()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/purchase-orders")
def debug_purchase_orders(limit: int = 20):
    return fetch_purchase_orders(odoo, limit=limit)


@app.get("/debug/receipts")
def debug_receipts(limit: int = 20):
    return fetch_incoming_receipts(odoo, limit=limit)


@app.get("/debug/manufacturing-orders")
def debug_manufacturing_orders(limit: int = 20):
    return fetch_manufacturing_orders(odoo, limit=limit)


@app.get("/debug/sales-orders")
def debug_sales_orders(limit: int = 20):
    return fetch_sales_orders(odoo, limit=limit)


@app.get("/debug/deliveries")
def debug_deliveries(limit: int = 20):
    return fetch_outgoing_deliveries(odoo, limit=limit)


@app.get("/debug/quants")
def debug_quants(limit: int = 20):
    return fetch_stock_quants(odoo, limit=limit)


def _fetch_snapshot() -> dict:
    """One fetch of everything detection and diagnosis need, so endpoints
    that need both don't hit Odoo twice for the same data.
    """
    return {
        "pickings": fetch_incoming_receipts(odoo) + fetch_outgoing_deliveries(odoo),
        "purchase_orders": fetch_purchase_orders(odoo),
        "purchase_order_lines": fetch_purchase_order_lines(odoo),
        "sales_orders": fetch_sales_orders(odoo),
        "sales_order_lines": fetch_sales_order_lines(odoo),
        "quants": fetch_stock_quants(odoo),
        "moves": fetch_stock_moves(odoo),
        "internal_locations": fetch_internal_locations(odoo),
        "products": fetch_products(odoo),
    }


def _detect_all_events(snapshot: dict | None = None, reference_date: datetime | None = None):
    """`reference_date` is what detect_stuck_orders measures "overdue"
    against — defaults to real wall-clock time for live use (debug
    endpoints, the running pipeline), but eval.py passes ground_truth.json's
    "generated_through" so eval numbers stay reproducible regardless of when
    the eval is actually run.
    """
    snapshot = snapshot or _fetch_snapshot()

    return [
        *detect_stuck_orders(snapshot["pickings"], reference_date=reference_date),
        *detect_delayed_deliveries(snapshot["pickings"]),
        *detect_duplicate_orders(
            snapshot["purchase_orders"], snapshot["purchase_order_lines"], qty_field="product_qty"
        ),
        *detect_quantity_mismatches(
            snapshot["quants"], snapshot["moves"], snapshot["internal_locations"], snapshot["products"]
        ),
    ]


def _build_order_index(snapshot: dict) -> dict:
    return build_order_index(
        snapshot["purchase_orders"],
        snapshot["purchase_order_lines"],
        snapshot["sales_orders"],
        snapshot["sales_order_lines"],
        snapshot["products"],
    )


@app.get("/debug/detected-anomalies")
def debug_detected_anomalies():
    return [event.model_dump() for event in _detect_all_events()]


@app.get("/debug/diagnose-sample")
def debug_diagnose_sample(index: int = 0):
    """Spot-check the LangGraph diagnosis agent against one real detected
    anomaly from the current dataset (not wired into the main pipeline yet).
    """
    snapshot = _fetch_snapshot()
    events = _detect_all_events(snapshot)
    if not events:
        return {"detail": "no anomalies detected in current dataset"}
    if index < 0 or index >= len(events):
        return {"detail": f"index out of range — {len(events)} anomalies detected"}
    return diagnose_event(events[index], events, order_index=_build_order_index(snapshot))


@app.get("/pipeline/run")
def run_pipeline():
    """The full Day 3 pipeline, wired end to end: Odoo fetch -> rule-based
    detection -> shared event schema -> LangGraph diagnosis agent. Runs on
    the free stub LLM (see llm_client.get_diagnosis_llm) until a real
    provider is configured — swapping providers only touches llm_client.py.
    """
    snapshot = _fetch_snapshot()
    events = _detect_all_events(snapshot)
    return diagnose_all(events, order_index=_build_order_index(snapshot))


@app.post("/reports/intake")
def submit_failure_report(report: FailureReportIn):
    """Version B: a human on the floor reports a problem directly. Adapts
    the report into the shared DiscrepancyEvent schema, matches it against
    historical_incidents.py's past-incident store, runs it through the same
    diagnosis engine Day 3 built for ERP anomalies, and auto-notifies the
    team — replacing the "someone has to type it into Slack" step Astin
    confirmed is today's actual process.
    """
    event = report_to_event(report)
    matches = find_similar_incidents(report.machine, report.issue, _HISTORICAL_INCIDENTS)
    diagnosis = diagnose_event(event, historical_matches=matches)
    notified = notify_ticket(diagnosis)
    return {**diagnosis, "notified": notified}

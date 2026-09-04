"""
LangGraph diagnosis agent — sits on top of detection.py's rule-based flags.
A DiscrepancyEvent only says *that* something is wrong; this agent reasons
about *why* it probably happened and what a human should do about it.

Two-node graph, run once per event:
  gather_context -> pure-Python fact gathering (no LLM). Computes things
      like how overdue an order is, or whether other events in the same
      batch share the anomaly type/product/location — the "systemic vs.
      isolated" signal — and, via order_lookup.build_order_index, pulls in
      record-level detail (vendor/customer, order value, products/
      quantities) so events aren't diagnosed as anonymous order numbers.
      Keeping this out of the prompt-writing step means the LLM reasons
      over numbers we've already verified, not ones it has to infer from
      raw timestamps itself.
  diagnose -> one Claude call, given the event + computed context, returns
      a structured DiagnosisReport (client.messages.parse, no free-text
      parsing needed downstream).
"""
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from llm_client import DiagnosisReport, get_diagnosis_llm
from schemas import DiscrepancyEvent


class DiagnosisState(TypedDict):
    event: DiscrepancyEvent
    all_events: list[DiscrepancyEvent]
    reference_date: datetime
    order_index: dict[str, dict]
    historical_matches: list[dict]
    context: dict[str, Any]
    report: DiagnosisReport | None


def _quantity_drift_direction(event: DiscrepancyEvent) -> str:
    return "excess_on_hand" if float(event.actual_value) - float(event.expected_value) > 0 else "shortage"


def _gather_context(
    event: DiscrepancyEvent,
    all_events: list[DiscrepancyEvent],
    reference_date: datetime,
    order_index: dict[str, dict] | None = None,
    historical_matches: list[dict] | None = None,
) -> dict[str, Any]:
    order_index = order_index or {}
    siblings = [e for e in all_events if e is not event]
    same_type_siblings = [e for e in siblings if e.anomaly_type == event.anomaly_type]

    context: dict[str, Any] = {
        "total_events_in_batch": len(all_events),
        "other_events_same_anomaly_type": len(same_type_siblings),
    }
    if event.product:
        context["other_events_same_product"] = sum(
            1 for e in siblings if e.product == event.product
        )
    if event.location:
        context["other_events_same_location"] = sum(
            1 for e in siblings if e.location == event.location
        )

    # Record-level detail for order-based anomalies (stuck_order,
    # delayed_delivery, duplicate_entry all use the order name as entity_id
    # — quantity_mismatch uses "sku@location" and simply won't match).
    order_info = order_index.get(event.entity_id)
    if order_info:
        context["vendor_or_customer"] = order_info["partner"]
        context["order_value"] = order_info["order_value"]
        context["order_products"] = order_info["products"]
        context["reference"] = order_info["reference"]

        # Clustering by vendor/product among siblings of the same anomaly
        # type — distinguishes "no real pattern" from "this vendor is the
        # actual bottleneck" instead of just counting same-type events.
        my_vendor = order_info["partner"]
        if my_vendor:
            same_vendor_siblings = [
                s for s in same_type_siblings
                if order_index.get(s.entity_id, {}).get("partner") == my_vendor
            ]
            context["other_events_same_vendor"] = len(same_vendor_siblings)
            context["vendor_name"] = my_vendor

        my_skus = {item["product"] for item in order_info["products"]}
        if my_skus:
            same_product_siblings = [
                s for s in same_type_siblings
                if my_skus & {item["product"] for item in order_index.get(s.entity_id, {}).get("products", [])}
            ]
            context["other_events_same_product_on_order"] = len(same_product_siblings)

    if event.anomaly_type == "stuck_order":
        scheduled = datetime.fromisoformat(event.timestamp)
        context["days_overdue"] = (reference_date - scheduled).days
    elif event.anomaly_type == "delayed_delivery":
        scheduled = datetime.fromisoformat(event.expected_value)
        done = datetime.fromisoformat(event.actual_value)
        context["delay_days"] = (done - scheduled).days
    elif event.anomaly_type == "quantity_mismatch":
        expected = float(event.expected_value)
        actual = float(event.actual_value)
        drift = actual - expected
        direction = "excess_on_hand" if drift > 0 else "shortage"
        context["drift_amount"] = drift
        context["drift_direction"] = direction
        context["drift_pct_of_expected"] = (
            abs(drift) / expected * 100 if expected else None
        )

        # No vendor concept is cheaply available for a stock quant (would
        # need a product -> preferred-supplier lookup we don't fetch), but
        # drift direction is: cluster same-type siblings by whether they're
        # also excess/also shortage, both overall and at the same location.
        # "3 other shortages at this location" implies something systemic
        # (shrinkage/theft/miscount pattern); a mix of excess and shortage
        # nearby looks more like independent counting noise.
        same_direction_siblings = [
            s for s in same_type_siblings if _quantity_drift_direction(s) == direction
        ]
        context["other_events_same_drift_direction"] = len(same_direction_siblings)
        if event.location:
            same_location_and_direction = [
                s for s in same_direction_siblings if s.location == event.location
            ]
            context["other_events_same_location_and_direction"] = len(same_location_and_direction)
    elif event.anomaly_type == "duplicate_entry":
        context["duplicate_of"] = event.duplicate_of

    if historical_matches:
        # Version B (human_report) signal: past incidents on this machine
        # (or with similar reported symptoms), ranked by historical_incidents
        # .find_similar_incidents — an ERP-side siblings count doesn't exist
        # for a one-off floor report, so this is the primary "have we seen
        # this before" evidence for equipment_failure events.
        context["similar_past_incidents"] = [
            {
                "machine": m["machine"],
                "issue": m["issue"],
                "resolution": m["resolution"],
                "match_score": m["match_score"],
                "same_machine": m["same_machine"],
            }
            for m in historical_matches
        ]

    return context


def _gather_context_node(state: DiagnosisState) -> dict[str, Any]:
    context = _gather_context(
        state["event"],
        state["all_events"],
        state["reference_date"],
        state["order_index"],
        state["historical_matches"],
    )
    return {"context": context}


def _diagnose_node(state: DiagnosisState) -> dict[str, Any]:
    llm = get_diagnosis_llm()
    report = llm.generate(state["event"].model_dump(), state["context"])
    return {"report": report}


def _build_graph():
    graph = StateGraph(DiagnosisState)
    graph.add_node("gather_context", _gather_context_node)
    graph.add_node("diagnose", _diagnose_node)
    graph.add_edge(START, "gather_context")
    graph.add_edge("gather_context", "diagnose")
    graph.add_edge("diagnose", END)
    return graph.compile()


_DIAGNOSIS_GRAPH = _build_graph()


def diagnose_event(
    event: DiscrepancyEvent,
    all_events: list[DiscrepancyEvent] | None = None,
    reference_date: datetime | None = None,
    order_index: dict[str, dict] | None = None,
    historical_matches: list[dict] | None = None,
) -> dict[str, Any]:
    """Run one DiscrepancyEvent through the diagnosis graph. `all_events`
    should be the full batch it was detected alongside (defaults to just
    this event) so the systemic-vs-isolated context has something to
    compare against. `order_index` (see order_lookup.build_order_index)
    supplies vendor/product/order-value detail for order-based anomalies —
    omit it to fall back to the generic, order-detail-free context.
    `historical_matches` (see historical_incidents.find_similar_incidents)
    supplies past-incident matches for human-reported events.
    """
    all_events = all_events if all_events is not None else [event]
    reference_date = reference_date or datetime.now()
    order_index = order_index or {}
    historical_matches = historical_matches or []

    result = _DIAGNOSIS_GRAPH.invoke(
        {
            "event": event,
            "all_events": all_events,
            "reference_date": reference_date,
            "order_index": order_index,
            "historical_matches": historical_matches,
            "context": {},
            "report": None,
        }
    )
    return {
        "event": event.model_dump(),
        "context": result["context"],
        "report": result["report"].model_dump(),
    }


def diagnose_all(
    events: list[DiscrepancyEvent],
    reference_date: datetime | None = None,
    order_index: dict[str, dict] | None = None,
) -> list[dict[str, Any]]:
    """Run every event in a detected batch through the diagnosis graph —
    the end-to-end wiring of detection -> shared event schema -> agent.
    Each event is diagnosed against the full batch for systemic-vs-isolated
    context.
    """
    reference_date = reference_date or datetime.now()
    return [diagnose_event(event, events, reference_date, order_index) for event in events]

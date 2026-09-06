"""
Dry run of the v2-gated sensor pipeline — sensor_detection_version_a.md
Section 1.5 wired together, but stopping *before* the diagnosis agent.
Purpose: prove the context bundle that would be handed to the LLM is
correct and sensible, by eye, before spending any API budget calling it.

Does NOT import llm_client, diagnosis.py, or anything that could make a
network call. This is deliberately a standalone script, not folded into
eval_diagnosis.py or demo_live_sim.py — those get built (and get to touch
the diagnosis agent for real) only once the bundles printed here have been
reviewed and approved.

What it does, per row in the sample:
  1. Computes the z-score/derived-feature deviations exactly as v1.5 did —
     unconditionally, on every row, regardless of what gates the flag now.
     This is the "which sensors are off, by how much" description — now via
     rank_all_deviations, which always returns the top-N columns by z-score
     magnitude even when none crossed their own threshold, so an ML-only
     catch still has real evidence to hand the diagnosis agent instead of
     an empty description (the gap found in the previous dry run).
  2. Asks the persisted v2 model (model_v2.pkl) whether the row is
     anomalous, using its own predict_proba + the 0.60 threshold from
     model_v2_meta.json. THIS decides `flagged` now, not the deviations.
  3. For rows the ML model flags: builds the exact context bundle
     gather_sensor_context() would hand the diagnosis agent, and prints it.
  4. Tallies ML-flagged vs. z-score-flagged counts on the same rows, so the
     new gate's behavior is visibly different (and better) from the old
     one, not identical or nonsensical — plus a count of how many ML-flagged
     rows still come back with an empty deviating_sensors list (should now
     be zero).

Usage (from backend/, with the venv active):
    python dry_run_pipeline.py
"""
from gather_context_sensor import gather_sensor_context
from ml_detector import load_dataset, split_dataset
from sensor_adapter import DEFAULT_K_PER_COLUMN, compute_baselines, load_ml_gate, process_row

# Reuses the same test split ml_detector.py/persist_model_v2.py already
# evaluated against — "the same rows used in earlier eval work" per the
# ask — so these examples are directly comparable to the numbers already
# reported, not a fresh, differently-distributed sample.
SAMPLE_SIZE = None  # None = full test split (2000 rows) — matches ml_detector.py's reported 72 ML-flagged rows
EXAMPLES_TO_PRINT = 3

# The two ML-only-catch rows that came back with an empty description in
# the previous dry run — explicitly re-shown this time (in addition to
# whatever the general picks logic below selects) so the fix's effect on
# these exact rows is directly visible, not just "some similar row."
MUST_SHOW_ENTITY_IDS = {"H30587", "L49195"}


def _print_context_bundle(index: int, row_result: dict, context: dict) -> None:
    print(f"\n{'=' * 70}")
    print(f"Example {index}: entity_id={row_result['entity_id']}  "
          f"ml_probability={row_result['ml_probability']:.3f}  "
          f"zscore_flagged={row_result['zscore_flagged']}")
    print("-" * 70)
    if not context["deviating_sensors"]:
        # Should be unreachable post-fix — printed loudly rather than
        # silently skipped, since it would mean the fix regressed.
        print("  !! REGRESSION: empty deviating_sensors on a flagged row !!")
    else:
        print("  Deviating sensors (ranked by |z-score|, top {}):".format(len(context["deviating_sensors"])))
        for dev in context["deviating_sensors"]:
            print(
                f"    - {dev['sensor']}: {dev['value']:.2f} "
                f"(baseline {dev['baseline_mean']:.2f} +/- {dev['baseline_std']:.2f}, "
                f"z={dev['z_score']:.2f}, {dev['direction']}) — {dev['note']}"
            )
    print(f"\n  Failure taxonomy attached: {list(context['failure_taxonomy'].keys())}")
    print("  Full taxonomy descriptions (as the agent would see them):")
    for code, info in context["failure_taxonomy"].items():
        print(f"    {code} ({info['name']}): {info['description']}")


def main() -> None:
    df = load_dataset()
    _, _, df_test, *_ = split_dataset(df)
    sample = df_test.head(SAMPLE_SIZE) if SAMPLE_SIZE else df_test

    baselines = compute_baselines(df)  # full-dataset baselines, same as every eval script
    ml_gate = load_ml_gate()

    results = [
        process_row(row, baselines, DEFAULT_K_PER_COLUMN, ml_gate=ml_gate)
        for row in sample.to_dict("records")
    ]

    ml_flagged = [r for r in results if r["flagged"]]
    zscore_flagged = [r for r in results if r["zscore_flagged"]]
    both = [r for r in results if r["flagged"] and r["zscore_flagged"]]
    only_ml = [r for r in results if r["flagged"] and not r["zscore_flagged"]]
    only_zscore = [r for r in results if r["zscore_flagged"] and not r["flagged"]]
    empty_description = [r for r in ml_flagged if not r["ranked_deviations"]]

    print(f"Sample: {len(results)} rows (head of the test split ml_detector.py already evaluated)")
    print(f"  ML-flagged:      {len(ml_flagged)}")
    print(f"  z-score-flagged: {len(zscore_flagged)}")
    print(f"  both agree:      {len(both)}")
    print(f"  ML only:         {len(only_ml)}  (ML caught something the old gate would have missed)")
    print(f"  z-score only:    {len(only_zscore)}  (old gate would have flagged, ML disagrees)")
    print(f"  ML-flagged rows with an EMPTY description: {len(empty_description)} / {len(ml_flagged)}"
          f"  (should be 0 post-fix)")

    if not ml_flagged:
        print("\nNo ML-flagged rows in this sample — nothing to print a context bundle for.")
        return

    # Pick a mix worth eyeballing: one where both gates agree (the
    # straightforward case), one where ML flagged but z-score found nothing
    # under the old threshold-only view (the honest edge case), plus the
    # two specific rows that came back empty last time — rather than just
    # the first N in row order.
    picks = []
    if both:
        picks.append(both[0])
    if only_ml:
        picks.append(only_ml[0])
    for r in ml_flagged:
        if r["entity_id"] in MUST_SHOW_ENTITY_IDS and r not in picks:
            picks.append(r)
    for r in ml_flagged:
        if len(picks) >= EXAMPLES_TO_PRINT and not (MUST_SHOW_ENTITY_IDS - {p["entity_id"] for p in picks}):
            break
        if r not in picks:
            picks.append(r)

    print(f"\nPrinting {len(picks)} example context bundle(s) — no LLM/diagnosis-agent call made.")
    for i, row_result in enumerate(picks, start=1):
        context = gather_sensor_context(row_result["entity_id"], row_result["ranked_deviations"])
        _print_context_bundle(i, row_result, context)


if __name__ == "__main__":
    main()

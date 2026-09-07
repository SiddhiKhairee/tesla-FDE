# Ground Truth Regeneration — 2026-09-07

## What was wrong

Final spot-checking before Day 6 found `ground_truth.json` had **zero `duplicate_entry`
examples** out of only 13 total events — too small a sample for any of the 4 anomaly types
to give a statistically meaningful eval number, and a direct violation of the "stop if any
type shows 0" rule.

**Root cause:** a full Odoo wipe-and-reseed after Day 2's original approved spot-check
produced a much smaller, differently-distributed dataset (13 events vs. whatever the
original run had — the original committed version, from before that reseed, did contain
real `duplicate_entry` examples, e.g. `P00539`/`P00540`). The `duplicate_entry` type was one
arm of a per-order 3-way `random.choice(["stuck", "delayed", "duplicate"])`, reached only 3
times in that smaller run — 0-for-3 on a 1-in-3 draw is ~30% likely by pure chance, not a
code defect. Nobody re-ran the "stop if any type shows 0" check after the reseed.

## The fix

- **`data-gen/anomalies.py`**: `inject_duplicate_entry()` unchanged — it was already correct.
- **`data-gen/generate.py`**: removed `duplicate_entry` from the per-order random 3-way
  choice (now `random.choice(["stuck", "delayed"])`, 2-way). Added a new
  `inject_duplicate_entries()` guaranteed-count pass, run once at the end of the simulated
  window over real, non-anomalous PO candidates collected during the run — same pattern
  `inject_quantity_mismatches()` already used. A full regeneration can no longer produce
  zero `duplicate_entry` examples regardless of random luck.
- **`data-gen/config.py`**: `SIMULATION_MONTHS` 3 → 8, `ANOMALY_RATE` 0.08 → 0.12 (sized via
  a dry-run check to comfortably clear ~10+ expected `stuck_order`/`delayed_delivery`
  examples even after typical live-Odoo skip/failure attrition), `QUANTITY_MISMATCH_COUNT`
  4 → 5 (the real ceiling — only 5 distinct product/location combos exist under the current
  entity model; going higher needs new entities, out of scope here), new
  `DUPLICATE_ENTRY_COUNT = 10`.

## Old vs. new ground truth

| anomaly_type | old (13 total) | new (56 total) |
|---|---|---|
| stuck_order | 8 | 28 |
| delayed_delivery | 1 | 13 |
| duplicate_entry | **0** | **10** |
| quantity_mismatch | 4 | 5 |

Spot-checked directly in Odoo (not just trusted from the JSON): one `duplicate_entry` pair
(P00244/P00311 — identical partner, date, and amount), one `stuck_order` (P00125's picking
still `assigned`, not `done`), one `delayed_delivery` (P00134, 14 days late), one
`quantity_mismatch` (PW3-ASSY @ Finished Goods, live on-hand matches the logged
post-injection value exactly).

## Two more things the re-run eval surfaced (not part of the original ask, found along the way)

**1. A real detection/eval bug, now fixed.** With real `duplicate_entry` ground truth for
the first time, the first eval run scored it 0%/0% — alarming, but investigation showed the
detector had actually found all 10 real pairs correctly; it just reported `entity_id`/
`duplicate_of` swapped relative to ground truth's convention, because the injected
duplicate shares its original's exact `date_order` and `detection.py`'s sort had no
tiebreak for same-timestamp orders. Fixed in `backend/detection.py`'s
`detect_duplicate_orders()`: sort by `(date_order, id)` instead of `date_order` alone, so
the lower-id (earlier-created, true original) record deterministically wins `entity_id`.
Covered by a new test in `backend/tests/test_detection.py`.

**2. Self-inflicted data contamination, cleaned up.** An earlier `generate.py` run was
manually killed mid-flight (~90 seconds in) before a proper reset; the ~35 orders it had
already created survived `reset_data.py`'s cleanup because their pickings had already
reached Odoo's "done" state, which `reset_data.py` cannot cancel/delete (a real, pre-existing
limitation of that script, not new). Because `generate.py` uses a fixed random seed, the
successful second run replayed the identical early-schedule sequence, creating near-duplicate
twins of these orphaned records — which then showed up as `duplicate_entry` false positives
once the eval actually had real data to compare against. Fixed by shifting the 35 orphaned
POs' `date_order` to 2016 (outside both the 2-day collision window and the 8-month
simulation window) — a pure data correction, no deletion, no auth/volume changes.

## Eval results: old vs. new

**Old** (`eval_results.json`, against the 13-event ground truth):

| anomaly_type | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|
| stuck_order | 7 | 0 | 1 | 100.0% | 87.5% |
| delayed_delivery | 1 | 0 | 0 | 100.0% | 100.0% |
| duplicate_entry | 0 | 0 | 0 | n/a (no ground truth to test) | n/a |
| quantity_mismatch | 4 | 0 | 0 | 100.0% | 100.0% |
| **OVERALL** | 12 | 0 | 1 | **100.0%** | **92.3%** |

**New** (against the 56-event ground truth, with the tiebreak fix and contamination cleanup
in place):

| anomaly_type | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|
| stuck_order | 28 | 0 | 0 | 100.0% | 100.0% |
| delayed_delivery | 13 | 0 | 0 | 100.0% | 100.0% |
| duplicate_entry | 10 | 1 | 0 | 90.9% | 100.0% |
| quantity_mismatch | 5 | 0 | 0 | 100.0% | 100.0% |
| **OVERALL** | 56 | 1 | 0 | **98.2%** | **100.0%** |

**The one remaining false positive, precisely explained (checked directly in Odoo, not
assumed):** `P00272` (real, from today's regeneration — `create_date` 2026-09-07, part of
the actual 56-event dataset) is flagged as a duplicate of `P00046`. Both order 130 units of
`BMS-100` from `CircuitWorks Electronics`, 2 days apart (2026-07-28 vs. 2026-07-30), same
$9,717.50 total — to the detector, indistinguishable from a real duplicate.

But `P00046` is *not* part of today's ground truth either — its `create_date` is
`2026-09-03 17:55:25`, predating today's regeneration entirely. It's leftover cruft from an
*earlier* session (same vintage as `P00020` above), still sitting in Odoo because
`reset_data.py` can't delete already-"done" records, that hadn't been identified as
contamination because the earlier cleanup only searched for leftovers from *today's* killed
run specifically.

So this isn't "two real orders colliding by chance at higher volume" (as first reported) —
it's a genuine new order (`P00272`) coincidentally matching an old, pre-existing piece of
contamination (`P00046`) on vendor + product + quantity within the 2-day window. The
underlying mechanism (only 3 suppliers, a 20–200 quantity range, so exact-quantity
collisions become more likely at higher order volume) is still real and still worth noting
as a detector limitation — it just happened to surface via a stale record rather than two
fresh ones this time. Left as-is, undocumented-but-understood, same spirit as the
TWF/RNF/HDF limitations already accepted elsewhere in this project — fixing it would mean
either more contamination archaeology (there may be other old leftovers like this one not
yet found) or changing the detector's matching heuristic, both out of scope for this task.

## Not done (explicitly deferred)

A full Postgres volume wipe + `setup_entities.py` reseed was considered as the cleanest way
to eliminate all historical contamination at once, but was ruled out: it would destroy
Odoo's entire user database, invalidating the `ODOO_API_KEY` used by both `backend/.env`
and `data-gen/.env` project-wide, with no scripted way to regenerate one (Odoo API key
generation is a manual, interactive step). The targeted contamination cleanup above was
judged sufficient and lower-risk.
